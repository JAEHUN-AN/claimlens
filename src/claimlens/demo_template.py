"""Self-contained demo page template: no external requests, works from file://."""

import json
from typing import Any

# Own mark: a magnifying lens over a document corner. Shared inner shapes
# keep the topbar SVG and the favicon data URL identical by construction.
MARK_SVG = (
    '<path d="M4 2.5h5.5L13 6v6.5"/><path d="M9.5 2.5V6H13"/>'
    '<circle cx="11.5" cy="12.5" r="4"/><path d="M14.5 15.5l3 3"/>'
)
FAVICON = (
    "data:image/svg+xml,%3Csvg%20xmlns='http://www.w3.org/2000/svg'%20"
    "viewBox='0%200%2020%2020'%20fill='none'%20stroke='%230064E0'"
    "%20stroke-width='1.8'%3E"
    + MARK_SVG.replace('"', "'").replace("<", "%3C").replace(">", "%3E").replace(" ", "%20")
    + "%3C/svg%3E"
)

CSS = """
:root{
--paper:#F0F2F5;--paper-2:#FFFFFF;--ink:#050505;--ink-dim:#65676B;--line:#E4E6EB;
--accent:#0064E0;--accent-hover:#0053BC;--pass:#1F7A33;--fail:#D61F2C;
--tint-pass:#DDF0E3;--tint-warn:#FFF1C4;--tint-fail:#FADCE0;--badge-none-bg:#E4E6EB;
--stamp-paid:#0F6B2E;--stamp-partial:#7A5200;--stamp-none:#4E4F50;--mark:#D6E9FF;
--btn:#E4E6EB;--btn-hover:#D8DADF;--tab-active-bg:#E7F0FD;
--mono:ui-monospace,"SF Mono","Cascadia Mono",Consolas,monospace;
--sans:system-ui,-apple-system,"Segoe UI",sans-serif;
--shadow:0 1px 2px rgba(0,0,0,.12);--shadow-lg:0 8px 24px rgba(0,0,0,.18)}
@media (prefers-color-scheme:dark){
:root{--paper:#18191A;--paper-2:#242526;--ink:#E4E6EB;--ink-dim:#B0B3B8;
--line:#3A3B3C;--accent:#2D88FF;--accent-hover:#5AA1FF;--pass:#5FD08A;--fail:#FF8A94;
--tint-pass:#1E3A28;--tint-warn:#3D2F10;--tint-fail:#452227;--badge-none-bg:#3A3B3C;
--stamp-paid:#7BD99A;--stamp-partial:#F0B429;--stamp-none:#D5D8DC;--mark:#1D3F66;
--btn:#3A3B3C;--btn-hover:#4E4F50;--tab-active-bg:#1E3A5F;
--shadow:0 1px 2px rgba(0,0,0,.4);--shadow-lg:0 8px 24px rgba(0,0,0,.5)}}
body{font-family:var(--sans);margin:0;color:var(--ink);background:var(--paper)}
.wrap{max-width:1160px;margin:0 auto;padding:0 1rem}
.topbar{position:sticky;top:0;z-index:5;background:var(--paper-2);border-bottom:1px solid var(--line)}
.topbar-inner{display:flex;align-items:center;gap:.6rem;flex-wrap:wrap;padding:.6rem 1rem}
.brandrow{display:flex;align-items:center;gap:.5rem}
.mark{width:18px;height:18px;color:var(--accent);flex:none}
h1{font-size:1.2rem;margin:0;letter-spacing:-.01em}
.replay-tag{font-size:.75rem;font-weight:700;color:var(--accent);background:var(--tab-active-bg);
padding:.15rem .55rem;border-radius:999px;white-space:nowrap}
.replay-tag.live{color:var(--pass);background:var(--tint-pass)}
.quotes{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin:.4rem 0}
.quotes>div{background:var(--paper);border-radius:8px;padding:.4rem .6rem}
.quotes h5{margin:.1rem 0 .3rem;font-size:.8rem;color:var(--ink-dim)}
.sev{font-size:.75rem;font-weight:700;border-radius:999px;padding:.1rem .5rem;white-space:nowrap}
.sev-blocker{color:var(--fail);background:var(--tint-fail)}
.sev-check{color:var(--stamp-partial);background:var(--tint-warn)}
.ask{border-left:3px solid var(--stamp-partial);padding:.2rem 0 .2rem .8rem}
@media (max-width:640px){.quotes{grid-template-columns:1fr}}
.langswitch{display:flex;gap:.25rem;margin-left:.4rem}
.langswitch button{padding:.25rem .6rem;font-size:.8rem;border-radius:999px;cursor:pointer}
.langswitch button.active{background:var(--tab-active-bg);color:var(--accent)}
.topnote{margin:0 0 0 auto;font-size:.8rem}
h2{font-size:1.05rem;margin:.2rem 0 .6rem}
h3{font-size:.92rem;margin:.9rem 0 .3rem}
p{margin:.3rem 0}
button{font-family:var(--sans);font-weight:600;background:var(--btn);color:var(--ink);
border:none;border-radius:6px;transition:background .15s ease}
button:hover{background:var(--btn-hover)}
button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
nav#scenes{display:flex;gap:.25rem;flex-wrap:wrap;align-items:center;margin:.8rem 0 .2rem}
nav#scenes>span{color:var(--ink-dim);font-size:.85rem;margin:0 .1rem}
nav#scenes button{background:transparent;color:var(--ink-dim);font-weight:600;
padding:.5rem .85rem;border-radius:8px;cursor:pointer;font-size:.9rem}
nav#scenes button:hover{background:var(--btn);color:var(--ink)}
nav#scenes button.active{background:var(--tab-active-bg);color:var(--accent)}
section.scene{display:none;background:var(--paper-2);border:1px solid var(--line);
border-radius:8px;box-shadow:var(--shadow);margin-top:.6rem;padding:1rem 1.2rem}
section.scene.active{display:block}
.scene-grid{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);
gap:1.2rem;align-items:start}
figure.doc{margin:0 0 .8rem}
img.doc{width:100%;max-height:296px;object-fit:contain;background:#fff;
border:1px solid var(--line);border-radius:8px}
figcaption{font-size:.8rem;color:var(--ink-dim)}
.badge{display:inline-block;font-weight:700;padding:.2rem .7rem;font-size:.8rem;
letter-spacing:.02em;border:none;border-radius:999px}
.badge-paid{background:var(--tint-pass);color:var(--stamp-paid)}
.badge-partial{background:var(--tint-warn);color:var(--stamp-partial)}
.badge-none{background:var(--badge-none-bg);color:var(--stamp-none)}
.amount{font-family:var(--mono);font-size:1.75rem;font-weight:700;margin:.1rem 0;
font-variant-numeric:tabular-nums}
.pinned{font-size:.8rem;color:var(--ink-dim)}
.pill{display:inline-block;padding:.1rem .5rem;border-radius:1rem;font-size:.85rem;
margin:0 .25rem .25rem 0;border:1px solid var(--line)}
.pass{color:var(--pass)}.fail{color:var(--fail)}.na{color:var(--ink-dim)}
.strip{margin:.3rem 0}
.panel{background:var(--paper);border-radius:8px;padding:.8rem 1rem}
.panel h4:first-child{margin-top:0}
table.bill{border-collapse:collapse;width:100%;font-size:.9rem;margin:.3rem 0}
table.bill td,table.bill th{border-bottom:1px solid var(--line);padding:.2rem .4rem;
text-align:left}
table.bill td.num,table.bill th.num{text-align:right;font-family:var(--mono);
font-variant-numeric:tabular-nums}
code.clause{font-family:var(--mono);background:var(--paper);border:1px solid var(--line);
padding:.05rem .3rem;border-radius:4px;font-size:.8rem}
ol.timeline{list-style:none;padding:0;margin:.4rem 0}
ol.timeline li{border-left:3px solid var(--line);padding:.2rem 0 .6rem .8rem}
ol.timeline li.tl-q{border-color:var(--stamp-partial);background:var(--paper)}
ol.timeline li.tl-final{border-color:var(--pass)}
ol.timeline p{margin:.2rem 0;font-size:.95rem;line-height:1.45}
.tool-name{font-size:.95rem}
.headline{margin:.1rem 0 .5rem;font-size:1.1rem}
.headline .badge{font-size:.8rem}
h4{font-size:.95rem;margin:.7rem 0 .25rem}
.rec-cols{display:grid;grid-template-columns:1fr 1fr;gap:.8rem}
ul.tight{margin:.3rem 0;padding-left:1.2rem}
ul.tight li{margin:.15rem 0}
.warn{color:var(--stamp-partial);font-weight:600}
.totag{display:inline-block;background:var(--tint-warn);color:var(--stamp-partial);
font-size:.75rem;font-weight:700;padding:0 .4rem;border-radius:4px}
small.dim{color:var(--ink-dim)}
.num{font-family:var(--mono);font-variant-numeric:tabular-nums;cursor:pointer;
border-bottom:1px dotted var(--ink-dim);border-radius:2px}
.num:hover{background:var(--mark)}
.num:focus-visible{outline:2px solid var(--accent);outline-offset:1px}
.num.hl{background:var(--mark)}
#prov-panel{position:fixed;right:1rem;bottom:1rem;max-width:24rem;background:var(--paper-2);
border:1px solid var(--line);border-radius:8px;padding:.7rem .9rem;font-size:.9rem;
box-shadow:var(--shadow-lg);z-index:10;color:var(--ink)}
#prov-panel p{margin:.2rem 0}
#prov-panel .kind{font-size:.75rem;font-weight:700;text-transform:uppercase;color:var(--ink-dim)}
#prov-panel .plink{background:none;border:none;padding:0;cursor:pointer;color:var(--accent);
font-size:.9rem;font-weight:400;text-align:left;text-decoration:underline}
#prov-panel .plink:hover{background:none}
#flow-view{background:var(--paper-2);border:1px solid var(--line);border-radius:8px;
box-shadow:var(--shadow);margin-top:.6rem;padding:1rem 1.2rem}
.tagline{font-size:1rem;color:var(--ink-dim);margin:.1rem 0 .5rem}
ol.strip3{list-style:none;display:flex;gap:.5rem;padding:0;margin:.2rem 0 .6rem;flex-wrap:wrap}
ol.strip3 li{background:var(--paper);border-radius:999px;padding:.25rem .8rem;
font-size:.85rem;font-weight:600;color:var(--ink-dim)}
ol.strip3 li:not(:last-child)::after{content:"→";margin-left:.7rem;color:var(--ink-dim)}
.flow-pick{display:flex;gap:.5rem;flex-wrap:wrap;margin:.4rem 0}
.fpick{display:flex;align-items:center;gap:.5rem;padding:.4rem .8rem .4rem .4rem;
cursor:pointer;font-size:.85rem;border-radius:8px}
.fpick.active{background:var(--tab-active-bg);box-shadow:inset 0 0 0 2px var(--accent)}
img.thumb{width:44px;height:44px;object-fit:cover;border-radius:6px;border:1px solid var(--line)}
#flow-drop{border:2px dashed var(--line);border-radius:8px;padding:.8rem;text-align:center;
color:var(--ink-dim);margin:.4rem 0}
.flow-main{display:grid;grid-template-columns:minmax(0,7fr) minmax(0,5fr);gap:1.2rem;
align-items:start;margin-top:.4rem}
.fstep{display:flex;gap:.6rem;align-items:baseline;padding:.35rem .5rem;
border-left:3px solid var(--line);margin-bottom:.25rem;border-radius:0 6px 6px 0;
transition:background .2s ease}
.fstep.active{border-color:var(--accent);background:var(--tab-active-bg)}
.fstep.done{border-color:var(--pass)}
.fstep span{flex:1}
#flow-play{padding:.5rem 1.4rem;font-size:1rem;cursor:pointer}
#flow-play:disabled{cursor:default;opacity:.55}
#flow-play:not(:disabled){background:var(--accent);color:#fff}
#flow-play:not(:disabled):hover{background:var(--accent-hover)}
.flow-result{margin-top:.6rem}
@media (max-width:640px){
.topbar-inner{padding:.5rem .6rem}
.wrap{padding:0 .6rem}
.scene-grid,.flow-main{grid-template-columns:1fr}
.rec-cols{grid-template-columns:1fr}
.topnote{margin-left:0}
#prov-panel{left:.6rem;right:.6rem;max-width:none}
table.bill{font-size:.85rem}}
@media print{
:root{--paper:#fff;--paper-2:#fff;--ink:#000;--ink-dim:#333;--line:#999}
body{background:#fff}
.topbar{position:static}
#langswitch,#scenes,#flow-play,#flow-drop,#prov-panel{display:none}
.panel,table.bill,ol.timeline li{break-inside:avoid}
img.doc{max-height:180px}}
"""

