"""Self-contained demo page template: no external requests, works from file://."""

import html
import json
from typing import Any

CSS = """
body{font-family:system-ui,-apple-system,sans-serif;max-width:960px;margin:2rem auto;
padding:0 1rem;color:#222}
nav button{margin-right:.5rem;padding:.4rem .8rem;cursor:pointer}
section.scene{display:none;border-top:2px solid #333;margin-top:1rem;padding-top:1rem}
section.scene.active{display:block}
.pill{display:inline-block;padding:.1rem .5rem;border-radius:1rem;font-size:.85rem}
.pass{background:#dfd}.fail{background:#fdd}.na{background:#eee}
pre{background:#f6f6f6;padding:1rem;overflow:auto;white-space:pre-wrap}
img.doc{max-width:100%;border:1px solid #ccc;margin:.5rem 0}
iframe.pack{width:100%;height:480px;border:1px solid #ccc}
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
  return `<section class="scene${first?' active':''}" id="${s.id}">
  <h2>${esc(s.title)}</h2>${reading(s)}${eligibility(s)}${result(s)}${images(s)}</section>`;
}
function esc(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;')}
function reading(s){
  const r=s.reading;
  const checks=r.checks.map(c=>
    `<span class="pill ${c.passed?'pass':'fail'}">${c.passed?'✓':'✗'} ${esc(c.name)}</span>`
  ).join(' ');
  return `<h3>Reading</h3><p>${esc(r.docs.join(' + '))} · ${esc(r.currency)} ·
  total ${esc(r.total)} · codes ${esc(r.diags.join(', ')||'-')}</p><p>${checks||'<span class="pill na">no bill checks</span>'}</p>`;
}
function eligibility(s){
  if(!s.eligibility)return `<h3>Eligibility</h3><p>Korean traveller abroad — engine path.</p>`;
  const e=s.eligibility;
  return `<h3>Eligibility</h3><p><strong>${esc(e.outcome)}</strong> (${esc(e.rule)})</p>
  <p><small class="dim">${esc(e.basis)}</small></p>`;
}
function result(s){
  if(s.card){
    const c=s.card;
    return `<h3>Engine card</h3><p><small class="dim">pre-existing open-source engine, pinned</small></p>
    <p>Decision: <strong>${esc(c.decision)}</strong> · Amount: <strong>${esc(c.amount)}</strong></p>
    <p>${esc(c.summary)}</p><pre>${esc(c.markdown)}</pre>`;
  }
  return `<h3>Claim Pack</h3><iframe class="pack" srcdoc="${esc(s.pack.html)}"></iframe>`;
}
function images(s){
  return (s.images||[]).map(p=>`<img class="doc" src="${esc(p)}" onerror="this.remove()">`).join('');
}
"""


def render_page(payload: dict[str, Any]) -> str:
    data = html.escape(json.dumps(payload, ensure_ascii=False))
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
