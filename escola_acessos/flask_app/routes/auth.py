"""Login, logout e alteração de password."""
from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..services.auth_service import (
    authenticate, change_password, is_locked, login_user, logout_user,
    password_error, record_login_attempt, verify_password,
)
from ..db import get_db
from ..services.notification_service import notify

bp = Blueprint("auth", __name__)


def _home():
    return redirect(url_for("index"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_type"):
        return _home()
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        from flask import current_app
        if not email or not password:
            flash("Preencha o email e a password.", "error")
            return render_template("login.html"), 400
        if is_locked(email, current_app.config["MAX_LOGIN_FALHAS"], current_app.config["JANELA_BLOQUEIO_MIN"]):
            flash("Conta temporariamente bloqueada por excesso de tentativas. Tente mais tarde.", "error")
            return render_template("login.html"), 429
        user = authenticate(email, password)
        ip = request.remote_addr
        record_login_attempt(email, bool(user), ip)
        if not user:
            notify("admin", None, "Tentativa de login falhada", f"Email: {email} (IP {ip or '?'})", "warn")
            flash("Credenciais inválidas.", "error")
            return render_template("login.html"), 401
        login_user(user)
        return redirect(url_for("auth.conta") if user["must_change"] else url_for("index"))
    return render_template("login.html")


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    logout_user()
    flash("Sessão terminada.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/conta", methods=["GET", "POST"])
def conta():
    """Alterar a própria password (obrigatório no primeiro login)."""
    tipo, uid = session.get("user_type"), session.get("user_id")
    if not tipo:
        return redirect(url_for("auth.login"))
    if request.method == "POST":
        atual = request.form.get("atual") or ""
        nova = request.form.get("nova") or ""
        confirma = request.form.get("confirma") or ""
        tabela = "alunos" if tipo == "aluno" else "utilizadores"
        row = get_db().execute(f"SELECT password_hash FROM {tabela} WHERE id = ?", (uid,)).fetchone()
        erro = None
        if not row or not verify_password(atual, row["password_hash"]):
            erro = "Password atual incorreta."
        elif nova != confirma:
            erro = "A confirmação não coincide."
        elif nova == atual:
            erro = "A nova password tem de ser diferente da atual."
        else:
            erro = password_error(nova)
        if erro:
            flash(erro, "error")
        else:
            change_password(tipo, uid, nova)
            session["must_change"] = False
            flash("Password alterada.", "success")
            return redirect(url_for("index"))
    return render_template("conta.html", obrigatorio=session.get("must_change", False))
