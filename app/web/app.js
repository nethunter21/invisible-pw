/* VAULTSEARCH frontend. Talks to Go bindings (window.go*). When those are
   absent (plain browser preview) it falls back to an in-memory MOCK so the UI
   is fully explorable for screenshots/testing. */
"use strict";

const HAS_BACKEND = typeof window.goListDatasets === "function";

/* ---------------- backend bridge ---------------- */
const api = {
  async listDatasets(){ return HAS_BACKEND ? J(await goListDatasets()) : MOCK.list(); },
  async search(q,ds,limit,off){ return HAS_BACKEND ? J(await goSearch(q,ds||0,limit||100,off||0)) : MOCK.search(q,ds,limit,off); },
  async resolve(id,d){ return HAS_BACKEND ? J(await goResolve(id,d||2)) : MOCK.resolve(id); },
  async duplicates(n){ return HAS_BACKEND ? J(await goDuplicates(n||50)) : MOCK.duplicates(); },
  async stats(){ return HAS_BACKEND ? J(await goStats()) : MOCK.stats(); },
  async pickImport(){ return HAS_BACKEND ? J(await goPickAndImport()) : MOCK.import(); },
  async importBytes(n,b){ return HAS_BACKEND ? J(await goImportBytes(n,b)) : MOCK.import(); },
  async rename(id,n){ return HAS_BACKEND ? J(await goRename(id,n)) : {ok:true}; },
  async del(id){ return HAS_BACKEND ? J(await goDelete(id)) : MOCK.del(id); },
  async getRecord(id){ return HAS_BACKEND ? J(await goGetRecord(id)) : MOCK.record(id); },
};
function J(s){ try{return JSON.parse(s);}catch(e){return {error:String(e)}} }

/* ---------------- helpers ---------------- */
const $ = s=>document.querySelector(s);
const el=(t,c,h)=>{const e=document.createElement(t);if(c)e.className=c;if(h!=null)e.innerHTML=h;return e;};
const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,m=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
function toast(msg,err){const t=el("div","toast"+(err?" err":""),esc(msg));$("#toasts").appendChild(t);setTimeout(()=>{t.style.opacity=0;setTimeout(()=>t.remove(),250)},2600);}
function kindClass(k){return ["email","phone","name","password","hash"].includes(k)?k:"";}
function identity(k){return ["email","phone","username","uuid","national_id","account_id","ip"].includes(k);}

let STATE={view:"dash",datasets:[],scope:0};

/* ---------------- shell ---------------- */
$("#nav").addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;go(b.dataset.view);});
$("#importBtn").addEventListener("click",doImport);
$("#drawerX").addEventListener("click",()=>$("#drawer").classList.remove("open"));

function setNav(v){document.querySelectorAll("#nav button").forEach(b=>b.classList.toggle("on",b.dataset.view===v));}
const CRUMB={dash:"DASHBOARD",db:"DATABASES",search:"SEARCH",conn:"CONNECTOR",integ:"INTEGRITY"};

async function go(v){
  STATE.view=v;setNav(v);$("#crumb").textContent=CRUMB[v]||"";$("#crumbTag").textContent="";
  await refreshStats();
  if(v==="dash")renderDash();
  else if(v==="db")renderDBs();
  else if(v==="search")renderSearch();
  else if(v==="conn")renderConn();
  else if(v==="integ")renderInteg();
}

async function refreshStats(){
  const s=await api.stats();
  $("#pStat").textContent=s.datasets||0;
  $("#pRec").textContent=fmt(s.records||0);
  $("#pIdx").textContent=fmt(s.indexed||0);
}
const fmt=n=>String(n).replace(/\B(?=(\d{3})+(?!\d))/g,",");

/* ---------------- import ---------------- */
async function doImport(){
  const res=await api.pickImport();
  handleImport(res);
}
function handleImport(res){
  if(res&&res.error){toast("Import failed: "+res.error,true);return;}
  if(!res||!res.length){return;}
  let ok=0;res.forEach(r=>{if(r.error){toast("✕ "+r.error,true);}else{ok++;toast("✓ Indexed "+r.dataset.name+" — "+fmt(r.dataset.rows)+" rows · "+r.dataset.cols+" cols");}});
  if(ok)go(STATE.view==="dash"?"db":STATE.view);
}

