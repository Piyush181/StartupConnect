from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, send_from_directory


ROOT = Path(__file__).parent
app = Flask(__name__, static_folder=str(ROOT), template_folder=str(ROOT))


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
    return jsonify({"ok": True, "message": "Your startup application has been received."})


@app.post("/api/login")
def login():
    return jsonify({"ok": True, "message": "Demo sign-in accepted"})


@app.get("/api/network")
def network():
    return jsonify({"departments": 42, "startups": 186, "pilots_scaled": 27, "active_pilots": 18})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)