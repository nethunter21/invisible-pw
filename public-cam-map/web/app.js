/* QUIET LENS — global webcam intel. Shows only cameras that their operators publish. */
"use strict";
const $ = (s, r = document) => r.querySelector(s), $$ = (s, r = document) => [...r.querySelectorAll(s)];
const h = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const store = { get(k, d) { try { const v = localStorage.getItem("pcm." + k); return v == null ? d : JSON.parse(v); } catch { return d; } }, set(k, v) { try { localStorage.setItem("pcm." + k, JSON.stringify(v)); } catch { } } };
async function api(p, opt) { const r = await fetch(p, Object.assign({ cache: "no-store" }, opt)); if (!r.ok) { let m = "HTTP " + r.status; try { m = (await r.json()).error || m; } catch { } throw new Error(m); } return r.json(); }
const wkey = () => store.get("wkey", "");
const WH = () => ({ headers: { "X-Windy-Key": wkey() } });
const CC = { ES: "Spain", CA: "Canada", IS: "Iceland", FR: "France", GB: "United Kingdom", US: "United States", HK: "Hong Kong", FI: "Finland", SG: "Singapore", AU: "Australia", NZ: "New Zealand" };
const TYPES = { video: ["LIVE / VIDEO", "#ff3b4e"], snap: ["SNAPSHOT", "#39c5cf"], page: ["WEB PAGE", "#f0a43a"], windy: ["WINDY LIVE", "#a371f7"], custom: ["MY CAMS", "#2bd67b"] };
const camType = c => c.src === "custom" ? "custom" : c.src === "windy" ? "windy" : c.video ? "video" : c.img ? "snap" : "page";
const shortSrc = k => ({ "fr-viewsurf": "🇫🇷 Viewsurf France", "fr-opale": "🇫🇷 Calais live", "fr-vision": "🇫🇷 A16 Calais", "es-dgt": "Spain", "us-wsdot": "Washington", "ca-drivebc": "British Columbia", "ca-quebec": "Québec", "us-maryland": "Maryland", "is-vegagerdin": "Iceland", "fr-lyon": "🇫🇷 Lyon", "fr-grenoble": "🇫🇷 Grenoble", osm: "OSM webcams", windy: "Windy", custom: "My cams", "uk-tfl": "London", "us-nyc": "New York", "us-caltrans": "California", "hk-td": "Hong Kong", "fi-digitraffic": "Finland", "sg-lta": "Singapore", "au-nsw": "Sydney/NSW", "nz-nzta": "New Zealand" }[k] || k);

/* ---------------- state ---------------- */
const CAMS = new Map(); let SOURCES = [];
const typeOn = Object.assign({ video: true, snap: true, page: true, windy: true, custom: true }, store.get("types", {}));
const srcOff = store.get("srcoff", {});
let wall = store.get("wall", []);
let sel = null;
const srcLabel = k => (SOURCES.find(s => s.Key === k) || {}).Name || { osm: "OpenStreetMap public webcams", windy: "Windy webcams", custom: "My cameras" }[k] || k;

