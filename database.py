"""Persistence helpers for Startup Connect registration data.

Fill in MYSQL_CONFIG before connecting this application to MySQL. Keep the
encryption key outside source control and use the same key for future reads.
"""

import json
import os
import uuid
from typing import Any, Mapping, cast

import mysql.connector
from cryptography.fernet import Fernet
from mysql.connector.errors import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash


# Replace these values manually, or set the matching environment variables.
MYSQL_CONFIG = {
    "host": os.getenv("STARTUP_CONNECT_DB_HOST", "localhost"),
    "user": os.getenv("STARTUP_CONNECT_DB_USER", "root"),
    "password": os.getenv("STARTUP_CONNECT_DB_PASSWORD", "apIEHewSeq8"),
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
