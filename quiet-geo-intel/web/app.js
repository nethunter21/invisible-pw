/* Quiet Geo Intel — front-end. Vanilla JS, no build step. All data comes from the local
   aggregation server (/api/*), which caches free public feeds. Nothing here fabricates data. */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const h = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = {
  get(k, d) { try { const v = localStorage.getItem("qgi." + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("qgi." + k, JSON.stringify(v)); } catch { } }
};
const ago = (t) => { const s = (Date.now() - new Date(t)) / 1000; if (!isFinite(s)) return "—"; if (s < 60) return Math.max(0, s | 0) + "s"; if (s < 3600) return (s / 60 | 0) + "m"; if (s < 86400) return (s / 3600 | 0) + "h"; return (s / 86400 | 0) + "d"; };
const fmtP = (v) => v == null || !isFinite(v) ? "—" : Math.abs(v) >= 1000 ? v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : Math.abs(v) >= 10 ? v.toFixed(2) : v.toFixed(Math.abs(v) >= 1 ? 3 : 4);
const fmtC = (v) => v == null || !isFinite(v) ? "—" : (v > 0 ? "+" : "") + v.toFixed(2) + "%";
const cls = (v) => v > 0.001 ? "up" : v < -0.001 ? "dn" : "fl";
const LV_COL = { CRITICAL: "#FF3B4E", HIGH: "#F07A2A", ELEVATED: "#F0C03A", WATCH: "#4C8DDB" };
const KIND = { WAR: "WAR", TC: "CYCLONE", EQ: "QUAKE", FL: "FLOOD", VO: "VOLCANO", DR: "DROUGHT", WF: "WILDFIRE", ST: "STORM", LS: "LANDSLIDE", DU: "DUST", TE: "TEMP" };
const KIND_COL = { WAR: "#FF3B4E", TC: "#A371F7", EQ: "#F0A43A", FL: "#39C5CF", VO: "#F07A2A", DR: "#D4A55A", WF: "#FF6A3D", ST: "#58A6FF", LS: "#B08968", DU: "#C9B37E", TE: "#F2495C" };

async function api(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) { let m = "HTTP " + r.status; try { m = (await r.json()).error || m; } catch { } throw new Error(m); }
  return r.json();
}

/* ---------------- state ---------------- */
const S = {
  news: [], nat: [], quotes: {}, status: [], sel: null, filter: store.get("filter", "ALL"),
  newsAt: null, natAt: null, newsErr: null, natErr: null,
  newsHit(re, minScore, hours, themes) {
    const cut = Date.now() - hours * 3600e3;
    const m = this.news.filter(e => new Date(e.time) > cut && e.score >= minScore && re.test(e.region || "") && (!themes || (e.themes || []).some(t => themes.includes(t))));
    return m.length ? { on: true, why: `${m.length} matching event(s) — latest: “${m[0].title.slice(0, 90)}”`, ev: m[0] } : { on: false, why: "No qualifying events in the live feed right now" };
  },
  natHit(kinds, re, minScore) {
    const m = this.nat.filter(e => kinds.includes(e.kind) && e.score >= minScore && re.test(e.region || (re.source === "." ? "x" : "")));
    return m.length ? { on: true, why: `${m.length} active: ${m[0].title.slice(0, 90)}`, ev: m[0] } : { on: false, why: "No qualifying active events" };
  }
};

/* ---------------- symbols & trade links ---------------- */
const TV = { "CL=F": "NYMEX:CL1!", "BZ=F": "ICEEUR:BRN1!", "NG=F": "NYMEX:NG1!", "RB=F": "NYMEX:RB1!", "HO=F": "NYMEX:HO1!", "GC=F": "COMEX:GC1!", "SI=F": "COMEX:SI1!", "HG=F": "COMEX:HG1!", "ZW=F": "CBOT:ZW1!", "ZC=F": "CBOT:ZC1!", "ZS=F": "CBOT:ZS1!", "ZR=F": "CBOT:ZR1!", "KC=F": "ICEUS:KC1!", "SB=F": "ICEUS:SB1!", "CC=F": "ICEUS:CC1!", "TTF=F": "ICEEUR:TFM1!", "LBS=F": "CME:LBR1!", "TIO=F": "SGX:FEF1!", "^VIX": "CBOE:VIX", "^N225": "TVC:NI225", "JPY=X": "FX:USDJPY", "CHF=X": "FX:USDCHF", "DX-Y.NYB": "TVC:DXY", "BTC-USD": "BITSTAMP:BTCUSD", "RHM.DE": "XETR:RHM", "BA.L": "LSE:BA.", "LDO.MI": "MIL:LDO", "SAAB-B.ST": "OMXSTO:SAAB_B", "HAG.DE": "XETR:HAG", "LHA.DE": "XETR:LHA", "HO.PA": "EURONEXT:HO", "AF.PA": "EURONEXT:AF", "MAERSK-B.CO": "OMXCOP:MAERSK_B", "7011.T": "TSE:7011", "012450.KS": "KRX:012450", "SREN.SW": "SIX:SREN", "MUV2.DE": "XETR:MUV2", "EUAD": "CBOE:EUAD" };
const BROKERS = {
  tradingview: { n: "TradingView", u: s => "https://www.tradingview.com/chart/?symbol=" + encodeURIComponent(TV[s] || s) },
  yahoo: { n: "Yahoo Finance", u: s => "https://finance.yahoo.com/quote/" + encodeURIComponent(s) },
  etoro: { n: "eToro", u: s => "https://www.etoro.com/markets/" + encodeURIComponent(s.replace(/[=^].*$/, "").replace(/\..*$/, "").toLowerCase()) },
  robinhood: { n: "Robinhood", u: s => "https://robinhood.com/us/en/stocks/" + encodeURIComponent(s) },
  webull: { n: "Webull", u: s => "https://www.webull.com/quote/" + encodeURIComponent(s.toLowerCase()) },
  ibkr: { n: "IBKR", u: s => "https://www.interactivebrokers.com/" },
  custom: { n: "My broker", u: s => (store.get("brokerTpl", "https://www.tradingview.com/chart/?symbol={sym}")).replace("{sym}", encodeURIComponent(s)) },
};
const tradeLinks = (s) => {
  const b = BROKERS[store.get("broker", "tradingview")] || BROKERS.tradingview;
  return `<a class="lnk go" target="_blank" href="${b.u(s)}">Trade ${h(s)} ↗</a><a class="lnk tv" target="_blank" href="${BROKERS.tradingview.u(s)}">TradingView</a><a class="lnk" target="_blank" href="${BROKERS.yahoo.u(s)}">Yahoo</a>`;
};
const NAMES = { "CL=F": "WTI Crude", "BZ=F": "Brent Crude", "NG=F": "Henry Hub Gas", "TTF=F": "Dutch TTF Gas", "RB=F": "RBOB Gasoline", "HO=F": "Heating Oil", "GC=F": "Gold", "SI=F": "Silver", "HG=F": "Copper", "ZW=F": "Wheat", "ZC=F": "Corn", "ZS=F": "Soybeans", "ZR=F": "Rough Rice", "KC=F": "Coffee", "SB=F": "Sugar #11", "CC=F": "Cocoa", "LBS=F": "Lumber", "TIO=F": "Iron Ore", "^VIX": "VIX", "^N225": "Nikkei 225", "JPY=X": "USD/JPY", "CHF=X": "USD/CHF", "DX-Y.NYB": "US Dollar Index", "BTC-USD": "Bitcoin" };

const GROUPS = {
  "Defense US": ["ITA", "XAR", "LMT", "RTX", "NOC", "GD", "LHX", "HII", "KTOS", "AVAV", "PLTR", "BA"],
  "Defense EU/Asia": ["EUAD", "RHM.DE", "BA.L", "LDO.MI", "SAAB-B.ST", "HAG.DE", "HO.PA", "ESLT", "7011.T", "012450.KS"],
  "Energy": ["CL=F", "BZ=F", "NG=F", "TTF=F", "RB=F", "HO=F", "XLE", "XOM", "CVX", "USO", "UNG"],
  "Safe Havens": ["GC=F", "SI=F", "TLT", "^VIX", "DX-Y.NYB", "JPY=X", "CHF=X", "BTC-USD"],
  "Shipping": ["ZIM", "MAERSK-B.CO", "FRO", "STNG", "BDRY"],
  "Agriculture": ["ZW=F", "ZC=F", "ZS=F", "ZR=F", "KC=F", "SB=F", "CC=F", "DBA", "WEAT"],
  "Semis": ["TSM", "SOXX", "SMH", "MU", "NVDA"],
  "Cyber": ["CIBR", "CRWD", "PANW", "FTNT", "ZS"],
  "Insurance & Rebuild": ["TRV", "ALL", "CB", "RNR", "HD", "LOW", "GNRC"],
  "Macro": ["SPY", "QQQ", "^N225", "EWJ", "FXI", "INDA", "EWY", "EUFN", "JETS", "HG=F"],
};
const TAPE = ["CL=F", "BZ=F", "NG=F", "GC=F", "^VIX", "ITA", "LMT", "RTX", "NOC", "RHM.DE", "ZW=F", "TSM", "SPY", "DX-Y.NYB", "BTC-USD", "FRO", "ZIM", "KC=F", "CC=F"];