/* ==================================================================
   DASHBOARD
================================================================== */
async function renderDash(){
  const s=await api.stats();
  const dss=await api.datasets?await api.datasets():(STATE.datasets=await api.listDatasets());
  const list=Array.isArray(dss)?dss:STATE.datasets;
  // aggregate detected kinds
  const kinds={};list.forEach(d=>{for(const k in (d.typeCount||{}))kinds[k]=(kinds[k]||0)+d.typeCount[k];});
  const topKinds=Object.entries(kinds).sort((a,b)=>b[1]-a[1]).slice(0,8);

  const v=$("#view");v.innerHTML="";
  v.append(shead("Operational Overview",`${list.length} SOURCES LINKED`));
  const g=el("div","grid g4");
  g.append(stat("Datasets",s.datasets||0,"LOADED SOURCES",true));
  g.append(stat("Records",fmt(s.records||0),"TOTAL ROWS INDEXED"));
  g.append(stat("Identity Keys",fmt(s.indexed||0),"CROSS-LINK ANCHORS"));
  g.append(stat("Field Types",Object.keys(kinds).length,"AUTO-DETECTED"));
  v.append(g);

  const g2=el("div","grid g2");g2.style.marginTop="16px";
  // detected field distribution
  const c1=el("div","card");
  c1.append(el("div","stat",`<div class="lbl">Detected Field Classes</div>`));
  const kb=el("div","",""); kb.style.marginTop="14px";
  if(!topKinds.length)kb.innerHTML=`<div style="color:var(--dim);font-family:var(--mono);font-size:11px">No data imported yet.</div>`;
  topKinds.forEach(([k,n])=>{
    const max=topKinds[0][1];
    const row=el("div","");row.style.margin="9px 0";
    row.innerHTML=`<div style="display:flex;justify-content:space-between;font-family:var(--mono);font-size:10px;letter-spacing:1px;color:var(--muted);margin-bottom:5px">
      <span class="chip ${kindClass(k)} ${identity(k)?'id':''}">${esc(k)}</span><span>${fmt(n)}</span></div>
      <div style="height:5px;border-radius:3px;background:var(--line);overflow:hidden"><i style="display:block;height:100%;width:${Math.max(6,n/max*100)}%;background:linear-gradient(90deg,var(--accent),var(--accent2))"></i></div>`;
    kb.append(row);
  });
  c1.append(kb);
  // recent sources
  const c2=el("div","card");
  c2.append(el("div","stat",`<div class="lbl">Recent Sources</div>`));
  const rb=el("div","");rb.style.marginTop="12px";
  if(!list.length)rb.innerHTML=`<div style="color:var(--dim);font-family:var(--mono);font-size:11px">—</div>`;
  list.slice(0,6).forEach(d=>{
    const row=el("div","linkrow");
    row.innerHTML=`<span class="dot"></span><span class="n">${esc(d.name)}</span><span class="b">${fmt(d.rows)} ROWS · ${d.cols} COLS</span>`;
    row.onclick=()=>{STATE.scope=d.id;go("db");};
    rb.append(row);
  });
  c2.append(rb);
  g2.append(c1,c2);v.append(g2);
}

