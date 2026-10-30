"""Cursos, turmas, disciplinas e professores."""
import secrets
import sqlite3

from flask import flash, redirect, render_template, request, url_for

from . import bp
from ...db import get_db
from ...services.auth_service import admin_required, hash_password
from ... import utils


@bp.route("/turmas", methods=["GET", "POST"])
@admin_required
def turmas():
    db = get_db()
    if request.method == "POST":
        acao = request.form.get("acao")
        try:
            if acao == "criar_curso":
                nome = utils.clean(request.form.get("nome"), 80)
                if not nome:
                    raise ValueError("Indique o nome do curso.")
                db.execute("INSERT INTO cursos (nome, descricao) VALUES (?,?)",
                           (nome, utils.clean(request.form.get("descricao"), 200) or None))
                flash("Curso criado.", "success")
            elif acao == "apagar_curso":
                db.execute("DELETE FROM cursos WHERE id = ?", (request.form.get("id", type=int),))
                flash("Curso removido.", "success")
            elif acao == "criar_turma":
                nome = utils.clean(request.form.get("nome"), 40)
                if not nome:
                    raise ValueError("Indique o nome da turma.")
                db.execute("INSERT INTO turmas (nome, curso_id, ano_letivo, diretor_turma_id) VALUES (?,?,?,?)",
                           (nome, request.form.get("curso_id", type=int) or None,
                            utils.clean(request.form.get("ano_letivo"), 20) or None,
                            request.form.get("diretor_turma_id", type=int) or None))
                flash("Turma criada.", "success")
            elif acao == "atualizar_turma":
                db.execute("UPDATE turmas SET curso_id = ?, ano_letivo = ?, diretor_turma_id = ? WHERE id = ?",
                           (request.form.get("curso_id", type=int) or None,
                            utils.clean(request.form.get("ano_letivo"), 20) or None,
                            request.form.get("diretor_turma_id", type=int) or None,
                            request.form.get("id", type=int)))
                flash("Turma atualizada.", "success")
            elif acao == "apagar_turma":
                db.execute("DELETE FROM turmas WHERE id = ?", (request.form.get("id", type=int),))
                flash("Turma removida (o horário é apagado e os alunos ficam sem turma).", "success")
            db.commit()
        except sqlite3.IntegrityError:
            flash("Já existe um registo com esse nome.", "error")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("admin.turmas"))

    cursos = db.execute("SELECT c.*, (SELECT COUNT(*) FROM turmas t WHERE t.curso_id = c.id) AS n_turmas FROM cursos c ORDER BY c.nome").fetchall()
    turmas_ = db.execute(
        """SELECT t.*, c.nome AS curso, u.nome AS diretor,
                  (SELECT COUNT(*) FROM horarios_turma h WHERE h.turma_id = t.id) AS n_dias,
                  (SELECT COUNT(*) FROM alunos a WHERE a.turma_id = t.id AND a.ativo = 1) AS n_alunos
             FROM turmas t LEFT JOIN cursos c ON c.id = t.curso_id LEFT JOIN utilizadores u ON u.id = t.diretor_turma_id
            ORDER BY t.nome""").fetchall()
    professores = db.execute("SELECT id, nome FROM utilizadores WHERE papel = 'professor' AND ativo = 1 ORDER BY nome").fetchall()
    return render_template("admin/turmas.html", cursos=cursos, turmas=turmas_, professores=professores)


@bp.route("/professores", methods=["GET", "POST"])
@admin_required
def professores():
    db = get_db()
    if request.method == "POST":
        acao = request.form.get("acao")
        try:
            if acao == "criar":
                nome = utils.clean(request.form.get("nome"), 120)
                email = utils.clean(request.form.get("email"), 120).lower()
                papel = request.form.get("papel") if request.form.get("papel") in ("professor", "admin") else "professor"
                if not nome or not utils.valid_email(email):
                    raise ValueError("Nome e email válido são obrigatórios.")
                temp = secrets.token_urlsafe(6)
                db.execute("INSERT INTO utilizadores (nome, email, password_hash, papel, must_change_password) VALUES (?,?,?,?,1)",
                           (nome, email, hash_password(temp), papel))
                flash(f"Utilizador criado. Password temporária (mostrada só agora): {temp}", "success")
            elif acao == "reset":
                temp = secrets.token_urlsafe(6)
                db.execute("UPDATE utilizadores SET password_hash = ?, must_change_password = 1 WHERE id = ?",
                           (hash_password(temp), request.form.get("id", type=int)))
                flash(f"Nova password temporária (mostrada só agora): {temp}", "success")
            elif acao == "ativar":
                db.execute("UPDATE utilizadores SET ativo = 1 - ativo WHERE id = ? AND papel != 'admin'", (request.form.get("id", type=int),))
                flash("Estado atualizado.", "success")
            elif acao == "apagar":
                db.execute("DELETE FROM utilizadores WHERE id = ? AND papel = 'professor'", (request.form.get("id", type=int),))
                flash("Professor removido (as suas aulas ficam sem professor).", "success")
            db.commit()
        except sqlite3.IntegrityError:
            flash("Já existe um utilizador com esse email.", "error")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("admin.professores"))
    rows = db.execute("SELECT * FROM utilizadores ORDER BY papel, nome").fetchall()
    return render_template("admin/professores.html", rows=rows)
