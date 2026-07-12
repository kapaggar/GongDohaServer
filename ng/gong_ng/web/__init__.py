"""Flask admin UI + JSON API (design §8)."""
from __future__ import annotations

from datetime import timedelta

from flask import Flask, g, jsonify, redirect, request, session, url_for

from .. import db
from ..model import Settings
from ..runtime import AppContext

OPEN_ENDPOINTS = {"ui.login", "api.healthz", "static"}


def create_app(ctx: AppContext) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=ctx.config.secret_key_path.read_text().strip(),
        PERMANENT_SESSION_LIFETIME=timedelta(hours=ctx.config.web.session_hours),
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        MAX_CONTENT_LENGTH=64 * 1024 * 1024,  # backup restore uploads
    )
    app.extensions["gong"] = ctx

    from . import auth
    from .routes_api import api
    from .routes_ui import ui

    app.register_blueprint(ui)
    app.register_blueprint(api)

    @app.before_request
    def _setup():
        g.ctx = ctx
        g.conn = db.connect(ctx.db_path)
        g.settings = Settings(g.conn)
        endpoint = request.endpoint or ""
        if endpoint in OPEN_ENDPOINTS:
            return None
        if not session.get("auth"):
            if request.blueprint == "api":
                return jsonify(error="not authenticated"), 401
            return redirect(url_for("ui.login"))
        if request.method in ("POST", "PUT", "DELETE"):
            token = (request.headers.get("X-CSRF-Token")
                     or request.form.get("csrf", ""))
            if not token or token != session.get("csrf"):
                if request.blueprint == "api":
                    return jsonify(error="bad csrf token"), 403
                return "CSRF token mismatch", 403
        return None

    @app.teardown_appcontext
    def _teardown(exc):
        conn = g.pop("conn", None)
        if conn is not None:
            conn.close()

    @app.context_processor
    def _globals():
        from .. import clock as clockmod
        now = ctx.clock.now()
        return dict(
            now=now,
            tz=ctx.config.time.timezone,
            csrf=auth.csrf_token(),
            clock_invalid=clockmod.clock_invalid(g.conn),
            authed=bool(session.get("auth")),
        )

    return app
