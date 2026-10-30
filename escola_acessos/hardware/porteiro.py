"""Processo "porteiro": corre no Raspberry Pi SEM ecrã nem browser.

  câmara → reconhecimento facial → regista entrada/saída → display + LEDs + buzzer + trinco

Usa os mesmos serviços do site (flask_app/services), por isso as regras são as mesmas.
Corre em paralelo com o site (gunicorn); partilham a base de dados SQLite (modo WAL).

  python -m hardware.porteiro                # usa HARDWARE_MODO do ambiente
  python -m hardware.porteiro --mock         # hardware simulado (PC)
  python -m hardware.porteiro --simular      # sem câmara: escreva nº de processo no terminal
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
import time

from flask_app import create_app, utils
from flask_app.db import get_db
from flask_app.services import acesso_service, notification_service, presenca_service
from . import get_hardware
from .camera import Camera

log = logging.getLogger("porteiro")

MANUTENCAO_CADA_S = 300   # recalcula presenças a cada 5 minutos


class Porteiro:
    def __init__(self, app, hw, camera=None, dormir=time.sleep, agora=time.monotonic):
        self.app, self.hw, self.camera = app, hw, camera
        self._dormir, self._agora = dormir, agora
        self.cfg = app.config
        self._parar = False
        self._chave_anterior = False
        self._ultima_manutencao = -MANUTENCAO_CADA_S
        self._ultimo_ecra_repouso = None
        self._falhas_camara = 0

    # ---------------------------- ciclo de vida ----------------------------
    def parar(self, *_):
        self._parar = True

    def _emails_em_segundo_plano(self, cada_s: int = 60):
        """Envia os emails aos encarregados numa thread à parte: um SMTP lento nunca pode atrasar a porta."""
        def laco():
            while not self._parar:
                try:
                    with self.app.app_context():
                        r = notification_service.enviar_pendentes()
                    if r.get("enviados") or r.get("erros") or r.get("erro"):
                        log.info("Emails: %s", r)
                except Exception:  # noqa: BLE001
                    log.exception("Falha no envio de emails")
                for _ in range(cada_s):
                    if self._parar:
                        return
                    time.sleep(1)
        if self.cfg.get("SMTP_HOST"):
            threading.Thread(target=laco, name="emails", daemon=True).start()
            log.info("Envio automático de emails aos encarregados ativo (SMTP %s).", self.cfg["SMTP_HOST"])
        else:
            log.info("SMTP não configurado: os emails aos encarregados ficam na fila (painel → Emails aos EE).")

    def executar(self):
        signal.signal(signal.SIGTERM, self.parar)
        signal.signal(signal.SIGINT, self.parar)
        self._emails_em_segundo_plano()
        if self.camera and not self.camera.abrir():
            self.hw.leds(False, True)
            self.hw.mostrar("Erro de camara", "Ver ligacao USB")
        else:
            self.hw.pronto()
        try:
            while not self._parar:
                self.passo()
                self._dormir(self.cfg["INTERVALO_FRAME_S"])
        finally:
            log.info("A terminar; a trancar a porta e a libertar o hardware.")
            self.hw.fechar()
            if self.camera:
                self.camera.fechar()

    # ---------------------------- um passo do ciclo ----------------------------
    def passo(self):
        self._tratar_chave()
        self._manutencao()
        if self.camera is None:
            return
        rgb = self.camera.ler_rgb()
        if rgb is None:                      # câmara desligada/avariada: mostra erro e tenta reabrir
            self._falhas_camara += 1
            self.hw.leds(False, True)
            self.hw.mostrar("Erro de camara", "A tentar de novo")
            if self._falhas_camara % 10 == 0:
                log.warning("Câmara sem imagem há %d tentativas; a reabrir.", self._falhas_camara)
                self.camera.abrir()
            return
        if self._falhas_camara:              # recuperou
            self._falhas_camara = 0
            self._ecra_repouso(forcar=True)
        self.processar_frame(rgb)

    def processar_frame(self, rgb):
        try:
            with self.app.app_context():
                res = acesso_service.processar_imagem(rgb, origem="porteiro", scale=self.cfg["FACE_SCALE"])
        except Exception:  # noqa: BLE001
            log.exception("Erro ao processar frame")
            self.hw.leds(False, True)
            self.hw.mostrar("Erro do sistema", "Ver registos")
            return None
        if res.estado == "sem_rosto":
            self._ecra_repouso()
            return res
        self.apresentar(res)
        return res

    def apresentar(self, res):
        """Mostra o resultado, mantém o trinco aberto o tempo certo e volta ao repouso."""
        self.hw.sinalizar(res)
        espera = self.cfg["MOSTRAR_RESULTADO_S"]
        if res.abrir:
            espera = max(espera, self.cfg["TRINCO_SEGUNDOS"])
        self._dormir(espera)
        if not self.hw.chave_ativa():       # com a chave em "porta livre" o trinco fica aberto
            self.hw.trinco(False)
        self._ultimo_ecra_repouso = None
        self._ecra_repouso(forcar=True)
        if self.camera:
            self.camera.descartar()

    # ---------------------------- chave ----------------------------
    def _tratar_chave(self):
        ativa = self.hw.chave_ativa()
        if ativa == self._chave_anterior:
            return
        self._chave_anterior = ativa
        with self.app.app_context():
            acesso_service.registar_evento("chave_ligada" if ativa else "chave_desligada", None, "porta livre")
        if ativa:
            self.hw.trinco(True)
            self.hw.leds(True, False)
            self.hw.mostrar("PORTA LIVRE", "Modo manual")
        else:
            self.hw.trinco(False)
            self._ultimo_ecra_repouso = None
            self._ecra_repouso(forcar=True)

    # ---------------------------- repouso e manutenção ----------------------------
    def _ecra_repouso(self, forcar=False):
        if self._chave_anterior:
            return
        agora = utils.now()
        texto = (agora.strftime("%H:%M  %d/%m"), "Aproxime-se")
        if forcar or texto != self._ultimo_ecra_repouso:
            self._ultimo_ecra_repouso = texto
            self.hw.pronto(*texto)

    def _manutencao(self):
        if self._agora() - self._ultima_manutencao < MANUTENCAO_CADA_S:
            return
        self._ultima_manutencao = self._agora()
        try:
            with self.app.app_context():
                st = presenca_service.processar_dia(utils.today())
            log.info("Presenças recalculadas: %s", st)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao recalcular presenças")


# ---------------------------- modo simulação (sem câmara) ----------------------------
def simular(app, hw):
    """Escreva o nº de processo de um aluno para simular o reconhecimento.
    'chave' alterna o switch com chave; 'sair' termina."""
    p = Porteiro(app, hw, camera=None, dormir=lambda s: time.sleep(min(s, 0.3)))
    hw.pronto()
    print("\nSimulação do porteiro. Escreva o nº de processo, 'chave' ou 'sair'.\n")
    while True:
        try:
            linha = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if linha in ("sair", "exit", "q"):
            break
        if linha == "chave":
            hw.chave = not getattr(hw, "chave", False)
            p._tratar_chave()
            continue
        if not linha:
            continue
        with app.app_context():
            al = get_db().execute("SELECT id FROM alunos WHERE numero_processo = ?", (linha,)).fetchone()
            res = acesso_service.registar_aluno(al["id"], origem="simulado") if al else \
                acesso_service.ResultadoAcesso("nao_reconhecido", linha1="Nao reconhecido", linha2="Tente de novo")
        p.apresentar(res)
    hw.fechar()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Porteiro da escola (câmara + hardware).")
    ap.add_argument("--mock", action="store_true", help="hardware simulado")
    ap.add_argument("--real", action="store_true", help="hardware real (Raspberry Pi)")
    ap.add_argument("--simular", action="store_true", help="sem câmara: escrever nº de processo")
    ap.add_argument("--camara", help="índice da webcam, ficheiro de vídeo ou imagem (por defeito CAMARA_INDEX)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = create_app()
    modo = "real" if args.real else "mock" if args.mock or args.simular else None
    hw = get_hardware(app.config, modo)
    if args.simular:
        return simular(app, hw)

    fonte = args.camara if args.camara is not None else app.config["CAMARA_INDEX"]
    if isinstance(fonte, str) and fonte.isdigit():
        fonte = int(fonte)
    cam = Camera(fonte, app.config["CAMARA_LARGURA"], app.config["CAMARA_ALTURA"])
    Porteiro(app, hw, cam).executar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
