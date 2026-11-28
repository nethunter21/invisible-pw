/* GeoLens front-end */
"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (p, d = 1) => ((p || 0) * 100).toFixed(d) + "%";
const api = async (path, body, raw) => {
  const opt = body === undefined ? {} : { method: "POST", body: raw ? body : JSON.stringify(body), headers: raw ? {} : { "Content-Type": "application/json" } };
  return (await fetch(path, opt)).json();
};
const toast = (msg, ms = 2600) => { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms); };
const openExternal = (url) => api("/api/open", { url });
const theme = () => document.documentElement.dataset.theme || "dark";

const S = { job: null, result: null, log: [], map: null, layers: {}, base: null, overlay: "none", measuring: null };

/* ---------------------------------------------------------------- status */
async function pollStatus() {
  try {
    const s = await api("/api/status");
    const pill = $("#modelPill"), m = s.model;
    pill.className = "status";
    let txt = "VISION OFF";
    if (m) {
      const name = (s.models[m.key] || m.key).split(" (")[0].toUpperCase();
      if (m.status === "ready") { pill.classList.add("ready"); txt = `${name} · ${m.device.toUpperCase()}`; }
      else if (m.status === "downloading") { pill.classList.add("busy"); txt = `DOWNLOADING MODEL ${m.download.done}/${m.download.total}`; }
      else if (m.status === "loading") { pill.classList.add("busy"); txt = `LOADING ${name}`; }
      else if (m.status === "unavailable") { pill.classList.add("bad"); txt = "VISION MODEL UNAVAILABLE"; pill.title = m.error || ""; }
      else txt = name;
    }
    pill.querySelector("span").textContent = txt;
    if (!m || m.status !== "ready") setTimeout(pollStatus, 1500);
  } catch { setTimeout(pollStatus, 3000); }
}

/* ---------------------------------------------------------------- flow */
function show(id) { for (const s of ["landing", "loading", "result"]) $("#" + s).hidden = s !== id; }

async function analyze(file) {
  if (!file || !file.type.startsWith("image/")) return toast("Please choose an image file");
  const buf = await file.arrayBuffer();
  $("#loadImg").src = URL.createObjectURL(file);
  $("#liveSteps").innerHTML = ""; $("#loadBar").style.width = "1%"; $("#loadStage").textContent = "Uploading"; $("#loadPct").textContent = "0%";
  show("loading");
  $("#logBtn").disabled = false; S.log = []; updateLogCount();
  const r = await api("/api/analyze?name=" + encodeURIComponent(file.name || "pasted.png"), buf, true);
  if (r.error) { toast(r.error); show("landing"); return; }
  S.job = r.job;
  poll(0);
}

