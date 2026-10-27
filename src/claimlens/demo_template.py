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
img.doc{width:100%;max-height:330px;object-fit:contain;border:1px solid #ccc;
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
.panel h4{margin:.7rem 0 .25rem;font-size:.95rem}
.panel h4:first-child{margin-top:0}
table.bill{border-collapse:collapse;width:100%;font-size:.9rem;margin:.3rem 0}
table.bill td,table.bill th{border-bottom:1px solid #ddd;padding:.2rem .4rem;
text-align:left}
table.bill td.num,table.bill th.num{text-align:right;font-variant-numeric:tabular-nums}
code.clause{background:#efefef;padding:.05rem .3rem;border-radius:.2rem;font-size:.85rem}
ul.tight{margin:.3rem 0;padding-left:1.2rem}
ul.tight li{margin:.15rem 0}
.warn{color:#7a4d0b;font-weight:600}
small.dim{color:#666}
"""

JS = """
function show(id){
  document.querySelectorAll('section.scene').forEach(s=>s.classList.remove('active'));
  document.getElementById(id).classList.add('active');
}
const data=JSON.parse(document.getElementById('demo-data').textContent);
const nav=document.getElementById('scenes');
data.scenes.forEach((s,i)=>{
  const b=document.createElement('button');
  b.textContent=s.title;b.onclick=()=>show(s.id);
  nav.appendChild(b);
  document.getElementById('stages').insertAdjacentHTML('beforeend',stage(s,i===0));
});
function stage(s,first){
  return `<section class="scene${first?' active':''}" id="${s.id}"><h2>${esc(s.title)}</h2>
  <div class="scene-grid"><div>${images(s)}</div>
  <div>${reading(s)}${eligibility(s)}${result(s)}</div></div></section>`;
}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')}
function num(n){return Number(n).toLocaleString('en-US')}
function reading(s){
  const r=s.reading;
  const checks=r.checks.map(c=>
    `<span class="pill ${c.passed?'pass':'fail'}">${c.passed?'✓':'✗'} ${esc(c.name)}</span>`
  ).join('');
  return `<h3>Reading</h3><p>${esc(r.docs.join(' + '))} · ${esc(r.currency)} ·
  total ${esc(r.total)} · codes ${esc(r.diags.join(', ')||'-')}</p>
  <p class="strip">${checks||'<span class="pill na">no bill checks</span>'}</p>`;
}
function eligibility(s){
  if(!s.eligibility)return `<h3>Eligibility</h3><p>Korean traveller abroad — engine path.</p>`;
  const e=s.eligibility;
  return `<h3>Eligibility</h3><p><strong>${esc(e.outcome)}</strong> (${esc(e.rule)})</p>
  <p><small class="dim">${esc(e.basis)}</small></p>`;
}
function badge(decision){
  const cls=decision==='PAID'?'paid':decision==='PARTIAL'?'partial':'none';
  return `<span class="badge badge-${cls}">${esc(decision)}</span>`;
}
function deductible(d){
  if(!d)return '';
  const head=`max(${d.terms.map(num).join(', ')}) = ${num(d.ours)}`;
  const text=d.match?`${head} — matches the engine`
    :`ClaimLens ${head} vs engine ${num(d.engine)} — FLAGGED: amounts differ; the engine amount stands.`;
  return `<h3>Deductible check (computed by ClaimLens from the reading)</h3><p>${esc(text)}</p>`;
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
  const guards=(c.guardrails||[]).length?`<p>Guardrails: ${esc(c.guardrails.join(', '))}</p>`:'';
  return `<h3>Engine card</h3><p>${badge(c.decision)}</p><p class="amount">${esc(c.amount)}</p>
  <p class="pinned">pre-existing open-source engine, pinned</p>
  <p>${esc(c.summary)}</p><h3>Steps</h3><ul class="tight">${steps}</ul>
  <h3>Cited clauses</h3><ul class="tight">${clauses}</ul>${deductible(c.deductible)}${guards}`;
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
  const questions=(cm.questions||[]).map(q=>`<li>Needed to narrow: ${esc(q)}</li>`).join('');
  const warn=p.codes&&p.codes.pitfall?`<li class="warn">Warning: ${esc(p.codes.pitfall.warning)}</li>`:'';
  const estimate=p.diagnosis.final===false
    ?'<li>Note: the certificate marks a clinical estimate; a final diagnosis may be requested.</li>':'';
  const rows=p.items.map(
    i=>`<tr><td>${esc(i.label_en)}<br/><span lang="ko">${esc(i.label_ko)}</span></td>`
      +`<td class="num">${num(i.amount)}</td></tr>`
  ).join('');
  const total=p.total_krw===null||p.total_krw===undefined?'-':num(p.total_krw);
  const list=(items)=>items.map(i=>`<li>${esc(i)}</li>`).join('');
  return `<h3>Claim Pack</h3><p>${badge('not adjudicated')}</p>
  <div class="panel"><h4>Cover</h4><p><strong>${esc(p.policy_line)}</strong></p>
  <h4>Patient and visit</h4><ul class="tight">`
  +piiLine('Name',p.patient.name,(p.pii_conflicts||{}).name,p.pii_mark)
  +piiLine('Date of birth',p.patient.date_of_birth,(p.pii_conflicts||{}).date_of_birth,p.pii_mark)
  +piiLine('Passport',p.patient.passport,(p.pii_conflicts||{}).passport,p.pii_mark)
  +piiLine('Patient ID',p.patient.patient_id,(p.pii_conflicts||{}).patient_id,p.pii_mark)
  +`<li>Hospital: ${esc(v.hospital)}</li><li>Stay: ${stay}</li></ul>
  <h4>Diagnosis codes</h4><ul class="tight">
  <li>Certificate: ${esc(p.diagnosis.label||'-')}</li>
  <li>KCD: ${esc(codes.kcd||'-')}</li>
  <li>WHO ICD-10: ${esc(codes.who||'-')}${codes.attribute?` (${esc(codes.attribute)})`:''}</li>
  <li>ICD-10-CM candidate: ${esc(cm.chosen||'-')}</li>${questions}${warn}
  <li>${esc(codes.disclaimer||'')}</li>${estimate}</ul>
  <h4>Itemized bill (KRW)</h4><table class="bill">
  <tr><th>Item</th><th class="num">Amount</th></tr>${rows}
  <tr><td><strong>Total</strong></td><td class="num"><strong>${total}</strong></td></tr></table>
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
<script id="demo-data" type="application/json">{data}</script>
<script>{JS}</script>
</body>
</html>
"""
