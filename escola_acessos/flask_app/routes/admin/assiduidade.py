"""Acessos à escola, presenças do dia, justificações e eventos da porta."""
from datetime import date

from flask import flash, redirect, render_template, request, session, url_for

from . import bp
from ...db import get_db
from ...services import notification_service as notif
from ...services import presenca_service
from ...services.auth_service import admin_required
from ... import utils


def _turmas():
    return get_db().execute("SELECT id, nome FROM turmas ORDER BY nome").fetchall()


def _data_arg(valor):
    return valor if valor and utils.valid_date(valor) else utils.today().isoformat()


@bp.route("/acessos")
@admin_required
def acessos():
    data = _data_arg(request.args.get("data"))
    turma_id = request.args.get("turma_id", type=int)
    sql = """SELECT x.*, al.nome_completo, al.numero_processo, t.nome AS turma
               FROM acessos x JOIN alunos al ON al.id = x.aluno_id LEFT JOIN turmas t ON t.id = al.turma_id
              WHERE date(x.timestamp) = ?"""
    args = [data]
    if turma_id:
        sql += " AND al.turma_id = ?"
        args.append(turma_id)
    rows = get_db().execute(sql + " ORDER BY x.timestamp DESC, x.id DESC LIMIT 500", args).fetchall()
    return render_template("admin/acessos.html", rows=rows, data=data, turma_id=turma_id, turmas=_turmas())


@bp.route("/presencas", methods=["GET", "POST"])
@admin_required
def presencas():
    turmas = _turmas()
    data = _data_arg(request.values.get("data"))
    turma_id = request.values.get("turma_id", type=int) or (turmas[0]["id"] if turmas else None)
    d = date.fromisoformat(data)
    if request.method == "POST":
        st = presenca_service.processar_dia(d, turma_id)
        flash(f"Dia processado: {st['presentes']} presentes, {st['atrasos']} atrasos e {st['faltas']} faltas.", "success")
        return redirect(url_for("admin.presencas", data=data, turma_id=turma_id))
    else:
        presenca_service.processar_hoje_se_necessario()
    linhas = presenca_service.dia_turma(turma_id, d) if turma_id else []
    from ...services import horario_service
    hor = horario_service.horario_do_dia(turma_id, d.weekday())
    return render_template("admin/presencas.html", linhas=linhas, data=data, turma_id=turma_id, turmas=turmas, hor=hor,
                           dia_nome=utils.DIAS_SEMANA[d.weekday()])


@bp.post("/presencas/definir")
@admin_required
def presencas_definir():
    data, turma_id = _data_arg(request.form.get("data")), request.form.get("turma_id", type=int)
    aid, estado = request.form.get("aluno_id", type=int), request.form.get("estado")
    try:
        if not estado:
            flash("Escolha o novo estado.", "error")
        elif estado == "auto":
            presenca_service.repor_auto(aid, date.fromisoformat(data))
            flash("Marcação manual removida; volta a valer o cálculo automático.", "success")
        else:
            presenca_service.definir_estado(aid, date.fromisoformat(data), estado, request.form.get("atraso", type=int) or 0,
                                            utils.clean(request.form.get("nota"), 200) or None)
            flash("Presença atualizada.", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("admin.presencas", data=data, turma_id=turma_id))


@bp.route("/justificacoes", methods=["GET", "POST"])
@admin_required
def justificacoes():
    db = get_db()
    if request.method == "POST":
        jid = request.form.get("id", type=int)
        decisao = request.form.get("decisao")
        resposta = utils.clean(request.form.get("resposta"), 300) or None
        j = db.execute("SELECT * FROM justificacoes WHERE id = ? AND estado = 'pendente'", (jid,)).fetchone()
        if j and decisao in ("aprovado", "rejeitado"):
            db.execute("UPDATE justificacoes SET estado=?, resposta=?, decidido_por=?, decided_at=? WHERE id=?",
                       (decisao, resposta, session["user_id"], utils.iso(utils.now()), jid))
            db.commit()
            n = presenca_service.aplicar_justificacao(j["aluno_id"], j["data_inicio"], j["data_fim"]) if decisao == "aprovado" else 0
            notif.notify("aluno", j["aluno_id"], f"Justificação {decisao}",
                         f"O pedido de {j['data_inicio']} a {j['data_fim']} foi {decisao}." + (f" {resposta}" if resposta else ""),
                         "success" if decisao == "aprovado" else "warn")
            flash(f"Pedido {decisao}." + (f" {n} falta(s) passaram a justificadas." if n else ""), "success")
        return redirect(url_for("admin.justificacoes"))
    rows = db.execute(
        """SELECT j.*, al.nome_completo, t.nome AS turma FROM justificacoes j
             JOIN alunos al ON al.id = j.aluno_id LEFT JOIN turmas t ON t.id = al.turma_id
            ORDER BY (j.estado = 'pendente') DESC, j.created_at DESC LIMIT 200""").fetchall()
    return render_template("admin/justificacoes.html", rows=rows)


@bp.route("/eventos")
@admin_required
def eventos():
    rows = get_db().execute(
        """SELECT e.*, al.nome_completo FROM eventos_porta e LEFT JOIN alunos al ON al.id = e.aluno_id
            ORDER BY e.id DESC LIMIT 300""").fetchall()
    return render_template("admin/eventos.html", rows=rows)