async function poll(since) {
  const r = await api(`/api/job/${S.job}?since=${since}`);
  $("#loadStage").textContent = r.stage;
  $("#loadPct").textContent = Math.round(r.progress * 100) + "%";
  $("#loadBar").style.width = Math.max(2, r.progress * 100) + "%";
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

/* ---------------------------------------------------------------- render */
function render(R) {
  show("result");
  $("#newBtn").hidden = false; $("#exportBtn").hidden = false;
  const L = R.location;
  $("#photo").src = R.image.src;
  $("#ansPlace").textContent = L.venue || (L.radius_km > 300 ? L.country : L.radius_km >= 30 ? `Around ${L.city || L.country}` : L.city || L.country);
  $("#ansSub").textContent = [L.venue ? L.city : null, L.country].filter(Boolean).join(", ") + (L.nearest_city && L.nearest_city.name !== L.city ? ` · nearest locality ${L.nearest_city.name}` : "");
  $("#ansCoords").textContent = `${L.lat.toFixed(5)}, ${L.lon.toFixed(5)}  ±${L.radius_km < 1 ? Math.round(L.radius_km * 1000) + " m" : L.radius_km + " km"}`;
  $("#confBar").style.width = Math.round(L.confidence * 100) + "%";
  $("#confTxt").textContent = `${Math.round(L.confidence * 100)}% · ${L.confidence_label.toUpperCase()}`;
  $("#reasoning").innerHTML = R.reasoning.map((t) => `<li>${esc(t)}</li>`).join("");
  $("#heatSel").innerHTML = (R.attention || []).map((m, i) => `<option value="${i}">${esc(m.label)}</option>`).join("");
  $$('[data-ov="mask"]')[0].hidden = !(R.prep && R.prep.masked_src);
  setOverlay(R.prep && R.prep.masked_src && S.overlay === "none" ? "none" : S.overlay);
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
  $("#photo").src = ov === "mask" && R.prep.masked_src ? R.prep.masked_src : R.image.src;
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svg.innerHTML = ""; heat.hidden = true; $("#heatSel").hidden = true; hint.textContent = R.prep && R.prep.mirrored ? "Shown un-mirrored (front-camera selfie detected)." : "";
  const fg = getComputedStyle(document.documentElement).getPropertyValue("--fg").trim() || "#fff";
  const label = (x, y, t, size) => `<text x="${x}" y="${y}" fill="#fff" font-size="${size}" font-family="Consolas,monospace" font-weight="700" style="paint-order:stroke;stroke:#000;stroke-width:4px">${esc(t)}</text>`;
  if (ov === "mask") {
    hint.textContent = "People are blurred out before vision analysis and reverse search, so engines match the place — not the face.";
    for (const p of R.prep.faces || []) svg.insertAdjacentHTML("beforeend", `<rect x="${p[0]}" y="${p[1]}" width="${p[2]}" height="${p[3]}" fill="none" stroke="#fff" stroke-dasharray="8 6" stroke-width="3"/>`);
  } else if (ov === "heat") {
    const maps = R.attention || [];
    if (!maps.length) { hint.textContent = "No attention map (vision model not available)."; return; }
    $("#heatSel").hidden = maps.length < 2;
    const m = maps[+$("#heatSel").value || 0];
    heat.src = m.png; heat.hidden = false;
    hint.textContent = "Bright = image patches that drove this answer. Hot regions: " + m.regions.slice(0, 3).map((r) => `${r.region} ${pct(r.share, 0)}`).join(", ");
  } else if (ov === "crops") {
    const v = (R.vision && R.vision.views) || [];
    const fs = Math.max(14, W / 42);
    if (v.length) {
      const max = Math.max(...v.map((x) => x.share_of_top));
      for (const c of v.slice(1).sort((a, b) => a.share_of_top - b.share_of_top)) {
        const [x0, y0, x1, y1] = c.box, a = c.share_of_top / max;
        svg.insertAdjacentHTML("beforeend", `<rect x="${x0 + 3}" y="${y0 + 3}" width="${x1 - x0 - 6}" height="${y1 - y0 - 6}" fill="rgba(255,255,255,${0.03 + a * 0.15})" stroke="rgba(255,255,255,${0.35 + a * 0.65})" stroke-width="${1.5 + a * 3}"/>` + label(x0 + 10, y0 + fs + 8, `${c.view} ${pct(c.share_of_top, 0)} · ${c.top[0][0]}`, fs));
      }
      hint.textContent = "Each crop is classified separately; % = share of the weight behind the winning country.";
    } else hint.textContent = "No crop analysis (vision model not available).";
  } else if (ov === "text") {
    const items = R.ocr.items || [];
    if (!items.length) { hint.textContent = "No readable text found."; return; }
    for (const it of items) {
      const [x0, y0, x1, y1] = it.box;
      svg.insertAdjacentHTML("beforeend", `<rect x="${x0 - 3}" y="${y0 - 3}" width="${x1 - x0 + 6}" height="${y1 - y0 + 6}" fill="rgba(255,255,255,.08)" stroke="#fff" stroke-width="2.5"><title>${esc(it.text)}</title></rect>`);
    }
    hint.textContent = `${items.length} text region(s): ` + items.slice(0, 8).map((i) => `“${i.text}”`).join(", ");
  }
  drawMeasure();
}

/* ---------------------------------------------------------------- map */
function baseLayer() {
  const esri = (svc, z = 16) => L.tileLayer(`https://server.arcgisonline.com/ArcGIS/rest/services/${svc}/MapServer/tile/{z}/{y}/{x}`, { attribution: "Esri · OpenStreetMap contributors", maxZoom: z });
  return theme() === "light"
    ? L.layerGroup([esri("Canvas/World_Light_Gray_Base"), esri("Canvas/World_Light_Gray_Reference")])
    : L.layerGroup([esri("Canvas/World_Dark_Gray_Base"), esri("Canvas/World_Dark_Gray_Reference")]);
}
function renderMap(R) {
  if (!S.map) {
    S.map = L.map("map", { zoomControl: true, worldCopyJump: true, attributionControl: true }).setView([20, 0], 2);
    S.base = baseLayer().addTo(S.map);
    const sat = L.layerGroup([L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Esri World Imagery" }),
      L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19 })]);
    const osm = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { attribution: "© OpenStreetMap contributors", maxZoom: 19 });
    S.layerCtl = L.control.layers({ Map: S.base, Satellite: sat, Streets: osm }, {}, { position: "topright" }).addTo(S.map);
    L.control.scale({ imperial: false }).addTo(S.map);
    S.layers.heat = L.layerGroup().addTo(S.map);
    S.layers.ranges = L.layerGroup();
    S.layers.main = L.layerGroup().addTo(S.map);
    S.layers.sun = L.layerGroup().addTo(S.map);
    S.layerCtl.addOverlay(S.layers.heat, "Probability heatmap");
    S.layerCtl.addOverlay(S.layers.ranges, "Species / climate ranges");
    S.layerCtl.addOverlay(S.layers.main, "Clues & pin");
  }
  S.layers.main.clearLayers(); S.layers.sun.clearLayers(); S.layers.heat.clearLayers(); S.layers.ranges.clearLayers();
  const Lc = R.location;
  const fg = theme() === "light" ? "#000" : "#fff";
  const hp = (R.heat && R.heat.points) || [];
  if (hp.length && L.heatLayer) {
    const mx = hp[0][2] || 1;
    S.layers.heat.addLayer(L.heatLayer(hp.map((p) => [p[0], p[1], Math.sqrt(p[2] / mx)]), {
      radius: 22, blur: 18, minOpacity: 0.25, maxZoom: 9,
      gradient: theme() === "light" ? { 0.2: "#bbb", 0.5: "#777", 0.8: "#333", 1: "#000" } : { 0.2: "#333", 0.5: "#888", 0.8: "#ccc", 1: "#fff" } }));
  }
  for (const sp of ((R.landscape || {}).species || []).slice(0, 3))
    for (const b of sp.boxes) S.layers.ranges.addLayer(L.rectangle([[b[0], b[2]], [b[1], b[3]]], { color: fg, weight: 1, dashArray: "4 4", fillOpacity: 0.03 }).bindTooltip(esc(sp.label) + " range"));
  for (const [i, c] of (R.clusters || []).entries()) {
    if (i === 0) continue;
    S.layers.main.addLayer(L.circleMarker([c.lat, c.lon], { radius: 5 + 14 * Math.sqrt(c.score), color: fg, weight: 1, opacity: 0.6, fillOpacity: 0.08, dashArray: "3 3" })
      .bindTooltip(`Alt. area: ${esc(c.name)} · ${pct(c.score, 0)}<br>${c.members.slice(0, 4).map((m) => esc(m.label)).join("<br>")}`));
  }
  for (const m of ((R.clusters || [])[0] || {}).members || []) {
    S.layers.main.addLayer(L.circleMarker([m.lat, m.lon], { radius: 3.5, color: fg, weight: 1, fillColor: fg, fillOpacity: 0.5 }).bindTooltip(`${esc(m.source)}: ${esc(m.label)}`));
  }
  S.layers.main.addLayer(L.circle([Lc.lat, Lc.lon], { radius: Math.max(80, Lc.radius_km * 1000), color: fg, weight: 1.2, fillOpacity: 0.06 }));
  S.layers.main.addLayer(L.marker([Lc.lat, Lc.lon], { icon: L.divIcon({ className: "", html: '<div class="pin"></div>', iconSize: [18, 18], iconAnchor: [9, 9] }) })
    .bindPopup(`<b>${esc($("#ansPlace").textContent)}</b><br>${esc(Lc.lat.toFixed(5))}, ${esc(Lc.lon.toFixed(5))}`));
  setTimeout(() => {
    S.map.invalidateSize();
    if (Lc.radius_km > 40 && hp.length) S.map.fitBounds(hp.slice(0, 150).map((p) => [p[0], p[1]]), { padding: [30, 30], maxZoom: 8 });
    else S.map.fitBounds(L.latLng(Lc.lat, Lc.lon).toBounds(Math.max(1500, Lc.radius_km * 2600)), { maxZoom: 15, padding: [20, 20] });
  }, 60);
}

