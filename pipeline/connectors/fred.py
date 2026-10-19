"""FRED (Federal Reserve Bank of St. Louis). Clave gratuita: https://fredaccount.stlouisfed.org/apikeys"""
from ..common import FetchResult, Observation, SourceError, env_key, http_get

API = "https://api.stlouisfed.org/fred"


def fetch(series_id: str, start: str) -> FetchResult:
    key = env_key("FRED_API_KEY")
    obs_resp = http_get(f"{API}/series/observations", params={
        "series_id": series_id, "api_key": key, "file_type": "json",
        "observation_start": start,
    }).json()
    if "observations" not in obs_resp:
        raise SourceError(f"FRED respuesta inesperada para {series_id}: {str(obs_resp)[:200]}")
    obs = []
    for row in obs_resp["observations"]:
        if row.get("value") in (".", "", None):   # FRED usa "." para faltantes
            continue
        try:
            obs.append(Observation(row["date"], float(row["value"])))
        except ValueError:
            continue
    meta = http_get(f"{API}/series", params={"series_id": series_id, "api_key": key, "file_type": "json"}).json()
    s = (meta.get("seriess") or [{}])[0]
    return FetchResult(
        observations=obs,
        source_url=f"https://fred.stlouisfed.org/series/{series_id}",
        unit=s.get("units"),
        published=s.get("last_updated"),
    )
