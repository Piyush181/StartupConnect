"""Sandbox and pilot programme engine.

Pure computation, no Flask or file I/O, so every rule is unit-testable.
A pilot runs for one startup selected in the final selection of a challenge:

    draft -> awaiting_acceptance -> readiness -> active <-> suspended
                  ^        |                        |
                  +--------+ (changes requested)    v
                                                  review -> scaled | procurement | closed
                                                     |
                                                     +-> active (extension)

Only measurements and milestones verified by the ministry count toward results.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any, Mapping

MODES = {"Sandbox", "Pilot"}
CADENCE_DAYS = {"Weekly": 7, "Biweekly": 14, "Monthly": 30}
REPORT_GRACE_DAYS = 3
INCIDENT_SEVERITIES = ("Low", "Medium", "High", "Critical")
DECISIONS = {
    "scale": "Scale the solution",
    "procurement": "Move to compliant procurement",
    "extend": "Extend and iterate",
    "close": "Close the pilot",
}

STAGE_LABELS = {
    "draft": "Agreement draft",
    "awaiting_acceptance": "Awaiting startup acceptance",
    "readiness": "Readiness checks",
    "active": "Active",
    "suspended": "Suspended",
    "review": "Results review",
    "scaled": "Scaled",
    "procurement": "Moved to procurement",
    "closed": "Closed",
}
TERMINAL_STAGES = {"scaled", "procurement", "closed"}

READINESS_ITEMS: list[tuple[str, str, set[str]]] = [
    ("data_sharing", "Data-sharing and privacy agreement signed", {"Sandbox", "Pilot"}),
    ("security_review", "Security review / VAPT of the solution cleared", {"Sandbox", "Pilot"}),
    ("environment", "Sandbox environment or pilot sites provisioned", {"Sandbox", "Pilot"}),
    ("rollback", "Rollback and exit plan documented", {"Sandbox", "Pilot"}),
    ("training", "Officers and users trained", {"Pilot"}),
    ("grievance", "Citizen feedback and grievance channel live", {"Pilot"}),
]


def parse_date(value: Any, name: str) -> date:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except ValueError as error:
        raise ValueError(f"{name} must be a date (YYYY-MM-DD).") from error


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number.") from error
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return result


def _text(value: Any, name: str, limit: int, required: bool = False) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"{name} is required.")
    if len(text) > limit:
        raise ValueError(f"{name} must be under {limit:,} characters.")
    return text


# --------------------------------------------------------------------------- #
# Agreement
# --------------------------------------------------------------------------- #

def validate_agreement(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a pilot agreement. Returns a normalised copy or raises ValueError."""
    raw = dict(raw or {})
    mode = str(raw.get("mode") or "").strip()
    if mode not in MODES:
        raise ValueError("Choose Sandbox (controlled environment) or Pilot (limited live rollout).")
    start = parse_date(raw.get("startDate"), "Start date")
    end = parse_date(raw.get("endDate"), "End date")
    if end <= start:
        raise ValueError("End date must be after the start date.")
    if (end - start).days > 730:
        raise ValueError("A pilot cannot run longer than two years; split it into phases.")
    cadence = str(raw.get("reportingCadence") or "").strip()
    if cadence not in CADENCE_DAYS:
        raise ValueError("Choose a weekly, biweekly or monthly reporting cadence.")
    budget = _number(raw.get("budget") or 0, "Budget")
    if budget < 0:
        raise ValueError("Budget cannot be negative.")
    cohort = _number(raw.get("cohortSize") or 0, "Cohort size")
    if cohort < 0 or not cohort.is_integer():
        raise ValueError("Cohort size must be a whole number.")

    raw_kpis = raw.get("kpis") or []
    if not isinstance(raw_kpis, list) or not 1 <= len(raw_kpis) <= 12:
        raise ValueError("Define between 1 and 12 success KPIs.")
    kpis, names = [], set()
    for index, item in enumerate(raw_kpis, start=1):
        if not isinstance(item, Mapping):
            raise ValueError("Each KPI must be an object.")
        name = _text(item.get("name"), "KPI name", 160, required=True)
        if name.casefold() in names:
            raise ValueError("KPI names must be unique.")
        names.add(name.casefold())
        baseline = _number(item.get("baseline"), f"Baseline for {name}")
        target = _number(item.get("target"), f"Target for {name}")
        direction = str(item.get("direction") or "increase").strip()
        if direction not in {"increase", "decrease"}:
            raise ValueError(f"{name}: choose whether higher or lower is better.")
        if direction == "increase" and target <= baseline:
            raise ValueError(f"{name}: target must be above the baseline when higher is better.")
        if direction == "decrease" and target >= baseline:
            raise ValueError(f"{name}: target must be below the baseline when lower is better.")
        weight = _number(item.get("weight"), f"Weight for {name}")
        if weight <= 0:
            raise ValueError(f"{name}: weight must be positive.")
        guardrail = item.get("guardrail")
        guardrail = None if guardrail in (None, "") else _number(guardrail, f"Guardrail for {name}")
        if guardrail is not None:
            wrong_side = guardrail > baseline if direction == "increase" else guardrail < baseline
            if wrong_side:
                raise ValueError(f"{name}: the guardrail is the worst acceptable value, so it must be on the far side of the baseline from the target.")
        kpis.append({
            "kpiId": str(item.get("kpiId") or f"KPI-{index}"),
            "name": name,
            "unit": _text(item.get("unit"), "KPI unit", 40),
            "baseline": baseline,
            "target": target,
            "direction": direction,
            "weight": weight,
            "critical": bool(item.get("critical")),
            "guardrail": guardrail,
            "method": _text(item.get("method"), "Measurement method", 1000),
        })
    if round(sum(item["weight"] for item in kpis), 6) != 100:
        raise ValueError("KPI weights must add up to 100.")
    if len({item["kpiId"] for item in kpis}) != len(kpis):
        raise ValueError("KPI identifiers must be unique.")

    raw_milestones = raw.get("milestones") or []
    if not isinstance(raw_milestones, list) or not 1 <= len(raw_milestones) <= 20:
        raise ValueError("Define between 1 and 20 milestones.")
    milestones = []
    for index, item in enumerate(raw_milestones, start=1):
        if not isinstance(item, Mapping):
            raise ValueError("Each milestone must be an object.")
        title = _text(item.get("title"), "Milestone title", 200, required=True)
        due = parse_date(item.get("dueDate"), f"Due date for {title}")
        if not start <= due <= end:
            raise ValueError(f"{title}: due date must fall within the pilot period.")
        payment = _number(item.get("paymentPct") or 0, f"Payment share for {title}")
        if payment < 0 or payment > 100:
            raise ValueError(f"{title}: payment share must be between 0 and 100 percent.")
        milestones.append({
            "milestoneId": str(item.get("milestoneId") or f"MS-{index}"),
            "title": title,
            "dueDate": due.isoformat(),
            "deliverables": _text(item.get("deliverables"), "Deliverables", 2000, required=True),
            "paymentPct": payment,
        })
    milestones.sort(key=lambda item: item["dueDate"])
    total_payment = round(sum(item["paymentPct"] for item in milestones), 6)
    if budget > 0 and total_payment != 100:
        raise ValueError("Milestone payment shares must add up to 100% of the budget.")
    if budget == 0 and total_payment != 0:
        raise ValueError("Set a budget before assigning milestone payments.")

    return {
        "mode": mode,
        "scope": _text(raw.get("scope"), "Scope", 4000, required=True),
        "sites": _text(raw.get("sites"), "Sites or environment", 2000, required=True),
        "cohortSize": int(cohort),
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "reportingCadence": cadence,
        "budget": round(budget, 2),
        "kpis": kpis,
        "milestones": milestones,
        "dataResponsibilities": _text(raw.get("dataResponsibilities"), "Data responsibilities", 4000, required=True),
        "ipOwnership": _text(raw.get("ipOwnership"), "IP ownership", 2000, required=True),
        "securityRequirements": _text(raw.get("securityRequirements"), "Security requirements", 4000, required=True),
        "exitCriteria": _text(raw.get("exitCriteria"), "Exit criteria", 4000, required=True),
        "riskResponsibilities": _text(raw.get("riskResponsibilities"), "Risks and responsibilities", 4000),
    }


