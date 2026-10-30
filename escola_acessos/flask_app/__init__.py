"""Fábrica da aplicação Flask."""
from __future__ import annotations

from pathlib import Path

from flask import Flask, redirect, render_template, session, url_for

from .config import Config
from .db import close_db, init_db, seed_initial_data
from .security import init_security


def create_app(overrides: dict | None = None) -> Flask:
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)

    Path(app.config["DATA_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["UPLOAD_DIR"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["DATABASE_PATH"]).parent.mkdir(parents=True, exist_ok=True)

    migrou = init_db(app)
    seed_initial_data(app)
    app.teardown_appcontext(close_db)
    init_security(app)

    from .routes.auth import bp as auth_bp
    from .routes.kiosk import bp as kiosk_bp
    from .routes.media import bp as media_bp
    from .routes.admin import bp as admin_bp
    from .routes.professor import bp as professor_bp
    from .routes.aluno import bp as aluno_bp
    for bp in (auth_bp, kiosk_bp, media_bp, admin_bp, professor_bp, aluno_bp):
        app.register_blueprint(bp)

    if migrou:
        # Presenças antigas eram por aula: recalcula-as por dia a partir das entradas/saídas (sem enviar avisos)
        from datetime import timedelta
        from .services import presenca_service
        from . import utils
        with app.app_context():
            presenca_service.recalcular_periodo(utils.today() - timedelta(days=90), utils.today())

    @app.route("/")
    def index():
        destino = {"admin": "admin.dashboard", "professor": "professor.dashboard", "aluno": "aluno.dashboard"}
        return redirect(url_for(destino.get(session.get("user_type"), "auth.login")))

    @app.template_filter("data_pt")
    def data_pt(valor):
        """2026-10-28 → 28/10/2026"""
        v = str(valor or "")
        return f"{v[8:10]}/{v[5:7]}/{v[:4]}" if len(v) >= 10 else v

    @app.context_processor
    def inject_globals():
        from .services.notification_service import unread_count
        from .db import get_db
        tipo, uid = session.get("user_type"), session.get("user_id")
        unread, avatar = 0, None
        if tipo:
            unread = unread_count(tipo, None if tipo == "admin" else uid)
        if tipo == "aluno":
            row = get_db().execute("SELECT foto_perfil FROM alunos WHERE id = ?", (uid,)).fetchone()
            avatar = row["foto_perfil"] if row else None
        return {
            "escola_nome": app.config["ESCOLA_NOME"],
            "current_user_type": tipo,
            "current_user_name": session.get("user_name"),
            "current_user_id": uid,
            "unread_notifs": unread,
            "current_avatar": avatar,
        }

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(404)
    @app.errorhandler(413)
    def _erro(e):
        msgs = {400: "Pedido inválido.", 403: "Não tem permissão para aceder a esta página.",
                404: "Página não encontrada.", 413: "Ficheiro demasiado grande."}
        detalhe = e.description if e.code == 400 else msgs.get(e.code, "Erro.")
        return render_template("erro.html", codigo=e.code, mensagem=detalhe), e.code

    return app
