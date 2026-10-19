"""Almacén de historial en JSON (uno por serie) con registro de procedencia.

- Upsert por fecha: elimina duplicados y registra revisiones de la fuente.
- Si una consulta falla, la serie conserva el último dato válido.
"""
from __future__ import annotations

import json
from pathlib import Path

from .common import STORE_DIR, now_local_iso

SERIES_DIR = lambda: STORE_DIR / "series"  # noqa: E731
MAX_LOG = 60


def _path(sid: str) -> Path:
    return SERIES_DIR() / f"{sid}.json"


def load(sid: str) -> dict:
    p = _path(sid)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"id": sid, "observations": [], "fetch_log": [], "revisions": []}


def save(rec: dict) -> None:
    SERIES_DIR().mkdir(parents=True, exist_ok=True)
    _path(rec["id"]).write_text(json.dumps(rec, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def upsert(rec: dict, observations, *, source_url: str, published: str | None) -> dict:
    """Mezcla observaciones nuevas. Devuelve estadísticas del cambio."""
    now = now_local_iso()
    existing = {o["date"]: o for o in rec["observations"]}
    added = revised = 0
    seen_in_batch: set[str] = set()
    duplicates = 0
    for ob in observations:
        if ob.date in seen_in_batch:
            duplicates += 1
            continue
        seen_in_batch.add(ob.date)
        old = existing.get(ob.date)
        if old is None:
            existing[ob.date] = {"date": ob.date, "value": ob.value, "retrieved": now}
            added += 1
        elif abs(old["value"] - ob.value) > 1e-9:
            rec.setdefault("revisions", []).append(
                {"date": ob.date, "old": old["value"], "new": ob.value, "at": now})
            rec["revisions"] = rec["revisions"][-MAX_LOG:]
            old.update(value=ob.value, retrieved=now)
            revised += 1
    rec["observations"] = sorted(existing.values(), key=lambda o: o["date"])
    entry = {"at": now, "ok": True, "url": source_url, "published": published,
             "received": len(observations), "added": added, "revised": revised,
             "duplicates_in_batch": duplicates}
    rec["fetch_log"] = (rec.get("fetch_log", []) + [entry])[-MAX_LOG:]
    rec["last_success"] = now
    return entry


def log_failure(rec: dict, error: str) -> None:
    entry = {"at": now_local_iso(), "ok": False, "error": error[:300]}
    rec["fetch_log"] = (rec.get("fetch_log", []) + [entry])[-MAX_LOG:]
    rec["last_error"] = entry


def load_json(name: str, default):
    p = STORE_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save_json(name: str, data) -> None:
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    (STORE_DIR / name).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