/* ==================================================================
   DATABASES
================================================================== */
async function renderDBs(){
  STATE.datasets=await api.listDatasets();
  const v=$("#view");v.innerHTML="";
  v.append(shead("Database Registry",`${STATE.datasets.length} SOURCES`));

  const drop=el("div","drop","⭱ &nbsp; DROP CSV · TSV · TXT · JSON · XLSX · SQLITE · COMBO LISTS &nbsp;—&nbsp; DELIMITER AUTO-DETECTED ( , ; | TAB : )");
  wireDrop(drop);v.append(drop);

  if(!STATE.datasets.length){v.append(el("div","empty","NO DATABASES LOADED · IMPORT A SOURCE TO BEGIN"));return;}
  const g=el("div","grid g3");
  STATE.datasets.forEach(d=>{
    const card=el("div","dscard");
    const idCols=(d.columns||[]).filter(c=>c.role==="identity");
    const bars=(d.columns||[]).slice(0,10).map(c=>`<span class="chip ${kindClass(c.kind)} ${c.role==='identity'?'id':''}" title="${esc(c.name)} · ${esc(c.kind)}">${esc(c.kind)}</span>`).join("");
    card.innerHTML=`
      <div class="nm"><span class="dot"></span>${esc(d.name)}</div>
      <div class="meta">${fmt(d.rows)} ROWS · ${d.cols} COLUMNS · ${idCols.length} IDENTITY · ${esc(d.created||"")}</div>
      <div class="cols">${bars}</div>
      <div class="bar"><i style="width:${Math.min(100,(d.rows/ (maxRows()||1))*100)}%"></i></div>
      <div class="acts"></div>`;
    const acts=card.querySelector(".acts");
    const bExp=el("button","btn sm","⌕ Explore");bExp.onclick=ev=>{ev.stopPropagation();STATE.scope=d.id;go("search");};
    const bRen=el("button","btn sm","✎ Rename");bRen.onclick=async ev=>{ev.stopPropagation();const n=prompt("Rename dataset:",d.name);if(n){await api.rename(d.id,n);toast("Renamed");renderDBs();}};
    const bDel=el("button","btn sm danger","⌫ Delete");bDel.onclick=async ev=>{ev.stopPropagation();if(confirm("Delete "+d.name+"?")){await api.del(d.id);toast("Deleted");renderDBs();refreshStats();}};
    acts.append(bExp,bRen,bDel);
    card.onclick=()=>openSchema(d);
    g.append(card);
  });
  v.append(g);
}
function maxRows(){return Math.max(...STATE.datasets.map(d=>d.rows),1);}

function openSchema(d){
  const dr=$("#drawer");$("#drawerTitle").textContent="SCHEMA · "+d.name;
  const b=$("#drawerBody");b.innerHTML="";
  b.append(el("div","",`<div style="font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:1px;margin-bottom:14px">
    ${fmt(d.rows)} ROWS · ${d.cols} COLUMNS · SRC: <span class="src">${esc(d.source||"—")}</span></div>`));
  (d.columns||[]).forEach(c=>{
    const row=el("div","kv");
    row.innerHTML=`<span class="k">${esc(c.name)}</span>
      <span class="v"><span class="chip ${kindClass(c.kind)} ${c.role==='identity'?'id':''}">${esc(c.kind)}</span>
      <div style="font-size:9px;color:var(--dim);margin-top:4px">${fmt(c.filled||0)} filled · ${fmt(c.distinct||0)} distinct</div>
      <div style="font-size:9px;color:var(--muted);margin-top:2px">${esc(c.sample||"")}</div></span>`;
    b.append(row);
  });
  dr.classList.add("open");
}

/* ==================================================================
   SEARCH
================================================================== */
function renderSearch(){
  const v=$("#view");v.innerHTML="";
  v.append(shead("Unified Search","FTS ACROSS ALL SOURCES"));
  const bar=el("div","searchbar");
  bar.innerHTML=`<div class="inp"><span class="ic">⌕</span><input id="q" placeholder="Search names, emails, phones, accounts… across every dataset" autofocus/></div>`;
  const scope=el("select","scope");scope.id="scope";
  scope.innerHTML=`<option value="0">◈ ALL DATASETS</option>`+STATE.datasets.map(d=>`<option value="${d.id}">▤ ${esc(d.name)}</option>`).join("");
  scope.value=STATE.scope||0;
  bar.append(scope);
  const btn=el("button","btn primary","Execute");
  bar.append(btn);
  v.append(bar);
  const res=el("div","");res.id="sres";v.append(res);

  const run=async()=>{
    const q=$("#q").value.trim();const ds=+$("#scope").value;STATE.scope=ds;
    const r=await api.search(q,ds,120,0);
    renderResults(r,q);
  };
  $("#q").addEventListener("keydown",e=>{if(e.key==="Enter")run();});
  $("#q").addEventListener("input",debounce(run,220));
  scope.addEventListener("change",run);
  btn.onclick=run;
  run();
}
function renderResults(r,q){
  const box=$("#sres");box.innerHTML="";
  if(r.error){box.append(el("div","empty","ERR · "+esc(r.error)));return;}
  const recs=r.records||[];
  box.append(el("div","shead",`<span class="cnt" style="margin-left:auto">${fmt(r.total||0)} MATCH${(r.total||0)===1?"":"ES"}${q?" · \""+esc(q)+"\"":""}</span>`));
  if(!recs.length){box.append(el("div","empty","NO MATCHES"));return;}
  // dynamic columns from union of first rows
  const keys=[];const seen={};recs.slice(0,30).forEach(rec=>Object.keys(rec.data||{}).forEach(k=>{if(!seen[k]){seen[k]=1;keys.push(k);}}));
  const show=keys.slice(0,6);
  const wrap=el("div","tbl-wrap");
  const t=el("table");
  t.innerHTML=`<thead><tr><th>SOURCE</th>${show.map(k=>`<th>${esc(k)}</th>`).join("")}<th></th></tr></thead>`;
  const tb=el("tbody");
  recs.forEach(rec=>{
    const tr=el("tr");
    tr.innerHTML=`<td><span class="src">${esc(rec.dataset)}</span></td>`+
      show.map(k=>`<td class="mono">${esc((rec.data||{})[k]||"")}</td>`).join("")+
      `<td><button class="btn sm">⟐ Link</button></td>`;
    tr.querySelector("button").onclick=e=>{e.stopPropagation();openConnFor(rec.id);};
    tr.onclick=()=>openRecord(rec);
    tb.append(tr);
  });
  t.append(tb);wrap.append(t);box.append(wrap);
}

