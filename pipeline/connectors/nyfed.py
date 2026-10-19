"""Fed de Nueva York — Global Supply Chain Pressure Index (mensual, sin clave)."""
from __future__ import annotations

import io
from datetime import date, datetime

import openpyxl

from ..common import FetchResult, Observation, SourceError, http_get

URL = "https://www.newyorkfed.org/medialibrary/research/interactives/gscpi/downloads/gscpi_data.xlsx"
PAGE = "https://www.newyorkfed.org/research/policy/gscpi"


def _to_date(v) -> str | None:
    if isinstance(v, (datetime, date)):
        return f"{v.year:04d}-{v.month:02d}-01"
    if isinstance(v, str):
        for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%b-%Y"):
            try:
                d = datetime.strptime(v.strip(), fmt)
                return f"{d.year:04d}-{d.month:02d}-01"
            except ValueError:
                pass
    return None


def parse(content: bytes) -> list[Observation]:
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    for ws in wb.worksheets:
        rows = list(ws.iter_rows(values_only=True))
        for i, r in enumerate(rows[:10]):
            idx = next((j for j, c in enumerate(r) if c and "gscpi" in str(c).lower()), None)
            if idx is None:
                continue
            obs = {}
            for row in rows[i + 1:]:
                d = _to_date(row[0]) if row else None
                v = row[idx] if row and idx < len(row) else None
                if d and isinstance(v, (int, float)):
                    obs[d] = Observation(d, float(v))
            if obs:
                return sorted(obs.values(), key=lambda o: o.date)
    raise SourceError("No se encontró la columna GSCPI en el Excel de la Fed de NY")


def fetch(source_key: str, start: str) -> FetchResult:
    obs = [o for o in parse(http_get(URL, timeout=60).content) if o.date >= start]
    return FetchResult(obs, source_url=PAGE, unit="desv. estándar")