/* ---------------- map ---------------- */
const v0 = store.get("view", [46.6, 2.4, 6]);
const map = L.map("map", { worldCopyJump: true, minZoom: 2, preferCanvas: true }).setView([v0[0], v0[1]], v0[2]);
const ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/", att = "Tiles © Esri — Esri, HERE, Garmin, © OpenStreetMap contributors";
const BASES = {
  Dark: [L.tileLayer(ESRI + "Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, attribution: att }), L.tileLayer(ESRI + "Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}", { maxZoom: 16, pane: "shadowPane" })],
  Streets: [L.tileLayer(ESRI + "World_Street_Map/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: att })],
  Satellite: [L.tileLayer(ESRI + "World_Imagery/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, attribution: "Imagery © Esri, Maxar, Earthstar Geographics" }), L.tileLayer(ESRI + "Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}", { maxZoom: 19, pane: "shadowPane" })],
};
function setBase(b) { Object.values(BASES).flat().forEach(l => map.removeLayer(l)); BASES[b].forEach(l => l.addTo(map)); store.set("base", b); $$("#basesw button").forEach(x => x.classList.toggle("on", x.dataset.b === b)); }
$("#basesw").innerHTML = Object.keys(BASES).map(b => `<button data-b="${b}">${b}</button>`).join("");
$("#basesw").onclick = e => e.target.dataset.b && setBase(e.target.dataset.b);
setBase(BASES[store.get("base", "Dark")] ? store.get("base", "Dark") : "Dark");
const cluster = L.markerClusterGroup({ chunkedLoading: true, maxClusterRadius: z => z < 6 ? 60 : z < 10 ? 45 : 30, disableClusteringAtZoom: 15, spiderfyOnMaxZoom: true, showCoverageOnHover: false });
map.addLayer(cluster);
const MARK = new Map();
function icon(c) { const t = camType(c); return L.divIcon({ className: "", iconSize: [14, 14], html: `<div class="cm ${t === "video" || t === "windy" ? "vid" : ""} ${sel === c.id ? "sel" : ""}" style="color:${TYPES[t][1]};position:relative"></div>` }); }
const visible = c => typeOn[camType(c)] && !srcOff[c.src];
function addCams(list) {
  const add = [];
  list.forEach(c => {
    if (!isFinite(c.lat) || !isFinite(c.lon) || (c.lat === 0 && c.lon === 0)) return;
    const old = CAMS.get(c.id); CAMS.set(c.id, c);
    if (old) { const m = MARK.get(c.id); if (m) m._cam = c; return; }
    const m = L.marker([c.lat, c.lon], { icon: icon(c) }); m._cam = c;
    m.on("click", () => openCam(m._cam.id));
    m.bindTooltip(() => { const x = m._cam; return `<div class="tt"><b>${h(x.name)}</b><br><span class="mut">${h(srcLabel(x.src))}</span>${x.img ? `<img src="${h(x.img)}" loading="lazy">` : ""}</div>`; }, { direction: "top", offset: [0, -6], opacity: 1 });
    MARK.set(c.id, m); if (visible(c)) add.push(m);
  });
  cluster.addLayers(add);
  $("#ncams").textContent = CAMS.size.toLocaleString();
}
function removeCam(id) { const m = MARK.get(id); if (m) cluster.removeLayer(m); MARK.delete(id); CAMS.delete(id); $("#ncams").textContent = CAMS.size.toLocaleString(); }
function refilter() { cluster.clearLayers(); cluster.addLayers([...MARK.values()].filter(m => visible(m._cam))); renderFilters(); renderList(); }

/* ---------------- filters & list ---------------- */
function renderFilters() {
  const cnt = {}, scnt = {};
  CAMS.forEach(c => { cnt[camType(c)] = (cnt[camType(c)] || 0) + 1; scnt[c.src] = (scnt[c.src] || 0) + 1; });
  $("#types").innerHTML = Object.entries(TYPES).map(([k, [n, col]]) => `<button class="chip ${typeOn[k] ? "on" : ""}" data-t="${k}"><span style="color:${col}">●</span> ${n}<i>${cnt[k] || 0}</i></button>`).join("");
  const keys = [...new Set([...SOURCES.map(s => s.Key), ...Object.keys(scnt)])];
  $("#srcs").innerHTML = keys.sort((a, b) => (b.startsWith("fr") - a.startsWith("fr")) || (scnt[b] || 0) - (scnt[a] || 0)).map(k => `<button class="chip ${srcOff[k] ? "" : "on"}" data-s="${k}" title="${h(srcLabel(k))}">${h(shortSrc(k))}<i>${scnt[k] || 0}</i></button>`).join("");
}
$("#types").onclick = e => { const t = e.target.closest(".chip")?.dataset.t; if (t) { typeOn[t] = !typeOn[t]; store.set("types", typeOn); refilter(); } };
$("#srcs").onclick = e => { const s = e.target.closest(".chip")?.dataset.s; if (s) { srcOff[s] = !srcOff[s]; store.set("srcoff", srcOff); refilter(); } };
function inView() { const b = map.getBounds().pad(0.02), c = map.getCenter(), out = []; CAMS.forEach(x => { if (visible(x) && b.contains([x.lat, x.lon])) out.push(x); }); out.sort((a, b2) => map.distance(c, [a.lat, a.lon]) - map.distance(c, [b2.lat, b2.lon])); return out; }
function moreLinks(lat, lon) {
  const z = 12;
  return `<div class="more"><a href="#" data-pop="https://www.windy.com/-Webcams/webcams?${lat.toFixed(3)},${lon.toFixed(3)},${z}">Windy webcams map ↗</a><a href="#" data-pop="https://www.skylinewebcams.com/">SkylineWebcams ↗</a><a href="#" data-pop="https://www.windfinder.com/#${z}/${lat.toFixed(4)}/${lon.toFixed(4)}">Windfinder cams ↗</a><a href="#" data-pop="https://www.viewsurf.com/">Viewsurf ↗</a><a href="#" data-pop="https://www.skaping.com/">Skaping ↗</a><a href="#" data-pop="https://www.webcamtaxi.com/en/france.html">WebcamTaxi ↗</a></div><div class="mut" style="margin-top:6px">Found a public webcam there? Copy its link → <b>+ ADD CAM</b>.</div>`;
}
function renderList() {
  const v = inView(); $("#nview").textContent = v.length.toLocaleString();
  const c = map.getCenter();
  $("#list").innerHTML = (v.length ? v.slice(0, 80).map(x => { const t = camType(x); return `<div class="it ${sel === x.id ? "sel" : ""}" data-id="${h(x.id)}"><div class="th" ${x.img ? `style="background-image:url('${h(x.img)}')"` : ""}><span class="b" style="background:${TYPES[t][1]}">${t === "video" ? "VIDEO" : t === "windy" ? "LIVE" : t === "page" ? "PAGE" : t === "custom" ? "MINE" : "IMG"}</span></div><div><div class="n">${h(x.name)}</div><div class="m">${h(x.city || CC[x.cc] || "")}</div><div class="m">${h(shortSrc(x.src))}</div></div></div>`; }).join("") + (v.length > 80 ? `<div class="empty">+${v.length - 80} more — zoom in</div>` : "")
    : `<div class="empty">No cameras loaded here yet.<br>${map.getZoom() < 7 ? "Zoom in: OpenStreetMap webcams load from zoom 7.<br>" : ""}${!wkey() ? "Add a free Windy key (⚙) then ⬇ ALL FRANCE.<br>" : ""}</div>`)
    + `<div class="pad" style="padding:8px 10px"><div class="mut">FIND MORE WEBCAMS AROUND HERE</div>${moreLinks(c.lat, c.lng)}</div>`;
}
$("#list").onclick = e => { const id = e.target.closest(".it")?.dataset.id; if (id) openCam(id, true); };
document.addEventListener("click", e => { const p = e.target.closest("[data-pop]"); if (p) { e.preventDefault(); popWin(p.dataset.pop); } });
const hostName = u => { try { return new URL(u).hostname.replace(/^www\./, ""); } catch { return u; } };
function popWin(u) { window.open(u, "_blank", "popup=yes,width=1100,height=720"); }

/* ---------------- dynamic sources (OSM / Windy) ---------------- */
function hint(t, ms) { const el = $("#hint"); el.textContent = t; el.style.display = t ? "block" : "none"; if (ms) setTimeout(() => { if (el.textContent === t) hint(""); }, ms); }
const osmDone = new Set(); let osmBusy = false;
async function loadOSM() {
  if (srcOff.osm || map.getZoom() < 7 || osmBusy) return;
  const b = map.getBounds(), s = Math.floor(b.getSouth()), w = Math.floor(b.getWest()), n = Math.ceil(b.getNorth()), e = Math.ceil(b.getEast());
  const tiles = []; for (let la = s; la < n; la += 2) for (let lo = w; lo < e; lo += 2) { const k = la + "," + lo; if (!osmDone.has(k)) tiles.push([la, lo, k]); }
  if (!tiles.length) return;
  osmBusy = true; hint("Loading OpenStreetMap public webcams…");
  for (const [la, lo, k] of tiles.slice(0, 12)) {
    try { addCams(await api(`/api/osm?s=${la}&w=${lo}&n=${la + 2}&e=${lo + 2}`)); osmDone.add(k); }
    catch (err) { hint("OpenStreetMap webcams unavailable: " + err.message, 6000); break; }
  }
  osmBusy = false; if ($("#hint").textContent.startsWith("Loading OpenStreetMap")) hint(""); renderList(); renderFilters();
}
const windyDone = new Set(); let windyBusy = false;
async function loadWindy() {
  if (!wkey() || srcOff.windy || windyBusy || map.getZoom() < 5) return;
  const b = map.getBounds(), r = v => Math.round(v * 4) / 4;
  const bb = [Math.min(85, r(b.getNorth())), Math.min(180, r(b.getEast())), Math.max(-85, r(b.getSouth())), Math.max(-180, r(b.getWest()))].join(",");
  if (windyDone.has(bb)) return; windyBusy = true; hint("Loading Windy webcams for this area (up to 1,000)…");
  try { const d = await api(`/api/windy?bbox=${bb}&max=${map.getZoom() >= 9 ? 1050 : 500}`, WH()); addCams(d.cams || []); windyDone.add(bb); hint(d.total > (d.cams || []).length ? `Windy: ${d.total.toLocaleString()} webcams here, ${d.cams.length} loaded — zoom in or use ⬇ ALL FRANCE` : `Windy: ${d.cams.length} webcams loaded`, 5000); }
  catch (err) { hint("Windy unavailable: " + err.message, 6000); }
  windyBusy = false; renderList(); renderFilters();
}
let mt; map.on("moveend", () => { const c = map.getCenter(); store.set("view", [c.lat, c.lng, map.getZoom()]); renderList(); clearTimeout(mt); mt = setTimeout(() => { loadOSM(); loadWindy(); }, 450); });

/* France-wide Windy sweep */
let frPoll = null;
async function franceSweep(start) {
  if (!wkey()) { openSettings(); $("#wstatus").textContent = "Add your free Windy key first, then press ⬇ ALL FRANCE."; return; }
  try {
    const d = await api("/api/windy/france" + (start ? "" : "?cams=0"), Object.assign({ method: start ? "POST" : "GET" }, WH()));
    const s = d.state;
    $("#frbtn").textContent = s.running ? `⬇ ${s.done}/${s.total} · ${s.cams} cams` : "⬇ ALL FRANCE";
    if (s.running) { hint(`Loading all of France from Windy — region ${s.done + 1}/${s.total} (${s.region}) · ${s.cams.toLocaleString()} webcams so far`); clearTimeout(frPoll); frPoll = setTimeout(() => franceSweep(false), 2500); if (s.cams) pullSweep(); }
    else { if (s.error) hint("France sweep: " + s.error, 8000); else if (s.cams) { await pullSweep(); hint(`✓ ${s.cams.toLocaleString()} Windy webcams loaded for France`, 6000); } }
  } catch (e) { hint("France sweep failed: " + e.message, 6000); }
}
async function pullSweep() { try { const d = await api("/api/windy/france?cams=1"); addCams(d.cams || []); renderList(); renderFilters(); } catch { } }
$("#frbtn").onclick = () => franceSweep(true);

/* ================= PLAYER ENGINE ================= */
/* createPlayer(container, cam, {compact}) — live by default; rewind buffer for snapshots,
   DVR seek for HLS streams, timelapse modes for Windy. "● LIVE" always returns to live. */
let hlsLoading = null;
function needHls() { if (window.Hls) return Promise.resolve(); return hlsLoading = hlsLoading || new Promise((res, rej) => { const s = document.createElement("script"); s.src = "vendor/hls.js"; s.onload = res; s.onerror = rej; document.head.appendChild(s); }); }
function bust(u) { return u + (u.includes("?") ? "&" : "?") + "_t=" + Date.now(); }
function createPlayer(root, cam, opt = {}) {
  root.innerHTML = `<div class="player"><div class="pm"></div><div class="pctl"></div></div>`;
  const pm = $(".pm", root), ctl = $(".pctl", root);
  const P = { cam, mode: null, live: true, frames: [], idx: -1, timer: null, hls: null, destroyed: false };
  const modes = [];
  if (cam.video) modes.push(cam.vtype === "iframe" ? "windy" : cam.vtype);
  if (cam.vtype === "window") cam = Object.assign({}, cam, { page: cam.video });
  if (cam.page && cam.noembed && !cam.video && !cam.img) modes.push("window");
  if (cam.img) modes.push("img");
  if (!cam.img && !cam.video && cam.page && !cam.noembed) modes.push("page");
  P.mode = opt.mode && modes.includes(opt.mode) ? opt.mode : modes[0];
  const maxF = () => store.get("buffer", 120);
  const badge = (txt, cls) => { let b = $(".badge", pm); if (!b) { b = document.createElement("div"); pm.appendChild(b); } b.className = "badge " + cls; b.innerHTML = cls === "live" ? `<i></i>${txt}` : txt; };
  const tsl = t => { let s = $(".ts", pm); if (!s) { s = document.createElement("div"); s.className = "ts"; pm.appendChild(s); } s.textContent = t; };
  function stop() { clearInterval(P.timer); P.timer = null; if (P.hls) { P.hls.destroy(); P.hls = null; } }
  function modeSel() { return modes.length > 1 ? `<select class="msel">${modes.map(m => `<option value="${m}" ${m === P.mode ? "selected" : ""}>${{ img: "Snapshot", hls: "Live stream", mp4: "Video clip", windy: "Live player", iframe: "Live player", viewsurf: "Live player", window: "Live window", page: "Web page" }[m]}</option>`).join("")}</select>` : ""; }
  function render() {
    stop(); P.live = true;
    if (P.mode === "img") renderImg(); else if (P.mode === "hls") renderHls(); else if (P.mode === "mp4") renderMp4(); else if (P.mode === "windy") renderWindy(); else if (P.mode === "viewsurf") renderViewsurf(); else if (P.mode === "window") renderWindow(); else renderPage();
  }
  // ---- snapshots with rewind buffer ----
  function showFrame(i) {
    const f = P.frames[i]; if (!f) return;
    let im = $("img", pm); if (!im) { pm.innerHTML = ""; im = document.createElement("img"); pm.appendChild(im); }
    im.src = f.url; P.idx = i;
    const isLive = i === P.frames.length - 1 && P.live;
    badge(isLive ? "LIVE" : "⏪ REPLAY " + f.t.toLocaleTimeString(), isLive ? "live" : "rew");
    tsl(f.t.toLocaleTimeString() + (P.frames.length > 1 ? ` · ${i + 1}/${P.frames.length}` : ""));
    const r = $("input[type=range]", ctl); if (r) { r.max = Math.max(0, P.frames.length - 1); r.value = i; }
    const g = $(".golive", ctl); if (g) g.classList.toggle("on", isLive);
  }
  async function grab() {
    try {
      const r = await fetch("/api/img?u=" + encodeURIComponent(cam.src === "windy" || cam.src === "sg-lta" ? cam.img : bust(cam.img)), { cache: "no-store" });
      if (!r.ok) throw 0;
      const b = await r.blob(); if (P.destroyed) return;
      const last = P.frames[P.frames.length - 1];
      if (last && last.size === b.size) { last.t2 = new Date(); if (P.live) tsl(last.t.toLocaleTimeString() + " · checked " + last.t2.toLocaleTimeString()); return; } // unchanged frame
      P.frames.push({ url: URL.createObjectURL(b), t: new Date(), size: b.size });
      while (P.frames.length > maxF()) URL.revokeObjectURL(P.frames.shift().url);
      if (P.live) showFrame(P.frames.length - 1); else { const rg = $("input[type=range]", ctl); if (rg) rg.max = P.frames.length - 1; }
    } catch {
      // proxy failed: fall back to loading the image directly (no rewind for this frame)
      const direct = cam.src === "windy" || cam.src === "sg-lta" ? cam.img : bust(cam.img);
      const im = new Image();
      im.onload = () => { if (P.destroyed || !P.live) return; pm.innerHTML = ""; pm.appendChild(im); badge("LIVE", "live"); tsl(new Date().toLocaleTimeString()); };
      im.onerror = () => { if (!P.frames.length && !$("img", pm)) pm.innerHTML = `<div class="err">Image currently unavailable from the operator.${cam.page ? `<br><a href="#" data-pop="${h(cam.page)}">Open source page ↗</a>` : ""}</div>`; };
      im.src = direct;
    }
  }
  function renderImg() {
    pm.innerHTML = `<div class="err" style="color:#6b7a90">Connecting…</div>`;
    ctl.innerHTML = `<button class="golive on" title="Back to live (L)">● LIVE</button><button class="pb" title="Previous frame">◀</button><input type="range" min="0" max="0" value="0" title="Rewind"><button class="nb" title="Next frame">▶</button>${modeSel()}<span class="lbl">${opt.compact ? "" : "refresh " + store.get("refresh", 10) + "s"}</span>`;
    const rg = $("input", ctl);
    rg.oninput = () => { P.live = +rg.value === P.frames.length - 1; showFrame(+rg.value); };
    $(".pb", ctl).onclick = () => { if (P.idx > 0) { P.live = false; showFrame(P.idx - 1); } };
    $(".nb", ctl).onclick = () => { if (P.idx < P.frames.length - 1) { P.live = P.idx + 1 === P.frames.length - 1; showFrame(P.idx + 1); } };
    $(".golive", ctl).onclick = () => P.goLive();
    if (P.frames.length) showFrame(P.frames.length - 1);
    grab(); P.timer = setInterval(grab, store.get("refresh", 10) * 1000);
  }
  // ---- HLS live stream with DVR ----
  async function renderHls() {
    pm.innerHTML = `<video autoplay muted playsinline></video>`; const v = $("video", pm); badge("LIVE", "live");
    ctl.innerHTML = `<button class="golive on" title="Back to live (L)">● LIVE</button><button class="back">⏪ 10s</button><button class="pp">❚❚</button><button class="mute">🔇</button>${modeSel()}<span class="lbl dvr"></span>`;
    const fail = (why) => { pm.innerHTML = `<div class="err">Live stream offline right now${why ? " (" + h(why) + ")" : ""}.${cam.img ? "<br>Switching to snapshots…" : ""}</div>`; if (cam.img) setTimeout(() => { if (!P.destroyed) { P.mode = "img"; render(); } }, 1500); };
    const src = "/api/hls?u=" + encodeURIComponent(cam.video);
    try { await needHls(); } catch { return fail("player failed to load"); }
    if (P.destroyed) return;
    if (Hls.isSupported()) { P.hls = new Hls({ liveDurationInfinity: true, backBufferLength: 300 }); P.hls.loadSource(src); P.hls.attachMedia(v); P.hls.on(Hls.Events.ERROR, (e, d) => d.fatal && fail(d.details)); }
    else if (v.canPlayType("application/vnd.apple.mpegurl")) { v.src = src; v.onerror = () => fail(); } else return fail("not supported");
    const edge = () => P.hls?.liveSyncPosition ?? (v.seekable.length ? v.seekable.end(v.seekable.length - 1) : v.duration);
    const upd = () => { const lag = Math.max(0, (edge() || 0) - v.currentTime); const isLive = lag < 8 && !v.paused; badge(isLive ? "LIVE" : `⏪ ${Math.round(lag)}s BEHIND LIVE`, isLive ? "live" : "rew"); $(".golive", ctl)?.classList.toggle("on", isLive); const d = $(".dvr", ctl); if (d) d.textContent = isLive ? "" : `-${Math.round(lag)}s`; };
    v.ontimeupdate = upd; v.onpause = upd; v.onplay = upd;
    $(".back", ctl).onclick = () => { v.currentTime = Math.max(v.seekable.length ? v.seekable.start(0) : 0, v.currentTime - 10); };
    $(".pp", ctl).onclick = e => { v.paused ? v.play() : v.pause(); e.target.textContent = v.paused ? "▶" : "❚❚"; };
    $(".mute", ctl).onclick = e => { v.muted = !v.muted; e.target.textContent = v.muted ? "🔇" : "🔊"; };
    $(".golive", ctl).onclick = () => P.goLive();
  }
  // ---- mp4 clips (TfL): latest clip loops; LIVE reloads newest ----
  function renderMp4() {
    pm.innerHTML = `<video autoplay muted loop playsinline src="${h(bust(cam.video))}"></video>`; badge("LATEST CLIP", "live");
    ctl.innerHTML = `<button class="golive on" title="Load newest clip (L)">● LIVE</button><button class="pp">❚❚</button>${modeSel()}<span class="lbl">operator publishes a new clip every ~5 min</span>`;
    const v = $("video", pm);
    $(".pp", ctl).onclick = e => { v.paused ? v.play() : v.pause(); e.target.textContent = v.paused ? "▶" : "❚❚"; badge(v.paused ? "PAUSED" : "LATEST CLIP", v.paused ? "rew" : "live"); };
    $(".golive", ctl).onclick = () => P.goLive();
    P.timer = setInterval(() => { if (!v.paused) v.src = bust(cam.video); }, 150000);
  }
  // ---- Windy embedded player: live / day / month / year ----
  function renderWindy(kind = "live") {
    if (cam.src !== "windy") { pm.innerHTML = `<iframe src="${h(cam.video)}" allow="autoplay; fullscreen" allowfullscreen></iframe>`; badge("LIVE", "live"); ctl.innerHTML = `<button class="golive on" title="Reconnect to live (L)">● LIVE</button><button class="popb">Open in window ↗</button>${modeSel()}<span class="lbl">official live player</span>`; $(".golive", ctl).onclick = () => renderWindy(); $(".popb", ctl).onclick = () => popWin(cam.video); return; }
    const pl = cam.players || {}; const opts = ["live", "day", "month", "year"].filter(k => pl[k]);
    if (!opts.length && cam.video) opts.push("live");
    if (!opts.includes(kind)) kind = opts[0];
    const url = pl[kind] || cam.video;
    pm.innerHTML = `<iframe src="${h(url)}" allow="autoplay; fullscreen" allowfullscreen></iframe>`;
    badge(kind === "live" ? "LIVE" : "⏪ " + { day: "24 H TIMELAPSE", month: "30 DAY TIMELAPSE", year: "YEAR TIMELAPSE" }[kind], kind === "live" ? "live" : "rew");
    ctl.innerHTML = `<button class="golive ${kind === "live" ? "on" : ""}" title="Back to live (L)">● LIVE</button>${opts.filter(k => k !== "live").map(k => `<button data-k="${k}">⏪ ${{ day: "24h", month: "30d", year: "1y" }[k]}</button>`).join("")}${modeSel()}<span class="lbl">Windy player</span>`;
    $$("[data-k]", ctl).forEach(b => b.onclick = () => renderWindy(b.dataset.k));
    $(".golive", ctl).onclick = () => renderWindy("live");
    P.windyKind = kind;
  }
  // ---- Viewsurf: their official embeddable live player, resolved fresh on open ----
  async function renderViewsurf() {
    pm.innerHTML = `<div class="err" style="color:#6b7a90">Connecting to Viewsurf live…</div>`; badge("LIVE", "live");
    ctl.innerHTML = `<button class="golive on" title="Reconnect to live (L)">● LIVE</button><button class="popb">Open on Viewsurf ↗</button>${modeSel()}<span class="lbl">Viewsurf HD live player</span>`;
    $(".golive", ctl).onclick = () => renderViewsurf(); $(".popb", ctl).onclick = () => popWin(cam.page);
    try {
      const p = new URL(cam.video).pathname;
      const d = await api("/api/vs?p=" + encodeURIComponent(p));
      if (P.destroyed) return;
      pm.innerHTML = `<iframe src="${h(d.embed)}" allow="autoplay; fullscreen" allowfullscreen scrolling="no"></iframe>`; badge("LIVE", "live");
    } catch (e) { if (!P.destroyed) pm.innerHTML = `<div class="err">Viewsurf live player unavailable: ${h(e.message)}<br><a href="#" data-pop="${h(cam.page)}">Open on Viewsurf ↗</a></div>`; }
  }
  // ---- sites that forbid embedding: open their page in a window placed over the player ----
  function placeWin() {
    const r = pm.getBoundingClientRect(), bx = window.screenX + (window.outerWidth - window.innerWidth) / 2, by = window.screenY + (window.outerHeight - window.innerHeight);
    return { left: Math.round(bx + r.left), top: Math.round(by + r.top), width: Math.max(420, Math.round(r.width)), height: Math.max(300, Math.round(r.height)) };
  }
  function renderWindow() {
    pm.innerHTML = `<div class="err" style="color:#9aa8bb">${cam.src === "fr-viewsurf" ? "Viewsurf only allows its live player on its own site," : "This webcam's website doesn't allow being shown inside other apps,"}<br>so the live feed opens in its own window placed exactly over this player.<br><br><button class="btn pri wopen">▶ Open live window</button></div>`;
    badge("LIVE WINDOW", "live");
    ctl.innerHTML = `<button class="golive on" title="Re-open live window (L)">● LIVE</button><button class="wfit">⤢ Fit window to player</button>${modeSel()}<span class="lbl">${h(hostName(cam.page))}</span>`;
    const open = () => { const g = placeWin(); try { if (P.win && !P.win.closed) P.win.close(); } catch { } P.win = window.open(cam.page, "ql_" + cam.id.replace(/\W/g, ""), `popup=yes,left=${g.left},top=${g.top},width=${g.width},height=${g.height}`); };
    $(".wopen", pm).onclick = open; $(".golive", ctl).onclick = open;
    $(".wfit", ctl).onclick = () => { if (P.win && !P.win.closed) { const g = placeWin(); try { P.win.moveTo(g.left, g.top); P.win.resizeTo(g.width, g.height); P.win.focus(); } catch { open(); } } else open(); };
    if (opt.autoOpen !== false && !opt.compact) open();
  }
  function renderPage() {
    pm.innerHTML = `<iframe src="${h(cam.page)}" referrerpolicy="no-referrer" sandbox="allow-scripts allow-same-origin allow-popups allow-presentation allow-forms" allow="autoplay; fullscreen"></iframe>`;
    badge("WEB PAGE", "live");
    ctl.innerHTML = `<button class="golive on" title="Reload (L)">● LIVE</button><button class="popb">Open in window ↗</button>${modeSel()}<span class="lbl">If blank, the site blocks embedding → Open in window</span>`;
    $(".popb", ctl).onclick = () => popWin(cam.page); $(".golive", ctl).onclick = () => P.goLive();
  }
  ctl.addEventListener("change", e => { if (e.target.classList.contains("msel")) { P.mode = e.target.value; render(); } });
  P.goLive = () => {
    P.live = true;
    if (P.mode === "img") { if (P.frames.length) showFrame(P.frames.length - 1); grab(); }
    else if (P.mode === "hls") { const v = $("video", pm); if (v) { const e = P.hls?.liveSyncPosition; if (e) v.currentTime = e; else if (v.seekable.length) v.currentTime = v.seekable.end(v.seekable.length - 1); v.play(); const pp = $(".pp", ctl); if (pp) pp.textContent = "❚❚"; } }
    else if (P.mode === "mp4") { const v = $("video", pm); if (v) { v.src = bust(cam.video); v.play(); } badge("LATEST CLIP", "live"); }
    else if (P.mode === "windy") renderWindy("live");
    else if (P.mode === "window") { const b = $(".golive", ctl); b && b.click(); }
    else render();
  };
  P.destroy = () => { P.destroyed = true; stop(); try { if (P.win && !P.win.closed) P.win.close(); } catch { } P.frames.forEach(f => URL.revokeObjectURL(f.url)); root.innerHTML = ""; };
  P.setCam = c => { P.cam = cam = c; };
  render();
  return P;
}

/* ================= DOCKED VIEWER ================= */
let VP = null;
async function openCam(id, fly) {
  let c = CAMS.get(id); if (!c) return;
  const prev = sel; sel = id;
  [prev, id].forEach(x => { const m = MARK.get(x); if (m) m.setIcon(icon(m._cam)); });
  $$("#list .it").forEach(r => r.classList.toggle("sel", r.dataset.id === id));
  $("#viewer").classList.remove("closed"); setTimeout(() => map.invalidateSize(), 200);
  if (fly) map.flyTo([c.lat, c.lon], Math.max(map.getZoom(), 14), { duration: 0.6 });
  if (c.src === "windy" && wkey()) { try { const f = await api("/api/windy/one?id=" + encodeURIComponent(c.id), WH()); c = Object.assign({}, c, f); CAMS.set(id, c); } catch { } }
  if (sel !== id) return;
  $("#vtitle").textContent = c.name;
  VP?.destroy(); VP = createPlayer($("#vplayer"), c);
  const inWall = wall.includes(id);
  $("#vbar").innerHTML = `<button class="btn" id="vwall">${inWall ? "✓ On wall" : "+ Add to wall"}</button><button class="btn" id="vzoom">⌖ Zoom map</button>${c.page ? `<button class="btn" data-pop="${h(c.page)}">Source page ↗</button>` : ""}${c.src === "custom" ? `<button class="btn danger" id="vdel">Delete my camera</button>` : ""}`;
  const s = SOURCES.find(x => x.Key === c.src) || {};
  $("#vinfo").innerHTML = `<div class="kv">
   <span>Camera</span><b>${h(c.name)}</b>${c.info ? `<span>View / road</span><b>${h(c.info)}</b>` : ""}
   <span>Location</span><b>${h([c.city, CC[c.cc] || c.cc].filter(Boolean).join(" · ") || "—")}</b>
   <span>Coordinates</span><b><a href="#" id="vcopy">${c.lat.toFixed(5)}, ${c.lon.toFixed(5)}</a></b>
   <span>Type</span><b>${TYPES[camType(c)][0]}${c.vtype ? " (" + c.vtype + ")" : ""}</b>
   <span>Source</span><b>${h(srcLabel(c.src))}</b>
   <span>Operator</span><b>${h(s.Operator || { osm: "Webcam owner (listed on OpenStreetMap)", windy: "Webcam owner via Windy.com", custom: "Added by you" }[c.src] || "—")}</b>
   <span>Licence</span><b>${h(s.License || { osm: "Listing ODbL · images © owner", windy: "Windy terms", custom: "—" }[c.src] || "—")}</b>
   ${c.every ? `<span>Operator update rate</span><b>~${c.every >= 60 ? Math.round(c.every / 60) + " min" : c.every + " s"}</b>` : ""}
   ${c.upd ? `<span>Last update</span><b>${h(new Date(c.upd).toLocaleString())}</b>` : ""}
   <span>Camera ID</span><b>${h(c.id)}</b></div>
   <h5>FIND MORE WEBCAMS NEARBY</h5>${moreLinks(c.lat, c.lon)}`;
}
$("#vbar").onclick = e => {
  const c = CAMS.get(sel); if (!c) return;
  if (e.target.id === "vwall") { toggleWall(c.id); e.target.textContent = wall.includes(c.id) ? "✓ On wall" : "+ Add to wall"; }
  if (e.target.id === "vzoom") map.flyTo([c.lat, c.lon], 16);
  if (e.target.id === "vdel") { saveCustom(customs().filter(x => x.id !== c.id)); removeCam(c.id); closeViewer(); renderFilters(); renderList(); }
};
$("#vinfo").onclick = e => { if (e.target.id === "vcopy") { e.preventDefault(); navigator.clipboard?.writeText(e.target.textContent); e.target.textContent += "  ✓"; } };
function closeViewer() { VP?.destroy(); VP = null; $("#viewer").classList.add("closed"); $("#viewer").classList.remove("big"); const p = sel; sel = null; const m = MARK.get(p); if (m) m.setIcon(icon(m._cam)); setTimeout(() => map.invalidateSize(), 200); }
$("#vclose").onclick = closeViewer;
$("#vbig").onclick = () => { $("#viewer").classList.toggle("big"); setTimeout(() => map.invalidateSize(), 220); };
$("#vfs").onclick = () => $("#vplayer .pm")?.requestFullscreen?.();
$("#vfloat").onclick = () => { const id = sel; if (!id) return; const mode = VP?.mode; closeViewer(); floatCam(id, mode); };
// drag-resize the docked viewer
(() => { let sx, sw; const g = $("#grip"), v = $("#viewer");
  g.onmousedown = e => { sx = e.clientX; sw = v.getBoundingClientRect().width; v.classList.remove("big"); document.body.style.userSelect = "none";
    const mv = ev => { v.style.width = Math.max(320, Math.min(window.innerWidth * 0.85, sw + (sx - ev.clientX))) + "px"; };
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); document.body.style.userSelect = ""; store.set("vw", v.style.width); map.invalidateSize(); };
    document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up); };
  if (store.get("vw")) v.style.width = store.get("vw");
})();

/* ================= FLOATING PLAYERS ================= */
let fz = 900;
function floatCam(id, mode) {
  const c = CAMS.get(id); if (!c) return;
  const n = $$(".float").length;
  const f = document.createElement("div"); f.className = "float"; f.style.cssText = `left:${60 + n * 30}px;top:${60 + n * 30}px;width:520px;height:340px;z-index:${++fz}`;
  f.innerHTML = `<div class="fh"><span>${h(c.name)}</span><button class="fdock" title="Dock">⇥</button><button class="ffs" title="Fullscreen">⛶</button><button class="fx" title="Close">✕</button></div><div class="fb" style="flex:1;min-height:0;display:flex"></div>`;
  $("#floats").appendChild(f);
  const holder = $(".fb", f); holder.style.flexDirection = "column";
  const P = createPlayer(holder, c, { mode });
  f.onmousedown = () => f.style.zIndex = ++fz;
  $(".fx", f).onclick = () => { P.destroy(); f.remove(); };
  $(".ffs", f).onclick = () => f.requestFullscreen?.();
  $(".fdock", f).onclick = () => { P.destroy(); f.remove(); openCam(id); };
  const hd = $(".fh", f); hd.onmousedown = e => { if (e.target.tagName === "BUTTON") return; const r = f.getBoundingClientRect(), pr = f.parentElement.getBoundingClientRect(), ox = e.clientX - r.left, oy = e.clientY - r.top;
    const mv = ev => { f.style.left = Math.max(0, ev.clientX - pr.left - ox) + "px"; f.style.top = Math.max(0, ev.clientY - pr.top - oy) + "px"; };
    const up = () => { document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up); };
    document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up); };
}

