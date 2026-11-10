"""Configuracion central y salvaguardas de rutas.

Regla dura: la base productiva historica (`data/promotions.sqlite3`) es de
solo lectura para este paquete. Solo se escribe en la base de ensayo
(`data/promotions_v4.sqlite3`) o en la ruta que indique ACH_DB / --db.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports" / "v4"
MIGRATIONS_DIR = BASE_DIR / "migrations"
FIXTURES_DIR = BASE_DIR / "tests" / "fixtures"

DEFAULT_DB = DATA_DIR / "promotions_v4.sqlite3"

# Bases que este paquete NUNCA debe abrir en modo escritura.
PROTECTED_DB_NAMES = {"promotions.sqlite3", "hunter.db", "promotions.sqlite3.bak"}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36 "
    "AI-Credits-Hunter/4.0 (+contacto: uso personal, solo lectura publica)"
)

HTTP_TIMEOUT_SEC = float(os.environ.get("ACH_TIMEOUT", "20"))
HTTP_RETRIES = int(os.environ.get("ACH_RETRIES", "2"))
HTTP_DELAY_SEC = float(os.environ.get("ACH_DELAY", "1.0"))
HTTP_MAX_BYTES = int(os.environ.get("ACH_MAX_BYTES", "4000000"))
HOST_MIN_INTERVAL_SEC = float(os.environ.get("ACH_HOST_INTERVAL", "1.5"))

ARGENTINA_TZ = "America/Argentina/Buenos_Aires"


def resolve_db(path: str | os.PathLike | None = None) -> Path:
    """Devuelve la ruta de base a usar, rechazando la base productiva."""
    if path:
        p = Path(path).expanduser().resolve()
    elif os.environ.get("ACH_DB"):
        p = Path(os.environ["ACH_DB"]).expanduser().resolve()
    else:
        p = DEFAULT_DB
    if p.name in PROTECTED_DB_NAMES:
        raise SystemExit(
            f"RECHAZADO: '{p}' es una base productiva/historica. "
            "Este paquete solo escribe en bases de ensayo (promotions_v4.sqlite3)."
        )
    return p


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
