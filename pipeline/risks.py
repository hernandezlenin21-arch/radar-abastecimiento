"""Radar de riesgos: eventos con fecha, ubicación, fuente, severidad y mitigación.

Fuentes de eventos:
  1. NHC (oficial): ciclones activos y su distancia a puertos de Nicaragua.
  2. NOAA CPC (oficial): estado ENSO.
  3. Fed NY (oficial): GSCPI.
  4. Titulares de prensa (GDELT) que mencionan puntos críticos — se marcan
     como "señal de prensa" y deben confirmarse con la autoridad competente.
La probabilidad NO se estima: no existe una metodología sustentada con estos datos.
"""
from __future__ import annotations

import math

MITIGATION = {
    "ciclon": ["Confirmar con agentes navieros el estado de Corinto/Puerto Sandino", "Adelantar o retrasar arribos programados",
               "Asegurar inventario crítico y combustible para planta", "Revisar rutas terrestres alternas"],
    "punto_critico": ["Consultar con navieras/agentes el impacto en tiempos de tránsito", "Revisar fletes contratados vs. spot",
                      "Evaluar origen alternativo o ampliar stock de seguridad"],
    "enso": ["Revisar proyecciones de cosecha en zonas de origen afectadas", "Planificar compras anticipadas si se esperan déficits",
             "Evaluar impacto en disponibilidad de biomasa/insumos locales"],
    "gscpi": ["Ampliar lead times planificados", "Aumentar stock de seguridad de importados", "Negociar capacidad con navieras"],
}


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


CLASS = {"HU": "Huracán", "TS": "Tormenta tropical", "TD": "Depresión tropical", "STS": "Tormenta subtropical",
         "STD": "Depresión subtropical", "PTC": "Ciclón potencial", "PC": "Ciclón potencial"}


def storm_events(storms: list[dict], refs: list[dict], url: str) -> list[dict]:
    ev = []
    for s in storms:
        lat, lon = s.get("latitudeNumeric"), s.get("longitudeNumeric")
        if lat is None or lon is None:
            continue
        near = min(refs, key=lambda r: haversine_km(lat, lon, r["lat"], r["lon"]))
        dist = haversine_km(lat, lon, near["lat"], near["lon"])
        cls = s.get("classification", "")
        if dist < 500:
            sev = "critico" if cls == "HU" else "alto"
        elif dist < 1200:
            sev = "medio"
        else:
            sev = "bajo"
        adv = (s.get("publicAdvisory") or {}).get("url") or url
        ev.append({
            "id": f"storm-{s.get('id')}", "type": "Ciclón tropical", "kind": "ciclon", "official": True,
            "date": s.get("lastUpdate"), "lat": lat, "lon": lon,
            "location": f"{lat:.1f}, {lon:.1f}",
            "title": f"{CLASS.get(cls, cls)} {s.get('name', '')}".strip(),
            "description": f"Vientos {s.get('intensity', '?')} nudos, presión {s.get('pressure', '?')} mb. "
                           f"A {dist:,.0f} km de {near['name']}.",
            "source": "NOAA National Hurricane Center", "url": adv,
            "affected": ["Puertos del Pacífico/Caribe centroamericano", "Transporte terrestre regional"],
            "severity": sev, "probability": None,
            "impact_ni": "Directo" if dist < 500 else ("Posible" if dist < 1200 else "Bajo, lejos de Nicaragua"),
            "mitigation": MITIGATION["ciclon"],
        })
    return ev


def chokepoint_events(news: list[dict], chokepoints: list[dict], kw: dict) -> list[dict]:
    by_cp: dict[str, list[dict]] = {}
    for n in news:
        for cp in chokepoints:
            if cp["name"] in n.get("chokepoints", []):
                by_cp.setdefault(cp["id"], []).append(n)
    ev = []
    for cp in chokepoints:
        items = by_cp.get(cp["id"])
        if not items:
            continue
        def sev_of(t):
            t = t.lower()
            for level in ("critico", "alto", "medio"):
                if any(k in t for k in kw[level]):
                    return level
            return "bajo"
        ranked = sorted(items, key=lambda n: ["critico", "alto", "medio", "bajo"].index(sev_of(n["title"])))
        top = ranked[0]
        sev = sev_of(top["title"])
        if sev == "critico":
            sev = "alto"   # tope para señales de prensa no confirmadas por autoridad
        ev.append({
            "id": f"cp-{cp['id']}", "type": "Punto crítico logístico", "kind": "punto_critico", "official": False,
            "date": top["published"], "lat": cp["lat"], "lon": cp["lon"], "location": cp["name"],
            "title": f"{cp['name']}: {len(items)} titular(es) en las últimas horas",
            "description": f"Titular principal: “{top['title']}” ({top.get('domain')}). Señal de prensa: confirmar con la autoridad o naviera.",
            "source": top.get("domain"), "url": top["url"],
            "headlines": [{"title": n["title"], "url": n["url"], "domain": n.get("domain"), "published": n["published"]} for n in ranked[:5]],
            "affected": cp["affects"], "severity": sev, "probability": None,
            "impact_ni": cp["impact_ni"], "mitigation": MITIGATION["punto_critico"],
        })
    return ev


def enso_event(status: dict | None, oni_last: dict | None) -> list[dict]:
    if not status or not status.get("status"):
        return []
    s = status["status"]
    sl = s.lower()
    if "not active" in sl:
        sev, impact = "informativo", "Condiciones neutrales."
    elif "niño" in sl or "nino" in sl:
        sev, impact = ("alto" if "advisory" in sl else "medio"), "El Niño suele asociarse con déficit de lluvia en el Pacífico centroamericano y menor producción de palma en el sudeste asiático."
    else:
        sev, impact = ("medio" if "advisory" in sl else "bajo"), "La Niña suele asociarse con sequía en Argentina/sur de Brasil (soya, maíz) y más lluvia y huracanes en el Caribe."
    ev = {"id": "enso", "type": "Clima — ENSO", "kind": "enso", "official": True, "date": oni_last["date"] if oni_last else None,
          "lat": -5.0, "lon": -145.0, "location": "Pacífico ecuatorial (Niño 3.4)",
          "title": f"Estado ENSO (NOAA): {s}",
          "description": (f"ONI más reciente: {oni_last['value']:+.1f} °C. " if oni_last else "") + "Impacto típico, no determinístico.",
          "source": "NOAA Climate Prediction Center", "url": status["url"], "affected": ["Maíz", "Soya", "Aceite de palma", "Clima Nicaragua"],
          "severity": sev, "probability": None, "impact_ni": impact, "mitigation": MITIGATION["enso"]}
    return [ev]


def gscpi_event(summary: dict | None, url: str) -> list[dict]:
    if not summary:
        return []
    v = summary["last"]["value"]
    sev = "critico" if v >= 2 else "alto" if v >= 1 else "medio" if v >= 0.5 else "bajo"
    return [{"id": "gscpi", "type": "Presión logística global", "kind": "gscpi", "official": True,
             "date": summary["last"]["date"], "lat": 40.7, "lon": -74.0, "location": "Global (Fed NY)",
             "title": f"GSCPI {v:+.2f} desviaciones estándar",
             "description": "Índice compuesto de fletes marítimos/aéreos y PMI de tiempos de entrega. 0 = promedio histórico.",
             "source": "Federal Reserve Bank of New York", "url": url,
             "affected": ["Fletes internacionales", "Tiempos de entrega"], "severity": sev, "probability": None,
             "impact_ni": "Afecta tiempos y costos de importación de toda la región.", "mitigation": MITIGATION["gscpi"]}]
