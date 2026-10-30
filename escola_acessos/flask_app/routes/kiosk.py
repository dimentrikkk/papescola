"""Kiosk web (alternativa/ensaio no PC com webcam do browser).
Em produção, no Raspberry Pi, quem faz este trabalho é o processo `hardware/porteiro.py`
(sem browser). Este endpoint NÃO abre a porta."""
from flask import Blueprint, abort, current_app, jsonify, render_template, request

from ..services import acesso_service, face_service

bp = Blueprint("kiosk", __name__, url_prefix="/kiosk")


def _enabled():
    if not current_app.config["KIOSK_WEB_ENABLED"]:
        abort(404)


@bp.route("/")
def index():
    _enabled()
    return render_template("kiosk/index.html")


@bp.post("/reconhecer")
def reconhecer():
    _enabled()
    payload = request.get_json(silent=True) or {}
    try:
        rgb = face_service.rgb_from_data_url(payload.get("image", ""))
    except face_service.ImagemInvalida as e:
        return jsonify({"ok": False, "estado": "erro", "mensagem": str(e)}), 400
    res = acesso_service.processar_imagem(rgb, origem="web")
    return jsonify(res.as_dict())
