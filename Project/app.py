import json
from datetime import datetime
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
    get_startup_profile,
    save_startup_registration,
)


ROOT = Path(__file__).parent
CHALLENGE_STORE_PATH = ROOT / "challenge_store.json"
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


TEMPLATE_LIBRARY = {
    "software": {
        "name": "Software / Digital Solution",
        "description": "For web applications, mobile applications, AI platforms, automation systems, government portals, data platforms, and digital services.",
        "category": "Web Development",
        "challengeType": "Software",
        "difficulty": "Intermediate",
        "templateSpecific": {
            "targetUsers": "Citizens and government officers",
            "requiredModules": "Dashboard, workflow automation, reporting",
            "deploymentEnvironment": "Government Cloud",
        },
    },
    "ai": {
        "name": "AI / Machine Learning",
        "description": "For artificial intelligence, machine learning, NLP, computer vision, predictive analytics, recommendation systems, and intelligent automation.",
        "category": "AI / ML",
        "challengeType": "Software",
        "difficulty": "Advanced",
        "templateSpecific": {
            "datasetAvailability": "Partially available",
            "expectedModelOutput": "Prediction and dashboard alerts",
            "evaluationMetric": "Accuracy and precision",
        },
    },
    "hardware": {
        "name": "Hardware / IoT",
        "description": "For IoT, sensors, embedded systems, smart infrastructure, robotics, and connected devices.",
        "category": "IoT",
        "challengeType": "Hardware",
        "difficulty": "Advanced",
        "templateSpecific": {
            "hardwareRequirements": "Edge sensor kit and gateway",
            "communicationProtocol": "LoRaWAN / Wi-Fi",
            "prototypeRequirements": "Field-ready prototype with dashboard",
        },
    },
    "research": {
        "name": "Research / Innovation",
        "description": "For scientific research, emerging technologies, experimental solutions, and innovation challenges.",
        "category": "Governance",
        "challengeType": "Research",
        "difficulty": "Expert",
        "templateSpecific": {
            "researchDomain": "Public service delivery",
            "researchObjective": "Develop a proof-of-concept for sustainable digital innovation.",
            "evaluationMethodology": "Research quality and pilot readiness",
        },
    },
    "open": {
        "name": "Open Innovation",
        "description": "For challenges where participants are free to propose different technological approaches.",
        "category": "Other",
        "challengeType": "Open Innovation",
        "difficulty": "Intermediate",
        "templateSpecific": {
            "expectedContribution": "Original, scalable solution concept",
        },
    },
}


def _now_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_store():
    if not CHALLENGE_STORE_PATH.exists():
        return {"drafts": {}, "published": {}}
    try:
        with CHALLENGE_STORE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return {"drafts": data.get("drafts", {}), "published": data.get("published", {})}
    except (json.JSONDecodeError, OSError):
        return {"drafts": {}, "published": {}}


def _write_store(store):
    with CHALLENGE_STORE_PATH.open("w", encoding="utf-8") as handle:
        json.dump(store, handle, indent=2)


def _challenge_id_for(store):
    count = len(store.get("drafts", {})) + len(store.get("published", {})) + 1
    return f"GOV-{datetime.utcnow().year}-{count:05d}"


def _default_challenge(template_key="software"):
    template = TEMPLATE_LIBRARY.get(template_key, TEMPLATE_LIBRARY["software"])
    challenge_id = _challenge_id_for(_read_store())
    return {
        "id": f"draft-{challenge_id.lower()}",
        "challengeId": challenge_id,
        "title": "",
        "template": template_key,
        "category": template["category"],
        "challengeType": template["challengeType"],
        "difficulty": template["difficulty"],
        "status": "Draft",
        "createdAt": _now_iso(),
        "updatedAt": _now_iso(),
        "department": "",
        "ministry": "",
        "state": "",
        "problemStatement": {
            "description": "",
            "currentSituation": "",
            "painPoints": [""],
            "affectedGroups": [],
            "geographicScope": "National",
            "impact": "",
        },
        "objectives": [""],
        "expectedOutcomes": [{"text": "", "order": 1}],
        "requirements": {"mandatory": [""], "optional": [""], "features": [{"name": "", "priority": "Mandatory"}]},
        "constraints": {
            "technical": [],
            "budget": {"estimatedBudget": "", "budgetType": "Fixed"},
            "deployment": "Government Cloud",
            "security": [],
        },
        "resources": {
            "datasetProvided": "Yes",
            "datasetType": [],
            "datasetSize": "",
            "dataAccess": "Public",
            "apis": [{"name": "", "purpose": "", "endpoint": "", "authentication": "No", "documentationUrl": ""}],
            "documents": [],
        },
        "deliverables": [],
        "platforms": [],
        "evaluationCriteria": [
            {"criterion": "Technical Quality", "description": "", "weight": 30},
            {"criterion": "Innovation", "description": "", "weight": 25},
            {"criterion": "Impact", "description": "", "weight": 25},
            {"criterion": "Scalability", "description": "", "weight": 20},
        ],
        "eligibility": {
            "participantTypes": ["Open to All"],
            "minTeamSize": "1",
            "maxTeamSize": "5",
            "requiredSkills": [],
        },
        "timeline": {
            "registrationOpen": "",
            "registrationClose": "",
            "submissionOpen": "",
            "submissionDeadline": "",
            "evaluationStart": "",
            "resultsDate": "",
        },
        "contact": {
            "department": "",
            "officerName": "",
            "designation": "",
            "email": "",
            "phone": "",
        },
        "templateSpecific": template["templateSpecific"],
    }


