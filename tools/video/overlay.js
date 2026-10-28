(()=>{ // ClaimLens recording overlay: caption bar + cursor dot. No demo change.
const init=()=>{
if(document.getElementById('vcap'))return;
const css=document.createElement('style');
css.textContent=`html.vrec *{cursor:none!important}
#vcap{position:fixed;left:0;right:0;bottom:0;z-index:2147483647;pointer-events:none;
background:rgba(10,10,12,.72);color:#fff;font:500 %%FONT%%px/1.45 system-ui,sans-serif;
padding:.55rem 1.2rem .7rem;opacity:0;transition:opacity .25s ease}
#vdot{position:fixed;left:0;top:0;width:18px;height:18px;margin:-9px 0 0 -9px;
border-radius:50%;background:rgba(0,100,224,.25);border:3px solid #0064e0;
z-index:2147483647;pointer-events:none}
#vdot.pulse{animation:vpulse .6s ease}
@keyframes vpulse{0%{box-shadow:0 0 0 0 rgba(0,100,224,.55)}
100%{box-shadow:0 0 0 22px rgba(0,100,224,0)}}`;
document.head.appendChild(css);
document.documentElement.classList.add('vrec');
const cap=document.createElement('div');cap.id='vcap';document.body.appendChild(cap);
const dot=document.createElement('div');dot.id='vdot';document.body.appendChild(dot);
let dx=innerWidth/2,dy=innerHeight/2,raf=null;
window.__cap=t=>{cap.style.opacity='0';
setTimeout(()=>{cap.textContent=t;cap.style.opacity='1';},260);};
window.__dot=(x,y,ms)=>new Promise(res=>{
if(raf)cancelAnimationFrame(raf);
const x0=dx,y0=dy,t0=performance.now();
const step=n=>{const k=Math.min(1,(n-t0)/ms),e=1-Math.pow(1-k,3);
dx=x0+(x-x0)*e;dy=y0+(y-y0)*e;
dot.style.transform=`translate(${dx}px,${dy}px)`;
if(k<1)raf=requestAnimationFrame(step);else res();};
raf=requestAnimationFrame(step);});
window.__pulse=()=>{dot.classList.remove('pulse');
void dot.offsetWidth;dot.classList.add('pulse');};
window.__place=(x,y)=>{dx=x;dy=y;
dot.style.transform=`translate(${dx}px,${dy}px)`;};
const lift=()=>{const p=document.getElementById('prov-panel');
if(!p||p.style.display==='none')return;
const h=cap.getBoundingClientRect().height||90;
p.style.bottom=(h+16)+'px';};
new MutationObserver(lift).observe(document.body,
{attributes:true,subtree:true,attributeFilter:['style']});};
if(document.body)init();
else document.addEventListener('DOMContentLoaded',init,{once:true});})();
