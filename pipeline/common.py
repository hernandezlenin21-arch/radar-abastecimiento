"""Utilidades compartidas: configuración, HTTP con reintentos, fechas."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
STORE_DIR = Path(os.environ.get("STORE_DIR", ROOT / "data" / "store"))
SITE_DATA_DIR = Path(os.environ.get("SITE_DATA_DIR", ROOT / "site" / "data"))
TZ = ZoneInfo("America/Managua")
USER_AGENT = "IntelMercados/1.0 (supply-chain dashboard; contacto en README)"


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local_iso() -> str:
    return now_utc().astimezone(TZ).isoformat(timespec="seconds")


class SourceError(Exception):
    """Error controlado de una fuente. Nunca se sustituye por datos inventados."""


class MissingCredential(SourceError):
    pass


@dataclass
class Observation:
    date: str            # ISO AAAA-MM-DD (fecha efectiva del dato)
    value: float         # valor en unidad ORIGINAL


@dataclass
class FetchResult:
    observations: list[Observation]
    source_url: str                      # URL pública verificable
    unit: str | None = None              # unidad reportada por la fuente (si la publica)
    published: str | None = None         # fecha de publicación/actualización de la fuente
    notes: list[str] = field(default_factory=list)


_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def http_get(url: str, *, params=None, auth=None, timeout=30, retries=3, backoff=4.0) -> requests.Response:
    """GET con reintentos exponenciales para 429/5xx y errores de red."""
    last: Exception | None = None
    for attempt in range(retries):
        try:
            resp = _session.get(url, params=params, auth=auth, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504):
                last = SourceError(f"HTTP {resp.status_code} en {url}")
                time.sleep(backoff * (2 ** attempt))
                continue
            if resp.status_code >= 400:
                raise SourceError(f"HTTP {resp.status_code} en {url}: {resp.text[:200]}")
            return resp
        except requests.RequestException as exc:  # red, timeout, TLS
            last = exc
            time.sleep(backoff * (2 ** attempt))
    raise SourceError(f"Sin respuesta tras {retries} intentos: {last}")


def env_key(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise MissingCredential(f"Falta la variable de entorno {name}")
    return val
