"""Briefing ejecutivo generado por reglas a partir de los datos del día.

Formato de cada punto: Qué ocurrió → Evidencia → Posible impacto → Acción sugerida.
Cada punto lleva su tipo (hecho / interpretación / acción) y las referencias
(indicador, fecha, fuente) para mantener la trazabilidad.
"""
from __future__ import annotations

from .alerts import BUY_GROUPS, SEVERITY_ORDER

IMPACT_TEXT = {
    "maiz": "Costo de la fórmula de alimento balanceado (principal fuente energética).",
    "soya": "Costo de proteína vegetal y de la molienda.",
    "harina_soya": "Costo de proteína en alimento balanceado.",
    "ddgs": "Alternativa proteica/energética a la harina de soya y al maíz.",
    "trigo": "Subproductos de trigo y competencia por superficie con maíz.",
    "aceite_soya": "Costo de grasas/aceites y precio de referencia para aceites comestibles.",
    "aceite_palma": "Precio de referencia de aceites vegetales comestibles.",
    "aceite_mani": "Referencia para aceites especiales.",
    "wti": "Fletes terrestres, búnker y costo de combustibles importados.",
    "brent": "Referencia del precio de combustibles importados en Centroamérica.",
    "diesel_nyh": "Señal anticipada del diésel importado (flota, montacargas, generación).",
    "diesel_retail_us": "Tendencia del diésel en EE.UU. (no es precio local).",
    "henry_hub": "Costos de fertilizantes y energía en EE.UU.",
    "carbon": "Referencia de costos energéticos para generación de vapor.",
    "oro": "Termómetro de aversión al riesgo e inflación.",
    "plata": "Termómetro de riesgo y demanda industrial.",
    "carne_bovina": "Precio de referencia internacional de carne procesada.",
}


def _best_change(s: dict, freq: str):
    ch = s.get("changes", {})
    for k in (("7d", "30d") if freq != "mensual" else ("30d", "90d")):
        if ch.get(k):
            return k, ch[k]
    return None, None


