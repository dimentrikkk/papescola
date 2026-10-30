import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from flask_app import utils
from flask_app.services import acesso_service, comunicacao_service, horario_service, notification_service, presenca_service
from flask_app.services.presenca_service import avaliar_dia
from .helpers import AppTestCase, SEGUNDA

D = date(2026, 10, 26)           # segunda-feira
PE, PS = datetime(2026, 10, 26, 9, 0), datetime(2026, 10, 26, 17, 30)


def dt(h, m=0):
    return datetime(2026, 10, 26, h, m)


class TestAvaliarDia(unittest.TestCase):
    """Regra pura: presente / atraso / falta a partir da 1.ª entrada e da hora prevista."""
    def av(self, ent, sai=None, agora=dt(18)):
        return avaliar_dia(ent, sai, PE, PS, agora, tol_min=5, falta_apos_min=30, saida_tol_min=5)

    def test_presente_antes_da_hora(self):
        self.assertEqual(self.av(dt(8, 40))["estado"], "presente")

    def test_presente_dentro_da_tolerancia(self):
        self.assertEqual(self.av(dt(9, 5))["estado"], "presente")

    def test_atraso_com_minutos(self):
        r = self.av(dt(9, 20))
        self.assertEqual((r["estado"], r["atraso"]), ("atraso", 20))

    def test_ainda_cedo_para_dar_falta(self):
        self.assertIsNone(self.av(None, agora=dt(9, 29)))

    def test_falta_sem_entrada_passado_o_prazo(self):
        self.assertEqual(self.av(None, agora=dt(9, 30))["estado"], "falta")

    def test_falta_se_so_apareceu_depois_do_fim(self):
        self.assertEqual(self.av(dt(17, 45))["estado"], "falta")

    def test_saida_antecipada(self):
        r = self.av(dt(8, 50), dt(15, 30))
        self.assertEqual(r["saida_antecipada"], 120)

    def test_saida_dentro_da_tolerancia_nao_conta(self):
        self.assertEqual(self.av(dt(8, 50), dt(17, 27))["saida_antecipada"], 0)