/* ---------------------------------------------------------------- tabs */
function renderTabs(R) {
  const pane = (n) => $(`.tabpane[data-pane="${n}"]`);
  const top = R.countries[0].iso;
  // LOCATION
  let h = "<h4>Candidate areas (spatial clusters)</h4>";
  for (const [i, c] of (R.clusters || []).entries()) {
    h += `<details class="run" ${i === 0 ? "open" : ""}><summary><span class="tag ${i === 0 ? "on" : ""}">${i === 0 ? "BEST" : "#" + (i + 1)}</span><div class="grow"><b>${esc(c.name)}</b> <span class="muted small">${c.lat}, ${c.lon}</span><div class="sub small muted">${esc(c.sources.join(" · "))}</div></div><div class="meter"><i style="width:${c.score * 100}%"></i></div><span class="pct">${pct(c.score, 0)}</span></summary>
      <div class="inner">${c.members.map((m) => `<div class="row"><div class="grow"><div>${esc(m.label)}</div><div class="sub">${esc(m.source)} · precision ${m.prec < 1 ? Math.round(m.prec * 1000) + " m" : m.prec + " km"}</div></div><span class="pct">${m.w}</span></div>`).join("")}</div></details>`;
  }
  if (!(R.clusters || []).length) h += `<p class="muted">No point-level clues; using the country centre.</p>`;
  h += "<h4>Countries</h4>";
  for (const c of R.countries.slice(0, 6)) {
    h += `<div class="row"><span class="tag ${c.iso === top ? "on" : ""}">${esc(c.iso)}</span><div class="grow"><div class="name">${esc(c.name)}</div>
      <div class="sub">${c.visual != null ? "visual " + pct(c.visual) + " · " : ""}${esc(c.support.slice(0, 4).join(" · ") || "visual similarity only")}</div></div>
      <div class="meter"><i style="width:${c.prob * 100}%"></i></div><span class="pct">${pct(c.prob)}</span></div>`;
  }
  if ((R.cities || []).length) {
    h += "<h4>Most similar cities in top countries</h4>";
    for (const c of R.cities.slice(0, 6)) h += `<div class="row"><div class="grow"><div class="name">${esc(c.name)}</div><div class="sub">${esc(c.cc)} · ${c.lat.toFixed(3)}, ${c.lon.toFixed(3)}</div></div><div class="meter"><i style="width:${(c.score || 0) * 100}%"></i></div><span class="pct">${pct(c.score || 0)}</span></div>`;
  }
  pane("loc").innerHTML = h;

  // CLUES
  h = "";
  if ((R.world || []).length) {
    h += "<h4>Worldwide landmark / skyline match</h4>";
    for (const w of R.world.slice(0, 8)) h += `<div class="row"><span class="tag">${w.type === "landmark" ? "VENUE" : "CITY"}</span><div class="grow"><div class="name">${esc(w.name)}</div><div class="sub">${esc(w.city)}, ${esc(w.cc)}</div></div><div class="meter"><i style="width:${w.p * 100}%"></i></div><span class="pct">${pct(w.p)}</span></div>`;
    h += `<div class="teach">The image is compared directly with hundreds of named places (casinos, towers, skylines). A country classifier can confuse two night skylines; a direct match with a named place is far more discriminative.</div>`;
  }
  const probes = (R.vision && R.vision.probes) || [];
  if (!probes.length) h += `<div class="notice">Visual clue recognition needs the vision model (see status). Text, metadata and reverse-search clues still apply.</div>`;
  else h += "<h4>Pattern recognition</h4>";
  const scene = probes.find((p) => p.id === "scene");
  if (scene) h += `<p class="muted small">Scene: <b>${esc(scene.label)}</b> (${pct(scene.prob, 0)}). Countries consistent with ${esc(R.countries[0].name)} are highlighted.</p>`;
  for (const p of probes.filter((p) => p.id !== "scene").sort((a, b) => b.detected - a.detected || b.prob * b.weight - a.prob * a.weight)) {
    h += `<div class="clue ${p.detected ? "" : "weak"}"><div class="clue-h"><span class="t">${esc(p.title)}</span><span class="l">${esc(p.label)}</span><span class="tag ${p.detected ? "on" : ""}">${p.applicable === false ? "N/A FOR SCENE" : p.detected ? "DETECTED" : "WEAK"} ${pct(p.prob, 0)}</span></div>
      ${p.explain ? `<p>${esc(p.explain)}</p>` : ""}
      <p class="small muted">Strongest in: ${esc(p.best_view)} · alternatives: ${p.ranking.slice(1).map((r) => esc(r[0]) + " " + pct(r[1], 0)).join(", ")}</p>
      ${p.countries.length ? `<div class="chips">${p.countries.slice(0, 44).map((c) => `<span class="chip ${c === top ? "hit" : ""}">${esc(c)}</span>`).join("")}${p.countries.length > 44 ? `<span class="chip">+${p.countries.length - 44}</span>` : ""}</div>` : ""}
      <div class="teach">${esc(p.teach)}</div></div>`;
  }
  pane("clues").innerHTML = h;

  // TEXT
  h = "";
  const clues = R.ocr.clues || [];
  if (clues.length) {
    h += "<h4>Text clues</h4>";
    for (const c of clues) h += `<div class="clue"><div class="clue-h"><span class="t">${esc(c.kind)}</span><span class="l">${esc(c.text)}</span><span class="tag">w ${c.weight.toFixed(2)}</span></div><p>${esc(c.explain)}</p>${c.countries.length ? `<div class="chips">${c.countries.slice(0, 30).map((x) => `<span class="chip ${x === top ? "hit" : ""}">${esc(x)}</span>`).join("")}</div>` : ""}</div>`;
  }
  h += `<h4>All text read (${(R.ocr.items || []).length})</h4>`;
  h += (R.ocr.items || []).map((i) => `<div class="row"><div class="grow mono">${esc(i.text)}</div><span class="pct">${i.score.toFixed(2)}</span><button class="chipbtn" data-search="${esc(i.text)}">SEARCH</button></div>`).join("") || `<p class="muted">No readable text.</p>`;
  if ((R.geocoded || []).length) h += "<h4>Geocoded (OpenStreetMap / Wikipedia)</h4>" + R.geocoded.map((g) => `<div class="row"><div class="grow"><div class="name">${esc(g.query)}</div><div class="sub">${esc(g.name)}</div></div><span class="tag">${esc(g.cc || "")}</span></div>`).join("");
  pane("text").innerHTML = h;

  renderLand(R);
  renderReverse(R);
  renderPrep(R);
  renderSun(R);

  // META
  const m = R.meta;
  h = `<div class="kv"><div>EXIF</div><div>${m.has_exif ? "present" : "none (stripped / screenshot)"}</div>
    <div>GPS</div><div>${m.gps ? `${m.gps.lat}, ${m.gps.lon}${m.gps.alt_m != null ? " · " + m.gps.alt_m + " m" : ""}` : "—"}</div>
    <div>Capture time</div><div>${m.datetime ? esc(m.datetime.local) + (m.datetime.offset ? " (" + esc(m.datetime.offset) + ")" : "") : "—"}</div>
    <div>Camera</div><div>${esc(m.camera || "—")}</div><div>Software</div><div>${esc(m.software || "—")}</div>
    <div>Heading</div><div>${m.heading != null ? m.heading + "°" : "—"}</div>
    <div>Image</div><div>${R.image.w}×${R.image.h}, ${(R.image.bytes / 1024).toFixed(0)} KB</div>
    <div>Brightness / contrast</div><div>${R.stats.brightness} / ${R.stats.contrast}${R.stats.night ? " · night" : ""}</div></div>`;
  if (Object.keys(m.raw || {}).length) h += "<h4>Raw tags</h4><div class='kv'>" + Object.entries(m.raw).map(([k, v]) => `<div>${esc(k)}</div><div>${esc(v)}</div>`).join("") + "</div>";
  pane("meta").innerHTML = h;
}