def build(indicators: list[dict], summaries: dict, sources: dict, alerts: list[dict], risks: list[dict], news: list[dict]) -> dict:
    movers = []
    for ind in indicators:
        s = summaries.get(ind["id"])
        if not s or ind["group"] in ("macro", "clima", "logistica"):
            continue
        k, c = _best_change(s, ind["frequency"])
        if not c:
            continue
        vol = (s.get("volatility") or {}).get("one_year") or (s.get("volatility") or {}).get("full")
        horizon_sd = (vol / 100) * ((7 if k == "7d" else 30 if k == "30d" else 90) / 365) ** 0.5 * 100 if vol else None
        sig = abs(c["pct"]) / horizon_sd if horizon_sd else abs(c["pct"]) / 5
        movers.append({"id": ind["id"], "name": ind["name"], "group": ind["group"], "horizon": k, "pct": c["pct"],
                       "significance": round(sig, 2), "date": s["last"]["date"], "value": s["last"]["value"],
                       "unit": ind.get("unit_norm"), "frequency": ind["frequency"], "url": sources[ind["id"]]["url"],
                       "source": sources[ind["id"]]["label"]})
    movers.sort(key=lambda m: m["significance"], reverse=True)
    top = movers[:5]

    top_risks = sorted(risks, key=lambda r: SEVERITY_ORDER.index(r["severity"]))[:3]
    key_alerts = [a for a in alerts if a["severity"] in ("critico", "alto")]

    items = []
    for m in top[:3]:
        up = m["pct"] > 0
        buy = m["group"] in BUY_GROUPS
        hz = {"7d": "7 días", "30d": "30 días", "90d": "90 días"}[m["horizon"]]
        impact = IMPACT_TEXT.get(m["id"], "")
        if buy:
            action = ("Revisar inventario disponible y cotizaciones; evaluar fijar precio en parte del volumen."
                      if up else "Evaluar adelantar compras o renegociar precio aprovechando la baja.")
        else:
            action = "Monitorear; no implica acción de compra directa."
        items.append({
            "what": f"{m['name']} {'subió' if up else 'bajó'} {abs(m['pct']):.1f}% en {hz}.",
            "evidence": f"Último dato {m['value']:,.2f} {m['unit'] or ''} ({m['date']}, {m['frequency']}). "
                        f"Movimiento de {m['significance']:.1f}× su variación típica en ese horizonte.",
            "impact": impact + (" Presión al alza en costos." if buy and up else " Posible alivio de costos." if buy else ""),
            "action": action, "type_impact": "interpretación", "type_action": "acción sugerida",
            "refs": [{"indicator": m["id"], "date": m["date"], "source": m["source"], "url": m["url"]}],
        })
    for r in top_risks[:2]:
        if r["severity"] in ("critico", "alto", "medio"):
            items.append({
                "what": r["title"], "evidence": r["description"], "impact": r["impact_ni"],
                "action": r["mitigation"][0], "type_impact": "interpretación", "type_action": "acción sugerida",
                "refs": [{"indicator": r["id"], "date": r.get("date"), "source": r["source"], "url": r["url"]}],
                "official": r.get("official", False),
            })

    # Titular: la alerta más severa o el mayor movimiento
    core = ["maiz", "harina_soya", "soya", "ddgs", "diesel_nyh", "brent", "wti", "gscpi", "aceite_soya", "aceite_palma"]
    def prio(a):
        ind = a.get("indicator", "")
        return (SEVERITY_ORDER.index(a["severity"]), 0 if a.get("official", True) else 1,
                core.index(ind) if ind in core else (len(core) if a["rule"] == "evento_riesgo" else len(core) + 1))
    key_alerts = sorted(key_alerts, key=prio)
    if key_alerts:
        headline = key_alerts[0]["title"]
    elif top:
        m = top[0]
        headline = f"{m['name']}: {m['pct']:+.1f}% en {m['horizon']} — el movimiento más significativo del día"
    else:
        headline = "Sin movimientos significativos en los indicadores disponibles"

    ups = sum(1 for m in movers if m["pct"] > 0)
    downs = sum(1 for m in movers if m["pct"] < 0)
    state = "alcista" if ups > downs * 1.5 else "bajista" if downs > ups * 1.5 else "mixto"
    opportunities = [m for m in movers if m["group"] in BUY_GROUPS and m["pct"] < 0 and m["significance"] >= 1]
    pressure = [m for m in movers if m["group"] in BUY_GROUPS and m["pct"] > 0 and m["significance"] >= 1]

    summary_txt = (f"De {len(movers)} commodities con datos, {ups} suben y {downs} bajan en su horizonte de referencia "
                   f"(estado {state}). {len(key_alerts)} alerta(s) de severidad alta o crítica; "
                   f"{len([r for r in risks if r['severity'] in ('critico', 'alto')])} riesgo(s) logístico(s) relevantes.")

    recs = []
    for m in pressure[:3]:
        recs.append(f"Presión en {m['name']} ({m['pct']:+.1f}%): revisar cobertura y fijación de precio.")
    for m in opportunities[:3]:
        recs.append(f"Oportunidad en {m['name']} ({m['pct']:+.1f}%): evaluar compra anticipada.")
    for r in top_risks:
        if r["severity"] in ("critico", "alto"):
            m0 = r['mitigation'][0]
            recs.append(f"{r['title']}: {m0[0].lower() + m0[1:]}.")
    if not recs:
        recs.append("Sin señales que requieran acción inmediata; mantener monitoreo.")

    return {"headline": headline, "summary": summary_txt, "market_state": state,
            "top_movers": top, "top_risks": top_risks, "items": items,
            "opportunities": opportunities[:5], "pressure": pressure[:5], "recommendations": recs[:6],
            "method": "Narrativa generada por reglas a partir de los datos y titulares del día; no es opinión editorial."}