/* ---------------- tabs ---------------- */
const TABS = [["terminal", "TERMINAL"], ["war", "WAR ROOM"], ["map", "WEATHER MAP"], ["cyclone", "CYCLONES"], ["markets", "MARKETS"], ["predict", "PREDICT"], ["forecast", "FORECAST"], ["strategies", "STRATEGIES"], ["alerts", "ALERTS"], ["sources", "SOURCES"]];
const onShow = {};
function showTab(id) {
  $$("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.t === id));
  $$(".view").forEach(v => v.classList.toggle("on", v.id === "v-" + id));
  store.set("tab", id);
  onShow[id] && onShow[id]();
  setTimeout(() => window.dispatchEvent(new Event("resize")), 30);
}
$("#tabs").innerHTML = TABS.map(([id, n], i) => `<button data-t="${id}">${n}<kbd>${(i + 1) % 10}</kbd>${id === "war" ? '<span class="bdg" id="warbdg" hidden></span>' : ""}</button>`).join("");
$("#tabs").onclick = e => { const b = e.target.closest("button"); b && showTab(b.dataset.t); };

/* ---------------- clocks ---------------- */
function tick() {
  const d = new Date();
  $("#utc").textContent = d.toISOString().slice(11, 19);
  $("#loc").textContent = d.toLocaleTimeString([], { hour12: false });
}
setInterval(tick, 1000); tick();

/* ---------------- sound & notifications ---------------- */
let actx = null;
const ensureAudio = () => { try { actx = actx || new (window.AudioContext || window.webkitAudioContext)(); if (actx.state === "suspended") actx.resume(); } catch { } };
document.addEventListener("pointerdown", ensureAudio, { once: false });
function tone(freq, start, dur, type = "sine", vol = 0.2) {
  const o = actx.createOscillator(), g = actx.createGain();
  o.type = type; o.frequency.setValueAtTime(freq, actx.currentTime + start);
  g.gain.setValueAtTime(0.0001, actx.currentTime + start);
  g.gain.exponentialRampToValueAtTime(vol, actx.currentTime + start + 0.02);
  g.gain.exponentialRampToValueAtTime(0.0001, actx.currentTime + start + dur);
  o.connect(g).connect(actx.destination); o.start(actx.currentTime + start); o.stop(actx.currentTime + start + dur + 0.05);
}
function playAlert(level) {
  if (!store.get("sound", true)) return;
  ensureAudio(); if (!actx) return;
  const v = store.get("vol", 0.6) * 0.35;
  if (level === "CRITICAL") { for (let i = 0; i < 3; i++) { tone(880, i * 0.42, 0.2, "sawtooth", v); tone(660, i * 0.42 + 0.2, 0.2, "sawtooth", v); } }
  else if (level === "HIGH") { tone(988, 0, 0.14, "square", v * 0.7); tone(1319, 0.17, 0.22, "square", v * 0.7); }
  else { tone(1175, 0, 0.25, "sine", v); tone(1568, 0.12, 0.3, "sine", v * 0.7); }
}
const SPK_ON = '<svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9Zm13.5 3A4.5 4.5 0 0 0 14 8v8a4.5 4.5 0 0 0 2.5-4ZM14 3.2v2.1a7 7 0 0 1 0 13.4v2.1a9 9 0 0 0 0-17.6Z"/></svg>';
const SPK_OFF = '<svg viewBox="0 0 24 24"><path d="M3 9v6h4l5 5V4L7 9Zm18.7 3-2.6-2.6-1.4 1.4L20.3 12l-2.6 2.6 1.4 1.4 2.6-2.6 2.6 2.6 1.4-1.4L23.1 12Z" transform="translate(-3 0)"/></svg>';
function renderSound() { const on = store.get("sound", true); $("#snd").innerHTML = on ? SPK_ON : SPK_OFF; $("#snd").classList.toggle("on", on); $("#snd").title = "Sound alerts " + (on ? "ON" : "OFF") + " (S)"; const c = $("#cfg-sound"); if (c) c.classList.toggle("on", on); }
function toggleSound() { store.set("sound", !store.get("sound", true)); renderSound(); if (store.get("sound", true)) { ensureAudio(); playAlert("ELEVATED"); } }
$("#snd").onclick = toggleSound; renderSound();
function renderNtf() { $("#ntf").classList.toggle("on", store.get("notify", false) && "Notification" in window && Notification.permission === "granted"); }
$("#ntf").onclick = async () => {
  if (!("Notification" in window)) return toast({ level: "WATCH", title: "Desktop notifications not supported in this browser" });
  if (Notification.permission !== "granted") { const p = await Notification.requestPermission(); store.set("notify", p === "granted"); }
  else store.set("notify", !store.get("notify", false));
  renderNtf();
};
renderNtf();
$("#fs").onclick = () => document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
$("#bell").onclick = () => showTab("alerts");

/* ---------------- toasts & alert engine ---------------- */
function toast(a, sticky) {
  const d = document.createElement("div");
  d.className = "toast " + (a.level || "");
  const assets = (a.assets || []).slice(0, 4).map(x => `<span class="tk" data-s="${h(x.s)}">${h(x.s)} <span class="dir ${x.d}">${x.d === "up" ? "▲" : x.d === "down" ? "▼" : "◆"}</span></span>`).join(" ");
  d.innerHTML = `<span class="x">✕</span><span class="lv ${a.level}">${a.level}</span> <span class="kd">${h(KIND[a.kind] || a.kind || "")}</span> <span class="mut">${h(a.region || a.source || "")}</span>
  <div class="t">${h(a.title)}</div>${assets ? `<div class="links" style="margin-bottom:6px">${assets}</div>` : ""}
  ${a.id ? `<div class="links"><button class="lnk go" data-open="${h(a.id)}">Open intel →</button>${a.assets && a.assets[0] ? `<a class="lnk" target="_blank" href="${BROKERS[store.get("broker", "tradingview")]?.u(a.assets[0].s)}">Trade ${h(a.assets[0].s)} ↗</a>` : ""}${a.link ? `<a class="lnk" target="_blank" href="${h(a.link)}">Source ↗</a>` : ""}</div>` : ""}`;
  d.onclick = (e) => {
    if (e.target.classList.contains("x")) return d.remove();
    const o = e.target.dataset.open; if (o) { openEvent(o); d.remove(); }
    const s = e.target.closest(".tk")?.dataset.s; if (s) { showTab("terminal"); loadChart(TC, s); }
  };
  $("#toasts").prepend(d);
  while ($("#toasts").children.length > 5) $("#toasts").lastChild.remove();
  if (!sticky) setTimeout(() => d.remove(), a.level === "CRITICAL" ? 45000 : 15000);
}
const LVN = { WATCH: 0, ELEVATED: 35, HIGH: 60, CRITICAL: 80 };
const defaultCfg = { warMin: 60, natMin: 60, kinds: { WAR: true, TC: true, EQ: true, FL: true, VO: true, DR: true, WF: false, ST: false }, keywords: "", priceMove: 0, regions: "" };
const cfg = () => Object.assign({}, defaultCfg, store.get("alertcfg", {}));
let seen = new Set(store.get("seen", []));
let firstRun = !store.get("seenInit", false);
let unread = store.get("unread", 0);
function setUnread(n) { unread = n; store.set("unread", n); $("#bellc").textContent = n || ""; $("#bellc").dataset.z = n ? 0 : 1; }
setUnread(unread);
function pushHist(e) {
  const hist = store.get("hist", []);
  hist.unshift({ id: e.id, t: Date.now(), level: e.level, kind: e.kind, title: e.title, region: e.region, assets: (e.assets || []).slice(0, 6), link: e.link, source: e.source });
  store.set("hist", hist.slice(0, 300));
  if (onShow.alerts && $("#v-alerts").classList.contains("on")) renderHist();
}
function matchesRules(e) {
  const c = cfg();
  if (!c.kinds[e.kind]) return false;
  const min = e.kind === "WAR" ? c.warMin : c.natMin;
  let ok = e.score >= min;
  if (c.keywords.trim()) {
    const kw = c.keywords.split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
    if (kw.some(k => (e.title + " " + (e.summary || "")).toLowerCase().includes(k))) ok = true;
  }
  if (ok && c.regions.trim()) {
    const rg = c.regions.split(",").map(s => s.trim().toLowerCase()).filter(Boolean);
    ok = rg.some(r => ((e.region || "") + " " + e.title + " " + (e.country || "")).toLowerCase().includes(r));
  }
  return ok;
}
function processAlerts(events) {
  const fresh = [];
  for (const e of events) {
    if (seen.has(e.id)) continue;
    seen.add(e.id);
    if (!matchesRules(e)) continue;
    if (Date.now() - new Date(e.updated || e.time) > 12 * 3600e3 && !firstRun) continue;
    fresh.push(e);
  }
  store.set("seen", [...seen].slice(-4000));
  if (!fresh.length) return;
  fresh.sort((a, b) => b.score - a.score);
  fresh.forEach(pushHist);
  if (firstRun) return; // first launch: populate history silently
  setUnread(unread + fresh.length);
  fresh.slice(0, 3).forEach(e => toast(e));
  const top = fresh[0];
  playAlert(top.level);
  if (store.get("notify", false) && "Notification" in window && Notification.permission === "granted") {
    try { const n = new Notification(`${top.level} · ${KIND[top.kind] || top.kind}${top.region ? " · " + top.region : ""}`, { body: top.title + (top.assets?.length ? "\nWatch: " + top.assets.slice(0, 4).map(a => a.s).join(", ") : ""), icon: "logo.svg", tag: top.id }); n.onclick = () => { window.focus(); openEvent(top.id); }; } catch { }
  }
}

/* ---------------- polling ---------------- */
async function pollNews() {
  try { const d = await api("/api/news"); S.news = d.events || []; S.newsAt = d.generated; S.newsErr = null; }
  catch (e) { S.newsErr = e.message; }
  afterData();
  processAlerts(S.news); checkFirst();
}
async function pollNat() {
  try { const d = await api("/api/natural"); S.nat = d.events || []; S.natAt = d.generated; S.natErr = null; }
  catch (e) { S.natErr = e.message; }
  afterData();
  processAlerts(S.nat); checkFirst(); renderWMapEvents && wmap && renderWMapEvents();
}
function universe() {
  const u = new Set(TAPE);
  [...S.news, ...S.nat].forEach(e => (e.assets || []).forEach(a => u.add(a.s)));
  const g = store.get("wlgroup", "Defense US"); (GROUPS[g] || []).forEach(s => u.add(s));
  Object.keys(store.get("paper", { pos: {} }).pos || {}).forEach(s => u.add(s));
  STRATS.forEach(st => { if (st.id === store.get("strat")) st.markets.forEach(s => /^[A-Z0-9^=.\-]+$/.test(s) && u.add(s)); });
  return [...u].slice(0, 120);
}
let quoteErr = null;
async function pollQuotes(extra = []) {
  try {
    const q = await api("/api/spark?symbols=" + encodeURIComponent([...new Set([...universe(), ...extra])].join(",")));
    const prev = S.quotes; S.quotes = Object.assign({}, S.quotes, q); quoteErr = null;
    const pm = cfg().priceMove;
    if (pm > 0) for (const [s, v] of Object.entries(q)) {
      const k = "pm:" + s + ":" + new Date().toISOString().slice(0, 10) + ":" + Math.trunc(v.chgPct / pm);
      if (Math.abs(v.chgPct) >= pm && !seen.has(k) && prev[s]) { seen.add(k); const e = { id: k, kind: "PRICE", level: Math.abs(v.chgPct) >= pm * 2 ? "HIGH" : "ELEVATED", title: `${s} ${NAMES[s] || v.name || ""} moved ${fmtC(v.chgPct)} today (${fmtP(v.price)})`, assets: [{ s, d: v.chgPct > 0 ? "up" : "down" }], score: 50 }; pushHist(e); toast(e); playAlert(e.level); setUnread(unread + 1); }
    }
  } catch (e) { quoteErr = e.message; }
  renderTape(); renderIntel(); renderWL(); renderPaper(); updChartPx();
}
async function pollStatus() { try { S.status = await api("/api/status"); } catch { } renderFeedStat(); if ($("#v-sources").classList.contains("on")) renderSources(); }
function afterData() {
  renderFeed(); renderTMap(); renderIntel(); renderThreat();
  if ($("#v-war").classList.contains("on")) renderWar();
  if ($("#v-strategies").classList.contains("on")) renderStrats();
}
function checkFirst() { if (firstRun && S.newsAt && S.natAt) { firstRun = false; store.set("seenInit", true); } }
function renderFeedStat() {
  const ok = S.status.filter(s => s.ok).length, n = S.status.length;
  const c = !n ? "" : ok === n ? "ok" : ok >= n * 0.6 ? "warn" : "bad";
  $("#feedstat").innerHTML = `<i class="dot ${c}"></i>${ok}/${n} LIVE`;
}
function renderThreat() {
  const cut = Date.now() - 6 * 3600e3;
  const rec = S.news.filter(e => new Date(e.time) > cut);
  const mx = rec.reduce((m, e) => Math.max(m, e.score), 0);
  const lvl = mx >= 80 ? "CRITICAL" : mx >= 60 ? "HIGH" : mx >= 35 ? "ELEVATED" : "WATCH";
  $("#threat").innerHTML = S.newsAt ? `<span class="lv ${lvl}">${lvl}</span> ${mx}` : "—";
  const hi = rec.filter(e => e.score >= 60).length; const b = $("#warbdg"); if (b) { b.hidden = !hi; b.textContent = hi; }
}

/* ---------------- ticker tape ---------------- */
function renderTape() {
  const it = TAPE.map(s => { const q = S.quotes[s]; return q ? `<span data-s="${s}"><b>${NAMES[s] || s}</b>${fmtP(q.price)} <span class="${cls(q.chgPct)}">${fmtC(q.chgPct)}</span></span>` : ""; }).join("");
  $("#tapein").innerHTML = it ? it + it : `<span class="mut">${quoteErr ? "Market data unavailable: " + h(quoteErr) : "Loading market data…"}</span>`;
}
$("#tape").onclick = e => { const s = e.target.closest("[data-s]")?.dataset.s; if (s) { showTab("terminal"); loadChart(TC, s); } };

/* ================= TERMINAL ================= */
const FILTERS = ["ALL", "WAR", "TC", "EQ", "FL", "VO", "DR", "WF", "ST"];
function allEvents() { return [...S.news, ...S.nat]; }
function renderFeed() {
  const all = allEvents();
  const counts = {}; all.forEach(e => counts[e.kind] = (counts[e.kind] || 0) + 1);
  $("#evfilter").innerHTML = FILTERS.map(f => `<button class="chip ${S.filter === f ? "on" : ""}" data-f="${f}">${f === "ALL" ? "ALL" : KIND[f]}<i>${f === "ALL" ? all.length : counts[f] || 0}</i></button>`).join("");
  const min = +$("#evlevel").value, sort = $("#evsort").value;
  let list = all.filter(e => (S.filter === "ALL" || e.kind === S.filter) && e.score >= min);
  if (sort === "score") list.sort((a, b) => b.score - a.score);
  else if (sort === "trade") list.sort((a, b) => ((b.assets || []).length * 5 + b.score) - ((a.assets || []).length * 5 + a.score));
  else list.sort((a, b) => new Date(b.updated || b.time) - new Date(a.updated || a.time));
  $("#evcount").textContent = list.length + " events";
  const err = [S.newsErr && "Conflict wire: " + S.newsErr, S.natErr && "Hazards: " + S.natErr].filter(Boolean);
  $("#evlist").innerHTML = (err.length ? `<div class="unavail">${err.map(h).join("<br>")}</div>` : "") + (list.length ? list.slice(0, 300).map(evRow).join("") : `<div class="empty">${S.newsAt || S.natAt ? "No events match this filter." : "Connecting to live feeds…"}</div>`);
}
function evRow(e) {
  return `<div class="ev ${S.sel?.id === e.id ? "sel" : ""}" data-id="${h(e.id)}"><div class="bar c-${e.level}"></div><div>
  <div class="t">${h(e.title)}</div>
  <div class="m"><span class="lv ${e.level}">${e.level} ${e.score}</span><span class="kd" style="color:${KIND_COL[e.kind] || "#39C5CF"}">${KIND[e.kind] || e.kind}</span>${e.region ? `<span>${h(e.region)}</span>` : e.country ? `<span>${h(e.country)}</span>` : ""}<span>${h(e.source)}</span><span>${ago(e.updated || e.time)} ago</span>${(e.assets || []).length ? `<span style="color:#58A6FF">${e.assets.length} assets</span>` : ""}</div></div></div>`;
}
$("#evfilter").onclick = e => { const f = e.target.closest(".chip")?.dataset.f; if (f) { S.filter = f; store.set("filter", f); renderFeed(); renderTMap(); } };
$("#evsort").onchange = renderFeed; $("#evlevel").onchange = () => { renderFeed(); renderTMap(); };
$("#evlist").onclick = e => { const id = e.target.closest(".ev")?.dataset.id; if (id) selectEvent(id, true); };

function findEvent(id) { return allEvents().find(e => e.id === id) || store.get("hist", []).find(e => e.id === id); }
function openEvent(id) { showTab("terminal"); selectEvent(id, true); }
function selectEvent(id, fly) {
  const e = findEvent(id); if (!e) return;
  S.sel = e;
  $$("#evlist .ev").forEach(r => r.classList.toggle("sel", r.dataset.id === id));
  if (fly && e.lat != null && tmap) tmap.flyTo([e.lat, e.lon], Math.max(tmap.getZoom(), 4), { duration: 0.8 });
  if (e.assets?.length) loadChart(TC, e.assets[0].s); else drawMarkers(TC);
  renderIntel();
}

/* map */
let tmap, tLayer, tBase;
const REGIONS = { Global: [[20, 15], 2], "N. America": [[40, -98], 3], "S. America": [[-16, -60], 3], Europe: [[50, 18], 4], "Middle East": [[28, 46], 5], Africa: [[4, 20], 3], Asia: [[30, 108], 3], Oceania: [[-24, 145], 4], Atlantic: [[24, -50], 3], Pacific: [[12, 170], 3], Indian: [[-8, 78], 3] };
const GIBS_B = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/";
function labelsLayer() { return L.tileLayer(GIBS_B + "Reference_Labels_15m/default/default/GoogleMapsCompatible_Level13/{z}/{y}/{x}.png", { maxNativeZoom: 13, maxZoom: 14, opacity: 0.75, pane: "shadowPane", className: "bm-lab" }); }
function baseTiles(m, labels = true) {
  L.tileLayer(GIBS_B + "OSM_Land_Water_Map/default/default/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png", { maxNativeZoom: 9, maxZoom: 14, className: "bm-land", attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · <a href="https://earthdata.nasa.gov/gibs">NASA GIBS</a>' }).addTo(m);
  L.tileLayer(GIBS_B + "Reference_Features_15m/default/default/GoogleMapsCompatible_Level13/{z}/{y}/{x}.png", { maxNativeZoom: 13, maxZoom: 14, opacity: 0.35, className: "bm-ref" }).addTo(m);
  if (labels) labelsLayer().addTo(m);
}
function mkMap(el, center = [22, 20], z = 2) {
  const m = L.map(el, { worldCopyJump: true, zoomControl: true, minZoom: 2, preferCanvas: true, attributionControl: true }).setView(center, z);
  baseTiles(m);
  return m;
}
const TOV = Object.assign({ radar: false, sst: false, chokepoints: true, energy: false, nuclear: false, bases: false, pipelines: false }, store.get("tov", {}));
function initTerminal() {
  tmap = mkMap("tmap");
  tLayer = L.layerGroup().addTo(tmap);
  $("#regionseg").innerHTML = Object.keys(REGIONS).map(r => `<button data-r="${r}">${r}</button>`).join("");
  $("#regionseg").onclick = e => { const r = e.target.dataset.r; if (r) { tmap.flyTo(...REGIONS[r], { duration: 0.7 }); $$("#regionseg button").forEach(b => b.classList.toggle("on", b === e.target)); } };
  const opts = { radar: "Radar", sst: "Sea temp", chokepoints: "Chokepoints", energy: "Energy", pipelines: "Pipelines", nuclear: "Nuclear", bases: "Bases" };
  const GROUPK = { energy: ["oilterminals", "refineries", "lng"], pipelines: ["pipelines"], nuclear: ["nuclear", "nukeweapons"], bases: ["bases"] };
  const tl = {};
  const draw = () => {
    $("#tlayers").innerHTML = Object.entries(opts).map(([k, n]) => `<button data-k="${k}" class="${TOV[k] ? "on" : ""}">${n}</button>`).join("");
    if (TOV.radar && !tl.radar) radarLayer().then(l => { if (l && TOV.radar) { tl.radar = l.addTo(tmap); } });
    if (!TOV.radar && tl.radar) { tmap.removeLayer(tl.radar); tl.radar = null; }
    if (TOV.sst && !tl.sst) tl.sst = gibs("GHRSST_L4_MUR_Sea_Surface_Temperature", 7, 0.55).addTo(tmap);
    if (!TOV.sst && tl.sst) { tmap.removeLayer(tl.sst); tl.sst = null; }
    if (TOV.chokepoints && !tl.ch) tl.ch = geoLayer("chokepoints").addTo(tmap);
    if (!TOV.chokepoints && tl.ch) { tmap.removeLayer(tl.ch); tl.ch = null; }
    Object.entries(GROUPK).forEach(([k, kinds]) => {
      if (TOV[k] && !tl[k]) tl[k] = L.layerGroup(kinds.map(geoLayer)).addTo(tmap);
      if (!TOV[k] && tl[k]) { tmap.removeLayer(tl[k]); tl[k] = null; }
    });
    store.set("tov", TOV);
  };
  $("#tlayers").onclick = e => { const k = e.target.dataset.k; if (k) { TOV[k] = !TOV[k]; draw(); } };
  draw();
  $("#tlegend").innerHTML = Object.entries(LV_COL).map(([k, c]) => `<div class="lg"><i class="sw" style="background:${c}"></i>${k}</div>`).join("") + `<div class="note" style="margin-top:4px">Size = severity · ◆ = conflict hotspot</div>`;
}
function evMarker(e, onClick) {
  const col = LV_COL[e.level];
  let mk;
  if (e.kind === "WAR") {
    const sz = 10 + e.score / 8;
    mk = L.marker([e.lat, e.lon], { icon: L.divIcon({ className: "", html: `<div class="${e.score >= 60 ? "pulse" : ""}" style="color:${col};width:${sz}px;height:${sz}px;transform:rotate(45deg);background:${col};box-shadow:0 0 10px ${col};border:1px solid #000"></div>`, iconSize: [sz, sz] }) });
  } else {
    mk = L.circleMarker([e.lat, e.lon], { radius: e.kind === "WF" ? 3 : 4 + e.score / 14, color: KIND_COL[e.kind] || col, weight: e.score >= 60 ? 2 : 1, fillColor: col, fillOpacity: 0.75 });
  }
  mk.bindTooltip(`<b>${h(KIND[e.kind] || e.kind)}</b> · <span style="color:${col}">${e.level}</span><br>${h(e.title.slice(0, 110))}`, { direction: "top" });
  mk.on("click", () => onClick(e));
  return mk;
}
function jitter(list) {
  const groups = {};
  return list.map(e => { const k = e.lat + "," + e.lon; const n = groups[k] = (groups[k] || 0) + 1; if (e.kind !== "WAR" || n === 1) return e; const a = n * 2.4, r = 0.9 + n * 0.25; return Object.assign({}, e, { lat: e.lat + Math.sin(a) * r, lon: e.lon + Math.cos(a) * r }); });
}
function renderTMap() {
  if (!tmap) return;
  tLayer.clearLayers();
  const min = +$("#evlevel").value;
  const list = jitter(allEvents().filter(e => e.lat != null && isFinite(e.lat) && (S.filter === "ALL" || e.kind === S.filter) && e.score >= min).sort((a, b) => a.score - b.score));
  list.forEach(e => evMarker(e, x => selectEvent(x.id, false)).addTo(tLayer));
}

/* intel panel */
function qcell(s) { const q = S.quotes[s]; return q ? `<span>${fmtP(q.price)}</span>` : `<span class="mut">—</span>`; }
function renderIntel() {
  const e = S.sel;
  if (!e) {
    const top = [...S.news].filter(x => Date.now() - new Date(x.time) < 24 * 3600e3).sort((a, b) => b.score - a.score).slice(0, 6);
    const tn = [...S.nat].sort((a, b) => b.score - a.score).slice(0, 4);
    $("#intel").innerHTML = `<div class="sec"><h4>GLOBAL BRIEF</h4><p class="note" style="font-size:11px;color:#9aa8bb">Select any event in the feed or on the map to see mapped tradable assets, live prices, linked strategies and one-click trade links.</p></div>
    <div class="sec"><h4>TOP GEOPOLITICAL · 24H</h4>${top.length ? top.map(x => `<div class="ev" data-id="${h(x.id)}" style="padding:6px 0;grid-template-columns:4px 1fr"><div class="bar c-${x.level}"></div><div><div class="t" style="font-size:11.5px">${h(x.title)}</div><div class="m"><span class="lv ${x.level}">${x.score}</span><span>${h(x.region || "")}</span><span>${ago(x.time)}</span></div></div></div>`).join("") : `<div class="mut">${S.newsErr ? "Conflict wire unavailable: " + h(S.newsErr) : "Loading…"}</div>`}</div>
    <div class="sec"><h4>TOP NATURAL HAZARDS</h4>${tn.map(x => `<div class="ev" data-id="${h(x.id)}" style="padding:6px 0;grid-template-columns:4px 1fr"><div class="bar c-${x.level}"></div><div><div class="t" style="font-size:11.5px">${h(x.title)}</div><div class="m"><span class="lv ${x.level}">${x.score}</span><span class="kd">${KIND[x.kind]}</span><span>${h(x.source)}</span></div></div></div>`).join("") || '<div class="mut">—</div>'}</div>
    <div class="sec"><h4>KEY MARKETS</h4>${["CL=F", "BZ=F", "GC=F", "^VIX", "ITA", "NG=F", "ZW=F", "TSM"].map(s => assetRow({ s, d: "", why: NAMES[s] || "" })).join("")}</div>`;
    return;
  }
  const strat = (e.strategies || []).map(id => STRATS.find(s => s.id === id)).filter(Boolean);
  if (e.kind === "WAR" && /Russia|Europe/.test(e.region || "") && !strat.find(s => s.id === "war-eu")) strat.push(STRATS.find(s => s.id === "war-eu"));
  if (e.kind === "WAR" && /Taiwan|China/.test(e.region || "") && !strat.find(s => s.id === "war-taiwan")) strat.push(STRATS.find(s => s.id === "war-taiwan"));
  const det = Object.entries(e.details || {}).filter(([k, v]) => v && k !== "Graphics" && k !== "Current");
  const col = LV_COL[e.level];
  $("#intelsrc").textContent = e.source;
  $("#intel").innerHTML = `
  <div class="sec"><div style="display:flex;gap:6px;align-items:center"><span class="lv ${e.level}">${e.level}</span><span class="kd" style="color:${KIND_COL[e.kind]}">${KIND[e.kind] || e.kind}</span><span class="mut">${h(e.region || e.country || "")}</span><button class="btn sm" style="margin-left:auto" id="intelclose">✕</button></div>
   <h3>${h(e.title)}</h3>${e.summary ? `<p class="note" style="font-size:11px;color:#9aa8bb">${h(e.summary)}</p>` : ""}
   <div class="kv" style="margin-top:8px"><span>Reported</span><b>${new Date(e.time).toUTCString().slice(5, 22)} UTC · ${ago(e.time)} ago</b><span>Source</span><b>${h(e.source)}</b>${det.map(([k, v]) => `<span>${h(k)}</span><b>${h(v)}</b>`).join("")}</div>
   ${(e.themes || []).length ? `<div class="links" style="margin-top:8px">${e.themes.map(t => `<span class="pill" style="${t === "DE-ESCALATION" ? "color:#2BD67B;border-color:#1d5a3a" : ""}">${t}</span>`).join("")}</div>` : ""}
  </div>
  <div class="sec"><h4>GEO IMPACT SCORE <span title="Transparent heuristic from keywords, region weight and official alert level. Not a probability.">ⓘ heuristic</span></h4>
   <div class="gauge"><b style="color:${col}">${e.score}</b><div class="g"><i style="width:${e.score}%;background:linear-gradient(90deg,#4C8DDB,${col})"></i></div><span class="mut">/100</span></div>
   <div class="note" style="margin-top:6px">${e.kind === "WAR" ? "Keyword + hotspot classifier on headline text. Verify with the source before trading." : "Derived from official alert level (GDACS/USGS/NHC). Verify with the agency link."}</div></div>
  <div class="sec"><h4>TRADABLE EXPOSURE <span>historical association · not advice</span></h4>
   ${(e.assets || []).length ? e.assets.map(assetRow).join("") : '<div class="mut">No direct market mapping for this event type/region.</div>'}</div>
  ${(e.assets || []).length ? `<div class="sec"><h4>ONE-CLICK TRADE</h4><div class="links">${tradeLinks(e.assets[0].s)}</div><div class="links" style="margin-top:6px">${e.assets.slice(1, 6).map(a => `<a class="lnk" target="_blank" href="${(BROKERS[store.get("broker", "tradingview")] || BROKERS.tradingview).u(a.s)}">${h(a.s)} ↗</a>`).join("")}</div></div>` : ""}
  ${strat.length ? `<div class="sec"><h4>PLAYBOOK</h4>${strat.map(s => `<div class="sc" data-st="${s.id}" style="padding:6px 0;border:0"><div><div class="n" style="font-size:11.5px">${h(s.name)}</div><div class="c">${s.horizon} · risk ${s.risk} · ${s.diff}</div></div><span class="lnk">Open →</span></div>`).join("")}</div>` : ""}
  <div class="sec"><h4>VERIFY</h4><div class="links">${e.link ? `<a class="lnk" target="_blank" href="${h(e.link)}">Original source ↗</a>` : ""}${e.details?.Graphics ? `<a class="lnk" target="_blank" href="${h(e.details.Graphics)}">NHC forecast cone ↗</a>` : ""}${e.kind === "TC" ? `<button class="lnk" data-goto="cyclone">Cyclone tracker →</button>` : ""}${e.kind === "WAR" ? `<button class="lnk" data-goto="war">War room →</button><button class="lnk" data-goto="predict">Prediction markets →</button>` : ""}</div></div>`;
}
function assetRow(a) {
  const q = S.quotes[a.s];
  return `<div class="ar"><span class="sy" data-s="${h(a.s)}">${h(a.s)}</span><span class="wy">${h(a.why || NAMES[a.s] || q?.name || "")}</span><span class="q">${q ? fmtP(q.price) : "—"}<br><span class="${q ? cls(q.chgPct) : "fl"}">${q ? fmtC(q.chgPct) : ""}</span></span>${a.d ? `<span class="dir ${a.d}">${a.d === "up" ? "▲ LONG" : a.d === "down" ? "▼ SHORT" : "◆ VOL"}</span>` : `<a class="lnk" target="_blank" href="${BROKERS.tradingview.u(a.s)}">↗</a>`}</div>`;
}
$("#intel").onclick = e => {
  if (e.target.id === "intelclose") { S.sel = null; renderIntel(); drawMarkers(TC); return; }
  const s = e.target.closest(".sy")?.dataset.s; if (s) return loadChart(TC, s);
  const id = e.target.closest(".ev")?.dataset.id; if (id) return selectEvent(id, true);
  const st = e.target.closest("[data-st]")?.dataset.st; if (st) { store.set("strat", st); showTab("strategies"); return; }
  const g = e.target.dataset.goto; if (g) showTab(g);
};

/* ---------------- charts ---------------- */
const TFS = { "1D": ["1d", "5m"], "5D": ["5d", "15m"], "1M": ["1mo", "60m"], "6M": ["6mo", "1d"], "1Y": ["1y", "1d"], "5Y": ["5y", "1wk"] };
function makeChart(el, tfEl, symEl, nameEl, pxEl, tradeEl) {
  const chart = LightweightCharts.createChart(el, {
    autoSize: true, layout: { background: { color: "#0B111B" }, textColor: "#6B7A90", fontFamily: "JetBrains Mono, monospace", fontSize: 10 },
    grid: { vertLines: { color: "#111a27" }, horzLines: { color: "#111a27" } }, crosshair: { mode: 0, vertLine: { color: "#2F81F7", labelBackgroundColor: "#2F81F7" }, horzLine: { color: "#2F81F7", labelBackgroundColor: "#2F81F7" } },
    rightPriceScale: { borderColor: "#1A2433" }, timeScale: { borderColor: "#1A2433", timeVisible: true, secondsVisible: false },
  });
  const cs = chart.addCandlestickSeries({ upColor: "#2BD67B", downColor: "#F2495C", borderVisible: false, wickUpColor: "#2BD67B", wickDownColor: "#F2495C" });
  const vs = chart.addHistogramSeries({ priceScaleId: "vol", priceFormat: { type: "volume" }, color: "#1d2a3d" });
  chart.priceScale("vol").applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
  const C = { chart, cs, vs, el, sym: null, tf: "5D", bars: [], tfEl, symEl, nameEl, pxEl, tradeEl };
  tfEl.innerHTML = Object.keys(TFS).map(k => `<button data-tf="${k}" class="${k === C.tf ? "on" : ""}">${k}</button>`).join("");
  tfEl.onclick = e => { const k = e.target.dataset.tf; if (k) { C.tf = k; $$("button", tfEl).forEach(b => b.classList.toggle("on", b.dataset.tf === k)); loadChart(C, C.sym); } };
  return C;
}
const tzOff = -new Date().getTimezoneOffset() * 60;
async function loadChart(C, sym) {
  if (!sym) return;
  C.sym = sym; C.symEl.textContent = sym; C.nameEl.textContent = NAMES[sym] || S.quotes[sym]?.name || "";
  C.tradeEl.innerHTML = tradeLinks(sym) + `<button class="lnk" data-paper="${h(sym)}">Paper</button>`;
  updChartPx();
  const [rng, iv] = TFS[C.tf];
  const token = (C.token = (C.token || 0) + 1);
  try {
    const d = await api(`/api/chart?symbol=${encodeURIComponent(sym)}&range=${rng}&interval=${iv}`);
    if (token !== C.token) return;
    const r = d.chart?.result?.[0]; if (!r || !r.timestamp) throw new Error(d.chart?.error?.description || "no data");
    const q = r.indicators.quote[0]; const bars = [], vols = [];
    const daily = /d|wk|mo/.test(iv) && !/m$/.test(iv);
    r.timestamp.forEach((t, i) => {
      if (q.open[i] == null || q.close[i] == null) return;
      const tt = daily ? t : t + tzOff;
      if (bars.length && tt <= bars[bars.length - 1].time) return;
      bars.push({ time: tt, open: q.open[i], high: q.high[i], low: q.low[i], close: q.close[i] });
      vols.push({ time: tt, value: q.volume?.[i] || 0, color: q.close[i] >= q.open[i] ? "#123a2a" : "#3a1820" });
    });
    C.bars = bars; C.daily = daily;
    C.cs.setData(bars); C.vs.setData(vols); C.chart.timeScale().fitContent();
    C.el.querySelector(".unavail")?.remove();
    drawMarkers(C);
  } catch (e) {
    if (token !== C.token) return;
    C.cs.setData([]); C.vs.setData([]);
    C.el.querySelector(".unavail")?.remove();
    C.el.insertAdjacentHTML("beforeend", `<div class="unavail" style="position:absolute;top:8px;left:8px;z-index:5">Chart unavailable for ${h(sym)}: ${h(e.message)}</div>`);
  }
  if (!S.quotes[sym]) pollQuotes([sym]);
}
function drawMarkers(C) {
  if (!C.bars?.length) return;
  const evs = allEvents().filter(e => (e.assets || []).some(a => a.s === C.sym) && e.score >= 35);
  if (S.sel && !evs.includes(S.sel) && C === TC) evs.push(S.sel);
  const first = C.bars[0].time, last = C.bars[C.bars.length - 1].time;
  const mk = [];
  evs.forEach(e => {
    let t = Math.floor(new Date(e.time) / 1000) + (C.daily ? 0 : tzOff);
    if (t < first || t > last + 86400) return;
    let bt = C.bars[0].time; for (const b of C.bars) { if (b.time <= t) bt = b.time; else break; }
    mk.push({ time: bt, position: "aboveBar", color: LV_COL[e.level], shape: e === S.sel ? "arrowDown" : "circle", text: e === S.sel ? (KIND[e.kind] || "") : "" });
  });
  mk.sort((a, b) => a.time - b.time);
  C.cs.setMarkers(mk);
}
function updChartPx() {
  [typeof TC !== "undefined" && TC, typeof MC !== "undefined" && MC].forEach(C => {
    if (!C || !C.sym) return; const q = S.quotes[C.sym];
    C.pxEl.innerHTML = q ? `${fmtP(q.price)} <span class="${cls(q.chgPct)}">${fmtC(q.chgPct)}</span> <span class="mut">${h(q.currency || "")}</span>` : "";
  });
}
document.addEventListener("click", e => { const p = e.target.dataset?.paper; if (p) { showTab("markets"); $("#psym").value = p; } });

/* ================= WAR ROOM ================= */
let wmapW, wLayer, warTheme = "ALL";
function renderWar() {
  if (!wmapW) { wmapW = mkMap("warmap", [30, 40], 3); wLayer = L.layerGroup().addTo(wmapW); ["chokepoints", "bases", "nukeweapons", "oilterminals"].forEach(k => geoLayer(k).addTo(wmapW)); }
  const themes = {}; S.news.forEach(e => (e.themes || []).forEach(t => themes[t] = (themes[t] || 0) + 1));
  $("#warfilter").innerHTML = ["ALL", ...Object.keys(themes).sort((a, b) => themes[b] - themes[a])].map(t => `<button class="chip ${warTheme === t ? "on" : ""}" data-t="${t}">${t}<i>${t === "ALL" ? S.news.length : themes[t]}</i></button>`).join("");
  const list = S.news.filter(e => warTheme === "ALL" || (e.themes || []).includes(warTheme));
  $("#warmeta").textContent = `${list.length} items · updated ${S.newsAt ? ago(S.newsAt) + " ago" : "—"} · keyword/region classifier`;
  $("#warlist").innerHTML = S.newsErr && !S.news.length ? `<div class="unavail">Conflict wire unavailable: ${h(S.newsErr)}</div>` : list.map(e => `<div class="ev" data-id="${h(e.id)}"><div class="bar c-${e.level}"></div><div><div class="t">${h(e.title)}</div>${e.summary ? `<div class="note" style="margin-top:3px;color:#8593a8">${h(e.summary.slice(0, 200))}</div>` : ""}<div class="m"><span class="lv ${e.level}">${e.level} ${e.score}</span>${e.region ? `<span>${h(e.region)}</span>` : ""}<span>${h(e.source)}</span><span>${ago(e.time)} ago</span>${(e.assets || []).slice(0, 5).map(a => `<span class="tk" data-s="${h(a.s)}">${h(a.s)}<span class="dir ${a.d}">${a.d === "up" ? "▲" : a.d === "down" ? "▼" : "◆"}</span></span>`).join("")}</div></div></div>`).join("") || '<div class="empty">No items</div>';
  wLayer.clearLayers();
  jitter(list.filter(e => e.lat != null)).forEach(e => evMarker(e, x => openEvent(x.id)).addTo(wLayer));
  // hotspots
  const cut = Date.now() - 24 * 3600e3, hs = {};
  S.news.filter(e => e.region && new Date(e.time) > cut).forEach(e => { const r = hs[e.region] = hs[e.region] || { n: 0, mx: 0, assets: {}, ev: e }; r.n++; if (e.score > r.mx) { r.mx = e.score; r.ev = e; } (e.assets || []).forEach(a => r.assets[a.s] = a); });
  const arr = Object.entries(hs).sort((a, b) => (b[1].mx * 2 + b[1].n * 4) - (a[1].mx * 2 + a[1].n * 4));
  $("#hotspots").innerHTML = arr.map(([r, v]) => { const l = v.mx >= 80 ? "CRITICAL" : v.mx >= 60 ? "HIGH" : v.mx >= 35 ? "ELEVATED" : "WATCH"; return `<div class="hs" data-id="${h(v.ev.id)}"><div><b style="font-size:11.5px">${h(r)}</b><div class="mut">${v.n} headline${v.n > 1 ? "s" : ""}</div></div><span class="lv ${l}">${v.mx}</span><div><div class="hb"><i style="width:${v.mx}%;background:${LV_COL[l]}"></i></div><div class="links" style="margin-top:4px">${Object.values(v.assets).slice(0, 6).map(a => `<span class="tk" data-s="${h(a.s)}">${h(a.s)}</span>`).join("")}</div></div></div>`; }).join("") || '<div class="empty">No regional hotspots in the last 24h</div>';
}
$("#warfilter").onclick = e => { const t = e.target.closest(".chip")?.dataset.t; if (t) { warTheme = t; renderWar(); } };
[$("#warlist"), $("#hotspots")].forEach(el => el.onclick = e => { const s = e.target.closest(".tk")?.dataset.s; if (s) { showTab("terminal"); return loadChart(TC, s); } const id = e.target.closest("[data-id]")?.dataset.id; if (id) openEvent(id); });
onShow.war = renderWar;

/* ================= GEO STATIC LAYERS (data in geodata.js) ================= */
function geoLayer(kind) {
  const g = L.layerGroup(), [label, col, shape] = GEOMETA[kind];
  const pop = (n, desc, syms) => `<b style="color:${col}">${h(n)}</b><div class="mut" style="font-size:9.5px;letter-spacing:.1em;margin-top:2px">${h(label.toUpperCase())}</div><div class="note" style="color:#9aa8bb;margin:4px 0 6px">${h(desc || "")}</div>${syms ? `<div class="links">${syms.split(",").filter(Boolean).map(s => `<a class="lnk" target="_blank" href="${BROKERS.tradingview.u(s)}">${s} ↗</a>`).join("")}</div>` : ""}`;
  GEO[kind].forEach(row => {
    let l;
    if (shape === "line") { const [n, pts, desc, syms] = row; l = L.polyline(pts, { color: col, weight: 2.2, opacity: 0.8, dashArray: /damaged|offline/i.test(n) ? "4 5" : null }); l.bindPopup(pop(n, desc, syms)); }
    else if (shape === "area") { const [n, bb, desc, syms] = row; l = L.rectangle([[bb[0], bb[1]], [bb[2], bb[3]]], { color: col, weight: 1, fillOpacity: 0.08, dashArray: "4 3" }); l.bindPopup(pop(n, desc, syms)); }
    else {
      const [n, la, lo, desc, syms] = row;
      if (shape === "dot" || shape === "square") l = L.circleMarker([la, lo], { radius: shape === "square" ? 4.5 : 4, color: "#05070a", weight: 1, fillColor: col, fillOpacity: 0.95 });
      else l = L.marker([la, lo], { icon: L.divIcon({ className: "", html: shape === "triangle" ? `<div style="width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-bottom:11px solid ${col};filter:drop-shadow(0 0 2px #000)"></div>` : shape === "ring" ? `<div style="width:11px;height:11px;border-radius:50%;border:2.5px solid ${col};background:#07090D;box-shadow:0 0 6px ${col}"></div>` : `<div style="width:9px;height:9px;border:2px solid ${col};background:#07090D;transform:rotate(45deg)"></div>`, iconSize: [12, 12] }) });
      l.bindPopup(pop(n, desc, syms));
    }
    l.bindTooltip(row[0], { direction: "top" });
    l.addTo(g);
  });
  return g;
}
function graticule() {
  const g = L.layerGroup(), st = { color: "#1e2a3c", weight: 0.6, interactive: false };
  for (let la = -75; la <= 75; la += 15) L.polyline([[la, -540], [la, 540]], st).addTo(g);
  for (let lo = -540; lo <= 540; lo += 15) L.polyline([[-85, lo], [85, lo]], st).addTo(g);
  return g;
}

/* ================= WEATHER MAP ================= */
const gibs = (id, lvl, op = 0.7, date = "default") => L.tileLayer(`https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${id}/default/${date}/GoogleMapsCompatible_Level${lvl}/{z}/{y}/{x}.${/Reflectance|Relief/.test(id) ? "jpg" : "png"}`, { maxNativeZoom: lvl, maxZoom: 12, opacity: op, attribution: 'Imagery: <a href="https://earthdata.nasa.gov/gibs">NASA GIBS</a>', bounds: [[-85, -180], [85, 180]] });
let radarMeta = null, radarFrames = [], radarIdx = 0, radarTimer = null;
async function loadRadarMeta() { try { radarMeta = await api("/api/radar"); radarFrames = [...(radarMeta.radar?.past || []), ...(radarMeta.radar?.nowcast || [])]; radarIdx = (radarMeta.radar?.past || []).length - 1; } catch (e) { radarMeta = null; } return radarMeta; }
async function radarLayer(path) {
  if (!radarMeta) await loadRadarMeta(); if (!radarMeta) { toast({ level: "WATCH", title: "Radar unavailable (RainViewer did not respond)" }); return null; }
  const f = path || radarFrames[radarIdx]?.path; if (!f) return null;
  return L.tileLayer(`${radarMeta.host}${f}/256/{z}/{x}/{y}/4/1_1.png`, { opacity: 0.75, maxNativeZoom: 7, maxZoom: 12, attribution: 'Radar <a href="https://www.rainviewer.com">RainViewer</a>' });
}
const WX_FIELDS = {
  wind: { v: "wind_speed_10m", n: "Wind speed (km/h)", grad: ["#2F81F7", "#39C5CF", "#2BD67B", "#F0C03A", "#F07A2A", "#FF3B4E", "#A371F7"], rng: [0, 100] },
  gust: { v: "wind_gusts_10m", n: "Wind gusts (km/h)", grad: ["#2F81F7", "#39C5CF", "#2BD67B", "#F0C03A", "#F07A2A", "#FF3B4E", "#A371F7"], rng: [0, 130] },
  temp: { v: "temperature_2m", n: "Temperature (°C)", grad: ["#A371F7", "#2F81F7", "#39C5CF", "#2BD67B", "#F0C03A", "#F07A2A", "#FF3B4E"], rng: [-30, 45] },
  feels: { v: "apparent_temperature", n: "Apparent temp (°C)", grad: ["#A371F7", "#2F81F7", "#39C5CF", "#2BD67B", "#F0C03A", "#F07A2A", "#FF3B4E"], rng: [-35, 50] },
  pres: { v: "pressure_msl", n: "Pressure MSL (hPa)", grad: ["#FF3B4E", "#F07A2A", "#F0C03A", "#2BD67B", "#39C5CF", "#2F81F7"], rng: [960, 1040] },
  hum: { v: "relative_humidity_2m", n: "Humidity (%)", grad: ["#F07A2A", "#F0C03A", "#2BD67B", "#39C5CF", "#2F81F7"], rng: [0, 100] },
  dew: { v: "dew_point_2m", n: "Dew point (°C)", grad: ["#A371F7", "#2F81F7", "#39C5CF", "#2BD67B", "#F0C03A", "#FF3B4E"], rng: [-30, 30] },
  cloud: { v: "cloud_cover", n: "Cloud cover (%)", grad: ["#0d1520", "#3b4a60", "#8a9ab0", "#e8eef7"], rng: [0, 100] },
  precip: { v: "precipitation", n: "Precipitation (mm/h)", grad: ["#1b2636", "#39C5CF", "#2F81F7", "#A371F7", "#FF3B4E"], rng: [0, 10] },
  snow: { v: "snowfall", n: "Snowfall (cm/h)", grad: ["#1b2636", "#8a9ab0", "#e8eef7", "#A371F7"], rng: [0, 3] },
  cape: { v: "cape", n: "CAPE (J/kg) — convective energy", grad: ["#1b2636", "#2BD67B", "#F0C03A", "#F07A2A", "#FF3B4E", "#A371F7"], rng: [0, 3000] },
  vis: { v: "visibility", n: "Visibility (m)", grad: ["#FF3B4E", "#F0C03A", "#2BD67B", "#2F81F7"], rng: [0, 30000] },
};
function grad(stops, t) {
  t = Math.max(0, Math.min(1, t)); const p = t * (stops.length - 1), i = Math.floor(p), f = p - i;
  const a = stops[i], b = stops[Math.min(i + 1, stops.length - 1)];
  const c = (x, k) => parseInt(x.slice(1 + 2 * k, 3 + 2 * k), 16);
  return "#" + [0, 1, 2].map(k => Math.round(c(a, k) + (c(b, k) - c(a, k)) * f).toString(16).padStart(2, "0")).join("");
}
const LAYERS = [
  ["BASE MAP", [
    { id: "labels", n: "Place labels", ds: "Cities, countries (NASA GIBS / OSM)", on: true, make: labelsLayer },
    { id: "grid", n: "Lat/lon grid", ds: "15° graticule", make: graticule },
    { id: "truecolor", n: "Satellite true colour", ds: "NASA VIIRS NOAA-20 · yesterday (latest complete day)", make: () => gibs("VIIRS_NOAA20_CorrectedReflectance_TrueColor", 9, 0.95, YDAY) },
    { id: "relief", n: "Terrain / shaded relief", ds: "NASA ASTER GDEM", make: () => gibs("ASTER_GDEM_Greyscale_Shaded_Relief", 12, 0.45) },
    { id: "lights", n: "Night lights", ds: "NASA Black Marble — economic activity", make: () => gibs("VIIRS_Black_Marble", 8, 0.8, "2016-01-01") },
    { id: "pop", n: "Population density", ds: "SEDAC GPW 2020", make: () => gibs("GPW_Population_Density_2020", 7, 0.6) },
  ]],
  ["RADAR & SATELLITE", [
    { id: "radar", n: "Precipitation radar (animated)", ds: "RainViewer · past 2h + nowcast", radar: true },
    { id: "imerg", n: "Global precipitation rate", ds: "NASA GPM IMERG · near-real-time", make: () => gibs("IMERG_Precipitation_Rate", 6, 0.75) },
    { id: "irsat", n: "Live IR satellite (~10 min)", ds: "GOES-East/West + Himawari · cloud & storm structure", make: irSat },
    { id: "cloudtop", n: "Cloud top temperature", ds: "MODIS Terra · yesterday", make: () => gibs("MODIS_Terra_Cloud_Top_Temp_Day", 6, 0.6, YDAY) },
    { id: "aerosol", n: "Aerosol / smoke / ash", ds: "MODIS Terra AOD", make: () => gibs("MODIS_Terra_Aerosol", 6, 0.6) },
  ]],
  ["MODEL FIELDS (OPEN-METEO, CURRENT)", Object.entries(WX_FIELDS).map(([k, f]) => ({ id: "wx-" + k, n: f.n, ds: "Best-match model · sampled grid · arrows = wind dir", wx: k }))],
  ["OCEAN", [
    { id: "sst", n: "Sea surface temperature", ds: "GHRSST MUR L4 · cyclone fuel ≥ 26.5°C", make: () => gibs("GHRSST_L4_MUR_Sea_Surface_Temperature", 7, 0.7) },
    { id: "ssta", n: "SST anomaly", ds: "GHRSST MUR · marine heatwaves / El Niño", make: () => gibs("GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies", 7, 0.7) },
  ]],
  ["LAND & AGRICULTURE", [
    { id: "soil", n: "Root-zone soil moisture", ds: "NASA SMAP L4 · drought stress", make: () => gibs("SMAP_L4_Analyzed_Root_Zone_Soil_Moisture", 6, 0.7) },
    { id: "lst", n: "Land surface temperature", ds: "MODIS Terra · day", make: () => gibs("MODIS_Terra_Land_Surface_Temp_Day", 7, 0.65) },
    { id: "geo-ag", n: "Agricultural regions", ds: "Key crop zones → futures", make: () => geoLayer("ag") },
  ]],
  ["EVENTS & GEOPOLITICS", [
    { id: "ev-nat", n: "Natural hazards (live)", ds: "GDACS · USGS · NASA EONET · NHC", on: true, ev: "nat" },
    { id: "ev-war", n: "Conflict hotspots (live)", ds: "Wire classifier", on: true, ev: "war" },
  ]],
  ["INFRASTRUCTURE & STRATEGIC SITES", Object.keys(GEOMETA).filter(k => k !== "ag").map(k => ({ id: "geo-" + k, n: GEOMETA[k][0], ds: GEO[k].length + " sites · click for tradable tickers", make: () => geoLayer(k) }))],
];
let wmap, LSTATE = store.get("layers", {}), LOBJ = {}, wxGrid = null, wxField = null;
function initWMap() {
  wmap = mkMap("wmap", [25, 0], 3);
  // remove default labels added by mkMap: we manage labels as a layer
  wmap.eachLayer(l => { if (l._url && l._url.includes("Reference_Labels")) wmap.removeLayer(l); });
  renderLayerList();
  LAYERS.flatMap(c => c[1]).forEach(l => { if (LSTATE[l.id]?.on ?? l.on) setLayer(l, true); });
  wmap.on("moveend", () => { if (wxField) loadWxGrid(); });
  wmap.on("click", e => inspect(e.latlng.lat, e.latlng.lng));
  $("#tplay").onclick = () => { if (radarTimer) { clearInterval(radarTimer); radarTimer = null; $("#tplay").textContent = "▶"; } else { $("#tplay").textContent = "❚❚"; radarTimer = setInterval(() => { radarIdx = (radarIdx + 1) % radarFrames.length; $("#tslider").value = radarIdx; showRadarFrame(); }, 700); } };
  $("#tslider").oninput = e => { radarIdx = +e.target.value; showRadarFrame(); };
}
function renderLayerList() {
  const q = ($("#layerq").value || "").toLowerCase();
  $("#layerlist").innerHTML = LAYERS.map(([cat, ls]) => { const m = ls.filter(l => !q || (l.n + l.ds).toLowerCase().includes(q)); return m.length ? `<div class="lcat">${cat}</div>` + m.map(l => { const on = LSTATE[l.id]?.on ?? !!l.on; return `<div class="lyr ${on ? "on" : ""}" data-id="${l.id}"><div class="tg"></div><div><div class="nm">${h(l.n)}</div><div class="ds">${h(l.ds)}</div></div>${l.make || l.radar ? `<input type="range" min="0.1" max="1" step="0.05" value="${LSTATE[l.id]?.op ?? 0.75}">` : ""}</div>`; }).join("") : ""; }).join("");
}
$("#layerq").oninput = renderLayerList;
$("#layerlist").onclick = e => { const row = e.target.closest(".lyr"); if (!row || e.target.type === "range") return; const l = LAYERS.flatMap(c => c[1]).find(x => x.id === row.dataset.id); setLayer(l, !(LSTATE[l.id]?.on ?? !!l.on)); renderLayerList(); };
$("#layerlist").oninput = e => { if (e.target.type !== "range") return; const id = e.target.closest(".lyr").dataset.id; LSTATE[id] = Object.assign(LSTATE[id] || {}, { op: +e.target.value }); store.set("layers", LSTATE); const o = LOBJ[id]; o?.setOpacity && o.setOpacity(+e.target.value); };
async function setLayer(l, on) {
  LSTATE[l.id] = Object.assign(LSTATE[l.id] || {}, { on }); store.set("layers", LSTATE);
  if (l.wx) {
    if (on) { LAYERS.flatMap(c => c[1]).filter(x => x.wx && x.id !== l.id).forEach(x => { LSTATE[x.id] = Object.assign(LSTATE[x.id] || {}, { on: false }); }); wxField = l.wx; loadWxGrid(); }
    else if (wxField === l.wx) { wxField = null; wxGrid && wmap.removeLayer(wxGrid); wxGrid = null; }
    store.set("layers", LSTATE); renderLegend(); return;
  }
  if (l.ev) { if (on) { LOBJ[l.id] = L.layerGroup().addTo(wmap); renderWMapEvents(); } else if (LOBJ[l.id]) { wmap.removeLayer(LOBJ[l.id]); delete LOBJ[l.id]; } return; }
  if (on) {
    if (LOBJ[l.id]) return;
    const obj = l.radar ? await radarLayer() : l.make(); if (!obj) return;
    if (!(LSTATE[l.id]?.on)) return;
    if (obj.setOpacity && LSTATE[l.id]?.op) obj.setOpacity(LSTATE[l.id].op);
    LOBJ[l.id] = obj.addTo(wmap);
    if (l.radar) { $("#timebar").classList.add("on"); $("#tslider").max = radarFrames.length - 1; $("#tslider").value = radarIdx; showRadarLabel(); }
  } else if (LOBJ[l.id]) {
    wmap.removeLayer(LOBJ[l.id]); delete LOBJ[l.id];
    if (l.radar) { $("#timebar").classList.remove("on"); if (radarTimer) { clearInterval(radarTimer); radarTimer = null; $("#tplay").textContent = "▶"; } }
  }
  renderLegend();
}
function showRadarLabel() { const f = radarFrames[radarIdx]; if (!f) return; const past = radarIdx < (radarMeta.radar?.past || []).length; $("#tlabel").textContent = `Radar ${new Date(f.time * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} ${past ? "(observed)" : "(nowcast)"}`; }
async function showRadarFrame() {
  const old = LOBJ.radar; if (!old) return;
  const nl = await radarLayer(radarFrames[radarIdx].path); nl.setOpacity(LSTATE.radar?.op ?? 0.75); nl.addTo(wmap); LOBJ.radar = nl;
  setTimeout(() => wmap.removeLayer(old), 350); showRadarLabel();
}
function renderWMapEvents() {
  if (LOBJ["ev-nat"]) { LOBJ["ev-nat"].clearLayers(); S.nat.filter(e => e.lat != null).forEach(e => evMarker(e, x => openEvent(x.id)).addTo(LOBJ["ev-nat"])); }
  if (LOBJ["ev-war"]) { LOBJ["ev-war"].clearLayers(); jitter(S.news.filter(e => e.lat != null && e.score >= 35)).forEach(e => evMarker(e, x => openEvent(x.id)).addTo(LOBJ["ev-war"])); }
}
let wxTok = 0;
async function loadWxGrid() {
  const f = WX_FIELDS[wxField]; if (!f) return;
  const b = wmap.getBounds(), tok = ++wxTok;
  const s = Math.max(-80, b.getSouth()), n = Math.min(80, b.getNorth()); let w = b.getWest(), e = b.getEast();
  if (e - w > 360) { w = -180; e = 180; }
  const cols = 11, rows = 7, lats = [], lons = [];
  const r = (v, st) => Math.round(v / st) * st;
  const stLat = Math.max(0.25, r((n - s) / rows, 0.25)), stLon = Math.max(0.25, r((e - w) / cols, 0.25));
  for (let i = 0; i < rows; i++) for (let j = 0; j < cols; j++) { const la = r(s + stLat * (i + 0.5), 0.25), lo = r(w + stLon * (j + 0.5), 0.25); lats.push(la.toFixed(2)); lons.push((((lo + 540) % 360) - 180).toFixed(2)); }
  const vars = [...new Set([f.v, "wind_direction_10m", "wind_speed_10m"])].join(",");
  $("#wlegend").innerHTML = `<b>${h(f.n)}</b><div class="mut">Loading model grid…</div>`;
  try {
    let d = await api(`/api/wx?latitude=${lats.join(",")}&longitude=${lons.join(",")}&current=${vars}&timezone=UTC`);
    if (tok !== wxTok || !wxField) return;
    if (!Array.isArray(d)) d = [d];
    wxGrid && wmap.removeLayer(wxGrid); wxGrid = L.layerGroup().addTo(wmap);
    d.forEach((p, i) => {
      const c = p.current; if (!c) return; const v = c[f.v]; if (v == null) return;
      const col = grad(f.grad, (v - f.rng[0]) / (f.rng[1] - f.rng[0]));
      const dir = c.wind_direction_10m, ws = c.wind_speed_10m;
      const disp = f.v === "visibility" ? (v / 1000).toFixed(0) + "k" : Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(v % 1 && Math.abs(v) < 10 ? 1 : 0);
      L.circle([p.latitude, p.longitude], { radius: stLat * 111000 * 0.48, stroke: false, fillColor: col, fillOpacity: 0.28, interactive: false }).addTo(wxGrid);
      L.marker([p.latitude, p.longitude], { icon: L.divIcon({ className: "", html: `<div class="wxpt" style="color:${col}"><i style="transform:rotate(${(dir ?? 0) + 180}deg);display:inline-block;opacity:${ws ? Math.min(1, 0.35 + ws / 40) : 0}">↑</i><br>${disp}</div>`, iconSize: [40, 28], iconAnchor: [20, 14] }) }).bindTooltip(`${h(f.n)}: <b>${v}</b><br>Wind ${ws ?? "—"} km/h from ${dir ?? "—"}°<br>${p.latitude.toFixed(2)}, ${p.longitude.toFixed(2)}`).addTo(wxGrid);
    });
    renderLegend(d[0]?.current?.time);
  } catch (err) { if (tok === wxTok) $("#wlegend").innerHTML = `<b>${h(f.n)}</b><div class="unavail" style="margin:4px 0 0">Open-Meteo unavailable: ${h(err.message)}</div>`; }
}
function renderLegend(t) {
  const parts = [];
  if (wxField) { const f = WX_FIELDS[wxField]; parts.push(`<b>${h(f.n)}</b>${t ? ` <span class="mut">valid ${h(t)} UTC</span>` : ""}<div class="grad" style="background:linear-gradient(90deg,${f.grad.join(",")})"></div><div class="gl"><span>${f.rng[0]}</span><span>${f.rng[1]}</span></div>`); }
  if (LOBJ.sst) parts.push(`<div class="mut">SST: blue cold → red warm (≥26.5°C supports cyclones)</div>`);
  if (LOBJ.soil) parts.push(`<div class="mut">Soil moisture: brown dry → blue wet</div>`);
  if (LOBJ["ev-nat"] || LOBJ["ev-war"]) parts.push(Object.entries(LV_COL).map(([k, c]) => `<span class="lg" style="display:inline-flex;margin-right:6px"><i class="sw" style="background:${c}"></i>${k}</span>`).join(""));
  $("#wlegend").innerHTML = parts.join('<div style="height:5px"></div>');
}
async function inspect(lat, lon) {
  const el = $("#inspect"); el.classList.add("on");
  el.innerHTML = `<div class="ph"><b>POINT FORECAST</b><span class="mut">${lat.toFixed(2)}, ${lon.toFixed(2)}</span><button class="btn sm" onclick="this.closest('.inspect').classList.remove('on')">✕</button></div><div class="pad mut">Loading Open-Meteo…</div>`;
  try {
    const d = await api(`/api/wx?latitude=${lat.toFixed(2)}&longitude=${lon.toFixed(2)}&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,pressure_msl,precipitation,cloud_cover,cape&daily=temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max&forecast_days=7&timezone=auto`);
    const c = d.current, dl = d.daily;
    el.innerHTML = `<div class="ph"><b>POINT FORECAST</b><span class="mut">${lat.toFixed(2)}, ${lon.toFixed(2)}</span><button class="btn sm" onclick="this.closest('.inspect').classList.remove('on')">✕</button></div>
    <div class="sec"><div class="kv"><span>Temperature</span><b>${c.temperature_2m}°C (feels ${c.apparent_temperature}°)</b><span>Wind</span><b>${c.wind_speed_10m} km/h · gust ${c.wind_gusts_10m} · ${c.wind_direction_10m}°</b><span>Pressure</span><b>${c.pressure_msl} hPa</b><span>Humidity</span><b>${c.relative_humidity_2m}%</b><span>Precip</span><b>${c.precipitation} mm</b><span>Cloud</span><b>${c.cloud_cover}%</b><span>CAPE</span><b>${c.cape ?? "—"} J/kg</b><span>Valid</span><b>${h(c.time)} ${h(d.timezone_abbreviation || "")}</b></div></div>
    <div class="sec"><h4>7-DAY</h4><table>${dl.time.map((t, i) => `<tr><td>${t.slice(5)}</td><td class="n">${dl.temperature_2m_min[i]}° / ${dl.temperature_2m_max[i]}°</td><td class="n">${dl.precipitation_sum[i]} mm</td><td class="n">${dl.wind_gusts_10m_max[i]} km/h</td></tr>`).join("")}</table></div>
    <div class="sec"><button class="btn sm pri" id="tofc">Open in Forecast Center →</button></div>`;
    $("#tofc").onclick = () => { FC.loc = { name: `${lat.toFixed(2)}, ${lon.toFixed(2)}`, lat, lon }; showTab("forecast"); loadFC(); };
  } catch (e) { el.querySelector(".pad").outerHTML = `<div class="unavail">Open-Meteo unavailable: ${h(e.message)}</div>`; }
}
onShow.map = () => { if (!wmap) initWMap(); else { wmap.invalidateSize(); renderWMapEvents(); } };

/* ================= CYCLONES ================= */
const YDAY = new Date(Date.now() - 86400e3).toISOString().slice(0, 10);
function irSat() { return L.layerGroup(["GOES-East_ABI_Band13_Clean_Infrared", "GOES-West_ABI_Band13_Clean_Infrared", "Himawari_AHI_Band13_Clean_Infrared"].map(id => gibs(id, 6, 0.5))); }
const SS = [[137, "CAT 5", "#D946EF"], [113, "CAT 4", "#FF3B4E"], [96, "CAT 3", "#F07A2A"], [83, "CAT 2", "#F0A43A"], [64, "CAT 1", "#F0C03A"], [34, "TS", "#39C5CF"], [0, "TD", "#5AA9E6"]];
const ssCat = kt => SS.find(s => (kt || 0) >= s[0]);
const segCol = c => /HU|TY|MH|CAT/.test(c || "") ? "#F07A2A" : /TS|STS/.test(c || "") ? "#39C5CF" : "#5AA9E6";
const haversine = (a, b, c, d) => { const R = 6371, r = Math.PI / 180, x = Math.sin((c - a) * r / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin((d - b) * r / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(x)); };
const CY_LAYERS = [
  ["nightlights", "Night lights", "BASE", true, () => gibs("VIIRS_Black_Marble", 8, 0.85, "2016-01-01")],
  ["truecolor", "Satellite true colour (yesterday)", "BASE", false, () => gibs("VIIRS_NOAA20_CorrectedReflectance_TrueColor", 9, 0.95, YDAY)],
  ["labels", "Place labels", "BASE", true, labelsLayer],
  ["grid", "Lat/lon grid", "BASE", false, graticule],
  ["irsat", "Live IR satellite (GOES / Himawari)", "WEATHER", true, irSat],
  ["sst", "Sea surface temperature", "WEATHER", false, () => gibs("GHRSST_L4_MUR_Sea_Surface_Temperature", 7, 0.5)],
  ["ssta", "SST anomaly", "WEATHER", false, () => gibs("GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies", 7, 0.55)],
  ["imerg", "Rain rate (NASA IMERG)", "WEATHER", false, () => gibs("IMERG_Precipitation_Rate", 6, 0.75)],
  ["cloudtop", "Cloud-top temperature (yesterday)", "WEATHER", false, () => gibs("MODIS_Terra_Cloud_Top_Temp_Day", 6, 0.6, YDAY)],
  ["radar", "Precipitation radar", "WEATHER", false, () => radarLayer()],
  ["pop", "Population density", "WEATHER", false, () => gibs("GPW_Population_Density_2020", 7, 0.55)],
  ["history", "Observed track (past positions)", "STORM", true, null],
  ["forecast", "Forecast track, positions & cone", "STORM", true, null],
  ["windbuf", "Wind-speed buffers (GDACS)", "STORM", true, null],
  ["ended", "Show recently ended storms", "STORM", true, null],
  ["inpath", "Highlight assets in the storm's path", "STORM", true, null],
  ...Object.keys(GEOMETA).map(k => ["geo-" + k, GEOMETA[k][0], "INFRASTRUCTURE", ["oilterminals", "refineries", "lng", "nuclear", "oilfields", "pipelines"].includes(k), () => geoLayer(k)]),
];
let cmap, cyObjs = {}, cyStormLayer, cyGeomLayer, cyPathLayer, cyData = null, cySel = null, CY_LIST = [], cyAt = 0, cyTimer = null;
let CYST = Object.assign(Object.fromEntries(CY_LAYERS.map(l => [l[0], l[3]])), store.get("cylayers", {}));
function initCyMap() {
  cmap = L.map("cmap", { worldCopyJump: true, minZoom: 2, preferCanvas: true }).setView([15, 100], 2);
  L.tileLayer(GIBS_B + "OSM_Land_Water_Map/default/default/GoogleMapsCompatible_Level9/{z}/{y}/{x}.png", { maxNativeZoom: 9, maxZoom: 14, className: "bm-land", attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · <a href="https://earthdata.nasa.gov/gibs">NASA GIBS</a> · RainViewer' }).addTo(cmap);
  L.tileLayer(GIBS_B + "Reference_Features_15m/default/default/GoogleMapsCompatible_Level13/{z}/{y}/{x}.png", { maxNativeZoom: 13, maxZoom: 14, opacity: 0.35, className: "bm-ref" }).addTo(cmap);
  cyGeomLayer = L.layerGroup().addTo(cmap); cyPathLayer = L.layerGroup().addTo(cmap); cyStormLayer = L.layerGroup().addTo(cmap);
  const wrap = $("#cmap").parentElement;
  wrap.insertAdjacentHTML("beforeend", `<div class="cylive" id="cylive"></div><div class="cylp" id="cylp"><div class="cylph" id="cylpt">LAYERS ▾</div><div class="cylpb" id="cylpb"></div></div>`);
  $("#cylpt").onclick = () => $("#cylp").classList.toggle("closed");
  renderCyLayerPanel();
  CY_LAYERS.forEach(l => CYST[l[0]] && l[4] && setCyLayer(l, true));
  setTimeout(() => cmap.invalidateSize(), 50);
}
function renderCyLayerPanel() {
  const groups = {}; CY_LAYERS.forEach(l => (groups[l[2]] = groups[l[2]] || []).push(l));
  $("#cylpb").innerHTML = Object.entries(groups).map(([g, ls]) => `<div class="lcat">${g}</div>` + ls.map(l => { const m = l[0].startsWith("geo-") ? GEOMETA[l[0].slice(4)] : null; return `<label class="cyl"><input type="checkbox" data-id="${l[0]}" ${CYST[l[0]] ? "checked" : ""}>${m ? `<i style="background:${m[1]}"></i>` : ""}${h(l[1])}</label>`; }).join("")).join("");
  $("#cylpb").onchange = e => { const id = e.target.dataset.id; const l = CY_LAYERS.find(x => x[0] === id); if (!l) return; CYST[id] = e.target.checked; store.set("cylayers", CYST); if (l[4]) setCyLayer(l, e.target.checked); else { renderCyStorms(); if (cySel) selCyclone(CY_LIST.find(c => c.id === cySel), false); } };
}
async function setCyLayer(l, on) {
  if (on && !cyObjs[l[0]]) { const o = await l[4](); if (o && CYST[l[0]]) cyObjs[l[0]] = o.addTo(cmap); }
  else if (!on && cyObjs[l[0]]) { cmap.removeLayer(cyObjs[l[0]]); delete cyObjs[l[0]]; }
}
function stormIcon(c, sel) {
  const cat = ssCat(c.windKt), col = c.current ? cat[2] : "#5b6b82", sz = sel ? 46 : c.current ? 38 : 24;
  return L.divIcon({ className: "", iconSize: [sz, sz], iconAnchor: [sz / 2, sz / 2], html: `<div class="cystorm ${c.current ? "live" : ""}" style="width:${sz}px;height:${sz}px;color:${col}"><svg viewBox="0 0 40 40"><g fill="currentColor"><circle cx="20" cy="20" r="5"/><path d="M20 4c-6 0-11 3-13 8 3-3 7-4 11-3-5 2-8 6-8 11h0c0 1 0 2 .3 3A12 12 0 0 1 20 4Z"/><path d="M20 36c6 0 11-3 13-8-3 3-7 4-11 3 5-2 8-6 8-11 0-1 0-2-.3-3A12 12 0 0 1 20 36Z"/></g></svg></div><div class="cylab">${h(c.name.replace(/Tropical Cyclone /i, ""))}${c.windKt ? ` · ${Math.round(c.windKt)} kt` : ""}</div>` });
}
async function loadCyclones() {
  if (!cmap) initCyMap();
  if (!CY_LIST.length) $("#cylist").innerHTML = `<div class="empty">Loading live cyclone feeds (NHC · GDACS · NASA · JTWC)…</div>`;
  try { cyData = await api("/api/cyclones"); cyAt = Date.now(); }
  catch (e) { $("#cylist").innerHTML = `<div class="unavail">Cyclone service unavailable: ${h(e.message)}</div>`; renderCyLive(); return; }
  CY_LIST = cyData.storms || [];
  const act = CY_LIST.filter(x => x.current).length;
  $("#cymeta").textContent = `${act} active · ${CY_LIST.length} tracked`;
  const bad = (cyData.sources || []).filter(s => !s.ok);
  $("#cylist").innerHTML = (bad.length ? `<div class="unavail">${bad.map(s => `${h(s.name)} unavailable: ${h(s.error)}`).join("<br>")}<br><span class="mut">Other sources still shown.</span></div>` : "") +
    (CY_LIST.length ? CY_LIST.map(c => { const cat = ssCat(c.windKt); return `<div class="ev ${cySel === c.id ? "sel" : ""}" data-id="${h(c.id)}"><div class="bar" style="background:${c.current ? cat[2] : "#2a3446"}"></div><div><div class="t">${h(c.name)} ${c.current ? '<span class="livebadge">LIVE</span>' : '<span class="mut">(ended)</span>'}</div><div class="m"><span class="lv" style="background:${cat[2]}22;color:${cat[2]};box-shadow:inset 0 0 0 1px ${cat[2]}66">${cat[1]}${c.windKt ? " " + Math.round(c.windKt) + " kt" : ""}</span>${c.alert ? `<span class="lv ${c.alert === "Red" ? "CRITICAL" : c.alert === "Orange" ? "HIGH" : "WATCH"}">${h(c.alert)}</span>` : ""}${c.country ? `<span>${h(c.country)}</span>` : ""}<span>${h((c.sources || []).join(" + "))}</span><span>${ago(c.updated)} ago</span></div></div></div>`; }).join("")
      : `<div class="empty">No tropical cyclones reported by NHC, GDACS, NASA or JTWC.<br><br><span class="note">When a storm forms anywhere it appears here automatically.</span></div>`) +
    ((cyData.jtwc || []).length ? `<div class="sec"><h4>JTWC BULLETIN</h4>${cyData.jtwc.slice(0, 3).map(j => `<div class="note" style="margin-bottom:6px;color:#9aa8bb"><a target="_blank" href="${h(j.link)}">${h(j.title)}</a><br>${h(j.desc.slice(0, 220))}</div>`).join("")}</div>` : "");
  renderCyStorms(); renderCyLive();
  $("#clegend").innerHTML = SS.slice().reverse().map(s => `<span class="lg" style="display:inline-flex;margin-right:7px"><i class="sw" style="background:${s[2]}"></i>${s[1]}</span>`).join("") + `<div class="note" style="margin-top:4px">Solid = observed track · dashed = forecast · shaded = forecast cone / wind buffers</div>`;
  const pick = CY_LIST.find(c => c.id === cySel) || CY_LIST.find(c => c.current) || null;
  if (pick) selCyclone(pick, !cySel); else renderCyIntel(null);
  clearInterval(cyTimer); cyTimer = setInterval(() => { if ($("#v-cyclone").classList.contains("on")) loadCyclones(); }, 300e3);
}
function renderCyLive() {
  const el = $("#cylive"); if (!el) return;
  const s = (cyData?.sources || []).map(x => `<span class="${x.ok ? "up" : "dn"}">${x.ok ? "●" : "○"} ${h(x.name)}</span>`).join(" ");
  const next = Math.max(0, 300 - Math.round((Date.now() - cyAt) / 1000));
  el.innerHTML = `<b class="livedot">● LIVE</b> updated ${cyAt ? ago(cyAt) : "—"} ago · next refresh ${Math.floor(next / 60)}:${String(next % 60).padStart(2, "0")} · ${s}`;
}
setInterval(() => { if ($("#v-cyclone").classList.contains("on")) renderCyLive(); }, 1000);
function renderCyStorms() {
  if (!cyStormLayer) return; cyStormLayer.clearLayers();
  CY_LIST.forEach(c => { if (c.lat == null || (!c.current && !CYST.ended && c.id !== cySel)) return; L.marker([c.lat, c.lon], { icon: stormIcon(c, c.id === cySel), zIndexOffset: c.current ? 1000 : 0 }).on("click", () => selCyclone(c, true)).addTo(cyStormLayer); });
}
$("#cylist").onclick = e => { if (e.target.closest("a")) return; const id = e.target.closest(".ev")?.dataset.id; const c = CY_LIST.find(x => x.id === id); if (c) selCyclone(c, true); };
function parseGdacsLabel(lbl, ref) {
  const m = /^(\d{1,2})\/(\d{1,2}) (\d{1,2}):(\d{2})/.exec(lbl || ""); if (!m) return null;
  const r = new Date(ref || Date.now()); let y = r.getUTCFullYear();
  if (+m[2] === 12 && r.getUTCMonth() === 0) y--; if (+m[2] === 1 && r.getUTCMonth() === 11) y++;
  return new Date(Date.UTC(y, +m[2] - 1, +m[1], +m[3], +m[4]));
}
function centroid(coords) { let a = 0, b = 0, n = 0; (coords[0] || []).forEach(p => { a += p[1]; b += p[0]; n++; }); return n ? [a / n, b / n] : null; }
async function selCyclone(c, fly = true) {
  if (!c) return;
  cySel = c.id; $$("#cylist .ev").forEach(r => r.classList.toggle("sel", r.dataset.id === c.id));
  renderCyStorms(); cyGeomLayer.clearLayers(); cyPathLayer.clearLayers();
  const path = []; const fc = [];
  const updated = new Date(c.updated).getTime();
  // observed history (NASA EONET)
  if (CYST.history && c.track?.length) {
    for (let i = 1; i < c.track.length; i++) { const a = c.track[i - 1], b = c.track[i]; L.polyline([[a.lat, a.lon], [b.lat, b.lon]], { color: ssCat(b.kt)[2], weight: 3, opacity: 0.95 }).addTo(cyGeomLayer); }
    c.track.forEach(p => { path.push([p.lat, p.lon]); L.circleMarker([p.lat, p.lon], { radius: 3, color: "#000", weight: 1, fillColor: ssCat(p.kt)[2], fillOpacity: 1 }).bindTooltip(`OBSERVED · ${new Date(p.t).toUTCString().slice(5, 22)} UTC${p.kt ? ` · ${p.kt} kt (${ssCat(p.kt)[1]})` : ""}`).addTo(cyGeomLayer); });
  }
  // official NHC forecast (cone / track / points)
  if (CYST.forecast && c.forecast) {
    L.geoJSON(c.forecast, {
      style: f => f.properties.kind === "cone" ? { color: "#ffffff", weight: 1, dashArray: "5 4", fillColor: "#ffffff", fillOpacity: 0.12 } : f.properties.kind === "windfield" ? { color: "#F0A43A", weight: 1, fillOpacity: 0.12 } : { color: "#ffffff", weight: 2, dashArray: "6 5" },
      pointToLayer: (f, ll) => { fc.push([ll.lat, ll.lng]); return L.circleMarker(ll, { radius: 5, color: "#fff", weight: 1.5, fillColor: "#A371F7", fillOpacity: 1 }); },
      onEachFeature: (f, l) => l.bindTooltip(`FORECAST (NHC) · ${h(f.properties.name || "")}<br><span class="mut">${h((f.properties.desc || "").slice(0, 160))}</span>`)
    }).addTo(cyGeomLayer);
  }
  if (fly && c.lat != null) cmap.flyTo([c.lat, c.lon], 5, { duration: 0.7 });
  renderCyIntel(c, path.concat(fc));
  // GDACS track / forecast positions / wind buffers
  if (c.gdacsEventId && (CYST.forecast || CYST.windbuf || CYST.history)) {
    try {
      const gu = `/api/tcgeom?eventid=${c.gdacsEventId}&episodeid=${c.gdacsEpisode}`;
      const g = await api(gu).catch(() => new Promise(r => setTimeout(r, 2500)).then(() => api(gu)));
      if (cySel !== c.id) return;
      const pos = {};
      (g.features || []).forEach(f => {
        const p = f.properties || {}, k = p.Class || "", gm = f.geometry;
        if (gm.type === "LineString" && (CYST.history || CYST.forecast)) {
          L.polyline(gm.coordinates.map(x => [x[1], x[0]]), { color: segCol(p.polygonlabel), weight: 3, opacity: 0.9 }).bindTooltip(`Track segment · ${h(p.polygonlabel || "")}`).addTo(cyGeomLayer);
          gm.coordinates.forEach(x => path.push([x[1], x[0]]));
        } else if (gm.type === "Polygon") {
          const t = parseGdacsLabel(p.polygonlabel, c.updated);
          const isWindbuf = /km\/h/.test(p.polygonlabel || "");
          if (t && /Green/.test(k)) { const ce = centroid(gm.coordinates); if (ce) pos[+t] = ce; }
          if (!CYST.windbuf) return;
          const col = /Red/.test(k) ? "#FF3B4E" : /Orange/.test(k) ? "#F07A2A" : "#2BD67B";
          const future = t && +t > updated;
          L.polygon(gm.coordinates.map(r => r.map(x => [x[1], x[0]])), { color: col, weight: 0.6, dashArray: future ? "4 3" : null, fillColor: col, fillOpacity: isWindbuf ? 0.2 : future ? 0.05 : 0.08 }).bindTooltip(`${future ? "FORECAST" : "OBSERVED"} wind ≥ ${/Red/.test(k) ? 120 : /Orange/.test(k) ? 90 : 60} km/h · ${h(p.polygonlabel || "")}`).addTo(cyGeomLayer);
        }
      });
      const times = Object.keys(pos).map(Number).sort((a, b) => a - b);
      const fut = times.filter(t => t > updated);
      if (CYST.forecast && fut.length) {
        const pts = [[c.lat, c.lon], ...fut.map(t => pos[t])];
        L.polyline(pts, { color: "#fff", weight: 2, dashArray: "7 6", opacity: 0.9 }).addTo(cyGeomLayer);
        fut.forEach(t => { fc.push(pos[t]); L.circleMarker(pos[t], { radius: 5, color: "#fff", weight: 1.5, fillColor: "#A371F7", fillOpacity: 1 }).bindTooltip(`<b>FORECAST</b> position · ${new Date(t).toUTCString().slice(5, 22)} UTC<br><span class="mut">GDACS (from official agency forecast)</span>`, { permanent: false }).addTo(cyGeomLayer); });
      }
      times.filter(t => t <= updated).forEach(t => path.push(pos[t]));
      if (fly) try { const all = path.concat(fc, [[c.lat, c.lon]]); if (all.length > 1) cmap.fitBounds(L.latLngBounds(all), { padding: [70, 70], maxZoom: 6 }); } catch { }
      renderCyIntel(c, path.concat(fc), fut.length);
    } catch (e) { $("#cyintel .gerr")?.remove(); $("#cyintel").insertAdjacentHTML("afterbegin", `<div class="unavail gerr">GDACS track/forecast geometry unavailable: ${h(e.message)}</div>`); }
  }
}
const PATH_CATS = ["oilterminals", "refineries", "lng", "oilfields", "nuclear", "ports", "grainports", "semis", "airports", "bases", "mines"];
function assetsInPath(pts, km = 450) {
  if (!pts.length) return [];
  const out = [];
  PATH_CATS.forEach(cat => GEO[cat].forEach(([n, la, lo, desc, syms]) => {
    let best = 1e9; pts.forEach(p => { const d = haversine(p[0], p[1], la, lo); if (d < best) best = d; });
    if (best <= km) out.push({ cat, n, la, lo, desc, syms, d: best });
  }));
  return out.sort((a, b) => a.d - b.d).slice(0, 30);
}
function renderCyIntel(c, pts = [], nFc = 0) {
  if (!c) { $("#cyintel").innerHTML = `<div class="empty">No storm selected.</div>`; return; }
  const cat = ssCat(c.windKt);
  const path = assetsInPath(pts.length ? pts : [[c.lat, c.lon]]);
  cyPathLayer.clearLayers();
  if (CYST.inpath) path.forEach(a => L.circleMarker([a.la, a.lo], { radius: 9, color: "#FF3B4E", weight: 2, fill: false, dashArray: "3 2" }).bindTooltip(`IN PATH · ${h(a.n)} · ${Math.round(a.d)} km from track`).addTo(cyPathLayer));
  let chart = "";
  if (c.track?.length > 1) {
    const W = 340, H = 90, kts = c.track.map(p => p.kt || 0), mx = Math.max(140, ...kts), t0 = +new Date(c.track[0].t), t1 = +new Date(c.track[c.track.length - 1].t) || t0 + 1;
    const X = t => ((+new Date(t) - t0) / (t1 - t0 || 1)) * (W - 30) + 28, Y = v => H - 12 - (v / mx) * (H - 20);
    chart = `<div class="sec"><h4>INTENSITY HISTORY (NASA EONET, kt)</h4><svg width="100%" viewBox="0 0 ${W} ${H}">${[34, 64, 96, 137].map(v => `<line x1="28" x2="${W}" y1="${Y(v)}" y2="${Y(v)}" stroke="${ssCat(v)[2]}" stroke-dasharray="2 3" opacity=".5"/><text x="0" y="${Y(v) + 3}" fill="${ssCat(v)[2]}" font-size="8" font-family="monospace">${ssCat(v)[1]}</text>`).join("")}<polyline fill="none" stroke="#fff" stroke-width="1.6" points="${c.track.map(p => X(p.t) + "," + Y(p.kt || 0)).join(" ")}"/>${c.track.map(p => `<circle cx="${X(p.t)}" cy="${Y(p.kt || 0)}" r="1.8" fill="${ssCat(p.kt)[2]}"/>`).join("")}</svg><div class="gl mono" style="display:flex;justify-content:space-between;color:#6B7A90;font-size:9px"><span>${new Date(t0).toUTCString().slice(5, 16)}</span><span>${new Date(t1).toUTCString().slice(5, 16)}</span></div></div>`;
  }
  const assets = c.assets?.length ? c.assets : [];
  $("#cyintel").innerHTML = `<div class="sec"><div style="display:flex;gap:6px;align-items:center">${c.current ? '<span class="livebadge">LIVE</span>' : '<span class="pill">ENDED</span>'}${(c.sources || []).map(s => `<span class="kd">${h(s)}</span>`).join(" ")}</div><h3>${h(c.name)}</h3>
   <div class="cybig"><b style="color:${cat[2]}">${cat[1]}</b><span>${c.windKt ? Math.round(c.windKt) + " kt · " + Math.round(c.windKmh || c.windKt * 1.852) + " km/h" : "wind n/a"}</span></div>
   <div class="kv"><span>Classification</span><b>${h(c.class || "—")}</b>${c.pressure ? `<span>Central pressure</span><b>${h(c.pressure)} mb</b>` : ""}${c.movement ? `<span>Movement</span><b>${h(c.movement)}</b>` : ""}<span>Position</span><b>${c.lat?.toFixed(1)}°, ${c.lon?.toFixed(1)}°</b>${c.alert ? `<span>GDACS alert</span><b>${h(c.alert)}</b>` : ""}${c.exposure ? `<span>Exposure</span><b>${h(c.exposure)}</b>` : ""}${c.country ? `<span>Countries</span><b>${h(c.country)}</b>` : ""}${c.region ? `<span>Market region</span><b>${h(c.region)}</b>` : ""}<span>Forecast positions</span><b>${nFc || (c.forecast ? "NHC official" : "none published")}</b><span>Last update</span><b>${new Date(c.updated).toUTCString().slice(5, 22)} UTC</b></div></div>
  ${chart}
  <div class="sec"><h4>ASSETS IN THE STORM'S PATH <span>≤450 km from observed/forecast track</span></h4>${path.length ? path.map(a => `<div class="ar" style="grid-template-columns:1fr 64px auto"><span><i class="sw" style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${GEOMETA[a.cat][1]};margin-right:5px"></i><b style="font-size:11px">${h(a.n)}</b><br><span class="wy">${h(GEOMETA[a.cat][0])} · ${h(a.desc)}</span></span><span class="q">${Math.round(a.d)} km</span><span>${(a.syms || "").split(",").filter(Boolean).slice(0, 2).map(s => `<span class="tk" data-s="${h(s)}">${h(s)}</span>`).join(" ")}</span></div>`).join("") : '<div class="mut">No mapped energy, nuclear, port or industrial assets within 450 km.</div>'}</div>
  <div class="sec"><h4>TRADABLE EXPOSURE</h4>${assets.map(assetRow).join("") || '<div class="mut">Open ocean — no direct market mapping.</div>'}</div>
  ${assets[0] ? `<div class="sec"><h4>ONE-CLICK TRADE</h4><div class="links">${tradeLinks(assets[0].s)}</div></div>` : ""}
  <div class="sec"><h4>OFFICIAL PRODUCTS</h4><div class="links">${c.link ? `<a class="lnk" target="_blank" href="${h(c.link)}">Advisory / report ↗</a>` : ""}${c.graphics ? `<a class="lnk" target="_blank" href="${h(c.graphics)}">NHC cone & models ↗</a>` : ""}${c.gdacsEventId ? `<a class="lnk" target="_blank" href="https://www.gdacs.org/report.aspx?eventtype=TC&eventid=${c.gdacsEventId}">GDACS report ↗</a>` : ""}<a class="lnk" target="_blank" href="https://www.metoc.navy.mil/jtwc/jtwc.html">JTWC ↗</a><a class="lnk" target="_blank" href="https://www.nhc.noaa.gov/">NHC ↗</a><a class="lnk" target="_blank" href="https://zoom.earth/">Zoom Earth ↗</a></div>
  <p class="note" style="margin-top:8px">Forecast positions and cones are official agency forecasts redistributed by NHC/GDACS (JTWC, RSMCs). Model spaghetti tracks are not in these free feeds, so none are drawn rather than invented.</p></div>
  <div class="sec"><h4>PLAYBOOK</h4>${["hurr-energy", "hurr-revision", "hurr-ri", "hurr-insure"].map(id => { const s = STRATS.find(x => x.id === id); return `<div class="sc" data-st="${id}" style="padding:6px 0;border:0"><div><div class="n" style="font-size:11.5px">${h(s.name)}</div><div class="c">${s.horizon} · ${s.diff}</div></div><span class="lnk">Open →</span></div>`; }).join("")}</div>`;
  const syms = [...new Set(path.flatMap(a => (a.syms || "").split(",").filter(Boolean)))]; if (syms.length) pollQuotes(syms.slice(0, 20));
}
$("#cyintel").onclick = e => { const s = e.target.closest(".sy,.tk")?.dataset.s; if (s) { showTab("terminal"); return loadChart(TC, s); } const st = e.target.closest("[data-st]")?.dataset.st; if (st) { store.set("strat", st); showTab("strategies"); } };
onShow.cyclone = () => { loadCyclones(); setTimeout(() => cmap && cmap.invalidateSize(), 60); };


/* ================= MARKETS ================= */
let MC;
function spark(closes, w = 80, hgt = 20) {
  if (!closes?.length) return "";
  const mn = Math.min(...closes), mx = Math.max(...closes), r = mx - mn || 1;
  const pts = closes.map((v, i) => `${(i / (closes.length - 1) * w).toFixed(1)},${(hgt - (v - mn) / r * hgt).toFixed(1)}`).join(" ");
  const col = closes[closes.length - 1] >= closes[0] ? "#2BD67B" : "#F2495C";
  return `<svg width="${w}" height="${hgt}"><polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.2"/></svg>`;
}
function renderWL() {
  if (!$("#wlgroups").innerHTML) {
    $("#wlgroups").innerHTML = Object.keys(GROUPS).map(g => `<button data-g="${g}">${g}</button>`).join("");
    $("#wlgroups").onclick = e => { const g = e.target.dataset.g; if (g) { store.set("wlgroup", g); renderWL(); pollQuotes(GROUPS[g]); } };
  }
  const g = store.get("wlgroup", "Defense US");
  $$("#wlgroups button").forEach(b => b.classList.toggle("on", b.dataset.g === g));
  const linked = s => allEvents().filter(e => (e.assets || []).some(a => a.s === s) && e.score >= 35).length;
  $("#wltable").innerHTML = `<table><tr><th>SYMBOL</th><th>NAME</th><th class="n">LAST</th><th class="n">CHG%</th><th>1D</th><th class="n">EVENTS</th><th></th></tr>${(GROUPS[g] || []).map(s => { const q = S.quotes[s]; const n = linked(s); return `<tr class="r ${MC?.sym === s ? "sel" : ""}" data-s="${s}"><td><b class="mono">${s}</b></td><td class="mut" style="max-width:150px;overflow:hidden;text-overflow:ellipsis">${h(NAMES[s] || q?.name || "")}</td><td class="n">${q ? fmtP(q.price) : "—"}</td><td class="n ${q ? cls(q.chgPct) : ""}">${q ? fmtC(q.chgPct) : "—"}</td><td>${spark(q?.closes)}</td><td class="n">${n ? `<span class="lv HIGH">${n}</span>` : '<span class="mut">0</span>'}</td><td><a class="lnk" target="_blank" href="${(BROKERS[store.get("broker", "tradingview")] || BROKERS.tradingview).u(s)}">Trade ↗</a></td></tr>`; }).join("")}</table>${quoteErr ? `<div class="unavail">Market data unavailable: ${h(quoteErr)}</div>` : ""}<p class="note pad">Quotes: Yahoo Finance public endpoints, may be delayed 15+ min depending on exchange. EVENTS = live events currently mapped to this asset.</p>`;
}
$("#wltable").onclick = e => { if (e.target.closest("a")) return; const s = e.target.closest("tr.r")?.dataset.s; if (s) { loadChart(MC, s); $("#psym").value = s; renderWL(); } };
onShow.markets = () => { if (!MC) { MC = makeChart($("#mchart"), $("#mchtf"), $("#mchsym"), $("#mchname"), $("#mchpx"), $("#mchtrade")); MC.tf = "1M"; $$("#mchtf button").forEach(b => b.classList.toggle("on", b.dataset.tf === "1M")); loadChart(MC, GROUPS[store.get("wlgroup", "Defense US")][0]); } renderWL(); renderPaper(); pollQuotes(GROUPS[store.get("wlgroup", "Defense US")]); };

/* paper trading */
const paper = () => store.get("paper", { cash: 100000, start: 100000, pos: {}, log: [] });
function renderPaper() {
  if (!$("#paper").dataset.init) {
    $("#paper").dataset.init = 1;
    $("#paper").innerHTML = `<div class="pform"><input id="psym" placeholder="Symbol" value="LMT"><input id="pqty" type="number" value="10" min="0.0001" step="any"><button class="btn pri" data-side="1">BUY</button><button class="btn danger" data-side="-1">SELL / SHORT</button><button class="btn sm" id="preset" style="margin-left:auto">Reset $100k</button></div><div class="pstat" id="pstat"></div><div id="ppos"></div>`;
    $("#paper").onclick = async e => {
      const side = +e.target.dataset.side;
      if (e.target.id === "preset") { if (confirm("Reset paper account to $100,000?")) { store.set("paper", { cash: 100000, start: 100000, pos: {}, log: [] }); renderPaper(); } return; }
      const close = e.target.dataset.close;
      if (!side && !close) return;
      const sym = (close || $("#psym").value).trim().toUpperCase(); if (!sym) return;
      if (!S.quotes[sym]) await pollQuotes([sym]);
      const q = S.quotes[sym]; if (!q?.price) return toast({ level: "WATCH", title: `No live price for ${sym} — cannot simulate fill` });
      const P = paper(); const cur = P.pos[sym] || { qty: 0, avg: 0 };
      let qty = close ? -cur.qty : side * Math.abs(+$("#pqty").value || 0); if (!qty) return;
      const nq = cur.qty + qty;
      if (Math.sign(nq) === Math.sign(cur.qty) && Math.abs(nq) > Math.abs(cur.qty) || cur.qty === 0) cur.avg = (cur.avg * cur.qty + q.price * qty) / nq;
      else if (Math.sign(nq) !== Math.sign(cur.qty) && nq !== 0) cur.avg = q.price;
      P.cash -= qty * q.price; cur.qty = nq;
      if (Math.abs(nq) < 1e-9) delete P.pos[sym]; else P.pos[sym] = cur;
      P.log.unshift({ t: Date.now(), sym, qty, px: q.price }); P.log = P.log.slice(0, 200);
      store.set("paper", P); renderPaper();
      toast({ level: "WATCH", title: `Paper ${qty > 0 ? "BUY" : "SELL"} ${Math.abs(qty)} ${sym} @ ${fmtP(q.price)} (simulated)` });
    };
  }
  const P = paper(); let mv = 0;
  const rows = Object.entries(P.pos).map(([s, p]) => { const px = S.quotes[s]?.price ?? p.avg; const val = p.qty * px; mv += val; const pnl = (px - p.avg) * p.qty; return `<tr><td><b class="mono">${s}</b></td><td class="n">${p.qty}</td><td class="n">${fmtP(p.avg)}</td><td class="n">${fmtP(px)}</td><td class="n ${cls(pnl)}">${pnl >= 0 ? "+" : ""}${pnl.toFixed(2)}</td><td class="n ${cls(pnl)}">${fmtC((px / p.avg - 1) * 100 * Math.sign(p.qty))}</td><td><button class="btn sm" data-close="${s}">Close</button></td></tr>`; }).join("");
  const eq = P.cash + mv, pnl = eq - P.start;
  $("#pstat").innerHTML = `<div><span>EQUITY</span><b>$${eq.toLocaleString(undefined, { maximumFractionDigits: 0 })}</b></div><div><span>CASH</span><b>$${P.cash.toLocaleString(undefined, { maximumFractionDigits: 0 })}</b></div><div><span>TOTAL P&amp;L</span><b class="${cls(pnl)}">${pnl >= 0 ? "+" : ""}$${pnl.toFixed(0)} (${fmtC(pnl / P.start * 100)})</b></div><div><span>EXPOSURE</span><b>$${Math.abs(mv).toLocaleString(undefined, { maximumFractionDigits: 0 })}</b></div>`;
  $("#ppos").innerHTML = (rows ? `<table><tr><th>POS</th><th class="n">QTY</th><th class="n">AVG</th><th class="n">LAST</th><th class="n">P&amp;L</th><th class="n">%</th><th></th></tr>${rows}</table>` : `<div class="empty">No open positions. Pick a symbol, set quantity, BUY or SELL — fills use the live quote.</div>`) + (P.log.length ? `<div class="pad"><div class="mut" style="margin-bottom:4px">HISTORY</div>${P.log.slice(0, 12).map(l => `<div class="mono" style="font-size:10.5px;color:#8593a8">${new Date(l.t).toLocaleString()} · ${l.qty > 0 ? "BUY" : "SELL"} ${Math.abs(l.qty)} ${l.sym} @ ${fmtP(l.px)}</div>`).join("")}</div>` : "");
}

/* ================= PREDICTION MARKETS ================= */
const PMTAGS = { geopolitics: "Geopolitics", "middle-east": "Middle East", ukraine: "Ukraine", china: "China", world: "World", economy: "Economy", commodities: "Commodities", weather: "Weather", climate: "Climate" };
const PMSRC = { auto: "Auto", polymarket: "Polymarket", kalshi: "Kalshi", manifold: "Manifold" };
async function loadPM() {
  if (!$("#pmtags").innerHTML) {
    $("#pmtags").innerHTML = Object.entries(PMTAGS).map(([k, n]) => `<button data-k="${k}">${n}</button>`).join("") + `<span style="width:10px"></span>` + Object.entries(PMSRC).map(([k, n]) => `<button data-src="${k}">${n}</button>`).join("");
    $("#pmtags").onclick = e => { const k = e.target.dataset.k, sr = e.target.dataset.src; if (k) store.set("pmtag", k); if (sr) store.set("pmsrc", sr); if (k || sr) loadPM(); };
  }
  const tag = store.get("pmtag", "geopolitics"), src = store.get("pmsrc", "auto");
  $$("#pmtags button").forEach(b => b.classList.toggle("on", b.dataset.k === tag || b.dataset.src === src));
  $("#pmlist").innerHTML = `<div class="empty">Loading prediction markets…</div>`;
  try {
    const d = await api("/api/predict?tag=" + tag + (src !== "auto" ? "&src=" + src : ""));
    const evs = (d.events || []).filter(e => e.markets?.length);
    const note = `<div class="pm" style="grid-column:1/-1;padding:8px 10px"><span class="mut">Source: <b style="color:#fff">${h(PMSRC[d.source] || d.source)}</b>${d.source === "manifold" ? " (play-money market)" : ""}${(d.errors || []).length ? ` · fallback used because ${h(d.errors.join(" · "))}` : ""}. Prices are market-implied probabilities, not forecasts. Check exact resolution rules before trading.</span></div>`;
    $("#pmlist").innerHTML = note + (evs.map(e => `<div class="pm"><h5><a target="_blank" href="${h(e.url)}">${h(e.title)} ↗</a></h5><div class="mut" style="margin-bottom:6px">${e.vol24 ? `24h vol ${Math.round(e.vol24).toLocaleString()} · ` : ""}${e.liq ? `liquidity/volume ${Math.round(e.liq).toLocaleString()}` : ""}${e.end ? " · ends " + h(e.end.slice(0, 10)) : ""}</div>${e.markets.map(m => `<div class="pmr"><span>${h(m.q)}</span><div class="b"><i style="width:${(m.yes * 100).toFixed(0)}%"></i></div><b>${(m.yes * 100).toFixed(0)}%</b></div>`).join("")}</div>`).join("") || `<div class="empty">No active markets for this topic.</div>`);
  } catch (e) { $("#pmlist").innerHTML = `<div class="unavail">Prediction markets unavailable: ${h(e.message)}</div>`; }
}
onShow.predict = loadPM;

/* ================= FORECAST CENTER ================= */
const MODELS = { ecmwf_ifs025: ["ECMWF IFS", "#58A6FF"], gfs_seamless: ["NOAA GFS", "#F0A43A"], icon_seamless: ["DWD ICON", "#2BD67B"], gem_seamless: ["CMC GEM", "#A371F7"], ukmo_seamless: ["UK Met Office", "#39C5CF"], meteofrance_seamless: ["Météo-France", "#F2495C"], jma_seamless: ["JMA", "#D4A55A"] };
const FCVARS = { temperature_2m: ["Temperature 2m", "°C", 6], apparent_temperature: ["Apparent temperature", "°C", 6], wind_speed_10m: ["Wind speed 10m", "km/h", 20], wind_gusts_10m: ["Wind gusts", "km/h", 30], precipitation: ["Precipitation", "mm", 4], pressure_msl: ["Pressure MSL", "hPa", 10], relative_humidity_2m: ["Humidity", "%", 30], cloud_cover: ["Cloud cover", "%", 50], snowfall: ["Snowfall", "cm", 3], cape: ["CAPE", "J/kg", 1500] };
const PRESETS = [["New York — gas/power demand", 40.71, -74.01], ["Chicago — Midwest demand", 41.88, -87.63], ["Dallas — ERCOT power", 32.78, -96.8], ["Houston — Gulf energy", 29.76, -95.37], ["New Orleans — Gulf refining", 29.95, -90.07], ["Atlanta — SE demand", 33.75, -84.39], ["Miami — hurricane coast", 25.76, -80.19], ["London — UK gas", 51.51, -0.13], ["Frankfurt — EU power", 50.11, 8.68], ["Paris", 48.86, 2.35], ["Rotterdam — TTF/ARA", 51.92, 4.48], ["Tokyo — JKM LNG demand", 35.68, 139.69], ["Des Moines — Corn Belt", 41.59, -93.62], ["Kansas — HRW wheat", 38.5, -98.5], ["Sorriso, MT — Brazil soy", -12.55, -55.71], ["Varginha, MG — Brazil coffee", -21.55, -45.43], ["Ribeirão Preto — sugar cane", -21.18, -47.81], ["Abidjan — cocoa belt", 5.36, -4.0], ["Kropyvnytskyi — Ukraine wheat", 48.51, 32.26], ["Ludhiana — Punjab wheat/rice", 30.9, 75.85], ["Rosario — Argentina soy", -32.95, -60.65], ["Singapore — shipping hub", 1.29, 103.85]];
const FC = { loc: store.get("fcloc", { name: PRESETS[0][0], lat: PRESETS[0][1], lon: PRESETS[0][2] }), v: store.get("fcvar", "temperature_2m"), days: store.get("fcdays", 10), models: store.get("fcmodels", ["ecmwf_ifs025", "gfs_seamless", "icon_seamless", "gem_seamless"]), chart: null, series: [] };
function initFC() {
  $("#fcpreset").innerHTML = `<option value="">Presets…</option>` + PRESETS.map((p, i) => `<option value="${i}">${h(p[0])}</option>`).join("");
  $("#fcpreset").onchange = e => { const p = PRESETS[e.target.value]; if (p) { FC.loc = { name: p[0], lat: p[1], lon: p[2] }; loadFC(); } };
  $("#fcvar").innerHTML = Object.entries(FCVARS).map(([k, v]) => `<option value="${k}" ${k === FC.v ? "selected" : ""}>${v[0]}</option>`).join("");
  $("#fcvar").onchange = e => { FC.v = e.target.value; store.set("fcvar", FC.v); loadFC(); };
  $("#fcdays").innerHTML = [3, 7, 10, 14].map(d => `<button data-d="${d}" class="${d === FC.days ? "on" : ""}">${d}D</button>`).join("");
  $("#fcdays").onclick = e => { const d = +e.target.dataset.d; if (d) { FC.days = d; store.set("fcdays", d); $$("#fcdays button").forEach(b => b.classList.toggle("on", +b.dataset.d === d)); loadFC(); } };
  const rm = () => $("#fcmodels").innerHTML = Object.entries(MODELS).map(([k, [n, c]]) => `<button class="chip ${FC.models.includes(k) ? "on" : ""}" data-m="${k}" style="${FC.models.includes(k) ? `border-color:${c};color:${c}` : ""}">${n}</button>`).join("");
  rm();
  $("#fcmodels").onclick = e => { const m = e.target.dataset.m; if (!m) return; FC.models = FC.models.includes(m) ? FC.models.filter(x => x !== m) : [...FC.models, m]; if (!FC.models.length) FC.models = [m]; store.set("fcmodels", FC.models); rm(); loadFC(); };
  let gt; $("#fcq").oninput = e => { clearTimeout(gt); const v = e.target.value.trim(); if (v.length < 2) return $("#fcres").style.display = "none"; gt = setTimeout(async () => { try { const d = await api("/api/geocode?name=" + encodeURIComponent(v)); $("#fcres").innerHTML = (d.results || []).map(r => `<div data-lat="${r.latitude}" data-lon="${r.longitude}" data-n="${h(r.name + ", " + (r.country || ""))}">${h(r.name)} <span class="mut">${h([r.admin1, r.country].filter(Boolean).join(", "))}</span></div>`).join("") || '<div class="mut">No match</div>'; } catch (err) { $("#fcres").innerHTML = `<div class="mut">Geocoder unavailable — use presets or click the Weather Map</div>`; } $("#fcres").style.display = "block"; }, 300); };
  $("#fcres").onclick = e => { const d = e.target.closest("[data-lat]")?.dataset; if (d) { FC.loc = { name: d.n, lat: +d.lat, lon: +d.lon }; $("#fcres").style.display = "none"; $("#fcq").value = ""; loadFC(); } };
  FC.chart = LightweightCharts.createChart($("#fchart"), { autoSize: true, layout: { background: { color: "#0B111B" }, textColor: "#6B7A90", fontFamily: "JetBrains Mono, monospace", fontSize: 10 }, grid: { vertLines: { color: "#111a27" }, horzLines: { color: "#111a27" } }, rightPriceScale: { borderColor: "#1A2433" }, timeScale: { borderColor: "#1A2433", timeVisible: true }, crosshair: { mode: 0 } });
}
async function loadFC() {
  store.set("fcloc", FC.loc);
  const [vn, unit, thr] = FCVARS[FC.v];
  $("#fcmeta").textContent = `${FC.loc.name} · ${FC.loc.lat.toFixed(2)}, ${FC.loc.lon.toFixed(2)} · ${vn}`;
  FC.series.forEach(s => FC.chart.removeSeries(s)); FC.series = [];
  $("#fcstats").innerHTML = `<div class="empty">Loading ${FC.models.length} models…</div>`;
  $("#fchart .unavail")?.remove();
  const needT = FC.v !== "temperature_2m";
  try {
    const d = await api(`/api/wx?latitude=${FC.loc.lat}&longitude=${FC.loc.lon}&hourly=${FC.v}${needT ? ",temperature_2m" : ""}&models=${FC.models.join(",")}&forecast_days=${FC.days}&timezone=UTC`);
    const H = d.hourly, T = H.time.map(t => Math.floor(Date.parse(t + "Z") / 1000) + tzOff);
    const per = {};
    FC.models.forEach(m => { const arr = H[`${FC.v}_${m}`] || (FC.models.length === 1 ? H[FC.v] : null); if (arr && arr.some(v => v != null)) per[m] = arr; });
    Object.entries(per).forEach(([m, arr]) => { const s = FC.chart.addLineSeries({ color: MODELS[m][1], lineWidth: 2, title: MODELS[m][0], priceLineVisible: false, lastValueVisible: false }); s.setData(arr.map((v, i) => v == null ? null : { time: T[i], value: v }).filter(Boolean)); FC.series.push(s); });
    // ensemble-of-models mean & spread
    const mean = [], spread = [];
    T.forEach((t, i) => { const vals = Object.values(per).map(a => a[i]).filter(v => v != null); if (vals.length) { const mu = vals.reduce((a, b) => a + b, 0) / vals.length; mean.push({ time: t, value: +mu.toFixed(2) }); spread.push(Math.max(...vals) - Math.min(...vals)); } });
    if (Object.keys(per).length > 1) { const ms = FC.chart.addLineSeries({ color: "#ffffff", lineWidth: 1, lineStyle: 2, title: "Mean", priceLineVisible: false, lastValueVisible: false }); ms.setData(mean); FC.series.push(ms); }
    FC.chart.timeScale().fitContent();
    // daily table
    const days = {};
    H.time.forEach((t, i) => { const k = t.slice(0, 10); const vals = Object.values(per).map(a => a[i]).filter(v => v != null); if (!vals.length) return; (days[k] = days[k] || []).push(vals); });
    const avgSpread = spread.length ? spread.reduce((a, b) => a + b, 0) / spread.length : 0;
    const agree = Math.max(0, Math.min(100, Math.round(100 * (1 - avgSpread / thr))));
    // HDD/CDD per model (base 18°C, from hourly temperature)
    let dd = "";
    if (FC.v === "temperature_2m" || needT) {
      const rows = FC.models.map(m => { const arr = H[`temperature_2m_${m}`] || (FC.models.length === 1 ? H.temperature_2m : null); if (!arr) return ""; const byDay = {}; H.time.forEach((t, i) => { if (arr[i] != null) (byDay[t.slice(0, 10)] = byDay[t.slice(0, 10)] || []).push(arr[i]); }); let hdd = 0, cdd = 0; Object.values(byDay).forEach(v => { const mu = v.reduce((a, b) => a + b, 0) / v.length; hdd += Math.max(0, 18 - mu); cdd += Math.max(0, mu - 18); }); return `<tr><td style="color:${MODELS[m][1]}">${MODELS[m][0]}</td><td class="n">${hdd.toFixed(1)}</td><td class="n">${cdd.toFixed(1)}</td></tr>`; }).join("");
      dd = `<div class="sec"><h4>DEGREE DAYS · ${FC.days}-DAY TOTAL (base 18°C)</h4><table><tr><th>MODEL</th><th class="n">HDD</th><th class="n">CDD</th></tr>${rows}</table><p class="note" style="margin-top:6px">Higher HDD = more heating demand (bullish natural gas in winter). Higher CDD = more cooling/power demand. Compare across model runs to spot revisions — see strategy “Degree-Day Surprise”.</p></div>`;
    }
    const agCol = agree >= 75 ? "#2BD67B" : agree >= 50 ? "#F0C03A" : "#FF3B4E";
    $("#fcstats").innerHTML = `<div class="stat"><div><span>MODELS</span><b>${Object.keys(per).length}/${FC.models.length}</b></div><div><span>AVG SPREAD</span><b>${avgSpread.toFixed(1)} ${unit}</b></div><div><span>AGREEMENT</span><b style="color:${agCol}">${agree}%</b></div></div>
    <div class="sec"><h4>DAILY CONSENSUS (MODEL MEAN · RANGE)</h4><table><tr><th>DATE</th><th class="n">MEAN</th><th class="n">MIN–MAX</th><th class="n">SPREAD</th></tr>${Object.entries(days).map(([k, v]) => { const flat = v.flat(); const ms = v.map(x => x.reduce((a, b) => a + b, 0) / x.length); const mu = ms.reduce((a, b) => a + b, 0) / ms.length; const sp = v.reduce((a, x) => a + (Math.max(...x) - Math.min(...x)), 0) / v.length; const agg = FC.v === "precipitation" || FC.v === "snowfall"; const tot = agg ? FC.models.map(m => (per[m] || []).filter((_, i) => H.time[i].startsWith(k)).reduce((a, b) => a + (b || 0), 0)) : null; return `<tr><td>${k.slice(5)}</td><td class="n">${agg ? (tot.reduce((a, b) => a + b, 0) / tot.length).toFixed(1) + " Σ" : mu.toFixed(1)}</td><td class="n">${agg ? Math.min(...tot).toFixed(1) + "–" + Math.max(...tot).toFixed(1) : Math.min(...flat).toFixed(1) + "–" + Math.max(...flat).toFixed(1)}</td><td class="n" style="color:${sp > thr ? "#FF3B4E" : sp > thr / 2 ? "#F0C03A" : "#2BD67B"}">${sp.toFixed(1)}</td></tr>`; }).join("")}</table></div>${dd}
    <div class="sec"><p class="note">Deterministic model output via Open-Meteo (CC BY 4.0). Mean/spread are computed across the selected deterministic models (multi-model ensemble), not an official ensemble product. Times shown in your local time. ${Object.keys(per).length < FC.models.length ? "Some models do not cover this location/horizon and are omitted." : ""}</p></div>`;
  } catch (e) { $("#fcstats").innerHTML = `<div class="unavail">Open-Meteo unavailable: ${h(e.message)}. Last successful data is not available for this query; try again shortly (free API rate limits reset each minute).</div>`; }
}
onShow.forecast = () => { if (!FC.chart) initFC(); loadFC(); };

/* ================= STRATEGIES ================= */
let stCat = "ALL";
function renderStrats() {
  const cats = ["ALL", ...new Set(STRATS.map(s => s.cat))];
  $("#stcats").innerHTML = cats.map(c => `<button class="chip ${stCat === c ? "on" : ""}" data-c="${c}">${c}<i>${c === "ALL" ? STRATS.length : STRATS.filter(s => s.cat === c).length}</i></button>`).join("");
  const sigs = {}; STRATS.forEach(s => { try { sigs[s.id] = s.signal(S); } catch { sigs[s.id] = { on: false, why: "—" }; } });
  const act = Object.values(sigs).filter(x => x.on).length;
  $("#stmeta").textContent = `${STRATS.length} strategies · ${act} live signal${act === 1 ? "" : "s"}`;
  const sel = store.get("strat", STRATS[0].id);
  $("#stlist").innerHTML = STRATS.filter(s => stCat === "ALL" || s.cat === stCat).sort((a, b) => sigs[b.id].on - sigs[a.id].on).map(s => `<div class="sc ${s.id === sel ? "sel" : ""}" data-id="${s.id}"><div><div class="n">${h(s.name)}</div><div class="c">${s.cat} · ${s.horizon} · risk ${s.risk} · ${s.diff}</div></div><span class="sig ${sigs[s.id].on ? "on" : "off"}">${sigs[s.id].on ? "● SIGNAL" : "IDLE"}</span></div>`).join("");
  const s = STRATS.find(x => x.id === sel) || STRATS[0], sg = sigs[s.id];
  const li = a => a.map(x => `<li>${h(x)}</li>`).join("");
  $("#stdetail").innerHTML = `<div class="meta"><span class="pill">${s.cat}</span><span class="pill">${s.diff}</span><span class="pill">Horizon ${s.horizon}</span><span class="pill">Risk ${s.risk}</span><span class="sig ${sg.on ? "on" : "off"}">${sg.on ? "● LIVE SIGNAL" : "IDLE"}</span></div>
  <h2>${h(s.name)}</h2><p>${h(s.idea)}</p>
  <div class="sec" style="padding:10px 0;border-color:#1b3558"><h4>CURRENT STATUS</h4><p class="note" style="font-size:11.5px;color:#9aa8bb">${h(sg.why)}</p>${sg.ev ? `<button class="btn sm pri" data-ev="${h(sg.ev.id)}" style="margin-top:6px">Open triggering event →</button>` : ""}</div>
  <h5>HOW TO RUN THIS WITH QUIET GEO INTEL</h5><div class="how"><ol>${li(s.howto)}</ol></div>
  <h5>INSTRUMENTS · ONE-CLICK</h5><div class="links">${s.markets.map(m => /^[A-Z0-9^=.\-]+$/.test(m) ? `<span class="ar" style="display:inline-flex;gap:6px;border:1px solid var(--bd2);padding:3px 6px;border-radius:2px"><span class="sy" data-s="${m}">${m}</span>${S.quotes[m] ? `<span class="${cls(S.quotes[m].chgPct)} mono" style="font-size:10px">${fmtC(S.quotes[m].chgPct)}</span>` : ""}<a target="_blank" href="${(BROKERS[store.get("broker", "tradingview")] || BROKERS.tradingview).u(m)}">↗</a></span>` : `<button class="lnk" data-goto="predict">${h(m)} →</button>`).join("")}</div>
  <h5>REQUIRED INDICATORS</h5><ul>${li(s.indicators)}</ul>
  <h5>ENTRY CONDITIONS</h5><ol>${li(s.entry)}</ol>
  <h5>CONFIRMATION SIGNALS</h5><ul>${li(s.confirm)}</ul>
  <h5>EXIT RULES</h5><ul>${li(s.exit)}</ul>
  <h5>INVALIDATION</h5><ul>${li(s.invalid)}</ul>
  <h5>RISK MANAGEMENT</h5><p>${h(s.riskm)}</p>
  <h5>HISTORICAL CONTEXT</h5><p>${h(s.example)}</p>
  <h5>BACKTEST STATUS</h5><p class="note" style="font-size:11px">Not backtested. This is a discretionary framework; live “signals” are transparent rule checks on the app's feeds, not price predictions. Practise in PAPER TRADING (Markets tab) first. Nothing here is financial advice.</p>`;
}
$("#stcats").onclick = e => { const c = e.target.closest(".chip")?.dataset.c; if (c) { stCat = c; renderStrats(); } };
$("#stlist").onclick = e => { const id = e.target.closest(".sc")?.dataset.id; if (id) { store.set("strat", id); renderStrats(); $("#stdetail").scrollTop = 0; pollQuotes(STRATS.find(s => s.id === id).markets.filter(m => /^[A-Z0-9^=.\-]+$/.test(m))); } };
$("#stdetail").onclick = e => { const s = e.target.closest(".sy")?.dataset.s; if (s) { showTab("terminal"); return loadChart(TC, s); } const ev = e.target.dataset.ev; if (ev) return openEvent(ev); const g = e.target.dataset.goto; if (g) showTab(g); };
onShow.strategies = renderStrats;

/* ================= ALERTS ================= */
function renderAlertCfg() {
  const c = cfg();
  const lvSel = (id, v) => `<select id="${id}">${Object.entries(LVN).map(([k, n]) => `<option value="${n}" ${+v === n ? "selected" : ""}>${k}+</option>`).join("")}</select>`;
  $("#alertcfg").innerHTML = `
  <div class="cfg"><div><label>Sound alerts</label><small>Siren for CRITICAL, double-beep for HIGH, chime otherwise</small></div><div style="display:flex;gap:8px;align-items:center"><div class="tg" id="cfg-sound"></div><button class="btn sm" id="testsnd">Test</button></div></div>
  <div class="cfg"><div><label>Volume</label></div><input type="range" id="cfgvol" min="0.05" max="1" step="0.05" value="${store.get("vol", 0.6)}"></div>
  <div class="cfg"><div><label>Desktop notifications</label><small>Pop-ups even when the window is in the background</small></div><button class="btn sm" id="cfgntf">${"Notification" in window && Notification.permission === "granted" && store.get("notify", false) ? "Enabled ✓" : "Enable"}</button></div>
  <div class="cfg"><div><label>War / geopolitical — minimum level</label><small>HIGH+ recommended for tradeable events</small></div>${lvSel("cfgwar", c.warMin)}</div>
  <div class="cfg"><div><label>Natural hazards — minimum level</label><small>GDACS orange ≈ HIGH, red ≈ CRITICAL; M6.5+ quakes ≈ HIGH</small></div>${lvSel("cfgnat", c.natMin)}</div>
  <div class="cfg"><div><label>Event types</label></div><div class="chips" style="border:0;padding:0" id="cfgkinds">${Object.keys(defaultCfg.kinds).map(k => `<button class="chip ${c.kinds[k] ? "on" : ""}" data-k="${k}">${KIND[k]}</button>`).join("")}</div></div>
  <div class="cfg"><div><label>Keyword triggers</label><small>Comma-separated. Always alert if a headline contains one (e.g. hormuz, taiwan, nuclear)</small></div><input type="text" id="cfgkw" value="${h(c.keywords)}" placeholder="hormuz, nuclear, taiwan"></div>
  <div class="cfg"><div><label>Region filter</label><small>Optional — only alert for these regions/countries (comma-separated)</small></div><input type="text" id="cfgrg" value="${h(c.regions)}" placeholder="iran, ukraine, gulf of mexico"></div>
  <div class="cfg"><div><label>Price-move alerts</label><small>Alert when a watched/mapped asset moves ≥ X% on the day (0 = off)</small></div><input type="number" id="cfgpm" min="0" step="0.5" value="${c.priceMove}"></div>
  <div class="cfg"><div><label>Trade button opens</label><small>Destination of one-click “Trade” buttons</small></div><select id="cfgbroker">${Object.entries(BROKERS).map(([k, b]) => `<option value="${k}" ${store.get("broker", "tradingview") === k ? "selected" : ""}>${b.n}</option>`).join("")}</select></div>
  <div class="cfg" id="tplrow" style="${store.get("broker") === "custom" ? "" : "display:none"}"><div><label>Custom broker URL</label><small>Use {sym} for the ticker</small></div><input type="text" id="cfgtpl" value="${h(store.get("brokerTpl", "https://www.tradingview.com/chart/?symbol={sym}"))}"></div>
  <div class="cfg"><div><label>Send a test alert</label></div><button class="btn sm pri" id="testalert">Fire test</button></div>`;
  renderSound();
  const save = () => { store.set("alertcfg", { warMin: +$("#cfgwar").value, natMin: +$("#cfgnat").value, kinds: Object.fromEntries($$("#cfgkinds .chip").map(b => [b.dataset.k, b.classList.contains("on")])), keywords: $("#cfgkw").value, regions: $("#cfgrg").value, priceMove: +$("#cfgpm").value || 0 }); };
  $("#alertcfg").onchange = e => { if (e.target.id === "cfgvol") store.set("vol", +e.target.value); else if (e.target.id === "cfgbroker") { store.set("broker", e.target.value); $("#tplrow").style.display = e.target.value === "custom" ? "" : "none"; renderIntel(); } else if (e.target.id === "cfgtpl") store.set("brokerTpl", e.target.value); else save(); };
  $("#alertcfg").onclick = e => {
    if (e.target.id === "cfg-sound") toggleSound();
    if (e.target.id === "testsnd") { ensureAudio(); const was = store.get("sound", true); store.set("sound", true); playAlert("CRITICAL"); store.set("sound", was); }
    if (e.target.id === "cfgntf") $("#ntf").click();
    if (e.target.dataset.k) { e.target.classList.toggle("on"); save(); }
    if (e.target.id === "testalert") { const ev = [...S.news].sort((a, b) => b.score - a.score)[0] || { id: "test", kind: "WAR", level: "HIGH", title: "Test alert — Quiet Geo Intel", assets: [{ s: "ITA", d: "up" }] }; toast(Object.assign({}, ev, { level: "CRITICAL", title: "[TEST] " + ev.title })); playAlert("CRITICAL"); }
  };
}
function renderHist() {
  const hist = store.get("hist", []);
  $("#alerthist").innerHTML = hist.length ? hist.map(a => `<div class="ev" data-id="${h(a.id)}"><div class="bar c-${a.level}"></div><div><div class="t">${h(a.title)}</div><div class="m"><span class="lv ${a.level}">${a.level}</span><span class="kd">${h(KIND[a.kind] || a.kind)}</span>${a.region ? `<span>${h(a.region)}</span>` : ""}<span>${new Date(a.t).toLocaleString()}</span>${(a.assets || []).slice(0, 5).map(x => `<a class="tk" target="_blank" href="${(BROKERS[store.get("broker", "tradingview")] || BROKERS.tradingview).u(x.s)}">${h(x.s)} ↗</a>`).join("")}</div></div></div>`).join("") : '<div class="empty">No alerts yet. New events matching your rules will appear here.</div>';
}
$("#alerthist").onclick = e => { if (e.target.closest("a")) return; const id = e.target.closest(".ev")?.dataset.id; if (id && findEvent(id)) openEvent(id); };
$("#clearhist").onclick = () => { store.set("hist", []); renderHist(); };
onShow.alerts = () => { renderAlertCfg(); renderHist(); setUnread(0); };

/* ================= SOURCES ================= */
function renderSources() {
  $("#srcs").innerHTML = `<div class="src" style="color:var(--mut);font-size:9.5px;letter-spacing:.12em;font-weight:700"><span></span><span>SOURCE</span><span>ITEMS</span><span>LAST SUCCESS</span><span>STATUS / ATTRIBUTION</span></div>` + S.status.map(s => `<div class="src"><i class="dot ${s.ok ? "ok" : "bad"}"></i><a target="_blank" href="${h(s.url)}">${h(s.name)}</a><span class="mono">${s.items}</span><span class="mono">${s.lastOk && !s.lastOk.startsWith("0001") ? ago(s.lastOk) + " ago" : "never"}</span><span>${s.ok ? `<span class="mut">${h(s.attribution)}</span>` : `<span class="e">${h(s.error)}</span> <span class="mut">· ${h(s.attribution)}</span>`}</span></div>`).join("") +
    `<div class="pad note" style="font-size:11px;line-height:1.7;margin-top:10px"><b>Map layers (loaded directly by your browser):</b> CARTO dark basemap © OpenStreetMap contributors · NASA GIBS imagery (VIIRS, MODIS, GHRSST, SMAP, IMERG, GPW) · RainViewer radar.<br>
    <b>Rate limits:</b> all requests go through this app's local cache (quotes 60 s, news 3 min, hazards 5 min, model data 15 min). Open-Meteo free tier: 10k calls/day. GDELT: 1 request per 5 s — queried every 5 min.<br>
    <b>Honesty policy:</b> if a source fails it is shown red here and the panel that depends on it shows “unavailable”. No values are invented or simulated (except your PAPER TRADING account, which is clearly labelled).<br>
    <b>Disclaimer:</b> Quiet Geo Intel is an information tool. Event-to-asset mappings are historical associations, not predictions. Nothing here is investment advice. Trading involves risk of loss.</div>`;
}
$("#quit").onclick = async () => { if (confirm("Quit Quiet Geo Intel? The local server will stop.")) { try { await fetch("/api/quit", { method: "POST" }); } catch { } document.body.innerHTML = '<div class="empty" style="margin-top:20vh;font-size:14px">Quiet Geo Intel has stopped. You can close this window.</div>'; } };
onShow.sources = () => { pollStatus(); };

/* ================= SEARCH ================= */
$("#q").oninput = e => {
  const v = e.target.value.trim().toLowerCase(); const box = $("#qres");
  if (v.length < 2) return box.style.display = "none";
  const res = [];
  TABS.forEach(([id, n]) => n.toLowerCase().includes(v) && res.push({ t: `Go to <b>${n}</b>`, a: () => showTab(id) }));
  const syms = new Set([...Object.values(GROUPS).flat(), ...allEvents().flatMap(e => (e.assets || []).map(a => a.s))]);
  [...syms].filter(s => s.toLowerCase().includes(v) || (NAMES[s] || "").toLowerCase().includes(v)).slice(0, 6).forEach(s => res.push({ t: `<b class="mono">${s}</b> <span class="mut">${h(NAMES[s] || S.quotes[s]?.name || "")} · chart</span>`, a: () => { showTab("terminal"); loadChart(TC, s); } }));
  allEvents().filter(e => (e.title + " " + (e.region || "") + " " + (e.country || "")).toLowerCase().includes(v)).slice(0, 8).forEach(e => res.push({ t: `<span class="lv ${e.level}">${e.score}</span> ${h(e.title.slice(0, 80))}`, a: () => openEvent(e.id) }));
  PRESETS.filter(p => p[0].toLowerCase().includes(v)).slice(0, 3).forEach(p => res.push({ t: `Forecast: ${h(p[0])}`, a: () => { FC.loc = { name: p[0], lat: p[1], lon: p[2] }; showTab("forecast"); } }));
  Object.keys(REGIONS).filter(r => r.toLowerCase().includes(v)).forEach(r => res.push({ t: `Map: ${r}`, a: () => { showTab("terminal"); tmap.flyTo(...REGIONS[r]); } }));
  STRATS.filter(s => s.name.toLowerCase().includes(v)).slice(0, 3).forEach(s => res.push({ t: `Strategy: ${h(s.name)}`, a: () => { store.set("strat", s.id); showTab("strategies"); } }));
  box.innerHTML = res.length ? res.map((r, i) => `<div data-i="${i}">${r.t}</div>`).join("") : '<div class="mut">No results</div>';
  box.style.display = "block"; box._res = res;
};
$("#qres").onclick = e => { const i = e.target.closest("[data-i]")?.dataset.i; if (i != null) { $("#qres")._res[i].a(); $("#qres").style.display = "none"; $("#q").value = ""; } };
document.addEventListener("click", e => { if (!e.target.closest(".search")) $("#qres").style.display = "none"; if (!e.target.closest(".fcrow")) $("#fcres").style.display = "none"; });

/* ================= KEYBOARD ================= */
document.addEventListener("keydown", e => {
  if (e.target.matches("input,select,textarea")) { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === "/") { e.preventDefault(); $("#q").focus(); }
  else if (e.key >= "0" && e.key <= "9") { const i = (+e.key + 9) % 10; TABS[i] && showTab(TABS[i][0]); }
  else if (e.key.toLowerCase() === "s") toggleSound();
  else if (e.key.toLowerCase() === "f") $("#fs").click();
  else if (e.key === "Escape") { S.sel = null; renderIntel(); }
});

/* ================= BOOT ================= */
let TC;
initTerminal();
TC = makeChart($("#tchart"), $("#chtf"), $("#chsym"), $("#chname"), $("#chpx"), $("#chtrade"));
loadChart(TC, "CL=F");
renderFeed(); renderIntel(); renderTape();
pollNews(); pollNat(); pollStatus();
setTimeout(() => pollQuotes(), 1500);
setInterval(pollNews, 60e3); setInterval(pollNat, 120e3); setInterval(() => pollQuotes(), 60e3); setInterval(pollStatus, 30e3);
setInterval(() => { if ($("#v-cyclone").classList.contains("on")) loadCyclones(); }, 600e3);
setInterval(() => fetch("/api/heartbeat").catch(() => { }), 30e3); fetch("/api/heartbeat").catch(() => { });
setInterval(() => { renderFeed(); }, 30e3);
showTab(store.get("tab", "terminal"));