function openRecord(rec){
  $("#drawerTitle").textContent="RECORD · "+rec.dataset;
  const b=$("#drawerBody");b.innerHTML="";
  for(const k in (rec.data||{})){
    const row=el("div","kv");
    row.innerHTML=`<span class="k">${esc(k)}</span><span class="v">${esc(rec.data[k])}</span>`;
    b.append(row);
  }
  const link=el("button","btn primary","⟐ Resolve linked identity");link.style.marginTop="16px";
  link.onclick=()=>{$("#drawer").classList.remove("open");openConnFor(rec.id);};
  b.append(link);
  $("#drawer").classList.add("open");
}

/* ==================================================================
   CONNECTOR  (entity resolution graph)
================================================================== */
let CONN_SEED=null;
function openConnFor(recordId){CONN_SEED=recordId;go("conn");}

async function renderConn(){
  const v=$("#view");v.innerHTML="";
  v.append(shead("Identity Connector","CROSS-DATASET ENTITY RESOLUTION"));
  const hint=el("div","",`<div style="font-family:var(--mono);font-size:10px;color:var(--muted);letter-spacing:.5px;margin-bottom:14px;line-height:1.7">
    Select any record (from Search → <b style="color:var(--accent)">Link</b>) to map every record across your datasets that resolves to the same client — matched on shared email, phone, username or account keys.</div>`);
  v.append(hint);

  const wrap=el("div","conn-wrap");
  const graph=el("div","graph");graph.id="graph";
  const side=el("div","node-card");side.id="connSide";
  wrap.append(graph,side);v.append(wrap);

  if(!CONN_SEED){
    // show something: resolve the first record if any
    const probe=await api.search("",0,1,0);
    if(probe.records&&probe.records.length)CONN_SEED=probe.records[0].id;
  }
  if(!CONN_SEED){graph.innerHTML=`<div class="empty" style="padding:180px 0">NO RECORD SELECTED</div>`;return;}
  const g=await api.resolve(CONN_SEED,3);
  drawGraph(g);
  drawConnSide(g);
}

