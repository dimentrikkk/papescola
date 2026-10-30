"""Portal do professor / diretor de turma: ver a assiduidade das suas turmas e corrigir marcações."""
from datetime import date, timedelta

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from ..db import get_db
from ..services import horario_service, notification_service as notif, presenca_service
from ..services.auth_service import professor_required
from .. import utils

bp = Blueprint("professor", __name__, url_prefix="/professor")


def _minhas_turmas(pid):
    return get_db().execute(
        """SELECT t.*, c.nome AS curso, (SELECT COUNT(*) FROM alunos a WHERE a.turma_id = t.id AND a.ativo = 1) AS n_alunos
             FROM turmas t LEFT JOIN cursos c ON c.id = t.curso_id WHERE t.diretor_turma_id = ? ORDER BY t.nome""", (pid,)).fetchall()


def _turma_do_professor(turma_id):
    t = get_db().execute("SELECT * FROM turmas WHERE id = ?", (turma_id,)).fetchone()
    if not t:
        abort(404)
    if t["diretor_turma_id"] != session["user_id"]:
        abort(403)
    return t


@bp.route("/")
@bp.route("/dashboard")
@professor_required
def dashboard():
    presenca_service.processar_hoje_se_necessario()
    pid, hoje = session["user_id"], utils.today()
    cartoes = []
    for t in _minhas_turmas(pid):
        linhas = presenca_service.dia_turma(t["id"], hoje)
        cont = {"presente": 0, "atraso": 0, "falta": 0, "falta_justificada": 0, "pendente": 0}
        for l in linhas:
            cont[l["estado"] or "pendente"] += 1
        cartoes.append({"turma": t, "cont": cont, "hor": horario_service.horario_do_dia(t["id"], hoje.weekday())})
    return render_template("professor/dashboard.html", cartoes=cartoes, notifs=notif.list_for("professor", pid, limit=5),
                           hoje=hoje, dias=utils.DIAS_SEMANA)


@bp.route("/turma/<int:turma_id>", methods=["GET", "POST"])
@professor_required
def turma(turma_id):
    t = _turma_do_professor(turma_id)
    data = request.values.get("data") or utils.today().isoformat()
    if not utils.valid_date(data):
        data = utils.today().isoformat()
    d = date.fromisoformat(data)

    if request.method == "POST":
        aid, estado = request.form.get("aluno_id", type=int), request.form.get("estado")
        pertence = get_db().execute("SELECT 1 FROM alunos WHERE id = ? AND turma_id = ?", (aid, turma_id)).fetchone()
        if not pertence or d > utils.today():
            abort(403)
        try:
            if not estado:
                flash("Escolha o novo estado.", "error")
            elif estado == "auto":
                presenca_service.repor_auto(aid, d)
                flash("Marcação manual removida.", "success")
            else:
                presenca_service.definir_estado(aid, d, estado, request.form.get("atraso", type=int) or 0,
                                                utils.clean(request.form.get("nota"), 200) or None)
                flash("Presença atualizada.", "success")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("professor.turma", turma_id=turma_id, data=data))

    if d <= utils.today():
        presenca_service.processar_dia(d, turma_id, avisar=False if d != utils.today() else None)
    de = (utils.today() - timedelta(days=30)).isoformat()
    return render_template("professor/turma.html", turma=t, data=data, hor=horario_service.horario_do_dia(turma_id, d.weekday()),
                           linhas=presenca_service.dia_turma(turma_id, d), resumo=presenca_service.resumo_turma(turma_id, de, utils.today().isoformat()),
                           dia_nome=utils.DIAS_SEMANA[d.weekday()], futuro=d > utils.today())


@bp.route("/notificacoes")
@professor_required
def notificacoes():
    pid = session["user_id"]
    rows = notif.list_for("professor", pid, limit=100)
    notif.mark_all_read("professor", pid)
    return render_template("notificacoes.html", rows=rows)
