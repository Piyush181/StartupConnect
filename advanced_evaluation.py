"""Advanced evaluation engine for startup applications to government challenges.

Everything in this module is pure computation: no Flask, no database, no file I/O.
The Flask routes in app.py load and persist data and call these functions, which
keeps the scoring rules easy to test and audit.

Stages covered:
  1. Automated pre-assessment of the submitted application (advisory only).
  2. Multi-member panel scoring with conflict-of-interest recusal, aggregation,
     divergence detection and moderation.
  3. Risk assessment (likelihood x impact) across delivery risk dimensions.
  4. Quality-and-Cost Based Selection (QCBS) with a technical qualifying threshold.
  5. Ranking with weight-sensitivity analysis and a recommendation per startup.
"""

from __future__ import annotations

import math
import re
import statistics
from typing import Any, Iterable, Mapping

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

AGGREGATION_METHODS = {
    "mean": "Mean of panel scores",
    "median": "Median of panel scores",
    "trimmed_mean": "Trimmed mean (highest and lowest score dropped when 4+ panelists)",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "technicalWeight": 70,
    "financialWeight": 30,
    "technicalThreshold": 60,
    "divergenceThreshold": 25,
    "aggregation": "trimmed_mean",
    "minimumPanelSize": 3,
    "riskPenaltyMax": 10,
}

RISK_DIMENSIONS: list[tuple[str, str]] = [
    ("technical", "Technical delivery"),
    ("schedule", "Schedule"),
    ("financial", "Financial viability"),
    ("data_security", "Data security and privacy"),
    ("compliance", "Regulatory compliance"),
    ("vendor_dependency", "Vendor dependency"),
]
RISK_KEYS = {key for key, _label in RISK_DIMENSIONS}

READINESS_LEVELS = [
    (4, "Deployed", ("deployed", "production", "live", "commercial", "scaled", "scale-up", "scaling", "rolled out")),
    (3, "Pilot", ("pilot", "field trial", "field-tested", "beta")),
    (2, "Prototype", ("prototype", "proof of concept", "poc", "mvp", "minimum viable", "demo", "alpha")),
    (1, "Concept", ("idea", "concept", "ideation", "research", "design stage", "planning")),
]

CORE_NARRATIVE_FIELDS = (
    "solution_description",
    "technology_approach",
    "implementation_approach",
    "expected_outcomes",
    "measurable_impact",
)

REQUIRED_FIELDS = (
    "problem_addressed",
    "challenge_solution",
    "solution_description",
    "technology_approach",
    "development_stage",
    "implementation_approach",
    "expected_timeline",
    "expected_outcomes",
    "target_users",
    "measurable_impact",
)

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "into",
    "is", "it", "its", "of", "on", "or", "that", "the", "their", "this", "to", "with", "within",
    "will", "should", "must", "shall", "can", "may", "all", "any", "each", "other", "such", "than",
    "then", "these", "those", "using", "used", "use", "based", "including", "relevant", "existing",
    "provide", "support", "ensure", "system", "solution", "aligned", "described", "problem",
}


