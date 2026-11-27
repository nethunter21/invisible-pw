/* Public Cam Map — front-end. Shows only cameras published by their operators. */
"use strict";
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = { get(k, d) { try { const v = localStorage.getItem("pcm." + k); return v == null ? d : JSON.parse(v); } catch { return d; } }, set(k, v) { try { localStorage.setItem("pcm." + k, JSON.stringify(v)); } catch { } } };
async function api(p, opt) { const r = await fetch(p, Object.assign({ cache: "no-store" }, opt)); if (!r.ok) { let m = "HTTP " + r.status; try { m = (await r.json()).error || m; } catch { } throw new Error(m); } return r.json(); }
const CC = { FR: "France", GB: "United Kingdom", US: "United States", HK: "Hong Kong", FI: "Finland", SG: "Singapore", AU: "Australia", NZ: "New Zealand" };
const SRCNAME = { osm: "OpenStreetMap public webcams", windy: "Windy webcams" };
const TYPES = { video: ["LIVE / VIDEO", "#ff3b4e"], snap: ["SNAPSHOT", "#39c5cf"], page: ["WEB PAGE", "#f0a43a"], windy: ["WINDY", "#a371f7"] };
const camType = c => c.src === "windy" ? "windy" : c.video ? "video" : c.img ? "snap" : "page";

/* ---------------- state ---------------- */
const CAMS = new Map(); let SOURCES = [];
const typeOn = Object.assign({ video: true, snap: true, page: true, windy: true }, store.get("types", {}));
const srcOff = store.get("srcoff", {});
let wall = store.get("wall", []);
let sel = null;

/* ---------------- map ---------------- */
const map = L.map("map", { worldCopyJump: true, minZoom: 2, preferCanvas: true, zoomControl: true }).setView(store.get("view", [46.6, 2.4, 6]).slice(0, 2), store.get("view", [46.6, 2.4, 6])[2]);
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/";
const att = 'Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors';
const BASES = {
  Dark: [L.tileLayer(ESRI + "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: att }), L.tileLayer(ESRI + "Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, pane: "shadowPane" })],
  Streets: [L.tileLayer(ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: att, className: "streets" })],
  Satellite: [L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }), L.tileLayer(ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, pane: "shadowPane" })],
};
let base = store.get("base", "Dark");
function setBase(b) { Object.values(BASES).flat().forEach(l => map.removeLayer(l)); BASES[b].forEach(l => l.addTo(map)); base = b; store.set("base", b); $$("#basesw button").forEach(x => x.classList.toggle("on", x.dataset.b === b)); }
$("#basesw").innerHTML = Object.keys(BASES).map(b => `<button data-b="${b}">${b}</button>`).join("");
$("#basesw").onclick = e => e.target.dataset.b && setBase(e.target.dataset.b);
setBase(BASES[base] ? base : "Dark");
const cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: z => z < 6 ? 60 : z < 10 ? 45 : 30, disableClusteringAtZoom: 15, spiderfyOnMaxZoom: true, showCoverageOnHover: false });
map.addLayer(cluster);
const MARK = new Map();
function icon(c) { const t = camType(c); return L.divIcon({ className: "", iconSize: [14, 14], html: `<div class="cm ${t === "video" || t === "windy" ? "vid" : ""} ${sel === c.id ? "sel" : ""}" style="color:${TYPES[t][1]};position:relative"></div>` }); }
function visible(c) { return typeOn[camType(c)] && !srcOff[c.src]; }
function addCams(list) {
  const add = [];
  list.forEach(c => {
    if (!isFinite(c.lat) || !isFinite(c.lon) || (c.lat === 0 && c.lon === 0)) return;
    const old = CAMS.get(c.id); CAMS.set(c.id, c);
    if (old) { const m = MARK.get(c.id); if (m) m._cam = c; return; }
    const m = L.marker([c.lat, c.lon], { icon: icon(c) }); m._cam = c;
    m.on("click", () => openCam(m._cam.id));
    m.bindTooltip(() => { const x = m._cam; return `<div class="tt"><b>${h(x.name)}</b><br><span class="mut">${h(srcLabel(x.src))}</span>${x.img ? `<img src="${h(imgURL(x))}" loading="lazy">` : ""}</div>`; }, { direction: "top", offset: [0, -6], opacity: 1 });
    MARK.set(c.id, m); if (visible(c)) add.push(m);
  });
  cluster.addLayers(add);
  $("#ncams").textContent = CAMS.size.toLocaleString();
}
function refilter() { cluster.clearLayers(); cluster.addLayers([...MARK.values()].filter(m => visible(m._cam))); renderFilters(); renderList(); }
const srcLabel = k => (SOURCES.find(s => s.Key === k) || {}).Name || SRCNAME[k] || k;
function imgURL(c, bust) { if (!c.img) return ""; if (!bust || c.src === "windy" || c.src === "sg-lta") return c.img; return c.img + (c.img.includes("?") ? "&" : "?") + "_t=" + Math.floor(Date.now() / 10000); }

