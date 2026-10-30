"""Horários: por turma e dia, só a hora de ENTRADA e a hora de SAÍDA."""
from flask import flash, redirect, render_template, request, url_for

from . import bp
from ...db import get_db
from ...services import horario_service
from ...services.auth_service import admin_required
from ... import utils


@bp.route("/horarios", methods=["GET", "POST"])
@admin_required
def horarios():
    db = get_db()
    turmas = db.execute("SELECT id, nome FROM turmas ORDER BY nome").fetchall()
    turma_id = request.values.get("turma_id", type=int) or (turmas[0]["id"] if turmas else None)

    if request.method == "POST" and turma_id:
        dias, erros = {}, []
        for d in range(7):
            if request.form.get(f"ativo_{d}") != "on":
                dias[d] = None
                continue
            ent, sai = request.form.get(f"entrada_{d}", ""), request.form.get(f"saida_{d}", "")
            erro = horario_service.validar(ent, sai)
            if erro:
                erros.append(f"{utils.DIAS_SEMANA[d]}: {erro}")
            else:
                dias[d] = (ent, sai)
        if erros:
            for e in erros:
                flash(e, "error")
        else:
            horario_service.guardar_horario(turma_id, dias)
            msg = "Horário guardado."
            if request.form.get("aplicar_todas") == "on":
                n = horario_service.copiar_para_outras_turmas(turma_id)
                msg += f" Aplicado também às outras {n} turma(s)."
            flash(msg, "success")
        return redirect(url_for("admin.horarios", turma_id=turma_id))

    return render_template("admin/horarios.html", turmas=turmas, turma_id=turma_id,
                           atual=horario_service.horario_turma(turma_id) if turma_id else {},
                           todos=horario_service.todos_os_horarios(), dias=utils.DIAS_SEMANA)
