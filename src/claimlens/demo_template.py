"""Self-contained demo page template: no external requests, works from file://."""

import json
from typing import Any

CSS = """
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:1240px;
margin:1rem auto;padding:0 1rem;color:#1a1a1a;background:#fff}
h1{font-size:1.4rem;margin:.4rem 0}
h2{font-size:1.15rem;margin:.2rem 0 .6rem}
h3{font-size:1rem;margin:.8rem 0 .3rem}
p{margin:.3rem 0}
nav button{margin:0 .5rem .5rem 0;padding:.45rem .9rem;cursor:pointer;font-size:.95rem}
section.scene{display:none;border-top:2px solid #333;margin-top:.5rem;padding-top:.8rem}
section.scene.active{display:block}
.scene-grid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);
gap:1.2rem;align-items:start}
figure.doc{margin:0 0 .8rem}
img.doc{width:100%;max-height:296px;object-fit:contain;border:1px solid #ccc;
background:#fafafa}
figcaption{font-size:.8rem;color:#555}
.badge{display:inline-block;font-weight:700;padding:.15rem .6rem;border-radius:.25rem;
font-size:1rem}
.badge-paid{background:#d6ecd6;color:#145214}
.badge-partial{background:#f7e3c3;color:#7a4d0b}
.badge-none{background:#e3e3e3;color:#444}
.amount{font-size:1.5rem;font-weight:700;margin:.1rem 0}
.pinned{font-size:.8rem;color:#555}
.pill{display:inline-block;padding:.1rem .5rem;border-radius:1rem;font-size:.85rem;
margin:0 .25rem .25rem 0}
.pass{background:#dfd}.fail{background:#fdd}.na{background:#eee}
.strip{margin:.3rem 0}
.panel{border:1px solid #bbb;border-radius:.4rem;padding:.7rem 1rem;background:#fbfbfb}
.panel h4:first-child{margin-top:0}
table.bill{border-collapse:collapse;width:100%;font-size:.9rem;margin:.3rem 0}
table.bill td,table.bill th{border-bottom:1px solid #ddd;padding:.2rem .4rem;
text-align:left}
table.bill td.num,table.bill th.num{text-align:right;font-variant-numeric:tabular-nums}
code.clause{background:#efefef;padding:.05rem .3rem;border-radius:.2rem;font-size:.85rem}
ol.timeline{list-style:none;padding:0;margin:.4rem 0}
ol.timeline li{border-left:3px solid #999;padding:.2rem 0 .6rem .8rem}
ol.timeline li.tl-q{border-color:#b26a00;background:#fff7e6}
ol.timeline li.tl-final{border-color:#2e7d32}
ol.timeline p{margin:.2rem 0;font-size:.95rem;line-height:1.45}
.tool-name{font-size:.95rem}
.headline{margin:.1rem 0 .5rem;font-size:1.1rem}
.headline .badge{font-size:.95rem}
h4{font-size:.95rem;margin:.7rem 0 .25rem}
ul.tight{margin:.3rem 0;padding-left:1.2rem}
ul.tight li{margin:.15rem 0}
.warn{color:#7a4d0b;font-weight:600}
.totag{display:inline-block;background:#fff1c1;color:#6b4e00;font-size:.75rem;
font-weight:600;padding:0 .4rem;border-radius:.25rem}
small.dim{color:#666}
.num{cursor:pointer;border-bottom:1px dotted #777}
.num:focus{outline:2px solid #1a73e8;outline-offset:1px}
.num.hl{background:#ffe08a}
#prov-panel{position:fixed;right:1rem;bottom:1rem;max-width:22rem;background:#fff;
border:1px solid #333;border-radius:.4rem;padding:.7rem .9rem;font-size:.9rem;
box-shadow:0 4px 16px rgba(0,0,0,.25);z-index:10}
#prov-panel p{margin:.2rem 0}
#prov-panel .kind{font-size:.75rem;font-weight:700;text-transform:uppercase;color:#555}
#flow-view{border-top:2px solid #333;margin-top:.5rem;padding-top:.8rem}
.flow-pick{display:flex;gap:.5rem;flex-wrap:wrap;margin:.4rem 0}
.fpick{display:flex;align-items:center;gap:.4rem;padding:.35rem .6rem;cursor:pointer;font-size:.85rem}
img.thumb{width:44px;height:44px;object-fit:cover;border:1px solid #ccc}
#flow-drop{border:2px dashed #999;border-radius:.4rem;padding:.8rem;text-align:center;
color:#555;margin:.4rem 0}
.flow-main{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:1.2rem;
align-items:start;margin-top:.4rem}
.fstep{display:flex;gap:.6rem;align-items:baseline;padding:.35rem .5rem;
border-left:3px solid #ccc;margin-bottom:.25rem}
.fstep.active{border-color:#1a73e8;background:#eef4fd}
.fstep.done{border-color:#2e7d32}
.fstep span{flex:1}
#flow-play{padding:.45rem 1.2rem;font-size:1rem;cursor:pointer}
#flow-play:disabled{cursor:default;opacity:.5}
.flow-result{margin-top:.6rem}
"""