/* ---------------- filters & list ---------------- */
function renderFilters() {
  const cnt = {}, scnt = {};
  CAMS.forEach(c => { cnt[camType(c)] = (cnt[camType(c)] || 0) + 1; scnt[c.src] = (scnt[c.src] || 0) + 1; });
  $("#types").innerHTML = Object.entries(TYPES).map(([k, [n, col]]) => `<button class="chip ${typeOn[k] ? "on" : ""}" data-t="${k}"><span style="color:${col}">●</span> ${n}<i>${cnt[k] || 0}</i></button>`).join("");
  const keys = [...new Set([...SOURCES.map(s => s.Key), ...Object.keys(scnt)])];
  $("#srcs").innerHTML = keys.sort((a, b) => (b.startsWith("fr") - a.startsWith("fr")) || (scnt[b] || 0) - (scnt[a] || 0)).map(k => `<button class="chip ${srcOff[k] ? "" : "on"}" data-s="${k}" title="${h(srcLabel(k))}">${h(shortSrc(k))}<i>${scnt[k] || 0}</i></button>`).join("");
}
const shortSrc = k => ({ "fr-lyon": "🇫🇷 Lyon", "fr-grenoble": "🇫🇷 Grenoble", osm: "OSM webcams", windy: "Windy", "uk-tfl": "London", "us-nyc": "New York", "us-caltrans": "California", "hk-td": "Hong Kong", "fi-digitraffic": "Finland", "sg-lta": "Singapore", "au-nsw": "Sydney/NSW", "nz-nzta": "New Zealand" }[k] || k);
$("#types").onclick = e => { const t = e.target.closest(".chip")?.dataset.t; if (t) { typeOn[t] = !typeOn[t]; store.set("types", typeOn); refilter(); } };
$("#srcs").onclick = e => { const s = e.target.closest(".chip")?.dataset.s; if (s) { srcOff[s] = !srcOff[s]; store.set("srcoff", srcOff); refilter(); } };
function inView() { const b = map.getBounds().pad(0.02), c = map.getCenter(); const out = []; CAMS.forEach(x => { if (visible(x) && b.contains([x.lat, x.lon])) out.push(x); }); out.sort((a, b2) => map.distance(c, [a.lat, a.lon]) - map.distance(c, [b2.lat, b2.lon])); return out; }
function renderList() {
  const v = inView(); $("#nview").textContent = v.length.toLocaleString();
  $("#list").innerHTML = v.length ? v.slice(0, 80).map(c => { const t = camType(c); return `<div class="it ${sel === c.id ? "sel" : ""}" data-id="${h(c.id)}"><div class="th" ${c.img ? `style="background-image:url('${h(c.img)}')"` : ""}><span class="b" style="background:${TYPES[t][1]}">${t === "video" ? "VIDEO" : t === "windy" ? "LIVE" : t === "page" ? "PAGE" : "IMG"}</span></div><div><div class="n">${h(c.name)}</div><div class="m">${h(c.city || CC[c.cc] || "")}</div><div class="m">${h(shortSrc(c.src))}</div></div></div>`; }).join("") + (v.length > 80 ? `<div class="empty">+${v.length - 80} more — zoom in</div>` : "") : `<div class="empty">No cameras here.<br>${map.getZoom() < 7 ? "Zoom in: OpenStreetMap webcams load from zoom 7." : ""}${!store.get("wkey", "") ? "<br>Add a free Windy key (⚙) for many more French webcams." : ""}</div>`;
}
$("#list").onclick = e => { const id = e.target.closest(".it")?.dataset.id; if (id) openCam(id, true); };

