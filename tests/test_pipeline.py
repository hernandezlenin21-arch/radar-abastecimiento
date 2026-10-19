"""Pruebas del pipeline. Usan datos de prueba (fixtures) — nunca se publican en producción."""
import io
import json
from datetime import date, datetime, timedelta, timezone

import openpyxl
import pytest

from pipeline import alerts, analytics, news, normalize, quality, store
from pipeline.common import FetchResult, Observation, SourceError, load_yaml
from pipeline.connectors import ams, fred, gdelt, noaa, nyfed, worldbank

SETTINGS = load_yaml("settings.yaml")


# ---------------------------------------------------------------- unidades
def test_unit_conversions_exact():
    f, u = normalize.rule("short_ton_to_t", "USD/short ton")
    assert u == "USD/t" and abs(200 * f - 220.462) < 0.01          # 200 USD/st = 220.46 USD/t
    assert abs(normalize.apply(4.00, "bu_corn_to_t", "USD/bu") - 157.47) < 0.01   # maíz 56 lb
    assert abs(normalize.apply(10.00, "bu_soy_to_t", "USD/bu") - 367.44) < 0.01   # soya 60 lb
    assert abs(normalize.apply(3.785411784, "gal_to_l", "USD/gal") - 1.0) < 1e-9
    assert normalize.rule(None, "USD/bbl") == (1.0, "USD/bbl")
    with pytest.raises(ValueError):
        normalize.rule("inventada", "x")


# ---------------------------------------------------------------- análisis
def _monthly(n=72, start=100.0, step=1.01):
    d, v = [], []
    x = start
    for i in range(n):
        y, m = 2020 + i // 12, i % 12 + 1
        d.append(f"{y:04d}-{m:02d}-01"); v.append(round(x, 4)); x *= step if i % 3 else 1 / step
    return d, v


def test_monthly_series_has_no_daily_changes():
    d, v = _monthly()
    ch = analytics.changes(d, v, "mensual")
    assert ch["1d"] is None and ch["7d"] is None
    assert ch["30d"]["ref_date"] == d[-2] and ch["12m"] is not None


def test_scenarios_require_enough_data():
    d, v = _monthly(n=30)
    sc = analytics.scenarios(v, "mensual")
    assert sc["7d"]["available"] is False                        # horizonte < frecuencia
    assert sc["90d"]["available"] is False and "insuficientes" in sc["90d"]["reason"]


def test_scenarios_bounds_ordered():
    vals = [100 * (1.001 ** i) * (1 + 0.02 * ((i * 7) % 5 - 2) / 2) for i in range(800)]
    sc = analytics.scenarios(vals, "diaria")
    for k in ("7d", "30d", "90d"):
        assert sc[k]["available"] and sc[k]["p10"] <= sc[k]["p50"] <= sc[k]["p90"]


def test_moving_average_and_trend():
    assert analytics.moving_average([1, 2, 3, 4], 2) == [None, 1.5, 2.5, 3.5]
    up = [100 * 1.01 ** i for i in range(40)]
    assert analytics.trend(up, 30)["label"] == "alcista"


def test_correlation_identity():
    d, v = _monthly()
    cm = analytics.correlation_matrix({"a": (d, v), "b": (d, [x * 2 for x in v])})
    assert cm["matrix"][0][1] == 1.0


# ---------------------------------------------------------------- calidad
IND = {"id": "x", "name": "X", "group": "agricola", "frequency": "mensual", "price_type": "promedio_mensual", "unit": "USD/t"}


def test_quality_flags_negative_future_stale():
    obs = [{"date": "2020-01-01", "value": -5}, {"date": "2099-01-01", "value": 10}]
    q = quality.check(IND, obs, source_unit=None, settings=SETTINGS, today=date(2026, 10, 16))
    msgs = " ".join(i["msg"] for i in q["issues"])
    assert q["status"] == "error" and "negativos" in msgs and "futuras" in msgs


def test_quality_stale_and_unit_mismatch():
    obs = [{"date": "2025-01-01", "value": 10}, {"date": "2025-02-01", "value": 10.1}]
    q = quality.check(IND, obs, source_unit="USD/bbl", settings=SETTINGS, today=date(2026, 10, 16))
    assert q["fresh"] is False
    assert any("Unidad" in i["msg"] for i in q["issues"])


def test_quality_empty_is_not_available():
    assert quality.check(IND, [], source_unit=None, settings=SETTINGS)["issues"][0]["msg"] == "Dato no disponible"


def test_cross_check():
    daily = [{"date": f"2026-0{m}-{d:02d}", "value": 80.0} for m in (1, 2) for d in (5, 6)]
    monthly = [{"date": "2026-01-01", "value": 80.0}, {"date": "2026-02-01", "value": 90.0}]
    cc = quality.cross_check(daily, monthly)
    assert cc["ok"] is False and cc["worst_month"] == "2026-02"


# ---------------------------------------------------------------- almacén
def test_store_upsert_dedupe_and_revision(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "STORE_DIR", tmp_path)
    rec = store.load("s")
    e = store.upsert(rec, [Observation("2026-01-01", 1.0), Observation("2026-01-01", 1.0), Observation("2026-01-02", 2.0)],
                     source_url="u", published=None)
    assert e["added"] == 2 and e["duplicates_in_batch"] == 1
    e = store.upsert(rec, [Observation("2026-01-02", 2.5)], source_url="u", published=None)
    assert e["revised"] == 1 and rec["revisions"][-1]["old"] == 2.0
    store.save(rec)
    assert len(store.load("s")["observations"]) == 2


