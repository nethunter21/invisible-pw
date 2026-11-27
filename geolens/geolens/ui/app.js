/* GeoLens front-end */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (p, d = 1) => (p * 100).toFixed(d) + "%";
const api = async (path, body, raw) => {
  const opt = body === undefined ? {} : { method: "POST", body: raw ? body : JSON.stringify(body), headers: raw ? {} : { "Content-Type": "application/json" } };
  const r = await fetch(path, opt);
  return r.json();
};
const toast = (msg, ms = 2600) => { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms); };
const openExternal = (url) => api("/api/open", { url });

const S = { job: null, result: null, log: [], map: null, layers: {}, overlay: "none", measuring: null, status: null };

/* ------------------------------------------------------------ model status */
async function pollStatus() {
  try {
    const s = await api("/api/status");
    S.status = s;
    const pill = $("#modelPill"), m = s.model;
    pill.className = "pill";
    let txt = "vision off";
    if (m) {
      const name = (s.models[m.key] || m.key).split(" (")[0];
      if (m.status === "ready") { pill.classList.add("ready"); txt = `${name} · ${m.device}`; }
      else if (m.status === "downloading") { pill.classList.add("busy"); txt = `Downloading model ${m.download.done}/${m.download.total} · ${m.download.file}`; }
      else if (m.status === "loading") { pill.classList.add("busy"); txt = `Loading ${name}…`; }
      else if (m.status === "unavailable") { pill.classList.add("bad"); txt = "Vision model unavailable"; pill.title = m.error || ""; }
      else txt = name;
    }
    pill.querySelector("span").textContent = txt;
    if (!m || m.status !== "ready") setTimeout(pollStatus, 1500);
  } catch { setTimeout(pollStatus, 3000); }
}

/* ------------------------------------------------------------ upload */
function show(id) { for (const s of ["landing", "loading", "result"]) $("#" + s).hidden = s !== id; }

async function analyze(file) {
  if (!file || !file.type.startsWith("image/")) return toast("Please choose an image file");
  const buf = await file.arrayBuffer();
  $("#loadImg").src = URL.createObjectURL(file);
  $("#liveSteps").innerHTML = ""; $("#loadBar").style.width = "2%"; $("#loadStage").textContent = "Uploading…";
  show("loading");
  $("#logBtn").disabled = false; S.log = []; updateLogCount();
  const r = await api("/api/analyze?name=" + encodeURIComponent(file.name || "pasted.png"), buf, true);
  if (r.error) { toast(r.error); show("landing"); return; }
  S.job = r.job;
  poll(0);
}

async function poll(since) {
  const r = await api(`/api/job/${S.job}?since=${since}`);
  $("#loadStage").textContent = r.stage + "…";
  $("#loadBar").style.width = Math.max(3, r.progress * 100) + "%";
  for (const e of r.entries) {
    S.log.push(e);
    const li = document.createElement("li");
    li.className = e.level;
    li.innerHTML = `<b>${esc(e.title)}</b>${e.method ? `<br><small>${esc(e.method)}</small>` : ""}`;
    $("#liveSteps").prepend(li);
  }
  updateLogCount();
  if (!r.done) return setTimeout(() => poll(since + r.entries.length), 400);
  S.log = r.log || S.log; updateLogCount();
  if (r.error || !r.result) { toast("Analysis failed: " + (r.error || "unknown")); openDrawer(); show("landing"); return; }
  S.result = r.result;
  render(r.result);
}

/* ------------------------------------------------------------ render */
function render(R) {
  show("result");
  $("#newBtn").hidden = false; $("#exportBtn").hidden = false;
  const L = R.location;
  $("#photo").src = R.image.src;
  // answer
  const near = L.nearest_city ? `${L.nearest_city.name}, ` : "";
  $("#ansPlace").textContent = near + L.country;
  $("#ansCoords").textContent = `${L.lat.toFixed(5)}, ${L.lon.toFixed(5)}  ±${L.radius_km} km`;
  $("#confRing").style.setProperty("--p", Math.round(L.confidence * 100));
  $("#confPct").textContent = Math.round(L.confidence * 100) + "%";
  $("#confLbl").textContent = L.confidence_label + " confidence";
  $("#ansMethod").textContent = "Pinned by: " + L.method + " · source: " + L.source;
  $("#reasoning").innerHTML = R.reasoning.map((t) => `<li>${esc(t)}</li>`).join("");
  // attention select
  const sel = $("#heatSel");
  sel.innerHTML = (R.attention || []).map((m, i) => `<option value="${i}">${esc(m.label)}</option>`).join("");
  setOverlay(S.overlay);
  renderMap(R);
  renderTabs(R);
  renderLog();
}