/* ---------------- dynamic sources (OSM / Windy) ---------------- */
const osmDone = new Set(); let osmBusy = false;
function hint(t) { const el = $("#hint"); el.textContent = t; el.style.display = t ? "block" : "none"; }
async function loadOSM() {
  if (srcOff.osm || map.getZoom() < 7 || osmBusy) return;
  const b = map.getBounds(); const s = Math.floor(b.getSouth()), w = Math.floor(b.getWest()), n = Math.ceil(b.getNorth()), e = Math.ceil(b.getEast());
  const tiles = []; for (let la = s; la < n; la += 2) for (let lo = w; lo < e; lo += 2) { const k = la + "," + lo; if (!osmDone.has(k)) tiles.push([la, lo, k]); }
  if (!tiles.length) return;
  osmBusy = true; hint(`Loading OpenStreetMap public webcams… (${tiles.length} area${tiles.length > 1 ? "s" : ""})`);
  for (const [la, lo, k] of tiles.slice(0, 12)) {
    try { const d = await api(`/api/osm?s=${la}&w=${lo}&n=${la + 2}&e=${lo + 2}`); osmDone.add(k); addCams(d.map(c => Object.assign(c, { cc: c.cc || "" }))); }
    catch (err) { hint("OpenStreetMap webcams unavailable: " + err.message); setTimeout(() => hint(""), 6000); break; }
  }
  osmBusy = false; hint(""); renderList(); renderFilters();
}
const windyDone = new Set(); let windyBusy = false;
async function loadWindy(force) {
  const key = store.get("wkey", ""); if (!key || srcOff.windy || windyBusy) return;
  if (map.getZoom() < 5 && !force) return;
  const b = map.getBounds(); const r = v => Math.round(v * 2) / 2;
  const bb = [Math.min(85, r(b.getNorth())), Math.min(180, r(b.getEast())), Math.max(-85, r(b.getSouth())), Math.max(-180, r(b.getWest()))].join(",");
  if (windyDone.has(bb)) return; windyBusy = true; hint("Loading Windy webcams…");
  try {
    let total = 0;
    for (let off = 0; off < 250; off += 50) { const d = await api(`/api/windy?bbox=${bb}&offset=${off}`, { headers: { "X-Windy-Key": key } }); total = d.total; addCams(d.cams || []); if (!d.cams || d.cams.length < 50) break; }
    windyDone.add(bb); hint(total > 250 ? `Windy: ${total} webcams in this area — zoom in to load more` : ""); setTimeout(() => hint(""), 4000);
  } catch (err) { hint("Windy unavailable: " + err.message); setTimeout(() => hint(""), 6000); }
  windyBusy = false; renderList(); renderFilters();
}
let mt; map.on("moveend", () => { const c = map.getCenter(); store.set("view", [c.lat, c.lng, map.getZoom()]); renderList(); clearTimeout(mt); mt = setTimeout(() => { loadOSM(); loadWindy(); }, 450); });