function renderLand(R) {
  const ld = R.landscape || {}, top = R.countries[0].iso;
  let h = "";
  const regs = (R.heat && R.heat.regions) || [];
  if (regs.length) {
    h += "<h4>Most probable regions (heatmap)</h4>";
    for (const r of regs.slice(0, 6)) h += `<div class="row"><span class="tag">${esc(r.cc)}</span><div class="grow"><div class="name">Around ${esc(r.name)}</div><div class="sub">${r.lat.toFixed(2)}, ${r.lon.toFixed(2)} · ${r.n} places</div></div><div class="meter"><i style="width:${Math.min(100, r.p * 100 / regs[0].p)}%"></i></div><span class="pct">${pct(r.p)}</span><button class="chipbtn" data-fly="${r.lat},${r.lon}">VIEW</button></div>`;
    h += `<div class="teach">For images without a unique landmark, the honest answer is a probability surface. Every known place is scored by country likelihood × species ranges × climate × hemisphere × visual similarity. Use SATELLITE layer + the regions above to search for the exact spot (river bends, tree lines, bridges).</div>`;
  }
  const comp = ld.composition;
  if (comp && comp.fractions) {
    h += `<h4>Scene composition — ${esc(comp.family_label)}</h4>`;
    for (const [k, v] of Object.entries(comp.fractions).sort((a, b) => b[1] - a[1]).filter((x) => x[1] >= 0.03)) h += `<div class="hbar"><span>${esc(k)}</span><div class="meter"><i style="width:${v * 100}%"></i></div><span class="pct">${pct(v, 0)}</span></div>`;
    h += `<div class="chips" style="display:grid;grid-template-columns:repeat(${comp.grid.length},1fr);gap:3px;max-width:340px;margin-top:8px">${comp.grid.flat().map((l) => `<span class="chip" style="text-align:center">${esc(l)}</span>`).join("")}</div>`;
  }
  if ((ld.species || []).length) {
    h += "<h4>Plant & tree indicators</h4>";
    for (const sp of ld.species) h += `<div class="clue"><div class="clue-h"><span class="t">SPECIES</span><span class="l">${esc(sp.label)}</span><span class="tag on">${pct(sp.p, 0)}</span></div><p>${esc(sp.teach)}</p>${sp.countries.length ? `<div class="chips">${sp.countries.slice(0, 44).map((c) => `<span class="chip ${c === top ? "hit" : ""}">${esc(c)}</span>`).join("")}</div>` : ""}</div>`;
  }
  if ((ld.climate || []).length) h += "<h4>Climate (Köppen)</h4>" + ld.climate.map((c) => `<div class="row"><span class="tag">${esc(c.code)}</span><div class="grow">${esc(c.label)}</div><div class="meter"><i style="width:${c.p * 100}%"></i></div><span class="pct">${pct(c.p, 0)}</span></div>`).join("");
  if (ld.season) h += `<h4>Season & hemisphere</h4><div class="row"><div class="grow">${esc(ld.season.label)} (${pct(ld.season.p, 0)})</div><span class="tag ${ld.hemisphere ? "on" : ""}">${ld.hemisphere ? esc(ld.hemisphere.toUpperCase()) + "ERN HEMISPHERE" : "HEMISPHERE UNDECIDED"}</span></div>`;
  if (ld.landform || ld.water) h += `<h4>Terrain & water</h4><div class="kv"><div>Landform</div><div>${esc(ld.landform ? ld.landform.label : "—")}</div><div>Water</div><div>${esc(ld.water ? ld.water.label : "—")}</div></div>`;
  if (ld.spectral) {
    const s = ld.spectral;
    h += `<h4>Spectral indices</h4><div class="kv"><div>Vegetation (ExG)</div><div>${pct(s.vegetation_index, 0)} of pixels</div><div>Sky blueness</div><div>${s.sky_blueness}</div><div>Haze</div><div>${s.haze ?? "—"}</div><div>Saturation</div><div>${s.saturation}</div><div>Bare soil</div><div>${pct(s.bare_soil, 0)}</div><div>Dry grass</div><div>${pct(s.dry_grass, 0)}</div></div>`;
  }
  if (!h) h = `<p class="muted">Landscape recon needs the vision model.</p>`;
  $(`.tabpane[data-pane="land"]`).innerHTML = h;
}

