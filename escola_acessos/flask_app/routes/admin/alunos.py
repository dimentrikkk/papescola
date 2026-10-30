"""Gestão de alunos, consentimento biométrico e recolha de rostos."""
import secrets
import sqlite3

from flask import flash, jsonify, redirect, render_template, request, url_for

from . import bp
from ...db import get_db
from ...services import acesso_service, face_service, media_service
from ...services.auth_service import admin_required, hash_password
from ... import utils


def _turmas():
    return get_db().execute("SELECT id, nome FROM turmas ORDER BY nome").fetchall()


def _ler_form(f):
    """Valida os campos do formulário. Devolve (dados, erro)."""
    d = {
        "numero_processo": utils.clean(f.get("numero_processo"), 30),
        "nome_completo": utils.clean(f.get("nome_completo"), 120),
        "data_nascimento": utils.clean(f.get("data_nascimento"), 10) or None,
        "email": utils.clean(f.get("email"), 120).lower(),
        "telefone": utils.clean(f.get("telefone"), 30) or None,
        "turma_id": f.get("turma_id", type=int),
        "encarregado_nome": utils.clean(f.get("encarregado_nome"), 120) or None,
        "encarregado_email": utils.clean(f.get("encarregado_email"), 120).lower() or None,
        "encarregado_telefone": utils.clean(f.get("encarregado_telefone"), 30) or None,
    }
    if not d["numero_processo"] or not d["nome_completo"]:
        return d, "Nº de processo e nome são obrigatórios."
    if not utils.valid_email(d["email"]):
        return d, "Email do aluno inválido."
    if d["encarregado_email"] and not utils.valid_email(d["encarregado_email"]):
        return d, "Email do encarregado inválido."
    if d["data_nascimento"] and not utils.valid_date(d["data_nascimento"]):
        return d, "Data de nascimento inválida."
    return d, None


@bp.route("/alunos")
@admin_required
def alunos_list():
    q = utils.clean(request.args.get("q"), 60)
    turma_id = request.args.get("turma_id", type=int)
    sql = """SELECT al.*, t.nome AS turma,
                    (SELECT COUNT(*) FROM face_encodings fe WHERE fe.aluno_id = al.id) AS amostras
               FROM alunos al LEFT JOIN turmas t ON t.id = al.turma_id WHERE 1=1"""
    args = []
    if q:
        sql += " AND (al.nome_completo LIKE ? OR al.numero_processo LIKE ? OR al.email LIKE ?)"
        args += [f"%{q}%"] * 3
    if turma_id:
        sql += " AND al.turma_id = ?"
        args.append(turma_id)
    rows = get_db().execute(sql + " ORDER BY al.nome_completo LIMIT 500", args).fetchall()
    return render_template("admin/alunos_list.html", rows=rows, turmas=_turmas(), q=q, turma_id=turma_id)


