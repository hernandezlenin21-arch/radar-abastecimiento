"""NOAA: índice ONI (CPC), estado ENSO y ciclones tropicales activos (NHC). Sin clave."""
from __future__ import annotations

import re

from ..common import FetchResult, Observation, SourceError, http_get

ONI_URL = "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt"
ENSO_URL = "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml"
NHC_URL = "https://www.nhc.noaa.gov/CurrentStorms.json"

# El ONI es una media móvil de 3 meses; se fecha en el mes central.
_SEAS_MID = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
             "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}


def parse_oni(text: str) -> list[Observation]:
    obs = []
    for line in text.splitlines():
        p = line.split()
        if len(p) >= 4 and p[0] in _SEAS_MID and p[1].isdigit():
            try:
                obs.append(Observation(f"{int(p[1]):04d}-{_SEAS_MID[p[0]]:02d}-01", float(p[3])))
            except ValueError:
                pass
    if not obs:
        raise SourceError("Formato ONI no reconocido")
    return obs


def fetch_oni(source_key: str, start: str) -> FetchResult:
    obs = [o for o in parse_oni(http_get(ONI_URL).text) if o.date >= start]
    return FetchResult(obs, source_url=ONI_URL, unit="°C anomalía",
                       notes=["Media móvil de 3 meses fechada en el mes central"])


def fetch_enso_status() -> dict:
    html = http_get(ENSO_URL).text
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"ENSO Alert System Status:\s*([^.:]+?)(?:Synopsis|\.|$)", text, re.I)
    syn = re.search(r"Synopsis:\s*(.{20,400}?\.)", text)
    return {"status": m.group(1).strip() if m else None,
            "synopsis_en": syn.group(1).strip() if syn else None,
            "url": ENSO_URL}


def fetch_storms() -> dict:
    js = http_get(NHC_URL).json()
    if "activeStorms" not in js:
        raise SourceError("CurrentStorms.json sin la clave activeStorms")
    return {"storms": js["activeStorms"], "url": "https://www.nhc.noaa.gov/"}