/* ================= VIDEO WALL (live) ================= */
const LAYOUTS = { "1": [1, 1, 1], "2×2": [2, 2, 4], "3×3": [3, 3, 9], "4×4": [4, 4, 16], "1+5": [3, 3, 6, "big"], "1+7": [4, 4, 8, "big4"], "2×3": [3, 2, 6] };
let layout = store.get("layout", "2×2"), wallPlayers = [];
function toggleWall(id) { wall = wall.includes(id) ? wall.filter(x => x !== id) : [...wall, id].slice(-16); store.set("wall", wall); $("#wallc").textContent = wall.length || ""; }
$("#wallc").textContent = wall.length || "";
function destroyWall() { wallPlayers.forEach(p => p.destroy()); wallPlayers = []; }
function renderWall() {
  destroyWall();
  const [cols, rows, n, special] = LAYOUTS[layout] || LAYOUTS["2×2"];
  $("#walllayout").innerHTML = Object.keys(LAYOUTS).map(k => `<button class="${k === layout ? "on" : ""}" data-l="${k}">${k}</button>`).join("");
  $("#walllive").checked = store.get("walllive", true);
  const g = $("#wallgrid"); g.style.gridTemplateColumns = `repeat(${cols},1fr)`; g.style.gridTemplateRows = `repeat(${rows},1fr)`;
  const ids = wall.filter(id => CAMS.has(id)).slice(0, n);
  g.innerHTML = Array.from({ length: n }, (_, i) => {
    const span = i === 0 && special === "big" ? "grid-column:span 2;grid-row:span 2" : i === 0 && special === "big4" ? "grid-column:span 3;grid-row:span 3" : "";
    const c = CAMS.get(ids[i]);
    return c ? `<div class="wt" draggable="true" data-i="${i}" data-id="${h(c.id)}" style="${span}"><div class="ph" style="flex:1;min-height:0;display:flex;flex-direction:column"></div><div class="l">${h(c.name)}</div><div class="tc"><button data-a="focus" title="Make main">⤢</button><button data-a="float" title="Float">⧉</button><button data-a="fs" title="Fullscreen">⛶</button><button data-a="rm" title="Remove">✕</button></div></div>`
      : `<div class="wt empty" data-i="${i}" style="${span}">empty — open a camera and “+ Add to wall”, or “Fill from view”</div>`;
  }).join("");
  const live = store.get("walllive", true);
  $$("#wallgrid .wt[data-id]").forEach(t => { const c = CAMS.get(t.dataset.id); wallPlayers.push(createPlayer($(".ph", t), c, { compact: true, mode: live ? undefined : (c.img ? "img" : undefined) })); });
}
$("#wallbtn").onclick = () => { $("#wall").classList.remove("hidden"); renderWall(); };
$("#wallclose").onclick = () => { $("#wall").classList.add("hidden"); destroyWall(); };
$("#wallclear").onclick = () => { wall = []; store.set("wall", wall); $("#wallc").textContent = ""; renderWall(); };
$("#wallfill").onclick = () => { const n = LAYOUTS[layout][2]; const add = inView().filter(c => !wall.includes(c.id) && (c.img || c.video)).slice(0, Math.max(0, n - wall.length)).map(c => c.id); wall = [...wall, ...add]; store.set("wall", wall); $("#wallc").textContent = wall.length || ""; renderWall(); };
$("#walllayout").onclick = e => { const l = e.target.dataset.l; if (l) { layout = l; store.set("layout", l); renderWall(); } };
$("#walllive").onchange = e => { store.set("walllive", e.target.checked); renderWall(); };
$("#wallgrid").onclick = e => {
  const a = e.target.dataset.a, t = e.target.closest(".wt"); if (!a || !t?.dataset.id) return;
  const id = t.dataset.id;
  if (a === "rm") { toggleWall(id); renderWall(); }
  if (a === "focus") { wall = [id, ...wall.filter(x => x !== id)]; store.set("wall", wall); if (!LAYOUTS[layout][3]) layout = "1+5"; store.set("layout", layout); renderWall(); }
  if (a === "fs") t.requestFullscreen?.();
  if (a === "float") { $("#wallclose").click(); floatCam(id); }
};
$("#wallgrid").ondblclick = e => { const t = e.target.closest(".wt[data-id]"); if (t && !e.target.closest(".pctl,.tc")) t.requestFullscreen?.(); };
let dragI = null;
$("#wallgrid").addEventListener("dragstart", e => { const t = e.target.closest(".wt[data-id]"); if (!t) return; dragI = +t.dataset.i; t.classList.add("drag"); });
$("#wallgrid").addEventListener("dragover", e => { const t = e.target.closest(".wt"); if (t) { e.preventDefault(); $$("#wallgrid .over").forEach(x => x.classList.remove("over")); t.classList.add("over"); } });
$("#wallgrid").addEventListener("drop", e => { e.preventDefault(); const t = e.target.closest(".wt"); if (!t || dragI == null) return; const to = +t.dataset.i; const ids = wall.filter(id => CAMS.has(id)); const [m] = ids.splice(dragI, 1); ids.splice(Math.min(to, ids.length), 0, m); wall = [...ids, ...wall.filter(id => !CAMS.has(id))]; store.set("wall", wall); dragI = null; renderWall(); });
$("#wallgrid").addEventListener("dragend", () => { dragI = null; $$("#wallgrid .drag,#wallgrid .over").forEach(x => x.classList.remove("drag", "over")); });

