"""SQLite: esquema, ligação por pedido e dados iniciais."""
from __future__ import annotations

import secrets
import shutil
import sqlite3
from datetime import datetime

from flask import current_app, g

from .services.passwords import hash_password

SCHEMA = """
CREATE TABLE IF NOT EXISTS utilizadores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    papel TEXT NOT NULL CHECK (papel IN ('admin','professor')),
    ativo INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    descricao TEXT
);

CREATE TABLE IF NOT EXISTS turmas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    curso_id INTEGER REFERENCES cursos(id) ON DELETE SET NULL,
    ano_letivo TEXT,
    diretor_turma_id INTEGER REFERENCES utilizadores(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS alunos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_processo TEXT NOT NULL UNIQUE,
    nome_completo TEXT NOT NULL,
    data_nascimento TEXT,
    email TEXT NOT NULL UNIQUE,
    telefone TEXT,
    turma_id INTEGER REFERENCES turmas(id) ON DELETE SET NULL,
    encarregado_nome TEXT,
    encarregado_email TEXT,
    encarregado_telefone TEXT,
    consentimento_biometrico INTEGER NOT NULL DEFAULT 0,
    consentimento_data TEXT,
    password_hash TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 1,
    foto_perfil TEXT,
    ativo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS face_encodings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id INTEGER NOT NULL REFERENCES alunos(id) ON DELETE CASCADE,
    encoding BLOB NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS horarios_turma (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turma_id INTEGER NOT NULL REFERENCES turmas(id) ON DELETE CASCADE,
    dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
    hora_entrada TEXT NOT NULL,
    hora_saida TEXT NOT NULL,
    UNIQUE(turma_id, dia_semana)
);

CREATE TABLE IF NOT EXISTS acessos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id INTEGER NOT NULL REFERENCES alunos(id) ON DELETE CASCADE,
    tipo TEXT NOT NULL CHECK (tipo IN ('entrada','saida')),
    timestamp TEXT NOT NULL,
    origem TEXT NOT NULL DEFAULT 'porteiro',
    foto_path TEXT
);

CREATE TABLE IF NOT EXISTS eventos_porta (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tipo TEXT NOT NULL,
    aluno_id INTEGER REFERENCES alunos(id) ON DELETE SET NULL,
    detalhe TEXT
);

CREATE TABLE IF NOT EXISTS presencas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id INTEGER NOT NULL REFERENCES alunos(id) ON DELETE CASCADE,
    data TEXT NOT NULL,
    estado TEXT NOT NULL CHECK (estado IN ('presente','atraso','falta','falta_justificada')),
    hora_entrada TEXT,
    hora_saida TEXT,
    atraso_minutos INTEGER NOT NULL DEFAULT 0,
    saida_antecipada_min INTEGER NOT NULL DEFAULT 0,
    origem TEXT NOT NULL DEFAULT 'auto' CHECK (origem IN ('auto','manual')),
    nota TEXT,
    aviso_estado TEXT,
    aviso_saida INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT,
    UNIQUE(aluno_id, data)
);

CREATE TABLE IF NOT EXISTS justificacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    aluno_id INTEGER NOT NULL REFERENCES alunos(id) ON DELETE CASCADE,
    data_inicio TEXT NOT NULL,
    data_fim TEXT NOT NULL,
    motivo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','aprovado','rejeitado')),
    resposta TEXT,
    decidido_por INTEGER REFERENCES utilizadores(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    decided_at TEXT
);

CREATE TABLE IF NOT EXISTS notificacoes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destinatario_tipo TEXT NOT NULL CHECK (destinatario_tipo IN ('admin','professor','aluno')),
    destinatario_id INTEGER,
    titulo TEXT NOT NULL,
    mensagem TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'info',
    lida INTEGER NOT NULL DEFAULT 0,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS outbox_email (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    destinatario TEXT NOT NULL,
    assunto TEXT NOT NULL,
    corpo TEXT NOT NULL,
    estado TEXT NOT NULL DEFAULT 'pendente' CHECK (estado IN ('pendente','enviado','erro')),
    erro TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    enviado_em TEXT
);

CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    success INTEGER NOT NULL DEFAULT 0,
    ip TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_acessos_aluno_ts ON acessos(aluno_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_presencas_data ON presencas(data);
CREATE INDEX IF NOT EXISTS idx_notif_dest ON notificacoes(destinatario_tipo, destinatario_id, lida);
CREATE INDEX IF NOT EXISTS idx_login_email_time ON login_attempts(email, created_at);
CREATE INDEX IF NOT EXISTS idx_eventos_ts ON eventos_porta(timestamp);
"""


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 8000")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = _connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


SCHEMA_VERSION = 2


def _tabelas(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _migrar_v1_para_v2(conn) -> None:
    """v1 tinha horários por aula/disciplina; v2 só guarda a hora de ENTRADA e de SAÍDA da turma por dia.
    Aproveita o que já existia: 1.ª aula do dia → entrada; fim da última → saída."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS horarios_turma (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            turma_id INTEGER NOT NULL REFERENCES turmas(id) ON DELETE CASCADE,
            dia_semana INTEGER NOT NULL CHECK (dia_semana BETWEEN 0 AND 6),
            hora_entrada TEXT NOT NULL,
            hora_saida TEXT NOT NULL,
            UNIQUE(turma_id, dia_semana)
        );
        INSERT OR IGNORE INTO horarios_turma (turma_id, dia_semana, hora_entrada, hora_saida)
            SELECT turma_id, dia_semana, MIN(hora_inicio), MAX(hora_fim) FROM aulas GROUP BY turma_id, dia_semana;
        DROP TABLE IF EXISTS presencas;   -- derivadas: recalculam-se a partir das entradas/saídas
        DROP TABLE IF EXISTS aulas;
        DROP TABLE IF EXISTS disciplinas;
    """)


def init_db(app) -> bool:
    """Cria/atualiza a base de dados. Devolve True se migrou de uma versão antiga
    (nesse caso é feita antes uma cópia de segurança do ficheiro)."""
    path = app.config["DATABASE_PATH"]
    conn = _connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    versao = conn.execute("PRAGMA user_version").fetchone()[0]
    migrou = False
    if "aulas" in _tabelas(conn) and versao < SCHEMA_VERSION:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        backup = f"{path}.bak-v1-{datetime.now():%Y%m%d-%H%M%S}"
        shutil.copy2(path, backup)
        print(f"[migração] Cópia de segurança da base de dados: {backup}")
        _migrar_v1_para_v2(conn)
        migrou = True
    conn.executescript(SCHEMA)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.close()
    return migrou


def seed_initial_data(app) -> None:
    """Cria o admin inicial se ainda não existir nenhum."""
    cfg = app.config
    conn = _connect(cfg["DATABASE_PATH"])
    try:
        if conn.execute("SELECT COUNT(*) FROM utilizadores WHERE papel = 'admin'").fetchone()[0] == 0:
            pw = cfg["ADMIN_PASSWORD"]
            generated = pw is None
            if generated:
                pw = secrets.token_urlsafe(9)
            conn.execute(
                "INSERT INTO utilizadores (nome, email, password_hash, papel, must_change_password) "
                "VALUES (?, ?, ?, 'admin', 1)",
                (cfg["ADMIN_NOME"], cfg["ADMIN_EMAIL"], hash_password(pw)),
            )
            if generated and not cfg.get("TESTING"):
                print("=" * 62)
                print(f" Conta admin criada: {cfg['ADMIN_EMAIL']}")
                print(f" Password temporária: {pw}   (será pedido para a alterar)")
                print("=" * 62)
        conn.commit()
    finally:
        conn.close()
