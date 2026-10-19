"""Genera un ENTORNO DE DEMOSTRACIÓN con datos SINTÉTICOS (caminatas aleatorias).

⚠ Estos datos NO son reales. Se escriben en demo/ (separado de producción) y el
dashboard muestra una franja roja "DEMO — datos de prueba" en todas las vistas.
Uso: python tests/make_demo.py   → luego abrir demo/site/index.html con un servidor local.
"""
import json
import math
import os
import random
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
random.seed(7)

START_VALUES = {"maiz": 210, "soya": 430, "harina_soya": 380, "ddgs": 190, "trigo": 250, "aceite_soya": 1050,
                "aceite_palma": 980, "aceite_mani": 1900, "wti": 70, "brent": 74, "diesel_nyh": 2.4,
                "diesel_retail_us": 3.7, "henry_hub": 3.0, "carbon": 120, "oro": 2300, "plata": 28, "carne_bovina": 5.5,
                "gscpi": 0.2, "usd_index": 120, "tasa_10y": 4.2, "oni": -0.3}


def dates_for(freq, years=6):
    end = date(2026, 10, 15)
    d = end - timedelta(days=365 * years)
    out = []
    while d <= end:
        if freq == "diaria" and d.weekday() < 5:
            out.append(d)
        elif freq == "semanal" and d.weekday() == 0:
            out.append(d)
        elif freq == "mensual" and d.day == 1:
            out.append(d)
        d += timedelta(days=1)
    if freq == "mensual":
        out = out[:-1]          # rezago de publicación
    return out


def main():
    shutil.rmtree(DEMO, ignore_errors=True)
    (DEMO / "store" / "series").mkdir(parents=True)
    cfg = yaml.safe_load((ROOT / "config" / "indicators.yaml").read_text(encoding="utf-8"))
    for ind in cfg["indicators"]:
        if not ind.get("enabled", True):
            continue
        ds = dates_for(ind["frequency"])
        v = START_VALUES[ind["id"]]
        vol = {"diaria": 0.018, "semanal": 0.03, "mensual": 0.05}[ind["frequency"]]
        obs = []
        additive = ind["price_type"] == "indice" and ind["id"] in ("gscpi", "oni")
        for i, d in enumerate(ds):
            shock = random.gauss(0, vol)
            if i == len(ds) - 3 and ind["id"] in ("wti", "brent"):
                shock = 0.07           # salto artificial para ejercitar alertas
            v = v + shock * 2 if additive else v * math.exp(shock)
            obs.append({"date": d.isoformat(), "value": round(v, 4), "retrieved": "DEMO"})
        if ind["id"] == "gscpi":
            obs[-1]["value"] = 1.35
        rec = {"id": ind["id"], "observations": obs, "source_url": "https://example.invalid/DEMO",
               "fetch_log": [{"at": "DEMO", "ok": True, "url": "https://example.invalid/DEMO"}], "last_success": "DEMO"}
        (DEMO / "store" / "series" / f"{ind['id']}.json").write_text(json.dumps(rec), encoding="utf-8")
    now = "2026-10-16T12:00:00+00:00"
    events = {
        "nhc": {"ok": True, "data": {"url": "https://www.nhc.noaa.gov/", "storms": [
            {"id": "ep992026", "name": "DEMO-UNO", "classification": "TS", "intensity": "50", "pressure": "998",
             "latitudeNumeric": 11.2, "longitudeNumeric": -90.1, "lastUpdate": now}]}},
        "enso": {"ok": True, "data": {"status": "La Niña Advisory", "url": "https://www.cpc.ncep.noaa.gov/"}},
        "news": {"ok": True, "at": now, "data": {"errors": {}, "raw": {
            "transporte_maritimo": [
                {"title": "DEMO: Panama Canal draft restrictions announced amid low water", "url": "https://example.invalid/1",
                 "domain": "demo.invalid", "published": now},
                {"title": "DEMO: Red Sea shipping attacks raise freight rates", "url": "https://example.invalid/2",
                 "domain": "demo.invalid", "published": now}],
            "commodities_agricolas": [
                {"title": "DEMO: Corn and soybean prices rise after WASDE report", "url": "https://example.invalid/3",
                 "domain": "demo.invalid", "published": now}]}}},
    }
    (DEMO / "store" / "events.json").write_text(json.dumps(events), encoding="utf-8")
    shutil.copytree(ROOT / "site", DEMO / "site", ignore=shutil.ignore_patterns("data"))
    env = {**os.environ, "STORE_DIR": str(DEMO / "store"), "SITE_DATA_DIR": str(DEMO / "site" / "data"),
           "DASHBOARD_MODE": "demo"}
    subprocess.run([sys.executable, "-m", "pipeline.run", "--offline"], cwd=ROOT, env=env, check=True)
    print(f"Demo lista en {DEMO / 'site'} — datos SINTÉTICOS")


if __name__ == "__main__":
    main()