/* ---------------- viewer ---------------- */
let vTimer = null, vMode = null, hls = null;
function openCam(id, fly) {
  const c = CAMS.get(id); if (!c) return;
  const prev = sel; sel = id;
  [prev, id].forEach(x => { const m = MARK.get(x); if (m) m.setIcon(icon(m._cam)); });
  $$("#list .it").forEach(r => r.classList.toggle("sel", r.dataset.id === id));
  $("#viewer").classList.remove("closed"); setTimeout(() => map.invalidateSize(), 200);
  if (fly) map.flyTo([c.lat, c.lon], Math.max(map.getZoom(), 14), { duration: 0.6 });
  $("#vtitle").textContent = c.name;
  const modes = [];
  if (c.video) modes.push(["video", c.vtype === "iframe" ? "▶ Live player" : c.vtype === "hls" ? "▶ Live stream" : "▶ Video clip"]);
  if (c.img) modes.push(["img", "◼ Snapshot"]);
  if (c.page && !c.img && !c.video) modes.push(["page", "▤ Web page"]);
  vMode = modes.find(m => m[0] === (c.src === "windy" || c.vtype === "hls" ? "video" : "img"))?.[0] || modes[0]?.[0];
  const inWall = wall.includes(id);
  $("#vbar").innerHTML = modes.map(m => `<button class="btn ${m[0] === vMode ? "pri" : ""}" data-mode="${m[0]}">${m[1]}</button>`).join("") +
    `<button class="btn" id="vwall">${inWall ? "✓ On wall" : "+ Add to wall"}</button><button class="btn" id="vzoom">⌖ Zoom</button>${c.page ? `<a class="btn" target="_blank" href="${h(c.page)}">Source page ↗</a>` : ""}<button class="btn" id="vfs">⛶</button>`;
  renderMedia(c);
  const s = SOURCES.find(x => x.Key === c.src) || {};
  $("#vinfo").innerHTML = `<div class="kv">
   <span>Camera</span><b>${h(c.name)}</b>
   ${c.info ? `<span>View / road</span><b>${h(c.info)}</b>` : ""}
   <span>Location</span><b>${h([c.city, CC[c.cc] || c.cc].filter(Boolean).join(" · ") || "—")}</b>
   <span>Coordinates</span><b><a href="#" id="vcopy">${c.lat.toFixed(5)}, ${c.lon.toFixed(5)}</a></b>
   <span>Type</span><b>${TYPES[camType(c)][0]}${c.vtype ? " (" + c.vtype + ")" : ""}</b>
   <span>Source</span><b>${h(srcLabel(c.src))}</b>
   <span>Operator</span><b>${h(s.Operator || (c.src === "osm" ? "Webcam owner (listed on OpenStreetMap)" : c.src === "windy" ? "Webcam owner via Windy.com" : "—"))}</b>
   <span>Licence</span><b>${h(s.License || (c.src === "osm" ? "Listing: ODbL; images © owner" : c.src === "windy" ? "Windy terms" : "—"))}</b>
   ${c.every ? `<span>Image updated</span><b>every ~${c.every >= 60 ? Math.round(c.every / 60) + " min" : c.every + " s"} (by operator)</b>` : ""}
   ${c.upd ? `<span>Last update</span><b>${h(new Date(c.upd).toLocaleString())}</b>` : ""}
   <span>Camera ID</span><b>${h(c.id)}</b>
  </div>
  <p class="note">Public camera published by its operator. Image refreshes every ${store.get("refresh", 20)} s in this app${c.every ? `; the operator updates it about every ${c.every >= 60 ? Math.round(c.every / 60) + " min" : c.every + " s"}` : ""}.</p>`;
}
function stopMedia() { clearInterval(vTimer); vTimer = null; if (hls) { hls.destroy(); hls = null; } }
function renderMedia(c) {
  stopMedia(); const el = $("#vmedia");
  if (vMode === "img") {
    const load = () => { const im = new Image(); im.onload = () => { el.innerHTML = ""; el.appendChild(im); el.insertAdjacentHTML("beforeend", `<div class="ov"><i></i>LIVE SNAPSHOT</div><div class="ts">loaded ${new Date().toLocaleTimeString()}</div>`); }; im.onerror = () => { if (!el.querySelector("img")) el.innerHTML = `<div class="err">Image currently unavailable from the operator.<br>${c.page ? `<a target="_blank" href="${h(c.page)}">Open source page ↗</a>` : ""}</div>`; }; im.src = imgURL(c, true); };
    el.innerHTML = `<div class="err" style="color:#6b7a90">Loading…</div>`; load(); vTimer = setInterval(load, store.get("refresh", 20) * 1000);
  } else if (vMode === "video") {
    if (c.vtype === "iframe") el.innerHTML = `<iframe src="${h(c.video)}" allow="autoplay; fullscreen" allowfullscreen></iframe>`;
    else if (c.vtype === "mp4") { el.innerHTML = `<video src="${h(c.video)}" autoplay muted loop playsinline controls></video><div class="ov"><i></i>LATEST CLIP</div>`; vTimer = setInterval(() => { const v = el.querySelector("video"); if (v) v.src = c.video + "?_t=" + Date.now(); }, 120000); }
    else if (c.vtype === "hls") {
      el.innerHTML = `<video autoplay muted playsinline controls></video><div class="ov"><i></i>LIVE STREAM</div>`;
      const v = el.querySelector("video"), src = "/api/hls?u=" + encodeURIComponent(c.video);
      const fail = () => { el.innerHTML = `<div class="err">Live stream offline right now. Showing the snapshot instead.</div>`; if (c.img) setTimeout(() => { vMode = "img"; renderMedia(c); }, 1500); };
      const go = () => { if (window.Hls && Hls.isSupported()) { hls = new Hls({ maxBufferLength: 10 }); hls.loadSource(src); hls.attachMedia(v); hls.on(Hls.Events.ERROR, (e, d) => d.fatal && fail()); } else if (v.canPlayType("application/vnd.apple.mpegurl")) { v.src = src; v.onerror = fail; } else fail(); };
      if (window.Hls) go(); else { const s = document.createElement("script"); s.src = "vendor/hls.js"; s.onload = go; s.onerror = fail; document.head.appendChild(s); }
    }
  } else if (vMode === "page") {
    el.innerHTML = `<iframe src="${h(c.page)}" referrerpolicy="no-referrer" sandbox="allow-scripts allow-same-origin allow-popups allow-presentation"></iframe><div class="ts">If blank, the site blocks embedding → use “Source page ↗”</div>`;
  } else el.innerHTML = `<div class="err">No media published for this camera.</div>`;
}
$("#vbar").onclick = e => {
  const c = CAMS.get(sel); if (!c) return;
  const m = e.target.dataset.mode; if (m) { vMode = m; $$("#vbar [data-mode]").forEach(b => b.classList.toggle("pri", b.dataset.mode === m)); renderMedia(c); }
  if (e.target.id === "vwall") { toggleWall(c.id); e.target.textContent = wall.includes(c.id) ? "✓ On wall" : "+ Add to wall"; }
  if (e.target.id === "vzoom") map.flyTo([c.lat, c.lon], 16);
  if (e.target.id === "vfs") $("#vmedia").requestFullscreen?.();
};
$("#vinfo").onclick = e => { if (e.target.id === "vcopy") { e.preventDefault(); navigator.clipboard?.writeText(e.target.textContent); e.target.textContent += "  ✓ copied"; } };
$("#vclose").onclick = () => { stopMedia(); $("#vmedia").innerHTML = ""; $("#viewer").classList.add("closed"); const p = sel; sel = null; const m = MARK.get(p); if (m) m.setIcon(icon(m._cam)); setTimeout(() => map.invalidateSize(), 200); };

