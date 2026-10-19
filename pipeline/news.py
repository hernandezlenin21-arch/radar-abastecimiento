"""Procesamiento de noticias: deduplicación, clasificación y relevancia."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

TRACKED_TERMS = {
    "maíz": ["corn", "maize"], "soya": ["soybean", "soy "], "harina de soya": ["soybean meal", "soymeal"],
    "DDGS": ["ddgs", "distillers"], "trigo": ["wheat"], "aceite de soya": ["soybean oil", "soyoil"],
    "aceite de palma": ["palm oil"], "petróleo": ["crude", "brent", "wti", "oil price", "opec"],
    "diésel": ["diesel"], "gas natural": ["natural gas", "lng"], "oro": ["gold"], "plata": ["silver"],
    "ganado/carne": ["cattle", "beef"], "fletes": ["freight", "shipping rates", "container"],
    "Centroamérica": ["central america", "nicaragua", "honduras", "guatemala", "costa rica", "el salvador"],
}
CATEGORY_LABELS = {
    "commodities_agricolas": "Commodities agrícolas", "energia": "Energía", "comercio_internacional": "Comercio internacional",
    "geopolitica": "Geopolítica", "transporte_maritimo": "Transporte marítimo", "riesgos_climaticos": "Riesgos climáticos",
    "produccion_agroindustrial": "Producción agroindustrial", "economia_mundial": "Economía mundial",
}


def _norm_title(t: str) -> set[str]:
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", t.lower()).split() if len(w) > 3}


def _similar(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= 0.6


def matches(title: str) -> list[str]:
    tl = f" {title.lower()} "
    return [k for k, kws in TRACKED_TERMS.items() if any(kw in tl for kw in kws)]


def process(raw: dict[str, list[dict]], chokepoints: list[dict], max_age_hours: int = 96, per_cat: int = 15) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
    seen_urls, seen_titles, out = set(), [], []
    for cat, items in raw.items():
        kept = 0
        for a in items:
            if not a.get("title") or not a.get("url") or a["url"] in seen_urls:
                continue
            pub = a.get("published")
            if not pub or datetime.fromisoformat(pub) < cutoff:
                continue                      # no presentar noticias antiguas como nuevas
            nt = _norm_title(a["title"])
            if any(_similar(nt, s) for s in seen_titles):
                continue
            seen_urls.add(a["url"])
            seen_titles.append(nt)
            terms = matches(a["title"])
            cps = [c["name"] for c in chokepoints if any(k in a["title"].lower() for k in c["keywords"])]
            score = len(terms) * 2 + len(cps) * 3 + (3 if "Centroamérica" in terms else 0)
            out.append({**a, "category": cat, "category_label": CATEGORY_LABELS.get(cat, cat),
                        "mentions": terms, "chokepoints": cps, "relevance": score,
                        "why": _why(terms, cps)})
            kept += 1
            if kept >= per_cat:
                break
    return sorted(out, key=lambda x: (x["relevance"], x["published"]), reverse=True)


def _why(terms, cps) -> str:
    parts = []
    if terms:
        parts.append("Menciona: " + ", ".join(terms))
    if cps:
        parts.append("Punto crítico: " + ", ".join(cps))
    return ". ".join(parts) or "Contexto general de mercado"
