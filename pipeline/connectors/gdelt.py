"""GDELT DOC 2.0 API — titulares de noticias globales (abierto, sin clave).

Se almacenan solo título, medio, fecha y enlace (no el texto de los artículos).
GDELT pide como máximo 1 consulta cada 5 segundos.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from ..common import SourceError, http_get

API = "https://api.gdeltproject.org/api/v2/doc/doc"


def parse_seendate(s: str) -> str | None:
    try:
        return datetime.strptime(s, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def fetch_query(query: str, timespan: str, maxrecords: int) -> list[dict]:
    resp = http_get(API, params={
        "query": f"{query} sourcelang:english", "mode": "ArtList", "format": "json",
        "maxrecords": maxrecords, "timespan": timespan, "sort": "DateDesc",
    }, timeout=45, backoff=6)
    try:
        js = resp.json()
    except ValueError:
        # GDELT responde texto plano cuando la consulta es inválida
        raise SourceError(f"GDELT: {resp.text[:160]}")
    out = []
    for a in js.get("articles", []):
        out.append({
            "title": (a.get("title") or "").strip(),
            "url": a.get("url"),
            "domain": a.get("domain"),
            "country": a.get("sourcecountry"),
            "published": parse_seendate(a.get("seendate")),
        })
    return out


def fetch_all(queries: dict[str, str], timespan: str, maxrecords: int, pause: float = 6.0):
    results, errors = {}, {}
    for i, (cat, q) in enumerate(queries.items()):
        if i:
            time.sleep(pause)
        try:
            results[cat] = fetch_query(q, timespan, maxrecords)
        except SourceError as exc:
            errors[cat] = str(exc)
    return results, errors
