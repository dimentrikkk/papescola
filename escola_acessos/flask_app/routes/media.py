"""Ficheiros enviados. Acesso controlado: cada aluno só vê a sua foto; o staff vê as dos alunos."""
from flask import Blueprint, abort, current_app, send_from_directory, session

from ..db import get_db
from ..services.auth_service import role_required

bp = Blueprint("media", __name__, url_prefix="/ficheiros")


@bp.route("/<path:filename>")
@role_required("admin", "professor", "aluno")
def ficheiro(filename):
    if "/" in filename or "\\" in filename or filename.startswith("."):
        abort(404)
    tipo, uid = session["user_type"], session["user_id"]
    db = get_db()
    if filename.startswith("avatar_"):
        dono = db.execute("SELECT id FROM alunos WHERE foto_perfil = ?", (filename,)).fetchone()
        if not dono:
            abort(404)
        if tipo == "aluno" and dono["id"] != uid:
            abort(403)
    elif filename.startswith("acesso_"):
        if tipo != "admin":
            abort(403)
    else:
        abort(404)
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename, max_age=0)
