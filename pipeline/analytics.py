"""Motor estadístico. Todas las funciones trabajan sobre la serie normalizada.

Distinción de salidas:
  - hechos: variaciones, máximos/mínimos, medias móviles, volatilidad observada
  - escenarios estadísticos: rangos P10–P90 construidos con rendimientos
    históricos (no son pronósticos de mercado ni certezas)
"""
from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median, pstdev

PERIODS_PER_YEAR = {"diaria": 252, "semanal": 52, "mensual": 12}
DAYS_PER_PERIOD = {"diaria": 1.45, "semanal": 7, "mensual": 30.44}   # 1.45 = días calendario por día hábil


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def value_at_or_before(dates: list[str], values: list[float], target: date):
    i = bisect_right(dates, target.isoformat()) - 1
    return (dates[i], values[i]) if i >= 0 else (None, None)


def changes(dates: list[str], values: list[float], freq: str) -> dict:
    """Variación % a 1, 7, 30, 90 días y 12 meses, solo si la frecuencia lo permite."""
    if not values:
        return {}
    last_d = _d(dates[-1])
    horizons = {"1d": 1, "7d": 7, "30d": 30, "90d": 90, "12m": 365}
    min_h = {"diaria": 1, "semanal": 7, "mensual": 28}[freq]
    out = {}
    for k, days in horizons.items():
        if days < min_h:
            out[k] = None                     # no aplica a la frecuencia de la serie
            continue
        if k == "1d":
            ref_d, ref_v = (dates[-2], values[-2]) if len(values) > 1 else (None, None)
        else:
            ref_d, ref_v = value_at_or_before(dates, values, last_d - timedelta(days=days))
        if ref_v in (None, 0) or ref_d == dates[-1]:
            out[k] = None
        else:
            out[k] = {"pct": round((values[-1] / ref_v - 1) * 100, 2), "ref_date": ref_d, "ref_value": ref_v}
    return out


def moving_average(values: list[float], n: int) -> list[float | None]:
    out, s = [], 0.0
    for i, v in enumerate(values):
        s += v
        if i >= n:
            s -= values[i - n]
        out.append(round(s / n, 6) if i >= n - 1 else None)
    return out


def log_returns(values: list[float]) -> list[float]:
    return [math.log(b / a) for a, b in zip(values, values[1:]) if a > 0 and b > 0]


def volatility(values: list[float], freq: str, window: int | None = None) -> float | None:
    r = log_returns(values)
    if window:
        r = r[-window:]
    if len(r) < 8:
        return None
    return round(pstdev(r) * math.sqrt(PERIODS_PER_YEAR[freq]) * 100, 2)   # % anualizada