/* ---------------- video wall ---------------- */
let wallN = store.get("wallN", 9), wallTimer = null;
function toggleWall(id) { wall = wall.includes(id) ? wall.filter(x => x !== id) : [...wall, id].slice(-16); store.set("wall", wall); $("#wallc").textContent = wall.length || ""; }
$("#wallc").textContent = wall.length || "";
function renderWall() {
  const n = wallN, cols = Math.sqrt(n);
  $("#wallsize").innerHTML = [4, 9, 16].map(k => `<button class="${k === n ? "on" : ""}" data-n="${k}">${Math.sqrt(k)}×${Math.sqrt(k)}</button>`).join("");
  const g = $("#wallgrid"); g.style.gridTemplateColumns = `repeat(${cols},1fr)`; g.style.gridTemplateRows = `repeat(${cols},1fr)`;
  let ids = wall.filter(id => CAMS.has(id));
  if (ids.length < n) ids = [...ids, ...inView().filter(c => c.img && !ids.includes(c.id)).slice(0, n - ids.length).map(c => c.id)];
  g.innerHTML = Array.from({ length: n }, (_, i) => { const c = CAMS.get(ids[i]); return c ? `<div class="wt" data-id="${h(c.id)}"><img data-src="${h(c.img || "")}" alt=""><div class="l">${wall.includes(c.id) ? "★ " : ""}${h(c.name)}</div><div class="t"></div></div>` : `<div class="wt empty">empty — add cameras with “+ Add to wall”</div>`; }).join("");
  const tick = () => $$("#wallgrid .wt[data-id]").forEach(t => { const c = CAMS.get(t.dataset.id); const im = t.querySelector("img"); if (!c?.img) return; const n2 = new Image(); n2.onload = () => { im.src = n2.src; t.querySelector(".t").textContent = new Date().toLocaleTimeString(); }; n2.src = imgURL(c, true); });
  tick(); clearInterval(wallTimer); wallTimer = setInterval(tick, store.get("refresh", 20) * 1000);
}
$("#wallbtn").onclick = () => { $("#wall").classList.remove("hidden"); renderWall(); };
$("#wallclose").onclick = () => { $("#wall").classList.add("hidden"); clearInterval(wallTimer); };
$("#wallclear").onclick = () => { wall = []; store.set("wall", wall); $("#wallc").textContent = ""; renderWall(); };
$("#wallsize").onclick = e => { const n = +e.target.dataset.n; if (n) { wallN = n; store.set("wallN", n); renderWall(); } };
$("#wallgrid").onclick = e => { const id = e.target.closest(".wt")?.dataset.id; if (id) { $("#wallclose").click(); openCam(id, true); } };
$("#wallgrid").oncontextmenu = e => { const id = e.target.closest(".wt")?.dataset.id; if (id && wall.includes(id)) { e.preventDefault(); toggleWall(id); renderWall(); } };