function setOverlay(ov) {
  S.overlay = ov;
  $$("#overlaySeg button").forEach((b) => b.classList.toggle("on", b.dataset.ov === ov));
  const R = S.result; if (!R) return;
  const heat = $("#heat"), svg = $("#ovl"), hint = $("#viewerHint");
  const W = R.image.work_w, H = R.image.work_h;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.innerHTML = ""; heat.hidden = true; $("#heatSel").hidden = true; hint.textContent = "";
  if (ov === "heat") {
    const maps = R.attention || [];
    if (!maps.length) { hint.textContent = "No attention map (vision model not available)."; return; }
    $("#heatSel").hidden = maps.length < 2;
    const m = maps[+$("#heatSel").value || 0];
    heat.src = m.png; heat.hidden = false;
    hint.textContent = "Bright = image patches that pushed the model towards this answer. Top regions: " + m.regions.slice(0, 3).map((r) => `${r.region} ${pct(r.share, 0)}`).join(", ");
  } else if (ov === "crops") {
    const v = (R.vision && R.vision.views) || [];
    if (!v.length) { hint.textContent = "No crop analysis available."; return; }
    const crops = v.slice(1).sort((a, b) => a.share_of_top - b.share_of_top);
    const max = Math.max(...v.map((x) => x.share_of_top));
    for (const c of crops) {
      const [x0, y0, x1, y1] = c.box, a = c.share_of_top / max;
      svg.insertAdjacentHTML("beforeend", `<rect x="${x0 + 3}" y="${y0 + 3}" width="${x1 - x0 - 6}" height="${y1 - y0 - 6}" fill="rgba(94,234,212,${0.05 + a * 0.22})" stroke="rgba(94,234,212,${0.3 + a * 0.7})" stroke-width="${2 + a * 3}" rx="8"/>
        <text x="${x0 + 12}" y="${y0 + 30}" fill="#fff" font-size="${Math.max(14, W / 45)}" font-weight="700" style="paint-order:stroke;stroke:#000;stroke-width:4px">${esc(c.view)} · ${pct(c.share_of_top, 0)} · ${esc(c.top[0][1])}</text>`);
    }
    hint.textContent = "Each crop was classified separately; % = share of the weight behind the winning country. Full image: " + pct(v[0].share_of_top, 0);
  } else if (ov === "text") {
    const items = R.ocr.items || [];
    if (!items.length) { hint.textContent = "No readable text was found."; return; }
    for (const it of items) {
      const [x0, y0, x1, y1] = it.box;
      svg.insertAdjacentHTML("beforeend", `<rect x="${x0 - 2}" y="${y0 - 2}" width="${x1 - x0 + 4}" height="${y1 - y0 + 4}" rx="3" fill="rgba(56,189,248,.12)" stroke="#38bdf8" stroke-width="2.5"><title>${esc(it.text)} (${it.score})</title></rect>`);
    }
    hint.textContent = `${items.length} text regions read by OCR: ` + items.slice(0, 8).map((i) => `“${i.text}”`).join(", ");
  }
  drawMeasure();
}

