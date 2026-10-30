"""O porteiro com hardware simulado: câmara → reconhecimento → display/LEDs/buzzer/trinco."""
from flask_app import utils
from hardware.mock import MockHardware
from hardware.porteiro import Porteiro
from .helpers import AppTestCase, imagem, SEGUNDA


class TestPorteiro(AppTestCase):
    def setUp(self):
        super().setUp()
        self.turma = self.mk_turma()
        self.mk_horario(self.turma, "09:00", "17:30")
        self.aluno = self.mk_aluno(1, self.turma)
        self.add_face(self.aluno, 60)
        self.hw = MockHardware(verbose=False)
        self.p = Porteiro(self.app, self.hw, camera=None, dormir=lambda s: None)

    def _eventos(self, tipo):
        return [e for e in self.hw.eventos if e[0] == tipo]

    def test_aluno_reconhecido_abre_porta_e_mostra_nome(self):
        self.p.processar_frame(imagem(60))
        self.assertIn(("trinco", True), self.hw.eventos)
        self.assertEqual(self.hw.estado_trinco, False)              # voltou a fechar no fim
        self.assertIn(("leds", True, False), self.hw.eventos)       # LED verde
        self.assertIn(("beep", "aviso"), self.hw.eventos)           # 09:12 → atraso → 2 beeps
        mostrados = [e[1] for e in self._eventos("display")]
        self.assertTrue(any(t.startswith("Ola Aluno") for t in mostrados))

    def test_desconhecido_nao_abre_e_acende_led_vermelho(self):
        self.p.processar_frame(imagem(230))
        self.assertNotIn(("trinco", True), self.hw.eventos)
        self.assertIn(("leds", False, True), self.hw.eventos)
        self.assertIn(("beep", "erro"), self.hw.eventos)
        self.assertIn("Nao reconhecido", [e[1] for e in self._eventos("display")])

    def test_sem_rosto_nao_faz_nada(self):
        self.p.processar_frame(imagem(0))
        self.assertNotIn(("trinco", True), self.hw.eventos)
        self.assertEqual(self._eventos("beep"), [])

    def test_chave_mantem_porta_aberta_e_regista_evento(self):
        self.hw.chave = True
        self.p._tratar_chave()
        self.assertTrue(self.hw.estado_trinco)
        self.assertEqual(self.hw.display[0], "PORTA LIVRE")
        self.hw.chave = False
        self.p._tratar_chave()
        self.assertFalse(self.hw.estado_trinco)
        tipos = [r["tipo"] for r in self.db.execute("SELECT tipo FROM eventos_porta")]
        self.assertEqual(tipos, ["chave_ligada", "chave_desligada"])

    def test_com_chave_ativa_o_trinco_nao_fecha_apos_reconhecer(self):
        self.hw.chave = True
        self.p._tratar_chave()
        self.p.processar_frame(imagem(60))
        self.assertTrue(self.hw.estado_trinco)

    def test_texto_cabe_no_display_sem_acentos(self):
        self.db.execute("UPDATE alunos SET nome_completo = 'Gonçalo Ângelo Ferreira' WHERE id = ?", (self.aluno,))
        self.db.commit()
        self.p.processar_frame(imagem(60))
        for e in self._eventos("display"):
            for linha in e[1:]:
                self.assertLessEqual(len(linha), 16)
                self.assertTrue(linha.isascii(), linha)

    def test_saida_antecipada_avisa_com_dois_beeps(self):
        self.p.processar_frame(imagem(60))                           # entrada 09:12
        self.agora = SEGUNDA.replace(hour=13)
        self.hw.eventos.clear()
        self.p.processar_frame(imagem(60))                           # sai às 13:00 (antes das 17:30)
        self.assertIn("Saida antecipada", [e[2] for e in self._eventos("display")])
        self.assertIn(("beep", "aviso"), self.hw.eventos)

    def test_saida_nao_abre_se_configurado(self):
        self.app.config["ABRIR_NA_SAIDA"] = False
        self.p.processar_frame(imagem(60))                           # entrada
        self.agora = SEGUNDA.replace(hour=17, minute=35)
        self.hw.eventos.clear()
        self.p.processar_frame(imagem(60))                           # saída
        self.assertNotIn(("trinco", True), self.hw.eventos)

    def test_erro_inesperado_nao_derruba_o_porteiro_nem_abre_a_porta(self):
        from flask_app.services import face_service
        class Avaria:
            def encode(self, *a, **k): raise RuntimeError("avaria")
        face_service.set_backend(Avaria())
        self.p.processar_frame(imagem(60))
        self.assertNotIn(("trinco", True), self.hw.eventos)
        self.assertEqual(self.hw.display[0], "Erro do sistema")

    def test_trinco_fail_safe_inverte_o_rele(self):
        """Na versão real, 'energiza_para_trancar' liga o relé para TRANCAR (sem corrente = aberto)."""
        from hardware.real import RealHardware
        import sys, types
        ligados = []
        class Dev:
            def __init__(s, *a, **k): s.value = 0
            def on(s): ligados.append(("on", s)); s.value = 1
            def off(s): ligados.append(("off", s)); s.value = 0
            def close(s): pass
            def beep(s, *a, **k): pass
            is_pressed = False
        gz = types.ModuleType("gpiozero")
        for n in ("LED", "Buzzer", "OutputDevice", "Button"):
            setattr(gz, n, Dev)
        sys.modules["gpiozero"] = gz
        try:
            cfg = dict(self.app.config); cfg.update(DISPLAY_TIPO="none", TRINCO_MODO="energiza_para_trancar")
            hw = RealHardware(cfg)
            hw.trinco(True)                                  # abrir → relé desligado
            self.assertEqual(hw._rele.value, 0)
            hw.trinco(False)                                 # trancar → relé ligado
            self.assertEqual(hw._rele.value, 1)
        finally:
            sys.modules.pop("gpiozero", None)


    def test_camara_desligada_mostra_erro_tenta_reabrir_e_recupera(self):
        class CamAvariada:
            def __init__(s): s.abertas, s.avaria = 0, True
            def abrir(s): s.abertas += 1; s.avaria = False if s.abertas >= 1 else True; return True
            def ler_rgb(s): return None if s.avaria else imagem(0)
            def descartar(s, n=3): pass
        cam = CamAvariada()
        p = Porteiro(self.app, self.hw, camera=cam, dormir=lambda s: None)
        for _ in range(9):
            p.passo()
        self.assertEqual(self.hw.display[0], "Erro de camara")
        self.assertEqual(cam.abertas, 0)
        p.passo()                                   # 10.ª falha → reabre
        self.assertEqual(cam.abertas, 1)
        p.passo()                                   # já devolve imagem → volta ao repouso
        self.assertNotEqual(self.hw.display[0], "Erro de camara")
        self.assertEqual(self.hw.estado_leds, (False, False))