class TestFluxoPresencas(AppTestCase):
    def setUp(self):
        super().setUp()
        self.prof = self.mk_prof()
        self.turma = self.mk_turma("T1", diretor=self.prof)
        self.mk_horario(self.turma, "09:00", "17:30")
        self.aluno = self.mk_aluno(1, self.turma)

    def emails(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM outbox_email ORDER BY id")]

    def presenca(self, d=D):
        return self.db.execute("SELECT * FROM presencas WHERE aluno_id = ? AND data = ?", (self.aluno, d.isoformat())).fetchone()

    # ---- entrada ----
    def test_atraso_cria_presenca_na_hora_e_avisa_o_ee(self):
        r = acesso_service.registar_aluno(self.aluno)                 # 09:12 → 12 min
        self.assertEqual((r.estado, r.tipo, r.atraso_min, r.abrir), ("aceite", "entrada", 12, True))
        self.assertIn("Atraso 12", r.linha2)
        p = self.presenca()
        self.assertEqual((p["estado"], p["atraso_minutos"], p["hora_entrada"]), ("atraso", 12, "09:12"))
        mails = self.emails()
        self.assertEqual(len(mails), 1)
        self.assertEqual(mails[0]["destinatario"], "enc@exemplo.pt")
        self.assertIn("Atraso", mails[0]["assunto"])
        self.assertIn("12 minuto", mails[0]["corpo"])
        self.assertIn("09:00", mails[0]["corpo"])
        self.assertEqual(notification_service.unread_count("aluno", self.aluno), 1)

    def test_entrada_a_horas_e_presente_sem_emails(self):
        self.agora = SEGUNDA.replace(hour=8, minute=55)
        acesso_service.registar_aluno(self.aluno)
        self.assertEqual(self.presenca()["estado"], "presente")
        self.assertEqual(self.emails(), [])

    def test_so_a_1_entrada_do_dia_conta(self):
        acesso_service.registar_aluno(self.aluno)                     # 09:12 (atraso)
        self.agora = SEGUNDA.replace(hour=12, minute=0)
        acesso_service.registar_aluno(self.aluno)                     # saída (almoço)
        self.agora = SEGUNDA.replace(hour=13, minute=0)
        r = acesso_service.registar_aluno(self.aluno)                 # reentrada
        self.assertEqual((r.tipo, r.atraso_min), ("entrada", 0))
        p = self.presenca()
        self.assertEqual((p["estado"], p["hora_entrada"], p["hora_saida"]), ("atraso", "09:12", None))   # ainda dentro

    def test_cooldown_evita_alternar_entrada_saida(self):
        acesso_service.registar_aluno(self.aluno)
        self.agora = SEGUNDA.replace(second=10)
        self.assertEqual(acesso_service.registar_aluno(self.aluno).estado, "repetido")
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM acessos").fetchone()[0], 1)

    def test_nao_ha_emails_repetidos_ao_recalcular(self):
        acesso_service.registar_aluno(self.aluno)
        for _ in range(3):
            presenca_service.processar_dia(D)
        self.assertEqual(len(self.emails()), 1)

    def test_sem_email_do_ee_nao_enfileira_mas_avisa_o_aluno(self):
        self.db.execute("UPDATE alunos SET encarregado_email = NULL")
        self.db.commit()
        acesso_service.registar_aluno(self.aluno)
        self.assertEqual(self.emails(), [])
        self.assertEqual(notification_service.unread_count("aluno", self.aluno), 1)

    def test_configuracao_pode_desligar_aviso_de_atraso(self):
        self.app.config["AVISAR_EE_ATRASO"] = False
        acesso_service.registar_aluno(self.aluno)
        self.assertEqual(self.emails(), [])

    # ---- saída ----
    def test_saida_regista_hora_e_marca_saida_antecipada(self):
        self.agora = SEGUNDA.replace(hour=8, minute=50)
        acesso_service.registar_aluno(self.aluno)
        self.agora = SEGUNDA.replace(hour=14, minute=0)
        r = acesso_service.registar_aluno(self.aluno)
        self.assertEqual((r.tipo, r.linha2, r.som), ("saida", "Saida antecipada", "aviso"))
        p = self.presenca()
        self.assertEqual((p["hora_saida"], p["saida_antecipada_min"]), ("14:00", 210))
        self.assertEqual(self.emails(), [])                           # por defeito não avisa saídas antecipadas

    def test_saida_antecipada_avisa_se_configurado_e_so_uma_vez(self):
        self.app.config["AVISAR_SAIDA_ANTECIPADA"] = True
        self.agora = SEGUNDA.replace(hour=8, minute=50)
        acesso_service.registar_aluno(self.aluno)
        self.agora = SEGUNDA.replace(hour=14, minute=0)
        acesso_service.registar_aluno(self.aluno)
        presenca_service.processar_dia(D)
        mails = self.emails()
        self.assertEqual(len(mails), 1)
        self.assertIn("Saída antecipada", mails[0]["assunto"])

    # ---- falta ----
    def test_falta_so_depois_do_prazo_e_avisa_ee_aluno_e_diretor(self):
        self.agora = SEGUNDA.replace(hour=9, minute=20)
        presenca_service.processar_dia(D)
        self.assertIsNone(self.presenca())                            # ainda cedo
        self.agora = SEGUNDA.replace(hour=9, minute=31)
        presenca_service.processar_dia(D)
        self.assertEqual(self.presenca()["estado"], "falta")
        mails = self.emails()
        self.assertEqual(len(mails), 1)
        self.assertIn("Falta", mails[0]["assunto"])
        self.assertIn("não registou entrada", mails[0]["corpo"])
        self.assertGreaterEqual(notification_service.unread_count("professor", self.prof), 1)
        self.assertGreaterEqual(notification_service.unread_count("aluno", self.aluno), 1)
        presenca_service.processar_dia(D)                             # idempotente
        self.assertEqual(len(self.emails()), 1)

    def test_falta_que_afinal_chegou_passa_a_atraso_e_avisa_de_novo(self):
        self.agora = SEGUNDA.replace(hour=9, minute=40)
        presenca_service.processar_dia(D)
        self.assertEqual(self.presenca()["estado"], "falta")
        self.agora = SEGUNDA.replace(hour=10, minute=0)
        acesso_service.registar_aluno(self.aluno)
        p = self.presenca()
        self.assertEqual((p["estado"], p["atraso_minutos"]), ("atraso", 60))
        self.assertEqual([("Falta" in m["assunto"], "Atraso" in m["assunto"]) for m in self.emails()], [(True, False), (False, True)])

    def test_falta_justificada_antes_nao_envia_email(self):
        self.db.execute("INSERT INTO justificacoes (aluno_id,data_inicio,data_fim,motivo,estado) VALUES (?,?,?,?, 'aprovado')",
                        (self.aluno, "2026-10-26", "2026-10-26", "consulta"))
        self.db.commit()
        self.agora = SEGUNDA.replace(hour=10)
        presenca_service.processar_dia(D)
        self.assertEqual(self.presenca()["estado"], "falta_justificada")
        self.assertEqual(self.emails(), [])

    def test_justificacao_aprovada_depois_converte_a_falta(self):
        self.agora = SEGUNDA.replace(hour=10)
        presenca_service.processar_dia(D)
        self.assertEqual(presenca_service.aplicar_justificacao(self.aluno, "2026-10-26", "2026-10-26"), 1)
        self.assertEqual(self.presenca()["estado"], "falta_justificada")

    def test_dia_sem_horario_nao_gera_nada(self):
        horario_service.guardar_horario(self.turma, {0: None})
        self.agora = SEGUNDA.replace(hour=11)
        self.assertEqual(presenca_service.processar_dia(D)["turmas"], 0)
        self.assertIsNone(self.presenca())

    def test_dias_passados_nunca_geram_emails(self):
        antigo = D - timedelta(days=7)
        presenca_service.processar_dia(antigo, agora=datetime(2026, 10, 19, 23, 59))
        self.assertEqual(self.presenca(antigo)["estado"], "falta")
        self.assertEqual(self.emails(), [])

    def test_recalcular_periodo_nao_envia_emails(self):
        n = presenca_service.recalcular_periodo(D - timedelta(days=5), D - timedelta(days=1))   # qua, qui, sex (+ sáb/dom sem aulas)
        self.assertGreaterEqual(n, 3)
        self.assertEqual(self.emails(), [])

    # ---- manual ----
    def test_marcacao_manual_tem_prioridade_e_pode_ser_reposta(self):
        self.agora = SEGUNDA.replace(hour=10)
        presenca_service.processar_dia(D)                             # falta (email enviado)
        presenca_service.definir_estado(self.aluno, D, "presente", nota="Veio mas a câmara falhou")
        presenca_service.processar_dia(D)                             # não pode sobrescrever
        p = self.presenca()
        self.assertEqual((p["estado"], p["origem"], p["nota"]), ("presente", "manual", "Veio mas a câmara falhou"))
        assuntos = [m["assunto"] for m in self.emails()]
        self.assertTrue(any("Falta" in a for a in assuntos) and any("Atualização" in a for a in assuntos))   # pede desculpa ao EE
        presenca_service.repor_auto(self.aluno, D)
        self.assertEqual(self.presenca()["estado"], "falta")

    def test_estado_manual_invalido(self):
        with self.assertRaises(ValueError):
            presenca_service.definir_estado(self.aluno, D, "xpto")

    def test_entrada_manual_para_aluno_sem_consentimento(self):
        sem = self.mk_aluno(2, self.turma, consent=False)
        acesso_service.registar_manual(sem, "entrada", SEGUNDA.replace(hour=8, minute=50))
        self.agora = SEGUNDA.replace(hour=13)
        presenca_service.processar_dia(D, self.turma)
        self.assertEqual(self.db.execute("SELECT estado FROM presencas WHERE aluno_id = ?", (sem,)).fetchone()[0], "presente")

    # ---- consultas ----
    def test_contagens_e_resumo(self):
        self.agora = SEGUNDA.replace(hour=10)
        presenca_service.processar_dia(D)
        self.assertEqual(presenca_service.contagens(self.aluno)["falta"], 1)
        r = presenca_service.resumo_turma(self.turma, "2026-10-01", "2026-10-31")[0]
        self.assertEqual((r["faltas"], r["atrasos"]), (1, 0))

    def test_emails_tem_assinatura_com_nome_da_escola(self):
        acesso_service.registar_aluno(self.aluno)
        self.assertIn(self.app.config["ESCOLA_NOME"], self.emails()[0]["corpo"])


class TestMigracao(unittest.TestCase):
    """Uma base de dados da v1 (horários por disciplina) é migrada sem perder alunos, professores, rostos nem acessos."""
    def test_migra_v1_para_v2(self):
        from flask_app import db as dbmod, create_app
        tmp = tempfile.mkdtemp(prefix="escola_mig_")
        try:
            path = str(Path(tmp) / "escola.db")
            conn = sqlite3.connect(path)
            conn.executescript(dbmod.SCHEMA)
            conn.executescript("""
                DROP TABLE presencas;
                CREATE TABLE disciplinas (id INTEGER PRIMARY KEY, nome TEXT, sigla TEXT, limite_faltas INTEGER);
                CREATE TABLE aulas (id INTEGER PRIMARY KEY, turma_id INTEGER, disciplina_id INTEGER, professor_id INTEGER, sala TEXT,
                                    dia_semana INTEGER, hora_inicio TEXT, hora_fim TEXT);
                CREATE TABLE presencas (id INTEGER PRIMARY KEY, aula_id INTEGER, aluno_id INTEGER, data TEXT, estado TEXT);
                INSERT INTO utilizadores (nome,email,password_hash,papel) VALUES ('Miguel','m@x.pt','h','professor');
                INSERT INTO turmas (nome, diretor_turma_id) VALUES ('PGI24', 1);
                INSERT INTO alunos (numero_processo,nome_completo,email,turma_id,encarregado_email,consentimento_biometrico,password_hash)
                       VALUES ('1','Dmytro','d@x.pt',1,'ee@x.pt',1,'h');
                INSERT INTO face_encodings (aluno_id, encoding) VALUES (1, x'00');
                INSERT INTO acessos (aluno_id,tipo,timestamp) VALUES (1,'entrada','2026-10-20 08:55:00');
                INSERT INTO disciplinas VALUES (1,'Prog','P',10);
                INSERT INTO aulas VALUES (1,1,1,1,'1.1',0,'09:00','10:30'), (2,1,1,1,'1.1',0,'10:45','12:15'), (3,1,1,1,'1.1',0,'14:00','17:30'),
                                         (4,1,1,1,'1.1',2,'09:30','12:00');
                INSERT INTO presencas VALUES (1,1,1,'2026-10-20','presente');
            """)
            conn.commit()
            conn.close()
            app = create_app({"TESTING": True, "DATABASE_PATH": path, "DATA_DIR": tmp, "UPLOAD_DIR": str(Path(tmp) / "up"), "ADMIN_PASSWORD": "Admin12345"})
            c = sqlite3.connect(path)
            c.row_factory = sqlite3.Row
            tabelas = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertNotIn("aulas", tabelas)
            self.assertNotIn("disciplinas", tabelas)
            self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], 2)
            horarios = {(r["dia_semana"], r["hora_entrada"], r["hora_saida"]) for r in c.execute("SELECT * FROM horarios_turma")}
            self.assertEqual(horarios, {(0, "09:00", "17:30"), (2, "09:30", "12:00")})       # 1.ª aula → entrada, última → saída
            self.assertEqual(c.execute("SELECT COUNT(*) FROM alunos").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT encarregado_email FROM alunos").fetchone()[0], "ee@x.pt")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM face_encodings").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM acessos").fetchone()[0], 1)
            self.assertEqual(c.execute("SELECT nome FROM utilizadores WHERE papel='professor'").fetchone()[0], "Miguel")
            self.assertEqual(c.execute("SELECT COUNT(*) FROM outbox_email").fetchone()[0], 0)   # a migração nunca envia emails
            colunas = [r[1] for r in c.execute("PRAGMA table_info(presencas)")]
            self.assertIn("hora_entrada", colunas)
            self.assertTrue(any(f.startswith("escola.db.bak-v1-") for f in os.listdir(tmp)), "falta a cópia de segurança")
            c.close()
            create_app({"TESTING": True, "DATABASE_PATH": path, "DATA_DIR": tmp, "UPLOAD_DIR": str(Path(tmp) / "up"), "ADMIN_PASSWORD": "x"})   # 2.º arranque: sem erros
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
