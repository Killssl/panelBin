from datetime import datetime
from functools import wraps
from datetime import datetime, timedelta
from flask import Flask, jsonify, Response, render_template, session, redirect, request, make_response

from app.utils.config import PORT, LOCAL_TZ, APP_PREFIX, BINOM_BASE, ADMIN_LOGIN, ADMIN_PASSWORD, FLASK_SECRET_KEY, SESSION_LIFETIME_DAYS
from app.routes.rotations import bp as bp_rotations
from app.routes.panel     import bp as bp_panel
from app.routes.reports   import bp as bp_reports
from app.routes.partner   import bp as bp_partner


app = Flask(
    __name__,
    static_folder="static",
    static_url_path="/static",
    template_folder="templates",
)

app.secret_key = FLASK_SECRET_KEY
app.config["SESSION_COOKIE_HTTPONLY"]      = True
app.config["SESSION_COOKIE_SAMESITE"]      = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"]   = timedelta(days=SESSION_LIFETIME_DAYS)


# ---------- CORS ----------

@app.after_request
def _after(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, api-key, Api-Key, X-API-Key, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return resp


# ---------- Auth ----------

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(APP_PREFIX + "/login")
        # Если сессия из прошлого месяца — сбрасываем
        if session.get("month") != datetime.now().strftime("%Y-%m"):
            session.clear()
            return redirect(APP_PREFIX + "/login")
        return fn(*args, **kwargs)
    return wrapper


# ---------- Login / Logout ----------

@app.get("/login")
def login_page():
    if session.get("logged_in"):
        return redirect(APP_PREFIX + "/")
    return render_template("login.html", app_prefix=APP_PREFIX)


@app.post("/login")
def login_post():
    body = request.get_json(silent=True) or {}
    username = str(body.get("username", "")).strip()
    password = str(body.get("password", ""))

    if username == ADMIN_LOGIN and password == ADMIN_PASSWORD:
        session.permanent    = True
        session["logged_in"] = True
        session["username"]  = username
        session["month"]     = datetime.now().strftime("%Y-%m")
        return jsonify({"ok": True})

    return make_response(jsonify({"ok": False, "error": "Неверный логин или пароль"}), 401)


@app.get("/logout")
def logout():
    session.clear()
    return redirect(APP_PREFIX + "/login")


# ---------- Pages ----------

@app.get("/")
@login_required
def index():
    html = render_template("index.html")
    inject = f'<script>window.APP_PREFIX = "{APP_PREFIX}";</script>'
    html = html.replace("</head>", inject + "\n</head>", 1)
    return Response(html, mimetype="text/html")

@app.get("/partner")
def partner_page():
    return render_template("partner.html")

@app.get("/favicon.ico")
def favicon():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><text y=".9em" font-size="90">A</text></svg>'
    return Response(svg, mimetype="image/svg+xml")


# ---------- Ping ----------

@app.get("/api/_ping")
def ping():
    return jsonify({
        "ok": True,
        "server_time_local": datetime.now(LOCAL_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "binom_base": BINOM_BASE,
        "app_prefix": APP_PREFIX,
    })


# ---------- Blueprints ----------

app.register_blueprint(bp_rotations)
app.register_blueprint(bp_panel)
app.register_blueprint(bp_reports)
app.register_blueprint(bp_partner)


# ---------- Scheduler ----------

try:
    from app.services.scheduler import init_scheduler
    init_scheduler(app)
except Exception as _sch_err:
    import logging
    logging.getLogger("scheduler").warning(f"Scheduler not started: {_sch_err}")


# ---------- Run ----------

if __name__ == "__main__":
    if APP_PREFIX:
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.serving import run_simple
        from flask import Flask as _Flask
        _root = _Flask("root")

        @_root.route("/")
        def _redirect_root():
            return redirect(APP_PREFIX + "/")

        wrapped = DispatcherMiddleware(_root, {APP_PREFIX: app})
        run_simple("0.0.0.0", PORT, wrapped, use_reloader=False)
    else:
        app.run(host="0.0.0.0", port=PORT, debug=False)