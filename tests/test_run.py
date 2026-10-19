"""Prueba de integración: si una fuente falla, se conserva el último dato válido y no se inventa nada."""
import json

from pipeline import run, store
from pipeline.common import FetchResult, Observation, SourceError
from pipeline.connectors import CONNECTORS


def test_failure_keeps_last_valid(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(run, "SITE_DATA_DIR", tmp_path / "site")
    calls = {"n": 0}

    def ok_then_fail(key, start):
        calls["n"] += 1
        if calls["n"] == 1:
            return FetchResult([Observation("2026-10-01", 70.0), Observation("2026-10-02", 71.0)], source_url="https://fred.stlouisfed.org/series/X")
        raise SourceError("HTTP 503")

    monkeypatch.setitem(CONNECTORS, "fred", ok_then_fail)
    ind = {"id": "wti", "connector": "fred", "source_key": "X"}
    _, st1 = run.fetch_indicator(ind, "2020-01-01")
    _, st2 = run.fetch_indicator(ind, "2020-01-01")
    rec = store.load("wti")
    assert st1["ok"] and not st2["ok"]
    assert [o["value"] for o in rec["observations"]] == [70.0, 71.0]       # último dato válido intacto
    assert rec["last_error"]["error"].endswith("HTTP 503")


def test_offline_build_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path / "store")
    monkeypatch.setattr(run, "SITE_DATA_DIR", tmp_path / "site")
    rec = store.load("wti")
    store.upsert(rec, [Observation(f"2026-09-{d:02d}", 70 + d * 0.1) for d in range(1, 29)], source_url="https://x", published=None)
    store.save(rec)
    assert run.main(["--offline", "--only", "wti,maiz"]) == 0
    cat = json.loads((tmp_path / "site" / "catalog.json").read_text())
    by = {i["id"]: i for i in cat["indicators"]}
    assert by["wti"]["sync"] == "actualizado" and by["maiz"]["sync"] == "sin_datos"
    assert by["maiz"]["quality"]["issues"][0]["msg"] == "Dato no disponible"
    meta = json.loads((tmp_path / "site" / "meta.json").read_text())
    assert meta["mode"] == "produccion"
