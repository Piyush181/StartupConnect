"""Persistence helpers for Startup Connect registration data.

Fill in MYSQL_CONFIG before connecting this application to MySQL. Keep the
encryption key outside source control and use the same key for future reads.
"""

import json
import os
import uuid
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping, cast

import mysql.connector
from cryptography.fernet import Fernet
from mysql.connector.errors import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


# Replace these values manually, or set the matching environment variables.
MYSQL_CONFIG = {
    "host": os.getenv("STARTUP_CONNECT_DB_HOST", "localhost"),
    "user": os.getenv("STARTUP_CONNECT_DB_USER", "root"),
    "password": os.getenv("STARTUP_CONNECT_DB_PASSWORD", "Soham@14"),
    "database": "startupconnect"
}

# Generate once with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
ENCRYPTION_KEY = os.getenv("STARTUP_CONNECT_ENCRYPTION_KEY", "iT69HvA01a7EPP6GlVpX1ugL0bcAUY1UXoTG-ZLs2QU=")


class DuplicateBusinessIdError(Exception):
    """Raised when a startup chooses an existing business ID."""


class DatabaseConfigurationError(Exception):
    """Raised when database or encryption configuration is incomplete."""


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS startup_registrations (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    business_id_encrypted TEXT NOT NULL,
    business_id_hash CHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    business_name VARCHAR(255) NOT NULL,
    business_type VARCHAR(100) NOT NULL,
    cin_encrypted TEXT NOT NULL,
    ownership_details TEXT NOT NULL,
    incorporation_date DATE NOT NULL,
    sector VARCHAR(255) NOT NULL,
    domain TEXT NOT NULL,
    employee_count INT NOT NULL,
    current_stage VARCHAR(100) NOT NULL,
    company_address TEXT NOT NULL,
    company_email VARCHAR(255) NOT NULL,
    company_phone VARCHAR(80) NOT NULL,
    website VARCHAR(500),
    pincode VARCHAR(20) NOT NULL,
    representative_encrypted TEXT NOT NULL,
    gstin_encrypted TEXT NOT NULL,
    gst_state VARCHAR(100) NOT NULL,
    gst_details TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

MINFO_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS minfo (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    ministry_id_encrypted TEXT NOT NULL,
    auth_code_encrypted TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

CONTRACTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS contracts (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    challenge_id VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(500) NOT NULL,
    government_body VARCHAR(255) NOT NULL,
    department VARCHAR(255) NOT NULL,
    state VARCHAR(100) NOT NULL,
    status VARCHAR(30) NOT NULL,
    created_by VARCHAR(255) NOT NULL,
    challenge_data LONGTEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_contracts_status (status),
    INDEX idx_contracts_created_by (created_by)
)
"""

CONTRACT_REPORTS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS contract_reports (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    report_id VARCHAR(120) NOT NULL UNIQUE,
    challenge_id VARCHAR(100) NOT NULL,
    check_id VARCHAR(120) NOT NULL,
    startup_id VARCHAR(255) NOT NULL,
    status VARCHAR(30) NOT NULL,
    report_data LONGTEXT NOT NULL,
    review_data LONGTEXT,
    submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    reviewed_at TIMESTAMP NULL,
    INDEX idx_contract_reports_challenge (challenge_id),
    INDEX idx_contract_reports_startup (startup_id),
    INDEX idx_contract_reports_status (status)
)
"""

APPLICATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS applications (
    application_id VARCHAR(80) NOT NULL PRIMARY KEY,
    challenge_id VARCHAR(100) NOT NULL,
    business_id_encrypted TEXT NOT NULL,
    business_id_hash CHAR(64) NOT NULL,
    status VARCHAR(40) NOT NULL,
    application_data LONGTEXT NOT NULL,
    submitted_at TIMESTAMP NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_applications_challenge_business (challenge_id, business_id_hash),
    INDEX idx_applications_challenge (challenge_id),
    INDEX idx_applications_business (business_id_hash),
    INDEX idx_applications_status (status)
)
"""

APPLICATION_SCREENINGS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_screenings (
    screening_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    application_id VARCHAR(80) NOT NULL,
    reviewer_id VARCHAR(255) NOT NULL,
    reviewer_role VARCHAR(30) NOT NULL,
    requirement TEXT NOT NULL,
    decision VARCHAR(40) NOT NULL,
    comment TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_screenings_application (application_id),
    INDEX idx_screenings_requirement (application_id, screening_id)
)
"""

APPLICATION_SCREENING_AUDIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_screening_audit (
    audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    application_id VARCHAR(80) NOT NULL,
    reviewer_id VARCHAR(255) NOT NULL,
    reviewer_role VARCHAR(30) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    details LONGTEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_screening_audit_application (application_id),
    INDEX idx_screening_audit_event (application_id, event_type)
)
"""

APPLICATION_EVALUATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_evaluations (
    evaluation_id VARCHAR(80) NOT NULL PRIMARY KEY,
    application_id VARCHAR(80) NOT NULL UNIQUE,
    reviewer_id VARCHAR(255) NOT NULL,
    reviewer_role VARCHAR(30) NOT NULL,
    total_score DECIMAL(10, 2) NOT NULL DEFAULT 0,
    maximum_total_score DECIMAL(10, 2) NOT NULL DEFAULT 0,
    status VARCHAR(30) NOT NULL,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_evaluations_status (status)
)
"""

APPLICATION_EVALUATION_SCORES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_evaluation_scores (
    score_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    evaluation_id VARCHAR(80) NOT NULL,
    application_id VARCHAR(80) NOT NULL,
    reviewer_id VARCHAR(255) NOT NULL,
    reviewer_role VARCHAR(30) NOT NULL,
    criterion VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    score DECIMAL(10, 2) NULL,
    maximum_score DECIMAL(10, 2) NOT NULL,
    weight DECIMAL(10, 2) NOT NULL,
    is_required TINYINT(1) NOT NULL DEFAULT 1,
    comment TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_evaluation_criterion (evaluation_id, criterion),
    INDEX idx_evaluation_scores_application (application_id)
)
"""

APPLICATION_EVALUATION_AUDIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_evaluation_audit (
    audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    application_id VARCHAR(80) NOT NULL,
    evaluation_id VARCHAR(80) NOT NULL,
    reviewer_id VARCHAR(255) NOT NULL,
    reviewer_role VARCHAR(30) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    details LONGTEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_evaluation_audit_application (application_id),
    INDEX idx_evaluation_audit_evaluation (evaluation_id, audit_id)
)
"""

APPLICATION_SHORTLIST_DECISIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_shortlist_decisions (
    decision_id VARCHAR(80) NOT NULL PRIMARY KEY,
    application_id VARCHAR(80) NOT NULL UNIQUE,
    decision VARCHAR(30) NOT NULL,
    decision_maker VARCHAR(255) NOT NULL,
    decision_role VARCHAR(30) NOT NULL,
    comments TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_shortlist_decision (decision)
)
"""

APPLICATION_SHORTLIST_AUDIT_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS application_shortlist_audit (
    audit_id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    application_id VARCHAR(80) NOT NULL,
    decision_id VARCHAR(80) NOT NULL,
    decision_maker VARCHAR(255) NOT NULL,
    decision_role VARCHAR(30) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    details LONGTEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_shortlist_audit_application (application_id),
    INDEX idx_shortlist_audit_decision (decision_id, audit_id)
)
"""


class DuplicateApplicationError(Exception):
    """Raised when a startup attempts to modify an already-submitted application."""


def _cipher() -> Fernet:
    if ENCRYPTION_KEY.startswith("REPLACE_WITH"):
        raise DatabaseConfigurationError(
            "Set STARTUP_CONNECT_ENCRYPTION_KEY before submitting registrations."
        )
    try:
        return Fernet(ENCRYPTION_KEY.encode())
    except (ValueError, TypeError) as error:
        raise DatabaseConfigurationError("STARTUP_CONNECT_ENCRYPTION_KEY is invalid.") from error


def _encrypted(cipher: Fernet, value: str) -> str:
    return cipher.encrypt(value.encode("utf-8")).decode("utf-8")


def _lookup_hash(value: str) -> str:
    """Create a stable lookup token without storing the identifier itself."""
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _required(data: Mapping[str, str], key: str) -> str:
    value = str(data.get(key, "")).strip()
    if not value:
        raise ValueError(f"Missing required registration field: {key}")
    return value


def save_startup_registration(data: Mapping[str, str]) -> None:
    """Validate, encrypt, and persist one complete startup registration."""
    cipher = _cipher()
    business_id = _required(data, "business_id")
    password = _required(data, "password")
    if password != _required(data, "password_confirmation"):
        raise ValueError("Passwords do not match.")

    representative = {
        "name": _required(data, "representative_name"),
        "title": _required(data, "representative_title"),
        "email": _required(data, "representative_email"),
        "phone": _required(data, "representative_phone"),
    }
    values = (
        _encrypted(cipher, business_id),
        _lookup_hash(business_id),
        generate_password_hash(password),
        _required(data, "business_name"),
        _required(data, "business_type"),
        _encrypted(cipher, _required(data, "cin")),
        _required(data, "ownership_details"),
        _required(data, "incorporation_date"),
        _required(data, "sector"),
        _required(data, "domain"),
        int(_required(data, "employee_count")),
        _required(data, "current_stage"),
        _required(data, "company_address"),
        _required(data, "company_email"),
        _required(data, "company_phone"),
        str(data.get("website", "")).strip() or None,
        _required(data, "pincode"),
        _encrypted(cipher, json.dumps(representative)),
        _encrypted(cipher, _required(data, "gstin")),
        _required(data, "gst_state"),
        str(data.get("gst_details", "")).strip() or None,
    )

    if MYSQL_CONFIG["user"].startswith("REPLACE_WITH") or MYSQL_CONFIG["password"].startswith("REPLACE_WITH"):
        raise DatabaseConfigurationError("Fill in MYSQL_CONFIG before saving registrations.")

    connection = mysql.connector.connect(**MYSQL_CONFIG)
    cursor = connection.cursor()
    try:
        cursor.execute(SCHEMA_SQL)
        cursor.execute("SELECT id FROM startup_registrations WHERE business_id_hash = %s", (_lookup_hash(business_id),))
        if cursor.fetchone():
            raise DuplicateBusinessIdError
        cursor.execute(
            """INSERT INTO startup_registrations (
                business_id_encrypted, business_id_hash, password_hash, business_name, business_type,
                cin_encrypted, ownership_details, incorporation_date, sector,
                domain, employee_count, current_stage, company_address,
                company_email, company_phone, website, pincode,
                representative_encrypted, gstin_encrypted, gst_state, gst_details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                values,
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def _open_connection():
    if MYSQL_CONFIG["user"].startswith("REPLACE_WITH") or MYSQL_CONFIG["password"].startswith("REPLACE_WITH"):
        raise DatabaseConfigurationError("Fill in MYSQL_CONFIG before using database authentication.")
    return mysql.connector.connect(**MYSQL_CONFIG)


def _prepare_auth_tables(connection, cursor, cipher: Fernet) -> None:
    cursor.execute(SCHEMA_SQL)
    cursor.execute(MINFO_SCHEMA_SQL)
    cursor.execute(CONTRACTS_SCHEMA_SQL)
    cursor.execute("SELECT id FROM minfo LIMIT 1")
    if cursor.fetchone() is None:
        cursor.execute(
            "INSERT INTO minfo (ministry_id_encrypted, auth_code_encrypted) VALUES (%s, %s)",
            (_encrypted(cipher, "admin"), _encrypted(cipher, "1234")),
        )
        connection.commit()


def authenticate_startup(business_id: str, gstin: str, password: str) -> bool:
    """Authenticate a startup using encrypted identifiers and a password hash."""
    cipher = _cipher()
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        _prepare_auth_tables(connection, cursor, cipher)
        cursor.execute(
            "SELECT business_id_encrypted, gstin_encrypted, password_hash FROM startup_registrations WHERE business_id_hash = %s",
            (_lookup_hash(business_id.strip()),),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row:
            return False
        stored_business_id = cipher.decrypt(row[0].encode()).decode()
        stored_gstin = cipher.decrypt(row[1].encode()).decode()
        return stored_business_id == business_id.strip() and stored_gstin == gstin.strip() and check_password_hash(row[2], password)
    finally:
        cursor.close()
        connection.close()


def authenticate_ministry(ministry_id: str, auth_code: str) -> bool:
    """Authenticate against the manually maintained encrypted minfo table."""
    cipher = _cipher()
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        _prepare_auth_tables(connection, cursor, cipher)
        cursor.execute("SELECT ministry_id_encrypted, auth_code_encrypted FROM minfo")
        for row in cast(list[tuple[Any, ...]], cursor.fetchall()):
            stored_id = cipher.decrypt(row[0].encode()).decode()
            stored_code = cipher.decrypt(row[1].encode()).decode()
            if stored_id == ministry_id.strip() and stored_code == auth_code:
                return True
        return False
    finally:
        cursor.close()
        connection.close()


def save_challenge_contract(challenge: Mapping[str, Any], created_by: str) -> None:
    """Persist the complete challenge definition in the contracts table."""
    challenge_id = str(challenge.get("challengeId", "")).strip()
    if not challenge_id:
        raise ValueError("Challenge ID is required before saving a contract.")
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(CONTRACTS_SCHEMA_SQL)
        cursor.execute(
            """INSERT INTO contracts (
                challenge_id, title, government_body, department, state,
                status, created_by, challenge_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                title = VALUES(title), government_body = VALUES(government_body),
                department = VALUES(department), state = VALUES(state),
                status = VALUES(status), created_by = VALUES(created_by),
                challenge_data = VALUES(challenge_data)""",
            (
                challenge_id,
                str(challenge.get("title", "Untitled challenge")) or "Untitled challenge",
                str(challenge.get("ministry", "")),
                str(challenge.get("department", "")),
                str(challenge.get("state", "")),
                str(challenge.get("status", "Draft")),
                str(created_by or "ministry-user"),
                json.dumps(dict(challenge), ensure_ascii=True),
            ),
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def save_contract_report(report: Mapping[str, Any]) -> None:
    """Persist a startup's periodic report for ministry review."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(CONTRACT_REPORTS_SCHEMA_SQL)
        cursor.execute(
            """INSERT INTO contract_reports (
                report_id, challenge_id, check_id, startup_id, status,
                report_data, review_data
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                status = VALUES(status),
                report_data = VALUES(report_data),
                review_data = VALUES(review_data),
                reviewed_at = CASE WHEN VALUES(review_data) IS NOT NULL THEN CURRENT_TIMESTAMP ELSE reviewed_at END""",
            (
                str(report.get("reportId", "")),
                str(report.get("challengeId", "")),
                str(report.get("checkId", "")),
                str(report.get("startupId", "")),
                str(report.get("status", "Submitted")),
                json.dumps(dict(report), ensure_ascii=True),
                json.dumps(report.get("review"), ensure_ascii=True) if report.get("review") else None,
            ),
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()


def _application_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    cipher = _cipher()
    application_data = row[4]
    try:
        application_data = json.loads(application_data)
    except (TypeError, json.JSONDecodeError):
        application_data = {}
    return {
        "application_id": row[0],
        "challenge_id": row[1],
        "business_id": cipher.decrypt(row[2].encode()).decode(),
        "status": row[3],
        "application_data": application_data,
        "submitted_at": row[5].isoformat() if row[5] else None,
        "updated_at": row[6].isoformat() if row[6] else None,
    }


def save_application(
    challenge_id: str,
    business_id: str,
    application_data: Mapping[str, Any],
    status: str,
) -> dict[str, Any]:
    """Create an application or update its draft for the authenticated startup."""
    if status not in {"draft", "submitted"}:
        raise ValueError("Application status must be draft or submitted.")
    cipher = _cipher()
    business_hash = _lookup_hash(business_id)
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_SCREENING_AUDIT_SCHEMA_SQL)
        cursor.execute(
            "SELECT application_id, status FROM applications WHERE challenge_id = %s AND business_id_hash = %s",
            (challenge_id, business_hash),
        )
        existing = cursor.fetchone()
        if existing:
            application_id, existing_status = existing
            if existing_status != "draft" and not (existing_status == "clarification_requested" and status == "submitted"):
                raise DuplicateApplicationError
            cursor.execute(
                """UPDATE applications SET application_data = %s, status = %s,
                   submitted_at = CASE WHEN %s = 'submitted' AND submitted_at IS NULL THEN CURRENT_TIMESTAMP ELSE submitted_at END,
                   updated_at = CURRENT_TIMESTAMP
                   WHERE application_id = %s AND business_id_hash = %s AND status = %s""",
                (json.dumps(dict(application_data), ensure_ascii=True), status, status, application_id, business_hash, existing_status),
            )
            if existing_status == "clarification_requested" and status == "submitted":
                _insert_screening_audit(
                    cursor,
                    application_id,
                    business_id,
                    "startup",
                    "clarification_response",
                    {"challenge_id": challenge_id},
                )
        else:
            application_id = f"APP-{uuid.uuid4()}"
            cursor.execute(
                """INSERT INTO applications (
                   application_id, challenge_id, business_id_encrypted, business_id_hash,
                   status, application_data, submitted_at
                   ) VALUES (%s, %s, %s, %s, %s, %s,
                   CASE WHEN %s = 'submitted' THEN CURRENT_TIMESTAMP ELSE NULL END)""",
                (
                    application_id,
                    challenge_id,
                    _encrypted(cipher, business_id),
                    business_hash,
                    status,
                    json.dumps(dict(application_data), ensure_ascii=True),
                    status,
                ),
            )
        connection.commit()
        cursor.execute(
            """SELECT application_id, challenge_id, business_id_encrypted, status,
                      application_data, submitted_at, updated_at
               FROM applications WHERE application_id = %s AND business_id_hash = %s""",
            (application_id, business_hash),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if row is None:
            raise RuntimeError("Saved application could not be loaded.")
        return _application_from_row(row)
    except IntegrityError as error:
        connection.rollback()
        if getattr(error, "errno", None) == 1062:
            raise DuplicateApplicationError from error
        raise
    finally:
        cursor.close()
        connection.close()


def get_application(application_id: str, business_id: str) -> dict[str, Any] | None:
    """Load an application only when it belongs to the supplied startup."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATIONS_SCHEMA_SQL)
        cursor.execute(
            """SELECT application_id, challenge_id, business_id_encrypted, status,
                      application_data, submitted_at, updated_at
               FROM applications WHERE application_id = %s AND business_id_hash = %s""",
            (application_id, _lookup_hash(business_id)),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        return _application_from_row(row) if row else None
    finally:
        cursor.close()
        connection.close()


def get_startup_application(challenge_id: str, business_id: str) -> dict[str, Any] | None:
    """Load the authenticated startup's application for one challenge."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATIONS_SCHEMA_SQL)
        cursor.execute(
            """SELECT application_id, challenge_id, business_id_encrypted, status,
                      application_data, submitted_at, updated_at
               FROM applications WHERE challenge_id = %s AND business_id_hash = %s""",
            (challenge_id, _lookup_hash(business_id)),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        return _application_from_row(row) if row else None
    finally:
        cursor.close()
        connection.close()


def list_startup_applications(business_id: str) -> list[dict[str, Any]]:
    """Return all applications belonging to one startup, including drafts."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATIONS_SCHEMA_SQL)
        cursor.execute(
            """SELECT application_id, challenge_id, business_id_encrypted, status,
                      application_data, submitted_at, updated_at
               FROM applications WHERE business_id_hash = %s ORDER BY updated_at DESC""",
            (_lookup_hash(business_id),),
        )
        return [_application_from_row(row) for row in cast(list[tuple[Any, ...]], cursor.fetchall())]
    finally:
        cursor.close()
        connection.close()


def count_challenge_applications(challenge_id: str) -> int:
    """Count non-draft applications for a challenge."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATIONS_SCHEMA_SQL)
        cursor.execute(
            "SELECT COUNT(*) FROM applications WHERE challenge_id = %s AND status <> 'draft'",
            (challenge_id,),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        return int(row[0]) if row else 0
    finally:
        cursor.close()
        connection.close()


def list_challenge_applications(challenge_id: str) -> list[dict[str, Any]]:
    """Return non-draft challenge applications with public startup identity."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATIONS_SCHEMA_SQL)
        cursor.execute(SCHEMA_SQL)
        cursor.execute(
            """SELECT a.application_id, a.challenge_id, a.business_id_encrypted,
                      a.status, a.application_data, a.submitted_at, a.updated_at,
                      r.business_name
               FROM applications a LEFT JOIN startup_registrations r
                 ON r.business_id_hash = a.business_id_hash
               WHERE a.challenge_id = %s AND a.status <> 'draft'
               ORDER BY a.submitted_at DESC""",
            (challenge_id,),
        )
        applications = []
        for row in cast(list[tuple[Any, ...]], cursor.fetchall()):
            application = _application_from_row(row[:7])
            application["startup_name"] = row[7] or application["business_id"]
            applications.append(application)
        return applications
    finally:
        cursor.close()
        connection.close()


def get_government_application(application_id: str) -> dict[str, Any] | None:
    """Load one submitted application for ministry-side, challenge-authorized access."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATIONS_SCHEMA_SQL)
        cursor.execute(SCHEMA_SQL)
        cursor.execute(
            """SELECT a.application_id, a.challenge_id, a.business_id_encrypted,
                      a.status, a.application_data, a.submitted_at, a.updated_at,
                      r.business_name
               FROM applications a LEFT JOIN startup_registrations r
                 ON r.business_id_hash = a.business_id_hash
               WHERE a.application_id = %s AND a.status <> 'draft'""",
            (application_id,),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row:
            return None
        application = _application_from_row(row[:7])
        application["startup_name"] = row[7] or application["business_id"]
        return application
    finally:
        cursor.close()
        connection.close()


def _insert_screening_audit(
    cursor: Any,
    application_id: str,
    reviewer_id: str,
    reviewer_role: str,
    event_type: str,
    details: Mapping[str, Any],
) -> None:
    cursor.execute(
        """INSERT INTO application_screening_audit (
               application_id, reviewer_id, reviewer_role, event_type, details
           ) VALUES (%s, %s, %s, %s, %s)""",
        (application_id, reviewer_id, reviewer_role, event_type, json.dumps(dict(details), ensure_ascii=True)),
    )


def start_application_screening(application_id: str, reviewer_id: str, reviewer_role: str) -> bool:
    """Record a ministry reviewer opening an application for eligibility screening."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_SCREENING_AUDIT_SCHEMA_SQL)
        cursor.execute("SELECT status FROM applications WHERE application_id = %s", (application_id,))
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row or row[0] == "draft":
            return False
        _insert_screening_audit(cursor, application_id, reviewer_id, reviewer_role, "screening_started", {})
        connection.commit()
        return True
    finally:
        cursor.close()
        connection.close()


def save_application_screening(
    application_id: str,
    reviewer_id: str,
    reviewer_role: str,
    requirements: list[Mapping[str, str]],
) -> None:
    """Append requirement-level decisions; prior screening records are never deleted."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_SCREENINGS_SCHEMA_SQL)
        cursor.execute("SELECT status FROM applications WHERE application_id = %s", (application_id,))
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row or row[0] not in {"submitted", "clarification_requested"}:
            raise ValueError("This application is not available for eligibility screening.")
        for item in requirements:
            cursor.execute(
                """INSERT INTO application_screenings (
                       application_id, reviewer_id, reviewer_role, requirement, decision, comment
                   ) VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    application_id,
                    reviewer_id,
                    reviewer_role,
                    item["requirement"],
                    item["decision"],
                    item["comment"],
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def get_application_screening(application_id: str, business_id: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """Return the latest requirement decisions and audit history, optionally owner-scoped."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_SCREENINGS_SCHEMA_SQL)
        cursor.execute(APPLICATION_SCREENING_AUDIT_SCHEMA_SQL)
        if business_id is not None:
            cursor.execute(
                """SELECT s.screening_id, s.reviewer_id, s.reviewer_role, s.requirement,
                          s.decision, s.comment, s.created_at
                   FROM application_screenings s JOIN applications a ON a.application_id = s.application_id
                   WHERE s.application_id = %s AND a.business_id_hash = %s
                   ORDER BY s.screening_id DESC""",
                (application_id, _lookup_hash(business_id)),
            )
        else:
            cursor.execute(
                """SELECT screening_id, reviewer_id, reviewer_role, requirement,
                          decision, comment, created_at
                   FROM application_screenings WHERE application_id = %s
                   ORDER BY screening_id DESC""",
                (application_id,),
            )
        latest_by_requirement: dict[str, dict[str, Any]] = {}
        for row in cast(list[tuple[Any, ...]], cursor.fetchall()):
            latest_by_requirement.setdefault(row[3], {
                "requirement": row[3],
                "decision": row[4],
                "comment": row[5],
                "reviewer_id": row[1],
                "reviewer_role": row[2],
                "created_at": row[6].isoformat() if row[6] else None,
            })
        if business_id is not None:
            cursor.execute(
                """SELECT e.event_type, e.reviewer_id, e.reviewer_role, e.details, e.created_at
                   FROM application_screening_audit e JOIN applications a ON a.application_id = e.application_id
                   WHERE e.application_id = %s AND a.business_id_hash = %s
                   ORDER BY e.audit_id""",
                (application_id, _lookup_hash(business_id)),
            )
        else:
            cursor.execute(
                """SELECT event_type, reviewer_id, reviewer_role, details, created_at FROM application_screening_audit
                   WHERE application_id = %s ORDER BY audit_id""",
                (application_id,),
            )
        audit = []
        for row in cast(list[tuple[Any, ...]], cursor.fetchall()):
            try:
                details = json.loads(row[3])
            except (TypeError, json.JSONDecodeError):
                details = {}
            audit.append({
                "event_type": row[0],
                "reviewer_id": row[1],
                "reviewer_role": row[2],
                "details": details,
                "created_at": row[4].isoformat() if row[4] else None,
            })
        return {"requirements": list(latest_by_requirement.values()), "audit": audit}
    finally:
        cursor.close()
        connection.close()


def finalize_application_screening(
    application_id: str,
    reviewer_id: str,
    reviewer_role: str,
    decision: str,
    details: Mapping[str, Any],
) -> bool:
    """Atomically move a submitted application to an eligibility outcome and audit it."""
    status_by_decision = {
        "eligible": ("eligible", "eligibility_approved"),
        "ineligible": ("ineligible", "eligibility_rejected"),
        "clarification_requested": ("clarification_requested", "clarification_requested"),
    }
    if decision not in status_by_decision:
        raise ValueError("Choose Eligible, Ineligible, or Request Clarification.")
    new_status, event_type = status_by_decision[decision]
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_SCREENING_AUDIT_SCHEMA_SQL)
        cursor.execute("SELECT status FROM applications WHERE application_id = %s FOR UPDATE", (application_id,))
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row or row[0] != "submitted":
            connection.rollback()
            return False
        cursor.execute(
            "UPDATE applications SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE application_id = %s AND status = 'submitted'",
            (new_status, application_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        _insert_screening_audit(cursor, application_id, reviewer_id, reviewer_role, event_type, details)
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def _decimal_value(value: Any, field_name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} must be a number.") from error
    if not result.is_finite():
        raise ValueError(f"{field_name} must be a finite number.")
    return result


def _evaluation_totals(rows: list[tuple[Any, ...]]) -> tuple[Decimal, Decimal]:
    total = Decimal("0")
    maximum_total = Decimal("0")
    for row in rows:
        maximum_score = _decimal_value(row[1], "Maximum score")
        weight = _decimal_value(row[2], "Criterion weight")
        maximum_total += weight
        if row[0] is not None:
            score = _decimal_value(row[0], "Score")
            total += score / maximum_score * weight
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), maximum_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _insert_evaluation_audit(
    cursor: Any,
    application_id: str,
    evaluation_id: str,
    reviewer_id: str,
    reviewer_role: str,
    event_type: str,
    details: Mapping[str, Any],
) -> None:
    cursor.execute(
        """INSERT INTO application_evaluation_audit (
               application_id, evaluation_id, reviewer_id, reviewer_role, event_type, details
           ) VALUES (%s, %s, %s, %s, %s, %s)""",
        (application_id, evaluation_id, reviewer_id, reviewer_role, event_type, json.dumps(dict(details), ensure_ascii=True)),
    )


def start_application_evaluation(
    application_id: str,
    reviewer_id: str,
    reviewer_role: str,
    criteria: list[Mapping[str, Any]],
) -> bool:
    """Create a scorecard and move an eligible application into evaluation."""
    if not criteria:
        raise ValueError("At least one evaluation criterion is required.")
    criterion_names = [str(item.get("criterion") or "").strip() for item in criteria]
    if any(not name for name in criterion_names) or len(set(criterion_names)) != len(criterion_names):
        raise ValueError("Evaluation criteria must have unique names.")
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_EVALUATIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_SCORES_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_AUDIT_SCHEMA_SQL)
        cursor.execute(APPLICATION_SCREENING_AUDIT_SCHEMA_SQL)
        cursor.execute("SELECT status FROM applications WHERE application_id = %s FOR UPDATE", (application_id,))
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row or row[0] != "eligible":
            connection.rollback()
            return False
        evaluation_id = f"EVAL-{uuid.uuid4()}"
        maximum_total = sum((_decimal_value(item["weight"], "Criterion weight") for item in criteria), Decimal("0"))
        cursor.execute(
            """INSERT INTO application_evaluations (
                   evaluation_id, application_id, reviewer_id, reviewer_role,
                   total_score, maximum_total_score, status
               ) VALUES (%s, %s, %s, %s, 0, %s, 'in_progress')""",
            (evaluation_id, application_id, reviewer_id, reviewer_role, maximum_total),
        )
        for item in criteria:
            cursor.execute(
                """INSERT INTO application_evaluation_scores (
                       evaluation_id, application_id, reviewer_id, reviewer_role,
                       criterion, description, score, maximum_score, weight, is_required, comment
                   ) VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, %s, %s, '')""",
                (
                    evaluation_id,
                    application_id,
                    reviewer_id,
                    reviewer_role,
                    str(item["criterion"]).strip(),
                    str(item.get("description") or ""),
                    _decimal_value(item["maximum_score"], "Maximum score"),
                    _decimal_value(item["weight"], "Criterion weight"),
                    1 if item.get("required", True) else 0,
                ),
            )
        cursor.execute(
            "UPDATE applications SET status = 'under_evaluation', updated_at = CURRENT_TIMESTAMP WHERE application_id = %s AND status = 'eligible'",
            (application_id,),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        _insert_screening_audit(cursor, application_id, reviewer_id, reviewer_role, "evaluation_started", {"evaluation_id": evaluation_id})
        _insert_evaluation_audit(cursor, application_id, evaluation_id, reviewer_id, reviewer_role, "evaluation_started", {})
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def get_application_evaluation(application_id: str) -> dict[str, Any] | None:
    """Load a ministry evaluation scorecard and its audit history."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_EVALUATIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_SCORES_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_AUDIT_SCHEMA_SQL)
        cursor.execute(
            """SELECT evaluation_id, application_id, reviewer_id, reviewer_role,
                      total_score, maximum_total_score, status, started_at, completed_at
               FROM application_evaluations WHERE application_id = %s""",
            (application_id,),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row:
            return None
        evaluation_id = row[0]
        cursor.execute(
            """SELECT criterion, description, score, maximum_score, weight, is_required,
                      comment, reviewer_id, reviewer_role, updated_at
               FROM application_evaluation_scores WHERE evaluation_id = %s ORDER BY score_id""",
            (evaluation_id,),
        )
        criteria = []
        for item in cast(list[tuple[Any, ...]], cursor.fetchall()):
            criteria.append({
                "criterion": item[0],
                "description": item[1],
                "score": float(item[2]) if item[2] is not None else None,
                "maximum_score": float(item[3]),
                "weight": float(item[4]),
                "required": bool(item[5]),
                "comment": item[6],
                "reviewer_id": item[7],
                "reviewer_role": item[8],
                "updated_at": item[9].isoformat() if item[9] else None,
            })
        cursor.execute(
            """SELECT reviewer_id, reviewer_role, event_type, details, created_at
               FROM application_evaluation_audit WHERE evaluation_id = %s ORDER BY audit_id""",
            (evaluation_id,),
        )
        history = []
        for item in cast(list[tuple[Any, ...]], cursor.fetchall()):
            try:
                details = json.loads(item[3])
            except (TypeError, json.JSONDecodeError):
                details = {}
            history.append({
                "reviewer_id": item[0],
                "reviewer_role": item[1],
                "event_type": item[2],
                "details": details,
                "created_at": item[4].isoformat() if item[4] else None,
            })
        return {
            "evaluation_id": row[0],
            "application_id": row[1],
            "reviewer_id": row[2],
            "reviewer_role": row[3],
            "total_score": float(row[4]),
            "maximum_total_score": float(row[5]),
            "status": row[6],
            "started_at": row[7].isoformat() if row[7] else None,
            "completed_at": row[8].isoformat() if row[8] else None,
            "criteria": criteria,
            "history": history,
        }
    finally:
        cursor.close()
        connection.close()


def save_application_evaluation(
    application_id: str,
    reviewer_id: str,
    reviewer_role: str,
    scores: list[Mapping[str, Any]],
) -> dict[str, float]:
    """Save criterion scores and recalculate the weighted total on the server."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_EVALUATIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_SCORES_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_AUDIT_SCHEMA_SQL)
        cursor.execute(
            """SELECT e.evaluation_id FROM application_evaluations e
               JOIN applications a ON a.application_id = e.application_id
               WHERE e.application_id = %s AND e.status = 'in_progress'
                 AND a.status = 'under_evaluation' FOR UPDATE""",
            (application_id,),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row:
            connection.rollback()
            raise ValueError("Only applications under evaluation can be edited.")
        evaluation_id = row[0]
        for item in scores:
            criterion = str(item.get("criterion") or "").strip()
            cursor.execute(
                "SELECT maximum_score FROM application_evaluation_scores WHERE evaluation_id = %s AND criterion = %s",
                (evaluation_id, criterion),
            )
            criterion_row = cast(tuple[Any, ...] | None, cursor.fetchone())
            if not criterion_row:
                raise ValueError("An evaluation criterion is invalid.")
            maximum_score = _decimal_value(criterion_row[0], "Maximum score")
            score = None if item.get("score") in (None, "") else _decimal_value(item["score"], "Score")
            if score is not None and (score < 0 or score > maximum_score):
                raise ValueError(f"Score for {criterion} must be between 0 and {maximum_score}.")
            comment = str(item.get("comment") or "").strip()
            if len(comment) > 4000:
                raise ValueError("An evaluation comment exceeds the 4,000 character limit.")
            cursor.execute(
                """UPDATE application_evaluation_scores
                   SET score = %s, comment = %s, reviewer_id = %s, reviewer_role = %s,
                       updated_at = CURRENT_TIMESTAMP
                   WHERE evaluation_id = %s AND criterion = %s""",
                (score, comment, reviewer_id, reviewer_role, evaluation_id, criterion),
            )
        cursor.execute(
            """SELECT score, maximum_score, weight FROM application_evaluation_scores
               WHERE evaluation_id = %s""",
            (evaluation_id,),
        )
        total, maximum_total = _evaluation_totals(cast(list[tuple[Any, ...]], cursor.fetchall()))
        cursor.execute(
            """UPDATE application_evaluations SET total_score = %s, maximum_total_score = %s,
                   reviewer_id = %s, reviewer_role = %s, updated_at = CURRENT_TIMESTAMP
               WHERE evaluation_id = %s AND status = 'in_progress'""",
            (total, maximum_total, reviewer_id, reviewer_role, evaluation_id),
        )
        _insert_evaluation_audit(
            cursor,
            application_id,
            evaluation_id,
            reviewer_id,
            reviewer_role,
            "evaluation_saved",
            {"total_score": str(total), "maximum_total_score": str(maximum_total)},
        )
        connection.commit()
        return {"total_score": float(total), "maximum_total_score": float(maximum_total)}
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def complete_application_evaluation(application_id: str, reviewer_id: str, reviewer_role: str) -> dict[str, float]:
    """Complete evaluation only after every required criterion has a score."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_EVALUATIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_SCORES_SCHEMA_SQL)
        cursor.execute(APPLICATION_EVALUATION_AUDIT_SCHEMA_SQL)
        cursor.execute(
            """SELECT e.evaluation_id FROM application_evaluations e
               JOIN applications a ON a.application_id = e.application_id
               WHERE e.application_id = %s AND e.status = 'in_progress'
                 AND a.status = 'under_evaluation' FOR UPDATE""",
            (application_id,),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row:
            connection.rollback()
            raise ValueError("Only applications under evaluation can be completed.")
        evaluation_id = row[0]
        cursor.execute(
            """SELECT criterion, score, maximum_score, weight, is_required
               FROM application_evaluation_scores WHERE evaluation_id = %s""",
            (evaluation_id,),
        )
        scores = cast(list[tuple[Any, ...]], cursor.fetchall())
        if not scores:
            raise ValueError("This evaluation has no criteria.")
        missing = [item[0] for item in scores if bool(item[4]) and item[1] is None]
        if missing:
            raise ValueError("Complete every required criterion before completing evaluation.")
        total, maximum_total = _evaluation_totals([(item[1], item[2], item[3]) for item in scores])
        cursor.execute(
            """UPDATE application_evaluations SET status = 'evaluation_complete',
                   total_score = %s, maximum_total_score = %s, reviewer_id = %s,
                   reviewer_role = %s, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
               WHERE evaluation_id = %s AND status = 'in_progress'""",
            (total, maximum_total, reviewer_id, reviewer_role, evaluation_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("Evaluation status changed; reload before completing.")
        cursor.execute(
            "UPDATE applications SET status = 'evaluation_complete', updated_at = CURRENT_TIMESTAMP WHERE application_id = %s AND status = 'under_evaluation'",
            (application_id,),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            raise ValueError("Application status changed; reload before completing.")
        details = {"total_score": str(total), "maximum_total_score": str(maximum_total)}
        _insert_evaluation_audit(cursor, application_id, evaluation_id, reviewer_id, reviewer_role, "evaluation_completed", details)
        _insert_screening_audit(cursor, application_id, reviewer_id, reviewer_role, "evaluation_completed", details)
        connection.commit()
        return {"total_score": float(total), "maximum_total_score": float(maximum_total)}
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def list_challenge_evaluation_comparison(challenge_id: str) -> list[dict[str, Any]]:
    """Return completed challenge evaluations for ministry comparison and decision."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_EVALUATIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_SHORTLIST_DECISIONS_SCHEMA_SQL)
        cursor.execute(SCHEMA_SQL)
        cursor.execute(
            """SELECT a.application_id, a.challenge_id, a.business_id_encrypted,
                      a.status, a.application_data, a.submitted_at, a.updated_at,
                      r.business_name, e.total_score, e.maximum_total_score,
                      e.completed_at, d.decision, d.decision_maker, d.decision_role,
                      d.comments, d.created_at
               FROM applications a
               JOIN application_evaluations e ON e.application_id = a.application_id
               LEFT JOIN startup_registrations r ON r.business_id_hash = a.business_id_hash
               LEFT JOIN application_shortlist_decisions d ON d.application_id = a.application_id
               WHERE a.challenge_id = %s
                 AND a.status IN ('evaluation_complete', 'shortlisted', 'not_selected')
                 AND e.status = 'evaluation_complete'
                             ORDER BY e.completed_at ASC, a.submitted_at ASC""",
            (challenge_id,),
        )
        results = []
        for row in cast(list[tuple[Any, ...]], cursor.fetchall()):
            try:
                application_data = json.loads(row[4])
            except (TypeError, json.JSONDecodeError):
                application_data = {}
            results.append({
                "application_id": row[0],
                "challenge_id": row[1],
                "business_id": _cipher().decrypt(row[2].encode()).decode(),
                "status": row[3],
                "application_data": application_data,
                "submitted_at": row[5].isoformat() if row[5] else None,
                "updated_at": row[6].isoformat() if row[6] else None,
                "startup_name": row[7] or "Startup",
                "total_score": float(row[8]),
                "maximum_total_score": float(row[9]),
                "evaluation_completed_at": row[10].isoformat() if row[10] else None,
                "selection_status": row[11] or "Pending Decision",
                "decision_maker": row[12],
                "decision_role": row[13],
                "decision_comments": row[14] or "",
                "decision_at": row[15].isoformat() if row[15] else None,
            })
        return results
    finally:
        cursor.close()
        connection.close()


def record_application_shortlist_decision(
    application_id: str,
    decision: str,
    decision_maker: str,
    decision_role: str,
    comments: str,
) -> bool:
    """Atomically record an explicit shortlist decision for a completed evaluation."""
    if decision not in {"shortlisted", "not_selected"}:
        raise ValueError("Decision must be shortlisted or not_selected.")
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_EVALUATIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_SHORTLIST_DECISIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_SHORTLIST_AUDIT_SCHEMA_SQL)
        cursor.execute(
            """SELECT a.status, e.status FROM applications a
               JOIN application_evaluations e ON e.application_id = a.application_id
               WHERE a.application_id = %s FOR UPDATE""",
            (application_id,),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row or row[0] != "evaluation_complete" or row[1] != "evaluation_complete":
            connection.rollback()
            return False
        decision_id = f"SHORT-{uuid.uuid4()}"
        cursor.execute(
            """INSERT INTO application_shortlist_decisions (
                   decision_id, application_id, decision, decision_maker, decision_role, comments
               ) VALUES (%s, %s, %s, %s, %s, %s)""",
            (decision_id, application_id, decision, decision_maker, decision_role, comments),
        )
        cursor.execute(
            "UPDATE applications SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE application_id = %s AND status = 'evaluation_complete'",
            (decision, application_id),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return False
        details = {"decision": decision, "comments": comments}
        cursor.execute(
            """INSERT INTO application_shortlist_audit (
                   application_id, decision_id, decision_maker, decision_role, event_type, details
               ) VALUES (%s, %s, %s, %s, %s, %s)""",
            (
                application_id,
                decision_id,
                decision_maker,
                decision_role,
                "application_shortlisted" if decision == "shortlisted" else "application_not_selected",
                json.dumps(details, ensure_ascii=True),
            ),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


def get_application_shortlist_history(application_id: str) -> dict[str, Any]:
    """Load the persistent shortlist decision and append-only audit events."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_SHORTLIST_DECISIONS_SCHEMA_SQL)
        cursor.execute(APPLICATION_SHORTLIST_AUDIT_SCHEMA_SQL)
        cursor.execute(
            """SELECT decision, decision_maker, decision_role, comments, created_at
               FROM application_shortlist_decisions WHERE application_id = %s""",
            (application_id,),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        decision = None if not row else {
            "decision": row[0],
            "decision_maker": row[1],
            "decision_role": row[2],
            "comments": row[3],
            "created_at": row[4].isoformat() if row[4] else None,
        }
        cursor.execute(
            """SELECT decision_maker, decision_role, event_type, details, created_at
               FROM application_shortlist_audit WHERE application_id = %s ORDER BY audit_id""",
            (application_id,),
        )
        history = []
        for item in cast(list[tuple[Any, ...]], cursor.fetchall()):
            try:
                details = json.loads(item[3])
            except (TypeError, json.JSONDecodeError):
                details = {}
            history.append({
                "decision_maker": item[0],
                "decision_role": item[1],
                "event_type": item[2],
                "details": details,
                "created_at": item[4].isoformat() if item[4] else None,
            })
        return {"decision": decision, "history": history}
    finally:
        cursor.close()
        connection.close()


def get_startup_clarification_request(application_id: str, business_id: str) -> list[dict[str, Any]]:
    """Load reviewer clarification comments only for the startup that owns the application."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(APPLICATION_SCREENINGS_SCHEMA_SQL)
        cursor.execute(
            """SELECT s.requirement, s.comment, s.created_at
               FROM application_screenings s JOIN applications a ON a.application_id = s.application_id
               WHERE s.application_id = %s AND a.business_id_hash = %s
                 AND a.status = 'clarification_requested' AND s.decision = 'needs_clarification'
               ORDER BY s.screening_id DESC""",
            (application_id, _lookup_hash(business_id)),
        )
        seen = set()
        clarifications = []
        for row in cast(list[tuple[Any, ...]], cursor.fetchall()):
            if row[0] not in seen:
                seen.add(row[0])
                clarifications.append({"requirement": row[0], "comment": row[1], "created_at": row[2].isoformat() if row[2] else None})
        return clarifications
    finally:
        cursor.close()
        connection.close()


def get_startup_profile(business_id: str) -> dict[str, Any] | None:
    """Fetch the non-sensitive company profile for the authenticated startup."""
    cipher = _cipher()
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(
            """SELECT business_id_encrypted, business_name, business_type,
                      ownership_details, incorporation_date, sector, domain,
                      employee_count, current_stage, company_address,
                      company_email, company_phone, website, pincode, gst_state
               FROM startup_registrations WHERE business_id_hash = %s""",
            (_lookup_hash(business_id.strip()),),
        )
        row = cast(tuple[Any, ...] | None, cursor.fetchone())
        if not row:
            return None
        return {
            "business_id": cipher.decrypt(row[0].encode()).decode(),
            "business_name": row[1],
            "business_type": row[2],
            "ownership_details": row[3],
            "incorporation_date": str(row[4]),
            "sector": row[5],
            "domain": row[6],
            "employee_count": row[7],
            "current_stage": row[8],
            "company_address": row[9],
            "company_email": row[10],
            "company_phone": row[11],
            "website": row[12],
            "pincode": row[13],
            "gst_state": row[14],
        }
    finally:
        cursor.close()
        connection.close()


def list_startup_directory() -> list[dict[str, Any]]:
    """Load public startup profile fields for the directory."""
    connection = _open_connection()
    cursor = connection.cursor()
    try:
        cursor.execute(SCHEMA_SQL)
        cursor.execute(
            """SELECT business_name, business_type, ownership_details,
                      incorporation_date, sector, domain, employee_count,
                      current_stage, company_address, company_email,
                      company_phone, pincode, website, gst_state
               FROM startup_registrations ORDER BY created_at DESC"""
        )
        directory = []
        for row in cast(list[tuple[Any, ...]], cursor.fetchall()):
            address = str(row[8] or "").strip()
            city = address.split(",")[0].strip() if address else "Maharashtra"
            directory.append({
                "business_name": row[0],
                "business_type": row[1],
                "ownership_details": row[2],
                "incorporation_date": str(row[3]),
                "sector": row[4],
                "domain": row[5],
                "employee_count": row[6],
                "current_stage": row[7],
                "city": city,
                "company_address": row[8],
                "company_email": row[9],
                "company_phone": row[10],
                "pincode": row[11],
                "website": row[12],
                "gst_state": row[13],
            })
        return directory
    finally:
        cursor.close()
        connection.close()
