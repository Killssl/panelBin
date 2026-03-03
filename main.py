from datetime import datetime
from flask import Flask, jsonify, send_from_directory, Response

from config import PORT, LOCAL_TZ, APP_PREFIX
from routes_rotations import bp as bp_rotations
from routes_panel     import bp as bp_panel
from routes_reports   import bp as bp_reports


app = Flask(__name__, static_folder=".", static_url_path="")


# ---------- CORS ----------

@app.after_request
def _after(resp):
    resp.headers["Access-Control-Allow-Origin"]  = "*"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, api-key, Api-Key, X-API-Key, Authorization"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return resp


# ---------- Static ----------

@app.get("/")
def index():
    with open("index.html", "r", encoding="utf-8") as f:
        html = f.read()
    # Инжектируем префикс чтобы JS знал под каким путём работает приложение
    inject = f'<script>window.APP_PREFIX = "{APP_PREFIX}";</script>'
    html = html.replace("</head>", inject + "\n</head>", 1)
    return Response(html, mimetype="text/html")

@app.get("/styles.css")
def styles():
    return send_from_directory(".", "styles.css")

@app.get("/app.js")
def js():
    return send_from_directory(".", "app.js")


# ---------- Ping ----------

@app.get("/api/_ping")
def ping():
    from config import BINOM_BASE
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


# ---------- Run ----------

if __name__ == "__main__":
    if APP_PREFIX:
        from werkzeug.middleware.dispatcher import DispatcherMiddleware
        from werkzeug.serving import run_simple
        from flask import Flask as _Flask, redirect
        _root = _Flask("root")

        @_root.route("/")
        def _redirect_root():
            return redirect(APP_PREFIX + "/")

        wrapped = DispatcherMiddleware(_root, {APP_PREFIX: app})
        run_simple("0.0.0.0", PORT, wrapped, use_reloader=False)
    else:
        app.run(host="0.0.0.0", port=PORT, debug=False)