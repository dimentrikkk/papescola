import io
from PIL import Image

from flask_app.services import horario_service, notification_service, presenca_service
from .helpers import AppTestCase, SEGUNDA


class TestSeguranca(AppTestCase):
    def setUp(self):
        super().setUp()
        self.prof = self.mk_prof()
        self.turma = self.mk_turma("T1", self.prof)
        self.a1 = self.mk_aluno(1, self.turma)
        self.a2 = self.mk_aluno(2, self.turma)

    def test_rotas_exigem_login(self):
        for url in ("/admin/dashboard", "/professor/dashboard", "/aluno/dashboard", "/admin/alunos"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302, url)
            self.assertIn("/login", r.headers["Location"])

    def test_separacao_de_papeis(self):
        self.login("a1@escola.pt", "Aluno1234")
        for url in ("/admin/dashboard", "/admin/alunos", "/professor/dashboard"):
            self.assertEqual(self.client.get(url).status_code, 403, url)
        self.assertEqual(self.client.get("/aluno/dashboard").status_code, 200)

    def test_professor_nao_acede_ao_admin(self):
        self.login("prof@escola.pt", "Professor123")
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 403)
        self.assertEqual(self.client.get("/professor/dashboard").status_code, 200)

    def test_post_sem_csrf_e_rejeitado(self):
        self.login("admin@escola.pt", "Admin12345")  # must_change=1 → ver abaixo; usa sessão com csrf
        with self.client.session_transaction() as s:
            s["must_change"] = False
        r = self.client.post("/admin/alunos/1/apagar", data={})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM alunos").fetchone()[0], 2)

    def test_login_invalido_e_bloqueio_apos_falhas(self):
        for _ in range(5):
            self.assertEqual(self.login("a1@escola.pt", "errada").status_code, 401)
        r = self.login("a1@escola.pt", "Aluno1234")          # mesmo com a password certa
        self.assertEqual(r.status_code, 429)

    def test_primeiro_login_obriga_a_mudar_password(self):
        r = self.login("admin@escola.pt", "Admin12345")
        self.assertIn("/conta", r.headers["Location"])
        self.assertIn("/conta", self.client.get("/admin/dashboard").headers["Location"])
        r = self.post("/conta", {"atual": "Admin12345", "nova": "NovaPass123", "confirma": "NovaPass123"})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get("/admin/dashboard").status_code, 200)

    def test_password_fraca_e_rejeitada(self):
        self.login("a1@escola.pt", "Aluno1234")
        r = self.post("/conta", {"atual": "Aluno1234", "nova": "12345678", "confirma": "12345678"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("letras e números".encode(), r.data)

    def test_passwords_guardadas_com_hash(self):
        h = self.db.execute("SELECT password_hash FROM alunos WHERE id = ?", (self.a1,)).fetchone()[0]
        self.assertNotIn("Aluno1234", h)

    def test_fotos_so_acessiveis_ao_dono_ou_staff(self):
        import os
        from flask import current_app
        os.makedirs(current_app.config["UPLOAD_DIR"], exist_ok=True)
        buf = io.BytesIO(); Image.new("RGB", (20, 20), "red").save(buf, "JPEG")
        for aid in (self.a1, self.a2):
            nome = f"avatar_{aid}_x.jpg"
            with open(os.path.join(current_app.config["UPLOAD_DIR"], nome), "wb") as fh:
                fh.write(buf.getvalue())
            self.db.execute("UPDATE alunos SET foto_perfil=? WHERE id=?", (nome, aid))
        self.db.commit()
        self.login("a1@escola.pt", "Aluno1234")
        self.assertEqual(self.client.get("/ficheiros/avatar_1_x.jpg").status_code, 200)   # a sua
        self.assertEqual(self.client.get("/ficheiros/avatar_2_x.jpg").status_code, 403)   # de outro aluno
        self.assertEqual(self.client.get("/ficheiros/../config.py").status_code, 404)
        self.assertEqual(self.client.get("/ficheiros/qualquer.txt").status_code, 404)

    def test_kiosk_web_pode_ser_desligado(self):
        self.app.config["KIOSK_WEB_ENABLED"] = False
        self.assertEqual(self.client.get("/kiosk/").status_code, 404)


class TestPaginas(AppTestCase):
    """Fumo: todas as páginas abrem sem erro com dados reais."""
    def setUp(self):
        super().setUp()
        self.prof = self.mk_prof()
        self.turma = self.mk_turma("T1", self.prof)
        self.mk_horario(self.turma, "09:00", "17:30")
        self.aluno = self.mk_aluno(1, self.turma)
        from flask_app.services import acesso_service
        acesso_service.registar_aluno(self.aluno)             # 09:12 → atraso
        self.agora = SEGUNDA.replace(hour=13)
        presenca_service.processar_dia(SEGUNDA.date())
        self.db.execute("UPDATE utilizadores SET must_change_password = 0")
        self.db.commit()

    def _admin(self):
        self.login("admin@escola.pt", "Admin12345")
        with self.client.session_transaction() as s:
            s["must_change"] = False

    def _ok(self, urls):
        for u in urls:
            r = self.client.get(u)
            self.assertEqual(r.status_code, 200, f"{u} → {r.status_code}")

    def test_paginas_admin(self):
        self._admin()
        self._ok(["/admin/dashboard", "/admin/alunos", "/admin/alunos/novo", f"/admin/alunos/{self.aluno}",
                  f"/admin/alunos/{self.aluno}/rosto", "/admin/turmas", "/admin/professores",
                  f"/admin/horarios?turma_id={self.turma}", "/admin/horarios", "/admin/acessos?data=2026-10-26",
                  f"/admin/presencas?data=2026-10-26&turma_id={self.turma}", "/admin/presencas",
                  "/admin/justificacoes", "/admin/eventos", "/admin/estatisticas", "/admin/comunicacoes", "/admin/notificacoes",
                  "/admin/exportar/presencas.csv?de=2026-10-01&ate=2026-10-31", "/kiosk/"])

    def test_paginas_professor(self):
        self.login("prof@escola.pt", "Professor123")
        self._ok(["/professor/dashboard", f"/professor/turma/{self.turma}?data=2026-10-26", f"/professor/turma/{self.turma}", "/professor/notificacoes"])

    def test_paginas_aluno(self):
        self.login("a1@escola.pt", "Aluno1234")
        self._ok(["/aluno/dashboard", "/aluno/horario", "/aluno/assiduidade", "/aluno/assiduidade?mes=2026-10", "/aluno/assiduidade?mes=lixo",
                  "/aluno/acessos", "/aluno/justificacoes", "/aluno/privacidade", "/aluno/notificacoes"])

    def test_logo_da_escola_aparece_nas_paginas(self):
        self.assertIn(b"logo-profitecla.svg", self.client.get("/login").data)
        self._admin()
        self.assertIn(b"logo-profitecla.svg", self.client.get("/admin/dashboard").data)
        self.assertEqual(self.client.get("/static/logo-profitecla.svg").status_code, 200)

    # ---- horários (só entrada/saída) ----
    def test_admin_guarda_horario_so_com_entrada_e_saida(self):
        self._admin()
        dados = {"turma_id": self.turma, "ativo_0": "on", "entrada_0": "08:30", "saida_0": "16:00",
                 "ativo_2": "on", "entrada_2": "10:00", "saida_2": "13:00"}
        r = self.post("/admin/horarios", dados)
        self.assertEqual(r.status_code, 302)
        h = horario_service.horario_turma(self.turma)
        self.assertEqual({d: (v["hora_entrada"], v["hora_saida"]) for d, v in h.items()}, {0: ("08:30", "16:00"), 2: ("10:00", "13:00")})

    def test_horario_invalido_nao_grava(self):
        self._admin()
        antes = horario_service.horario_turma(self.turma)
        self.post("/admin/horarios", {"turma_id": self.turma, "ativo_0": "on", "entrada_0": "17:00", "saida_0": "09:00"})
        self.assertEqual(horario_service.horario_turma(self.turma), antes)

    def test_horario_pode_ser_aplicado_a_todas_as_turmas(self):
        outra = self.mk_turma("T2")
        self._admin()
        self.post("/admin/horarios", {"turma_id": self.turma, "ativo_1": "on", "entrada_1": "09:15", "saida_1": "15:45", "aplicar_todas": "on"})
        self.assertEqual(horario_service.horario_turma(outra)[1]["hora_entrada"], "09:15")

    # ---- professor / diretor de turma ----
    def test_professor_so_ve_as_suas_turmas(self):
        outra = self.mk_turma("T2")
        self.login("prof@escola.pt", "Professor123")
        self.assertEqual(self.client.get(f"/professor/turma/{outra}").status_code, 403)
        self.assertEqual(self.client.get("/professor/turma/9999").status_code, 404)

    def test_professor_corrige_presenca_do_seu_aluno(self):
        self.login("prof@escola.pt", "Professor123")
        r = self.post(f"/professor/turma/{self.turma}", {"data": "2026-10-26", "aluno_id": self.aluno, "estado": "presente", "nota": "veio"})
        self.assertEqual(r.status_code, 302)
        p = self.db.execute("SELECT estado, origem FROM presencas WHERE aluno_id = ?", (self.aluno,)).fetchone()
        self.assertEqual((p["estado"], p["origem"]), ("presente", "manual"))

    def test_correcao_sem_escolher_estado_nao_altera_nada(self):
        antes = dict(self.db.execute("SELECT * FROM presencas").fetchone())
        self.login("prof@escola.pt", "Professor123")
        self.post(f"/professor/turma/{self.turma}", {"data": "2026-10-26", "aluno_id": self.aluno, "estado": ""})
        self.assertEqual(dict(self.db.execute("SELECT * FROM presencas").fetchone()), antes)

    def test_professor_nao_corrige_aluno_de_outra_turma(self):
        outra = self.mk_turma("T2")
        intruso = self.mk_aluno(9, outra)
        self.login("prof@escola.pt", "Professor123")
        r = self.post(f"/professor/turma/{self.turma}", {"data": "2026-10-26", "aluno_id": intruso, "estado": "presente"})
        self.assertEqual(r.status_code, 403)

    def test_admin_corrige_presenca(self):
        self._admin()
        self.post("/admin/presencas/definir", {"data": "2026-10-26", "turma_id": self.turma, "aluno_id": self.aluno, "estado": "falta_justificada"})
        self.assertEqual(self.db.execute("SELECT estado FROM presencas").fetchone()[0], "falta_justificada")

    def test_csv_neutraliza_formulas(self):
        self.db.execute("UPDATE alunos SET nome_completo = '=HYPERLINK(\"x\")' WHERE id = ?", (self.aluno,))
        self.db.commit()
        self._admin()
        body = self.client.get("/admin/exportar/presencas.csv?de=2026-10-01&ate=2026-10-31").data.decode("utf-8")
        self.assertIn("'=HYPERLINK", body)

    def test_fluxo_justificacao_completo(self):
        self.agora = SEGUNDA.replace(hour=13)
        self.db.execute("UPDATE presencas SET estado='falta', hora_entrada=NULL, atraso_minutos=0")
        self.db.commit()
        self.login("a1@escola.pt", "Aluno1234")
        r = self.post("/aluno/justificacoes", {"data_inicio": "2026-10-26", "data_fim": "2026-10-26", "motivo": "Consulta médica"})
        self.assertEqual(r.status_code, 302)
        jid = self.db.execute("SELECT id FROM justificacoes").fetchone()[0]
        self.client.get("/logout")
        self._admin()
        self.post("/admin/justificacoes", {"id": jid, "decisao": "aprovado", "resposta": "ok"})
        self.assertEqual(self.db.execute("SELECT estado FROM justificacoes").fetchone()[0], "aprovado")
        self.assertEqual(self.db.execute("SELECT estado FROM presencas").fetchone()[0], "falta_justificada")

    def test_comunicacoes_sem_smtp_mantem_fila_e_reenvia_erros(self):
        self.db.execute("UPDATE outbox_email SET estado = 'erro', erro = 'x'")
        self.db.commit()
        self._admin()
        self.post("/admin/comunicacoes", {"acao": "reenviar"})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox_email WHERE estado = 'pendente'").fetchone()[0], 1)
        self.post("/admin/comunicacoes", {})
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM outbox_email WHERE estado = 'enviado'").fetchone()[0], 0)

    def test_envio_smtp_reserva_o_email_e_nao_duplica(self):
        import smtplib
        from unittest import mock
        self.app.config.update(SMTP_HOST="smtp.teste", SMTP_USER=None)
        enviados = []
        class Falso:
            def __init__(s, *a, **k): pass
            def starttls(s): pass
            def send_message(s, m): enviados.append(m["To"])
            def quit(s): pass
        with mock.patch.object(smtplib, "SMTP", Falso):
            r1 = notification_service.enviar_pendentes()
            r2 = notification_service.enviar_pendentes()
        self.assertEqual((r1["enviados"], r2["enviados"], enviados), (1, 0, ["enc@exemplo.pt"]))
