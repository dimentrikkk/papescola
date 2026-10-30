"""CSRF (sem dependências extra), cabeçalhos de segurança e hook de mudança de password."""
from __future__ import annotations

import secrets

from flask import abort, request, session, redirect, url_for
from markupsafe import Markup

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def _token() -> str:
    tok = session.get("_csrf")
    if not tok:
        tok = secrets.token_urlsafe(32)
        session["_csrf"] = tok
    return tok


def init_security(app) -> None:
    @app.before_request
    def _csrf_protect():
        if request.method in _UNSAFE and not app.config.get("CSRF_DISABLED"):
            sent = request.form.get("csrf_token") or request.headers.get("X-CSRFToken") or ""
            expected = session.get("_csrf") or ""
            if not expected or not secrets.compare_digest(sent, expected):
                abort(400, "Pedido inválido (token CSRF em falta ou incorreto). Recarregue a página.")

    @app.before_request
    def _force_password_change():
        if session.get("must_change") and request.endpoint not in (
            "auth.conta", "auth.logout", "static", None
        ):
            return redirect(url_for("auth.conta"))

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(self), microphone=()")
        return resp

    @app.context_processor
    def _csrf_ctx():
        def csrf_field():
            return Markup(f'<input type="hidden" name="csrf_token" value="{_token()}">')
        return {"csrf_token": _token, "csrf_field": csrf_field}
