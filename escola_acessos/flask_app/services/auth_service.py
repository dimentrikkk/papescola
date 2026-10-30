"""Autenticação e autorização por papel (admin, professor, aluno)."""
from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import session, redirect, url_for, flash, request, abort

from ..db import get_db
from .passwords import hash_password, verify_password  # noqa: F401  (re-exportados)


def authenticate(email: str, password: str) -> Optional[dict]:
    """Devolve {id, nome, email, papel, must_change} ou None."""
    db = get_db()
    row = db.execute(
        "SELECT id, nome, email, password_hash, papel, ativo, must_change_password "
        "FROM utilizadores WHERE email = ?", (email,),
    ).fetchone()
    if row and row["ativo"] and verify_password(password, row["password_hash"]):
        return {"id": row["id"], "nome": row["nome"], "email": row["email"],
                "papel": row["papel"], "must_change": bool(row["must_change_password"])}

    row = db.execute(
        "SELECT id, nome_completo, email, password_hash, ativo, must_change_password "
        "FROM alunos WHERE email = ?", (email,),
    ).fetchone()
    if row and row["ativo"] and verify_password(password, row["password_hash"]):
        return {"id": row["id"], "nome": row["nome_completo"], "email": row["email"],
                "papel": "aluno", "must_change": bool(row["must_change_password"])}
    return None


def record_login_attempt(email: str, success: bool, ip: Optional[str] = None) -> None:
    db = get_db()
    db.execute("INSERT INTO login_attempts (email, success, ip) VALUES (?, ?, ?)",
               (email, 1 if success else 0, ip))
    db.commit()


def is_locked(email: str, max_attempts: int = 5, window_minutes: int = 15) -> bool:
    row = get_db().execute(
        "SELECT COUNT(*) AS c FROM login_attempts "
        "WHERE email = ? AND success = 0 AND created_at > datetime('now', ?)",
        (email, f"-{int(window_minutes)} minutes"),
    ).fetchone()
    return int(row["c"] or 0) >= max_attempts


def login_user(user: dict) -> None:
    session.clear()
    session["user_id"] = user["id"]
    session["user_type"] = user["papel"]
    session["user_name"] = user["nome"]
    session["must_change"] = bool(user.get("must_change"))
    session.permanent = True


def logout_user() -> None:
    session.clear()


def change_password(papel: str, user_id: int, new_password: str) -> None:
    table = "alunos" if papel == "aluno" else "utilizadores"
    db = get_db()
    db.execute(f"UPDATE {table} SET password_hash = ?, must_change_password = 0 WHERE id = ?",
               (hash_password(new_password), user_id))
    db.commit()


def password_error(pw: str) -> Optional[str]:
    if len(pw) < 8:
        return "A password deve ter pelo menos 8 caracteres."
    if pw.isdigit() or pw.isalpha():
        return "Use letras e números na password."
    return None


def role_required(*papeis: str):
    """Restringe a rota a um ou mais papéis. Sem sessão → login; papel errado → 403."""
    def deco(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            tipo = session.get("user_type")
            if not tipo:
                return redirect(url_for("auth.login", next=request.path))
            if tipo not in papeis:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return deco


admin_required = role_required("admin")
professor_required = role_required("professor")
aluno_required = role_required("aluno")
