"""USDA AMS MyMarketNews (MARS API). Clave gratuita al registrarse en https://mymarketnews.ams.usda.gov

Autenticación: HTTP Basic, usuario = API key, contraseña vacía.
Los reportes tienen estructuras distintas; este conector busca de forma
tolerante los campos de fecha y precio. Si no encuentra precio, falla de forma
controlada en lugar de suponer un valor.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import mean

from ..common import FetchResult, Observation, SourceError, env_key, http_get

API = "https://marsapi.ams.usda.gov/services/v1.2/reports"
PRICE_KEYS_AVG = ("avg_price", "price_avg", "weighted_average", "wtd_avg", "avg")
PRICE_KEYS_MIN = ("price_min", "low_price", "min_price", "price_low")
PRICE_KEYS_MAX = ("price_max", "high_price", "max_price", "price_high")


def _date(v: str) -> str | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(str(v).strip()[:19], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return None


def _num(row: dict, keys) -> float | None:
    for k in keys:
        for rk, rv in row.items():
            if rk.lower() == k:
                try:
                    return float(str(rv).replace(",", ""))
                except (TypeError, ValueError):
                    pass
    return None


def parse_results(results: list[dict], commodity_filter: str | None = None) -> list[Observation]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in results:
        if commodity_filter and commodity_filter.lower() not in str(row.get("commodity", "")).lower():
            continue
        d = _date(row.get("report_date") or row.get("report_end_date") or row.get("published_date") or "")
        if not d:
            continue
        price = _num(row, PRICE_KEYS_AVG)
        if price is None:
            lo, hi = _num(row, PRICE_KEYS_MIN), _num(row, PRICE_KEYS_MAX)
            if lo is not None and hi is not None:
                price = (lo + hi) / 2           # punto medio del rango publicado
        if price is not None and price > 0:
            by_date[d].append(price)
    # Promedio simple de las localidades reportadas el mismo día (documentado)
    return [Observation(d, round(mean(v), 2)) for d, v in sorted(by_date.items())]


def fetch(slug: str, start: str) -> FetchResult:
    if not slug.isdigit():
        raise SourceError("Número de reporte AMS sin validar; active el indicador cuando se confirme")
    key = env_key("AMS_API_KEY")
    # La API limita el rango; se consulta el último año.
    begin = max(datetime.strptime(start, "%Y-%m-%d"), datetime.utcnow() - timedelta(days=365))
    q = f"report_begin_date={begin:%m/%d/%Y}:{datetime.utcnow():%m/%d/%Y}"
    js = http_get(f"{API}/{slug}", params={"q": q, "allSections": "true"}, auth=(key, ""), timeout=60).json()
    results = js.get("results") if isinstance(js, dict) else None
    if results is None and isinstance(js, list):   # allSections devuelve lista de secciones
        results = [r for sec in js for r in (sec.get("results") or [])]
    if not results:
        raise SourceError(f"AMS reporte {slug}: sin resultados en el periodo")
    obs = parse_results(results)
    if not obs:
        raise SourceError(f"AMS reporte {slug}: no se identificaron campos de precio")
    return FetchResult(obs, source_url=f"https://mymarketnews.ams.usda.gov/viewReport/{slug}",
                       notes=["Precio = promedio simple de localidades; si la fuente da rango, punto medio."])
