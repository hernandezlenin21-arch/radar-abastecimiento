"""Controles de calidad automáticos por serie."""
from __future__ import annotations

from datetime import date, datetime

EXPECTED_DAYS = {"diaria": 1, "semanal": 7, "mensual": 31}
# Margen extra: fines de semana/feriados (diaria) y rezago de publicación (mensual)
GRACE_DAYS = {"diaria": 4, "semanal": 7, "mensual": 45}
NEGATIVE_OK = {"indice"}


def check(ind: dict, obs: list[dict], *, source_unit: str | None, settings: dict, today: date | None = None) -> dict:
    today = today or date.today()
    issues: list[dict] = []
    freq = ind["frequency"]

    if not obs:
        return {"status": "sin_datos", "issues": [{"level": "error", "msg": "Dato no disponible"}],
                "age_days": None, "fresh": False}

    # Fechas inconsistentes
    dates = [o["date"] for o in obs]
    if len(set(dates)) != len(dates):
        issues.append({"level": "error", "msg": "Fechas duplicadas en el historial"})
    future = [d for d in dates if d > today.isoformat()]
    if future:
        issues.append({"level": "error", "msg": f"{len(future)} fechas futuras ({future[-1]})"})

    # Nulos / negativos
    vals = [o["value"] for o in obs]
    if any(v is None for v in vals):
        issues.append({"level": "error", "msg": "Valores nulos"})
    if ind["price_type"] not in NEGATIVE_OK and any(v is not None and v <= 0 for v in vals):
        issues.append({"level": "error", "msg": "Precios cero o negativos (inválidos para esta serie)"})

    # Cambios extraordinarios (último dato vs anterior)
    limit = settings["quality"]["max_abs_change_pct"][freq]
    if len(vals) >= 2 and vals[-2] and ind["price_type"] not in NEGATIVE_OK:
        chg = (vals[-1] / vals[-2] - 1) * 100
        if abs(chg) > limit:
            issues.append({"level": "warn", "msg": f"Cambio de {chg:+.1f}% en un periodo: requiere verificación"})

    # Unidad reportada por la fuente vs configurada
    if source_unit and not _unit_compatible(ind["unit"], source_unit):
        issues.append({"level": "warn", "msg": f"Unidad de la fuente '{source_unit}' difiere de la configurada '{ind['unit']}'"})

    # Frescura
    last = datetime.strptime(dates[-1], "%Y-%m-%d").date()
    age = (today - last).days
    max_age = EXPECTED_DAYS[freq] * settings["alerts"]["stale_factor"] + GRACE_DAYS[freq]
    fresh = age <= max_age
    if not fresh:
        issues.append({"level": "warn", "msg": f"Dato obsoleto: {age} días desde la última observación"})

    status = "error" if any(i["level"] == "error" for i in issues) else ("advertencia" if issues else "ok")
    return {"status": status, "issues": issues, "age_days": age, "fresh": fresh}


def _unit_compatible(cfg: str, src: str) -> bool:
    a, b = cfg.lower(), src.lower()
    tokens = [t for t in ("bbl", "barrel", "gal", "mmbtu", "troy", "oz", "/t", "mt", "kg", "short", "index", "percent", "%") if t in a]
    if not tokens:
        return True
    alias = {"bbl": ["barrel", "bbl"], "gal": ["gallon", "gal"], "mmbtu": ["mmbtu", "million btu"],
             "troy": ["troy"], "oz": ["oz", "ounce"], "/t": ["/mt", "metric ton", "/t"], "mt": ["mt", "metric ton"],
             "kg": ["kg", "kilogram"], "short": ["short", "ton"], "%": ["percent", "%"], "percent": ["percent", "%"],
             "index": ["index"]}
    return any(any(x in b for x in alias.get(t, [t])) for t in tokens)


def cross_check(daily_obs: list[dict], monthly_obs: list[dict], tol_pct: float = 3.0) -> dict | None:
    """Compara el promedio mensual de una serie diaria con una referencia mensual de otra fuente."""
    from collections import defaultdict
    buckets = defaultdict(list)
    for o in daily_obs:
        buckets[o["date"][:7]].append(o["value"])
    ref = {o["date"][:7]: o["value"] for o in monthly_obs}
    common = sorted(set(buckets) & set(ref))[-6:]
    if not common:
        return None
    diffs = [(m, (sum(buckets[m]) / len(buckets[m]) / ref[m] - 1) * 100) for m in common if ref[m]]
    worst = max(diffs, key=lambda x: abs(x[1]))
    return {"months": [m for m, _ in diffs], "diff_pct": [round(d, 2) for _, d in diffs],
            "ok": abs(worst[1]) <= tol_pct, "worst_month": worst[0], "worst_diff_pct": round(worst[1], 2)}