/* ---------------- quick jumps & search ---------------- */
const JUMPS = [["🇫🇷 France", 46.6, 2.4, 6, 1], ["Paris", 48.857, 2.352, 12, 1], ["Lyon", 45.76, 4.84, 12, 1], ["Marseille", 43.296, 5.37, 12, 1], ["Lille / Nord", 50.63, 3.06, 10, 1], ["Pas-de-Calais (62)", 50.5, 2.3, 9, 1], ["Calais", 50.95, 1.86, 12, 1], ["Grenoble", 45.18, 5.72, 12, 1], ["Nice", 43.70, 7.27, 12, 1], ["Bordeaux", 44.84, -0.58, 12, 1], ["Toulouse", 43.60, 1.44, 12, 1], ["Strasbourg", 48.58, 7.75, 12, 1], ["Nantes", 47.22, -1.55, 12, 1], ["Chamonix", 45.92, 6.87, 12, 1], ["London", 51.507, -0.128, 11], ["New York", 40.73, -73.95, 11], ["Los Angeles", 34.05, -118.25, 10], ["San Francisco", 37.77, -122.42, 11], ["Helsinki", 60.17, 24.94, 10], ["Hong Kong", 22.32, 114.17, 11], ["Singapore", 1.35, 103.82, 11], ["Sydney", -33.87, 151.21, 11], ["Auckland", -36.85, 174.76, 10], ["World", 30, 10, 2]];
$("#jump").innerHTML = JUMPS.map((j, i) => `<button data-i="${i}" class="${j[4] ? "fr" : ""}">${j[0]}</button>`).join("");
$("#jump").onclick = e => { const j = JUMPS[e.target.dataset.i]; if (j) map.flyTo([j[1], j[2]], j[3], { duration: 0.8 }); };
$("#q").oninput = e => {
  const v = e.target.value.trim().toLowerCase(), box = $("#qres"); if (v.length < 2) return box.style.display = "none";
  const res = [];
  JUMPS.filter(j => j[0].toLowerCase().includes(v)).forEach(j => res.push([`📍 ${h(j[0])}`, () => map.flyTo([j[1], j[2]], j[3])]));
  for (const c of CAMS.values()) { if (res.length > 30) break; if ((c.name + " " + (c.city || "") + " " + (c.info || "")).toLowerCase().includes(v)) res.push([`<span style="color:${TYPES[camType(c)][1]}">●</span> ${h(c.name)} <span class="mut">${h(c.city || CC[c.cc] || "")}</span>`, () => openCam(c.id, true)]); }
  box.innerHTML = res.length ? res.map((r, i) => `<div data-i="${i}">${r[0]}</div>`).join("") : `<div class="mut">No match in loaded cameras (zoom into an area to load OpenStreetMap/Windy webcams)</div>`; box.style.display = "block"; box._r = res;
};
$("#qres").onclick = e => { const i = e.target.closest("[data-i]")?.dataset.i; if (i != null) { $("#qres")._r[i][1](); $("#qres").style.display = "none"; $("#q").value = ""; } };
document.addEventListener("click", e => { if (!e.target.closest(".search")) $("#qres").style.display = "none"; });
document.addEventListener("keydown", e => { if (e.target.matches("input,select")) { if (e.key === "Escape") e.target.blur(); return; } if (e.key === "/") { e.preventDefault(); $("#q").focus(); } if (e.key === "w") $("#wallbtn").click(); if (e.key === "Escape") { if (!$("#wall").classList.contains("hidden")) $("#wallclose").click(); else if (!$("#settings").classList.contains("hidden")) $("#setclose").click(); else $("#vclose").click(); } });