def zscore(values: list[float], window: int) -> float | None:
    ref = values[-window - 1:-1]
    if len(ref) < max(10, window // 2):
        return None
    sd = pstdev(ref)
    return round((values[-1] - mean(ref)) / sd, 2) if sd else None


def range_stats(dates, values, since: date) -> dict | None:
    pts = [(d, v) for d, v in zip(dates, values) if d >= since.isoformat()]
    if not pts:
        return None
    hi = max(pts, key=lambda p: p[1])
    lo = min(pts, key=lambda p: p[1])
    vs = [p[1] for p in pts]
    return {"max": hi[1], "max_date": hi[0], "min": lo[1], "min_date": lo[0],
            "mean": round(mean(vs), 4), "median": round(median(vs), 4),
            "std": round(pstdev(vs), 4) if len(vs) > 1 else 0, "n": len(vs),
            "pct_rank": round(sum(v <= vs[-1] for v in vs) / len(vs) * 100, 1)}


def trend(values: list[float], n: int) -> dict | None:
    """Pendiente de regresión lineal sobre log(precio) en las últimas n obs, con estadístico t."""
    y = [math.log(v) for v in values[-n:] if v > 0]
    if len(y) < max(8, n // 2):
        return None
    xs = list(range(len(y)))
    mx, my = mean(xs), mean(y)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (yy - my) for x, yy in zip(xs, y)) / sxx
    resid = [yy - (my + slope * (x - mx)) for x, yy in zip(xs, y)]
    se = math.sqrt(sum(e * e for e in resid) / max(1, len(y) - 2) / sxx) if sxx else 0
    t = slope / se if se else 0
    label = "alcista" if t > 2 else "bajista" if t < -2 else "lateral"
    return {"slope_pct_per_obs": round(slope * 100, 3), "t_stat": round(t, 2), "label": label, "n": len(y)}


def trend_change(values: list[float], short: int, long: int, lookback: int = 5) -> str | None:
    """Detecta cruce de medias móviles en las últimas `lookback` observaciones."""
    s, l = moving_average(values, short), moving_average(values, long)
    pairs = [(a, b) for a, b in zip(s, l) if a is not None and b is not None][-(lookback + 1):]
    if len(pairs) < 2:
        return None
    before, now = pairs[0][0] - pairs[0][1], pairs[-1][0] - pairs[-1][1]
    if before <= 0 < now:
        return "cruce_alcista"
    if before >= 0 > now:
        return "cruce_bajista"
    return None


def monthly_last(dates, values) -> dict[str, float]:
    out = {}
    for d, v in zip(dates, values):
        out[d[:7]] = v
    return out


def seasonality(dates, values, min_years: int = 5) -> dict | None:
    """Rendimiento mensual promedio por mes calendario (requiere ≥ min_years de historia)."""
    m = monthly_last(dates, values)
    keys = sorted(m)
    if len(keys) < min_years * 12:
        return None
    by_month = defaultdict(list)
    for a, b in zip(keys, keys[1:]):
        if m[a] > 0:
            by_month[int(b[5:])].append((m[b] / m[a] - 1) * 100)
    return {str(k): {"mean_pct": round(mean(v), 2), "n": len(v), "pos_share": round(sum(x > 0 for x in v) / len(v) * 100)}
            for k, v in sorted(by_month.items())}


def correlation_matrix(series: dict[str, tuple[list[str], list[float]]], months: int = 36) -> dict:
    """Correlación de rendimientos mensuales (últimos `months` meses)."""
    rets = {}
    for sid, (dates, values) in series.items():
        m = monthly_last(dates, values)
        keys = sorted(m)[-(months + 1):]
        rets[sid] = {b: math.log(m[b] / m[a]) for a, b in zip(keys, keys[1:]) if m[a] > 0 and m[b] > 0}
    ids = list(rets)
    mat = []
    for a in ids:
        row = []
        for b in ids:
            common = sorted(set(rets[a]) & set(rets[b]))
            if len(common) < 12:
                row.append(None)
                continue
            xa, xb = [rets[a][k] for k in common], [rets[b][k] for k in common]
            sa, sb = pstdev(xa), pstdev(xb)
            if not sa or not sb:
                row.append(None)
                continue
            cov = mean([(x - mean(xa)) * (y - mean(xb)) for x, y in zip(xa, xb)])
            row.append(round(cov / (sa * sb), 2))
        mat.append(row)
    return {"ids": ids, "matrix": mat, "months": months}


def scenarios(values: list[float], freq: str, horizons_days=(7, 30, 90)) -> dict:
    """Rangos P10/P50/P90 a partir de rendimientos históricos de h periodos (ventanas solapadas).

    No es un pronóstico: describe qué rango de variación ha sido habitual
    en el historial disponible. Se omite si los datos son insuficientes.
    """
    out = {}
    min_windows = 60
    for hd in horizons_days:
        h = round(hd / DAYS_PER_PERIOD[freq])
        key = f"{hd}d"
        if h < 1:
            out[key] = {"available": False, "reason": "Horizonte menor que la frecuencia de publicación"}
            continue
        hist = values[-(PERIODS_PER_YEAR[freq] * 5 + h):]      # máx. 5 años
        rets = [math.log(b / a) for a, b in zip(hist, hist[h:]) if a > 0 and b > 0]
        if len(rets) < min_windows:
            out[key] = {"available": False, "reason": f"Datos insuficientes ({len(rets)} ventanas; se requieren {min_windows})"}
            continue
        rets.sort()
        q = lambda p: rets[min(len(rets) - 1, max(0, int(round(p * (len(rets) - 1)))))]  # noqa: E731
        last = values[-1]
        out[key] = {"available": True, "periods": h, "windows": len(rets),
                    "p10": round(last * math.exp(q(0.10)), 4), "p50": round(last * math.exp(q(0.50)), 4),
                    "p90": round(last * math.exp(q(0.90)), 4),
                    "p10_pct": round((math.exp(q(0.10)) - 1) * 100, 2), "p90_pct": round((math.exp(q(0.90)) - 1) * 100, 2),
                    "method": "Cuantiles empíricos de rendimientos históricos de igual horizonte (≤5 años)"}
    return out


def summarize(ind: dict, dates: list[str], values: list[float], settings: dict) -> dict:
    freq = ind["frequency"]
    if not values:
        return {}
    last = _d(dates[-1])
    ma_n = (7, 30, 90)
    long_n = {"diaria": 60, "semanal": 26, "mensual": 12}[freq]
    return {
        "last": {"date": dates[-1], "value": values[-1]},
        "changes": changes(dates, values, freq),
        "ma": {f"ma{n}": moving_average(values, n)[-1] for n in ma_n},
        "volatility": {"recent": volatility(values, freq, window={"diaria": 30, "semanal": 13, "mensual": 12}[freq]),
                       "one_year": volatility(values, freq, window=PERIODS_PER_YEAR[freq]),
                       "full": volatility(values, freq)},
        "zscore": zscore(values, {"diaria": settings["alerts"]["zscore_window"], "semanal": 26, "mensual": 24}[freq]),
        "range_12m": range_stats(dates, values, last - timedelta(days=365)),
        "range_3y": range_stats(dates, values, last - timedelta(days=365 * 3)),
        "trend": trend(values, long_n),
        "trend_change": trend_change(values, {"diaria": 20, "semanal": 8, "mensual": 3}[freq], long_n),
        "seasonality": seasonality(dates, values),
        "scenarios": scenarios(values, freq),
    }