function drawGraph(g){
  const graph=$("#graph");graph.innerHTML="";
  const W=graph.clientWidth||760,H=460,cx=W/2,cy=H/2;
  const nodes=g.nodes||[];
  const rootIdx=Math.max(0,nodes.findIndex(n=>n.recordId===g.root));
  const pos={};
  nodes.forEach((n,i)=>{
    if(i===rootIdx){pos[n.recordId]={x:cx,y:cy};return;}
    const others=nodes.length-1||1;let k=i<rootIdx?i:i-1;
    const a=(k/others)*Math.PI*2 - Math.PI/2;
    const r=Math.min(W,H)/2-70;
    pos[n.recordId]={x:cx+Math.cos(a)*r,y:cy+Math.sin(a)*r};
  });
  const NS="http://www.w3.org/2000/svg";
  const svg=document.createElementNS(NS,"svg");svg.setAttribute("viewBox",`0 0 ${W} ${H}`);
  // merge parallel edges between the same pair into one labelled connection
  const pairs={};
  (g.edges||[]).forEach(e=>{const k=[Math.min(e.from,e.to),Math.max(e.from,e.to)].join("-");
    (pairs[k]=pairs[k]||{from:e.from,to:e.to,kinds:new Set()}).kinds.add(e.kind);});
  Object.values(pairs).forEach(e=>{
    const a=pos[e.from],b=pos[e.to];if(!a||!b)return;
    const ln=document.createElementNS(NS,"line");
    ln.setAttribute("x1",a.x);ln.setAttribute("y1",a.y);ln.setAttribute("x2",b.x);ln.setAttribute("y2",b.y);
    ln.setAttribute("stroke","rgba(40,224,180,.35)");ln.setAttribute("stroke-width","1.2");
    svg.append(ln);
    // label at 42% from source, nudged perpendicular to clear the nodes
    const t=0.42,mx=a.x+(b.x-a.x)*t,my=a.y+(b.y-a.y)*t;
    const dx=b.x-a.x,dy=b.y-a.y,len=Math.hypot(dx,dy)||1;
    const ox=-dy/len*7,oy=dx/len*7;
    const mid=document.createElementNS(NS,"text");
    mid.setAttribute("x",mx+ox);mid.setAttribute("y",my+oy);
    mid.setAttribute("fill","#5a7f93");mid.setAttribute("font-size","7.5");mid.setAttribute("font-family","JetBrains Mono");
    mid.setAttribute("text-anchor","middle");mid.setAttribute("letter-spacing","0.5");
    mid.textContent=[...e.kinds].map(k=>k.toUpperCase()).join("+");
    svg.append(mid);
  });
  // nodes
  nodes.forEach(n=>{
    const p=pos[n.recordId];const isRoot=n.recordId===g.root;
    const gp=document.createElementNS(NS,"g");gp.style.cursor="pointer";
    const c=document.createElementNS(NS,"circle");
    c.setAttribute("cx",p.x);c.setAttribute("cy",p.y);c.setAttribute("r",isRoot?17:12);
    c.setAttribute("fill",isRoot?"rgba(40,224,180,.18)":"rgba(58,160,255,.12)");
    c.setAttribute("stroke",isRoot?"#28e0b4":"#3aa0ff");c.setAttribute("stroke-width",isRoot?"2":"1.4");
    if(isRoot)c.setAttribute("filter","drop-shadow(0 0 10px rgba(40,224,180,.6))");
    const label=pickLabel(n.data);
    const tx=document.createElementNS(NS,"text");
    tx.setAttribute("x",p.x);tx.setAttribute("y",p.y+(isRoot?30:24));tx.setAttribute("text-anchor","middle");
    tx.setAttribute("fill",isRoot?"#28e0b4":"#aebfce");tx.setAttribute("font-size","9");tx.setAttribute("font-family","JetBrains Mono");
    tx.textContent=label;
    const ds=document.createElementNS(NS,"text");
    ds.setAttribute("x",p.x);ds.setAttribute("y",p.y+(isRoot?42:36));ds.setAttribute("text-anchor","middle");
    ds.setAttribute("fill","#4a6a7e");ds.setAttribute("font-size","7.5");ds.setAttribute("font-family","JetBrains Mono");
    ds.textContent=(n.dataset||"").toUpperCase();
    gp.append(c,tx,ds);
    gp.onclick=async()=>{CONN_SEED=n.recordId;const ng=await api.resolve(n.recordId,3);drawGraph(ng);drawConnSide(ng);};
    svg.append(gp);
  });
  graph.append(svg);
}
function pickLabel(d){d=d||{};for(const k of Object.keys(d)){const v=d[k];if(v&&/@|^[0-9+]/.test(v))return trimv(v);}for(const k in d)if(d[k])return trimv(d[k]);return "—";}
function trimv(v){v=String(v);return v.length>16?v.slice(0,16)+"…":v;}