JS = """
const LANGS=["en","ko"];
let LANG="en";
let currentView="flow";
let flowTimer=null;
let LIVE=false;
const MMKIND={"patient_name":"patient name","birth_date":"birth date","visit_date":"visit date","visit_type":"visit type","hospital":"hospital","billed_not_described":"billed, not described","described_not_billed":"described, not billed","diagnosis_vs_department":"diagnosis vs department","prose_date":"prose date"};
// UI chrome strings only (labels, step names, buttons). Document contents
// stay in their own language. Every row is [en, ko].
const UI={
topnote:["All documents are synthetic. Rendered from committed replay caches only.","모든 문서는 합성본입니다. 커밋된 리플레이 캐시로만 렌더링됩니다."],
replay_tag:["replay demo","리플레이 데모"],
nav_flow:["Guided flow","안내 흐름"],
nav_examples:["Examples: ","예시: "],
nav_aria:["Demo scenes","데모 장면"],
prov_aria:["Number provenance","숫자 출처"],
tagline:["AI reads, reasons and asks; code counts.","AI는 읽고 추론하고 묻고, 코드는 계산한다."],
strip_1:["Muse Spark reads & reasons","Muse Spark가 읽고 추론"],
strip_2:["code counts","코드가 계산"],
strip_3:["people decide","사람이 결정"],
flow_h2:["Process a claim","청구 처리"],
flow_note:["Replay mode: pick a sample. Every step below replays a recording.","리플레이 모드: 예시를 고르세요. 아래 단계는 모두 녹화본을 재생합니다."],
drop:["Want to try your own document? Live upload needs an API key — or pick an example above.","직접 문서를 올려보고 싶으세요? 실시간 업로드에는 API 키가 필요합니다 — 위 예시로 체험해 보세요."],
tip_numbers:["Tip: every number is clickable — select one to see its source.","팁: 모든 숫자를 누르면 출처를 볼 수 있습니다."],
play:["Play","재생"],
see_full:["See the full example","전체 예시 보기"],
live_msg:["live mode needs an API key — run `claimlens` locally","라이브 모드에는 API 키가 필요합니다 — `claimlens`를 로컬에서 실행하세요"],
step_reading:["Reading","읽기"],
step_checks:["Checks","검증"],
step_eligibility:["Eligibility","자격"],
step_decision:["Decision","판정"],
step_pack:["Claim Pack","Claim Pack"],
step_question:["Question","질문"],
step_codes:["Codes","코드"],
step_reread:["Re-read","재판독"],
step_transcription:["Transcription","받아쓰기"],
step_facts:["Fact extraction","사실 추출"],
meta_det:["deterministic","결정적"],
meta_tokens:["tokens (recorded)","토큰 (녹화본)"],
meta_user:["user answers","사용자 답변"],
prov_formula:["Formula:","계산식:"],
prov_related:["Related:","관련:"],
prov_value:["Value:","값:"],
prov_source:["Source:","출처:"],
prov_esc:["Esc closes · related numbers highlighted","Esc로 닫기 · 관련 숫자 강조 표시"],
h_reading:["Reading","읽기"],
h_eligibility:["Eligibility","자격"],
h_engine:["Engine card","엔진 카드"],
h_steps:["Steps","단계"],
h_clauses:["Cited clauses","인용 조항"],
h_deductible:["Deductible check (computed by ClaimLens from the reading)","본인부담금 확인 (ClaimLens가 판독본에서 계산)"],
h_pack:["Claim Pack","Claim Pack"],
h_cover:["Cover","표지"],
h_patient:["Patient and visit","환자와 방문"],
h_diag:["Diagnosis codes","진단 코드"],
h_bill:["Itemized bill (KRW)","세부 청구서 (KRW)"],
h_checklist:["Checklist before leaving","떠나기 전 확인 목록"],
h_deadlines:["Filing deadlines","제출 기한"],
h_agent:["Agent timeline","에이전트 타임라인"],
h_voice:["Voice intake","음성 접수"],
h_eval:["Reading accuracy (offline eval)","판독 정확도 (오프라인 평가)"],
eval_foot:["Full table with tokens and cost: docs/eval.md in the repo.","토큰·비용 포함 전체 표: 저장소의 docs/eval.md."],
th_sample:["Sample","샘플"],
th_lines:["Lines","항목"],
th_diags:["Diags","진단"],
h_recovery:["Verify & re-read","검증 후 재판독"],
rec_before:["Base reading","1차 판독"],
rec_after:["After one narrow re-read","좁은 범위 재판독 후"],
rec_corrected:["Corrected:","수정됨:"],
rec_story:["The base reading failed receipt checks, so ClaimLens re-read only the failed cells. Amounts below are re-read, never computed.","1차 판독이 영수증 검사를 통과하지 못해 실패한 셀만 다시 읽었습니다. 아래 금액은 재판독본이며 계산된 값이 아닙니다."],
total_w:["total","합계"],
codes_w:["codes","코드"],
no_checks:["no bill checks","청구서 검사 없음"],
elig_fallback:["Korean traveller abroad — engine path.","해외의 한국 여행자 — 엔진 경로."],
step_w:["Step","단계"],
q_w:["Q:","질문:"],
why_w:["Why:","이유:"],
a_w:["A:","답변:"],
turns_w:["turns","턴"],
model_turns:["model turns","모델 턴"],
tokens_w:["tokens","토큰"],
replayed_w:["replayed trace","재생된 추적"],
clip_w:["Clip","클립"],
th_fact:["Fact","사실"],
th_value:["Value","값"],
th_quote:["Quoted words","인용 어구"],
to_confirm_list:["To confirm with the person:","본인과 확인할 사항:"],
toconfirm:["to confirm","확인 필요"],
p_name:["Name","이름"],
p_dob:["Date of birth","생년월일"],
p_pass:["Passport","여권"],
p_pid:["Patient ID","환자 번호"],
p_hosp:["Hospital","병원"],
p_stay:["Stay","입원"],
stay_out:["outpatient","외래"],
stay_in:["inpatient","입원"],
stay_to:["to","~"],
differs:["differs between documents; ","문서 간 불일치; "],
cert_w:["Certificate:","진단서:"],
kcd_w:["KCD:","KCD:"],
who_w:["WHO ICD-10:","WHO ICD-10:"],
cm_w:["ICD-10-CM candidate:","ICD-10-CM 후보:"],
narrow:["Needed to narrow: ","좁히는 데 필요: "],
warn_w:["Warning: ","경고: "],
est_note:["Note: the certificate marks a clinical estimate; a final diagnosis may be requested.","참고: 진단서에 임상 추정으로 표시되어 있습니다. 최종 진단을 요청할 수 있습니다."],
th_item:["Item","항목"],
th_amount:["Amount","금액"],
total_cap:["Total","합계"],
receipt_ok:["Receipt arithmetic verified: ","영수증 계산 검증: "],
pass_w:["pass","통과"],
fail_w:["FAIL","실패"],
match_eng:["matches the engine","엔진과 일치"],
vs_mid:["vs engine","대 엔진"],
flagged:["FLAGGED: amounts differ; the engine amount stands.","경고: 금액이 다릅니다. 엔진 금액이 우선합니다."],
copay_w:["copay","본인부담금"],
pinned_w:["pre-existing open-source engine, pinned","기존 오픈소스 엔진, 고정됨"],
guards_w:["Guardrails: ","가드레일: "],
cap_receipt_photo:["Receipt (photo)","영수증 (사진)"],
cap_cert_photo:["Certificate (photo)","진단서 (사진)"],
cap_receipt_masked:["Receipt (masked copy)","영수증 (마스킹본)"],
cap_cert_masked:["Certificate (masked copy)","진단서 (마스킹본)"],
live_tag:["LIVE","LIVE"],
live_drop:["Drop receipt + certificate photos here — runs live on your machine.","영수증과 진단서 사진을 여기에 놓으세요 — 이 컴퓨터에서 실시간으로 실행됩니다."],
live_running:["Running live…","실시간 실행 중…"],
live_failed:["Live run failed: ","실시간 실행 실패: "],
live_tokens:["tokens (live)","토큰 (실시간)"],
step_consistency:["Consistency","일관성"],
mm_head:["Resolve the blocking questions first.","차단 질문부터 해결하세요."],
mm_findings:["Cross-document findings","문서 간 대조 결과"],
mm_receipt:["Receipt says","영수증"],
mm_cert:["Certificate says","진단서"],
sev_blocker:["blocker","차단"],
sev_check:["note","참고"]
};
function t(k){
  const r=UI[k];if(!r)return k;
  const v=r[LANGS.indexOf(LANG)];
  return v!==undefined?v:r[0];
}
function titleOf(o){return (o.titles&&o.titles[LANG])||o.title;}
const STEPLABEL={"Reading":"step_reading","Checks":"step_checks","Eligibility":"step_eligibility",
"Decision":"step_decision","Claim Pack":"step_pack","Question":"step_question","Codes":"step_codes",
"Re-read":"step_reread","Consistency":"step_consistency","Fact extraction":"step_facts"};
function stepLabel(s){
  const k=STEPLABEL[s.label];
  if(k)return t(k);
  const m=/^Transcription \\((\\w+)\\)$/.exec(s.label||"");
  if(m)return t("step_transcription")+" ("+m[1]+")";
  return s.label;
}
function stepMeta(m){
  if(m==="deterministic")return t("meta_det");
  return String(m||"").replace(/([\\d,]+) tokens \\(recorded\\)/,
    (mm,n)=>n+" "+t("meta_tokens")).replace(/· user answers$/,"· "+t("meta_user"))
    .replace(/([\\d,]+) tokens \\(live\\)/,(mm,n)=>n+" "+t("live_tokens"));
}
const CAPTION={"Receipt (photo)":"cap_receipt_photo","Certificate (photo)":"cap_cert_photo",
"Receipt (masked copy)":"cap_receipt_masked","Certificate (masked copy)":"cap_cert_masked"};
function caption(c){const k=CAPTION[c];return k?t(k):c;}
function show(id){
  currentView=id;
  document.querySelectorAll('section.scene').forEach(s=>s.classList.remove('active'));
  document.querySelectorAll('#scenes button').forEach(b=>{
    if(b.classList&&b.classList.toggle)b.classList.toggle('active',b._view===id);
  });
  const f=document.getElementById('flow-view');
  if(id==='flow'){if(f&&f.style)f.style.display='block';return;}
  if(f&&f.style)f.style.display='none';
  document.getElementById(id).classList.add('active');
}
function setLang(l){
  if(LANGS.indexOf(l)<0)return;
  LANG=l;
  render();
}
const data=JSON.parse(document.getElementById('demo-data').textContent);
const PROV={};
data.scenes.forEach(s=>Object.assign(PROV,s.provenance||{}));
function render(){
  if(flowTimer){clearTimeout(flowTimer);flowTimer=null;}
  hideProv();
  const root=document.documentElement;
  if(root)root.lang=LANG;
  const tn=document.getElementById('topnote');
  if(tn)tn.textContent=t('topnote');
  const rt=document.getElementById('replaytag');
  if(rt){if(LIVE){rt.textContent=t('live_tag');if(rt.classList)rt.classList.add('live');}else rt.textContent=t('replay_tag');}
  const pp=document.getElementById('prov-panel');
  if(pp&&pp.setAttribute)pp.setAttribute('aria-label',t('prov_aria'));
  document.querySelectorAll('#langswitch button').forEach(b=>{
    if(b.classList&&b.classList.toggle&&b.getAttribute)
      b.classList.toggle('active',b.getAttribute('data-lang')===LANG);
  });
  const nav=document.getElementById('scenes');
  nav.innerHTML='';
  if(nav.setAttribute)nav.setAttribute('aria-label',t('nav_aria'));
  const fb=document.createElement('button');
  fb.textContent=t('nav_flow');fb.onclick=()=>show('flow');fb._view='flow';
  nav.appendChild(fb);
  const exLabel=document.createElement('span');
  exLabel.textContent=t('nav_examples');
  nav.appendChild(exLabel);
  const st=document.getElementById('stages');
  st.innerHTML='';
  data.scenes.forEach((s)=>{
    const b=document.createElement('button');
    b.textContent=titleOf(s);b.onclick=()=>show(s.id);b._view=s.id;
    nav.appendChild(b);
    st.insertAdjacentHTML('beforeend',stage(s,false));
  });
  st.insertAdjacentHTML('afterbegin',flowView(data.flow));
  show(currentView);
  pickFlow('A_niseko_wrist');
}
render();
liveProbe();
function reducedMotion(){
  return typeof window!=='undefined'&&window.matchMedia
    &&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
function pickFlow(id){
  const ex=(data.flow.examples||[]).find(e=>e.id===id);
  if(!ex)return;
  if(flowTimer){clearTimeout(flowTimer);flowTimer=null;}
  document.getElementById('flow-steps').innerHTML=ex.steps.map((s,i)=>
    `<div class="fstep" id="fstep-${i}"><strong>${esc(stepLabel(s))}</strong>`
    +`<span>${esc(s.detail)}</span><small class="dim">${esc(stepMeta(s.meta))}</small></div>`
  ).join('');
  document.getElementById('flow-result').innerHTML='';
  document.getElementById('flow-msg').textContent='';
  const play=document.getElementById('flow-play');
  play.disabled=false;
  play.onclick=()=>playFlow(id);
  document.querySelectorAll('.fpick').forEach(b=>{
    if(b.classList&&b.classList.toggle&&b.getAttribute)
      b.classList.toggle('active',b.getAttribute('data-ex')===id);
  });
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
    return `<button class="fpick" data-ex="${e.id}" onclick="pickFlow('${e.id}')">${thumb}${esc(titleOf(e))}</button>`;
  }).join('');
  return `<div id="flow-view">`
    +`<p class="tagline">${esc(t('tagline'))}</p>`
    +`<ol class="strip3"><li>${esc(t('strip_1'))}</li><li>${esc(t('strip_2'))}</li><li>${esc(t('strip_3'))}</li></ol>`
    +`<h2>${esc(t('flow_h2'))}</h2>`
    +`<p><small class="dim">${esc(t('flow_note'))}</small></p>`
    +`<p id="flow-tip"><small class="dim">${esc(t('tip_numbers'))}</small></p>`
    +`<div class="flow-pick">${picks}</div>`
    +`<div id="flow-drop">${esc(LIVE?t('live_drop'):t('drop'))}</div>`
    +`<p id="flow-msg" role="status"></p>`
    +`<div class="flow-main"><div id="flow-steps"></div>`
    +`<div><button id="flow-play" disabled>${esc(t('play'))}</button><div id="flow-result"></div></div></div>`
    +evalBlock(f.eval)+`</div>`;
}
function evalBlock(e){
  if(!e)return '';
  const rows=(e.rows||[]).map(r=>`<tr><td>${esc(r.sample)}</td><td>${esc(r.total)}</td>`
    +`<td>${esc(r.lines)}</td><td>${esc(r.diags)}</td>`
    +`<td>${esc(r.checks)}</td><td>${esc(r.pii)}</td></tr>`).join('');
  return `<h3>${esc(t('h_eval'))}</h3><table class="bill">`
    +`<tr><th>${esc(t('th_sample'))}</th><th>${esc(t('total_cap'))}</th>`
    +`<th>${esc(t('th_lines'))}</th><th>${esc(t('th_diags'))}</th>`
    +`<th>${esc(t('step_checks'))}</th><th>PII</th></tr>${rows}</table>`
    +`<p><small class="dim">${esc(e.open_line||'')}</small></p>`
    +`<p><small class="dim">${esc(t('eval_foot'))}</small></p>`;
}
function flowResult(ex){
  return `<div class="flow-result"><p>${badge(ex.result.badge)}</p>`
    +`<p class="amount">${esc(ex.result.title)}</p>`
    +`<p><button onclick="show('${ex.result.scene}')">${esc(t('see_full'))}</button></p></div>`;
}
document.addEventListener('dragover',e=>{
  if(e.target&&e.target.closest&&e.target.closest('#flow-drop'))e.preventDefault();
});
document.addEventListener('drop',e=>{
  const dz=e.target&&e.target.closest?e.target.closest('#flow-drop'):null;
  if(!dz)return;
  e.preventDefault();
  liveDrop(e);
});
function liveProbe(){
  try{
    if(typeof fetch==='undefined'||typeof location==='undefined')return;
    if(!/^https?:/.test(location.protocol||''))return;
    fetch('/api/health').then(r=>r.json()).then(j=>{
      if(!j||j.mode!=='live')return;
      LIVE=true;
      const rt=document.getElementById('replaytag');
      if(rt){rt.textContent=t('live_tag');if(rt.classList)rt.classList.add('live');}
      const dz=document.getElementById('flow-drop');
      if(dz)dz.textContent=t('live_drop');
    }).catch(()=>{});
  }catch(e){}
}
function liveDrop(e){
  if(!LIVE){document.getElementById('flow-msg').textContent=t('live_msg');return;}
  const files=[...((e.dataTransfer&&e.dataTransfer.files)||[])].slice(0,2);
  if(!files.length)return;
  document.getElementById('flow-msg').textContent=t('live_running');
  Promise.all(files.map(f=>new Promise((res,rej)=>{
    const r=new FileReader();
    r.onload=()=>res({name:f.name,data:String(r.result).split(',')[1]});
    r.onerror=rej;r.readAsDataURL(f);
  }))).then(images=>fetch('/api/run',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({images})})
    .then(r=>r.json().then(j=>({ok:r.ok,j})))
  ).then(({ok,j})=>{
    const msg=document.getElementById('flow-msg');
    if(!ok){msg.textContent=t('live_failed')+(j.error||'');return;}
    msg.textContent='';
    document.getElementById('flow-steps').innerHTML=j.steps.map((s,i)=>
      `<div class="fstep done" id="fstep-${i}"><strong>${esc(stepLabel(s))}</strong>`
      +`<span>${esc(s.detail)}</span><small class="dim">${esc(String(s.seconds))}s · ${esc(liveMeta(s))}</small></div>`
    ).join('');
    document.getElementById('flow-result').innerHTML=`<div class="flow-result"><p>${badge(j.result.badge)}</p>`
      +`<p class="amount">${esc(j.result.title)}</p></div>`;
  }).catch(err=>{document.getElementById('flow-msg').textContent=t('live_failed')+err;});
}
function liveMeta(s){
  if(s.tokens)return String(s.tokens).replace(/(\\d)(?=(\\d{3})+$)/g,'$1,')+" "+t('live_tokens');
  return stepMeta(s.meta);
}
document.addEventListener('click',e=>{
  const go=e.target.closest?e.target.closest('.plink'):null;
  if(go){
    const t=document.querySelector('.num[data-prov="'+go.getAttribute('data-goto')+'"]');
    if(t){t.scrollIntoView({block:'center'});t.classList.add('hl');}
    return;
  }
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
  const formula=r.formula?`<p>${esc(t('prov_formula'))} ${esc(r.formula)}</p>`:'';
  const rel=(r.operands||[]).map(o=>{
    const q=PROV[o];
    if(!q)return '';
    const how=q.formula?` = ${esc(q.formula)}`:'';
    return `<li><button class="plink" data-goto="${esc(o)}">${esc(q.label)}: `
      +`${esc(q.value)}${how}</button></li>`;
  }).join('');
  const relBlock=rel?`<p>${esc(t('prov_related'))}</p><ul class="tight">${rel}</ul>`:'';
  p.innerHTML=`<p class="kind">${esc(r.kind)}</p><p><strong>${esc(r.label)}</strong></p>`
    +`<p>${esc(t('prov_value'))} ${esc(r.value)}</p><p>${esc(t('prov_source'))} ${esc(r.source)}</p>${formula}${relBlock}`
    +`<p><small class="dim">${esc(t('prov_esc'))}</small></p>`;
  p.style.display='block';
}
function hideProv(){
  const p=document.getElementById('prov-panel');
  if(p&&p.style)p.style.display='none';
  document.querySelectorAll('.num.hl').forEach(n=>n.classList.remove('hl'));
}
// MMKIND lookup is declared near the top: the first render needs it.
function mismatchSection(s,first){
  return `<section class="scene${first?' active':''}" id="${s.id}"><h2>${esc(titleOf(s))}</h2>`
    +`${headline(s)}<div class="scene-grid"><div>${images(s)}</div><div>${mismatchScene(s)}</div></div></section>`;
}
function mismatchScene(s){
  const items=s.mismatch.findings.map(f=>{
    const sev=f.severity==='blocker'?'sev-blocker':'sev-check';
    const sevText=f.severity==='blocker'?t('sev_blocker'):t('sev_check');
    const ask=f.question?`<p class="ask noprov"><strong>${esc(t('q_w'))} ${esc(f.question)}</strong><br/>`
      +`<small class="dim">${esc(t('why_w'))} ${esc(f.why_needed||'')}</small></p>`:'';
    return `<li><p><span class="sev ${sev}">${esc(sevText)}</span> `
      +`<strong>${esc(MMKIND[f.kind]||f.kind)}</strong></p>`
      +`<p class="noprov">${esc(f.reason)}</p>`
      +`<div class="quotes"><div><h5>${esc(t('mm_receipt'))}</h5>`
      +`<p class="noprov">“${esc(f.quote_receipt)}”</p></div>`
      +`<div><h5>${esc(t('mm_cert'))}</h5><p class="noprov">“${esc(f.quote_cert)}”</p></div></div>`
      +ask+`</li>`;
  }).join('');
  return `<h3>${esc(t('mm_findings'))}</h3><ul class="tight">${items}</ul>`;
}
function stage(s,first){
  if(s.mismatch)return mismatchSection(s,first);
  if(s.clips)
    return `<section class="scene${first?' active':''}" id="${s.id}"><h2>${esc(titleOf(s))}</h2>`
      +`${headline(s)}${voiceScene(s)}</section>`;
  const right=s.timeline?timeline(s):`${reading(s)}${s.recovery?recoveryPanel(s.recovery):''}${eligibility(s)}${result(s)}`;
  return `<section class="scene${first?' active':''}" id="${s.id}"><h2>${esc(titleOf(s))}</h2>`
    +`${headline(s)}<div class="scene-grid"><div>${images(s)}</div><div>${right}</div></div></section>`;
}
function headline(s){
  if(s.mismatch)return `<p class="headline">${badge('needs review')} <strong>${esc(t('mm_head'))}</strong></p>`;
  if(s.card)
    return `<p class="headline">${badge(s.card.decision)} <strong>${pv(s.card.amount)}</strong></p>`;
  if(s.pack)
    return `<p class="headline">${badge('not adjudicated')} `
      +`<strong>Claim Pack · ${pv(s.pack.total_krw)} KRW</strong></p>`;
  if(s.timeline){
    const o=s.timeline.outcome||{};
    if(!o.decision)return '';
    return `<p class="headline">${badge(o.decision)} <strong>${pv(o.amount)}</strong> `
      +`<small class="dim">· ${pv(s.timeline.model_calls)} ${esc(t('turns_w'))}</small></p>`;
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
      const tag=pending.has(k)?` <span class="totag">${esc(t('toconfirm'))}</span>`:'';
      return `<tr><td>${esc(k)}</td><td>${esc(String(c.facts[k]))}${tag}</td>`
        +`<td><small class="dim">${esc(c.quotes[k]||'')}</small></td></tr>`;
    }).join('');
    const asks=(c.confirmations||[]).map(
      q=>`<li>${esc(q.question)} <small class="dim">(${esc(q.why)})</small></li>`
    ).join('');
    return `<h4>${esc(t('clip_w'))} (${esc(c.lang)})</h4>`
      +`<audio controls preload="none" src="${esc(c.audio)}"></audio>`
      +`<p>${esc(c.transcript)}</p>`
      +`<table class="bill"><tr><th>${esc(t('th_fact'))}</th><th>${esc(t('th_value'))}</th><th>${esc(t('th_quote'))}</th></tr>${rows}</table>`
      +`<p>${esc(t('to_confirm_list'))}</p><ul class="tight">${asks}</ul>`;
  }).join('');
  return `<h3>${esc(t('h_voice'))}</h3><div class="noprov">`
    +`<p><strong>${esc(s.next_step)}</strong> (${esc(e.rule)})</p>`
    +`<p><small class="dim">${esc(e.basis)}</small></p>${clips}</div>`;
}
function timeline(s){
  const tl=s.timeline;
  const seg=g=>g.prov?`<span class="num" tabindex="0" data-prov="${esc(g.prov)}">${esc(g.n)}</span>`
    :g.noprov?`<span class="noprov">${esc(g.t)}</span>`:esc(g.t);
  const items=tl.entries.map(e=>{
    if(e.kind==='question')
      return `<li class="tl-q"><span class="tool-name noprov"><strong>${esc(t('step_w'))} ${e.n} — ask_user</strong></span>`
        +`<p class="noprov">${esc(t('q_w'))} ${esc(e.question)}</p><p class="noprov">${esc(t('why_w'))} ${esc(e.why_needed)}</p>`
        +`<p>${esc(t('a_w'))} ${pv(e.answer)}</p></li>`;
    if(e.kind==='final'||e.kind==='stopped')
      return `<li class="tl-final"><span class="tool-name noprov"><strong>${esc(t('step_w'))} ${e.n} — ${esc(e.kind)}</strong></span>`
        +`<p class="noprov">${esc(e.text)}</p></li>`;
    return `<li><span class="tool-name noprov"><strong>${esc(t('step_w'))} ${e.n} — ${esc(e.tool)}</strong></span>`
      +`<p>${(e.segments||[]).map(seg).join('')}</p></li>`;
  }).join('');
  const o=tl.outcome||{};
  const head=o.decision?`<p>${badge(o.decision)}</p><p class="amount">${pv(o.amount)}</p>`:'';
  return `<h3>${esc(t('h_agent'))}</h3>${head}`
    +`<p class="pinned">${pv(tl.model_calls)} ${esc(t('model_turns'))} · ${pv(tl.tokens)} ${esc(t('tokens_w'))} · ${esc(t('replayed_w'))}</p>`
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
  return `<h3>${esc(t('h_reading'))}</h3><p>${esc(r.docs.join(' + '))} · ${esc(r.currency)} ·
  ${esc(t('total_w'))} ${pv(r.total)} · ${esc(t('codes_w'))} ${diags}</p>
  <p class="strip">${checks||`<span class="pill na">${esc(t('no_checks'))}</span>`}</p>`;
}
function eligibility(s){
  if(!s.eligibility)return `<h3>${esc(t('h_eligibility'))}</h3><p>${esc(t('elig_fallback'))}</p>`;
  const e=s.eligibility;
  return `<h3>${esc(t('h_eligibility'))}</h3><p><strong>${esc(e.outcome)}</strong> (${esc(e.rule)})</p>
  <p class="noprov"><small class="dim">${esc(e.basis)}</small></p>`;
}
function badge(decision){
  const cls=decision==='PAID'?'paid':decision==='PARTIAL'?'partial':'none';
  return `<span class="badge badge-${cls}">${esc(decision)}</span>`;
}
function deductible(d){
  if(!d)return '';
  const head=`max(${(d.terms||[]).map(pv).join(', ')}) = ${pv(d.ours)}`;
  const text=d.match?`${head} — ${esc(t('match_eng'))}`
    :`ClaimLens ${head} ${esc(t('vs_mid'))} ${pv(d.engine)} — ${esc(t('flagged'))}`;
  const c=d.cells||{};
  const cells=`<p>① = ${pv(c.c1)} · ② = ${pv(c.c2)} · ${esc(t('copay_w'))} = ① ÷ (① + ②) = ${pv(c.copay)}</p>`;
  return `<h3>${esc(t('h_deductible'))}</h3>${cells}<p>${text}</p>`;
}
function recoveryPanel(r){
  const cols=(o)=>`<li>lines: ${pv(o.lines)}</li><li>amounts: ${esc(o.amounts)}</li>`
    +`<li>checks: ${esc(o.checks)}</li><li>kr_cells: ${pv(o.kr_cells)}</li>`;
  const img=r.image?`<figure class="doc"><img class="doc" src="${esc(r.image.src)}" onerror="this.closest('figure').remove()"/>`
    +`<figcaption>${esc(r.image.caption)}</figcaption></figure>`:'';
  return `<h3>${esc(t('h_recovery'))}</h3><div class="panel"><div class="rec-cols">`
    +`<div><h4>${esc(t('rec_before'))}</h4><ul class="tight">${cols(r.before)}</ul></div>`
    +`<div><h4>${esc(t('rec_after'))}</h4><ul class="tight">${cols(r.after)}</ul></div>`
    +`</div><p>${esc(t('rec_corrected'))} ${esc((r.corrected||[]).join(', '))}</p>`
    +img
    +`<p><small class="dim">${esc(t('rec_story'))}</small></p></div>`;
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
    ?`<p class="noprov">${esc(t('guards_w'))}${esc(c.guardrails.join(', '))}</p>`:'';
  return `<h3>${esc(t('h_engine'))}</h3><p>${badge(c.decision)}</p><p class="amount">${pv(c.amount)}</p>
  <p class="pinned">${esc(t('pinned_w'))}</p>
  <p class="noprov">${esc(c.summary)}</p><h3>${esc(t('h_steps'))}</h3><ul class="tight noprov">${steps}</ul>
  <h3>${esc(t('h_clauses'))}</h3><ul class="tight noprov">${clauses}</ul>${deductible(c.deductible)}${guards}`;
}
function piiLine(label,value,conflict,mark){
  if(!value)return `<li>${esc(label)}: -</li>`;
  if(conflict){
    const readings=conflict.map(([w,v])=>`${esc(v)} (${esc(w)})`).join(' / ');
    return `<li>${esc(label)}: ${readings} — ${esc(t('differs'))}${esc(mark)}</li>`;
  }
  return `<li>${esc(label)}: ${esc(value)} — ${esc(mark)}</li>`;
}
function packPanel(p){
  const v=p.visit;
  const stay=v.inpatient?`${esc(t('stay_in'))}, ${esc(v.period_from)} ${esc(t('stay_to'))} ${esc(v.period_to)}`:esc(t('stay_out'));
  const codes=p.codes||{};
  const cm=codes.cm||{};
  const questions=(codes.questions||[]).map(
    q=>`<li class="noprov">${esc(t('narrow'))}${esc(q)}</li>`
  ).join('');
  const warn=codes.pitfall
    ?`<li class="warn noprov">${esc(t('warn_w'))}${esc(codes.pitfall.warning)}</li>`:'';
  const estimate=p.diagnosis.final===false
    ?`<li class="noprov">${esc(t('est_note'))}</li>`:'';
  const rows=p.items.map(
    i=>`<tr><td class="noprov">${esc(i.label_en)}<br/><span lang="ko">${esc(i.label_ko)}</span></td>`
      +`<td class="num">${pv(i.amount)}</td></tr>`
  ).join('');
  const list=(items)=>items.map(i=>`<li>${esc(i)}</li>`).join('');
  return `<h3>${esc(t('h_pack'))}</h3><p>${badge('not adjudicated')}</p>
  <div class="panel"><h4>${esc(t('h_cover'))}</h4><p><strong>${esc(p.policy_line)}</strong></p>
  <h4>${esc(t('h_patient'))}</h4><ul class="tight noprov">`
  +piiLine(t('p_name'),p.patient.name,(p.pii_conflicts||{}).name,p.pii_mark)
  +piiLine(t('p_dob'),p.patient.date_of_birth,(p.pii_conflicts||{}).date_of_birth,p.pii_mark)
  +piiLine(t('p_pass'),p.patient.passport,(p.pii_conflicts||{}).passport,p.pii_mark)
  +piiLine(t('p_pid'),p.patient.patient_id,(p.pii_conflicts||{}).patient_id,p.pii_mark)
  +`<li>${esc(t('p_hosp'))}: ${esc(v.hospital)}</li><li>${esc(t('p_stay'))}: ${stay}</li></ul>
  <h4>${esc(t('h_diag'))}</h4><ul class="tight">
  <li class="noprov">${esc(t('cert_w'))} ${esc(p.diagnosis.label||'-')}</li>
  <li>${esc(t('kcd_w'))} ${pv(codes.kcd)}</li>
  <li>${esc(t('who_w'))} ${pv(codes.who)}${codes.attribute?` (${esc(codes.attribute)})`:''}</li>
  <li>${esc(t('cm_w'))} ${pv(cm.chosen)}</li>${questions}${warn}
  <li class="noprov">${esc(codes.disclaimer||'')}</li>${estimate}</ul>
  <h4>${esc(t('h_bill'))}</h4><table class="bill">
  <tr><th>${esc(t('th_item'))}</th><th class="num">${esc(t('th_amount'))}</th></tr>${rows}
  <tr><td><strong>${esc(t('total_cap'))}</strong></td><td class="num"><strong>${pv(p.total_krw)}</strong></td></tr></table>
  <ul class="tight"><li>${esc(t('receipt_ok'))}${p.checks_passed?esc(t('pass_w')):esc(t('fail_w'))}</li>
  <li>${esc(p.translation_note)}</li></ul>
  <h4>${esc(t('h_checklist'))}</h4><ul class="tight">${list(p.checklist)}</ul>
  <h4>${esc(t('h_deadlines'))}</h4><ul class="tight"><li>${esc(p.deadline)}</li></ul></div>`;
}
function images(s){
  return (s.images||[]).map(
    p=>`<figure class="doc"><img class="doc" src="${esc(p.src)}" onerror="this.closest('figure').remove()"/>`
      +`<figcaption>${esc(caption(p.caption))}</figcaption></figure>`
  ).join('');
}
"""