/* ------------------------------------------------------------ map */
function renderMap(R) {
  if (!S.map) {
    S.map = L.map("map", { zoomControl: true, worldCopyJump: true }).setView([20, 0], 2);
    const esri = (svc, attr, z = 19) => L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`, { attribution: attr, maxZoom: z });
    const dark = L.layerGroup([esri("Canvas/World_Dark_Gray_Base", "Esri, OpenStreetMap contributors", 16), esri("Canvas/World_Dark_Gray_Reference", "", 16)]);
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap contributors", maxZoom: 19 });
    const sat = L.layerGroup([esri("World_Imagery", "Esri World Imagery"), esri("Reference/World_Boundaries_and_Places", "")]);
    const topo = L.tileLayer("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", { attribution: "© OpenTopoMap (CC-BY-SA)", maxZoom: 17 });
    dark.addTo(S.map);
    L.control.layers({ Dark: dark, Streets: osm, "Satellite + labels": sat, Terrain: topo }).addTo(S.map);
    L.control.scale({ imperial: false }).addTo(S.map);
    S.layers.main = L.layerGroup().addTo(S.map);
    S.layers.sun = L.layerGroup().addTo(S.map);
  }
  S.layers.main.clearLayers(); S.layers.sun.clearLayers();
  const Lc = R.location;
  const pin = L.circleMarker([Lc.lat, Lc.lon], { radius: 9, color: "#04141a", weight: 3, fillColor: "#5eead4", fillOpacity: 1 }).bindPopup(`<b>${esc($("#ansPlace").textContent)}</b><br>${esc(Lc.method)}`);
  const circ = L.circle([Lc.lat, Lc.lon], { radius: Lc.radius_km * 1000, color: "#5eead4", weight: 1.5, fillOpacity: 0.08 });
  S.layers.main.addLayer(circ); S.layers.main.addLayer(pin);
  for (const c of (R.cities || []).slice(0, 8)) {
    S.layers.main.addLayer(L.circleMarker([c.lat, c.lon], { radius: 4 + 10 * Math.sqrt(c.score || 0), color: "#38bdf8", weight: 1, fillOpacity: 0.35 })
      .bindTooltip(`${esc(c.name)} (${esc(c.cc)}) ${pct(c.score || 0)}`));
  }
  for (const g of R.geocoded || []) S.layers.main.addLayer(L.circleMarker([g.lat, g.lon], { radius: 5, color: "#fbbf24", weight: 2, fillOpacity: 0.6 }).bindTooltip("Geocoded text: " + esc(g.query)));
  setTimeout(() => { S.map.invalidateSize(); S.map.fitBounds(L.latLng(Lc.lat, Lc.lon).toBounds(Lc.radius_km * 2000), { maxZoom: 13, padding: [20, 20] }); }, 50);
}

/* ------------------------------------------------------------ tabs */
function renderTabs(R) {
  const pane = (n) => $(`.tabpane[data-pane="${n}"]`);
  // Locations
  let h = "<h4>Countries</h4>";
  for (const c of R.countries.slice(0, 6)) {
    h += `<div class="row"><span class="tag">${esc(c.iso)}</span><div class="grow"><div class="name">${esc(c.name)}</div>
      <div class="sub">${c.visual != null ? "visual " + pct(c.visual) + " · " : ""}${esc(c.support.slice(0, 4).join(" · ") || "visual similarity only")}</div></div>
      <div class="meter"><i style="width:${c.prob * 100}%"></i></div><span class="pct">${pct(c.prob)}</span></div>`;
  }
  if ((R.cities || []).length) {
    h += "<h4>Closest-matching cities / regions</h4>";
    for (const c of R.cities.slice(0, 8)) h += `<div class="row"><div class="grow"><div class="name">${esc(c.name)}</div><div class="sub">${esc(c.cc)} · ${c.lat.toFixed(3)}, ${c.lon.toFixed(3)} · pop ${(c.pop || 0).toLocaleString()}</div></div><div class="meter"><i style="width:${(c.score || 0) * 100}%"></i></div><span class="pct">${pct(c.score || 0)}</span></div>`;
  }
  pane("loc").innerHTML = h;

  // Clues
  h = "";
  const probes = (R.vision && R.vision.probes) || [];
  if (!probes.length) h += `<div class="notice">Visual clue recognition needs the vision model (see the status pill). Text, metadata and reverse search clues are still shown.</div>`;
  const top = R.countries[0].iso;
  for (const p of probes.filter((p) => p.id !== "scene").sort((a, b) => b.detected - a.detected || b.prob * b.weight - a.prob * a.weight)) {
    const hit = p.countries.includes(top);
    h += `<div class="clue ${p.detected ? "" : "weak"}"><div class="clue-h"><span class="t">${esc(p.title)}</span><span class="l">${esc(p.label)}</span>
      <span class="tag ${p.detected ? "ok" : ""}">${p.detected ? "detected" : "weak"} · ${pct(p.prob, 0)}</span></div>
      ${p.explain ? `<p>${esc(p.explain)}</p>` : ""}
      <p class="small muted">Strongest in: ${esc(p.best_view)} · alternatives: ${p.ranking.slice(1).map((r) => esc(r[0]) + " " + pct(r[1], 0)).join(", ")}</p>
      ${p.countries.length ? `<div class="chips">${p.countries.slice(0, 40).map((c) => `<span class="chip ${c === top ? "hit" : ""}">${esc(c)}</span>`).join("")}${p.countries.length > 40 ? `<span class="chip">+${p.countries.length - 40}</span>` : ""}</div>` : ""}
      <div class="teach">${esc(p.teach)}</div></div>`;
  }
  const scene = probes.find((p) => p.id === "scene");
  if (scene) h = `<p class="muted">Scene classified as <b>${esc(scene.label)}</b> (${pct(scene.prob, 0)}). Clues that point to ${esc(R.countries[0].name)} are highlighted.</p>` + h;
  pane("clues").innerHTML = h;

  // Text
  h = "";
  const clues = R.ocr.clues || [];
  if (clues.length) {
    h += "<h4>Text clues</h4>";
    for (const c of clues) h += `<div class="clue"><div class="clue-h"><span class="t">${esc(c.kind)}</span><span class="l">${esc(c.text)}</span><span class="tag ok">weight ${c.weight}</span></div><p>${esc(c.explain)}</p>${c.countries.length ? `<div class="chips">${c.countries.slice(0, 30).map((x) => `<span class="chip ${x === top ? "hit" : ""}">${esc(x)}</span>`).join("")}</div>` : ""}</div>`;
  }
  h += `<h4>All text read (${(R.ocr.items || []).length})</h4>`;
  h += (R.ocr.items || []).map((i) => `<div class="row"><div class="grow">${esc(i.text)}</div><span class="pct">${i.score.toFixed(2)}</span><button class="btn small ghost" data-search="${esc(i.text)}">search</button></div>`).join("") || `<p class="muted">No readable text.</p>`;
  if ((R.geocoded || []).length) h += "<h4>Geocoded (OpenStreetMap)</h4>" + R.geocoded.map((g) => `<div class="row"><div class="grow"><div class="name">${esc(g.query)}</div><div class="sub">${esc(g.name)}</div></div><span class="tag">${esc(g.cc)}</span></div>`).join("");
  pane("text").innerHTML = h;

  // Reverse
  renderReverse(R);
  // Sun
  renderSun(R);
  // Meta
  const m = R.meta;
  h = `<div class="kv"><div>EXIF present</div><div>${m.has_exif ? "yes" : "no (stripped)"}</div>
    <div>GPS</div><div>${m.gps ? `${m.gps.lat}, ${m.gps.lon}${m.gps.alt_m != null ? " · " + m.gps.alt_m + " m" : ""}` : "—"}</div>
    <div>Capture time</div><div>${m.datetime ? esc(m.datetime.local) + (m.datetime.offset ? " (" + esc(m.datetime.offset) + ")" : "") : "—"}</div>
    <div>Camera</div><div>${esc(m.camera || "—")}</div><div>Software</div><div>${esc(m.software || "—")}</div>
    <div>Heading</div><div>${m.heading != null ? m.heading + "°" : "—"}</div>
    <div>Image</div><div>${R.image.w}×${R.image.h}, ${(R.image.bytes / 1024).toFixed(0)} KB</div>
    <div>Brightness / contrast</div><div>${R.stats.brightness} / ${R.stats.contrast}</div></div>`;
  if (Object.keys(m.raw || {}).length) h += "<h4>Raw tags</h4><div class='kv'>" + Object.entries(m.raw).map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join("") + "</div>";
  pane("meta").innerHTML = h;
}

function renderReverse(R) {
  const rv = R.reverse || { engines: {}, manual: {} };
  let h = `<p class="muted small">Key-less web uploads. Click to upload this image to an engine and open the results in your browser.</p><div class="btnrow">`;
  for (const [k, n] of [["yandex", "Yandex"], ["lens", "Google Lens"], ["bing", "Bing"], ["tineye", "TinEye"]]) h += `<button class="btn small" data-rev="${k}">${n} ↗</button>`;
  h += `</div><div class="btnrow"><span class="muted small">Manual (drag the image in):</span>${Object.entries(rv.manual || {}).map(([k, u]) => `<button class="link" data-open="${esc(u)}">${esc(k)}</button>`).join("")}</div>`;
  const y = rv.engines && rv.engines.yandex;
  if (y) {
    if (y.captcha && !y.results.length) h += `<div class="notice">Yandex showed a captcha for automated access. Click “Yandex ↗” to see results in your browser.</div>`;
    if ((rv.places || []).length) h += "<h4>Places mentioned in matches</h4><div class='chips'>" + rv.places.map((p) => `<span class="chip ${p.cc === R.countries[0].iso ? "hit" : ""}">${esc(p.name)} (${esc(p.cc)}) ×${p.hits}</span>`).join("") + "</div>";
    if ((y.tags || []).length) h += "<h4>Yandex tags</h4><div class='chips'>" + y.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("") + "</div>";
    h += `<h4>Yandex matches (${y.results.length}) <button class="link" data-open="${esc(y.url)}">open</button></h4>`;
    h += y.results.map((r) => `<div class="res"><a href="#" data-open="${esc(r.url)}">${esc(r.title || r.url)}</a><div class="sub">${esc(r.domain || "")} ${esc(r.snippet || "")}</div></div>`).join("") || "<p class='muted'>No parsed matches.</p>";
  } else if (R.settings_online === false) h += "<p class='muted'>Online techniques disabled in settings.</p>";
  const te = rv.engines && rv.engines.tineye;
  if (te) h += `<h4>TinEye exact copies: ${te.total ?? te.results.length} <button class="link" data-open="${esc(te.url)}">open</button></h4>` + te.results.map((r) => `<div class="res"><a href="#" data-open="${esc(r.url)}">${esc(r.domain)}</a><div class="sub">${esc(r.url)}</div></div>`).join("");
  h += `<div class="teach">Reverse search finds copies of the photo or similar-looking places. Yandex is strongest for scenery and buildings; Google Lens for landmarks; TinEye finds the oldest upload, which often carries the original caption and location.</div>`;
  $(`.tabpane[data-pane="rev"]`).innerHTML = h;
}

function renderSun(R) {
  const sun = R.sun || {};
  const dt = R.meta.datetime;
  const local = dt ? dt.local : new Date().toISOString().slice(0, 19);
  const off = dt && dt.offset ? dt.offset : guessOffset(sun.utc, dt && dt.local);
  let h = "";
  if (sun.position) {
    const p = sun.position;
    h += `<div class="${sun.consistent ? "clue" : "notice"}"><b>Sun at capture time</b> (${esc(sun.time_basis)})<br>
      Elevation <b>${p.elevation}°</b>, azimuth <b>${p.azimuth}°</b>. ${p.shadow_ratio ? `Shadows should point to <b>${p.shadow_bearing}°</b> and be <b>${p.shadow_ratio}×</b> the object height.` : "Sun below the horizon."}
      ${sun.consistent ? "" : "<br>⚠ Image brightness does not match — time zone, timestamp or location may be wrong."}
      ${sun.times ? `<br><span class="small muted">Sunrise ${fmtT(sun.times.sunrise_utc)} · noon ${fmtT(sun.times.solar_noon_utc)} · sunset ${fmtT(sun.times.sunset_utc)} UTC · max elevation ${sun.times.max_elevation}°</span>` : ""}</div>`;
  } else h += `<p class="muted">No capture time in metadata. Enter date/time manually and measure a shadow with <b>Measure shadow</b> above the photo.</p>`;
  h += `<h4>Shadow geolocation</h4><div class="form">
    <label>Local date &amp; time<input type="datetime-local" step="60" id="sunLocal" value="${esc(local.slice(0, 16))}"></label>
    <label>UTC offset<input id="sunOff" value="${esc(off)}" placeholder="+02:00"></label>
    <label>Sun elevation (°)<input id="sunEl" type="number" step="0.1" placeholder="from shadow"></label>
    <label>Tolerance (°)<input id="sunTol" type="number" step="0.1" value="1.5"></label>
    <label class="full">Shadow bearing (° from north, optional — needs a known camera heading)<input id="sunAz" type="number" step="1" placeholder="e.g. 315"></label>
    <label>Object height<input id="objH" type="number" step="0.01" placeholder="m or px"></label>
    <label>Shadow length<input id="shL" type="number" step="0.01" placeholder="same unit"></label></div>
    <div class="btnrow"><button class="btn small" id="sunCalcEl">Elevation from height/shadow</button><button class="btn small primary" id="sunLocus">Plot possible locations</button><button class="btn small" id="sunChrono">Chronolocate at pin</button><button class="btn small ghost" id="sunClear">Clear</button></div>
    <div id="sunOut" class="small"></div>
    <div class="teach">${esc(sun.teach || "")}</div>`;
  $(`.tabpane[data-pane="sun"]`).innerHTML = h;
}
const fmtT = (s) => (s ? s.slice(11, 16) : "—");
function guessOffset(utc, local) {
  if (!utc || !local) return "+00:00";
  const m = Math.round((new Date(local + "Z") - new Date(utc)) / 60000);
  const s = m < 0 ? "-" : "+", a = Math.abs(m);
  return `${s}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(a % 60).padStart(2, "0")}`;
}
function sunUTC() {
  const local = $("#sunLocal").value, off = ($("#sunOff").value || "+00:00").trim();
  return new Date(local + ":00" + (off.match(/^[+-]\d\d:\d\d$/) ? off : "+00:00")).toISOString();
}
async function sunLocus() {
  const el = parseFloat($("#sunEl").value);
  if (isNaN(el)) return toast("Enter a sun elevation (measure a shadow first)");
  const r = await api("/api/sun/locus", { utc: sunUTC(), elevation: el, tol: parseFloat($("#sunTol").value) || 1.5, azimuth: $("#sunAz").value });
  S.layers.sun.clearLayers();
  const rend = L.canvas({ padding: 0.5 });
  for (const [la, lo] of r.points) S.layers.sun.addLayer(L.circleMarker([la, lo], { renderer: rend, radius: 2.2, stroke: false, fillColor: "#fbbf24", fillOpacity: 0.55 }));
  S.layers.sun.addLayer(L.circleMarker(r.subsolar, { radius: 7, color: "#fbbf24", weight: 2, fillOpacity: 0.2 }).bindTooltip("Sub-solar point (sun at zenith)"));
  $("#sunOut").innerHTML = `${r.count} grid cells (1°) match. The yellow band is every place where the sun stood at ${el}° at that moment.`;
  if (r.points.length) S.map.fitBounds(r.points.map((p) => [p[0], p[1]]), { padding: [20, 20] });
  addClientLog("sun", "Shadow locus plotted", "Circle of equal altitude (NOAA solar position, 1° grid)", `${r.count} cells at elevation ${el}° ± tol, UTC ${sunUTC()}`);
}
async function sunChrono() {
  const el = parseFloat($("#sunEl").value);
  if (isNaN(el)) return toast("Enter a sun elevation first");
  const Lc = S.result.location;
  const r = await api("/api/sun/chrono", { lat: Lc.lat, lon: Lc.lon, date: sunUTC(), elevation: el });
  const off = $("#sunOff").value || "+00:00";
  const sign = off[0] === "-" ? -1 : 1, mins = sign * (parseInt(off.slice(1, 3)) * 60 + parseInt(off.slice(4, 6) || 0));
  $("#sunOut").innerHTML = r.times.length ? "At the pinned location the sun was at " + el + "° at: " + r.times.map((t) => {
    const d = new Date(new Date(t.utc).getTime() + mins * 60000);
    return `<b>${d.toISOString().slice(11, 16)}</b> local (${t.part}, sun az ${t.azimuth}°)`;
  }).join(" or ") : "The sun never reached that elevation there on that date.";
  addClientLog("sun", "Chronolocation", "Solve solar elevation(t) = measured elevation at the pinned location", $("#sunOut").textContent);
}

/* ------------------------------------------------------------ shadow measuring */
function startMeasure() {
  if (!S.result) return;
  S.measuring = { pts: [] };
  $("#stage").classList.add("measuring");
  $("#viewerHint").textContent = "Click the BASE of a vertical object, then its TOP, then the TIP of its shadow.";
}
function stageClick(ev) {
  if (!S.measuring) return;
  const img = $("#photo"), r = img.getBoundingClientRect();
  const W = S.result.image.work_w, H = S.result.image.work_h;
  const sc = Math.min(r.width / W, r.height / H), ox = (r.width - W * sc) / 2, oy = (r.height - H * sc) / 2;
  const x = (ev.clientX - r.left - ox) / sc, y = (ev.clientY - r.top - oy) / sc;
  S.measuring.pts.push([x, y]);
  drawMeasure();
  const n = S.measuring.pts.length;
  $("#viewerHint").textContent = ["Now click the TOP of the object.", "Now click the TIP of the shadow.", ""][n - 1] || "";
  if (n === 3) {
    const [b, t, s] = S.measuring.pts;
    const hgt = Math.hypot(t[0] - b[0], t[1] - b[1]), len = Math.hypot(s[0] - b[0], s[1] - b[1]);
    const el = (Math.atan2(hgt, len) * 180) / Math.PI;
    S.measuring.done = true; $("#stage").classList.remove("measuring");
    activateTab("sun");
    $("#objH").value = hgt.toFixed(1); $("#shL").value = len.toFixed(1); $("#sunEl").value = el.toFixed(1);
    $("#viewerHint").textContent = `Estimated sun elevation ≈ ${el.toFixed(1)}° (pixel ratio; assumes a vertical object, flat ground and a roughly side-on view — enter real lengths for accuracy).`;
    addClientLog("sun", "Shadow measured on image", "Sun elevation = atan(object height / shadow length)", `height ${hgt.toFixed(0)} px, shadow ${len.toFixed(0)} px → ${el.toFixed(1)}°`);
  }
}
function drawMeasure() {
  const svg = $("#ovl");
  svg.querySelectorAll(".ms").forEach((e) => e.remove());
  if (!S.measuring) return;
  const p = S.measuring.pts, W = S.result.image.work_w, rr = Math.max(4, W / 200);
  const col = ["#4ade80", "#38bdf8", "#fbbf24"];
  if (p.length >= 2) svg.insertAdjacentHTML("beforeend", `<line class="ms" x1="${p[0][0]}" y1="${p[0][1]}" x2="${p[1][0]}" y2="${p[1][1]}" stroke="#38bdf8" stroke-width="${rr / 1.5}"/>`);
  if (p.length >= 3) svg.insertAdjacentHTML("beforeend", `<line class="ms" x1="${p[0][0]}" y1="${p[0][1]}" x2="${p[2][0]}" y2="${p[2][1]}" stroke="#fbbf24" stroke-width="${rr / 1.5}" stroke-dasharray="${rr * 2}"/>`);
  p.forEach((q, i) => svg.insertAdjacentHTML("beforeend", `<circle class="ms" cx="${q[0]}" cy="${q[1]}" r="${rr}" fill="${col[i]}" stroke="#000" stroke-width="2"/>`));
}

/* ------------------------------------------------------------ log drawer */
function updateLogCount() { $("#logCount").textContent = S.log.length; }
function addClientLog(step, title, method, detail) {
  S.log.push({ id: S.log.length + 1, t: null, step, title, method, detail, level: "info", teach: "", ms: null, data: null });
  updateLogCount(); renderLog();
}
let logFilter = "all";
function renderLog() {
  const R = S.result, log = S.log;
  // summary
  let h = "";
  const total = log.reduce((a, e) => a + (e.ms || 0), 0);
  const methods = {};
  for (const e of log) if (e.method) { const m = (methods[e.method] ||= { n: 0, ms: 0, step: e.step }); m.n++; m.ms += e.ms || 0; }
  const detected = R && R.vision ? R.vision.probes.filter((p) => p.detected && p.id !== "scene").length : 0;
  h += `<div class="tiles"><div class="tile"><b>${log.length}</b><span>steps</span></div><div class="tile"><b>${Object.keys(methods).length}</b><span>techniques</span></div>
    <div class="tile"><b>${detected + ((R && R.ocr.clues.length) || 0)}</b><span>clues found</span></div><div class="tile"><b>${(total / 1000).toFixed(1)}s</b><span>compute</span></div></div>`;
  if (R && R.vision) {
    h += `<div><h4>Which part of the image mattered most</h4>`;
    for (const v of [...R.vision.views].sort((a, b) => b.share_of_top - a.share_of_top)) h += `<div class="hbar"><span>${esc(v.view)}</span><div class="meter"><i style="width:${v.share_of_top * 100}%"></i></div><span class="pct">${pct(v.share_of_top, 0)}</span></div>`;
    if (R.attention && R.attention[0]) h += `<p class="small muted">Attention map hot-spots: ${R.attention[0].regions.slice(0, 4).map((r) => `${r.region} ${pct(r.share, 0)}`).join(" · ")}</p>`;
    h += `</div>`;
  }
  if (R && R.evidence && R.evidence.length) {
    h += `<div><h4>Pattern-recognition evidence used in the final decision</h4>`;
    const mx = Math.max(...R.evidence.map((e) => e.weight));
    for (const e of [...R.evidence].sort((a, b) => b.weight - a.weight).slice(0, 12)) h += `<div class="hbar"><span title="${esc(e.source)}">${esc(e.label).slice(0, 26)}</span><div class="meter"><i style="width:${(e.weight / mx) * 100}%"></i></div><span class="pct">${e.weight.toFixed(2)}</span></div>`;
    h += `</div>`;
  }
  $("#logSummary").innerHTML = h;
  // filter
  const steps = ["all", ...new Set(log.map((e) => e.step))];
  $("#logFilter").innerHTML = steps.map((s) => `<button data-f="${esc(s)}" class="${s === logFilter ? "on" : ""}">${esc(s)}</button>`).join("");
  // entries
  $("#logList").innerHTML = log.filter((e) => logFilter === "all" || e.step === logFilter).map((e) => `
    <div class="entry ${e.level}"><div class="entry-h"><span class="ts">${e.t != null ? e.t.toFixed(2) + "s" : "manual"}</span><span class="st">${esc(e.step)}</span>${e.ms != null ? `<span class="ms">${e.ms} ms</span>` : ""}<span class="ti">${esc(e.title)}</span></div>
    ${e.method ? `<div class="me">⚙ ${esc(e.method)}</div>` : ""}
    ${e.detail ? `<div class="de">${esc(e.detail)}</div>` : ""}
    ${e.teach ? `<div class="teach">${esc(e.teach)}</div>` : ""}
    ${e.data != null ? `<details><summary>raw data</summary><pre>${esc(JSON.stringify(e.data, null, 2)).slice(0, 12000)}</pre></details>` : ""}</div>`).join("");
}
function openDrawer() { renderLog(); $("#drawer").classList.add("open"); $("#scrim").hidden = false; }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").hidden = true; }

/* ------------------------------------------------------------ misc */
function activateTab(n) {
  $$("#tabbar button").forEach((b) => b.classList.toggle("on", b.dataset.tab === n));
  $$(".tabpane").forEach((p) => (p.hidden = p.dataset.pane !== n));
}
function exportJSON() {
  const R = JSON.parse(JSON.stringify(S.result));
  delete R.image.src; (R.attention || []).forEach((m) => delete m.png);
  const blob = new Blob([JSON.stringify({ result: R, log: S.log }, null, 2)], { type: "application/json" });
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = (S.result.filename || "image").replace(/\.[^.]+$/, "") + "_geolens.json"; a.click();
}
async function openSettings() {
  const s = await api("/api/status");
  $("#setModel").innerHTML = Object.entries(s.models).map(([k, v]) => `<option value="${k}" ${k === s.settings.model ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("#setOnline").checked = s.settings.online; $("#setReverse").checked = s.settings.reverse_auto; $("#setGeocode").checked = s.settings.geocode_ocr;
  $("#setOcr").checked = s.settings.ocr; $("#setAttn").checked = s.settings.attention;
  $("#settings").showModal();
}

document.addEventListener("DOMContentLoaded", () => {
  pollStatus();
  const drop = $("#drop");
  $("#file").addEventListener("change", (e) => analyze(e.target.files[0]));
  ["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  document.addEventListener("drop", (e) => { const f = e.dataTransfer.files[0]; if (f) analyze(f); });
  document.addEventListener("paste", (e) => { const it = [...e.clipboardData.items].find((i) => i.type.startsWith("image/")); if (it) analyze(it.getAsFile()); });
  $("#overlaySeg").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) setOverlay(b.dataset.ov); });
  $("#heatSel").addEventListener("change", () => setOverlay("heat"));
  $("#tabbar").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) activateTab(b.dataset.tab); });
  $("#logBtn").addEventListener("click", openDrawer);
  $("#drawerClose").addEventListener("click", closeDrawer);
  $("#scrim").addEventListener("click", closeDrawer);
  $("#logFilter").addEventListener("click", (e) => { const b = e.target.closest("button"); if (b) { logFilter = b.dataset.f; renderLog(); } });
  const reset = () => { show("landing"); $("#file").value = ""; S.measuring = null; };
  $("#newBtn").addEventListener("click", reset); $("#homeBtn").addEventListener("click", reset);
  $("#exportBtn").addEventListener("click", exportJSON);
  $("#settingsBtn").addEventListener("click", openSettings);
  $("#setSave").addEventListener("click", () => api("/api/settings", {
    model: $("#setModel").value, online: $("#setOnline").checked, reverse_auto: $("#setReverse").checked,
    geocode_ocr: $("#setGeocode").checked, ocr: $("#setOcr").checked, attention: $("#setAttn").checked,
  }).then(() => { toast("Settings saved"); pollStatus(); }));
  $("#shadowBtn").addEventListener("click", startMeasure);
  $("#stage").addEventListener("click", stageClick);
  $("#copyBtn").addEventListener("click", () => { const L = S.result.location; navigator.clipboard.writeText(`${L.lat}, ${L.lon}`); toast("Coordinates copied"); });
  $("#gmapsBtn").addEventListener("click", () => { const L = S.result.location; openExternal(`https://www.google.com/maps/@${L.lat},${L.lon},12z`); });
  $("#svBtn").addEventListener("click", () => { const L = S.result.location; openExternal(`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${L.lat},${L.lon}`); });
  document.body.addEventListener("click", async (e) => {
    const o = e.target.closest("[data-open]"); if (o) { e.preventDefault(); openExternal(o.dataset.open); return; }
    const s = e.target.closest("[data-search]"); if (s) { openExternal("https://www.google.com/search?q=" + encodeURIComponent(s.dataset.search)); return; }
    const r = e.target.closest("[data-rev]");
    if (r) { toast("Uploading to " + r.textContent.replace(" ↗", "") + "…"); const res = await api("/api/reverse/" + r.dataset.rev, { job: S.job, open: true }); if (res.error) toast(res.error + " — opened manual page", 4000); S.log.push({ id: 0, t: null, step: "reverse", title: "Manual reverse search: " + r.dataset.rev, method: "Web upload, no API key", detail: res.error || res.url, level: res.error ? "warn" : "info" }); updateLogCount(); if (res.error && res.url) openExternal(res.url); return; }
    if (e.target.id === "sunLocus") sunLocus();
    if (e.target.id === "sunChrono") sunChrono();
    if (e.target.id === "sunClear") { S.layers.sun.clearLayers(); $("#sunOut").textContent = ""; }
    if (e.target.id === "sunCalcEl") { const h = parseFloat($("#objH").value), l = parseFloat($("#shL").value); if (h > 0 && l > 0) $("#sunEl").value = ((Math.atan2(h, l) * 180) / Math.PI).toFixed(2); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); if (e.key.toLowerCase() === "l" && !e.target.closest("input,select") && S.log.length) openDrawer(); });
});
