"""Orquestador: descarga → normaliza → historial → calidad → análisis → alertas → riesgos → briefing.

Uso:
  python -m pipeline.run               # actualización completa
  python -m pipeline.run --offline     # recalcula con el historial guardado (sin red)
  python -m pipeline.run --only maiz,wti --skip-news
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import alerts as alerts_mod
from . import analytics, briefing, news as news_mod, normalize, quality, risks, store
from .common import SITE_DATA_DIR, MissingCredential, SourceError, load_yaml, now_local_iso
from .connectors import CONNECTORS, SOURCE_LABELS
from .connectors import gdelt, noaa, nyfed

MODE = os.environ.get("DASHBOARD_MODE", "produccion")


def fetch_indicator(ind: dict, start: str) -> tuple[str, dict]:
    rec = store.load(ind["id"])
    try:
        res = CONNECTORS[ind["connector"]](ind["source_key"], start)
        if not res.observations:
            raise SourceError("La fuente no devolvió observaciones")
        entry = store.upsert(rec, res.observations, source_url=res.source_url, published=res.published)
        rec["source_url"], rec["source_unit"], rec["notes"] = res.source_url, res.unit, res.notes
        status = {"ok": True, **entry}
    except MissingCredential as exc:
        store.log_failure(rec, str(exc))
        status = {"ok": False, "error": str(exc), "kind": "credencial"}
    except Exception as exc:  # noqa: BLE001 — cualquier fallo se registra; se conserva el último dato válido
        store.log_failure(rec, f"{type(exc).__name__}: {exc}")
        status = {"ok": False, "error": f"{type(exc).__name__}: {exc}", "kind": "fuente"}
    store.save(rec)
    return ind["id"], status


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--skip-news", action="store_true")
    args = ap.parse_args(argv)

    cfg, settings = load_yaml("indicators.yaml"), load_yaml("settings.yaml")
    inds = [i for i in cfg["indicators"] if i.get("enabled", True)]
    disabled = [i for i in cfg["indicators"] if not i.get("enabled", True)]
    if args.only:
        wanted = set(args.only.split(","))
        inds = [i for i in inds if i["id"] in wanted]
    now = now_local_iso()
    status = store.load_json("status.json", {"sources": {}, "indicators": {}})
    status["run_at"] = now

    # 1) Series — en paralelo controlado (4 hilos); el Pink Sheet se descarga una sola vez
    if not args.offline:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for sid, st in pool.map(lambda i: fetch_indicator(i, settings["history_start"]), inds):
                status["indicators"][sid] = {**st, "at": now}
                print(("  OK  " if st["ok"] else "  --  ") + sid + ("" if st["ok"] else f"  ({st['error']})"))

    # 2) Normalización, calidad y análisis
    catalog, summaries, sources, series_norm, all_alerts = [], {}, {}, {}, []
    (SITE_DATA_DIR / "series").mkdir(parents=True, exist_ok=True)
    for ind in inds:
        rec = store.load(ind["id"])
        obs = rec["observations"]
        factor, unit_norm = normalize.rule(ind.get("normalize"), ind["unit"])
        dates = [o["date"] for o in obs]
        vals = [round(o["value"] * factor, 6) for o in obs]
        ind = {**ind, "unit_norm": unit_norm, "factor": factor}
        src = {"label": SOURCE_LABELS[ind["connector"]], "url": rec.get("source_url") or "",
               "published": (rec.get("fetch_log") or [{}])[-1].get("published") if rec.get("fetch_log") else None}
        sources[ind["id"]] = src
        q = quality.check(ind, obs, source_unit=rec.get("source_unit"), settings=settings)
        s = analytics.summarize(ind, dates, vals, settings) if vals else {}
        summaries[ind["id"]] = s
        series_norm[ind["id"]] = (dates, vals)
        last_ok = next((e for e in reversed(rec.get("fetch_log", [])) if e.get("ok")), None)
        last_try = (rec.get("fetch_log") or [None])[-1]
        sync = ("sin_datos" if not vals else "actualizado" if last_try and last_try.get("ok")
                else "ultimo_dato_valido")
        catalog.append({**{k: ind[k] for k in ("id", "name", "group", "connector", "source_key", "price_type", "market",
                                                 "unit", "unit_norm", "factor", "frequency", "drivers")},
                        "source": src, "notes": rec.get("notes", []), "quality": q, "summary": s, "sync": sync,
                        "last_success": rec.get("last_success"), "last_attempt": last_try,
                        "last_ok_fetch": last_ok, "revisions": rec.get("revisions", [])[-5:]})
        (SITE_DATA_DIR / "series" / f"{ind['id']}.json").write_text(
            json.dumps({"id": ind["id"], "dates": dates, "values": vals, "raw": [o["value"] for o in obs]},
                       separators=(",", ":")), encoding="utf-8")
        all_alerts += alerts_mod.series_alerts(ind, s, q, src, settings["alerts"])

    # 3) Validación cruzada entre fuentes (Brent/WTI diario FRED vs promedio mensual Banco Mundial)
    cross = {}
    if not args.offline:
        for sid, col in (("brent", "Crude oil, Brent"), ("wti", "Crude oil, WTI")):
            if sid in series_norm:
                try:
                    from .connectors import worldbank
                    ref = worldbank.fetch(col, settings["history_start"]).observations
                    d, v = series_norm[sid]
                    cross[sid] = quality.cross_check([{"date": a, "value": b} for a, b in zip(d, v)],
                                                     [{"date": o.date, "value": o.value} for o in ref])
                    if cross[sid]:
                        cross[sid]["reference"] = f"Banco Mundial Pink Sheet — {col}"
                except Exception as exc:  # noqa: BLE001
                    cross[sid] = {"error": str(exc)}
        store.save_json("cross_checks.json", cross)
    else:
        cross = store.load_json("cross_checks.json", {})

    # 4) Fuentes de eventos: NHC, ENSO, noticias
    events_store = store.load_json("events.json", {})
    def safe(name, fn):
        try:
            data = fn()
            events_store[name] = {"ok": True, "at": now, "data": data}
            status["sources"][name] = {"ok": True, "at": now}
        except Exception as exc:  # noqa: BLE001
            status["sources"][name] = {"ok": False, "at": now, "error": f"{type(exc).__name__}: {exc}"}
            events_store.setdefault(name, {"ok": False, "data": None})["last_error"] = str(exc)
    if not args.offline:
        safe("nhc", noaa.fetch_storms)
        safe("enso", noaa.fetch_enso_status)
        if not args.skip_news:
            def _news():
                raw, errs = gdelt.fetch_all(settings["news"]["queries"], settings["news"]["timespan"],
                                            settings["news"]["max_per_query"])
                if not raw:
                    raise SourceError(f"GDELT sin resultados: {errs}")
                return {"raw": raw, "errors": errs}
            safe("news", _news)
        store.save_json("events.json", events_store)

    news_raw = ((events_store.get("news") or {}).get("data") or {}).get("raw", {})
    news_items = news_mod.process(news_raw, settings["chokepoints"])
    storms = ((events_store.get("nhc") or {}).get("data") or {})
    enso = (events_store.get("enso") or {}).get("data")
    oni_last = (summaries.get("oni") or {}).get("last")
    gscpi_src = sources.get("gscpi", {}).get("url") or nyfed.PAGE
    risk_events = (risks.storm_events(storms.get("storms", []), settings["reference_points"], storms.get("url", ""))
                   + risks.chokepoint_events(news_items, settings["chokepoints"], settings["risk_keywords"])
                   + risks.enso_event(enso, oni_last)
                   + risks.gscpi_event(summaries.get("gscpi"), gscpi_src))
    for r in risk_events:
        if r["severity"] in ("critico", "alto") and r["kind"] != "gscpi":   # gscpi ya genera su alerta
            all_alerts.append({"id": alerts_mod._id(r["id"], r.get("date")), "indicator": r["id"], "name": r["type"],
                               "group": "logistica", "date": (r.get("date") or "")[:10], "rule": "evento_riesgo",
                               "severity": r["severity"], "title": r["title"], "evidence": r["description"],
                               "action": r["mitigation"][0], "source": r["source"], "url": r["url"],
                               "frequency": "evento", "official": r["official"]})

    all_alerts = alerts_mod.sort_alerts(all_alerts)
    history = alerts_mod.merge_history(store.load_json("alerts_history.json", []), all_alerts, now)
    store.save_json("alerts_history.json", history)
    alerts_mod.dispatch(all_alerts)

    corr_ids = [i["id"] for i in inds if i["group"] in ("agricola", "energia", "metales", "proteinas")]
    corr = analytics.correlation_matrix({k: series_norm[k] for k in corr_ids if series_norm.get(k) and series_norm[k][1]})
    brief = briefing.build([{**i, "unit_norm": normalize.rule(i.get("normalize"), i["unit"])[1]} for i in inds],
                           summaries, sources, all_alerts, risk_events, news_items)

    # 5) Escritura de salidas para el frontend
    out = {
        "meta.json": {"generated_at": now, "mode": MODE, "timezone": "America/Managua", "version": "1.0.0",
                      "disabled_indicators": [{"id": i["id"], "name": i["name"], "reason": "Desactivado en config (pendiente de validación)"} for i in disabled]},
        "catalog.json": {"indicators": catalog, "correlation": corr, "cross_checks": cross,
                         "thresholds": settings["alerts"]},
        "alerts.json": {"current": all_alerts, "history": history[:300]},
        "risks.json": {"events": risk_events, "chokepoints": settings["chokepoints"],
                       "sources": {k: status["sources"].get(k) for k in ("nhc", "enso", "news")}},
        "news.json": {"items": news_items, "errors": ((events_store.get("news") or {}).get("data") or {}).get("errors", {}),
                      "fetched_at": (events_store.get("news") or {}).get("at")},
        "briefing.json": brief,
        "status.json": status,
    }
    SITE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name, data in out.items():
        (SITE_DATA_DIR / name).write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    store.save_json("status.json", status)
    ok = sum(1 for i in catalog if i["sync"] == "actualizado")
    print(f"Listo: {ok}/{len(catalog)} series actualizadas, {len(all_alerts)} alertas, {len(risk_events)} eventos, {len(news_items)} noticias")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
