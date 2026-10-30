"""Notificações in-app e fila de emails para encarregados de educação."""
from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional

from flask import current_app

from ..db import get_db
from .. import utils


def notify(dest_tipo: str, dest_id: Optional[int], titulo: str, mensagem: str, tipo: str = "info") -> None:
    db = get_db()
    db.execute(
        "INSERT INTO notificacoes (destinatario_tipo, destinatario_id, titulo, mensagem, tipo) VALUES (?,?,?,?,?)",
        (dest_tipo, dest_id, titulo, mensagem, tipo),
    )
    db.commit()


def _scope(dest_tipo: str, dest_id: Optional[int]):
    if dest_tipo == "admin":
        return "destinatario_tipo = 'admin'", ()
    return "destinatario_tipo = ? AND destinatario_id = ?", (dest_tipo, dest_id)


def list_for(dest_tipo: str, dest_id: Optional[int], limit: int = 50):
    where, args = _scope(dest_tipo, dest_id)
    return get_db().execute(
        f"SELECT * FROM notificacoes WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ?",
        (*args, limit),
    ).fetchall()


def unread_count(dest_tipo: str, dest_id: Optional[int]) -> int:
    where, args = _scope(dest_tipo, dest_id)
    row = get_db().execute(
        f"SELECT COUNT(*) AS c FROM notificacoes WHERE {where} AND lida = 0", args
    ).fetchone()
    return int(row["c"])


def mark_all_read(dest_tipo: str, dest_id: Optional[int]) -> None:
    where, args = _scope(dest_tipo, dest_id)
    db = get_db()
    db.execute(f"UPDATE notificacoes SET lida = 1 WHERE {where}", args)
    db.commit()


# ------------------------------ Email ------------------------------
def enfileirar_email_encarregado(aluno, assunto: str, corpo: str) -> bool:
    """Põe um email na fila (outbox). Nunca bloqueia nem envia na hora — o envio é feito
    por scripts/enviar_emails.py ou pelo botão no painel, para não atrasar a porta."""
    destino = (aluno["encarregado_email"] or "").strip() if aluno else ""
    if not destino:
        return False
    db = get_db()
    db.execute("INSERT INTO outbox_email (destinatario, assunto, corpo) VALUES (?,?,?)",
               (destino, assunto, corpo))
    db.commit()
    return True


def reenviar_erros() -> int:
    db = get_db()
    n = db.execute("UPDATE outbox_email SET estado = 'pendente', erro = NULL WHERE estado = 'erro'").rowcount
    db.commit()
    return n


def enviar_pendentes(limit: int = 50) -> dict:
    """Envia os emails pendentes via SMTP (sem SMTP configurado, não faz nada).
    Cada email é "reservado" antes de enviar, por isso dois processos em simultâneo não duplicam envios."""
    cfg = current_app.config
    db = get_db()
    if not cfg.get("SMTP_HOST"):
        n = db.execute("SELECT COUNT(*) FROM outbox_email WHERE estado='pendente'").fetchone()[0]
        return {"enviados": 0, "erros": 0, "pendentes": n, "smtp": False}

    rows = db.execute("SELECT * FROM outbox_email WHERE estado='pendente' ORDER BY id LIMIT ?", (limit,)).fetchall()
    if not rows:
        return {"enviados": 0, "erros": 0, "pendentes": 0, "smtp": True}
    try:
        srv = smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"], timeout=15)
        if cfg.get("SMTP_TLS"):
            srv.starttls()
        if cfg.get("SMTP_USER"):
            srv.login(cfg["SMTP_USER"], cfg["SMTP_PASSWORD"] or "")
    except Exception as e:  # noqa: BLE001
        return {"enviados": 0, "erros": 0, "pendentes": len(rows), "smtp": True, "erro": f"Ligação ao SMTP falhou: {e}"}
    enviados = erros = 0
    try:
        for r in rows:
            reservado = db.execute("UPDATE outbox_email SET estado='enviado', enviado_em=? WHERE id=? AND estado='pendente'",
                                   (utils.iso(utils.now()), r["id"])).rowcount
            db.commit()
            if not reservado:          # outro processo já o apanhou
                continue
            msg = EmailMessage()
            msg["From"], msg["To"], msg["Subject"] = cfg["SMTP_FROM"], r["destinatario"], r["assunto"]
            msg.set_content(r["corpo"])
            try:
                srv.send_message(msg)
                enviados += 1
            except Exception as e:  # noqa: BLE001
                db.execute("UPDATE outbox_email SET estado='erro', erro=?, enviado_em=NULL WHERE id=?", (str(e)[:200], r["id"]))
                db.commit()
                erros += 1
    finally:
        try:
            srv.quit()
        except Exception:  # noqa: BLE001
            pass
    return {"enviados": enviados, "erros": erros, "pendentes": 0, "smtp": True}
