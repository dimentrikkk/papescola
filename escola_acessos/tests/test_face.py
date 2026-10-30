from flask_app.services import acesso_service, face_service
from .helpers import AppTestCase, imagem


class TestFace(AppTestCase):
    def setUp(self):
        super().setUp()
        self.turma = self.mk_turma()
        self.a = self.mk_aluno(1, self.turma)
        self.b = self.mk_aluno(2, self.turma)
        self.add_face(self.a, 50)
        self.add_face(self.b, 120)

    def test_identifica_o_aluno_certo(self):
        r = face_service.identify(imagem(50))
        self.assertEqual((r.estado, r.aluno_id), ("ok", self.a))
        self.assertEqual(face_service.identify(imagem(120)).aluno_id, self.b)

    def test_desconhecido(self):
        self.assertEqual(face_service.identify(imagem(220)).estado, "desconhecido")

    def test_sem_rosto(self):
        self.assertEqual(face_service.identify(imagem(0)).estado, "sem_rosto")

    def test_ambiguo_quando_dois_alunos_sao_parecidos(self):
        c = self.mk_aluno(3, self.turma)
        self.db.execute("INSERT INTO face_encodings (aluno_id, encoding) VALUES (?, ?)", (c, face_service._to_blob(__import__('numpy').full(128, 51 / 255.0))))
        self.db.commit()
        self.app.config["FACE_MARGEM"] = 0.2
        self.assertEqual(face_service.identify(imagem(50)).estado, "ambiguo")

    def test_sem_consentimento_nao_se_guardam_amostras(self):
        s = self.mk_aluno(4, self.turma, consent=False)
        with self.assertRaises(face_service.ConsentimentoEmFalta):
            face_service.adicionar_amostra(s, imagem(200))

    def test_nao_deixa_associar_o_mesmo_rosto_a_dois_alunos(self):
        c = self.mk_aluno(5, self.turma)
        with self.assertRaises(face_service.AmostraRejeitada):
            face_service.adicionar_amostra(c, imagem(50))        # igual ao aluno A

    def test_limite_de_amostras(self):
        self.app.config["MAX_FACE_SAMPLES"] = 2
        self.add_face(self.a, 51)
        with self.assertRaises(face_service.AmostraRejeitada):
            face_service.adicionar_amostra(self.a, imagem(52))

    def test_retirar_consentimento_para_o_reconhecimento_imediatamente(self):
        self.assertEqual(face_service.identify(imagem(50)).estado, "ok")
        self.db.execute("UPDATE alunos SET consentimento_biometrico = 0 WHERE id = ?", (self.a,))
        self.db.commit()
        self.assertEqual(face_service.identify(imagem(50)).estado, "desconhecido")

    def test_aluno_inativo_nao_e_reconhecido(self):
        self.db.execute("UPDATE alunos SET ativo = 0 WHERE id = ?", (self.a,))
        self.db.commit()
        self.assertEqual(face_service.identify(imagem(50)).estado, "desconhecido")

    def test_processar_imagem_regista_acesso_e_desconhecido_fica_em_auditoria(self):
        ok = acesso_service.processar_imagem(imagem(50))
        self.assertTrue(ok.sucesso and ok.abrir)
        nok = acesso_service.processar_imagem(imagem(220))
        self.assertEqual((nok.estado, nok.abrir), ("nao_reconhecido", False))
        tipos = [r["tipo"] for r in self.db.execute("SELECT tipo FROM eventos_porta")]
        self.assertIn("nao_reconhecido", tipos)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM acessos").fetchone()[0], 1)   # desconhecido NÃO regista acesso

    def test_fotos_de_acesso_nao_sao_guardadas_por_defeito(self):
        acesso_service.processar_imagem(imagem(50))
        self.assertIsNone(self.db.execute("SELECT foto_path FROM acessos").fetchone()[0])

    def test_dados_de_amostras_apagam_se_o_aluno_for_apagado(self):
        self.db.execute("DELETE FROM alunos WHERE id = ?", (self.a,))
        self.db.commit()
        self.assertEqual(face_service.contar_amostras(self.a), 0)
