"""Portal do aluno (só leitura + pedidos de justificação)."""
import calendar
from datetime import date, timedelta

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from ..db import get_db
from ..services import horario_service, notification_service as notif, presenca_service
from ..services.auth_service import aluno_required
from .. import utils

bp = Blueprint("aluno", __name__, url_prefix="/aluno")

_MESES = ["", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _me():
    return get_db().execute(
        "SELECT al.*, t.nome AS turma FROM alunos al LEFT JOIN turmas t ON t.id = al.turma_id WHERE al.id = ?",
        (session["user_id"],)).fetchone()


@bp.route("/")
@bp.route("/dashboard")
@aluno_required
def dashboard():
    al = _me()
    db = get_db()
    hoje = utils.today()
    acessos_hoje = db.execute("SELECT tipo, timestamp FROM acessos WHERE aluno_id = ? AND date(timestamp) = ? ORDER BY timestamp, id",
                              (al["id"], hoje.isoformat())).fetchall()
    ultimo = acessos_hoje[-1] if acessos_hoje else None
    hoje_pres = db.execute("SELECT * FROM presencas WHERE aluno_id = ? AND data = ?", (al["id"], hoje.isoformat())).fetchone()
    hor_hoje = horario_service.horario_do_dia(al["turma_id"], hoje.weekday())
    proximo, data_prox = (horario_service.proximo_dia_com_aulas(al["turma_id"], utils.now()) if al["turma_id"] else (None, None))
    mes_ini = hoje.replace(day=1).isoformat()
    return render_template("aluno/dashboard.html", al=al, ultimo=ultimo, hoje_pres=hoje_pres, hor_hoje=hor_hoje, proximo=proximo,
                           data_prox=data_prox, hoje=hoje, mes=presenca_service.contagens(al["id"], mes_ini, hoje.isoformat()),
                           total=presenca_service.contagens(al["id"]), notifs=notif.list_for("aluno", al["id"], limit=4),
                           dias=utils.DIAS_SEMANA, rotulos=presenca_service.ROTULOS)


@bp.route("/horario")
@aluno_required
def horario():
    al = _me()
    return render_template("aluno/horario.html", al=al, hor=horario_service.horario_turma(al["turma_id"]) if al["turma_id"] else {},
                           dias=utils.DIAS_SEMANA, hoje=utils.today().weekday())


@bp.route("/assiduidade")
@aluno_required
def assiduidade():
    al = _me()
    hoje = utils.today()
    try:
        ano, mes = [int(x) for x in (request.args.get("mes") or hoje.strftime("%Y-%m")).split("-")]
        date(ano, mes, 1)
    except (ValueError, TypeError):
        ano, mes = hoje.year, hoje.month
    dados = presenca_service.mes_do_aluno(al["id"], ano, mes)
    hor = horario_service.horario_turma(al["turma_id"]) if al["turma_id"] else {}
    semanas = calendar.Calendar(0).monthdatescalendar(ano, mes)
    ant = (date(ano, mes, 1) - timedelta(days=1)).strftime("%Y-%m")
    seg = (date(ano, mes, 28) + timedelta(days=5)).replace(day=1).strftime("%Y-%m")
    detalhe = [v for k, v in sorted(dados.items(), reverse=True) if v["estado"] != "presente"]
    ini, fim = f"{ano:04d}-{mes:02d}-01", f"{ano:04d}-{mes:02d}-31"
    return render_template("aluno/assiduidade.html", al=al, semanas=semanas, dados=dados, hor=hor, mes=mes, ano=ano, mes_nome=_MESES[mes],
                           ant=ant, seg=seg if seg <= hoje.strftime("%Y-%m") else None, hoje=hoje, detalhe=detalhe,
                           cont=presenca_service.contagens(al["id"], ini, fim), rotulos=presenca_service.ROTULOS)


@bp.route("/acessos")
@aluno_required
def acessos():
    rows = get_db().execute("SELECT * FROM acessos WHERE aluno_id = ? ORDER BY timestamp DESC, id DESC LIMIT 60", (session["user_id"],)).fetchall()
    return render_template("aluno/acessos.html", rows=rows)


@bp.route("/justificacoes", methods=["GET", "POST"])
@aluno_required
def justificacoes():
    al = _me()
    db = get_db()
    if request.method == "POST":
        di = request.form.get("data_inicio", "")
        df = request.form.get("data_fim") or di
        motivo = utils.clean(request.form.get("motivo"), 400)
        if not utils.valid_date(di) or not utils.valid_date(df) or df < di:
            flash("Datas inválidas.", "error")
        elif not motivo:
            flash("Indique o motivo.", "error")
        else:
            db.execute("INSERT INTO justificacoes (aluno_id, data_inicio, data_fim, motivo) VALUES (?,?,?,?)", (al["id"], di, df, motivo))
            db.commit()
            notif.notify("admin", None, "Pedido de justificação",
                         f"{al['nome_completo']} ({al['turma'] or 's/ turma'}) pediu justificação de {di} a {df}: {motivo}", "info")
            flash("Pedido enviado. Aguarde a decisão.", "success")
            return redirect(url_for("aluno.justificacoes"))
    rows = db.execute("SELECT * FROM justificacoes WHERE aluno_id = ? ORDER BY created_at DESC", (al["id"],)).fetchall()
    return render_template("aluno/justificacoes.html", rows=rows)


@bp.route("/notificacoes")
@aluno_required
def notificacoes():
    uid = session["user_id"]
    rows = notif.list_for("aluno", uid, limit=100)
    notif.mark_all_read("aluno", uid)
    return render_template("notificacoes.html", rows=rows)


@bp.route("/privacidade")
@aluno_required
def privacidade():
    from ..services.face_service import contar_amostras
    al = _me()
    return render_template("aluno/privacidade.html", al=al, amostras=contar_amostras(al["id"]))