def _serialize_challenges():
    store = _read_store()
    challenges = []
    for bucket in ("drafts", "published"):
        for entry in store.get(bucket, {}).values():
            challenges.append(entry)
    return sorted(challenges, key=lambda item: item.get("updatedAt", ""), reverse=True)


def _generate_ai_draft(description):
    normalized = (description or "").strip()
    if not normalized:
        raise ValueError("A brief problem description is required to generate a draft.")
    title = "AI Waste Monitoring for Municipal Compliance"
    return {
        "title": title,
        "challengeType": "Software",
        "category": "AI / ML",
        "difficulty": "Advanced",
        "problemStatement": {
            "description": "We need a system to help municipalities identify illegal garbage dumping using citizen reports and CCTV imagery.",
            "currentSituation": "Municipal teams currently rely on manual inspections and inconsistent reporting, which slows response times and creates gaps in enforcement.",
            "painPoints": [
                "Anonymous complaints are not centrally tracked",
                "CCTV footage is reviewed manually",
                "Illegal dumping hotspots are difficult to prioritize",
            ],
            "affectedGroups": ["Citizens", "Local Authorities", "Government Officers"],
            "geographicScope": "Local",
            "impact": "The lack of timely detection leads to environmental degradation, public complaints, and delayed enforcement.",
        },
        "objectives": [
            "Create a monitoring workflow for citizens and local authorities",
            "Use AI to identify illegal dumping hotspots from reports and CCTV feeds",
            "Reduce response time for municipal enforcement teams",
        ],
        "expectedOutcomes": [
            {"text": "Improved detection coverage across urban hotspots", "order": 1},
            {"text": "Reduced manual review time for municipal staff", "order": 2},
            {"text": "Faster escalation and action on illegal dumping complaints", "order": 3},
        ],
        "requirements": {
            "mandatory": ["Dashboard for monitoring complaints and evidence", "AI-assisted image classification workflow", "Role-based user access"],
            "optional": ["Map-based hotspot visualization", "Citizen reporting app"],
            "features": [{"name": "User authentication", "priority": "Mandatory"}, {"name": "Analytics dashboard", "priority": "Mandatory"}],
        },
        "constraints": {
            "technical": ["Low bandwidth support required", "Existing government system integration required"],
            "budget": {"estimatedBudget": "INR 8-15 lakh", "budgetType": "Flexible"},
            "deployment": "Government Cloud",
            "security": ["Encryption", "Audit Logs"],
        },
        "deliverables": ["Working Prototype", "Source Code", "Technical Documentation"],
        "platforms": ["Web", "Android"],
        "evaluationCriteria": [
            {"criterion": "Technical Quality", "description": "Model and software quality", "weight": 30},
            {"criterion": "Innovation", "description": "Novelty and problem-solving approach", "weight": 25},
            {"criterion": "Impact", "description": "Public value and operational benefit", "weight": 25},
            {"criterion": "Scalability", "description": "Model and deployment viability", "weight": 20},
        ],
        "eligibility": {
            "participantTypes": ["Startups", "Individual Developers", "Researchers"],
            "minTeamSize": "1",
            "maxTeamSize": "5",
            "requiredSkills": ["AI/ML", "Python", "JavaScript", "Cloud"],
        },
        "timeline": {
            "registrationOpen": "2026-10-05",
            "registrationClose": "2026-10-25",
            "submissionOpen": "2026-10-30",
            "submissionDeadline": "2026-11-30",
            "evaluationStart": "2026-12-01",
            "resultsDate": "2026-12-20",
        },
        "contact": {
            "department": "Municipal Administration",
            "officerName": "Rohit Sharma",
            "designation": "Deputy Secretary",
            "email": "rohitt@ma.gov.in",
            "phone": "+91 98765 43210",
        },
        "status": "Draft",
        "template": "ai",
        "department": "Municipal Administration",
        "ministry": "Ministry of Housing and Urban Affairs",
        "state": "Delhi",
        "templateSpecific": {
            "datasetAvailability": "Partially available",
            "expectedModelOutput": "Incident classification and risk score",
            "evaluationMetric": "Precision, recall, and F1 score",
        },
    }