def _number(value: Any, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a number.") from error
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number.")
    return result


def normalize_config(raw: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate an evaluation configuration and fill defaults."""
    raw = dict(raw or {})
    config = dict(DEFAULT_CONFIG)
    for key in ("technicalWeight", "financialWeight", "technicalThreshold", "divergenceThreshold", "riskPenaltyMax"):
        if raw.get(key) not in (None, ""):
            config[key] = _number(raw[key], key)
    if raw.get("minimumPanelSize") not in (None, ""):
        size = _number(raw["minimumPanelSize"], "Minimum panel size")
        if not size.is_integer():
            raise ValueError("Minimum panel size must be a whole number.")
        config["minimumPanelSize"] = int(size)
    if raw.get("aggregation") not in (None, ""):
        config["aggregation"] = str(raw["aggregation"]).strip()

    if config["technicalWeight"] < 0 or config["financialWeight"] < 0:
        raise ValueError("Technical and financial weights cannot be negative.")
    if round(config["technicalWeight"] + config["financialWeight"], 6) != 100:
        raise ValueError("Technical and financial weights must add up to 100.")
    if config["technicalWeight"] < 50:
        raise ValueError("Technical weight must be at least 50 so quality is never outweighed by price alone.")
    if not 0 <= config["technicalThreshold"] <= 100:
        raise ValueError("Technical qualifying threshold must be between 0 and 100.")
    if not 5 <= config["divergenceThreshold"] <= 100:
        raise ValueError("Divergence threshold must be between 5 and 100 percent.")
    if not 0 <= config["riskPenaltyMax"] <= 30:
        raise ValueError("Maximum risk penalty must be between 0 and 30 percent.")
    if not 1 <= config["minimumPanelSize"] <= 15:
        raise ValueError("Minimum panel size must be between 1 and 15.")
    if config["aggregation"] not in AGGREGATION_METHODS:
        raise ValueError("Choose mean, median, or trimmed mean aggregation.")
    return config


# --------------------------------------------------------------------------- #
# Stage 1: automated pre-assessment
# --------------------------------------------------------------------------- #

def _stem(word: str) -> str:
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ities", "ity", "ies", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", str(text or "").casefold())
    return {_stem(word) for word in words if len(word) >= 3 and word not in _STOPWORDS}


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", str(text or "")))


def _is_placeholder(text: str) -> bool:
    value = str(text or "").strip().casefold()
    return value in {"", "na", "n/a", "none", "nil", "no", "-", "not applicable", "tbd", "to be decided"}


def challenge_requirements(challenge: Mapping[str, Any]) -> list[str]:
    """Mandatory requirements and mandatory features, de-duplicated, in order."""
    requirements = challenge.get("requirements") or {}
    items: list[str] = []
    if isinstance(requirements, Mapping):
        for value in requirements.get("mandatory") or []:
            items.append(str(value))
        for feature in requirements.get("features") or []:
            if isinstance(feature, Mapping) and str(feature.get("priority", "")).casefold() == "mandatory":
                items.append(str(feature.get("name") or ""))
    seen: set[str] = set()
    result = []
    for item in items:
        cleaned = item.strip()
        if cleaned and cleaned.casefold() not in seen:
            seen.add(cleaned.casefold())
            result.append(cleaned)
    return result


def readiness_level(development_stage: str) -> dict[str, Any]:
    text = str(development_stage or "").casefold()
    for level, label, keywords in READINESS_LEVELS:
        if any(keyword in text for keyword in keywords):
            return {"level": level, "label": label, "score": round(level / 4 * 100, 2)}
    return {"level": 0, "label": "Not stated", "score": 0.0}


def pre_assessment(challenge: Mapping[str, Any], application_data: Mapping[str, Any]) -> dict[str, Any]:
    """Rule-based screening of a submitted application.

    The result is an advisory indicator to focus reviewer attention. It is never
    used as, or blended into, the panel's technical score.
    """
    data = {key: str(value or "") for key, value in dict(application_data or {}).items()}

    # Completeness: required answers present, and core narrative answers substantive.
    filled_required = [field for field in REQUIRED_FIELDS if not _is_placeholder(data.get(field))]
    substantive = [field for field in CORE_NARRATIVE_FIELDS if _word_count(data.get(field)) >= 40]
    completeness = 60 * len(filled_required) / len(REQUIRED_FIELDS) + 40 * len(substantive) / len(CORE_NARRATIVE_FIELDS)
    thin_answers = [field for field in CORE_NARRATIVE_FIELDS if 0 < _word_count(data.get(field)) < 40]

    # Requirement coverage: keyword overlap between each requirement and the whole application.
    application_terms = _terms(" ".join(data.values()))
    coverage_items = []
    for requirement in challenge_requirements(challenge):
        keywords = _terms(requirement)
        if not keywords:
            continue
        matched = sorted(keywords & application_terms)
        ratio = len(matched) / len(keywords)
        status = "covered" if ratio >= 0.6 else "partial" if ratio >= 0.3 else "missing"
        coverage_items.append({"requirement": requirement, "status": status, "matched_terms": matched, "match_ratio": round(ratio, 2)})
    if coverage_items:
        coverage = 100 * sum(1 if item["status"] == "covered" else 0.5 if item["status"] == "partial" else 0 for item in coverage_items) / len(coverage_items)
    else:
        coverage = None

    readiness = readiness_level(data.get("development_stage", ""))

    # Evidence strength.
    quantified_impact = bool(re.search(r"\d", data.get("measurable_impact", "")))
    has_deployments = not _is_placeholder(data.get("previous_deployments"))
    has_documents = bool(re.search(r"https?://|\.pdf\b|report|certificat|case stud|letter|testimonial", data.get("supporting_evidence", ""), re.I))
    has_experience = _word_count(data.get("relevant_experience")) >= 20
    evidence = 30 * quantified_impact + 30 * has_deployments + 25 * has_documents + 15 * has_experience

    flags: list[dict[str, str]] = []
    if not quantified_impact:
        flags.append({"severity": "warning", "message": "Measurable impact has no quantified targets or baselines."})
    if _is_placeholder(data.get("expected_timeline")) or not re.search(r"\d|week|month|quarter|phase", data.get("expected_timeline", ""), re.I):
        flags.append({"severity": "warning", "message": "Delivery timeline does not state durations or phases."})
    missing = [item["requirement"] for item in coverage_items if item["status"] == "missing"]
    if missing:
        flags.append({"severity": "critical", "message": f"{len(missing)} mandatory requirement(s) not addressed: " + "; ".join(missing)})
    if readiness["level"] <= 1 and str(challenge.get("difficulty", "")) in {"Advanced", "Expert"}:
        flags.append({"severity": "warning", "message": f"Solution is at {readiness['label'].lower()} stage for an {challenge.get('difficulty', '').lower()} challenge."})
    if thin_answers:
        flags.append({"severity": "info", "message": "Short answers (under 40 words): " + ", ".join(field.replace("_", " ") for field in thin_answers)})
    narratives = [data.get(field, "").strip().casefold() for field in CORE_NARRATIVE_FIELDS if data.get(field, "").strip()]
    if len(narratives) != len(set(narratives)):
        flags.append({"severity": "warning", "message": "The same text is repeated across several answers."})
    if data.get("clarification_response", "").strip():
        flags.append({"severity": "info", "message": "Startup has submitted a clarification response; review it alongside the original answers."})

    components = [(completeness, 0.30), (readiness["score"], 0.15), (evidence, 0.20)]
    components.append((coverage if coverage is not None else completeness, 0.35))
    indicator = sum(value * weight for value, weight in components)
    band = "Strong" if indicator >= 70 else "Adequate" if indicator >= 45 else "Weak"
    return {
        "indicator": round(indicator, 2),
        "band": band,
        "completeness": round(completeness, 2),
        "requirement_coverage": None if coverage is None else round(coverage, 2),
        "coverage_items": coverage_items,
        "readiness": readiness,
        "evidence": {
            "score": evidence,
            "quantified_impact": quantified_impact,
            "previous_deployments": has_deployments,
            "supporting_documents": has_documents,
            "relevant_experience": has_experience,
        },
        "flags": flags,
    }


def suggested_risks(pre: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Starting-point likelihood values derived from the pre-assessment.

    Reviewers must confirm or change them; they are never saved automatically.
    """
    readiness = int((pre.get("readiness") or {}).get("level") or 0)
    technical = {4: 1, 3: 2, 2: 3, 1: 4}.get(readiness, 4)
    timeline_flag = any("timeline" in flag["message"] for flag in pre.get("flags", []))
    evidence = pre.get("evidence") or {}
    suggestions = {
        "technical": {"likelihood": technical, "impact": 4},
        "schedule": {"likelihood": 4 if timeline_flag else 2, "impact": 3},
        "financial": {"likelihood": 2 if evidence.get("previous_deployments") else 3, "impact": 3},
        "data_security": {"likelihood": 3, "impact": 4},
        "compliance": {"likelihood": 2, "impact": 4},
        "vendor_dependency": {"likelihood": 3, "impact": 2},
    }
    return suggestions


# --------------------------------------------------------------------------- #
# Stage 2: panel scoring
# --------------------------------------------------------------------------- #

def validate_scorecard(criteria: list[Mapping[str, Any]], payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one panelist's independent scorecard."""
    name = str(payload.get("panelistName") or "").strip()
    role = str(payload.get("panelistRole") or "").strip()
    if not name:
        raise ValueError("Enter the panelist's name.")
    if len(name) > 120 or len(role) > 120:
        raise ValueError("Panelist name and role must be under 120 characters.")
    conflict = str(payload.get("conflictOfInterest") or "").strip().lower()
    if conflict not in {"none", "declared"}:
        raise ValueError("Record the panelist's conflict-of-interest declaration before scoring.")
    conflict_note = str(payload.get("conflictNote") or "").strip()
    if conflict == "declared" and not conflict_note:
        raise ValueError("Describe the declared conflict of interest.")
    if len(conflict_note) > 2000:
        raise ValueError("Conflict note must be under 2,000 characters.")

    raw_scores = payload.get("scores") or {}
    raw_comments = payload.get("comments") or {}
    if not isinstance(raw_scores, Mapping) or not isinstance(raw_comments, Mapping):
        raise ValueError("Scores and comments must be keyed by criterion.")
    known = {item["criterion"] for item in criteria}
    unknown = set(raw_scores) - known
    if unknown:
        raise ValueError("Unknown criterion in scorecard: " + ", ".join(sorted(unknown)))

    scores: dict[str, float | None] = {}
    comments: dict[str, str] = {}
    if conflict == "none":
        for item in criteria:
            name_key = item["criterion"]
            value = raw_scores.get(name_key)
            if value in (None, ""):
                if item.get("required", True):
                    raise ValueError(f"Score every required criterion ({name_key} is missing).")
                scores[name_key] = None
            else:
                score = _number(value, f"Score for {name_key}")
                if not 0 <= score <= item["maximum_score"]:
                    raise ValueError(f"Score for {name_key} must be between 0 and {item['maximum_score']:g}.")
                scores[name_key] = score
            comment = str(raw_comments.get(name_key) or "").strip()
            if len(comment) > 2000:
                raise ValueError("Each criterion comment must be under 2,000 characters.")
            comments[name_key] = comment
    overall = str(payload.get("overallComment") or "").strip()
    if len(overall) > 4000:
        raise ValueError("Overall comment must be under 4,000 characters.")
    return {
        "panelistId": re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-"),
        "panelistName": name,
        "panelistRole": role,
        "conflictOfInterest": conflict,
        "conflictNote": conflict_note,
        "recused": conflict == "declared",
        "scores": scores,
        "comments": comments,
        "overallComment": overall,
    }


def _aggregate(values: list[float], method: str) -> float:
    if method == "median":
        return statistics.median(values)
    if method == "trimmed_mean" and len(values) >= 4:
        ordered = sorted(values)[1:-1]
        return sum(ordered) / len(ordered)
    return sum(values) / len(values)


def aggregate_panel(
    criteria: list[Mapping[str, Any]],
    scorecards: Iterable[Mapping[str, Any]],
    config: Mapping[str, Any],
    moderation: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Combine independent panel scorecards into one technical score (0-100)."""
    moderation = dict(moderation or {})
    cards = list(scorecards)
    active = [card for card in cards if not card.get("recused")]
    method = config["aggregation"]
    rows = []
    weighted_total = 0.0
    weight_total = 0.0
    divergent = []
    for item in criteria:
        name = item["criterion"]
        maximum = float(item["maximum_score"])
        weight = float(item["weight"])
        values = [float(card["scores"][name]) for card in active if card.get("scores", {}).get(name) is not None]
        row: dict[str, Any] = {
            "criterion": name,
            "maximum_score": maximum,
            "weight": weight,
            "scores": values,
            "panel_size": len(values),
        }
        if values:
            spread_pct = (max(values) - min(values)) / maximum * 100
            aggregated = _aggregate(values, method)
            row.update({
                "mean": round(sum(values) / len(values), 2),
                "median": round(statistics.median(values), 2),
                "std_dev": round(statistics.pstdev(values), 2),
                "min": min(values),
                "max": max(values),
                "spread_pct": round(spread_pct, 1),
                "aggregated": round(aggregated, 2),
                "divergent": len(values) >= 2 and spread_pct > config["divergenceThreshold"],
            })
            moderated = moderation.get(name)
            if moderated is not None:
                row["moderated"] = {"score": float(moderated["score"]), "note": moderated.get("note", ""), "by": moderated.get("by"), "at": moderated.get("at")}
                aggregated = float(moderated["score"])
            row["final"] = round(aggregated, 2)
            if row["divergent"] and moderated is None:
                divergent.append(name)
            weighted_total += aggregated / maximum * weight
            weight_total += weight
        else:
            row.update({"aggregated": None, "final": None, "divergent": False})
        rows.append(row)

    scored_all_required = all(row["final"] is not None for row, item in zip(rows, criteria) if item.get("required", True))
    technical_score = round(weighted_total / weight_total * 100, 2) if weight_total and scored_all_required else None

    # Reviewer calibration: how far each panelist sits from the panel on average.
    calibration = []
    for card in active:
        deltas = []
        for row in rows:
            own = card.get("scores", {}).get(row["criterion"])
            if own is not None and row.get("aggregated") is not None and row["panel_size"] >= 2:
                deltas.append((float(own) - row["mean"]) / row["maximum_score"] * 100)
        if deltas:
            bias = sum(deltas) / len(deltas)
            tendency = "Lenient" if bias > 10 else "Strict" if bias < -10 else "Consistent"
            calibration.append({"panelistName": card["panelistName"], "bias_pct": round(bias, 1), "tendency": tendency})

    panel_size = len(active)
    if panel_size == 0:
        confidence = "None"
    elif panel_size < config["minimumPanelSize"]:
        confidence = "Low"
    elif divergent:
        confidence = "Medium"
    else:
        confidence = "High"
    return {
        "method": method,
        "panel_size": panel_size,
        "recused": [card["panelistName"] for card in cards if card.get("recused")],
        "criteria": rows,
        "technical_score": technical_score,
        "divergent_criteria": divergent,
        "confidence": confidence,
        "calibration": calibration,
    }


def validate_moderation(criteria: list[Mapping[str, Any]], payload: Mapping[str, Any]) -> dict[str, Any]:
    by_name = {item["criterion"]: item for item in criteria}
    name = str(payload.get("criterion") or "").strip()
    if name not in by_name:
        raise ValueError("Choose a valid criterion to moderate.")
    note = str(payload.get("note") or "").strip()
    if not note:
        raise ValueError("Record the consensus discussion outcome before moderating a score.")
    if len(note) > 4000:
        raise ValueError("Moderation note must be under 4,000 characters.")
    score = _number(payload.get("score"), "Moderated score")
    if not 0 <= score <= by_name[name]["maximum_score"]:
        raise ValueError(f"Moderated score must be between 0 and {by_name[name]['maximum_score']:g}.")
    return {"criterion": name, "score": score, "note": note}


# --------------------------------------------------------------------------- #
# Stage 3: risk
# --------------------------------------------------------------------------- #

def risk_level(rating: float) -> str:
    if rating > 15:
        return "Critical"
    if rating > 9:
        return "High"
    if rating > 4:
        return "Medium"
    return "Low"


def validate_risk(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    raw = payload.get("risks")
    if not isinstance(raw, Mapping):
        raise ValueError("Risk assessment must be keyed by risk dimension.")
    missing = RISK_KEYS - set(raw)
    if missing:
        raise ValueError("Assess every risk dimension before saving.")
    result = {}
    for key, _label in RISK_DIMENSIONS:
        entry = raw[key]
        if not isinstance(entry, Mapping):
            raise ValueError("Each risk entry must include likelihood and impact.")
        likelihood = _number(entry.get("likelihood"), "Likelihood")
        impact = _number(entry.get("impact"), "Impact")
        if likelihood not in {1, 2, 3, 4, 5} or impact not in {1, 2, 3, 4, 5}:
            raise ValueError("Likelihood and impact must be whole numbers from 1 to 5.")
        mitigation = str(entry.get("mitigation") or "").strip()
        if len(mitigation) > 2000:
            raise ValueError("Mitigation notes must be under 2,000 characters.")
        if likelihood * impact > 9 and not mitigation:
            raise ValueError("Add a mitigation for every high or critical risk.")
        result[key] = {"likelihood": int(likelihood), "impact": int(impact), "mitigation": mitigation}
    return result


def risk_profile(risks: Mapping[str, Mapping[str, Any]] | None, config: Mapping[str, Any]) -> dict[str, Any]:
    if not risks:
        return {"assessed": False, "index": None, "level": "Not assessed", "penalty_pct": 0.0, "dimensions": []}
    dimensions = []
    for key, label in RISK_DIMENSIONS:
        entry = risks.get(key) or {}
        rating = int(entry.get("likelihood", 0)) * int(entry.get("impact", 0))
        dimensions.append({"key": key, "label": label, **entry, "rating": rating, "level": risk_level(rating)})
    index = sum(item["rating"] for item in dimensions) / (25 * len(dimensions)) * 100
    critical = [item["label"] for item in dimensions if item["level"] == "Critical"]
    overall = "Critical" if critical else risk_level(index / 100 * 25)
    penalty = index / 100 * float(config["riskPenaltyMax"])
    return {
        "assessed": True,
        "index": round(index, 1),
        "level": overall,
        "critical": critical,
        "penalty_pct": round(penalty, 2),
        "dimensions": dimensions,
    }


# --------------------------------------------------------------------------- #
# Stages 4 & 5: QCBS ranking and sensitivity
# --------------------------------------------------------------------------- #

def _score_field(entries: list[dict[str, Any]], technical_weight: float, config: Mapping[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    financial_weight = 100 - technical_weight
    qualified = [item for item in entries if item["technical_score"] is not None and item["technical_score"] >= config["technicalThreshold"]]
    quotes = [item["quote"] for item in qualified if item.get("quote")]
    financial_applied = bool(qualified) and len(quotes) == len(qualified) and financial_weight > 0
    lowest = min(quotes) if financial_applied else None
    qualified_ids = {item["application_id"] for item in qualified}
    scored = []
    for item in entries:
        result = dict(item)
        is_qualified = item["application_id"] in qualified_ids
        financial = round(lowest / item["quote"] * 100, 2) if financial_applied and is_qualified else None
        if is_qualified:
            composite = (technical_weight * item["technical_score"] + financial_weight * financial) / 100 if financial_applied else item["technical_score"]
            adjusted = composite * (1 - item.get("risk_penalty_pct", 0) / 100)
        else:
            composite = adjusted = None
        result.update({
            "qualified": is_qualified,
            "financial_score": financial,
            "composite_score": None if composite is None else round(composite, 2),
            "risk_adjusted_score": None if adjusted is None else round(adjusted, 2),
        })
        scored.append(result)
    ranked = sorted(
        [item for item in scored if item["qualified"]],
        key=lambda item: (-item["risk_adjusted_score"], -item["technical_score"], item.get("risk_penalty_pct", 0), item["application_id"]),
    )
    for position, item in enumerate(ranked, start=1):
        item["rank"] = position
    for item in scored:
        item.setdefault("rank", None)
    return scored, financial_applied


def rank_applications(entries: list[dict[str, Any]], config: Mapping[str, Any], maximum_selected: int | None = None) -> dict[str, Any]:
    """Rank applications with QCBS, risk adjustment and weight-sensitivity analysis.

    Each entry needs: application_id, startup_name, technical_score (or None),
    quote (or None), risk_penalty_pct, confidence, risk_level.
    """
    base, financial_applied = _score_field(entries, config["technicalWeight"], config)

    scenarios = []
    for shift in (-20, -10, 10, 20):
        weight = min(100, max(50, config["technicalWeight"] + shift))
        if weight == config["technicalWeight"] or any(item["technicalWeight"] == weight for item in scenarios):
            continue
        scenario, _ = _score_field(entries, weight, config)
        ranks = {item["application_id"]: item["rank"] for item in scenario}
        leader = next((item["application_id"] for item in scenario if item["rank"] == 1), None)
        scenarios.append({"technicalWeight": weight, "financialWeight": 100 - weight, "leader": leader, "ranks": ranks})

    base_leader = next((item["application_id"] for item in base if item["rank"] == 1), None)
    for item in base:
        observed = [item["rank"]] + [scenario["ranks"].get(item["application_id"]) for scenario in scenarios]
        observed = [value for value in observed if value is not None]
        item["rank_range"] = [min(observed), max(observed)] if observed else None
        if item["technical_score"] is None:
            item["recommendation"] = "Awaiting panel scores"
        elif not item["qualified"]:
            item["recommendation"] = "Below technical threshold"
        elif item.get("risk_level") == "Not assessed":
            item["recommendation"] = "Hold: risk not assessed"
        elif item.get("risk_level") == "Critical":
            item["recommendation"] = "Hold: critical risk"
        elif item.get("confidence") in {"Low", "None"}:
            item["recommendation"] = "Hold: panel too small"
        elif maximum_selected is None or item["rank"] <= maximum_selected:
            item["recommendation"] = "Recommend"
        else:
            item["recommendation"] = "Reserve list"
    order = sorted(base, key=lambda item: (item["rank"] is None, item["rank"] or 0, -(item["technical_score"] or -1), item["startup_name"].casefold()))
    return {
        "applications": order,
        "financial_applied": financial_applied,
        "leader": base_leader,
        "leader_is_robust": bool(base_leader) and all(scenario["leader"] == base_leader for scenario in scenarios),
        "scenarios": [{key: value for key, value in scenario.items() if key != "ranks"} for scenario in scenarios],
    }
