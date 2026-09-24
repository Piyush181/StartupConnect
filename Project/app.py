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
    list_startup_directory,
    save_contract_report,
    save_startup_registration,
)


ROOT = Path(__file__).parent
CHALLENGE_STORE_PATH = ROOT / "challenge_store.json"
FIXED_GOVERNMENT_BODY = "Maharashtra State Innovation Society"
FIXED_DEPARTMENT = "Department of Skills, Employment, Entrepreneurship and Innovation"
FIXED_STATE = "Maharashtra"
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


def ministry_api_required():
    """Reject unauthenticated or non-ministry API requests."""
    if session.get("role") != "ministry":
        return jsonify({"ok": False, "message": "Authentication required for ministry actions."}), 401
    return None


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

SAMPLE_CONTRACTS = {
    "PS-MH-038": {
        "id": "PS-MH-038",
        "title": "Low-cost remote screening for diabetic retinopathy",
        "ministry": "Public Health Department, Government of Maharashtra",
        "sub_ministry": "Non-Communicable Disease Control Cell",
        "description": "The department is seeking an accessible screening solution that helps frontline health workers identify diabetic retinopathy risk earlier and route patients for timely clinical review.",
        "solution_parameters": ["Works on low-bandwidth mobile devices", "Supports Marathi and English workflows", "Provides an auditable referral record", "Protects patient data in transit and at rest"],
        "deadline": "30 November 2026",
        "budget": "₹50–75 lakh",
        "timeline": "16 weeks from contract award",
        "milestones": ["Weeks 1–3 · Discovery and clinical workflow mapping", "Weeks 4–8 · Prototype and supervised validation", "Weeks 9–13 · District pilot across three facilities", "Weeks 14–16 · Impact report and scale recommendation"],
        "application_deadline": "02 September 2026",
        "applications": 18,
        "type": "Health-tech",
    }
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
        "status": "created",
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
            challenge = dict(entry)
            status = challenge.get("status", "created")
            challenge["status"] = {"Draft": "created", "Published": "currently bidding"}.get(status, status)
            challenges.append(challenge)
    return sorted(challenges, key=lambda item: item.get("updatedAt", ""), reverse=True)


def _public_challenge(challenge):
    """Return only challenge information approved for public discovery."""
    problem = challenge.get("problemStatement") or {}
    contact = challenge.get("contact") or {}
    timeline = challenge.get("timeline") or {}
    resources = challenge.get("resources") or {}
    objectives = challenge.get("objectives") or {}
    if isinstance(objectives, list):
        objectives = {"primary": objectives[0] if objectives else "", "secondary": objectives[1:]}
    engagement = challenge.get("startupEngagement") or {}
    try:
        bids_received = int(engagement.get("bidsReceived", 0) or 0)
    except (TypeError, ValueError):
        bids_received = 0
    return {
        "challengeId": challenge.get("challengeId"),
        "title": challenge.get("title"),
        "status": challenge.get("status"),
        "category": challenge.get("category"),
        "categoryList": challenge.get("categoryList", []),
        "challengeType": challenge.get("challengeType"),
        "difficulty": challenge.get("difficulty"),
        "government": {
            "body": challenge.get("ministry"),
            "department": challenge.get("department"),
            "state": challenge.get("state"),
            "publicDepartment": contact.get("publicDepartment") or challenge.get("department"),
            "nodalOfficerName": contact.get("nodalOfficerName"),
            "designation": contact.get("designation"),
            "officialEmail": contact.get("officialEmail"),
            "officialPhone": contact.get("officialPhone"),
        },
        "problemStatement": {
            "title": problem.get("title"),
            "description": problem.get("description"),
            "currentSituation": problem.get("currentSituation"),
            "painPoints": problem.get("painPoints", []),
            "affectedGroups": problem.get("affectedGroups", []),
            "geographicScope": problem.get("geographicScope"),
            "impact": problem.get("impact"),
        },
        "objectives": objectives,
        "expectedOutcomes": challenge.get("expectedOutcomes", []),
        "requirements": challenge.get("requirements", {}),
        "constraints": challenge.get("constraints", {}),
        "deliverables": challenge.get("deliverables", []),
        "platforms": challenge.get("platforms", []),
        "evaluationCriteria": challenge.get("evaluationCriteria", []),
        "eligibility": challenge.get("eligibility", {}),
        "timeline": timeline,
        "resources": {
            "dataProvided": resources.get("dataProvided"),
            "datasetType": resources.get("datasetType", []),
            "datasetSize": resources.get("datasetSize"),
            "dataAccess": resources.get("dataAccess"),
            "apis": [{"name": api.get("name"), "purpose": api.get("purpose"), "endpoint": api.get("endpoint")} for api in resources.get("apis", [])],
        },
        "startupEngagement": {
            "bidsReceived": max(bids_received, len(engagement.get("startups", []))),
            "startups": [{
                "name": item.get("name"),
                "stage": item.get("stage"),
                "evaluationStatus": item.get("evaluationStatus"),
                "performanceStatus": item.get("performanceStatus"),
                "deadline": item.get("deadline"),
                "publicNote": item.get("publicNote"),
            } for item in engagement.get("startups", [])],
        },
    }


def _find_periodic_check(store, check_id):
    for challenge in _serialize_challenges():
        for check in challenge.get("periodicChecks", []):
            if check.get("checkId") == check_id:
                return challenge, check
    return None, None


def _next_periodic_due_date(due_date, frequency):
    try:
        current = datetime.strptime(due_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return due_date
    days = {"Monthly": 30, "Quarterly": 90}.get(frequency)
    if not days:
        return due_date
    return (current + timedelta(days=days)).strftime("%Y-%m-%d")


def _generate_ai_draft(description):
    normalized = (description or "").strip()
    if not normalized:
        raise ValueError("A brief problem description is required to generate a draft.")

    lower = normalized.lower()

    if any(keyword in lower for keyword in ["telemedicine", "clinic", "health", "medical", "patient"]):
        title = "AI-Powered Rural Telemedicine Monitoring Platform"
        category = "AI / ML"
        challenge_type = "Software"
        problem_description = "We need an AI-driven telemedicine platform that helps clinics and health workers monitor rural patient care, triage urgent needs, and improve follow-up coordination in remote communities."
        premise = "remote villages, local clinics, and underserved communities"
        phases = [
            "Build a patient monitoring and triage workflow for rural healthcare teams",
            "Use AI to identify high-risk cases and support clinician decisions",
            "Improve continuity of care in underserved regions",
        ]
    elif any(keyword in lower for keyword in ["transport", "mobility", "traffic", "route", "logistics"]):
        title = "AI Mobility and Route Optimization Platform"
        category = "AI / ML"
        challenge_type = "Software"
        problem_description = "We need an intelligent mobility platform to improve route planning, reduce delays, and support faster civic transportation decisions for urban and rural mobility networks."
        premise = "urban mobility networks and emergency transport operations"
        phases = [
            "Improve route planning and delivery efficiency",
            "Detect bottlenecks and high-risk travel patterns",
            "Support a safer and more responsive mobility system",
        ]
    elif any(keyword in lower for keyword in ["education", "student", "school", "learning", "teacher"]):
        title = "AI Education Insight and Learning Support System"
        category = "AI / ML"
        challenge_type = "Software"
        problem_description = "We need a learning support platform that helps schools and education departments detect learning gaps, personalize support, and improve student outcomes using data-driven insights."
        premise = "schools, teachers, and student support systems"
        phases = [
            "Support teachers with actionable student insights",
            "Identify learners needing intervention early",
            "Improve classroom and program effectiveness",
        ]
    else:
        title = "AI Waste Monitoring for Municipal Compliance"
        category = "AI / ML"
        challenge_type = "Software"
        problem_description = "We need a system to help municipalities identify illegal garbage dumping using citizen reports and CCTV imagery."
        premise = "municipal teams and citizen reporting workflows"
        phases = [
            "Create a monitoring workflow for citizens and local authorities",
            "Use AI to identify illegal dumping hotspots from reports and CCTV feeds",
            "Reduce response time for municipal enforcement teams",
        ]

    title = title if title else "AI Challenge Draft"
    return {
        "title": title,
        "challengeType": challenge_type,
        "category": category,
        "difficulty": "Advanced",
        "problemStatement": {
            "description": problem_description,
            "currentSituation": f"Current teams still rely on manual review, inconsistent reporting, and fragmented workflows, which slows action across {premise}.",
            "painPoints": [
                "Reports and evidence are not centralized",
                "Manual review creates delays and inconsistency",
                "Priority issues are hard to detect early",
            ],
            "affectedGroups": ["Citizens", "Local Authorities", "Government Officers"],
            "geographicScope": "Local",
            "impact": "The lack of timely action leads to service gaps, operational inefficiency, and poorer outcomes for the public and frontline teams.",
        },
        "objectives": [
            *phases,
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
        "status": "created",
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
    challenges = [_public_challenge(item) for item in _serialize_challenges() if item.get("status") in {"currently bidding", "Ongoing", "Completed"}]
    try:
        startup_count = len(list_startup_directory())
    except Exception:
        app.logger.exception("Could not load homepage startup metric.")
        startup_count = 0
    departments = len({item.get("government", {}).get("department") for item in challenges if item.get("government", {}).get("department")})
    return render_template(
        "index.htm",
        homepage_challenges=challenges[:3],
        departments=departments,
        startups=startup_count,
        active_pilots=sum(item.get("status") == "Ongoing" for item in challenges),
        pilots_scaled=sum(item.get("status") == "Completed" for item in challenges),
    )


@app.get("/pages.css")
def pages_stylesheet():
    return send_from_directory(ROOT, "pages.css", mimetype="text/css")


@app.get("/<page>")
def page(page):
    pages = {"directory", "how-it-works", "login", "join", "register", "government-dashboard", "create-challenge", "public-challenges"}
    if page in pages:
        return render_template(f"{page}.htm")
    return ("Page not found", 404)


@app.get("/directory")
def directory():
    try:
        startups = list_startup_directory()
        database_error = None
    except Exception:
        app.logger.exception("Could not load startup directory from the database.")
        startups = []
        database_error = "Startup profiles could not be loaded from the database. Please check the database connection."
    return render_template("directory.htm", startups=startups, database_error=database_error)


@app.get("/challenges")
def challenges():
    if session.get("role") == "ministry":
        return redirect("/government-dashboard")
    return redirect("/public-challenges")


@app.get("/public-challenges")
def public_challenges():
    challenges = [_public_challenge(item) for item in _serialize_challenges() if item.get("status") in {"currently bidding", "Ongoing", "Completed"}]
    return render_template("public-challenges.htm", challenges=challenges)


@app.get("/public-challenges/<challenge_id>")
def public_challenge_view(challenge_id):
    challenge = next((item for item in _serialize_challenges() if item.get("challengeId") == challenge_id), None)
    if not challenge or challenge.get("status") not in {"currently bidding", "Ongoing", "Completed"}:
        return ("Challenge not found", 404)
    return render_template("public-challenge-view.htm", challenge=_public_challenge(challenge))


@app.get("/api/public/challenges")
def public_challenges_api():
    challenges = [_public_challenge(item) for item in _serialize_challenges() if item.get("status") in {"currently bidding", "Ongoing", "Completed"}]
    return jsonify({"ok": True, "challenges": challenges})


@app.get("/government-dashboard")
@session_required("ministry")
def government_dashboard():
    return render_template("government-dashboard.htm", challenges=_serialize_challenges())


@app.get("/create-challenge")
@session_required("ministry")
def create_challenge():
    return render_template("create-challenge.htm", templates=TEMPLATE_LIBRARY)


@app.post("/api/challenges/generate-draft")
def generate_challenge_draft():
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
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
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
    return jsonify({"ok": True, "challenges": _serialize_challenges()})


@app.post("/api/challenges")
def save_challenge():
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
    payload = request.get_json(silent=True) or {}
    challenge = payload.get("challenge") or payload
    if not challenge:
        return jsonify({"ok": False, "message": "Challenge data is required."}), 400
    challenge["ministry"] = FIXED_GOVERNMENT_BODY
    challenge["department"] = FIXED_DEPARTMENT
    challenge["state"] = FIXED_STATE
    challenge_id = str(challenge.get("challengeId") or _challenge_id_for(_read_store())).strip()
    challenge["challengeId"] = challenge_id
    challenge["updatedAt"] = _now_iso()
    challenge["createdBy"] = session.get("ministry_id") or "ministry-user"
    if not challenge.get("id"):
        challenge["id"] = f"{challenge_id.lower()}"
    store = _read_store()
    challenge["status"] = "currently bidding" if challenge.get("status") in {"Published", "currently bidding"} else "created"
    bucket = "published" if challenge.get("status") in {"currently bidding", "Ongoing", "Completed"} else "drafts"
    store[bucket][challenge["id"]] = challenge
    if bucket == "published":
        store["drafts"].pop(challenge["id"], None)
    _write_store(store)
    return jsonify({"ok": True, "challenge": challenge, "message": "Challenge saved successfully."})


@app.get("/api/challenges/<challenge_id>")
def get_challenge(challenge_id):
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
    store = _read_store()
    for bucket in ("drafts", "published"):
        for key, value in store.get(bucket, {}).items():
            if value.get("challengeId") == challenge_id or key == challenge_id:
                return jsonify({"ok": True, "challenge": value})
    return jsonify({"ok": False, "message": "Challenge not found."}), 404


@app.post("/api/challenges/<challenge_id>/publish")
def publish_challenge(challenge_id):
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
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
    found["status"] = "currently bidding"
    found["updatedAt"] = _now_iso()
    if target_bucket == "drafts":
        store["drafts"].pop(found["id"], None)
    store["published"][found["id"]] = found
    _write_store(store)
    return jsonify({"ok": True, "challenge": found, "message": "Challenge published successfully."})


@app.post("/api/challenges/<challenge_id>/periodic-checks")
def schedule_periodic_check(challenge_id):
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
    data = request.get_json(silent=True) or {}
    title = str(data.get("title") or "Periodic progress report").strip()
    frequency = str(data.get("frequency") or "Monthly").strip()
    due_date = str(data.get("dueDate") or "").strip()
    notification = str(data.get("notification") or "Please submit your periodic progress report.").strip()
    if not due_date:
        return jsonify({"ok": False, "message": "A first report date is required."}), 400

    store = _read_store()
    challenge = next((item for item in _serialize_challenges() if item.get("challengeId") == challenge_id), None)
    if not challenge:
        return jsonify({"ok": False, "message": "Challenge not found."}), 404
    check = {
        "checkId": f"CHECK-{challenge_id}-{len(challenge.get('periodicChecks', [])) + 1:03d}",
        "title": title,
        "frequency": frequency,
        "dueDate": due_date,
        "notification": notification,
        "status": "Awaiting Startup Report",
        "createdAt": _now_iso(),
        "reports": [],
    }
    challenge.setdefault("periodicChecks", []).append(check)
    challenge["updatedAt"] = _now_iso()
    for bucket in ("drafts", "published"):
        if challenge.get("id") in store.get(bucket, {}):
            store[bucket][challenge["id"]] = challenge
            break
    _write_store(store)
    return jsonify({"ok": True, "check": check, "message": "Periodic check scheduled and startup notification queued."})


@app.post("/api/challenges/<challenge_id>/startup-progress")
def update_startup_progress(challenge_id):
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
    data = request.get_json(silent=True) or {}
    startup_name = str(data.get("name") or "").strip()
    if not startup_name:
        return jsonify({"ok": False, "message": "A public startup name is required."}), 400
    stage = str(data.get("stage") or "Bid Received").strip()
    allowed_stages = {"Bid Received", "Under Evaluation", "Evaluation Completed", "Performing"}
    if stage not in allowed_stages:
        return jsonify({"ok": False, "message": "Choose a valid startup progress stage."}), 400
    try:
        bids_received = int(data.get("bidsReceived") or 0)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "message": "Total bids received must be a number."}), 400
    if bids_received < 0:
        return jsonify({"ok": False, "message": "Total bids received cannot be negative."}), 400

    store = _read_store()
    challenge = next((item for item in _serialize_challenges() if item.get("challengeId") == challenge_id), None)
    if not challenge:
        return jsonify({"ok": False, "message": "Challenge not found."}), 404
    engagement = challenge.setdefault("startupEngagement", {"bidsReceived": 0, "startups": []})
    startups = engagement.setdefault("startups", [])
    startup = next((item for item in startups if item.get("name", "").casefold() == startup_name.casefold()), None)
    if startup is None:
        startup = {"name": startup_name}
        startups.append(startup)
    startup.update({
        "stage": stage,
        "evaluationStatus": str(data.get("evaluationStatus") or ("Completed" if stage in {"Evaluation Completed", "Performing"} else "Pending")).strip(),
        "performanceStatus": str(data.get("performanceStatus") or ("Active" if stage == "Performing" else "Not started")).strip(),
        "deadline": str(data.get("deadline") or "").strip(),
        "publicNote": str(data.get("publicNote") or "").strip(),
        "updatedAt": _now_iso(),
    })
    engagement["bidsReceived"] = max(bids_received, len(startups))
    challenge["updatedAt"] = _now_iso()
    for bucket in ("drafts", "published"):
        if challenge.get("id") in store.get(bucket, {}):
            store[bucket][challenge["id"]] = challenge
            break
    _write_store(store)
    return jsonify({"ok": True, "startupEngagement": engagement, "message": "Public startup progress updated."})


@app.get("/api/periodic-checks")
def startup_periodic_checks():
    if session.get("role") != "startup":
        return jsonify({"ok": False, "message": "Startup authentication required."}), 401
    startup_id = session.get("business_id") or "startup-user"
    checks = []
    for challenge in _serialize_challenges():
        if challenge.get("status") != "Published":
            continue
        for check in challenge.get("periodicChecks", []):
            reports = [report for report in check.get("reports", []) if report.get("startupId") == startup_id]
            checks.append({
                "challengeId": challenge.get("challengeId"),
                "challengeTitle": challenge.get("title"),
                "check": {key: value for key, value in check.items() if key != "reports"},
                "report": reports[-1] if reports else None,
            })
    return jsonify({"ok": True, "checks": checks})


@app.post("/api/periodic-checks/<check_id>/reports")
def submit_periodic_report(check_id):
    if session.get("role") != "startup":
        return jsonify({"ok": False, "message": "Startup authentication required."}), 401
    data = request.get_json(silent=True) or {}
    summary = str(data.get("summary") or "").strip()
    if not summary:
        return jsonify({"ok": False, "message": "A progress summary is required."}), 400
    store = _read_store()
    challenge, check = _find_periodic_check(store, check_id)
    if not challenge or not check:
        return jsonify({"ok": False, "message": "Periodic check not found."}), 404
    report = {
        "reportId": f"REPORT-{check_id}-{session.get('business_id', 'startup-user')}",
        "challengeId": challenge.get("challengeId"),
        "checkId": check_id,
        "startupId": session.get("business_id") or "startup-user",
        "summary": summary,
        "progress": str(data.get("progress") or "").strip(),
        "metrics": str(data.get("metrics") or "").strip(),
        "blockers": str(data.get("blockers") or "").strip(),
        "evidence": str(data.get("evidence") or "").strip(),
        "status": "Submitted for Government Review",
        "submittedAt": _now_iso(),
        "review": None,
    }
    check.setdefault("reports", [])
    check["reports"] = [item for item in check["reports"] if item.get("startupId") != report["startupId"]]
    check["reports"].append(report)
    check["status"] = "Report Submitted - Government Review Pending"
    for bucket in ("drafts", "published"):
        if challenge.get("id") in store.get(bucket, {}):
            store[bucket][challenge["id"]] = challenge
            break
    _write_store(store)
    try:
        save_contract_report(report)
    except Exception:
        app.logger.exception("Report %s was saved locally but could not be written to contract_reports.", report["reportId"])
    return jsonify({"ok": True, "report": report, "message": "Report submitted for government review."})


@app.get("/api/periodic-reports")
def government_periodic_reports():
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
    reports = []
    for challenge in _serialize_challenges():
        for check in challenge.get("periodicChecks", []):
            for report in check.get("reports", []):
                reports.append({
                    "challengeId": challenge.get("challengeId"),
                    "challengeTitle": challenge.get("title"),
                    "check": {key: value for key, value in check.items() if key != "reports"},
                    "report": report,
                })
    return jsonify({"ok": True, "reports": reports})


@app.post("/api/periodic-reports/<report_id>/review")
def review_periodic_report(report_id):
    auth_error = ministry_api_required()
    if auth_error is not None:
        return auth_error
    data = request.get_json(silent=True) or {}
    decision = str(data.get("decision") or "").strip()
    feedback = str(data.get("feedback") or "").strip()
    if decision not in {"Accepted", "Changes Requested"}:
        return jsonify({"ok": False, "message": "Choose Accepted or Changes Requested."}), 400
    store = _read_store()
    for challenge in _serialize_challenges():
        for check in challenge.get("periodicChecks", []):
            for report in check.get("reports", []):
                if report.get("reportId") != report_id:
                    continue
                report["status"] = decision
                report["review"] = {"decision": decision, "feedback": feedback, "reviewedAt": _now_iso()}
                check["status"] = "Accepted" if decision == "Accepted" else "Changes Requested"
                if decision == "Accepted" and check.get("frequency") in {"Monthly", "Quarterly"}:
                    next_due_date = _next_periodic_due_date(check.get("dueDate"), check.get("frequency"))
                    check["status"] = "Completed"
                    challenge.setdefault("periodicChecks", []).append({
                        "checkId": f"CHECK-{challenge.get('challengeId')}-{len(challenge.get('periodicChecks', [])) + 1:03d}",
                        "title": check.get("title", "Periodic progress report"),
                        "frequency": check.get("frequency"),
                        "dueDate": next_due_date,
                        "notification": check.get("notification", "Please submit your periodic progress report."),
                        "status": "Awaiting Startup Report",
                        "createdAt": _now_iso(),
                        "reports": [],
                    })
                for bucket in ("drafts", "published"):
                    if challenge.get("id") in store.get(bucket, {}):
                        store[bucket][challenge["id"]] = challenge
                        break
                _write_store(store)
                try:
                    save_contract_report(report)
                except Exception:
                    app.logger.exception("Report %s was reviewed locally but could not be updated in contract_reports.", report_id)
                return jsonify({"ok": True, "report": report, "message": "Report review saved."})
    return jsonify({"ok": False, "message": "Report not found."}), 404


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
    if role == "ministry":
        session["ministry_id"] = str(data.get("ministry_id", "")).strip()
    else:
        session["business_id"] = str(data.get("business_id", "")).strip()
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


@app.get("/contracts/<contract_id>")
def contract_detail(contract_id):
    contract = SAMPLE_CONTRACTS.get(contract_id.upper())
    if not contract:
        return ("Contract not found", 404)
    return render_template("contract-detail.htm", contract=contract)


@app.get("/contracts/<contract_id>/apply")
@session_required("startup")
def start_contract_application(contract_id):
    contract = SAMPLE_CONTRACTS.get(contract_id.upper())
    if not contract:
        return ("Contract not found", 404)
    return render_template("application-start.htm", contract=contract)


@app.get("/ministry-portal")
@session_required("ministry")
def ministry_portal():
    return render_template("ministry-portal.htm")


@app.get("/api/network")
def network():
    return jsonify({"departments": 42, "startups": 186, "pilots_scaled": 27, "active_pilots": 18})


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