function drawConnSide(g){
  const s=$("#connSide");s.innerHTML="";
  const n=(g.nodes||[]).length,links=(g.edges||[]).length;
  s.append(el("h3",null,"RESOLVED ENTITY"));
  s.append(el("div","",`<div style="display:flex;gap:10px;margin-bottom:14px">
    <div class="card" style="flex:1;padding:10px"><div class="stat"><div class="lbl">Records</div><div class="num accent" style="font-size:22px;margin-top:4px">${n}</div></div></div>
    <div class="card" style="flex:1;padding:10px"><div class="stat"><div class="lbl">Links</div><div class="num" style="font-size:22px;margin-top:4px">${links}</div></div></div></div>`));
  // anchor keys
  const keys=g.keys||{};
  if(Object.keys(keys).length){
    s.append(el("div","",`<div style="font-family:var(--mono);font-size:9.5px;letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;margin:6px 0 8px">Anchor Keys</div>`));
    for(const k in keys){keys[k].forEach(val=>{
      const row=el("div","kv");row.innerHTML=`<span class="k"><span class="chip id ${kindClass(k)}">${esc(k)}</span></span><span class="v">${esc(val)}</span>`;s.append(row);
    });}
  }
  s.append(el("div","",`<div style="font-family:var(--mono);font-size:9.5px;letter-spacing:1.5px;color:var(--muted);text-transform:uppercase;margin:16px 0 8px">Linked Records</div>`));
  (g.nodes||[]).forEach(nd=>{
    const row=el("div","linkrow");const isRoot=nd.recordId===g.root;
    row.innerHTML=`<span class="dot" style="background:${isRoot?'var(--accent)':'var(--accent2)'}"></span>
      <span class="n">${esc(pickLabel(nd.data))}</span>
      <span class="b">${esc(nd.dataset)}${nd.via&&nd.via.length?" · "+nd.via.join("/").toUpperCase():""}</span>`;
    row.onclick=async()=>{CONN_SEED=nd.recordId;const ng=await api.resolve(nd.recordId,3);drawGraph(ng);drawConnSide(ng);};
    s.append(row);
  });
}

/* ==================================================================
   INTEGRITY  (duplicate / shared-key report)
================================================================== */
async function renderInteg(){
  const v=$("#view");v.innerHTML="";
  v.append(shead("Integrity & De-duplication","SHARED IDENTITY KEYS ACROSS SOURCES"));
  const d=await api.duplicates(80);
  if(d.error){v.append(el("div","empty","ERR · "+esc(d.error)));return;}
  if(!d.length){v.append(el("div","empty","NO SHARED KEYS DETECTED · DATASETS ARE DISJOINT"));return;}
  const wrap=el("div","tbl-wrap");
  const t=el("table");
  t.innerHTML=`<thead><tr><th>CLASS</th><th>NORMALIZED KEY</th><th>RECORDS</th><th>APPEARS IN</th><th></th></tr></thead>`;
  const tb=el("tbody");
  d.forEach(c=>{
    const tr=el("tr");
    tr.innerHTML=`<td><span class="chip id ${kindClass(c.kind)}">${esc(c.kind)}</span></td>
      <td class="mono">${esc(c.norm)}</td>
      <td class="mono"><b style="color:var(--amber)">${c.count}</b></td>
      <td class="mono" style="font-size:10px;color:var(--accent2)">${(c.where||[]).map(esc).join(" · ")}</td>
      <td><button class="btn sm">⟐ Inspect</button></td>`;
    tr.querySelector("button").onclick=()=>{if(c.records&&c.records.length)openConnFor(c.records[0]);};
    tb.append(tr);
  });
  t.append(tb);wrap.append(t);v.append(wrap);
}

/* ---------------- shared UI bits ---------------- */
function shead(title,cnt){const h=el("div","shead");h.innerHTML=`<h2>${esc(title)}</h2><span class="ln"></span><span class="cnt">${esc(cnt||"")}</span>`;return h;}
function stat(lbl,num,foot,accent){const c=el("div","card stat");c.innerHTML=`<div class="lbl">${esc(lbl)}</div><div class="num ${accent?'accent':''}">${num}</div><div class="foot">${esc(foot||"")}</div>`;return c;}
function debounce(fn,ms){let t;return(...a)=>{clearTimeout(t);t=setTimeout(()=>fn(...a),ms);};}

function wireDrop(z){
  ["dragenter","dragover"].forEach(e=>z.addEventListener(e,ev=>{ev.preventDefault();z.classList.add("hot");}));
  ["dragleave","drop"].forEach(e=>z.addEventListener(e,ev=>{ev.preventDefault();z.classList.remove("hot");}));
  z.addEventListener("drop",async ev=>{
    const files=[...(ev.dataTransfer?.files||[])];
    for(const f of files){
      const b64=await fileB64(f);
      const r=await api.importBytes(f.name,b64);
      handleImport([r]);
    }
  });
  z.addEventListener("click",doImport);
}
function fileB64(f){return new Promise(res=>{const r=new FileReader();r.onload=()=>res(String(r.result).split(",")[1]||"");r.readAsDataURL(f);});}