function renderReverse(R) {
  const rv = R.reverse || {};
  let h = `<div class="btnrow"><span class="muted small">Open in browser (upload, no key):</span>`;
  for (const [k, n] of [["yandex", "YANDEX"], ["lens", "LENS"], ["bing", "BING"], ["tineye", "TINEYE"]]) h += `<button class="chipbtn" data-rev="${k}">${n} ↗</button>`;
  h += `</div>`;
  if ((rv.landmarks || []).length) h += "<h4>Venues named in matches</h4><div class='chips'>" + rv.landmarks.map((l) => `<span class="chip hit">${esc(l.name)} ×${l.count}</span>`).join("") + "</div>";
  if ((rv.places || []).length) h += "<h4>Places named in matches</h4><div class='chips'>" + rv.places.map((p) => `<span class="chip ${p.cc === R.countries[0].iso ? "hit" : ""}">${esc(p.name)} (${esc(p.cc)}) ×${p.hits}</span>`).join("") + "</div>";
  if ((rv.phrases || []).length) h += "<h4>Recurring phrases</h4><div class='chips'>" + rv.phrases.map(([p, n]) => `<span class="chip">${esc(p)} ×${n}</span>`).join("") + "</div>";
  const runs = rv.runs || [];
  h += `<h4>Searches run (${runs.length})</h4>`;
  if (!runs.length) h += `<p class="muted">No automatic searches (offline or disabled in settings).</p>`;
  for (const r of runs) {
    const n = (r.results || []).length;
    h += `<details class="run"><summary><span class="tag ${n ? "on" : ""}">${esc((r.engine || "").toUpperCase())}</span><div class="grow">${esc(r.query)}<div class="sub small muted">${r.error ? esc(r.error).slice(0, 120) : n + " matches" + (r.tags && r.tags.length ? " · tags: " + esc(r.tags.slice(0, 4).join(", ")) : "")}</div></div>${r.url ? `<button class="chipbtn" data-open="${esc(r.url)}">OPEN</button>` : ""}</summary>
      <div class="inner">${(r.results || []).slice(0, 15).map((x) => `<div class="res"><a href="#" data-open="${esc(x.url)}">${esc(x.title || x.url)}</a><div class="sub">${esc(x.domain || "")} ${esc((x.snippet || "").slice(0, 160))}</div></div>`).join("") || "<p class='muted small'>No parsed results.</p>"}</div></details>`;
  }
  h += `<div class="teach">Searching the person-masked image, background-only crops and zoomed sign crops separately is the manual trick analysts use — GeoLens runs it automatically. Venue and place names that recur across independent result pages are geocoded and clustered with the other clues.</div>`;
  $(`.tabpane[data-pane="rev"]`).innerHTML = h;
}

