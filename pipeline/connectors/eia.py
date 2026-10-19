"""EIA API v2 (U.S. Energy Information Administration). Clave gratuita: https://www.eia.gov/opendata/register.php"""
from ..common import FetchResult, Observation, SourceError, env_key, http_get

API = "https://api.eia.gov/v2/petroleum/pri/gnd/data/"


def fetch(series: str, start: str) -> FetchResult:
    params = {
        "api_key": env_key("EIA_API_KEY"),
        "frequency": "weekly",
        "data[0]": "value",
        "facets[series][]": series,
        "start": start,
        "sort[0][column]": "period",
        "sort[0][direction]": "asc",
        "length": 5000,
    }
    js = http_get(API, params=params).json()
    data = (js.get("response") or {}).get("data")
    if data is None:
        raise SourceError(f"EIA respuesta inesperada: {str(js)[:200]}")
    obs = [Observation(r["period"], float(r["value"])) for r in data if r.get("value") not in (None, "")]
    unit = data[0].get("units") if data else None
    return FetchResult(obs, source_url=f"https://www.eia.gov/dnav/pet/hist/LeafHandler.ashx?n=PET&s={series}&f=W",
                       unit=unit)
