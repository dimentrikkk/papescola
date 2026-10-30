"""Dashboard, estatísticas, exportação CSV, comunicações e notificações."""
import csv
import io

from flask import Response, flash, redirect, render_template, request, url_for

from . import bp
from ...db import get_db
from ...services import estatisticas_service as est
from ...services import notification_service as notif
from ...services import presenca_service
from ...services.auth_service import admin_required
from ... import utils


@bp.route("/dashboard")
@admin_required
def dashboard():
    presenca_service.processar_hoje_se_necessario()
    ultimos = get_db().execute(
        """SELECT x.tipo, x.timestamp, x.origem, al.nome_completo, t.nome AS turma
             FROM acessos x JOIN alunos al ON al.id = x.aluno_id LEFT JOIN turmas t ON t.id = al.turma_id
            ORDER BY x.timestamp DESC, x.id DESC LIMIT 8""").fetchall()
    return render_template("admin/dashboard.html", k=est.kpis_hoje(), estados=est.estados_de_hoje(),
                           entradas=est.entradas_por_dia(7), ocorrencias=est.ocorrencias_por_turma(30), ultimos=ultimos)


@bp.route("/estatisticas")
@admin_required
def estatisticas():
    return render_template("admin/estatisticas.html", entradas=est.entradas_por_dia(30), ocorrencias=est.ocorrencias_por_turma(30),
                           chegadas=est.chegadas_por_hora(30), top_atrasos=est.ranking("atraso", 30), top_faltas=est.ranking("falta", 30))


def _csv_safe(v):
    """Evita injeção de fórmulas ao abrir o CSV no Excel."""
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s


@bp.route("/exportar/presencas.csv")
@admin_required
def exportar_presencas():
    hoje = utils.today()
    de = request.args.get("de") or hoje.replace(day=1).isoformat()
    ate = request.args.get("ate") or hoje.isoformat()
    if not (utils.valid_date(de) and utils.valid_date(ate)):
        flash("Datas inválidas.", "error")
        return redirect(url_for("admin.estatisticas"))
    rows = get_db().execute(
        """SELECT p.data, t.nome AS turma, al.numero_processo, al.nome_completo, p.estado, p.hora_entrada, p.hora_saida,
                  p.atraso_minutos, p.saida_antecipada_min, p.origem, p.nota
             FROM presencas p JOIN alunos al ON al.id = p.aluno_id LEFT JOIN turmas t ON t.id = al.turma_id
            WHERE p.data BETWEEN ? AND ? ORDER BY p.data, t.nome, al.nome_completo""", (de, ate)).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["data", "turma", "n_processo", "aluno", "estado", "entrada", "saida", "atraso_min", "saida_antecipada_min", "origem", "nota"])
    for r in rows:
        w.writerow([_csv_safe(c) for c in tuple(r)])
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=presencas_{de}_{ate}.csv"})


@bp.route("/comunicacoes", methods=["GET", "POST"])
@admin_required
def comunicacoes():
    if request.method == "POST":
        if request.form.get("acao") == "reenviar":
            n = notif.reenviar_erros()
            flash(f"{n} email(s) com erro voltaram à fila.", "success")
            return redirect(url_for("admin.comunicacoes"))
        r = notif.enviar_pendentes()
        if not r["smtp"]:
            flash("Servidor de email não configurado (variáveis SMTP_*). Os emails ficam guardados na fila.", "error")
        elif r.get("erro"):
            flash(r["erro"], "error")
        else:
            flash(f"Enviados: {r['enviados']} · Erros: {r['erros']}", "success" if not r["erros"] else "error")
        return redirect(url_for("admin.comunicacoes"))
    rows = get_db().execute("SELECT * FROM outbox_email ORDER BY id DESC LIMIT 200").fetchall()
    return render_template("admin/comunicacoes.html", rows=rows)


@bp.route("/notificacoes")
@admin_required
def notificacoes():
    rows = notif.list_for("admin", None, limit=100)
    notif.mark_all_read("admin", None)
    return render_template("notificacoes.html", rows=rows)