function renderPrep(R) {
  const p = R.prep || {};
  let h = `<div class="kv"><div>Mirrored (selfie)</div><div>${p.mirrored ? "YES — un-mirrored" : "no"} <span class="muted small">(OCR readability ${p.quality_normal ?? "–"} normal vs ${p.quality_mirrored ?? "–"} flipped)</span></div>
    <div>People</div><div>${(p.faces || []).length} face(s)${p.person_area ? `, ${pct(p.person_area, 0)} of frame masked` : ""}</div>
    <div>OCR passes</div><div>${p.passes ?? "–"}</div>
    <div>Scene crops</div><div>${(p.crops || []).map((c) => esc(c.name)).join(", ") || "—"}</div></div>`;
  if (p.masked_src) h += `<h4>Person-masked image used for vision & search</h4><div class="thumbs"><figure><img src="${p.masked_src}"><figcaption>masked</figcaption></figure></div>`;
  h += `<div class="teach">Selfies are the hardest case: the face dominates reverse search and the vision model, and front cameras mirror text. GeoLens un-mirrors, blurs people out and searches the scene crops separately.</div>`;
  $(`.tabpane[data-pane="prep"]`).innerHTML = h;
}

function renderSun(R) {
  const sun = R.sun || {};
  const dt = R.meta.datetime;
  const local = dt ? dt.local : new Date().toISOString().slice(0, 19);
  const off = dt && dt.offset ? dt.offset : guessOffset(sun.utc, dt && dt.local);
  let h = "";
  if (sun.position) {
    const p = sun.position;
    h += `<div class="${sun.consistent ? "clue" : "notice"}"><b>Sun at capture time</b> <span class="muted small">(${esc(sun.time_basis)})</span><br>
      Elevation <b>${p.elevation}°</b>, azimuth <b>${p.azimuth}°</b>. ${p.shadow_ratio ? `Shadows → <b>${p.shadow_bearing}°</b>, <b>${p.shadow_ratio}×</b> object height.` : "Sun below the horizon."}
      ${sun.consistent ? "" : "<br>Lighting does not match — time zone, timestamp or location may be wrong."}
      ${sun.times ? `<br><span class="small muted">Sunrise ${fmtT(sun.times.sunrise_utc)} · noon ${fmtT(sun.times.solar_noon_utc)} · sunset ${fmtT(sun.times.sunset_utc)} UTC</span>` : ""}</div>`;
  } else h += `<p class="muted">No capture time in metadata${R.stats.night ? " (and this is a night image)" : ""}. Enter date/time and measure a shadow with SHADOW above the image.</p>`;
  h += `<h4>Shadow geolocation</h4><div class="form">
    <label>Local date &amp; time<input type="datetime-local" step="60" id="sunLocal" value="${esc(local.slice(0, 16))}"></label>
    <label>UTC offset<input id="sunOff" value="${esc(off)}" placeholder="+02:00"></label>
    <label>Sun elevation (°)<input id="sunEl" type="number" step="0.1" placeholder="from shadow"></label>
    <label>Tolerance (°)<input id="sunTol" type="number" step="0.1" value="1.5"></label>
    <label class="full">Shadow bearing (° from north, optional)<input id="sunAz" type="number" step="1"></label>
    <label>Object height<input id="objH" type="number" step="0.01"></label>
    <label>Shadow length<input id="shL" type="number" step="0.01"></label></div>
    <div class="btnrow"><button class="chipbtn" id="sunCalcEl">ELEVATION FROM H/L</button><button class="btn solid" id="sunLocus">PLOT POSSIBLE LOCATIONS</button><button class="chipbtn" id="sunChrono">CHRONOLOCATE AT PIN</button><button class="chipbtn" id="sunClear">CLEAR</button></div>
    <div id="sunOut" class="small"></div><div class="teach">${esc(sun.teach || "")}</div>`;
  $(`.tabpane[data-pane="sun"]`).innerHTML = h;
}
const fmtT = (s) => (s ? s.slice(11, 16) : "—");
function guessOffset(utc, local) {
  if (!utc || !local) return "+00:00";
  const m = Math.round((new Date(local + "Z") - new Date(utc)) / 60000), a = Math.abs(m);
  return `${m < 0 ? "-" : "+"}${String(Math.floor(a / 60)).padStart(2, "0")}:${String(a % 60).padStart(2, "0")}`;
}
function sunUTC() {
  const off = ($("#sunOff").value || "+00:00").trim();
  return new Date($("#sunLocal").value + ":00" + (/^[+-]\d\d:\d\d$/.test(off) ? off : "+00:00")).toISOString();
}
async function sunLocus() {
  const el = parseFloat($("#sunEl").value);
  if (isNaN(el)) return toast("Enter a sun elevation (measure a shadow first)");
  const r = await api("/api/sun/locus", { utc: sunUTC(), elevation: el, tol: parseFloat($("#sunTol").value) || 1.5, azimuth: $("#sunAz").value });
  S.layers.sun.clearLayers();
  const rend = L.canvas({ padding: 0.5 });
  for (const [la, lo] of r.points) S.layers.sun.addLayer(L.circleMarker([la, lo], { renderer: rend, radius: 2, stroke: false, fillColor: "#e0b54a", fillOpacity: 0.6 }));
  S.layers.sun.addLayer(L.circleMarker(r.subsolar, { radius: 7, color: "#e0b54a", weight: 2, fillOpacity: 0.2 }).bindTooltip("Sub-solar point"));
  $("#sunOut").textContent = `${r.count} one-degree cells match: every place where the sun stood at ${el}° at that moment.`;
  if (r.points.length) S.map.fitBounds(r.points, { padding: [20, 20] });
  addClientLog("sun", "Shadow locus plotted", "Circle of equal altitude (NOAA solar position, 1° grid)", $("#sunOut").textContent);
}
async function sunChrono() {
  const el = parseFloat($("#sunEl").value);
  if (isNaN(el)) return toast("Enter a sun elevation first");
  const Lc = S.result.location;
  const r = await api("/api/sun/chrono", { lat: Lc.lat, lon: Lc.lon, date: sunUTC(), elevation: el });
  const off = $("#sunOff").value || "+00:00", sign = off[0] === "-" ? -1 : 1;
  const mins = sign * (parseInt(off.slice(1, 3)) * 60 + parseInt(off.slice(4, 6) || 0));
  $("#sunOut").innerHTML = r.times.length ? `At the pin the sun was at ${el}° at ` + r.times.map((t) => `<b>${new Date(new Date(t.utc).getTime() + mins * 60000).toISOString().slice(11, 16)}</b> (${t.part}, az ${t.azimuth}°)`).join(" or ") : "The sun never reached that elevation there on that date.";
  addClientLog("sun", "Chronolocation", "Solve elevation(t) = measured elevation at the pin", $("#sunOut").textContent);
}

