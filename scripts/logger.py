"""
scripts/logger.py

Centralised logging using loguru.

Log structure (mirrors IN/ archive):
    logs/YYYY/mmmYYYY/DDMMYYYY/tech_syslog.log
    logs/YYYY/mmmYYYY/DDMMYYYY/software_log.log
    logs/YYYY/mmmYYYY/DDMMYYYY/audit_log.log

All files append daily — new folder when date changes.

Usage:
    from logger import tech, log, audit

    tech.info("DB connected")
    log.info("Fetched 342 rows")
    log.warning("Skipping invalid coordinate")
    log.error("DB insert failed")

    audit("engineer@tlt.ee", "Data Engineer", "CLICK_SYNC", button="sync_gps")
"""

import os
import sys
from pathlib import Path
from loguru import logger

# ── Log base ──────────────────────────────────────────────────
LOG_BASE = Path(os.getenv("LOG_DIR", "logs"))

# Daily folder pattern — mirrors IN/ structure
# Example: logs/2026/may2026/27052026/
FOLDER = str(LOG_BASE / "{time:YYYY}" / "{time:MMMYYYY}" / "{time:DDMMYYYY}")

# ── Remove default loguru handler ─────────────────────────────
logger.remove()

# ── software_log — all application events ────────────────────
logger.add(
    FOLDER + "/software_log.log",
    level="DEBUG",
    rotation="00:00",           # new file at midnight (new folder)
    retention="90 days",
    encoding="utf-8",
    enqueue=True,               # thread-safe
    backtrace=True,
    diagnose=True,
    format="{time:YYYY-MM-DD HH:mm:ss} {level:<5} [{name}] {message};",
    filter=lambda r: not r["extra"].get("tech") and not r["extra"].get("audit")
)

# ── tech_syslog — infrastructure events only ─────────────────
logger.add(
    FOLDER + "/tech_syslog.log",
    level="DEBUG",
    rotation="00:00",
    retention="90 days",
    encoding="utf-8",
    enqueue=True,
    format="{time:YYYY-MM-DD HH:mm:ss} {level:<5} [{extra[component]}] {message}",
    filter=lambda r: r["extra"].get("tech", False)
)

# ── audit_log — user actions only ────────────────────────────
logger.add(
    FOLDER + "/audit_log.log",
    level="INFO",
    rotation="00:00",
    retention="365 days",       # keep audit logs for 1 year
    encoding="utf-8",
    enqueue=True,
    format="{time:YYYY-MM-DD HH:mm:ss} AUDIT {message}",
    filter=lambda r: r["extra"].get("audit", False)
)

# ── stdout — INFO and above ───────────────────────────────────
logger.add(
    sys.stdout,
    level="INFO",
    colorize=True,
    format="<green>{time:HH:mm:ss}</green> <level>{level:<5}</level> <cyan>[{name}]</cyan> {message}",
    filter=lambda r: not r["extra"].get("audit")
)

# ── Public loggers ────────────────────────────────────────────

# Application logger — use in all scripts
log = logger.bind()

# Tech logger — use for infra events
tech = logger.bind(tech=True, component="SYSTEM")

# ── Helpers ───────────────────────────────────────────────────
def get_tech_log(component: str):
    """Get tech logger bound to a specific component."""
    return logger.bind(tech=True, component=component)


def audit(user: str, role: str, action: str, **kwargs) -> None:
    """
    Log a user action to audit log.

    Example:
        audit("engineer@tlt.ee", "Data Engineer", "CLICK_SYNC", button="sync_gps")

    Output:
        2026-05-27 14:23:11 AUDIT [user=engineer@tlt.ee] [role=Data Engineer] [action=CLICK_SYNC] [button=sync_gps]
    """
    parts  = [f"user={user}", f"role={role}", f"action={action}"]
    parts += [f"{k}={v}" for k, v in kwargs.items()]
    message = " ".join(f"[{p}]" for p in parts)
    logger.bind(audit=True).info(message)


def log_startup(component: str, **info) -> None:
    """Log service startup to tech log."""
    t = get_tech_log(component)
    t.info(f"Starting")
    for k, v in info.items():
        t.info(f"{k}={v}")


def log_db_connected(host: str, dbname: str, user: str) -> None:
    """Log successful DB connection."""
    get_tech_log("DB").info(f"Connected host={host} db={dbname} user={user}")


def log_http(component: str, url: str, status: int, ms: float) -> None:
    """Log HTTP request result."""
    t = get_tech_log(component)
    if status == 200:
        t.info(f"HTTP {status} {url} ({ms:.0f}ms)")
    else:
        t.warning(f"HTTP {status} {url} ({ms:.0f}ms)")