def render_page(payload: dict[str, Any]) -> str:
    # Script text is not entity-decoded: emit raw JSON, only neutralizing
    # the closing tag.
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    mark = (
        '<svg class="mark" viewBox="0 0 20 20" fill="none" '
        f'stroke="currentColor" stroke-width="1.8" aria-hidden="true">{MARK_SVG}</svg>'
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/>
<title>ClaimLens</title>
<link rel="icon" href="{FAVICON}"/>
<style>{CSS}</style></head>
<body>
<header class="topbar"><div class="wrap topbar-inner"><div class="brandrow">{mark}<h1>ClaimLens</h1><span class="replay-tag" id="replaytag">replay demo</span></div><div class="langswitch" id="langswitch" role="group" aria-label="Language"><button data-lang="en" class="active" onclick="setLang('en')">EN</button><button data-lang="ko" onclick="setLang('ko')">한국어</button></div><p class="topnote"><small class="dim" id="topnote">All documents are synthetic. Rendered from committed replay caches only.</small></p></div></header>
<div class="wrap"><nav id="scenes" aria-label="Demo scenes"></nav>
<div id="stages"></div></div>
<div id="prov-panel" style="display:none" role="dialog" aria-label="Number provenance"></div>
<script id="demo-data" type="application/json">{data}</script>
<script>{JS}</script>
</body>
</html>
"""