/* ---------------------------------------------------------------- shadow tool */
function startMeasure() {
  if (!S.result) return;
  S.measuring = { pts: [] };
  $("#stage").classList.add("measuring");
  $("#viewerHint").textContent = "Click the BASE of a vertical object, then its TOP, then the TIP of its shadow.";
}
function stageClick(ev) {
  if (!S.measuring || S.measuring.done) return;
  const r = $("#photo").getBoundingClientRect(), W = S.result.image.work_w, H = S.result.image.work_h;
  const sc = Math.min(r.width / W, r.height / H), ox = (r.width - W * sc) / 2, oy = (r.height - H * sc) / 2;
  S.measuring.pts.push([(ev.clientX - r.left - ox) / sc, (ev.clientY - r.top - oy) / sc]);
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
    $("#viewerHint").textContent = `Sun elevation ≈ ${el.toFixed(1)}° (pixel ratio; assumes vertical object, flat ground, side-on view).`;
    addClientLog("sun", "Shadow measured on image", "Sun elevation = atan(height / shadow length)", `${hgt.toFixed(0)} px / ${len.toFixed(0)} px → ${el.toFixed(1)}°`);
  }
}
function drawMeasure() {
  const svg = $("#ovl");
  svg.querySelectorAll(".ms").forEach((e) => e.remove());
  if (!S.measuring || !S.result) return;
  const p = S.measuring.pts, rr = Math.max(4, S.result.image.work_w / 200);
  if (p.length >= 2) svg.insertAdjacentHTML("beforeend", `<line class="ms" x1="${p[0][0]}" y1="${p[0][1]}" x2="${p[1][0]}" y2="${p[1][1]}" stroke="#fff" stroke-width="${rr / 1.5}"/>`);
  if (p.length >= 3) svg.insertAdjacentHTML("beforeend", `<line class="ms" x1="${p[0][0]}" y1="${p[0][1]}" x2="${p[2][0]}" y2="${p[2][1]}" stroke="#e0b54a" stroke-width="${rr / 1.5}" stroke-dasharray="${rr * 2}"/>`);
  p.forEach((q) => svg.insertAdjacentHTML("beforeend", `<circle class="ms" cx="${q[0]}" cy="${q[1]}" r="${rr}" fill="#fff" stroke="#000" stroke-width="2"/>`));
}

/* ---------------------------------------------------------------- log drawer */
function updateLogCount() { $("#logCount").textContent = S.log.length; }
function addClientLog(step, title, method, detail) {
  S.log.push({ id: S.log.length + 1, t: null, step, title, method, detail, level: "info", teach: "", ms: null, data: null });
  updateLogCount(); renderLog();
}
let logFilter = "all";
function renderLog() {
  const R = S.result, log = S.log;
  const total = log.reduce((a, e) => a + (e.ms || 0), 0);
  const methods = new Set(log.filter((e) => e.method).map((e) => e.method.split(" (")[0]));
  const nClues = R ? (R.evidence || []).length : 0;
  let h = `<div class="tiles"><div class="tile"><b>${log.length}</b><span>steps</span></div><div class="tile"><b>${methods.size}</b><span>techniques</span></div>
    <div class="tile"><b>${nClues}</b><span>evidence items</span></div><div class="tile"><b>${(total / 1000).toFixed(1)}s</b><span>compute</span></div></div>`;
  if (R && R.evidence && R.evidence.length) {
    h += `<div><h4>Evidence behind the decision (weight)</h4>`;
    const mx = Math.max(...R.evidence.map((e) => e.weight));
    for (const e of [...R.evidence].sort((a, b) => b.weight - a.weight).slice(0, 12)) h += `<div class="hbar"><span title="${esc(e.source)}: ${esc(e.label)}">${esc(e.label)}</span><div class="meter"><i style="width:${(e.weight / mx) * 100}%"></i></div><span class="pct">${e.weight.toFixed(2)}</span></div>`;
    h += `</div>`;
  }
  if (R && R.vision) {
    h += `<div><h4>Which part of the image mattered most</h4>`;
    for (const v of [...R.vision.views].sort((a, b) => b.share_of_top - a.share_of_top).slice(0, 8)) h += `<div class="hbar"><span>${esc(v.view)}</span><div class="meter"><i style="width:${v.share_of_top * 100}%"></i></div><span class="pct">${pct(v.share_of_top, 0)}</span></div>`;
    if (R.attention && R.attention[0]) h += `<p class="small muted">Attention hot-spots (${esc(R.attention[0].label)}): ${R.attention[0].regions.slice(0, 4).map((r) => `${r.region} ${pct(r.share, 0)}`).join(" · ")}</p>`;
    h += `</div>`;
  }
  $("#logSummary").innerHTML = h;
  const steps = ["all", ...new Set(log.map((e) => e.step))];
  $("#logFilter").innerHTML = steps.map((s) => `<button data-f="${esc(s)}" class="${s === logFilter ? "on" : ""}">${esc(s)}</button>`).join("");
  $("#logList").innerHTML = log.filter((e) => logFilter === "all" || e.step === logFilter).map((e) => `
    <div class="entry ${e.level}"><div class="entry-h"><span class="ts">${e.t != null ? "T+" + e.t.toFixed(2) + "s" : "MANUAL"}</span><span class="st">${esc(e.step)}</span>${e.ms != null ? `<span class="ms">${e.ms} ms</span>` : ""}<span class="ti">${esc(e.title)}</span></div>
    ${e.method ? `<div class="me">› ${esc(e.method)}</div>` : ""}
    ${e.detail ? `<div class="de">${esc(e.detail)}</div>` : ""}
    ${e.teach ? `<div class="teach">${esc(e.teach)}</div>` : ""}
    ${e.data != null ? `<details><summary>RAW DATA</summary><pre>${esc(JSON.stringify(e.data, null, 2)).slice(0, 12000)}</pre></details>` : ""}</div>`).join("");
}
function openDrawer() { renderLog(); $("#drawer").classList.add("open"); $("#scrim").hidden = false; }
function closeDrawer() { $("#drawer").classList.remove("open"); $("#scrim").hidden = true; }

