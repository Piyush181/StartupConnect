"""Persistence helpers for Startup Connect registration data.

Fill in MYSQL_CONFIG before connecting this application to MySQL. Keep the
encryption key outside source control and use the same key for future reads.
"""

import json
import os
from typing import Mapping

import mysql.connector
from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash


# Replace these values manually, or set the matching environment variables.
MYSQL_CONFIG = {
    "host": os.getenv("STARTUP_CONNECT_DB_HOST", "localhost"),
    "port": int(os.getenv("STARTUP_CONNECT_DB_PORT", "3306")),
    "user": os.getenv("STARTUP_CONNECT_DB_USER", "root"),
    "password": os.getenv("STARTUP_CONNECT_DB_PASSWORD", "apIEHewSeq8"),
    "database": "startupconnect",
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
    business_id VARCHAR(80) NOT NULL UNIQUE,
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
        business_id,
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
        cursor.execute("SELECT id FROM startup_registrations WHERE business_id = %s", (business_id,))
        if cursor.fetchone():
            raise DuplicateBusinessIdError
        cursor.execute(
            """INSERT INTO startup_registrations (
                business_id, password_hash, business_name, business_type,
                cin_encrypted, ownership_details, incorporation_date, sector,
                domain, employee_count, current_stage, company_address,
                company_email, company_phone, website, pincode,
                representative_encrypted, gstin_encrypted, gst_state, gst_details
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            values,
        )
        connection.commit()
    finally:
        cursor.close()
        connection.close()