/* ---------------- settings ---------------- */
async function renderSources() {
  try { SOURCES = await api("/api/sources"); } catch { }
  const extra = [{ Key: "windy", Name: "Windy webcams (optional free key)", Country: "World", OK: !!store.get("wkey", ""), Count: [...CAMS.values()].filter(c => c.src === "windy").length, Error: store.get("wkey", "") ? "" : "No key set" }];
  $("#srclist").innerHTML = [...SOURCES, ...extra].map(s => `<div class="src"><i class="dot ${s.OK ? "ok" : s.Error ? "bad" : ""}"></i><div>${h(s.Name)}<small>${h([s.Operator, s.License].filter(Boolean).join(" · "))}${s.Error ? ` · <span style="color:#ff8a98">${h(s.Error)}</span>` : ""}</small></div><span class="c">${s.Count ?? 0}</span></div>`).join("");
  renderFilters();
}
$("#setbtn").onclick = () => { $("#settings").classList.remove("hidden"); $("#wkey").value = store.get("wkey", ""); $("#refresh").value = store.get("refresh", 20); renderSources(); };
$("#setclose").onclick = () => $("#settings").classList.add("hidden");
$("#refresh").onchange = e => store.set("refresh", +e.target.value);
$("#wsave").onclick = () => { store.set("wkey", $("#wkey").value.trim()); windyDone.clear(); $("#wstatus").textContent = $("#wkey").value.trim() ? "Saved. Windy webcams load for the visible area (zoom ≥ 5)." : "Key removed."; loadWindy(true); renderSources(); };
$("#wtest").onclick = async () => { const k = $("#wkey").value.trim(); if (!k) return $("#wstatus").textContent = "Paste a key first."; $("#wstatus").textContent = "Testing…"; try { const d = await api("/api/windy?bbox=51.2,3.2,50.0,1.5", { headers: { "X-Windy-Key": k } }); $("#wstatus").textContent = `✓ Key works — ${d.total} public webcams in Nord/Pas-de-Calais alone.`; } catch (err) { $("#wstatus").textContent = "✗ " + err.message; } };
$("#quit").onclick = async () => { if (confirm("Quit Public Cam Map?")) { try { await fetch("/api/quit", { method: "POST" }); } catch { } document.body.innerHTML = '<div class="empty" style="margin-top:30vh">Public Cam Map stopped. You can close this window.</div>'; } };

/* ---------------- boot ---------------- */
async function loadAll() {
  hint("Loading public cameras…");
  try { addCams(await api("/api/cams")); hint(""); } catch (e) { hint("Camera service error: " + e.message); }
  renderSources(); renderList(); loadOSM(); loadWindy();
}
loadAll();
setInterval(async () => { try { addCams(await api("/api/cams")); renderList(); } catch { } }, 120000);
setInterval(() => fetch("/api/heartbeat").catch(() => { }), 30000); fetch("/api/heartbeat").catch(() => { });