def readiness_items(mode: str) -> list[dict[str, str]]:
    return [{"key": key, "label": label} for key, label, modes in READINESS_ITEMS if mode in modes]


def readiness_complete(mode: str, readiness: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """Return labels of readiness items still outstanding."""
    return [item["label"] for item in readiness_items(mode) if not (readiness.get(item["key"]) or {}).get("done")]


# --------------------------------------------------------------------------- #
# KPI analytics
# --------------------------------------------------------------------------- #

def attainment(kpi: Mapping[str, Any], value: float) -> float:
    """Share of the baseline-to-target distance achieved (1.0 = target met)."""
    return (value - kpi["baseline"]) / (kpi["target"] - kpi["baseline"])


def guardrail_breached(kpi: Mapping[str, Any], value: float) -> bool:
    if kpi.get("guardrail") is None:
        return False
    return value < kpi["guardrail"] if kpi["direction"] == "increase" else value > kpi["guardrail"]


def _linear_fit(points: list[tuple[int, float]]) -> tuple[float, float] | None:
    if len({x for x, _ in points}) < 2:
        return None
    n = len(points)
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    return slope, mean_y - slope * mean_x


def kpi_analysis(kpi: Mapping[str, Any], measurements: list[Mapping[str, Any]], end_date: date) -> dict[str, Any]:
    """Latest verified value, attainment, trend and end-of-pilot forecast for one KPI."""
    verified = sorted(
        (item for item in measurements if item.get("kpiId") == kpi["kpiId"] and item.get("status") == "verified"),
        key=lambda item: (item["date"], item.get("recordedAt", "")),
    )
    result: dict[str, Any] = {
        "kpiId": kpi["kpiId"], "name": kpi["name"], "unit": kpi.get("unit", ""), "weight": kpi["weight"],
        "baseline": kpi["baseline"], "target": kpi["target"], "direction": kpi["direction"],
        "critical": kpi.get("critical", False), "guardrail": kpi.get("guardrail"),
        "points": [{"date": item["date"], "value": item["value"]} for item in verified],
        "pending": sum(1 for item in measurements if item.get("kpiId") == kpi["kpiId"] and item.get("status") == "pending"),
        "latest": None, "attainment": None, "met": False, "breached": False,
        "projected": None, "projected_attainment": None, "trend": "No data", "target_eta": None,
    }
    if not verified:
        return result
    latest = float(verified[-1]["value"])
    result["latest"] = latest
    result["attainment"] = round(attainment(kpi, latest), 4)
    result["met"] = result["attainment"] >= 1
    result["breached"] = guardrail_breached(kpi, latest)

    fit = _linear_fit([(parse_date(item["date"], "Measurement date").toordinal(), float(item["value"])) for item in verified])
    if fit is None:
        result["trend"] = "Single reading"
        return result
    slope, intercept = fit
    toward_target = slope * (kpi["target"] - kpi["baseline"]) > 0
    result["trend"] = "Improving" if toward_target and abs(slope) > 1e-12 else "Flat" if abs(slope) <= 1e-12 else "Worsening"
    projected = slope * end_date.toordinal() + intercept
    result["projected"] = round(projected, 4)
    result["projected_attainment"] = round(attainment(kpi, projected), 4)
    if toward_target and not result["met"] and abs(slope) > 1e-12:
        eta = date.fromordinal(max(1, math.ceil((kpi["target"] - intercept) / slope)))
        result["target_eta"] = eta.isoformat()
    return result


def weighted_attainment(analyses: list[Mapping[str, Any]], key: str = "attainment") -> float | None:
    """Weighted attainment in percent, each KPI capped at 100% so one star KPI cannot hide failures."""
    scored = [item for item in analyses if item.get(key) is not None]
    if not scored:
        return None
    total_weight = sum(item["weight"] for item in analyses)
    return round(sum(max(0.0, min(1.0, item[key])) * item["weight"] for item in scored) / total_weight * 100, 2)


# --------------------------------------------------------------------------- #
# Programme health and scorecard
# --------------------------------------------------------------------------- #

def milestone_view(agreement: Mapping[str, Any], states: Mapping[str, Mapping[str, Any]], today: date) -> list[dict[str, Any]]:
    rows = []
    for milestone in agreement.get("milestones", []):
        state = dict(states.get(milestone["milestoneId"]) or {})
        status = state.get("status", "pending")
        due = parse_date(milestone["dueDate"], "Due date")
        verified_on = state.get("verifiedAt", "")[:10]
        overdue = status != "verified" and today > due
        slip = None
        if status == "verified" and verified_on:
            slip = (parse_date(verified_on, "Verified date") - due).days
        amount = round(agreement.get("budget", 0) * milestone["paymentPct"] / 100, 2)
        rows.append({**milestone, **state, "status": status, "overdue": overdue, "slip_days": slip, "amount": amount})
    return rows


def last_report_date(reports: list[Mapping[str, Any]]) -> date | None:
    dates = [parse_date(item["submittedAt"][:10], "Report date") for item in reports if item.get("submittedAt")]
    return max(dates) if dates else None


def next_report_due(pilot: Mapping[str, Any]) -> date | None:
    agreement = pilot.get("agreement") or {}
    if pilot.get("stage") not in {"active", "suspended"} or not pilot.get("wentLiveAt"):
        return None
    anchor = last_report_date(pilot.get("reports", [])) or parse_date(pilot["wentLiveAt"][:10], "Go-live date")
    return anchor + timedelta(days=CADENCE_DAYS[agreement["reportingCadence"]])


def programme_health(pilot: Mapping[str, Any], today: date) -> dict[str, Any]:
    """Live RAG health for an active pilot, with the reasons behind it."""
    agreement = pilot["agreement"]
    end = parse_date(agreement["endDate"], "End date")
    analyses = [kpi_analysis(kpi, pilot.get("measurements", []), end) for kpi in agreement["kpis"]]
    milestones = milestone_view(agreement, pilot.get("milestoneStates", {}), today)
    reasons: list[str] = []

    projected = weighted_attainment(analyses, "projected_attainment")
    current = weighted_attainment(analyses)
    kpi_score = projected if projected is not None else current if current is not None else 50.0
    if projected is None and current is None:
        reasons.append("No verified KPI readings yet.")

    overdue = [item["title"] for item in milestones if item["overdue"]]
    schedule_score = max(0.0, 100 - 25 * len(overdue))
    if overdue:
        reasons.append(f"{len(overdue)} milestone(s) overdue: " + ", ".join(overdue))

    compliance_score = 100.0
    due = next_report_due(pilot)
    if due and today > due + timedelta(days=REPORT_GRACE_DAYS):
        compliance_score = 40.0
        reasons.append(f"Progress report overdue since {due.isoformat()}.")

    score = 0.5 * kpi_score + 0.3 * schedule_score + 0.2 * compliance_score
    open_incidents = [item for item in pilot.get("incidents", []) if item.get("status") == "open"]
    high = [item for item in open_incidents if item["severity"] == "High"]
    critical = [item for item in open_incidents if item["severity"] == "Critical"]
    score -= 15 * len(high)
    if high:
        reasons.append(f"{len(high)} open high-severity incident(s).")
    breached = [item["name"] for item in analyses if item["breached"]]
    worsening_critical = [item["name"] for item in analyses if item["critical"] and item["trend"] == "Worsening"]
    if worsening_critical:
        reasons.append("Critical KPI worsening: " + ", ".join(worsening_critical))

    score = round(max(0.0, min(100.0, score)), 1)
    rag = "Green" if score >= 70 else "Amber" if score >= 45 else "Red"
    suspension_recommended = bool(critical or breached)
    if critical:
        rag = "Red"
        reasons.append(f"{len(critical)} open critical incident(s).")
    if breached:
        rag = "Red"
        reasons.append("Guardrail breached: " + ", ".join(breached))
    days_total = max(1, (end - parse_date(agreement["startDate"], "Start date")).days)
    elapsed = min(1.0, max(0.0, (today - parse_date(agreement["startDate"], "Start date")).days / days_total))
    return {
        "score": score,
        "rag": rag,
        "reasons": reasons,
        "suspension_recommended": suspension_recommended,
        "kpis": analyses,
        "milestones": milestones,
        "current_attainment": current,
        "projected_attainment": projected,
        "time_elapsed_pct": round(elapsed * 100, 1),
        "next_report_due": due.isoformat() if due else None,
    }


def results_scorecard(pilot: Mapping[str, Any], today: date) -> dict[str, Any]:
    """End-of-pilot evidence summary and a recommended stage-gate decision."""
    agreement = pilot["agreement"]
    health = programme_health(pilot, today)
    analyses = health["kpis"]
    milestones = health["milestones"]
    verified = [item for item in milestones if item["status"] == "verified"]
    on_time = [item for item in verified if (item["slip_days"] or 0) <= 0]
    released = sum(item["amount"] for item in pilot.get("payments", []))
    attainment_pct = health["current_attainment"] or 0.0
    projected_pct = health["projected_attainment"]
    critical_unmet = [item["name"] for item in analyses if item["critical"] and not item["met"]]
    open_serious = [item for item in pilot.get("incidents", []) if item.get("status") == "open" and item["severity"] in {"High", "Critical"}]
    milestone_rate = len(verified) / len(milestones) * 100 if milestones else 0.0

    reasons = []
    if attainment_pct >= 80 and not critical_unmet and not open_serious and milestone_rate >= 80:
        recommendation = "scale"
        reasons.append(f"{attainment_pct:.0f}% of weighted KPI targets achieved with every critical KPI met.")
        reasons.append("Choose 'Move to compliant procurement' instead if scaling needs a fresh tender.")
    elif attainment_pct >= 50 or (projected_pct is not None and projected_pct >= 80):
        recommendation = "extend"
        reasons.append(f"Partial results ({attainment_pct:.0f}% achieved" + (f", {projected_pct:.0f}% projected" if projected_pct is not None else "") + ").")
        if critical_unmet:
            reasons.append("Critical KPI(s) not yet met: " + ", ".join(critical_unmet))
    else:
        recommendation = "close"
        reasons.append(f"Only {attainment_pct:.0f}% of weighted KPI targets achieved.")
    if open_serious:
        reasons.append(f"{len(open_serious)} high or critical incident(s) still open.")
    return {
        "recommendation": recommendation,
        "recommendation_label": DECISIONS[recommendation],
        "reasons": reasons,
        "attainment_pct": attainment_pct,
        "projected_pct": projected_pct,
        "critical_unmet": critical_unmet,
        "milestones_verified_pct": round(milestone_rate, 1),
        "milestones_on_time_pct": round(len(on_time) / len(verified) * 100, 1) if verified else None,
        "budget": agreement.get("budget", 0),
        "released": round(released, 2),
        "incidents_total": len(pilot.get("incidents", [])),
        "incidents_open": len([item for item in pilot.get("incidents", []) if item.get("status") == "open"]),
        "health": health,
    }


# --------------------------------------------------------------------------- #
# Startup progress reports
# --------------------------------------------------------------------------- #

def validate_report(agreement: Mapping[str, Any], milestone_states: Mapping[str, Mapping[str, Any]], payload: Mapping[str, Any], today: date) -> dict[str, Any]:
    start = parse_date(agreement["startDate"], "Start date")
    kpis = {item["kpiId"]: item for item in agreement["kpis"]}
    milestones = {item["milestoneId"]: item for item in agreement["milestones"]}

    measurements = []
    for item in payload.get("measurements") or []:
        if not isinstance(item, Mapping) or item.get("value") in (None, ""):
            continue
        kpi_id = str(item.get("kpiId") or "")
        if kpi_id not in kpis:
            raise ValueError("A measurement refers to an unknown KPI.")
        measured_on = parse_date(item.get("date"), f"Measurement date for {kpis[kpi_id]['name']}")
        if not start <= measured_on <= today:
            raise ValueError(f"{kpis[kpi_id]['name']}: measurement date must be between the pilot start and today.")
        measurements.append({
            "kpiId": kpi_id,
            "value": _number(item.get("value"), f"Value for {kpis[kpi_id]['name']}"),
            "date": measured_on.isoformat(),
            "evidence": _text(item.get("evidence"), "Measurement evidence", 2000, required=True),
        })

    claims = []
    for item in payload.get("milestoneClaims") or []:
        if not isinstance(item, Mapping):
            continue
        milestone_id = str(item.get("milestoneId") or "")
        if milestone_id not in milestones:
            raise ValueError("A completion claim refers to an unknown milestone.")
        if (milestone_states.get(milestone_id) or {}).get("status") in {"claimed", "verified"}:
            raise ValueError(f"{milestones[milestone_id]['title']} is already claimed or verified.")
        claims.append({"milestoneId": milestone_id, "evidence": _text(item.get("evidence"), "Completion evidence", 4000, required=True)})

    incidents = []
    for item in payload.get("incidents") or []:
        if not isinstance(item, Mapping) or not str(item.get("description") or "").strip():
            continue
        severity = str(item.get("severity") or "")
        if severity not in INCIDENT_SEVERITIES:
            raise ValueError("Choose an incident severity: Low, Medium, High or Critical.")
        incidents.append({"severity": severity, "description": _text(item.get("description"), "Incident description", 4000, required=True)})

    summary = _text(payload.get("summary"), "Progress summary", 4000, required=True)
    blockers = _text(payload.get("blockers"), "Blockers", 4000)
    if not measurements and not claims and not incidents and not blockers:
        raise ValueError("Add at least one KPI reading, milestone claim, blocker or incident.")
    return {"summary": summary, "blockers": blockers, "measurements": measurements, "milestoneClaims": claims, "incidents": incidents}


def cohort_comparison(pilots: list[Mapping[str, Any]], today: date) -> list[dict[str, Any]]:
    """Side-by-side view of every pilot running for the same challenge."""
    rows = []
    for pilot in pilots:
        row = {"pilotId": pilot["pilotId"], "startupName": pilot.get("startupName"), "stage": pilot["stage"], "stageLabel": STAGE_LABELS[pilot["stage"]]}
        if pilot["stage"] in {"active", "suspended", "review"} or pilot["stage"] in TERMINAL_STAGES and pilot.get("wentLiveAt"):
            card = results_scorecard(pilot, today)
            row.update({
                "rag": card["health"]["rag"],
                "health": card["health"]["score"],
                "attainment": card["attainment_pct"],
                "projected": card["projected_pct"],
                "milestones_verified_pct": card["milestones_verified_pct"],
                "released": card["released"],
                "budget": card["budget"],
                "incidents_open": card["incidents_open"],
            })
        rows.append(row)
    return sorted(rows, key=lambda row: -(row.get("attainment") or -1))


# --------------------------------------------------------------------------- #
# Monitoring: what needs an officer's attention on one programme
# --------------------------------------------------------------------------- #

ATTENTION_ORDER = {"critical": 0, "action": 1, "warning": 2, "upcoming": 3, "info": 4}


def programme_mode(pilot: Mapping[str, Any]) -> str:
    """Sandbox or Pilot, from the sent agreement or, before sending, the draft."""
    source = pilot.get("agreement") or pilot.get("agreementDraft") or {}
    return source.get("mode") if source.get("mode") in MODES else "Pilot"


def programme_attention(pilot: Mapping[str, Any], today: date) -> dict[str, Any]:
    """Summarise reporting status and list the actions an officer should take now."""
    stage = pilot["stage"]
    agreement = pilot.get("agreement") or {}
    items: list[dict[str, Any]] = []

    def add(kind: str, message: str, when: str | None = None) -> None:
        items.append({"kind": kind, "message": message, "date": when})

    report = {"next_due": None, "status": "Not reporting", "days_overdue": 0, "last_report": None}
    counts = {"pending_readings": 0, "claims": 0, "unpaid": 0, "open_serious": 0}

    if stage == "awaiting_acceptance":
        sent = (pilot.get("agreementHistory") or [{}])[-1].get("sentAt", "")[:10] or None
        add("info", f"Waiting for the startup to accept agreement version {pilot.get('agreementVersion')}", sent)
    elif stage == "draft" and pilot.get("changeRequests"):
        add("action", "Startup requested changes to the agreement", pilot["changeRequests"][-1].get("at", "")[:10])
    elif stage == "draft":
        add("action", "Agreement not yet sent to the startup")
    elif stage == "readiness":
        outstanding = readiness_complete(agreement["mode"], pilot.get("readiness", {}))
        if outstanding:
            add("action", f"{len(outstanding)} readiness check(s) before go-live")
        else:
            add("action", "All readiness checks complete: ready to go live")
    elif stage == "review":
        add("action", "Evaluation board decision pending")

    if stage in {"active", "suspended", "review"}:
        counts["pending_readings"] = sum(1 for item in pilot.get("measurements", []) if item.get("status") == "pending")
        if counts["pending_readings"]:
            add("action", f"{counts['pending_readings']} KPI reading(s) to verify")
        milestones = milestone_view(agreement, pilot.get("milestoneStates", {}), today)
        paid = {item["milestoneId"] for item in pilot.get("payments", [])}
        for milestone in milestones:
            if milestone["status"] == "claimed":
                counts["claims"] += 1
                add("action", f"Verify completion claim: {milestone['title']}", (milestone.get("claimedAt") or "")[:10] or None)
            elif milestone["status"] == "verified" and milestone["amount"] > 0 and milestone["milestoneId"] not in paid:
                counts["unpaid"] += 1
                add("action", f"Release payment for {milestone['title']} (₹{milestone['amount']:,.0f})")
            elif milestone["overdue"]:
                add("warning", f"Milestone overdue: {milestone['title']}", milestone["dueDate"])
            elif stage != "review" and 0 <= (parse_date(milestone["dueDate"], "Due date") - today).days <= 14:
                add("upcoming", f"Milestone due: {milestone['title']}", milestone["dueDate"])
        for incident in pilot.get("incidents", []):
            if incident.get("status") == "open":
                serious = incident["severity"] in {"High", "Critical"}
                counts["open_serious"] += serious
                add("critical" if serious else "warning", f"{incident['severity']} incident open: {incident['description'][:80]}", (incident.get("reportedAt") or "")[:10] or None)

    if stage in {"active", "suspended"}:
        due = next_report_due(pilot)
        last = last_report_date(pilot.get("reports", []))
        report.update({"next_due": due.isoformat() if due else None, "last_report": last.isoformat() if last else None})
        if due:
            late = (today - due).days
            if late > REPORT_GRACE_DAYS:
                report.update({"status": "Overdue", "days_overdue": late})
                add("critical", f"Progress report overdue by {late} days", due.isoformat())
            elif late >= 0:
                report["status"] = "Due now"
                add("action", "Progress report due", due.isoformat())
            elif -late <= 3:
                report["status"] = "Due soon"
                add("upcoming", "Progress report due", due.isoformat())
            else:
                report["status"] = "On schedule"
        if stage == "active" and today >= parse_date(agreement["endDate"], "End date"):
            add("action", "End date reached: start the results review", agreement["endDate"])
        if stage == "suspended":
            add("warning", "Programme suspended")

    items.sort(key=lambda item: (ATTENTION_ORDER[item["kind"]], item["date"] or "9999"))
    days_left = None
    if agreement and stage in {"active", "suspended"}:
        days_left = (parse_date(agreement["endDate"], "End date") - today).days
    return {
        "mode": programme_mode(pilot),
        "items": items,
        "urgent": sum(1 for item in items if item["kind"] in {"critical", "action"}),
        "report": report,
        "counts": counts,
        "days_left": days_left,
    }
