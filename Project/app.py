from pathlib import Path
from datetime import timedelta
import os
from functools import wraps

from flask import Flask, jsonify, redirect, render_template, request, send_from_directory, session

from database import (
    DatabaseConfigurationError,
    DuplicateBusinessIdError,
    authenticate_ministry,
    authenticate_startup,
    save_startup_registration,
)


ROOT = Path(__file__).parent
app = Flask(__name__, static_folder=str(ROOT), template_folder=str(ROOT))
app.secret_key = os.getenv("STARTUP_CONNECT_SESSION_SECRET", "development-only-change-this-session-secret")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("STARTUP_CONNECT_COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=2),
)


def session_required(role: str):
    """Require an authenticated Flask session with the expected role."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if session.get("role") != role:
                return redirect("/login")
            return view(*args, **kwargs)
        return wrapped
    return decorator


@app.get("/")
def home():
    return render_template("index.htm")


@app.get("/pages.css")
def pages_stylesheet():
    return send_from_directory(ROOT, "pages.css", mimetype="text/css")


@app.get("/<page>")
def page(page):
    pages = {"directory", "how-it-works", "resources", "login", "join", "register"}
    if page in pages:
        return render_template(f"{page}.htm")
    return ("Page not found", 404)


@app.get("/challenges")
def challenges():
    return redirect("/#challenges")


@app.post("/api/register")
def register():
    data = request.get_json(silent=True) or request.form.to_dict()
    try:
        save_startup_registration(data)
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400
    except DuplicateBusinessIdError:
        return jsonify({"ok": False, "message": "That business ID is already in use."}), 409
    except DatabaseConfigurationError as error:
        return jsonify({"ok": False, "message": str(error)}), 503
    except Exception:
        app.logger.exception("Startup registration failed")
        return jsonify({"ok": False, "message": "Registration could not be saved. Please try again."}), 500
    return jsonify({"ok": True, "message": "Your startup application has been received."})


@app.post("/api/login")
def login():
    data = request.get_json(silent=True) or request.form.to_dict()
    role = data.get("role", "startup")
    try:
        if role == "ministry":
            valid = authenticate_ministry(data.get("ministry_id", ""), data.get("auth_code", ""))
            landing_page = "/ministry-portal"
        else:
            valid = authenticate_startup(data.get("business_id", ""), data.get("gstin", ""), data.get("password", ""))
            landing_page = "/startup-portal"
    except (DatabaseConfigurationError, ValueError) as error:
        return jsonify({"ok": False, "message": str(error)}), 503
    if not valid:
        return jsonify({"ok": False, "message": "The credentials could not be verified."}), 401
    session.clear()
    session.permanent = True
    session["role"] = role
    return jsonify({"ok": True, "message": "Sign in successful.", "redirect": landing_page})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/startup-portal")
@session_required("startup")
def startup_portal():
    return render_template("startup-portal.htm")


@app.get("/ministry-portal")
@session_required("ministry")
def ministry_portal():
    return render_template("ministry-portal.htm")


@app.get("/api/network")
def network():
    return jsonify({"departments": 42, "startups": 186, "pilots_scaled": 27, "active_pilots": 18})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)