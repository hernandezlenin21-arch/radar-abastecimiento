"""Motor de alertas tempranas. Reglas explícitas y verificables.

Cada alerta incluye: regla activada, evidencia numérica, fecha, fuente y
acción de seguimiento. Las reglas respetan la frecuencia de publicación:
no se generan alertas diarias sobre series mensuales.

Diseño extensible: `dispatch()` es el punto de enganche para notificaciones
(correo, WhatsApp, Teams) en una fase posterior.
"""
from __future__ import annotations

import hashlib

SEVERITY_ORDER = ["critico", "alto", "medio", "bajo", "informativo"]
BUY_GROUPS = {"agricola", "energia", "proteinas"}   # alzas = presión de costo


def _id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12]


def _dir_text(ind, pct):
    if ind["group"] in BUY_GROUPS:
        return "presión al alza en costos" if pct > 0 else "posible ventana de compra"
    return "movimiento al alza" if pct > 0 else "movimiento a la baja"


def series_alerts(ind: dict, summary: dict, quality: dict, src: dict, th: dict) -> list[dict]:
    out = []
    if not summary:
        return out
    ch, freq, last = summary["changes"], ind["frequency"], summary["last"]
    base = {"indicator": ind["id"], "name": ind["name"], "group": ind["group"], "date": last["date"],
            "source": src["label"], "url": src["url"], "frequency": freq}

    def add(rule, sev, title, evidence, action):
        out.append({**base, "id": _id(ind["id"], rule, last["date"]), "rule": rule, "severity": sev,
                    "title": title, "evidence": evidence, "action": action})

    buy = ind["group"] in BUY_GROUPS
    c1 = ch.get("1d")
    if freq == "diaria" and c1 and abs(c1["pct"]) >= th["daily_change_pct"]:
        sev = "alto" if abs(c1["pct"]) >= 2 * th["daily_change_pct"] else "medio"
        if not buy or c1["pct"] < 0:
            sev = "bajo" if buy else "informativo"
        add("cambio_diario", sev, f"{ind['name']}: {c1['pct']:+.1f}% en una sesión ({_dir_text(ind, c1['pct'])})",
            f"{c1['ref_value']:.2f} ({c1['ref_date']}) → {last['value']:.2f} ({last['date']}). Umbral ±{th['daily_change_pct']}%.",
            "Confirmar si el movimiento persiste en las próximas sesiones antes de ajustar órdenes de compra.")
    c7 = ch.get("7d")
    if freq in ("diaria", "semanal") and c7 and abs(c7["pct"]) >= th["weekly_change_pct"]:
        sev = ("alto" if c7["pct"] > 0 else "medio") if buy else "informativo"
        add("cambio_7d", sev, f"{ind['name']}: {c7['pct']:+.1f}% acumulado en 7 días",
            f"{c7['ref_value']:.2f} ({c7['ref_date']}) → {last['value']:.2f}. Umbral ±{th['weekly_change_pct']}%.",
            "Revisar cobertura de inventario y cotizaciones vigentes con proveedores." if c7["pct"] > 0
            else "Evaluar adelantar compras o negociar precio con proveedores.")
    c30 = ch.get("30d")
    if freq == "mensual" and c30 and abs(c30["pct"]) >= th["monthly_change_pct"]:
        sev = ("alto" if c30["pct"] > 0 else "bajo") if buy else "informativo"
        add("cambio_mensual", sev, f"{ind['name']}: {c30['pct']:+.1f}% vs. el mes anterior (promedio mensual)",
            f"{c30['ref_value']:.2f} ({c30['ref_date'][:7]}) → {last['value']:.2f} ({last['date'][:7]}). Umbral ±{th['monthly_change_pct']}%.",
            "Actualizar el costo estándar de la materia prima en el presupuesto y en el simulador.")
    z = summary.get("zscore")
    if z is not None and abs(z) >= th["zscore"]:
        sev = "alto" if abs(z) >= 3 else "medio"
        if not buy:
            sev = "informativo"
        add("anomalia_z", sev, f"{ind['name']}: valor atípico ({z:+.1f} desviaciones estándar)",
            f"Último valor {last['value']:.2f} frente a la media de referencia. Umbral ±{th['zscore']} σ.",
            "Verificar en la fuente original y buscar el evento que explica el movimiento.")
    vol = summary.get("volatility") or {}
    if vol.get("recent") and vol.get("one_year") and vol["recent"] >= th["vol_ratio"] * vol["one_year"]:
        add("volatilidad", "medio" if buy else "informativo",
            f"{ind['name']}: volatilidad reciente {vol['recent']:.0f}% vs. {vol['one_year']:.0f}% anual",
            f"Volatilidad anualizada reciente / de 1 año = {vol['recent'] / vol['one_year']:.2f}× (umbral {th['vol_ratio']}×).",
            "Considerar compras escalonadas para reducir el riesgo de entrada en un mal momento.")
    if ind["id"] == "gscpi" and last["value"] >= th["gscpi_high"]:
        add("gscpi_alto", "critico" if last["value"] >= 2 else "alto",
            f"Presión global en cadenas de suministro elevada (GSCPI {last['value']:+.2f})",
            f"GSCPI {last['value']:+.2f} desv. est. sobre su promedio histórico ({last['date'][:7]}). Umbral {th['gscpi_high']}.",
            "Ampliar tiempos de entrega planificados y revisar stock de seguridad de importados.")
    if quality and not quality.get("fresh", True):
        add("dato_obsoleto", "informativo", f"{ind['name']}: dato sin actualizar ({quality['age_days']} días)",
            f"Última observación {last['date']}; frecuencia esperada {freq}.",
            "Revisar el estado del conector o la publicación de la fuente.")
    return out


def dispatch(alerts: list[dict]) -> None:
    """Gancho para notificaciones futuras (correo/mensajería). Hoy no envía nada."""
    return None


def sort_alerts(alerts: list[dict]) -> list[dict]:
    return sorted(alerts, key=lambda a: (SEVERITY_ORDER.index(a["severity"]), a.get("date", "")), reverse=False)


def merge_history(history: list[dict], current: list[dict], now: str, keep: int = 500) -> list[dict]:
    known = {a["id"] for a in history}
    for a in current:
        if a["id"] not in known:
            history.append({**a, "first_seen": now})
    return sorted(history, key=lambda a: a["first_seen"], reverse=True)[:keep]
