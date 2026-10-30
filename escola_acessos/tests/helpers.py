"""Utilitários comuns aos testes."""
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np

from flask_app import create_app, utils
from flask_app.db import get_db
from flask_app.services import face_service
from flask_app.services.passwords import hash_password

SEGUNDA = datetime(2026, 10, 26, 9, 12, 0)   # uma segunda-feira


class FakeBackend:
    """Codificação falsa: imagem de cor uniforme v → vetor constante v/255. Imagem preta = sem rosto."""
    def encode(self, rgb, scale=1.0):
        v = int(rgb.max())
        return None if v == 0 else np.full(128, v / 255.0)


def imagem(v: int) -> np.ndarray:
    return np.full((48, 48, 3), v, dtype=np.uint8)


class AppTestCase(unittest.TestCase):
    overrides: dict = {}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="escola_t_")
        cfg = {"TESTING": True, "DATABASE_PATH": str(Path(self.tmp) / "t.db"), "UPLOAD_DIR": str(Path(self.tmp) / "up"),
               "DATA_DIR": self.tmp, "ADMIN_PASSWORD": "Admin12345", "ADMIN_EMAIL": "admin@escola.pt"}
        cfg.update(self.overrides)
        self.app = create_app(cfg)
        self._now = utils.now
        utils.now = lambda: self.agora
        self.agora = SEGUNDA
        face_service.set_backend(FakeBackend())
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.db = get_db()
        self.client = self.app.test_client()

    def tearDown(self):
        utils.now = self._now
        face_service.set_backend(None)
        self.ctx.pop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------- fábricas ----------
    def mk_prof(self, nome="Prof Teste", email="prof@escola.pt", pw="Professor123"):
        cur = self.db.execute("INSERT INTO utilizadores (nome,email,password_hash,papel) VALUES (?,?,?, 'professor')",
                              (nome, email, hash_password(pw)))
        self.db.commit()
        return cur.lastrowid

    def mk_turma(self, nome="T1", diretor=None):
        cur = self.db.execute("INSERT INTO turmas (nome, diretor_turma_id) VALUES (?,?)", (nome, diretor))
        self.db.commit()
        return cur.lastrowid

    def mk_horario(self, turma, entrada="09:00", saida="17:30", dias=range(5)):
        from flask_app.services import horario_service
        horario_service.guardar_horario(turma, {d: (entrada, saida) for d in dias})

    def mk_aluno(self, n=1, turma=None, consent=True, pw="Aluno1234", enc_email="enc@exemplo.pt", must_change=0):
        cur = self.db.execute(
            """INSERT INTO alunos (numero_processo,nome_completo,email,turma_id,encarregado_email,consentimento_biometrico,
                   consentimento_data,password_hash,must_change_password) VALUES (?,?,?,?,?,?,?,?,?)""",
            (str(n), f"Aluno {n} Teste", f"a{n}@escola.pt", turma, enc_email, 1 if consent else 0,
             "2026-09-01 10:00:00" if consent else None, hash_password(pw), must_change))
        self.db.commit()
        return cur.lastrowid

    def add_face(self, aluno_id, cor):
        face_service.adicionar_amostra(aluno_id, imagem(cor))

    def login(self, email, pw):
        with self.client.session_transaction() as s:
            s["_csrf"] = "tok"
        return self.client.post("/login", data={"email": email, "password": pw, "csrf_token": "tok"})

    def post(self, url, data=None, **kw):
        with self.client.session_transaction() as s:
            s.setdefault("_csrf", "tok")
            tok = s["_csrf"]
        d = dict(data or {})
        d["csrf_token"] = tok
        return self.client.post(url, data=d, **kw)