# ---------------------------------------------------------------- conectores (respuestas simuladas)
class FakeResp:
    def __init__(self, js=None, text="", content=b""):
        self._js, self.text, self.content = js, text, content

    def json(self):
        if self._js is None:
            raise ValueError("no json")
        return self._js


def test_fred_skips_missing_dots(monkeypatch):
    monkeypatch.setenv("FRED_API_KEY", "test")
    def fake(url, **kw):
        if url.endswith("observations"):
            return FakeResp({"observations": [{"date": "2026-10-01", "value": "70.1"}, {"date": "2026-10-02", "value": "."}]})
        return FakeResp({"seriess": [{"units": "Dollars per Barrel", "last_updated": "2026-10-08"}]})
    monkeypatch.setattr(fred, "http_get", fake)
    r = fred.fetch("DCOILWTICO", "2026-01-01")
    assert [o.date for o in r.observations] == ["2026-10-01"] and r.source_url.endswith("DCOILWTICO")


def test_fred_requires_key(monkeypatch):
    monkeypatch.delenv("FRED_API_KEY", raising=False)
    from pipeline.common import MissingCredential
    with pytest.raises(MissingCredential):
        fred.fetch("DCOILWTICO", "2026-01-01")


def _pinksheet_bytes():
    wb = openpyxl.Workbook()
    ws = wb.active; ws.title = "Monthly Prices"
    ws.append(["World Bank Commodity Price Data"]); ws.append([]); ws.append([]); ws.append([])
    ws.append([None, "Crude oil, average", "Maize", "Soybean meal", "Beef **"])
    ws.append([None, "($/bbl)", "($/mt)", "($/mt)", "($/kg)"])
    ws.append(["2026M08", 70.0, 200.0, 350.0, 6.1])
    ws.append(["2026M09", 72.0, 205.5, "…", 6.2])
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()


def test_worldbank_parse():
    data = worldbank.parse_workbook(_pinksheet_bytes())
    assert [o.value for o in data["maize"]["obs"]] == [200.0, 205.5]
    assert len(data["soybean meal"]["obs"]) == 1              # el "…" se descarta, no se inventa
    assert data["beef"]["unit"] == "($/kg)"


def test_worldbank_discover_url(monkeypatch):
    monkeypatch.delenv("PINKSHEET_URL", raising=False)
    monkeypatch.setattr(worldbank, "http_get", lambda u, **k: FakeResp(text='<a href="https://thedocs.worldbank.org/en/doc/abc/related/CMO-Historical-Data-Monthly.xlsx">x</a>'))
    assert worldbank.discover_url().endswith("CMO-Historical-Data-Monthly.xlsx")
    monkeypatch.setattr(worldbank, "http_get", lambda u, **k: FakeResp(text="sin enlace"))
    with pytest.raises(SourceError):
        worldbank.discover_url()


def test_nyfed_parse():
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Date", "GSCPI"]); ws.append([datetime(2026, 8, 31), 0.12]); ws.append(["30-Sep-2026", 0.25])
    buf = io.BytesIO(); wb.save(buf)
    obs = nyfed.parse(buf.getvalue())
    assert [(o.date, o.value) for o in obs] == [("2026-08-01", 0.12), ("2026-09-01", 0.25)]


def test_oni_parse():
    txt = "SEAS  YR   TOTAL   ANOM\n  JJA 2026  27.10  -0.35\n  JAS 2026  26.90  -0.52\n"
    obs = noaa.parse_oni(txt)
    assert obs[-1].date == "2026-08-01" and obs[-1].value == -0.52


def test_ams_parse_uses_avg_or_midpoint():
    rows = [{"report_date": "10/14/2026", "commodity": "Corn Distillers", "price_min": "180", "price_max": "200"},
            {"report_date": "10/14/2026", "commodity": "Corn Distillers", "avg_price": "210"},
            {"report_date": "10/07/2026", "commodity": "Corn Distillers"}]           # sin precio: se ignora
    obs = ams.parse_results(rows)
    assert len(obs) == 1 and obs[0].value == 200.0


def test_gdelt_seendate():
    assert gdelt.parse_seendate("20261016T143000Z").startswith("2026-10-16T14:30")
    assert gdelt.parse_seendate("x") is None


# ---------------------------------------------------------------- alertas y noticias
def test_no_daily_alert_for_monthly_series():
    d, v = _monthly()
    v[-1] = v[-2] * 1.25
    ind = {**IND, "id": "maiz", "name": "Maíz", "frequency": "mensual"}
    s = analytics.summarize(ind, d, v, SETTINGS)
    al = alerts.series_alerts(ind, s, {"fresh": True}, {"label": "WB", "url": "u"}, SETTINGS["alerts"])
    rules = {a["rule"] for a in al}
    assert "cambio_diario" not in rules and "cambio_mensual" in rules
    assert all(a["url"] and a["evidence"] and a["action"] for a in al)


def test_news_dedupe_and_age_filter():
    now = datetime.now(timezone.utc)
    raw = {"energia": [
        {"title": "Oil prices rise as OPEC cuts output again", "url": "a", "published": now.isoformat()},
        {"title": "Oil prices rise as OPEC cuts output again today", "url": "b", "published": now.isoformat()},
        {"title": "Old story about corn", "url": "c", "published": (now - timedelta(days=30)).isoformat()}]}
    out = news.process(raw, SETTINGS["chokepoints"])
    assert [n["url"] for n in out] == ["a"]