JS = """
function show(id){
  document.querySelectorAll('section.scene').forEach(s=>s.classList.remove('active'));
  const f=document.getElementById('flow-view');
  if(id==='flow'){if(f)f.style.display='block';return;}
  if(f)f.style.display='none';
  document.getElementById(id).classList.add('active');
}
const data=JSON.parse(document.getElementById('demo-data').textContent);
const PROV={};
data.scenes.forEach(s=>Object.assign(PROV,s.provenance||{}));
const nav=document.getElementById('scenes');
const fb=document.createElement('button');
fb.textContent='Guided flow';fb.onclick=()=>show('flow');
nav.appendChild(fb);
const exLabel=document.createElement('span');
exLabel.textContent='Examples: ';
nav.appendChild(exLabel);
data.scenes.forEach((s)=>{
  const b=document.createElement('button');
  b.textContent=s.title;b.onclick=()=>show(s.id);
  nav.appendChild(b);
  document.getElementById('stages').insertAdjacentHTML('beforeend',stage(s,false));
});
document.getElementById('stages').insertAdjacentHTML('afterbegin',flowView(data.flow));
let flowTimer=null;
function reducedMotion(){
  return typeof window!=='undefined'&&window.matchMedia
    &&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
function pickFlow(id){
  const ex=(data.flow.examples||[]).find(e=>e.id===id);
  if(!ex)return;
  if(flowTimer){clearTimeout(flowTimer);flowTimer=null;}
  document.getElementById('flow-steps').innerHTML=ex.steps.map((s,i)=>
    `<div class="fstep" id="fstep-${i}"><strong>${esc(s.label)}</strong>`
    +`<span>${esc(s.detail)}</span><small class="dim">${esc(s.meta)}</small></div>`
  ).join('');
  document.getElementById('flow-result').innerHTML='';
  document.getElementById('flow-msg').textContent='';
  const play=document.getElementById('flow-play');
  play.disabled=false;
  play.onclick=()=>playFlow(id);
}
function playFlow(id){
  const ex=(data.flow.examples||[]).find(e=>e.id===id);
  if(!ex)return;
  if(flowTimer){clearTimeout(flowTimer);flowTimer=null;}
  document.getElementById('flow-result').innerHTML='';
  const boxes=[...document.querySelectorAll('#flow-steps .fstep')];
  boxes.forEach(b=>b.classList.remove('active','done'));
  if(reducedMotion()||!boxes.length){
    boxes.forEach(b=>b.classList.add('done'));
    document.getElementById('flow-result').innerHTML=flowResult(ex);
    return;
  }
  let i=0;
  const next=()=>{
    if(i>0)boxes[i-1].classList.replace('active','done');
    if(i>=boxes.length){
      document.getElementById('flow-result').innerHTML=flowResult(ex);
      return;
    }
    boxes[i].classList.add('active');
    i+=1;
    flowTimer=setTimeout(next,650);
  };
  next();
}
function flowView(f){
  const picks=(f.examples||[]).map(e=>{
    const thumb=e.thumb?`<img class="thumb" src="${esc(e.thumb)}" onerror="this.remove()"/>`:'';
    return `<button class="fpick" onclick="pickFlow('${e.id}')">${thumb}${esc(e.title)}</button>`;
  }).join('');
  return `<div id="flow-view"><h2>Process a claim</h2>`
    +`<p><small class="dim">Replay mode: pick a sample. Every step below replays a recording.</small></p>`
    +`<div class="flow-pick">${picks}</div>`
    +`<div id="flow-drop">Drop a document photo here — or pick an example above.</div>`
    +`<p id="flow-msg" role="status"></p>`
    +`<div class="flow-main"><div id="flow-steps"></div>`
    +`<div><button id="flow-play" disabled>Play</button><div id="flow-result"></div></div></div></div>`;
}
function flowResult(ex){
  return `<div class="flow-result"><p>${badge(ex.result.badge)}</p>`
    +`<p class="amount">${esc(ex.result.title)}</p>`
    +`<p><button onclick="show('${ex.result.scene}')">See the full example</button></p></div>`;
}
document.addEventListener('dragover',e=>{
  if(e.target&&e.target.closest&&e.target.closest('#flow-drop'))e.preventDefault();
});
document.addEventListener('drop',e=>{
  const dz=e.target&&e.target.closest?e.target.closest('#flow-drop'):null;
  if(!dz)return;
  e.preventDefault();
  document.getElementById('flow-msg').textContent
    ='live mode needs an API key — run `claimlens` locally';
});
document.addEventListener('click',e=>{
  const el=e.target.closest?e.target.closest('.num'):null;
  if(el){showProv(el.getAttribute('data-prov'));return;}
  if(e.target.closest&&!e.target.closest('#prov-panel'))hideProv();
});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){hideProv();return;}
  if((e.key==='Enter'||e.key===' ')&&e.target.classList&&e.target.classList.contains('num')){
    e.preventDefault();showProv(e.target.getAttribute('data-prov'));
  }
});
function showProv(id){
  const r=PROV[id];if(!r)return;
  document.querySelectorAll('.num.hl').forEach(n=>n.classList.remove('hl'));
  [id].concat(r.operands||[]).forEach(o=>
    document.querySelectorAll('.num[data-prov="'+o+'"]').forEach(n=>n.classList.add('hl')));
  const p=document.getElementById('prov-panel');
  const formula=r.formula?`<p>Formula: ${esc(r.formula)}</p>`:'';
  p.innerHTML=`<p class="kind">${esc(r.kind)}</p><p><strong>${esc(r.label)}</strong></p>`
    +`<p>Value: ${esc(r.value)}</p><p>Source: ${esc(r.source)}</p>${formula}`
    +`<p><small class="dim">Esc closes · related numbers highlighted</small></p>`;
  p.style.display='block';
}
function hideProv(){
  document.getElementById('prov-panel').style.display='none';
  document.querySelectorAll('.num.hl').forEach(n=>n.classList.remove('hl'));
}
function stage(s,first){
  if(s.clips)
    return `<section class="scene${first?' active':''}" id="${s.id}"><h2>${esc(s.title)}</h2>`
      +`${headline(s)}${voiceScene(s)}</section>`;
  const right=s.timeline?timeline(s):`${reading(s)}${eligibility(s)}${result(s)}`;
  return `<section class="scene${first?' active':''}" id="${s.id}"><h2>${esc(s.title)}</h2>`
    +`${headline(s)}<div class="scene-grid"><div>${images(s)}</div><div>${right}</div></div></section>`;
}
function headline(s){
  if(s.card)
    return `<p class="headline">${badge(s.card.decision)} <strong>${pv(s.card.amount)}</strong></p>`;
  if(s.pack)
    return `<p class="headline">${badge('not adjudicated')} `
      +`<strong>Claim Pack · ${pv(s.pack.total_krw)} KRW</strong></p>`;
  if(s.timeline){
    const o=s.timeline.outcome||{};
    if(!o.decision)return '';
    return `<p class="headline">${badge(o.decision)} <strong>${pv(o.amount)}</strong> `
      +`<small class="dim">· ${pv(s.timeline.model_calls)} turns</small></p>`;
  }
  if(s.clips)
    return `<p class="headline">${badge(s.eligibility.outcome)} `
      +`<strong>${esc(s.next_step)}</strong></p>`;
  return '';
}
function voiceScene(s){
  const e=s.eligibility;
  const clips=s.clips.map(c=>{
    const pending=new Set(c.to_confirm||[]);
    const rows=Object.keys(c.facts).map(k=>{
      const tag=pending.has(k)?' <span class="totag">to confirm</span>':'';
      return `<tr><td>${esc(k)}</td><td>${esc(String(c.facts[k]))}${tag}</td>`
        +`<td><small class="dim">${esc(c.quotes[k]||'')}</small></td></tr>`;
    }).join('');
    const asks=(c.confirmations||[]).map(
      q=>`<li>${esc(q.question)} <small class="dim">(${esc(q.why)})</small></li>`
    ).join('');
    return `<h4>Clip (${esc(c.lang)})</h4>`
      +`<audio controls preload="none" src="${esc(c.audio)}"></audio>`
      +`<p>${esc(c.transcript)}</p>`
      +`<table class="bill"><tr><th>Fact</th><th>Value</th><th>Quoted words</th></tr>${rows}</table>`
      +`<p>To confirm with the person:</p><ul class="tight">${asks}</ul>`;
  }).join('');
  return `<h3>Voice intake</h3><div class="noprov"><p>${badge(e.outcome)}</p>`
    +`<p><strong>${esc(s.next_step)}</strong> (${esc(e.rule)})</p>`
    +`<p><small class="dim">${esc(e.basis)}</small></p>${clips}</div>`;
}
function timeline(s){
  const t=s.timeline;
  const seg=g=>g.prov?`<span class="num" tabindex="0" data-prov="${esc(g.prov)}">${esc(g.n)}</span>`
    :g.noprov?`<span class="noprov">${esc(g.t)}</span>`:esc(g.t);
  const items=t.entries.map(e=>{
    if(e.kind==='question')
      return `<li class="tl-q"><span class="tool-name noprov"><strong>Step ${e.n} — ask_user</strong></span>`
        +`<p class="noprov">Q: ${esc(e.question)}</p><p class="noprov">Why: ${esc(e.why_needed)}</p>`
        +`<p>A: ${pv(e.answer)}</p></li>`;
    if(e.kind==='final'||e.kind==='stopped')
      return `<li class="tl-final"><span class="tool-name noprov"><strong>Step ${e.n} — ${esc(e.kind)}</strong></span>`
        +`<p class="noprov">${esc(e.text)}</p></li>`;
    return `<li><span class="tool-name noprov"><strong>Step ${e.n} — ${esc(e.tool)}</strong></span>`
      +`<p>${(e.segments||[]).map(seg).join('')}</p></li>`;
  }).join('');
  const o=t.outcome||{};
  const head=o.decision?`<p>${badge(o.decision)}</p><p class="amount">${pv(o.amount)}</p>`:'';
  return `<h3>Agent timeline</h3>${head}`
    +`<p class="pinned">${pv(t.model_calls)} model turns · ${pv(t.tokens)} tokens · replayed trace</p>`
    +`<ol class="timeline">${items}</ol>`;
}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')}
function num(n){return Number(n).toLocaleString('en-US')}
function pv(obj){
  if(obj&&typeof obj==='object'&&obj.prov)
    return `<span class="num" tabindex="0" data-prov="${esc(obj.prov)}">${esc(obj.v)}</span>`;
  if(obj&&typeof obj==='object')return esc(obj.v!==undefined?obj.v:'');
  return esc(obj===null||obj===undefined?'':obj);
}
function reading(s){
  const r=s.reading;
  const checks=r.checks.map(c=>
    `<span class="pill ${c.passed?'pass':'fail'}">${c.passed?'✓':'✗'} ${esc(c.name)}</span>`
  ).join('');
  const diags=(r.diags||[]).map(pv).join(', ')||'-';
  return `<h3>Reading</h3><p>${esc(r.docs.join(' + '))} · ${esc(r.currency)} ·
  total ${pv(r.total)} · codes ${diags}</p>
  <p class="strip">${checks||'<span class="pill na">no bill checks</span>'}</p>`;
}
function eligibility(s){
  if(!s.eligibility)return `<h3>Eligibility</h3><p>Korean traveller abroad — engine path.</p>`;
  const e=s.eligibility;
  return `<h3>Eligibility</h3><p><strong>${esc(e.outcome)}</strong> (${esc(e.rule)})</p>
  <p class="noprov"><small class="dim">${esc(e.basis)}</small></p>`;
}
function badge(decision){
  const cls=decision==='PAID'?'paid':decision==='PARTIAL'?'partial':'none';
  return `<span class="badge badge-${cls}">${esc(decision)}</span>`;
}
function deductible(d){
  if(!d)return '';
  const head=`max(${(d.terms||[]).map(pv).join(', ')}) = ${pv(d.ours)}`;
  const text=d.match?`${head} — matches the engine`
    :`ClaimLens ${head} vs engine ${pv(d.engine)} — FLAGGED: amounts differ; the engine amount stands.`;
  const c=d.cells||{};
  const cells=`<p>① = ${pv(c.c1)} · ② = ${pv(c.c2)} · copay = ① ÷ (① + ②) = ${pv(c.copay)}</p>`;
  return `<h3>Deductible check (computed by ClaimLens from the reading)</h3>${cells}<p>${text}</p>`;
}
function result(s){
  if(s.card)return engineCard(s.card);
  return packPanel(s.pack);
}
function engineCard(c){
  const steps=c.steps.map(i=>`<li>${esc(i.text)}</li>`).join('');
  const clauses=c.clauses.map(
    i=>`<li><code class="clause">${esc(i.id)}</code> (${esc(i.title)}): ${esc(i.text)}</li>`
  ).join('');
  const guards=(c.guardrails||[]).length
    ?`<p class="noprov">Guardrails: ${esc(c.guardrails.join(', '))}</p>`:'';
  return `<h3>Engine card</h3><p>${badge(c.decision)}</p><p class="amount">${pv(c.amount)}</p>
  <p class="pinned">pre-existing open-source engine, pinned</p>
  <p class="noprov">${esc(c.summary)}</p><h3>Steps</h3><ul class="tight noprov">${steps}</ul>
  <h3>Cited clauses</h3><ul class="tight noprov">${clauses}</ul>${deductible(c.deductible)}${guards}`;
}
function piiLine(label,value,conflict,mark){
  if(!value)return `<li>${esc(label)}: -</li>`;
  if(conflict){
    const readings=conflict.map(([w,v])=>`${esc(v)} (${esc(w)})`).join(' / ');
    return `<li>${esc(label)}: ${readings} — differs between documents; ${esc(mark)}</li>`;
  }
  return `<li>${esc(label)}: ${esc(value)} — ${esc(mark)}</li>`;
}
function packPanel(p){
  const v=p.visit;
  const stay=v.inpatient?`inpatient, ${esc(v.period_from)} to ${esc(v.period_to)}`:'outpatient';
  const codes=p.codes||{};
  const cm=codes.cm||{};
  const questions=(codes.questions||[]).map(
    q=>`<li class="noprov">Needed to narrow: ${esc(q)}</li>`
  ).join('');
  const warn=codes.pitfall
    ?`<li class="warn noprov">Warning: ${esc(codes.pitfall.warning)}</li>`:'';
  const estimate=p.diagnosis.final===false
    ?'<li class="noprov">Note: the certificate marks a clinical estimate; a final diagnosis may be requested.</li>':'';
  const rows=p.items.map(
    i=>`<tr><td class="noprov">${esc(i.label_en)}<br/><span lang="ko">${esc(i.label_ko)}</span></td>`
      +`<td class="num">${pv(i.amount)}</td></tr>`
  ).join('');
  const list=(items)=>items.map(i=>`<li>${esc(i)}</li>`).join('');
  return `<h3>Claim Pack</h3><p>${badge('not adjudicated')}</p>
  <div class="panel"><h4>Cover</h4><p><strong>${esc(p.policy_line)}</strong></p>
  <h4>Patient and visit</h4><ul class="tight noprov">`
  +piiLine('Name',p.patient.name,(p.pii_conflicts||{}).name,p.pii_mark)
  +piiLine('Date of birth',p.patient.date_of_birth,(p.pii_conflicts||{}).date_of_birth,p.pii_mark)
  +piiLine('Passport',p.patient.passport,(p.pii_conflicts||{}).passport,p.pii_mark)
  +piiLine('Patient ID',p.patient.patient_id,(p.pii_conflicts||{}).patient_id,p.pii_mark)
  +`<li>Hospital: ${esc(v.hospital)}</li><li>Stay: ${stay}</li></ul>
  <h4>Diagnosis codes</h4><ul class="tight">
  <li class="noprov">Certificate: ${esc(p.diagnosis.label||'-')}</li>
  <li>KCD: ${pv(codes.kcd)}</li>
  <li>WHO ICD-10: ${pv(codes.who)}${codes.attribute?` (${esc(codes.attribute)})`:''}</li>
  <li>ICD-10-CM candidate: ${pv(cm.chosen)}</li>${questions}${warn}
  <li class="noprov">${esc(codes.disclaimer||'')}</li>${estimate}</ul>
  <h4>Itemized bill (KRW)</h4><table class="bill">
  <tr><th>Item</th><th class="num">Amount</th></tr>${rows}
  <tr><td><strong>Total</strong></td><td class="num"><strong>${pv(p.total_krw)}</strong></td></tr></table>
  <ul class="tight"><li>Receipt arithmetic verified: ${p.checks_passed?'pass':'FAIL'}</li>
  <li>${esc(p.translation_note)}</li></ul>
  <h4>Checklist before leaving</h4><ul class="tight">${list(p.checklist)}</ul>
  <h4>Filing deadlines</h4><ul class="tight"><li>${esc(p.deadline)}</li></ul></div>`;
}
function images(s){
  return (s.images||[]).map(
    p=>`<figure class="doc"><img class="doc" src="${esc(p.src)}" onerror="this.closest('figure').remove()"/>`
      +`<figcaption>${esc(p.caption)}</figcaption></figure>`
  ).join('');
}
"""


def render_page(payload: dict[str, Any]) -> str:
    # Script text is not entity-decoded: emit raw JSON, only neutralizing
    # the closing tag.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/>
<title>ClaimLens replay demo</title>
<style>{CSS}</style></head>
<body>
<h1>ClaimLens replay demo</h1>
<p><small class="dim">All documents are synthetic. Rendered from committed replay caches only.</small></p>
<nav id="scenes"></nav>
<div id="stages"></div>
<div id="prov-panel" style="display:none" role="dialog" aria-label="Number provenance"></div>
<script id="demo-data" type="application/json">{data}</script>
<script>{JS}</script>
</body>
</html>
"""