/* ---------------------------------------------------------------- misc */
function activateTab(n) {
  $$("#tabbar button").forEach((b) => b.classList.toggle("on", b.dataset.tab === n));
  $$(".tabpane").forEach((p) => (p.hidden = p.dataset.pane !== n));
}
function setTheme(t) {
  document.documentElement.dataset.theme = t;
  try { localStorage.setItem("gl-theme", t); } catch {}
  if (S.map) {
    S.map.removeLayer(S.base); S.layerCtl.removeLayer(S.base);
    S.base = baseLayer().addTo(S.map); S.layerCtl.addBaseLayer(S.base, "Map");
    if (S.result) renderMap(S.result);
  }
}
function exportJSON() {
  const R = JSON.parse(JSON.stringify(S.result));
  delete R.image.src; if (R.prep) delete R.prep.masked_src; if (R.heat) R.heat.points = R.heat.points.slice(0, 200); (R.attention || []).forEach((m) => delete m.png);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify({ result: R, log: S.log }, null, 2)], { type: "application/json" }));
  a.download = (S.result.filename || "image").replace(/\.[^.]+$/, "") + "_geolens.json"; a.click();
}
async function openSettings() {
  const s = await api("/api/status");
  $("#setModel").innerHTML = Object.entries(s.models).map(([k, v]) => `<option value="${esc(k)}" ${k === s.settings.model ? "selected" : ""}>${esc(v)}</option>`).join("");
  $("#setOnline").checked = s.settings.online; $("#setReverse").checked = s.settings.reverse_auto; $("#setLens").checked = s.settings.lens_auto !== false;
  $("#setGeocode").checked = s.settings.geocode_ocr; $("#setOcr").checked = s.settings.ocr; $("#setAttn").checked = s.settings.attention;
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
  $("#themeBtn").addEventListener("click", () => setTheme(theme() === "dark" ? "light" : "dark"));
  $("#settingsBtn").addEventListener("click", openSettings);
  $("#setSave").addEventListener("click", () => api("/api/settings", {
    model: $("#setModel").value, online: $("#setOnline").checked, reverse_auto: $("#setReverse").checked, lens_auto: $("#setLens").checked,
    geocode_ocr: $("#setGeocode").checked, ocr: $("#setOcr").checked, attention: $("#setAttn").checked,
  }).then(() => { toast("Settings saved"); pollStatus(); }));
  $("#shadowBtn").addEventListener("click", startMeasure);
  $("#stage").addEventListener("click", stageClick);
  $("#copyBtn").addEventListener("click", () => { const L = S.result.location; navigator.clipboard.writeText(`${L.lat}, ${L.lon}`); toast("Coordinates copied"); });
  $("#gmapsBtn").addEventListener("click", () => { const L = S.result.location; openExternal(`https://www.google.com/maps/search/?api=1&query=${L.lat},${L.lon}`); });
  $("#svBtn").addEventListener("click", () => { const L = S.result.location; openExternal(`https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=${L.lat},${L.lon}`); });
  document.body.addEventListener("click", async (e) => {
    const fly = e.target.closest("[data-fly]"); if (fly) { const [a, b] = fly.dataset.fly.split(",").map(Number); S.map.flyTo([a, b], 9); return; }
    const o = e.target.closest("[data-open]"); if (o) { e.preventDefault(); e.stopPropagation(); openExternal(o.dataset.open); return; }
    const s = e.target.closest("[data-search]"); if (s) { openExternal("https://www.google.com/search?q=" + encodeURIComponent(s.dataset.search)); return; }
    const r = e.target.closest("[data-rev]");
    if (r) {
      toast("Uploading to " + r.textContent.replace(" ↗", "") + "…");
      const res = await api("/api/reverse/" + r.dataset.rev, { job: S.job, open: true });
      if (res.error) { toast(res.error.slice(0, 120) + " — opened manual page", 4000); if (res.url) openExternal(res.url); }
      addClientLog("reverse", "Manual reverse search: " + r.dataset.rev, "Web upload, no API key", res.error || res.url);
      return;
    }
    const id = e.target.id;
    if (id === "sunLocus") sunLocus();
    if (id === "sunChrono") sunChrono();
    if (id === "sunClear") { S.layers.sun.clearLayers(); $("#sunOut").textContent = ""; }
    if (id === "sunCalcEl") { const hh = parseFloat($("#objH").value), l = parseFloat($("#shL").value); if (hh > 0 && l > 0) $("#sunEl").value = ((Math.atan2(hh, l) * 180) / Math.PI).toFixed(2); }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); if (e.key.toLowerCase() === "l" && !e.target.closest("input,select") && S.log.length) openDrawer(); });
});
