(()=>{ // Recording FX: camera zoom + spotlight + micro-motion. Needs overlay.js.
window.__zoomFit=(x,y,bw,bh,s,vw,vh,m)=>{
m=m||24;
if(!(bw>0&&bh>0))return s;
const roomX=Math.min(x,vw-x)-m,roomY=Math.min(y,vh-y)-m;
const fit=Math.min(roomX/(bw/2),roomY/(bh/2));
return Math.min(s,Math.max(1,fit));};
const init=()=>{
if(document.getElementById('vzoom')||!document.body)return;
const wrap=document.createElement('div');wrap.id='vzoom';
[...document.body.children].forEach(el=>{
if(!['vcap','vdot','vdim','prov-panel'].includes(el.id))wrap.appendChild(el);});
document.body.insertBefore(wrap,document.body.firstChild);
const dim=document.createElement('div');dim.id='vdim';
dim.style.cssText='position:fixed;inset:0;z-index:2147483646;'
+'pointer-events:none;display:none;background:rgba(0,0,0,.55)';
document.body.appendChild(dim);
window.__zoom=(x,y,s,ms,bw,bh)=>{s=window.__zoomFit(x,y,bw||0,bh||0,s,innerWidth,innerHeight,24);
wrap.style.transition=`transform ${ms}ms ease`;
wrap.style.transformOrigin=`${x+scrollX}px ${y+scrollY}px`;
wrap.style.transform=`scale(${s})`;
document.body.style.overflow='hidden';
dim.style.background=`radial-gradient(circle at ${x}px ${y}px,`
+'transparent 110px, rgba(0,0,0,.55) 230px)';
dim.style.display='block';};
window.__unzoom=()=>{wrap.style.transition='transform 500ms ease';
wrap.style.transform='';document.body.style.overflow='';
dim.style.display='none';};
let css='#flow-steps .fstep.active{animation:vpop .35s ease}';
for(let i=1;i<=12;i++)
css+=`section.scene.active .strip .pill:nth-of-type(${i})`
+`{animation:vpop .35s ease both;animation-delay:${(i*0.06).toFixed(2)}s}`;
for(let i=1;i<=10;i++)
css+=`#prov-panel li:nth-child(${i}) .plink`
+`{animation:vplink .5s ease backwards;animation-delay:${(i*0.08).toFixed(2)}s}`;
const st=document.createElement('style');
st.textContent=`@keyframes vpop{0%{transform:scale(.6);opacity:0}`
+`100%{transform:scale(1);opacity:1}}`
+`@keyframes vplink{0%{background:transparent}`
+`30%{background:var(--tab-active-bg,#E7F0FE)}100%{background:transparent}}`
+`@keyframes vhl{0%{box-shadow:0 0 0 0 rgba(0,100,224,.55)}`
+`100%{box-shadow:0 0 0 10px rgba(0,100,224,0)}}`
+`.num.hl{animation:vhl .8s ease 2}`+css;
document.head.appendChild(st);};
if(document.getElementById('vcap'))init();
else document.addEventListener('DOMContentLoaded',init,{once:true});})();