@app.get("/")
def home():
    return render_template("index.htm")


@app.get("/pages.css")
def pages_stylesheet():
    return send_from_directory(ROOT, "pages.css", mimetype="text/css")


@app.get("/<page>")
def page(page):
    pages = {"directory", "how-it-works", "resources", "login", "join", "register", "government-dashboard", "create-challenge"}
    if page in pages:
        return render_template(f"{page}.htm")
    return ("Page not found", 404)


@app.get("/government-dashboard")
def government_dashboard():
    challenges = _serialize_challenges()
    return render_template("government-dashboard.htm", challenges=challenges)


@app.get("/create-challenge")
def create_challenge():
    return render_template("create-challenge.htm", templates=TEMPLATE_LIBRARY)


@app.post("/api/challenges/generate-draft")
def generate_challenge_draft():
    data = request.get_json(silent=True) or {}
    description = str(data.get("description") or "").strip()
    if not description:
        return jsonify({"ok": False, "message": "A challenge description is required."}), 400
    try:
        draft = _generate_ai_draft(description)
        return jsonify({"ok": True, "draft": draft, "message": "AI-generated draft — Please review before publishing."})
    except ValueError as error:
        return jsonify({"ok": False, "message": str(error)}), 400


@app.get("/api/challenges")
def list_challenges():
    return jsonify({"ok": True, "challenges": _serialize_challenges()})


@app.post("/api/challenges")
def save_challenge():
    payload = request.get_json(silent=True) or {}
    challenge = payload.get("challenge") or payload
    if not challenge:
        return jsonify({"ok": False, "message": "Challenge data is required."}), 400
    challenge_id = str(challenge.get("challengeId") or _challenge_id_for(_read_store())).strip()
    challenge["challengeId"] = challenge_id
    challenge["updatedAt"] = _now_iso()
    if not challenge.get("id"):
        challenge["id"] = f"{challenge_id.lower()}"
    store = _read_store()
    bucket = "published" if challenge.get("status") == "Published" else "drafts"
    store[bucket][challenge["id"]] = challenge
    if bucket == "drafts" and challenge.get("status") == "Published":
        store["drafts"].pop(challenge["id"], None)
    _write_store(store)
    return jsonify({"ok": True, "challenge": challenge, "message": "Challenge saved successfully."})


@app.get("/api/challenges/<challenge_id>")
def get_challenge(challenge_id):
    store = _read_store()
    for bucket in ("drafts", "published"):
        for key, value in store.get(bucket, {}).items():
            if value.get("challengeId") == challenge_id or key == challenge_id:
                return jsonify({"ok": True, "challenge": value})
    return jsonify({"ok": False, "message": "Challenge not found."}), 404


@app.post("/api/challenges/<challenge_id>/publish")
def publish_challenge(challenge_id):
    store = _read_store()
    found = None
    target_bucket = None
    for bucket in ("drafts", "published"):
        for key, value in store.get(bucket, {}).items():
            if value.get("challengeId") == challenge_id or key == challenge_id:
                found = value
                target_bucket = bucket
                break
        if found:
            break
    if not found:
        return jsonify({"ok": False, "message": "Challenge not found."}), 404
    found["status"] = "Published"
    found["updatedAt"] = _now_iso()
    if target_bucket == "drafts":
        store["drafts"].pop(found["id"], None)
    store["published"][found["id"]] = found
    _write_store(store)
    return jsonify({"ok": True, "challenge": found, "message": "Challenge published successfully."})


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
            business_id = data.get("business_id", "")
            valid = authenticate_startup(business_id, data.get("gstin", ""), data.get("password", ""))
            landing_page = "/startup-portal"
    except (DatabaseConfigurationError, ValueError) as error:
        return jsonify({"ok": False, "message": str(error)}), 503
    if not valid:
        return jsonify({"ok": False, "message": "The credentials could not be verified."}), 401
    session.clear()
    session.permanent = True
    session["role"] = role
    if role == "startup":
        session["business_id"] = business_id
    return jsonify({"ok": True, "message": "Sign in successful.", "redirect": landing_page})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.get("/startup-portal")
@session_required("startup")
def startup_portal():
    profile = get_startup_profile(session["business_id"])
    if not profile:
        session.clear()
        return redirect("/login")
    return render_template("startup-portal.htm", profile=profile)


@app.get("/company-profile")
@session_required("startup")
def company_profile():
    profile = get_startup_profile(session["business_id"])
    if not profile:
        session.clear()
        return redirect("/login")
    return render_template("company-profile.htm", profile=profile)


@app.get("/ministry-portal")
@session_required("ministry")
def ministry_portal():
    return render_template("ministry-portal.htm")


@app.get("/api/network")
def network():
    return jsonify({"departments": 42, "startups": 186, "pilots_scaled": 27, "active_pilots": 18})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