/* ================= MY CAMERAS ================= */
const customs = () => store.get("custom", []);
function saveCustom(list) { store.set("custom", list); $("#ccount").textContent = list.length + " camera(s)"; }
function detectType(u, t) { if (t !== "auto") return t; if (/\.m3u8(\?|$)/i.test(u)) return "hls"; if (/\.mp4(\?|$)/i.test(u)) return "mp4"; if (/\.(jpe?g|png|webp|gif)(\?|$)/i.test(u)) return "img"; return "page"; }
function customToCam(x) { const t = x.type; return { id: x.id, src: "custom", lat: x.lat, lon: x.lon, name: x.name, kind: "city", cc: "", city: "Added by you", img: t === "img" ? x.url : "", video: t === "hls" || t === "mp4" ? x.url : "", vtype: t === "hls" ? "hls" : t === "mp4" ? "mp4" : "", page: t === "page" ? x.url : x.url }; }
let picking = false;
$("#addbtn").onclick = () => { $("#addcam").classList.remove("hidden"); const c = map.getCenter(); if (!$("#aclat").value) { $("#aclat").value = c.lat.toFixed(5); $("#aclon").value = c.lng.toFixed(5); } $("#acmsg").textContent = ""; };
$("#addclose").onclick = () => $("#addcam").classList.add("hidden");
$("#acpick").onclick = () => { picking = true; $("#addcam").classList.add("hidden"); document.body.classList.add("picking"); hint("Click on the map where the camera is"); };
map.on("click", e => { if (!picking) return; picking = false; document.body.classList.remove("picking"); hint(""); $("#aclat").value = e.latlng.lat.toFixed(5); $("#aclon").value = e.latlng.lng.toFixed(5); $("#addcam").classList.remove("hidden"); });
$("#acsave").onclick = () => {
  const name = $("#acname").value.trim(), u = $("#acurl").value.trim(), lat = parseFloat($("#aclat").value), lon = parseFloat($("#aclon").value);
  if (!/^https?:\/\//.test(u)) return $("#acmsg").textContent = "Enter a valid http(s) link";
  if (!isFinite(lat) || !isFinite(lon)) return $("#acmsg").textContent = "Set a location";
  const x = { id: "custom-" + Date.now(), name: name || "My webcam", url: u, type: detectType(u, $("#actype").value), lat, lon };
  saveCustom([...customs(), x]); addCams([customToCam(x)]); renderFilters(); renderList();
  $("#acname").value = $("#acurl").value = ""; $("#addcam").classList.add("hidden"); openCam(x.id, true);
};
$("#exportc").onclick = () => { const b = new Blob([JSON.stringify(customs(), null, 2)], { type: "application/json" }); const a = document.createElement("a"); a.href = URL.createObjectURL(b); a.download = "quiet-lens-my-cameras.json"; a.click(); };
$("#importc").onclick = () => $("#importf").click();
$("#importf").onchange = async e => { try { const list = JSON.parse(await e.target.files[0].text()).filter(x => x.url && isFinite(x.lat) && isFinite(x.lon)); const merged = [...customs(), ...list.filter(x => !customs().some(y => y.id === x.id))]; saveCustom(merged); addCams(merged.map(customToCam)); renderFilters(); renderList(); } catch (err) { alert("Import failed: " + err.message); } };

/* ---------------- quick jumps & search ---------------- */
const JUMPS = [["🇫🇷 France", 46.6, 2.4, 6, 1], ["Paris", 48.857, 2.352, 12, 1], ["Lyon", 45.76, 4.84, 12, 1], ["Marseille", 43.296, 5.37, 12, 1], ["Lille / Nord", 50.63, 3.06, 10, 1], ["Pas-de-Calais (62)", 50.5, 2.3, 9, 1], ["Calais", 50.95, 1.86, 12, 1], ["Coquelles", 50.935, 1.80, 13, 1], ["Boulogne", 50.725, 1.61, 12, 1], ["Dunkerque", 51.03, 2.37, 12, 1], ["Grenoble", 45.18, 5.72, 12, 1], ["Nice", 43.70, 7.27, 12, 1], ["Bordeaux", 44.84, -0.58, 12, 1], ["Toulouse", 43.60, 1.44, 12, 1], ["Strasbourg", 48.58, 7.75, 12, 1], ["Nantes", 47.22, -1.55, 12, 1], ["Chamonix", 45.92, 6.87, 12, 1], ["London", 51.507, -0.128, 11], ["New York", 40.73, -73.95, 11], ["Los Angeles", 34.05, -118.25, 10], ["San Francisco", 37.77, -122.42, 11], ["Helsinki", 60.17, 24.94, 10], ["Hong Kong", 22.32, 114.17, 11], ["Singapore", 1.35, 103.82, 11], ["Sydney", -33.87, 151.21, 11], ["Auckland", -36.85, 174.76, 10], ["World", 30, 10, 2]];
$("#jump").innerHTML = JUMPS.map((j, i) => `<button data-i="${i}" class="${j[4] ? "fr" : ""}">${j[0]}</button>`).join("");
$("#jump").onclick = e => { const j = JUMPS[e.target.dataset.i]; if (j) map.flyTo([j[1], j[2]], j[3], { duration: 0.8 }); };
$("#q").oninput = e => {
  const v = e.target.value.trim().toLowerCase(), box = $("#qres"); if (v.length < 2) return box.style.display = "none";
  const res = [];
  JUMPS.filter(j => j[0].toLowerCase().includes(v)).forEach(j => res.push([`📍 ${h(j[0])}`, () => map.flyTo([j[1], j[2]], j[3])]));
  for (const c of CAMS.values()) { if (res.length > 40) break; if ((c.name + " " + (c.city || "") + " " + (c.info || "")).toLowerCase().includes(v)) res.push([`<span style="color:${TYPES[camType(c)][1]}">●</span> ${h(c.name)} <span class="mut">${h(c.city || CC[c.cc] || "")}</span>`, () => openCam(c.id, true)]); }
  box.innerHTML = res.length ? res.map((r, i) => `<div data-i="${i}">${r[0]}</div>`).join("") : `<div class="mut">No match in loaded cameras</div>`; box.style.display = "block"; box._r = res;
};
$("#qres").onclick = e => { const i = e.target.closest("[data-i]")?.dataset.i; if (i != null) { $("#qres")._r[i][1](); $("#qres").style.display = "none"; $("#q").value = ""; } };
document.addEventListener("click", e => { if (!e.target.closest(".search")) $("#qres").style.display = "none"; });
document.addEventListener("keydown", e => {
  if (e.target.matches("input,select")) { if (e.key === "Escape") e.target.blur(); return; }
  if (e.key === "/") { e.preventDefault(); $("#q").focus(); }
  if (e.key === "w") $("#wallbtn").click();
  if (e.key === "b" && sel) $("#vbig").click();
  if (e.key === "f" && sel) $("#vfs").click();
  if (e.key === "l") { VP?.goLive(); wallPlayers.forEach(p => p.goLive()); }
  if (e.key === "Escape") { if (!$("#wall").classList.contains("hidden")) $("#wallclose").click(); else if (!$("#settings").classList.contains("hidden")) $("#setclose").click(); else if (!$("#addcam").classList.contains("hidden")) $("#addclose").click(); else closeViewer(); }
});

/* ---------------- settings ---------------- */
async function renderSources() {
  try { SOURCES = await api("/api/sources"); } catch { }
  const cnt = k => [...CAMS.values()].filter(c => c.src === k).length;
  const extra = [{ Key: "windy", Name: "Windy webcams (optional free key)", OK: !!wkey(), Count: cnt("windy"), Error: wkey() ? "" : "No key set" }, { Key: "custom", Name: "My cameras (added by you)", OK: true, Count: cnt("custom") }];
  $("#srclist").innerHTML = [...SOURCES.map(s => Object.assign({}, s, { Count: s.Key === "osm" ? cnt("osm") : s.Count })), ...extra].map(s => `<div class="src"><i class="dot ${s.OK ? "ok" : s.Error ? "bad" : ""}"></i><div>${h(s.Name)}<small>${h([s.Operator, s.License].filter(Boolean).join(" · "))}${s.Error ? ` · <span style="color:#ff8a98">${h(s.Error)}</span>` : ""}</small></div><span class="c">${(s.Count ?? 0).toLocaleString()}</span></div>`).join("");
  renderFilters();
}
function openSettings() { $("#settings").classList.remove("hidden"); $("#wkey").value = wkey(); $("#refresh").value = store.get("refresh", 10); $("#buffer").value = store.get("buffer", 120); saveCustom(customs()); renderSources(); }
$("#setbtn").onclick = openSettings;
$("#setclose").onclick = () => $("#settings").classList.add("hidden");
$("#refresh").onchange = e => store.set("refresh", +e.target.value);
$("#buffer").onchange = e => store.set("buffer", +e.target.value);
$("#wsave").onclick = () => { store.set("wkey", $("#wkey").value.trim()); windyDone.clear(); $("#wstatus").textContent = wkey() ? "Saved. Press ⬇ ALL FRANCE to load every French region, or just zoom the map." : "Key removed."; loadWindy(); renderSources(); };
$("#wtest").onclick = async () => { const k = $("#wkey").value.trim(); if (!k) return $("#wstatus").textContent = "Paste a key first."; $("#wstatus").textContent = "Testing…"; try { const d = await api("/api/windy?bbox=51.2,3.2,50.0,1.5&max=50", { headers: { "X-Windy-Key": k } }); $("#wstatus").textContent = `✓ Key works — ${d.total} public webcams in Nord / Pas-de-Calais.`; } catch (err) { $("#wstatus").textContent = "✗ " + err.message; } };
$("#quit").onclick = async () => { if (confirm("Quit Quiet Lens?")) { try { await fetch("/api/quit", { method: "POST" }); } catch { } document.body.innerHTML = '<div class="empty" style="margin-top:30vh">Quiet Lens stopped. You can close this window.</div>'; } };

/* ---------------- boot ---------------- */
async function boot() {
  hint("Loading public cameras…");
  addCams(customs().map(customToCam));
  try { addCams(await api("/api/cams")); hint(""); } catch (e) { hint("Camera service error: " + e.message); }
  await pullSweep();
  renderSources(); renderList(); loadOSM(); loadWindy();
  try { const d = await api("/api/windy/france"); if (d.state?.running) franceSweep(false); } catch { }
}
boot();
setInterval(async () => { try { addCams(await api("/api/cams")); renderList(); } catch { } }, 120000);
setInterval(() => fetch("/api/heartbeat").catch(() => { }), 30000); fetch("/api/heartbeat").catch(() => { });
