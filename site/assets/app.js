/* Radar de Abastecimiento — frontend.
   Lee los JSON que genera el pipeline (site/data). No contiene claves ni datos incrustados.
   Si una fuente falla, el pipeline conserva el último dato válido y aquí se indica su estado. */
(() => {
"use strict";

const TZ = "America/Managua";
const SEV = ["critico", "alto", "medio", "bajo", "informativo"];
const SEV_LABEL = { critico: "Crítico", alto: "Alto", medio: "Medio", bajo: "Bajo", informativo: "Informativo" };
const GROUP_LABEL = { agricola: "Agrícola", energia: "Energía", metales: "Metales", proteinas: "Proteínas", logistica: "Logística", macro: "Macro", clima: "Clima" };
const BUY_GROUPS = new Set(["agricola", "energia", "proteinas"]);
const PRICE_TYPE = { futuros: "Futuros", fisico_spot: "Físico / spot", fob: "FOB", cif: "CIF", promedio_mensual: "Promedio mensual (estadístico)", indice: "Índice", minorista: "Minorista" };
const FREQ_LABEL = { diaria: "Diaria", semanal: "Semanal", mensual: "Mensual" };
const ACCESS = {
  fred: { method: "API REST (JSON)", cost: "Gratuito · requiere clave" },
  worldbank: { method: "Descarga Excel oficial", cost: "Gratuito · sin clave" },
  nyfed: { method: "Descarga Excel oficial", cost: "Gratuito · sin clave" },
  eia: { method: "API REST v2 (JSON)", cost: "Gratuito · requiere clave" },
  ams: { method: "API MARS (JSON, Basic Auth)", cost: "Gratuito · requiere clave" },
  noaa_oni: { method: "Archivo de texto oficial", cost: "Gratuito · sin clave" },
};
const PERIODS_PER_YEAR = { diaria: 252, semanal: 52, mensual: 12 };

const S = { series: {}, selected: new Set(), detailId: null, tab: "exec", ack: new Set(), th: null, timer: null, worldReady: false };
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------- almacenamiento local (tolerante a fallos) ---------------- */
const store = {
  get(k, d) { try { const v = localStorage.getItem("radar:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("radar:" + k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } },
};

/* ---------------- formato ---------------- */
const nf = (d = 2) => new Intl.NumberFormat("es-NI", { minimumFractionDigits: d, maximumFractionDigits: d });
const fmtNum = (v, d) => v == null || isNaN(v) ? "—" : nf(d ?? (Math.abs(v) >= 1000 ? 0 : Math.abs(v) >= 10 ? 2 : 3)).format(v);
const fmtPct = (v) => v == null || isNaN(v) ? "—" : (v > 0 ? "+" : "") + nf(1).format(v) + "%";
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
function fmtDate(iso, freq) {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return freq === "mensual" ? `${MONTHS[m - 1]} ${y}` : `${d} ${MONTHS[m - 1]} ${y}`;
}
function fmtDT(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return new Intl.DateTimeFormat("es-NI", { timeZone: TZ, day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }).format(d);
}
const todayISO = () => new Intl.DateTimeFormat("en-CA", { timeZone: TZ }).format(new Date());
const addDays = (iso, n) => { const d = new Date(iso + "T12:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); };
const pctClass = (v, grp) => v == null ? "neutral" : (BUY_GROUPS.has(grp) ? (v > 0 ? "up" : v < 0 ? "down" : "neutral") : "neutral");
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function toast(msg) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2600); }

/* ---------------- carga de datos ---------------- */
async function getJSON(path) {
  const r = await fetch(`${path}?v=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

async function load(initial = false) {
  setSync("loading", "Actualizando…");
  $("#btn-refresh").disabled = true;
  try {
    const [meta, catalog, alerts, risks, news, brief, status] = await Promise.all(
      ["meta", "catalog", "alerts", "risks", "news", "briefing", "status"].map((n) => getJSON(`data/${n}.json`)));
    Object.assign(S, { meta, catalog, alertsData: alerts, risks, news, brief, status, queriedAt: new Date().toISOString() });
    S.inds = catalog.indicators;
    S.byId = Object.fromEntries(S.inds.map((i) => [i.id, i]));
    const ser = await Promise.all(S.inds.map((i) => getJSON(`data/series/${i.id}.json`).catch(() => null)));
    ser.forEach((s, k) => { S.series[S.inds[k].id] = s || { dates: [], values: [] }; });
    if (!S.th) S.th = { ...catalog.thresholds, ...store.get("thresholds", {}) };
    if (initial) initControls();
    renderAll();
    updateSync();
  } catch (err) {
    console.error(err);
    setSync("err", S.meta ? `Error al actualizar: se muestran los últimos datos cargados (${fmtDT(S.queriedAt)})` : "No se pudieron cargar los datos. Verifique que el pipeline haya publicado site/data.");
  } finally { $("#btn-refresh").disabled = false; }
}

function setSync(state, text) {
  $("#sync-dot").className = "dot " + (state === "loading" ? "loading" : state);
  $("#sync-text").textContent = text;
}

function updateSync() {
  const total = S.inds.length;
  const upd = S.inds.filter((i) => i.sync === "actualizado").length;
  const lastValid = S.inds.filter((i) => i.sync === "ultimo_dato_valido").length;
  const none = S.inds.filter((i) => i.sync === "sin_datos").length;
  const genAge = (Date.now() - new Date(S.meta.generated_at)) / 36e5;
  let state = "ok";
  if (lastValid || none || genAge > 8) state = "warn";
  if (upd === 0) state = "err";
  const parts = [`Consulta ${fmtDT(S.queriedAt)}`, `datos procesados ${fmtDT(S.meta.generated_at)}`, `${upd}/${total} series al día`];
  if (lastValid) parts.push(`${lastValid} con último dato válido`);
  if (none) parts.push(`${none} sin datos`);
  if (genAge > 8) parts.push(`proceso automático sin ejecutar hace ${Math.round(genAge)} h`);
  setSync(state, parts.join(" · "));
  $("#foot-gen").textContent = `Datos procesados: ${fmtDT(S.meta.generated_at)}`;
  $("#demo-banner").hidden = S.meta.mode !== "demo";
}

/* ---------------- filtros y periodo ---------------- */
function filtered(list = S.inds) {
  const g = $("#f-group").value, f = $("#f-freq").value, src = $("#f-source").value, t = $("#f-trend").value, q = $("#f-search").value.trim().toLowerCase();
  return list.filter((i) => (!g || i.group === g) && (!f || i.frequency === f) && (!src || i.connector === src)
    && (!t || i.summary?.trend?.label === t) && (!q || (i.name + " " + i.market + " " + i.id).toLowerCase().includes(q)));
}
function periodRange() {
  const p = $("#f-period").value;
  const to = (p === "custom" && $("#f-to").value) || todayISO();
  const from = p === "custom" ? ($("#f-from").value || addDays(to, -365)) : addDays(to, -Number(p));
  return [from, to];
}
function slice(id, from, to) {
  const s = S.series[id] || { dates: [], values: [] };
  const out = { dates: [], values: [] };
  s.dates.forEach((d, k) => { if (d >= from && d <= to) { out.dates.push(d); out.values.push(s.values[k]); } });
  return out;
}
function valueAtOrBefore(id, iso) {
  const s = S.series[id]; if (!s?.dates.length) return null;
  let lo = 0, hi = s.dates.length - 1, ans = -1;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (s.dates[m] <= iso) { ans = m; lo = m + 1; } else hi = m - 1; }
  return ans < 0 ? null : { date: s.dates[ans], value: s.values[ans] };
}
function periodChange(id) {
  const [from, to] = periodRange();
  const s = S.series[id]; if (!s?.dates.length) return null;
  const end = valueAtOrBefore(id, to), start = valueAtOrBefore(id, from);
  if (!end || !start || start.date === end.date || !start.value) return null;
  return { pct: (end.value / start.value - 1) * 100, from: start, to: end };
}

/* ---------------- estadística en cliente ---------------- */
const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
const std = (a) => { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))); };
function ma(values, n) { const out = []; let s = 0; values.forEach((v, i) => { s += v; if (i >= n) s -= values[i - n]; out.push(i >= n - 1 ? s / n : null); }); return out; }
function rollingStd(values, n) { return values.map((_, i) => i >= n - 1 ? std(values.slice(i - n + 1, i + 1)) : null); }
function rollingVol(values, n, freq) {
  const r = values.map((v, i) => i && values[i - 1] > 0 && v > 0 ? Math.log(v / values[i - 1]) : null);
  return r.map((_, i) => { if (i < n) return null; const w = r.slice(i - n + 1, i + 1).filter((x) => x != null); return w.length > n / 2 ? std(w) * Math.sqrt(PERIODS_PER_YEAR[freq]) * 100 : null; });
}

/* ---------------- motor de alertas (cliente, con umbrales editables) ---------------- */
function computeAlerts() {
  const th = S.th, out = [];
  for (const ind of S.inds) {
    const s = ind.summary; if (!s?.last) continue;
    const ch = s.changes || {}, buy = BUY_GROUPS.has(ind.group), last = s.last;
    const base = { indicator: ind.id, name: ind.name, group: ind.group, date: last.date, source: ind.source.label, url: ind.source.url, frequency: ind.frequency };
    const add = (rule, severity, title, evidence, action) => out.push({ ...base, id: `${ind.id}|${rule}|${last.date}`, rule, severity, title, evidence, action });
    const dirTxt = (p) => buy ? (p > 0 ? "presión al alza en costos" : "posible ventana de compra") : (p > 0 ? "movimiento al alza" : "movimiento a la baja");
    const c1 = ch["1d"];
    if (ind.frequency === "diaria" && c1 && Math.abs(c1.pct) >= th.daily_change_pct) {
      let sev = Math.abs(c1.pct) >= 2 * th.daily_change_pct ? "alto" : "medio";
      if (!buy || c1.pct < 0) sev = buy ? "bajo" : "informativo";
      add("cambio_diario", sev, `${ind.name}: ${fmtPct(c1.pct)} en una sesión (${dirTxt(c1.pct)})`,
        `${fmtNum(c1.ref_value)} (${fmtDate(c1.ref_date)}) → ${fmtNum(last.value)} (${fmtDate(last.date)}). Umbral ±${th.daily_change_pct}%.`,
        "Confirmar si el movimiento persiste en las próximas sesiones antes de ajustar órdenes de compra.");
    }
    const c7 = ch["7d"];
    if ((ind.frequency === "diaria" || ind.frequency === "semanal") && c7 && Math.abs(c7.pct) >= th.weekly_change_pct) {
      add("cambio_7d", buy ? (c7.pct > 0 ? "alto" : "medio") : "informativo", `${ind.name}: ${fmtPct(c7.pct)} acumulado en 7 días`,
        `${fmtNum(c7.ref_value)} (${fmtDate(c7.ref_date)}) → ${fmtNum(last.value)}. Umbral ±${th.weekly_change_pct}%.`,
        c7.pct > 0 ? "Revisar cobertura de inventario y cotizaciones vigentes con proveedores." : "Evaluar adelantar compras o negociar precio con proveedores.");
    }
    const c30 = ch["30d"];
    if (ind.frequency === "mensual" && c30 && Math.abs(c30.pct) >= th.monthly_change_pct) {
      add("cambio_mensual", buy ? (c30.pct > 0 ? "alto" : "bajo") : "informativo", `${ind.name}: ${fmtPct(c30.pct)} vs. el mes anterior (promedio mensual)`,
        `${fmtNum(c30.ref_value)} (${fmtDate(c30.ref_date, "mensual")}) → ${fmtNum(last.value)} (${fmtDate(last.date, "mensual")}). Umbral ±${th.monthly_change_pct}%.`,
        "Actualizar el costo estándar de la materia prima en el presupuesto y en el simulador.");
    }
    if (s.zscore != null && Math.abs(s.zscore) >= th.zscore) {
      add("anomalia_z", buy ? (Math.abs(s.zscore) >= 3 ? "alto" : "medio") : "informativo", `${ind.name}: valor atípico (${s.zscore > 0 ? "+" : ""}${fmtNum(s.zscore, 1)} desviaciones estándar)`,
        `Último valor ${fmtNum(last.value)} frente a la media de referencia. Umbral ±${th.zscore} σ.`,
        "Verificar en la fuente original y buscar el evento que explica el movimiento.");
    }
    const v = s.volatility || {};
    if (v.recent && v.one_year && v.recent >= th.vol_ratio * v.one_year) {
      add("volatilidad", buy ? "medio" : "informativo", `${ind.name}: volatilidad reciente ${fmtNum(v.recent, 0)}% vs. ${fmtNum(v.one_year, 0)}% anual`,
        `Relación ${fmtNum(v.recent / v.one_year, 2)}× (umbral ${th.vol_ratio}×).`, "Considerar compras escalonadas para reducir el riesgo de entrada.");
    }
    if (ind.id === "gscpi" && last.value >= th.gscpi_high) {
      add("gscpi_alto", last.value >= 2 ? "critico" : "alto", `Presión global en cadenas de suministro elevada (GSCPI ${fmtNum(last.value, 2)})`,
        `GSCPI ${fmtNum(last.value, 2)} desv. est. sobre su promedio histórico (${fmtDate(last.date, "mensual")}). Umbral ${th.gscpi_high}.`,
        "Ampliar tiempos de entrega planificados y revisar stock de seguridad de importados.");
    }
    if (ind.quality && ind.quality.fresh === false) {
      add("dato_obsoleto", "informativo", `${ind.name}: dato sin actualizar (${ind.quality.age_days} días)`, `Última observación ${fmtDate(last.date)}; frecuencia ${ind.frequency}.`, "Revisar el estado del conector o la publicación de la fuente.");
    }
  }
  for (const a of S.alertsData.current.filter((x) => x.rule === "evento_riesgo")) out.push(a);
  return out.sort((a, b) => SEV.indexOf(a.severity) - SEV.indexOf(b.severity));
}

/* ---------------- gráficos ---------------- */
function chart(el) {
  if (!window.echarts) { el.innerHTML = '<p class="empty">No se pudo cargar la librería de gráficos.</p>'; return null; }
  return echarts.getInstanceByDom(el) || echarts.init(el, null, { renderer: "canvas" });
}
function baseOpt() {
  const fg = css("--fg"), muted = css("--muted"), line = css("--line");
  return {
    animationDuration: 300, textStyle: { fontFamily: "IBM Plex Sans, system-ui, sans-serif", color: fg },
    grid: { left: 56, right: 18, top: 28, bottom: 36, containLabel: false },
    tooltip: { trigger: "axis", backgroundColor: css("--surface"), borderColor: line, textStyle: { color: fg, fontSize: 12 }, confine: true },
    legend: { textStyle: { color: muted, fontSize: 11 }, top: 0, type: "scroll" },
    xAxis: { type: "category", axisLine: { lineStyle: { color: line } }, axisLabel: { color: muted, fontSize: 11 }, axisTick: { show: false } },
    yAxis: { type: "value", scale: true, splitLine: { lineStyle: { color: line, type: "dashed" } }, axisLabel: { color: muted, fontSize: 11 } },
  };
}
function spark(el, values, grp) {
  const c = chart(el); if (!c) return;
  if (!values.length) { c.clear(); return; }
  const col = values[values.length - 1] >= values[0] ? (BUY_GROUPS.has(grp) ? css("--up") : css("--accent")) : (BUY_GROUPS.has(grp) ? css("--down") : css("--accent"));
  c.setOption({
    animation: false, grid: { left: 0, right: 0, top: 3, bottom: 3 },
    xAxis: { type: "category", show: false, data: values.map((_, i) => i) }, yAxis: { type: "value", show: false, scale: true },
    series: [{ type: "line", data: values, symbol: "none", lineStyle: { width: 1.5, color: col }, areaStyle: { color: col, opacity: 0.08 },
      markPoint: { symbol: "circle", symbolSize: 5, label: { show: false }, itemStyle: { color: col }, data: [{ coord: [values.length - 1, values[values.length - 1]] }] } }],
  }, true);
}
function resizeAll() { $$(".chart, .spark").forEach((el) => echarts?.getInstanceByDom(el)?.resize()); }

/* ---------------- 1. Resumen ejecutivo ---------------- */
function renderExec() {
  const b = S.brief;
  $("#exec-date").textContent = `${fmtDT(S.meta.generated_at)} · ${b.market_state ? "Estado del mercado: " + b.market_state : ""}`;
  $("#exec-headline").textContent = b.headline;
  $("#exec-summary").textContent = b.summary;
  $("#exec-method").textContent = b.method;
  $("#exec-story").innerHTML = b.items.length ? b.items.map((it) => `<li>
      <div><span class="k">Qué ocurrió <span class="chip fact">Hecho</span></span><span class="what">${esc(it.what)}</span></div>
      <div><span class="k">Evidencia</span>${esc(it.evidence)} ${it.refs.map((r) => `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.source)}</a>`).join(" ")}${it.official === false ? ' <span class="tag press">Señal de prensa</span>' : ""}</div>
      <div><span class="k">Posible impacto <span class="chip interp">Interpretación</span></span>${esc(it.impact)}</div>
      <div><span class="k">Acción sugerida <span class="chip act">Acción</span></span>${esc(it.action)}</div></li>`).join("")
    : '<li class="empty">Sin eventos relevantes con los datos disponibles.</li>';

  const press = ["gscpi", "brent", "wti", "diesel_nyh", "henry_hub", "usd_index"].map((id) => S.byId[id]).filter(Boolean);
  $("#exec-pressure").innerHTML = press.map((i) => {
    const s = i.summary || {}, c = s.changes || {}, ref = i.frequency === "mensual" ? c["30d"] : c["7d"];
    return `<div class="pr"><span class="lbl">${esc(i.name)}</span><span class="v">${fmtNum(s.last?.value)} <small>${esc(i.unit_norm)}</small></span>
      <span class="sub">${fmtDate(s.last?.date, i.frequency)} · ${FREQ_LABEL[i.frequency]} · <span class="pct ${pctClass(ref?.pct, i.group)}">${fmtPct(ref?.pct)} ${i.frequency === "mensual" ? "1 mes" : "7 d"}</span> · ${esc(i.source.label)}</span>
      <div class="spark" id="sp-pr-${i.id}"></div></div>`;
  }).join("") || '<p class="empty">Dato no disponible</p>';
  press.forEach((i) => spark($(`#sp-pr-${i.id}`), slice(i.id, addDays(todayISO(), -365), todayISO()).values, i.group));

  $("#exec-movers").innerHTML = b.top_movers.length ? b.top_movers.map((m) => `<div class="row"><span class="name">${esc(m.name)}<span class="meta">${fmtDate(m.date, m.frequency)} · ${FREQ_LABEL[m.frequency]} · <a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.source)}</a></span></span>
      <span class="pct ${pctClass(m.pct, m.group)}">${fmtPct(m.pct)} <small>${m.horizon}</small></span></div>`).join("") : '<p class="empty">Dato no disponible</p>';
  $("#exec-risks").innerHTML = b.top_risks.length ? b.top_risks.map((r) => `<div class="row"><span class="name"><span class="sev ${r.severity}">${SEV_LABEL[r.severity]}</span> ${esc(r.title)}<span class="meta">${fmtDT(r.date)} · <a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.source)}</a> · ${r.official ? "Oficial" : "Señal de prensa"}</span></span></div>`).join("") : '<p class="empty">Sin riesgos registrados.</p>';
  $("#exec-recs").innerHTML = b.recommendations.map((r) => `<li>${esc(r)}</li>`).join("");
  $("#exec-opps").innerHTML = b.opportunities.length ? b.opportunities.map((m) => `<div class="row"><span class="name">${esc(m.name)}<span class="meta">${fmtDate(m.date, m.frequency)}</span></span><span class="pct down">${fmtPct(m.pct)} <small>${m.horizon}</small></span></div>`).join("") : '<p class="empty">Sin bajas significativas en materias primas de compra.</p>';
}

/* ---------------- 2. Monitor de commodities ---------------- */
function stateChip(i) {
  if (i.sync === "sin_datos") return '<span class="state err">Dato no disponible</span>';
  if (i.sync === "ultimo_dato_valido") return '<span class="state warn">Último dato válido</span>';
  if (i.quality?.fresh === false) return '<span class="state warn">Pendiente de actualización</span>';
  if (i.quality?.status === "advertencia") return '<span class="state warn">Verificar</span>';
  return '<span class="state ok">Actualizado</span>';
}
function renderCards() {
  const list = filtered();
  const [from, to] = periodRange();
  $("#cards").innerHTML = list.map((i) => {
    const s = i.summary || {}, c = s.changes || {}, pc = periodChange(i.id), tr = s.trend?.label;
    const cell = (k, lbl) => `<span><b>${lbl}</b><span class="pct ${pctClass(c[k]?.pct, i.group)}">${c[k] ? fmtPct(c[k].pct) : "n/a"}</span></span>`;
    return `<div class="card ${S.selected.has(i.id) ? "sel" : ""}" data-id="${i.id}" role="button" tabindex="0" aria-label="Ver ${esc(i.name)}">
      <div class="top"><div><div class="grp grp-${i.group}">${GROUP_LABEL[i.group]} · ${esc(PRICE_TYPE[i.price_type] || i.price_type)}</div><div class="nm">${esc(i.name)}</div></div>
        <input type="checkbox" data-cmp="${i.id}" ${S.selected.has(i.id) ? "checked" : ""} aria-label="Comparar ${esc(i.name)}" title="Comparar"></div>
      <div><span class="price">${s.last ? fmtNum(s.last.value) : "—"}</span> <span class="unit">${esc(i.unit_norm)}${i.unit_norm !== i.unit ? ` · orig. ${esc(i.unit)}` : ""}</span></div>
      <div class="chg">${cell("1d", "1d")}${cell("7d", "7d")}${cell("30d", "30d")}${cell("90d", "90d")}${cell("12m", "12m")}</div>
      <div class="spark" id="sp-${i.id}"></div>
      <div class="foot2"><span>Periodo: <span class="pct ${pctClass(pc?.pct, i.group)}">${fmtPct(pc?.pct)}</span>${tr ? ` · ${tr}` : ""}</span>${stateChip(i)}</div>
      <div class="foot2"><span>${fmtDate(s.last?.date, i.frequency)} · ${FREQ_LABEL[i.frequency]}</span><a href="${esc(i.source.url)}" target="_blank" rel="noopener" data-stop>${esc(i.source.label.split(" — ")[0])}</a></div>
    </div>`;
  }).join("") || '<p class="empty">Ningún indicador coincide con los filtros.</p>';
  list.forEach((i) => spark($(`#sp-${i.id}`), slice(i.id, from, to).values, i.group));
  if (S.detailId) renderDetail(S.detailId);
  if (!$("#compare").hidden) renderCompare();
}

function tooltipFor(ind) {
  return (params) => {
    const p = params.find((x) => x.seriesName === "Precio") || params[0];
    if (!p) return "";
    const idx = p.dataIndex, sl = S._detailSlice;
    const prev = idx > 0 ? sl.values[idx - 1] : null, v = sl.values[idx];
    return `<b>${esc(ind.name)}</b><br>${fmtDate(sl.dates[idx], ind.frequency)}<br>
      Valor: <b>${fmtNum(v)}</b> ${esc(ind.unit_norm)}${prev ? `<br>Variación vs. obs. anterior: ${fmtPct((v / prev - 1) * 100)}` : ""}
      ${params.filter((x) => x.seriesName.startsWith("MM")).map((x) => `<br>${x.seriesName}: ${fmtNum(x.value)}`).join("")}
      <br><span style="opacity:.7">${esc(PRICE_TYPE[ind.price_type])} · ${esc(ind.market)}<br>Fuente: ${esc(ind.source.label)}</span>`;
  };
}

function renderDetail(id) {
  const ind = S.byId[id]; if (!ind) return;
  S.detailId = id;
  const panel = $("#detail"); panel.hidden = false;
  const s = ind.summary || {};
  $("#d-title").textContent = ind.name;
  $("#d-sub").textContent = `${PRICE_TYPE[ind.price_type]} · ${ind.market}`;
  $("#d-meta").innerHTML = [
    ["Último", s.last ? `${fmtNum(s.last.value)} ${ind.unit_norm}` : "Dato no disponible"], ["Fecha efectiva", fmtDate(s.last?.date, ind.frequency)],
    ["Unidad original", ind.unit + (ind.factor !== 1 ? ` (×${fmtNum(ind.factor, 4)} → ${ind.unit_norm})` : "")], ["Frecuencia", FREQ_LABEL[ind.frequency]],
    ["Fuente", `<a href="${esc(ind.source.url)}" target="_blank" rel="noopener">${esc(ind.source.label)}</a>`], ["Serie", ind.source_key],
    ["Sincronización", stateChip(ind)], ["Calidad", ind.quality?.issues?.length ? ind.quality.issues.map((x) => esc(x.msg)).join("; ") : "Sin observaciones"],
  ].map(([k, v]) => `<span>${k}: <b>${v}</b></span>`).join("");

  const [from, to] = periodRange();
  const full = S.series[id];
  const startIdx = full.dates.findIndex((d) => d >= from);
  const endIdx = full.dates.length - 1 - [...full.dates].reverse().findIndex((d) => d <= to);
  const i0 = startIdx < 0 ? full.dates.length : startIdx;
  const sl = { dates: full.dates.slice(i0, endIdx + 1), values: full.values.slice(i0, endIdx + 1) };
  S._detailSlice = sl;
  const sub = (arr) => arr.slice(i0, endIdx + 1);
  const m7 = sub(ma(full.values, 7)), m30 = sub(ma(full.values, 30)), m90 = sub(ma(full.values, 90));
  const bn = ind.frequency === "mensual" ? 12 : 20;
  const mb = sub(ma(full.values, bn)), sb = sub(rollingStd(full.values, bn));
  const lower = mb.map((m, k) => m == null ? null : m - 2 * sb[k]), width = mb.map((m, k) => m == null ? null : 4 * sb[k]);
  const marks = (S.alertsData.history || []).filter((a) => a.indicator === id && a.date >= from).slice(0, 12);
  const opt = baseOpt();
  const accent = css("--accent"), muted = css("--muted");
  opt.tooltip.formatter = tooltipFor(ind);
  opt.xAxis.data = sl.dates.map((d) => fmtDate(d, ind.frequency));
  opt.yAxis.name = ind.unit_norm; opt.yAxis.nameTextStyle = { color: muted, fontSize: 11 };
  opt.dataZoom = [{ type: "inside" }];
  opt.series = [
    { name: "Banda ±2σ", type: "line", data: lower, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, tooltip: { show: false } },
    { name: "Banda ±2σ ", type: "line", data: width, stack: "band", symbol: "none", lineStyle: { opacity: 0 }, areaStyle: { color: accent, opacity: 0.08 }, tooltip: { show: false } },
    { name: "Precio", type: "line", data: sl.values, symbol: "none", lineStyle: { width: 2, color: accent }, itemStyle: { color: accent },
      markPoint: { symbolSize: 36, label: { fontSize: 9, color: css("--surface") }, data: [{ type: "max", name: "Máx", itemStyle: { color: css("--up") } }, { type: "min", name: "Mín", itemStyle: { color: css("--down") } }] },
      markLine: marks.length ? { symbol: "none", label: { show: false }, lineStyle: { color: css("--sev-alto"), type: "dotted" },
        data: marks.map((a) => ({ xAxis: fmtDate(a.date, ind.frequency), name: a.title })).filter((x) => opt.xAxis.data.includes(x.xAxis)) } : undefined },
    { name: "MM7", type: "line", data: m7, symbol: "none", lineStyle: { width: 1, color: css("--g-agricola") } },
    { name: "MM30", type: "line", data: m30, symbol: "none", lineStyle: { width: 1, color: css("--g-proteinas") } },
    { name: "MM90", type: "line", data: m90, symbol: "none", lineStyle: { width: 1, color: css("--g-metales") } },
  ];
  opt.legend.data = ["Precio", "MM7", "MM30", "MM90", "Banda ±2σ "];
  opt.legend.formatter = (n) => n.trim();
  chart($("#ch-price"))?.setOption(opt, true);

  const vol = sub(rollingVol(full.values, { diaria: 30, semanal: 13, mensual: 12 }[ind.frequency], ind.frequency));
  const ov = baseOpt(); ov.xAxis.data = opt.xAxis.data; ov.yAxis.axisLabel.formatter = "{value}%";
  ov.series = [{ name: "Volatilidad", type: "line", data: vol.map((x) => x == null ? null : +x.toFixed(2)), symbol: "none", lineStyle: { color: css("--sev-alto") }, areaStyle: { color: css("--sev-alto"), opacity: 0.08 } }];
  ov.tooltip.valueFormatter = (v) => v == null ? "—" : fmtNum(v, 1) + "% anualizada";
  chart($("#ch-vol"))?.setOption(ov, true);

  // Interanual: promedio mensual por año (últimos 3 años)
  const byYM = {};
  full.dates.forEach((d, k) => { const y = d.slice(0, 4), m = +d.slice(5, 7); (byYM[y] ||= {}); (byYM[y][m] ||= []).push(full.values[k]); });
  const years = Object.keys(byYM).sort().slice(-3);
  const oy = baseOpt(); oy.xAxis.data = MONTHS;
  const ycol = [css("--muted"), css("--g-metales"), accent];
  oy.series = years.map((y, k) => ({ name: y, type: "line", symbol: "circle", symbolSize: 4, lineStyle: { color: ycol[k + 3 - years.length] }, itemStyle: { color: ycol[k + 3 - years.length] },
    data: MONTHS.map((_, m) => byYM[y][m + 1] ? +mean(byYM[y][m + 1]).toFixed(4) : null) }));
  oy.tooltip.valueFormatter = (v) => v == null ? "—" : `${fmtNum(v)} ${ind.unit_norm}`;
  chart($("#ch-yoy"))?.setOption(oy, true);

  const v = sl.values;
  const r12 = s.range_12m, r3 = s.range_3y;
  const rows = v.length ? [
    ["Observaciones en el periodo", v.length], ["Media", fmtNum(mean(v))], ["Mediana", fmtNum([...v].sort((a, b) => a - b)[Math.floor(v.length / 2)])],
    ["Desviación estándar", fmtNum(std(v))], ["Máximo", `${fmtNum(Math.max(...v))} (${fmtDate(sl.dates[v.indexOf(Math.max(...v))], ind.frequency)})`],
    ["Mínimo", `${fmtNum(Math.min(...v))} (${fmtDate(sl.dates[v.indexOf(Math.min(...v))], ind.frequency)})`],
    ["Variación del periodo", fmtPct((v[v.length - 1] / v[0] - 1) * 100)],
    ["Rango 12 meses", r12 ? `${fmtNum(r12.min)} – ${fmtNum(r12.max)} (percentil actual ${fmtNum(r12.pct_rank, 0)})` : "—"],
    ["Rango 3 años", r3 ? `${fmtNum(r3.min)} – ${fmtNum(r3.max)}` : "—"],
    ["Volatilidad anualizada (reciente / 1 año)", `${fmtNum(s.volatility?.recent, 1)}% / ${fmtNum(s.volatility?.one_year, 1)}%`],
    ["Z-score último dato", s.zscore == null ? "—" : fmtNum(s.zscore, 2)],
    ["Tendencia (regresión)", s.trend ? `${s.trend.label} (t = ${fmtNum(s.trend.t_stat, 1)})` : "—"],
  ] : [["Datos", "No hay observaciones en el periodo seleccionado"]];
  $("#d-stats").innerHTML = rows.map(([k, x]) => `<tr><td>${k}</td><td class="n">${x}</td></tr>`).join("");
  $("#d-drivers").innerHTML = (ind.drivers || []).map((d) => `<li>${esc(d)}</li>`).join("") + (ind.notes || []).map((n) => `<li class="hint">${esc(n)}</li>`).join("");
  $("#d-events").innerHTML = marks.length ? marks.map((a) => `<li><span class="sev ${a.severity}">${SEV_LABEL[a.severity]}</span> ${fmtDate(a.date, ind.frequency)}: ${esc(a.title)}</li>`).join("") : '<li class="hint">Sin alertas registradas en el periodo.</li>';
}

function renderCompare() {
  const ids = [...S.selected]; if (!ids.length) { $("#compare").hidden = true; return; }
  $("#compare").hidden = false;
  const [from, to] = periodRange();
  // Unión de fechas; cada serie base 100 en su primer dato del periodo
  const all = new Set();
  const data = ids.map((id) => { const sl = slice(id, from, to); sl.dates.forEach((d) => all.add(d)); return { id, sl }; });
  const dates = [...all].sort();
  const opt = baseOpt(); opt.xAxis.data = dates.map((d) => fmtDate(d));
  const palette = [css("--accent"), css("--g-agricola"), css("--g-energia"), css("--g-proteinas"), css("--g-metales"), css("--sev-alto")];
  opt.series = data.map(({ id, sl }, k) => {
    const base = sl.values[0], map = Object.fromEntries(sl.dates.map((d, j) => [d, (sl.values[j] / base) * 100]));
    return { name: S.byId[id].name, type: "line", connectNulls: true, symbol: "none", lineStyle: { width: 1.8, color: palette[k % palette.length] }, itemStyle: { color: palette[k % palette.length] },
      data: dates.map((d) => map[d] != null ? +map[d].toFixed(2) : null) };
  });
  opt.tooltip.valueFormatter = (v) => v == null ? "—" : fmtNum(v, 1);
  opt.yAxis.name = "base 100"; opt.dataZoom = [{ type: "inside" }];
  chart($("#ch-compare"))?.setOption(opt, true);
}

/* ---------------- 3. Riesgos ---------------- */
async function ensureWorld() {
  if (S.worldReady || !window.echarts) return S.worldReady;
  try { echarts.registerMap("world", await getJSON("assets/world.geo.json")); S.worldReady = true; } catch (e) { console.warn("Mapa no disponible", e); }
  return S.worldReady;
}
async function renderRisk() {
  const sev = $("#r-sev").value, ty = $("#r-type").value;
  const ev = S.risks.events.filter((e) => (!sev || e.severity === sev) && (!ty || e.type === ty))
    .sort((a, b) => SEV.indexOf(a.severity) - SEV.indexOf(b.severity));
  const types = [...new Set(S.risks.events.map((e) => e.type))];
  const sel = $("#r-type"); if (sel.options.length - 1 !== types.length) sel.innerHTML = '<option value="">Todo tipo</option>' + types.map((t) => `<option>${esc(t)}</option>`).join("");
  $("#risk-list").innerHTML = ev.length ? ev.map((e) => `<article class="event ${e.severity}">
      <div class="panel-h" style="margin:0"><span class="sev ${e.severity}">${SEV_LABEL[e.severity]}</span><span class="tag ${e.official ? "official" : "press"}">${e.official ? "Fuente oficial" : "Señal de prensa — confirmar"}</span></div>
      <h3>${esc(e.title)}</h3>
      <dl><dt>Fecha</dt><dd>${fmtDT(e.date)}</dd><dt>Ubicación</dt><dd>${esc(e.location)}</dd><dt>Descripción</dt><dd>${esc(e.description)}</dd>
      <dt>Fuente</dt><dd><a href="${esc(e.url)}" target="_blank" rel="noopener">${esc(e.source)}</a></dd>
      <dt>Afecta</dt><dd>${esc((e.affected || []).join(" · "))}</dd><dt>Probabilidad</dt><dd>No estimada (sin metodología sustentada)</dd>
      <dt>Impacto NI/CA</dt><dd>${esc(e.impact_ni)}</dd><dt>Mitigación</dt><dd>${esc((e.mitigation || []).join(" · "))}</dd></dl>
      ${e.headlines ? `<details><summary class="hint">Titulares (${e.headlines.length})</summary><ul class="drivers">${e.headlines.map((h) => `<li><a href="${esc(h.url)}" target="_blank" rel="noopener">${esc(h.title)}</a> <span class="hint">${esc(h.domain)} · ${fmtDT(h.published)}</span></li>`).join("")}</ul></details>` : ""}
    </article>`).join("") : '<p class="empty">Sin eventos con los filtros actuales.</p>';

  const el = $("#ch-map");
  if (!(await ensureWorld())) { el.innerHTML = '<p class="empty">Mapa no disponible.</p>'; return; }
  const c = chart(el); if (!c) return;
  const sevCol = (s) => css({ critico: "--sev-critico", alto: "--sev-alto", medio: "--sev-medio", bajo: "--sev-bajo", informativo: "--sev-info" }[s]);
  c.setOption({
    tooltip: { trigger: "item", backgroundColor: css("--surface"), borderColor: css("--line"), textStyle: { color: css("--fg"), fontSize: 12 }, confine: true,
      formatter: (p) => p.data?.ev ? `<b>${esc(p.data.ev.title)}</b><br>${SEV_LABEL[p.data.ev.severity]} · ${fmtDT(p.data.ev.date)}<br>${esc(p.data.ev.source)}` : p.data?.cp ? `<b>${esc(p.data.cp.name)}</b><br>${esc(p.data.cp.impact_ni)}` : esc(p.name) },
    geo: { map: "world", roam: true, zoom: 1.15, center: [-20, 15], itemStyle: { areaColor: css("--surface-2"), borderColor: css("--line") },
      emphasis: { itemStyle: { areaColor: css("--accent-soft") }, label: { show: false } }, regions: [{ name: "Nicaragua", itemStyle: { areaColor: css("--accent-soft"), borderColor: css("--accent") } }] },
    series: [
      { name: "Puntos críticos", type: "scatter", coordinateSystem: "geo", symbol: "diamond", symbolSize: 9, itemStyle: { color: "transparent", borderColor: css("--muted"), borderWidth: 1.2 },
        data: S.risks.chokepoints.map((cp) => ({ name: cp.name, value: [cp.lon, cp.lat], cp })) },
      { name: "Eventos", type: "effectScatter", coordinateSystem: "geo", rippleEffect: { scale: 2.6, brushType: "stroke" }, showEffectOn: "render",
        symbolSize: (v, p) => ({ critico: 18, alto: 15, medio: 12, bajo: 9, informativo: 8 }[p.data.ev.severity]),
        data: ev.filter((e) => e.lat != null).map((e) => ({ name: e.title, value: [e.lon, e.lat], ev: e, itemStyle: { color: sevCol(e.severity) } })) },
    ],
  }, true);
}

/* ---------------- 4. Tendencias ---------------- */
function renderTrends() {
  const list = filtered().filter((i) => i.summary?.last);
  $("#t-trend").innerHTML = `<thead><tr><th>Indicador</th><th>Frec.</th><th class="n">Último</th><th class="n">Var. periodo</th><th class="n">MM7</th><th class="n">MM30</th><th class="n">MM90</th><th class="n">Vol. 1 año</th><th>Tendencia</th><th class="n">t</th><th>Cambio de tendencia</th></tr></thead><tbody>` +
    list.map((i) => { const s = i.summary, pc = periodChange(i.id); return `<tr><td>${esc(i.name)}</td><td>${FREQ_LABEL[i.frequency]}</td><td class="n">${fmtNum(s.last.value)}</td>
      <td class="n"><span class="pct ${pctClass(pc?.pct, i.group)}">${fmtPct(pc?.pct)}</span></td><td class="n">${fmtNum(s.ma?.ma7)}</td><td class="n">${fmtNum(s.ma?.ma30)}</td><td class="n">${fmtNum(s.ma?.ma90)}</td>
      <td class="n">${s.volatility?.one_year != null ? fmtNum(s.volatility.one_year, 1) + "%" : "—"}</td><td>${s.trend?.label || "—"}</td><td class="n">${s.trend ? fmtNum(s.trend.t_stat, 1) : "—"}</td>
      <td>${s.trend_change === "cruce_alcista" ? "Cruce alcista de medias" : s.trend_change === "cruce_bajista" ? "Cruce bajista de medias" : "—"}</td></tr>`; }).join("") + "</tbody>";

  const sel = $("#s-ind");
  if (!sel.options.length) sel.innerHTML = S.inds.filter((i) => i.summary?.scenarios).map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
  const ind = S.byId[sel.value] || S.inds[0];
  if (ind?.summary?.scenarios) {
    const sc = ind.summary.scenarios, keys = ["7d", "30d", "90d"], last = ind.summary.last.value;
    const av = keys.filter((k) => sc[k]?.available);
    const opt = baseOpt();
    opt.xAxis.data = keys.map((k) => k.replace("d", " días"));
    opt.tooltip = { ...opt.tooltip, trigger: "axis", formatter: (ps) => { const k = keys[ps[0].dataIndex], x = sc[k]; return x?.available ? `<b>${k}</b> · escenario estadístico<br>P90: ${fmtNum(x.p90)} (${fmtPct(x.p90_pct)})<br>P50: ${fmtNum(x.p50)}<br>P10: ${fmtNum(x.p10)} (${fmtPct(x.p10_pct)})<br><span style="opacity:.7">${x.windows} ventanas históricas</span>` : `<b>${k}</b><br>${esc(x?.reason || "No disponible")}`; } };
    opt.series = [
      { type: "bar", stack: "r", data: keys.map((k) => sc[k]?.available ? sc[k].p10 : null), itemStyle: { color: "transparent" }, barWidth: 34 },
      { name: "Rango P10–P90", type: "bar", stack: "r", data: keys.map((k) => sc[k]?.available ? +(sc[k].p90 - sc[k].p10).toFixed(4) : null), itemStyle: { color: css("--g-proteinas"), opacity: 0.35 }, barWidth: 34 },
      { name: "P50", type: "scatter", data: keys.map((k) => sc[k]?.available ? sc[k].p50 : null), symbol: "rect", symbolSize: [34, 3], itemStyle: { color: css("--g-proteinas") } },
      { name: "Último", type: "line", data: keys.map(() => last), symbol: "none", lineStyle: { type: "dashed", color: css("--muted") } },
    ];
    opt.legend.data = ["Rango P10–P90", "P50", "Último"];
    chart($("#ch-scen"))?.setOption(opt, true);
    $("#scen-note").innerHTML = `<span class="chip scen">Escenario estadístico</span> ${av.length ? esc(sc[av[0]].method) + ". No es un pronóstico de mercado." : ""} ${keys.filter((k) => !sc[k]?.available).map((k) => `${k}: ${esc(sc[k]?.reason || "n/d")}`).join(" · ")}`;
    const se = ind.summary.seasonality;
    const os = baseOpt(); os.xAxis.data = MONTHS;
    os.series = [{ type: "bar", name: "Rend. promedio", data: MONTHS.map((_, m) => se?.[m + 1] ? { value: se[m + 1].mean_pct, itemStyle: { color: se[m + 1].mean_pct >= 0 ? css("--up") : css("--down") } } : null), barWidth: "60%" }];
    os.yAxis.axisLabel.formatter = "{value}%"; os.tooltip.valueFormatter = (v) => v == null ? "—" : fmtPct(v);
    chart($("#ch-season"))?.setOption(os, true);
    $("#season-note").textContent = se ? `${ind.name}: rendimiento mensual promedio por mes calendario (${se[1]?.n || "?"} años). Patrón histórico, no garantiza repetición.` : "Datos insuficientes para estacionalidad (se requieren ≥ 5 años de historia).";
  }

  const cr = S.catalog.correlation;
  if (cr?.ids?.length) {
    const names = cr.ids.map((id) => S.byId[id]?.name.split(" (")[0] || id);
    const data = []; cr.matrix.forEach((row, y) => row.forEach((v, x) => data.push([x, y, v])));
    chart($("#ch-corr"))?.setOption({
      tooltip: { formatter: (p) => `${esc(names[p.data[1]])} × ${esc(names[p.data[0]])}<br>ρ = ${p.data[2] == null ? "n/d" : fmtNum(p.data[2], 2)}`, backgroundColor: css("--surface"), borderColor: css("--line"), textStyle: { color: css("--fg") }, confine: true },
      grid: { left: 140, right: 20, top: 10, bottom: 110 },
      xAxis: { type: "category", data: names, axisLabel: { rotate: 55, color: css("--muted"), fontSize: 10 }, axisLine: { lineStyle: { color: css("--line") } } },
      yAxis: { type: "category", data: names, axisLabel: { color: css("--muted"), fontSize: 10 }, axisLine: { lineStyle: { color: css("--line") } } },
      visualMap: { min: -1, max: 1, show: false, inRange: { color: [css("--down"), css("--surface-2"), css("--up")] } },
      series: [{ type: "heatmap", data: data.map((d) => [d[0], d[1], d[2] == null ? null : d[2]]), label: { show: window.innerWidth > 700, fontSize: 9, color: css("--fg"), formatter: (p) => p.data[2] == null ? "" : p.data[2].toFixed(1) } }],
    }, true);
    $("#corr-note").textContent = `Últimos ${cr.months} meses · rendimientos logarítmicos mensuales`;
  }
  const an = S.inds.filter((i) => i.summary?.zscore != null && Math.abs(i.summary.zscore) >= S.th.zscore);
  $("#anoms").innerHTML = an.length ? an.map((i) => `<div class="row"><span class="name">${esc(i.name)}<span class="meta">${fmtDate(i.summary.last.date, i.frequency)} · ${esc(i.source.label)}</span></span><span class="pct">${i.summary.zscore > 0 ? "+" : ""}${fmtNum(i.summary.zscore, 2)} σ</span></div>`).join("") : '<p class="empty">Sin anomalías con el umbral actual.</p>';
}

/* ---------------- 5. Alertas ---------------- */
function renderThresholds() {
  const defs = [["daily_change_pct", "Cambio diario (%)", 0.5], ["weekly_change_pct", "Acumulado 7 días (%)", 0.5], ["monthly_change_pct", "Cambio mensual (%)", 0.5],
    ["zscore", "Anomalía (σ)", 0.1], ["vol_ratio", "Volatilidad reciente / anual (×)", 0.1], ["gscpi_high", "GSCPI alto (σ)", 0.1]];
  $("#th-form").innerHTML = defs.map(([k, l, st]) => `<div class="f"><label for="th-${k}">${l}</label><input type="number" id="th-${k}" data-th="${k}" step="${st}" min="0" value="${S.th[k]}"></div>`).join("")
    + '<div class="f"><label>&nbsp;</label><button class="btn ghost" type="button" id="th-reset">Restablecer</button></div>';
}
function renderAlerts() {
  const all = computeAlerts();
  S.currentAlerts = all;
  const sev = $("#a-sev").value, hide = $("#a-hide-ack").checked;
  const list = all.filter((a) => (!sev || a.severity === sev) && (!hide || !S.ack.has(a.id)));
  const pending = all.filter((a) => !S.ack.has(a.id) && ["critico", "alto"].includes(a.severity)).length;
  $("#alert-count").textContent = pending || "";
  $("#alert-list").innerHTML = list.length ? list.map((a) => `<div class="alert ${a.severity} ${S.ack.has(a.id) ? "ack" : ""}">
      <div class="t">${esc(a.title)}</div>
      <div class="ev"><b>Evidencia:</b> ${esc(a.evidence)}</div>
      <div class="ac"><b>Acción:</b> ${esc(a.action)}</div>
      <div class="mt">${fmtDate(a.date, a.frequency)} · ${esc(FREQ_LABEL[a.frequency] || a.frequency)} · <a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.source)}</a> · regla: ${esc(a.rule)}${a.official === false ? " · señal de prensa" : ""}</div>
      <div class="side"><span class="sev ${a.severity}">${SEV_LABEL[a.severity]}</span><button class="btn ghost" type="button" data-ack="${esc(a.id)}">${S.ack.has(a.id) ? "Reabrir" : "Marcar revisada"}</button></div>
    </div>`).join("") : '<p class="empty">Sin alertas con los filtros y umbrales actuales.</p>';
  const h = (S.alertsData.history || []).filter((a) => !sev || a.severity === sev).slice(0, 150);
  $("#alert-history").innerHTML = `<thead><tr><th>Detectada</th><th>Fecha dato</th><th>Severidad</th><th>Alerta</th><th>Fuente</th></tr></thead><tbody>` +
    (h.map((a) => `<tr><td>${fmtDT(a.first_seen)}</td><td>${fmtDate(a.date)}</td><td><span class="sev ${a.severity}">${SEV_LABEL[a.severity]}</span></td><td>${esc(a.title)}</td><td><a href="${esc(a.url)}" target="_blank" rel="noopener">${esc(a.source)}</a></td></tr>`).join("") || '<tr><td colspan="5" class="empty">Sin historial.</td></tr>') + "</tbody>";
}

/* ---------------- 6. Compras y logística ---------------- */
const SIM_IDS = () => S.inds.filter((i) => i.unit_norm === "USD/t" && BUY_GROUPS.has(i.group) && i.summary?.last);
function initSim() {
  $("#sim-ind").innerHTML = SIM_IDS().map((i) => `<option value="${i.id}">${esc(i.name)}</option>`).join("");
  fillSimPrice();
}
function fillSimPrice() {
  const i = S.byId[$("#sim-ind").value]; if (!i) return;
  const p = $("#sim-price");
  p.value = i.summary.last.value.toFixed(2); p.classList.remove("user");
  $("#sim-price-src").innerHTML = `<span class="tag auto">Automático</span> ${esc(i.source.label.split(" — ")[0])}, ${fmtDate(i.summary.last.date, i.frequency)} · ${esc(PRICE_TYPE[i.price_type])}`;
}
function landed(price, v) {
  const cfr = price + v.freight, ins = cfr * v.ins / 100, cif = cfr + ins, tariff = cif * v.tariff / 100;
  return { cfr, ins, cif, tariff, total: cif + tariff + v.customs + v.inland + v.other };
}
function renderSim() {
  const i = S.byId[$("#sim-ind").value]; if (!i) { $("#sim-out").innerHTML = '<p class="empty">Dato no disponible</p>'; return; }
  const n = (id) => Math.max(0, parseFloat($(id).value) || 0);
  const v = { freight: n("#sim-freight"), ins: n("#sim-ins"), tariff: n("#sim-tariff"), customs: n("#sim-customs"), inland: n("#sim-inland"), other: n("#sim-other") };
  const price = n("#sim-price"), vol = n("#sim-vol"), r = landed(price, v);
  $("#sim-out").innerHTML = `<div class="big">${fmtNum(r.total, 2)} <small>USD/t</small></div>
    <div class="hint">Costo estimado puesto en planta · total ${fmtNum(r.total * vol, 0)} USD para ${fmtNum(vol, 0)} t</div>
    <div class="kv"><span>Precio internacional ${$("#sim-price").classList.contains("user") ? '<span class="tag user">Usuario</span>' : '<span class="tag auto">Automático</span>'}</span><span>${fmtNum(price, 2)}</span>
    <span>+ Flete marítimo <span class="tag user">Usuario</span></span><span>${fmtNum(v.freight, 2)}</span><span>= CFR</span><span>${fmtNum(r.cfr, 2)}</span>
    <span>+ Seguro (${fmtNum(v.ins, 2)}%)</span><span>${fmtNum(r.ins, 2)}</span><span>= CIF</span><span>${fmtNum(r.cif, 2)}</span>
    <span>+ Arancel (${fmtNum(v.tariff, 1)}%)</span><span>${fmtNum(r.tariff, 2)}</span><span>+ Gastos aduaneros/portuarios</span><span>${fmtNum(v.customs, 2)}</span>
    <span>+ Transporte nacional</span><span>${fmtNum(v.inland, 2)}</span><span>+ Otros</span><span>${fmtNum(v.other, 2)}</span>
    <span class="total">Puesto en planta</span><span class="total">${fmtNum(r.total, 2)}</span></div>
    <p class="hint">El precio de referencia (${esc(PRICE_TYPE[i.price_type])}, ${esc(i.market)}) no equivale a una cotización de proveedor.</p>`;
  const pc = [-20, -10, -5, 0, 5, 10, 20], fc = [-20, 0, 20, 50];
  $("#sim-sens").innerHTML = `<thead><tr><th>Precio \\ Flete</th>${fc.map((f) => `<th class="n">${f > 0 ? "+" : ""}${f}%</th>`).join("")}</tr></thead><tbody>` +
    pc.map((p) => `<tr><td>${p > 0 ? "+" : ""}${p}%</td>${fc.map((f) => `<td class="n">${fmtNum(landed(price * (1 + p / 100), { ...v, freight: v.freight * (1 + f / 100) }).total, 2)}</td>`).join("")}</tr>`).join("") + "</tbody>";
  const sc = i.summary.scenarios?.["90d"];
  $("#sim-scen").innerHTML = sc?.available
    ? `<span class="chip scen">Escenario estadístico</span> Con rendimientos históricos a 90 días, el precio de referencia se ubicó entre ${fmtPct(sc.p10_pct)} (P10) y ${fmtPct(sc.p90_pct)} (P90). Costo puesto en planta equivalente: ${fmtNum(landed(price * (1 + sc.p10_pct / 100), v).total, 2)} – ${fmtNum(landed(price * (1 + sc.p90_pct / 100), v).total, 2)} USD/t. No es un pronóstico.`
    : `Escenario a 90 días no disponible: ${esc(sc?.reason || "datos insuficientes")}.`;
}

function renderBasket() {
  const ids = SIM_IDS().map((i) => i.id);
  const saved = store.get("basket", null);
  const form = $("#basket");
  if (!form.children.length) {
    const def = { maiz: 45, harina_soya: 25, ddgs: 10, aceite_soya: 10, aceite_palma: 10 };
    form.innerHTML = ids.map((id) => `<div class="f"><label for="bw-${id}">${esc(S.byId[id].name.split(" (")[0])}</label><input type="number" min="0" step="1" id="bw-${id}" data-bw="${id}" value="${(saved || def)[id] ?? 0}"></div>`).join("");
  }
  const w = Object.fromEntries(ids.map((id) => [id, Math.max(0, parseFloat($(`#bw-${id}`)?.value) || 0)]));
  const tot = Object.values(w).reduce((a, b) => a + b, 0);
  if (!tot) { $("#basket-out").textContent = "Asigne al menos una ponderación."; chart($("#ch-basket"))?.clear(); return; }
  // Se trabaja con el último valor de cada mes para combinar frecuencias distintas
  const [from, to] = periodRange();
  const monthly = {};
  ids.filter((id) => w[id]).forEach((id) => { const s = slice(id, addDays(from, -31), to); monthly[id] = {}; s.dates.forEach((d, k) => { monthly[id][d.slice(0, 7)] = s.values[k]; }); });
  const months = [...new Set(Object.values(monthly).flatMap((m) => Object.keys(m)))].sort().filter((m) => Object.keys(monthly).every((id) => monthly[id][m] != null));
  if (months.length < 2) { $("#basket-out").textContent = "Periodo demasiado corto para la canasta (requiere al menos 2 meses con datos de todos los componentes). Amplíe el periodo."; chart($("#ch-basket"))?.clear(); return; }
  const m0 = months[0];
  const idx = months.map((m) => Object.keys(monthly).reduce((acc, id) => acc + (w[id] / tot) * (monthly[id][m] / monthly[id][m0]) * 100, 0));
  const contrib = Object.keys(monthly).map((id) => ({ id, c: (w[id] / tot) * (monthly[id][months.at(-1)] / monthly[id][m0] - 1) * 100 })).sort((a, b) => Math.abs(b.c) - Math.abs(a.c));
  const opt = baseOpt(); opt.xAxis.data = months.map((m) => fmtDate(m + "-01", "mensual"));
  opt.series = [{ name: "Canasta", type: "line", data: idx.map((x) => +x.toFixed(2)), symbol: "circle", symbolSize: 4, lineStyle: { color: css("--accent"), width: 2 }, itemStyle: { color: css("--accent") }, areaStyle: { color: css("--accent"), opacity: 0.07 } }];
  opt.tooltip.valueFormatter = (v) => fmtNum(v, 1); opt.yAxis.name = "base 100";
  chart($("#ch-basket"))?.setOption(opt, true);
  $("#basket-out").innerHTML = `Variación de la canasta en el periodo: <b class="pct ${pctClass(idx.at(-1) - 100, "agricola")}">${fmtPct(idx.at(-1) - 100)}</b>. Aporte por componente: ${contrib.map((c) => `${esc(S.byId[c.id].name.split(" (")[0])} ${fmtPct(c.c)}`).join(" · ")}. Base: último dato de cada mes.`;
  store.set("basket", w);
}

function renderImpact() {
  const rows = [["maiz", "Compras de maíz"], ["soya", "Compras de soya"], ["harina_soya", "Compras de harina de soya"], ["ddgs", "Compras de DDGS"], ["aceite_soya", "Aceites vegetales (soya)"],
    ["aceite_palma", "Aceites vegetales (palma)"], ["diesel_nyh", "Combustibles / transporte terrestre"], ["brent", "Transporte marítimo (búnker)"], ["gscpi", "Disponibilidad y tiempos de importación"]];
  $("#impact").innerHTML = `<thead><tr><th>Rubro</th><th>Indicador</th><th class="n">Último</th><th class="n">Var. periodo</th><th class="n">Var. 12 m</th><th>Tendencia</th><th>Lectura</th><th>Fecha · fuente</th></tr></thead><tbody>` +
    rows.map(([id, rubro]) => { const i = S.byId[id]; if (!i?.summary?.last) return `<tr><td>${rubro}</td><td colspan="7" class="hint">Dato no disponible</td></tr>`;
      const s = i.summary, pc = periodChange(id), c12 = s.changes?.["12m"]?.pct, tr = s.trend?.label;
      let read = "Sin cambio relevante";
      if (id === "gscpi") read = s.last.value >= 1 ? "Presión alta: ampliar lead times" : s.last.value >= 0 ? "Presión moderada" : "Presión baja: buen momento para negociar fletes";
      else if (pc && pc.pct > 5) read = "Presión al alza en costos";
      else if (pc && pc.pct < -5) read = "Alivio de costos / ventana de compra";
      return `<tr><td>${rubro}</td><td>${esc(i.name)}</td><td class="n">${fmtNum(s.last.value)} ${esc(i.unit_norm)}</td><td class="n"><span class="pct ${pctClass(pc?.pct, i.group)}">${fmtPct(pc?.pct)}</span></td>
        <td class="n"><span class="pct ${pctClass(c12, i.group)}">${fmtPct(c12)}</span></td><td>${tr || "—"}</td><td>${read}</td><td>${fmtDate(s.last.date, i.frequency)} · <a href="${esc(i.source.url)}" target="_blank" rel="noopener">${esc(i.source.label.split(" — ")[0])}</a></td></tr>`; }).join("") + "</tbody>";
}

/* ---------------- 7. Noticias ---------------- */
function renderNews() {
  const items = S.news.items || [];
  const cats = [...new Map(items.map((n) => [n.category, n.category_label])).entries()];
  const sel = $("#n-cat"); if (sel.options.length - 1 !== cats.length) sel.innerHTML = '<option value="">Todas las categorías</option>' + cats.map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join("");
  const cat = sel.value;
  const errs = Object.keys(S.news.errors || {});
  $("#news-note").textContent = `Titulares indexados por GDELT (consulta ${fmtDT(S.news.fetched_at)}), ordenados por relevancia para costos, transporte y abastecimiento. Solo se muestran título, medio, fecha y enlace; abra el enlace para leer la nota original.${errs.length ? " Categorías sin respuesta en esta consulta: " + errs.join(", ") + "." : ""}`;
  const list = items.filter((n) => !cat || n.category === cat);
  $("#news-list").innerHTML = list.length ? list.map((n) => `<div class="news"><a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.title)}</a>
      <div class="mt"><span>${fmtDT(n.published)}</span><span>${esc(n.domain)}</span><span>${esc(n.category_label)}</span>${n.country ? `<span>${esc(n.country)}</span>` : ""}</div>
      <div class="why">${esc(n.why)}</div></div>`).join("") : '<p class="empty" style="padding:14px">Sin noticias disponibles en la última consulta.</p>';
}

/* ---------------- Fuentes y calidad ---------------- */
function renderSources() {
  const st = S.status || {};
  const byConn = {};
  S.inds.forEach((i) => { (byConn[i.connector] ||= []).push(i); });
  const src = Object.entries(byConn).map(([k, list]) => {
    const ok = list.filter((i) => i.sync === "actualizado").length;
    const err = list.map((i) => st.indicators?.[i.id]).find((x) => x && !x.ok);
    return `<div class="src-item"><b>${esc(list[0].source.label)}</b><span><span class="dot ${ok === list.length ? "ok" : ok ? "warn" : "err"}" style="display:inline-block"></span> ${ok}/${list.length} series actualizadas</span>
      <span class="hint">${esc(ACCESS[k]?.method)} · ${esc(ACCESS[k]?.cost)}</span>${err ? `<span class="hint">Último error: ${esc(err.error)}</span>` : ""}</div>`;
  });
  const extra = { nhc: "NOAA NHC — ciclones activos", enso: "NOAA CPC — estado ENSO", news: "GDELT — noticias" };
  Object.entries(extra).forEach(([k, l]) => { const s = st.sources?.[k]; src.push(`<div class="src-item"><b>${l}</b><span><span class="dot ${s?.ok ? "ok" : s ? "err" : ""}" style="display:inline-block"></span> ${s ? (s.ok ? "Consultado " + fmtDT(s.at) : "Error " + fmtDT(s.at)) : "Sin consultar"}</span>${s?.error ? `<span class="hint">${esc(s.error)}</span>` : ""}<span class="hint">Gratuito · sin clave</span></div>`); });
  $("#src-status").innerHTML = src.join("");

  $("#src-matrix").innerHTML = `<thead><tr><th>Indicador</th><th>Proveedor</th><th>Serie</th><th>Tipo de precio</th><th>Unidad (orig. → norm.)</th><th>Frecuencia</th><th>Acceso</th><th>Costo</th><th>Último dato</th><th>Estado</th><th>Calidad</th><th>URL</th></tr></thead><tbody>` +
    S.inds.map((i) => `<tr><td>${esc(i.name)}</td><td>${esc(i.source.label)}</td><td>${esc(i.source_key)}</td><td>${esc(PRICE_TYPE[i.price_type])}</td><td>${esc(i.unit)} → ${esc(i.unit_norm)}</td>
      <td>${FREQ_LABEL[i.frequency]}</td><td>${esc(ACCESS[i.connector]?.method)}</td><td>${esc(ACCESS[i.connector]?.cost)}</td><td>${fmtDate(i.summary?.last?.date, i.frequency)}</td><td>${stateChip(i)}</td>
      <td>${i.quality?.issues?.length ? i.quality.issues.map((x) => esc(x.msg)).join("; ") : "OK"}</td><td>${i.source.url ? `<a href="${esc(i.source.url)}" target="_blank" rel="noopener">abrir</a>` : "—"}</td></tr>`).join("") + "</tbody>";

  const cc = S.catalog.cross_checks || {};
  $("#src-cross").innerHTML = Object.keys(cc).length ? Object.entries(cc).map(([id, c]) => c?.error ? `<p class="hint">${esc(S.byId[id]?.name)}: ${esc(c.error)}</p>` : c ? `<div class="row"><span class="name">${esc(S.byId[id]?.name)} (promedio mensual FRED) vs. ${esc(c.reference)}<span class="meta">Meses: ${c.months.join(", ")} · diferencias ${c.diff_pct.map((d) => fmtPct(d)).join(", ")}</span></span><span class="state ${c.ok ? "ok" : "warn"}">${c.ok ? "Consistente" : "Diferencia a revisar"}</span></div>` : "").join("")
    : '<p class="empty">Validación cruzada pendiente de la próxima actualización en línea.</p>';

  const pend = [
    "CME Group / CBOT (futuros en tiempo real): requiere licencia de datos de mercado; no se integra. Las referencias de granos son promedios mensuales del Banco Mundial y precios físicos de USDA AMS.",
    "USDA WASDE / PSD (oferta y demanda): API de USDA FAS con registro; prevista para la fase 2.",
    "Precios puestos en Nicaragua, cotizaciones de proveedores y tarifas locales de energía: deben cargarse desde fuentes internas (no son públicas).",
    "Canal de Panamá y autoridades portuarias: no publican API abierta de restricciones; se monitorean mediante titulares de prensa marcados como señal a confirmar.",
    "Oro y plata diarios: no hay fuente oficial abierta con licencia de redistribución; se usa el promedio mensual del Banco Mundial.",
    ...(S.meta.disabled_indicators || []).map((d) => `${d.name}: ${d.reason}.`),
    ...S.inds.filter((i) => S.status?.indicators?.[i.id]?.kind === "credencial").map((i) => `${i.name}: falta configurar la clave de API en el servidor.`),
  ];
  $("#src-pending").innerHTML = pend.map((p) => `<li>${esc(p)}</li>`).join("");
}

/* ---------------- exportación ---------------- */
function download(rows, name) {
  try {
    if (window.XLSX) {
      const ws = XLSX.utils.aoa_to_sheet(rows), wb = XLSX.utils.book_new();
      XLSX.utils.book_append_sheet(wb, ws, name.slice(0, 30));
      XLSX.writeFile(wb, `${name}.xlsx`);
    } else {
      const csvTxt = "﻿" + rows.map((r) => r.map((c) => `"${String(c ?? "").replace(/"/g, '""')}"`).join(",")).join("\n");
      const a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([csvTxt], { type: "text/csv" })); a.download = `${name}.csv`; a.click();
    }
    toast("Archivo generado");
  } catch (e) { toast("Este entorno no permite descargas: use el enlace publicado del dashboard."); }
}
function exportCards() {
  download([["Indicador", "Grupo", "Tipo", "Mercado", "Último", "Unidad", "Fecha", "Var 7d %", "Var 30d %", "Var 12m %", "Fuente", "URL"],
    ...filtered().map((i) => { const s = i.summary || {}, c = s.changes || {}; return [i.name, GROUP_LABEL[i.group], PRICE_TYPE[i.price_type], i.market, s.last?.value, i.unit_norm, s.last?.date, c["7d"]?.pct, c["30d"]?.pct, c["12m"]?.pct, i.source.label, i.source.url]; })], "commodities");
}
function exportSeries() {
  const i = S.byId[S.detailId]; if (!i) return; const [from, to] = periodRange(); const s = slice(i.id, from, to);
  download([["Fecha", `Valor (${i.unit_norm})`, "Fuente", "URL"], ...s.dates.map((d, k) => [d, s.values[k], i.source.label, i.source.url])], `serie_${i.id}`);
}

/* ---------------- control general ---------------- */
function renderAll() {
  const r = { exec: renderExec, monitor: renderCards, risk: renderRisk, trends: renderTrends, alerts: renderAlerts, procure: () => { renderSim(); renderBasket(); renderImpact(); }, news: renderNews, sources: renderSources };
  renderAlerts();                                       // mantiene el contador al día
  (r[S.tab] || renderExec)();
  setTimeout(resizeAll, 30);
}

function initControls() {
  const srcSel = $("#f-source");
  [...new Map(S.inds.map((i) => [i.connector, i.source.label])).entries()].forEach(([k, l]) => srcSel.insertAdjacentHTML("beforeend", `<option value="${k}">${esc(l)}</option>`));
  S.ack = new Set(store.get("ack", []));
  renderThresholds(); initSim();

  $("#tabs").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    $$("#tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + b.dataset.tab));
    S.tab = b.dataset.tab; store.set("tab", S.tab); renderAll();
  });
  ["#f-group", "#f-freq", "#f-source", "#f-trend", "#f-from", "#f-to"].forEach((s) => $(s).addEventListener("change", renderAll));
  $("#f-period").addEventListener("change", () => { $("#f-custom").hidden = $("#f-period").value !== "custom"; renderAll(); });
  $("#f-search").addEventListener("input", () => { clearTimeout(S._q); S._q = setTimeout(renderAll, 200); });

  $("#cards").addEventListener("click", (e) => {
    if (e.target.closest("[data-stop]")) return;
    const cb = e.target.closest("input[data-cmp]");
    if (cb) { cb.checked ? S.selected.add(cb.dataset.cmp) : S.selected.delete(cb.dataset.cmp); cb.closest(".card").classList.toggle("sel", cb.checked); if (!$("#compare").hidden) renderCompare(); return; }
    const card = e.target.closest(".card"); if (!card) return;
    renderDetail(card.dataset.id); $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  $("#cards").addEventListener("keydown", (e) => { if ((e.key === "Enter" || e.key === " ") && e.target.classList.contains("card")) { e.preventDefault(); renderDetail(e.target.dataset.id); } });
  $("#btn-close-detail").onclick = () => { $("#detail").hidden = true; S.detailId = null; };
  $("#btn-compare").onclick = () => { if (!S.selected.size) { toast("Marque al menos una tarjeta para comparar"); return; } renderCompare(); $("#compare").scrollIntoView({ behavior: "smooth" }); };
  $("#btn-close-compare").onclick = () => { $("#compare").hidden = true; };
  $("#btn-export-cards").onclick = exportCards;
  $("#btn-export-series").onclick = exportSeries;
  $("#btn-export-alerts").onclick = () => download([["Detectada", "Fecha dato", "Severidad", "Alerta", "Evidencia", "Acción", "Fuente", "URL"], ...(S.alertsData.history || []).map((a) => [a.first_seen, a.date, a.severity, a.title, a.evidence, a.action, a.source, a.url])], "historial_alertas");
  $("#btn-export-sources").onclick = () => download([["Indicador", "Proveedor", "Serie", "URL", "Método", "Costo", "Frecuencia", "Unidad original", "Unidad normalizada", "Último dato", "Estado"], ...S.inds.map((i) => [i.name, i.source.label, i.source_key, i.source.url, ACCESS[i.connector]?.method, ACCESS[i.connector]?.cost, i.frequency, i.unit, i.unit_norm, i.summary?.last?.date, i.sync])], "matriz_fuentes");

  $("#r-sev").onchange = renderRisk; $("#r-type").onchange = renderRisk;
  $("#s-ind").onchange = renderTrends;
  $("#a-sev").onchange = renderAlerts; $("#a-hide-ack").onchange = renderAlerts;
  $("#th-form").addEventListener("input", (e) => { const k = e.target.dataset.th; if (!k) return; const v = parseFloat(e.target.value); if (!isNaN(v)) { S.th[k] = v; store.set("thresholds", Object.fromEntries(Object.keys(S.th).map((x) => [x, S.th[x]]))); renderAlerts(); } });
  $("#th-form").addEventListener("click", (e) => { if (e.target.id === "th-reset") { S.th = { ...S.catalog.thresholds }; store.set("thresholds", {}); renderThresholds(); renderAlerts(); } });
  $("#alert-list").addEventListener("click", (e) => { const b = e.target.closest("[data-ack]"); if (!b) return; const id = b.dataset.ack; S.ack.has(id) ? S.ack.delete(id) : S.ack.add(id); store.set("ack", [...S.ack]); renderAlerts(); });

  $("#sim-ind").onchange = () => { fillSimPrice(); renderSim(); };
  $("#sim").addEventListener("input", (e) => { if (e.target.id === "sim-price") { e.target.classList.add("user"); $("#sim-price-src").innerHTML = '<span class="tag user">Usuario</span> valor ingresado manualmente'; } renderSim(); });
  $("#basket").addEventListener("input", renderBasket);

  $("#btn-refresh").onclick = () => load();
  if ($("#btn-print")) $("#btn-print").onclick = () => { $$("#tabs button")[0].click(); setTimeout(() => window.print(), 300); };
  const ar = $("#auto-refresh"); ar.value = String(store.get("auto", 30)); const setAuto = () => { clearInterval(S.timer); const m = +ar.value; if (m) S.timer = setInterval(() => load(), m * 60000); store.set("auto", m); }; ar.onchange = setAuto; setAuto();
  $("#btn-theme").onclick = () => {
    const cur = document.documentElement.dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    document.documentElement.dataset.theme = cur === "dark" ? "light" : "dark"; store.set("theme", document.documentElement.dataset.theme); renderAll();
  };
  matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => renderAll());
  window.addEventListener("resize", () => { clearTimeout(S._r); S._r = setTimeout(resizeAll, 150); });
  document.addEventListener("visibilitychange", () => { if (!document.hidden && S.queriedAt && Date.now() - new Date(S.queriedAt) > 10 * 60000) load(); });

  const tab = store.get("tab", "exec"); const btn = $(`#tabs button[data-tab="${tab}"]`); if (btn && tab !== "exec") btn.click();
}

const th = store.get("theme", null); if (th) document.documentElement.dataset.theme = th;
load(true);
})();