@bp.route("/alunos/novo", methods=["GET", "POST"])
@admin_required
def alunos_new():
    if request.method == "POST":
        d, erro = _ler_form(request.form)
        if erro:
            flash(erro, "error")
            return render_template("admin/alunos_form.html", aluno=d, turmas=_turmas(), novo=True), 400
        temp = request.form.get("password") or secrets.token_urlsafe(6)
        try:
            db = get_db()
            db.execute(
                """INSERT INTO alunos (numero_processo, nome_completo, data_nascimento, email, telefone, turma_id,
                       encarregado_nome, encarregado_email, encarregado_telefone, password_hash, must_change_password)
                   VALUES (:numero_processo,:nome_completo,:data_nascimento,:email,:telefone,:turma_id,
                       :encarregado_nome,:encarregado_email,:encarregado_telefone,:ph,1)""",
                {**d, "ph": hash_password(temp)},
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Já existe um aluno com esse nº de processo ou email.", "error")
            return render_template("admin/alunos_form.html", aluno=d, turmas=_turmas(), novo=True), 400
        flash(f"Aluno criado. Password temporária (mostrada só agora): {temp}", "success")
        return redirect(url_for("admin.alunos_list"))
    return render_template("admin/alunos_form.html", aluno={}, turmas=_turmas(), novo=True)


@bp.route("/alunos/<int:aid>", methods=["GET", "POST"])
@admin_required
def alunos_edit(aid):
    db = get_db()
    aluno = db.execute("SELECT * FROM alunos WHERE id = ?", (aid,)).fetchone()
    if not aluno:
        flash("Aluno não encontrado.", "error")
        return redirect(url_for("admin.alunos_list"))
    if request.method == "POST":
        d, erro = _ler_form(request.form)
        if erro:
            flash(erro, "error")
            return render_template("admin/alunos_form.html", aluno={**dict(aluno), **d}, turmas=_turmas(), novo=False), 400
        ativo = 1 if request.form.get("ativo") == "on" else 0
        try:
            db.execute(
                """UPDATE alunos SET numero_processo=:numero_processo, nome_completo=:nome_completo,
                       data_nascimento=:data_nascimento, email=:email, telefone=:telefone, turma_id=:turma_id,
                       encarregado_nome=:encarregado_nome, encarregado_email=:encarregado_email,
                       encarregado_telefone=:encarregado_telefone, ativo=:ativo WHERE id=:id""",
                {**d, "ativo": ativo, "id": aid},
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash("Já existe outro aluno com esse nº de processo ou email.", "error")
            return render_template("admin/alunos_form.html", aluno={**dict(aluno), **d}, turmas=_turmas(), novo=False), 400
        flash("Aluno atualizado.", "success")
        return redirect(url_for("admin.alunos_list"))
    return render_template("admin/alunos_form.html", aluno=aluno, turmas=_turmas(), novo=False,
                           amostras=face_service.contar_amostras(aid))


@bp.post("/alunos/<int:aid>/apagar")
@admin_required
def alunos_delete(aid):
    db = get_db()
    al = db.execute("SELECT foto_perfil FROM alunos WHERE id = ?", (aid,)).fetchone()
    if al:
        media_service.apagar_ficheiro(al["foto_perfil"])
        db.execute("DELETE FROM alunos WHERE id = ?", (aid,))  # apaga em cascata rostos, acessos e presenças
        db.commit()
        flash("Aluno e todos os seus dados (incluindo biométricos) foram apagados.", "success")
    return redirect(url_for("admin.alunos_list"))


@bp.post("/alunos/<int:aid>/password")
@admin_required
def alunos_reset_password(aid):
    temp = secrets.token_urlsafe(6)
    db = get_db()
    db.execute("UPDATE alunos SET password_hash = ?, must_change_password = 1 WHERE id = ?", (hash_password(temp), aid))
    db.commit()
    flash(f"Nova password temporária (mostrada só agora): {temp}", "success")
    return redirect(url_for("admin.alunos_edit", aid=aid))


@bp.post("/alunos/<int:aid>/foto")
@admin_required
def alunos_foto(aid):
    f = request.files.get("foto")
    if not f or not f.filename:
        flash("Escolha uma imagem.", "error")
        return redirect(url_for("admin.alunos_edit", aid=aid))
    db = get_db()
    antigo = db.execute("SELECT foto_perfil FROM alunos WHERE id = ?", (aid,)).fetchone()
    try:
        nome = media_service.guardar_avatar(aid, f.read())
    except face_service.ImagemInvalida as e:
        flash(str(e), "error")
        return redirect(url_for("admin.alunos_edit", aid=aid))
    db.execute("UPDATE alunos SET foto_perfil = ? WHERE id = ?", (nome, aid))
    db.commit()
    if antigo:
        media_service.apagar_ficheiro(antigo["foto_perfil"])
    flash("Foto atualizada.", "success")
    return redirect(url_for("admin.alunos_edit", aid=aid))


# ------------------------- consentimento + rosto -------------------------
@bp.post("/alunos/<int:aid>/consentimento")
@admin_required
def alunos_consentimento(aid):
    db = get_db()
    if request.form.get("acao") == "dar":
        db.execute("UPDATE alunos SET consentimento_biometrico = 1, consentimento_data = ? WHERE id = ?",
                   (utils.iso(utils.now()), aid))
        flash("Consentimento biométrico registado.", "success")
    else:
        db.execute("UPDATE alunos SET consentimento_biometrico = 0, consentimento_data = NULL WHERE id = ?", (aid,))
        face_service.apagar_amostras(aid)
        flash("Consentimento retirado: os dados biométricos foram apagados.", "success")
    db.commit()
    return redirect(url_for("admin.alunos_edit", aid=aid))


@bp.route("/alunos/<int:aid>/rosto")
@admin_required
def alunos_rosto(aid):
    aluno = get_db().execute("SELECT * FROM alunos WHERE id = ?", (aid,)).fetchone()
    if not aluno:
        return redirect(url_for("admin.alunos_list"))
    return render_template("admin/alunos_rosto.html", aluno=aluno, amostras=face_service.contar_amostras(aid))


@bp.post("/alunos/<int:aid>/rosto/amostra")
@admin_required
def alunos_rosto_amostra(aid):
    """Aceita uma imagem da webcam (JSON data-URL) ou ficheiros carregados (multipart)."""
    try:
        imagens = []
        if request.files:
            for f in request.files.getlist("fotos"):
                imagens.append(face_service.rgb_from_bytes(f.read()))
        else:
            imagens.append(face_service.rgb_from_data_url((request.get_json(silent=True) or {}).get("image", "")))
        if not imagens:
            return jsonify({"ok": False, "error": "Nenhuma imagem recebida."}), 400
        total, erros = 0, []
        for img in imagens:
            try:
                total = face_service.adicionar_amostra(aid, img)
            except (face_service.AmostraRejeitada, face_service.ConsentimentoEmFalta) as e:
                erros.append(str(e))
                if isinstance(e, face_service.ConsentimentoEmFalta):
                    break
        if erros and not total:
            return jsonify({"ok": False, "error": erros[0]}), 200
        return jsonify({"ok": True, "samples": face_service.contar_amostras(aid), "avisos": erros})
    except face_service.ImagemInvalida as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@bp.post("/alunos/<int:aid>/rosto/apagar")
@admin_required
def alunos_rosto_apagar(aid):
    face_service.apagar_amostras(aid)
    return jsonify({"ok": True})


@bp.post("/alunos/<int:aid>/acesso-manual")
@admin_required
def alunos_acesso_manual(aid):
    tipo = request.form.get("tipo")
    try:
        r = acesso_service.registar_manual(aid, tipo)
        flash(f"Registo manual: {r.mensagem or tipo}", "success")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(request.referrer or url_for("admin.alunos_list"))