/* ==================================================================
   MOCK backend (browser preview only)
================================================================== */
const MOCK=(()=>{
  const DS=[
    {id:1,name:"WEBSITE SIGNUPS",source:"signups_2024.csv",rows:18432,cols:7,created:"2026-11-24 09:12",
     columns:[{name:"email",kind:"email",role:"identity",filled:18432,distinct:18201,sample:"a.weber@proton.me"},
      {name:"full_name",kind:"name",role:"attribute",filled:18110,distinct:17980,sample:"Alicia Weber"},
      {name:"phone",kind:"phone",role:"identity",filled:14002,distinct:13890,sample:"+1 415 555 0132"},
      {name:"country",kind:"address",role:"attribute",filled:18432,distinct:64,sample:"United States"},
      {name:"plan",kind:"status",role:"attribute",filled:18432,distinct:4,sample:"pro"},
      {name:"created_at",kind:"date",role:"attribute",filled:18432,distinct:9820,sample:"2024-03-11"},
      {name:"account_id",kind:"account_id",role:"identity",filled:18432,distinct:18432,sample:"ACC-44192"}],
     typeCount:{email:1,name:1,phone:1,address:1,status:1,date:1,account_id:1}},
    {id:2,name:"BILLING LEDGER",source:"billing.xlsx",rows:9841,cols:6,created:"2026-11-24 09:15",
     columns:[{name:"customer_id",kind:"account_id",role:"identity",filled:9841,distinct:9820,sample:"ACC-44192"},
      {name:"email",kind:"email",role:"identity",filled:9400,distinct:9388,sample:"a.weber@proton.me"},
      {name:"amount",kind:"number",role:"attribute",filled:9841,distinct:3201,sample:"49.00"},
      {name:"status",kind:"status",role:"attribute",filled:9841,distinct:3,sample:"paid"},
      {name:"invoice_date",kind:"date",role:"attribute",filled:9841,distinct:410,sample:"2024-04-01"},
      {name:"card_last4",kind:"number",role:"attribute",filled:9841,distinct:5120,sample:"4471"}],
     typeCount:{account_id:1,email:1,number:2,status:1,date:1}},
    {id:3,name:"SUPPORT TICKETS",source:"zendesk_export.json",rows:5120,cols:5,created:"2026-11-24 09:18",
     columns:[{name:"requester_email",kind:"email",role:"identity",filled:5120,distinct:4410,sample:"a.weber@proton.me"},
      {name:"name",kind:"name",role:"attribute",filled:5000,distinct:4390,sample:"Alicia Weber"},
      {name:"phone",kind:"phone",role:"identity",filled:3010,distinct:2990,sample:"415-555-0132"},
      {name:"subject",kind:"text",role:"attribute",filled:5120,distinct:4800,sample:"Cannot log in"},
      {name:"priority",kind:"status",role:"attribute",filled:5120,distinct:4,sample:"high"}],
     typeCount:{email:1,name:1,phone:1,text:1,status:1}},
    {id:4,name:"CRM CONTACTS",source:"crm.sqlite",rows:12004,cols:6,created:"2026-11-24 09:21",
     columns:[{name:"username",kind:"username",role:"identity",filled:12004,distinct:11990,sample:"aliciaw"},
      {name:"email",kind:"email",role:"identity",filled:11800,distinct:11700,sample:"a.weber@proton.me"},
      {name:"company",kind:"company",role:"attribute",filled:9800,distinct:3400,sample:"Northwind Ltd"},
      {name:"owner",kind:"name",role:"attribute",filled:12004,distinct:42,sample:"Sales Team"},
      {name:"stage",kind:"status",role:"attribute",filled:12004,distinct:6,sample:"customer"},
      {name:"account_id",kind:"account_id",role:"identity",filled:12004,distinct:11990,sample:"ACC-44192"}],
     typeCount:{username:1,email:1,company:1,name:1,status:1,account_id:1}},
  ];
  const RECS={
    101:{id:101,datasetId:1,dataset:"WEBSITE SIGNUPS",data:{email:"a.weber@proton.me",full_name:"Alicia Weber",phone:"+1 415 555 0132",country:"United States",plan:"pro",created_at:"2024-03-11",account_id:"ACC-44192"}},
    102:{id:102,datasetId:2,dataset:"BILLING LEDGER",data:{customer_id:"ACC-44192",email:"a.weber@proton.me",amount:"49.00",status:"paid",invoice_date:"2024-04-01",card_last4:"4471"}},
    103:{id:103,datasetId:3,dataset:"SUPPORT TICKETS",data:{requester_email:"a.weber@proton.me",name:"Alicia Weber",phone:"415-555-0132",subject:"Cannot log in",priority:"high"}},
    104:{id:104,datasetId:4,dataset:"CRM CONTACTS",data:{username:"aliciaw",email:"a.weber@proton.me",company:"Northwind Ltd",owner:"Sales Team",stage:"customer",account_id:"ACC-44192"}},
    105:{id:105,datasetId:1,dataset:"WEBSITE SIGNUPS",data:{email:"m.santos@gmail.com",full_name:"Marco Santos",phone:"+44 7700 900821",country:"United Kingdom",plan:"free",created_at:"2024-06-02",account_id:"ACC-51120"}},
    106:{id:106,datasetId:2,dataset:"BILLING LEDGER",data:{customer_id:"ACC-51120",email:"m.santos@gmail.com",amount:"0.00",status:"trial",invoice_date:"2024-06-02",card_last4:"—"}},
  };
  const ALL=Object.values(RECS);
  return {
    stats:()=>({datasets:DS.length,records:45397,indexed:88210}),
    list:()=>DS.slice(),
    del:id=>{const i=DS.findIndex(d=>d.id===id);if(i>=0)DS.splice(i,1);return{ok:true};},
    import:()=>[{dataset:{id:99,name:"NEW SOURCE",rows:3201,cols:5}}],
    record:id=>RECS[id]||ALL[0],
    search:(q,ds)=>{let r=ALL;if(ds)r=r.filter(x=>x.datasetId===ds);
      if(q)r=r.filter(x=>JSON.stringify(x.data).toLowerCase().includes(q.toLowerCase()));
      return{total:r.length,records:r};},
    duplicates:()=>[
      {kind:"email",norm:"a.weber@proton.me",count:4,records:[101,102,103,104],where:["WEBSITE SIGNUPS","BILLING LEDGER","SUPPORT TICKETS","CRM CONTACTS"]},
      {kind:"account_id",norm:"acc-44192",count:3,records:[101,102,104],where:["WEBSITE SIGNUPS","BILLING LEDGER","CRM CONTACTS"]},
      {kind:"phone",norm:"4155550132",count:2,records:[101,103],where:["WEBSITE SIGNUPS","SUPPORT TICKETS"]},
      {kind:"email",norm:"m.santos@gmail.com",count:2,records:[105,106],where:["WEBSITE SIGNUPS","BILLING LEDGER"]},
      {kind:"account_id",norm:"acc-51120",count:2,records:[105,106],where:["WEBSITE SIGNUPS","BILLING LEDGER"]},
    ],
    resolve:id=>{
      const cluster=[101,102,103,104].includes(id)?[101,102,103,104]:[105,106];
      const nodes=cluster.map(rid=>{const r=RECS[rid];const via=rid===id?[]:["email"];if([101,102,104].includes(rid)&&cluster.includes(102))via.push("account_id");if([101,103].includes(rid))via.push("phone");return{recordId:rid,datasetId:r.datasetId,dataset:r.dataset,data:r.data,via:[...new Set(via)]};});
      const edges=[];for(let i=1;i<cluster.length;i++)edges.push({kind:"email",from:cluster[0],to:cluster[i]});
      if(cluster.includes(102)){edges.push({kind:"account_id",from:101,to:102});edges.push({kind:"account_id",from:102,to:104});}
      if(cluster.includes(103))edges.push({kind:"phone",from:101,to:103});
      const keys=id<105?{email:["a.weber@proton.me"],account_id:["acc-44192"],phone:["4155550132"]}:{email:["m.santos@gmail.com"],account_id:["acc-51120"]};
      return{root:id,nodes,edges,keys};
    },
  };
})();

/* boot */
go("dash");
