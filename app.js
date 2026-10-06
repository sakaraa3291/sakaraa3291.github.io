'use strict';
const C=globalThis.LapCore;
const APP_VERSION='3.8.0';
const $=id=>document.getElementById(id);
let bundle=null, mode='cond', pedigreeView='sire', overlays=[], busy=false;
const SER=['#FFB13B','#5BC08A','#4A9BD8','#D9945A','#C58CE0'];
const VORDER=['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉','大井','船橋','川崎','浦和'];
const GRADE_ORDER=['GI','GII','GIII','JpnI','JpnII','JpnIII','L','OP'];
const SORT=(a,list)=>{const i=list.indexOf(a);return i<0?99:i};
function node(tag,txt,cls){const n=document.createElement(tag);if(txt!==undefined)n.textContent=String(txt);if(cls)n.className=cls;return n}
function svg(tag,attrs,txt){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs||{}))n.setAttribute(k,String(v));if(txt!==undefined)n.textContent=String(txt);return n}
function empty(id,msg){$(id).replaceChildren(node('div',msg,'pedigreeStatus'))}
function state(label,detail=''){ $('dataStatus').textContent=label+(detail?' ／ '+detail:'');$('dataStatus').dataset.state=label; }
function summary(){if(!bundle)return '';const m=bundle['lapdata.json'].meta;return `更新 ${bundle.version.updated_at} ／ ラップ ${m.races.toLocaleString()}R ／ 血統 ${bundle['pedigree_stats.json'].meta.source_rows.toLocaleString()}走`}
function currentKey(){return ['fVenue','fSurf','fDist','fClass','fGoing'].map(id=>$(id).value).join('|')}
function cond(){return bundle?.['lapdata.json'].cond||{}}
function grades(){return bundle?.['lapdata.json'].grade||{}}
function classLabel(c){return c==='オープン'?'オープン（重賞含む）':c}
function fill(id,items,desired){const s=$(id),keep=desired??s.value;s.replaceChildren(...items.map(v=>{const o=node('option',v.label??v);o.value=String(v.value??v);return o}));s.value=items.some(v=>String(v.value??v)===keep)?keep:(items[0]?.value??items[0]??'')}
function refreshFilters(){
 let rs=Object.keys(cond()).map(k=>k.split('|'));
 const ids=['fVenue','fSurf','fDist','fClass','fGoing'];
 ids.forEach((id,i)=>{const values=[...new Set(rs.map(r=>r[i]))].sort(i===0?(a,b)=>SORT(a,VORDER)-SORT(b,VORDER):i===2?(a,b)=>+a-+b:i===3?(a,b)=>SORT(a,C.CLASSES)-SORT(b,C.CLASSES):undefined);fill(id,i===3?values.map(value=>({value,label:classLabel(value)})):values);rs=rs.filter(r=>r[i]===$(id).value)});
 const d=+$('fDist').value;overlays=overlays.filter(k=>cond()[k]&&+k.split('|')[2]===d);
}
function gradeRows(){
 return Object.entries(grades()).map(([name,r])=>({name,grade:r.g||'その他',dist:+r.dist,venue:r.v,surface:r.s}));
}
function gradeSort(a,b){
 const ai=GRADE_ORDER.indexOf(a),bi=GRADE_ORDER.indexOf(b);
 return (ai<0?99:ai)-(bi<0?99:bi)||a.localeCompare(b,'ja');
}
function refreshGradeFilters(){
 const rows=gradeRows(),gKeep=$('fGradeClass').value,dKeep=$('fGradeDist').value,rKeep=$('fRace').value;
 const gs=[...new Set(rows.map(x=>x.grade))].sort(gradeSort);
 fill('fGradeClass',[{value:'',label:'すべて'},...gs.map(x=>({value:x,label:x}))],gKeep);
 const byGrade=rows.filter(x=>!$('fGradeClass').value||x.grade===$('fGradeClass').value);
 const ds=[...new Set(byGrade.map(x=>x.dist))].sort((a,b)=>a-b);
 fill('fGradeDist',[{value:'',label:'すべて'},...ds.map(x=>({value:x,label:`${x}m`}))],dKeep);
 const filtered=byGrade.filter(x=>!$('fGradeDist').value||String(x.dist)===$('fGradeDist').value)
  .sort((a,b)=>gradeSort(a.grade,b.grade)||a.dist-b.dist||a.name.localeCompare(b.name,'ja'));
 fill('fRace',filtered.map(x=>({value:x.name,label:`${x.grade}｜${x.dist}m｜${x.name}（${x.venue}${x.surface}）`})),rKeep);
}
function rebuild(){
 refreshFilters();
 refreshGradeFilters();
 const m=bundle['lapdata.json'].meta;
 $('metaLine').textContent=`v${APP_VERSION} ／ ${m.from||'—'} ～ ${m.to||'—'} ／ ${m.races.toLocaleString()}レース`;
 render();
}
async function digest(str){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(str)))).map(x=>x.toString(16).padStart(2,'0')).join('')}
class FetchFailure extends Error{constructor(message,kind){super(message);this.kind=kind}}
async function getText(file){
 const u=new URL(file,location.href);u.searchParams.set('verify',String(Date.now()));const ctrl=new AbortController(),timer=setTimeout(()=>ctrl.abort(),15000);
 try{const r=await fetch(u,{cache:'no-store',signal:ctrl.signal});if(!r.ok)throw new FetchFailure(`${file}: HTTP ${r.status}`,'http');return await r.text()}
 catch(e){if(e instanceof FetchFailure)throw e;throw new FetchFailure('通信できません','network')}finally{clearTimeout(timer)}
}
async function decode(snapshot){
 const version=JSON.parse(snapshot.manifest);C.assert(version.app_version===APP_VERSION,'アプリ本体の更新が必要です。すべてのアプリ画面を閉じて開き直してください。');
 C.assert(version.schema_version===C.SCHEMA&&version.files,'データ形式が一致しません');const b={version};
 for(const f of C.FILES){C.assert(typeof snapshot.files[f]==='string','保存データ不足');C.assert(await digest(snapshot.files[f])===version.files[f],`${f} の世代または内容が一致しません`);b[f]=JSON.parse(snapshot.files[f])}
 return C.validateBundle(b);
}
const snapshotURL=()=>new URL(`./__lap_snapshot_${APP_VERSION}`,location.href).href;
const snapshotCache=()=>`lap-section-snapshot-${APP_VERSION}-${encodeURIComponent(new URL('.',location.href).pathname)}`;
async function saveSnapshot(s){if(!globalThis.caches)return false;try{const cache=await caches.open(snapshotCache());await cache.put(snapshotURL(),new Response(JSON.stringify(s),{headers:{'Content-Type':'application/json'}}));return true}catch{return false}}
async function readSnapshot(){if(!globalThis.caches)return null;try{const cache=await caches.open(snapshotCache()),r=await cache.match(snapshotURL());return r?await decode(await r.json()):null}catch{return null}}
async function update(initial=false){
 if(busy)return;busy=true;$('btnUpdate').disabled=true;state('確認中',summary());
 try{
  C.assert(C.APP_VERSION===APP_VERSION&&document.querySelector('meta[name="app-version"]')?.content===APP_VERSION,'アプリ本体の世代が一致しません。開き直してください。');
  const manifest=await getText('data-version.json');const files={};
  await Promise.all(C.FILES.map(async f=>{files[f]=await getText(f)}));
  const next=await decode({manifest,files}); // Commit only a complete validated generation.
  const saved=await saveSnapshot({manifest,files});bundle=next;rebuild();
  state('最新版確認済み',summary()+(saved?'':' ／ オフライン保存不可'));
 }catch(e){
  if(initial&&!bundle){bundle=await readSnapshot();if(bundle)rebuild()}
  const offline=e.kind==='network'&&navigator.onLine===false;
  state(offline?'オフライン':'更新失敗',(bundle?'前回の正常データを表示 ／ ':'')+e.message);
  if(!bundle){empty('readout','データを読み込めません。通信状態を確認して再試行してください。');$('chart').replaceChildren();$('courseBody').replaceChildren();$('pedigreeBody').replaceChildren()}
 }finally{busy=false;$('btnUpdate').disabled=false}
}
function fmt(x){if(x===null||x===undefined)return '—';if(x<60)return x.toFixed(1);return `${Math.floor(x/60)}:${(x%60).toFixed(1).padStart(4,'0')}`}
function label(k){const [v,s,d,c,g]=k.split('|');return `${v}${s}${d}m ${classLabel(c)} ${g}`}
function color(t,lo,hi){return `hsl(${8+(t-lo)/((hi-lo)||1)*205},72%,55%)`}
function pace(a,b){const d=a-b;return d<=-1?'ハイペース':d<=-.3?'やや前傾':d<.4?'ミドル':d<1.2?'やや後傾':'スローペース'}
function table(headers,rows){const t=node('table'),head=node('tr');headers.forEach(x=>head.append(node('th',x)));t.append(head);for(const row of rows){const tr=node('tr');row.forEach(x=>tr.append(node('td',x)));t.append(tr)}return t}
function draw(series,dist){
 const chart=$('chart');chart.replaceChildren();const all=series.flatMap(s=>C.segments(s.raw,dist).map(x=>x.normalized));
 const min=Math.min(...all),max=Math.max(...all),pad=(max-min)*.18||.6,lo=min-pad,hi=max+pad;
 const X=d=>44+(700-44-14)*d/dist,Y=v=>16+(340-16-42)*(1-(v-lo)/(hi-lo));
 const step=hi-lo>6?2:hi-lo>3?1:.5;
 for(let t=Math.ceil(lo/step)*step;t<=hi;t+=step){chart.append(svg('line',{x1:44,x2:686,y1:Y(t),y2:Y(t),stroke:'#16405B'}),svg('text',{x:37,y:Y(t)+4,fill:'#8FAABB','font-size':11,'text-anchor':'end'},t.toFixed(1)))}
 const base=series.find(x=>x.heat)||series[0],ss=C.segments(base.raw,dist),stride=ss.length>10?2:1;
 chart.append(svg('text',{x:X(0),y:318,fill:'#8FAABB','font-size':10,'text-anchor':'middle'},'0'));
 ss.forEach((s,i)=>{if(i%stride===0||i===ss.length-1)chart.append(svg('text',{x:X(s.end),y:318,fill:'#8FAABB','font-size':10,'text-anchor':'middle'},s.end))});
 chart.append(svg('text',{x:350,y:334,fill:'#8FAABB','font-size':11,'text-anchor':'middle'},'通過距離 (m)'));
 series.forEach((s,i)=>{
  const seg=C.segments(s.raw,dist),c=s.color||SER[i%SER.length];
  if(s.heat){
   for(let j=1;j<seg.length;j++)chart.append(svg('line',{x1:X(seg[j-1].end),y1:Y(seg[j-1].normalized),x2:X(seg[j].end),y2:Y(seg[j].normalized),stroke:color((seg[j-1].normalized+seg[j].normalized)/2,min,max),'stroke-width':3.2,'stroke-linecap':'round'}));
  }else chart.append(svg('polyline',{points:seg.map(p=>`${X(p.end)},${Y(p.normalized)}`).join(' '),fill:'none',stroke:c,'stroke-width':s.thin?1.4:2.3,'stroke-opacity':s.thin?.38:.78}));
  if(!s.thin)seg.forEach(p=>{const dotColor=s.heat?color(p.normalized,min,max):c;const dot=svg('circle',{cx:X(p.end),cy:Y(p.normalized),r:4.0,fill:dotColor,stroke:'#DDF3FF','stroke-width':0.7});dot.append(svg('title',{},`${p.start}–${p.end}m ／ ${p.normalized.toFixed(1)}秒（200m換算）`));chart.append(dot);if(s.heat)chart.append(svg('text',{x:X(p.end),y:Y(p.normalized)-9,fill:'#E8F2F7','font-size':10,'font-weight':700,'text-anchor':'middle'},p.normalized.toFixed(1)))})
 });
}
/* Schematic route helpers -------------------------------------------------
   The diagram is a schematic shape, but the DISTANCE SCALE along the drawn
   path is uniform: 1m is the same number of pixels everywhere. That is what
   lets the 200m lap bands (drawn with stroke-dasharray in the same px units)
   line up with the JRA distance anchors. Half-ellipse corner, parametrised
   from the straight/corner junction: p(t) = (cx - rx*sin t, cy - ry*cos t). */
function ellipseHalfLength(rx,ry,n=2048){let L=0,px=0,py=-ry;for(let i=1;i<=n;i++){const t=Math.PI*i/n,x=-rx*Math.sin(t),y=-ry*Math.cos(t);L+=Math.hypot(x-px,y-py);px=x;py=y}return L}
function ellipseRx(target,ry){let lo=.01,hi=Math.max(4*target,4*ry);for(let i=0;i<80;i++){const mid=(lo+hi)/2;if(ellipseHalfLength(mid,ry)<target)lo=mid;else hi=mid}return (lo+hi)/2}
function ellipseAngleAt(arc,rx,ry,n=2048){let L=0,px=0,py=-ry;for(let i=1;i<=n;i++){const t=Math.PI*i/n,x=-rx*Math.sin(t),y=-ry*Math.cos(t),step=Math.hypot(x-px,y-py);if(L+step>=arc)return Math.PI*(i-1)/n+(Math.PI/n)*(arc-L)/(step||1);L+=step;px=x;py=y}return Math.PI}
const ROLE=(route,r)=>route.anchors.find(a=>a.role===r);
// Original display vectors, reviewed against JRA course plan images (2026-10-06).
// Coordinates are illustration units, never surveyed coordinates. Each template
// runs backwards from the home-straight entrance (remaining distance increases).
// Cubics describe the different bends; straight segments preserve shared branches.
const COURSE_SHAPES={
 'tokyo-turf':[[115,215],[38,215,32,167,48,111],[58,73,78,55,125,55],[420,55],[474,55,489,78,505,108],[528,141,510,191,465,205],[440,215,422,215,400,215],[115,215]],
 'tokyo-dirt':[[128,199],[70,199,60,171,72,121],[80,91,96,78,133,78],[401,78],[440,78,460,103,470,130],[487,164,457,194,408,199],[128,199]],
 'nakayama-inner':[[427,214],[487,214,527,180,518,147],[509,111,480,100,442,100],[154,100],[104,100,69,132,76,167],[83,202,107,214,153,214],[427,214]],
 'nakayama-outer':[[427,214],[487,214,527,180,518,147],[480,92,337,39,205,34],[129,25,117,58,100,110],[80,151,72,170,91,192],[107,208,126,214,153,214],[427,214]],
 'nakayama-dirt':[[418,197],[466,197,490,177,486,151],[482,124,463,117,430,117],[159,117],[119,117,100,138,104,160],[109,187,128,197,165,197],[418,197]],
 'kyoto-inner':[[417,215],[475,215,490,172,480,132],[471,88,390,78,350,85],[163,119],[115,129,103,161,123,192],[135,210,153,215,184,215],[417,215]],
 'kyoto-outer':[[417,215],[517,215,522,174,513,116],[509,49,483,61,437,69],[350,85],[163,119],[115,129,103,161,123,192],[135,210,153,215,184,215],[417,215]],
 'kyoto-dirt':[[403,198],[450,198,465,163,454,133],[444,105,428,96,405,99],[175,135],[139,141,133,164,147,183],[158,195,174,198,194,198],[403,198]],
 'hanshin-inner':[[389,218],[433,203,450,169,428,125],[406,78,378,70,348,79],[133,142],[94,154,91,184,111,204],[122,217,139,218,165,218],[389,218]],
 'hanshin-outer':[[389,218],[476,218,540,179,521,120],[506,66,451,24,413,35],[348,79],[133,142],[94,154,91,184,111,204],[122,217,139,218,165,218],[389,218]],
 'hanshin-dirt':[[374,198],[411,188,420,168,402,132],[386,102,368,96,347,101],[148,157],[121,165,119,181,135,192],[144,198,154,198,176,198],[374,198]],
 'chukyo-turf':[[155,214],[83,214,35,172,48,123],[57,73,100,40,156,48],[428,72],[482,78,512,107,508,148],[504,190,479,214,435,214],[155,214]],
 'chukyo-dirt':[[159,197],[102,197,66,165,77,127],[86,88,115,67,160,73],[417,94],[458,99,482,121,476,151],[470,181,452,197,414,197],[159,197]],
 'niigata-inner':[[255,207],[201,207,185,172,191,139],[197,109,218,92,255,92],[459,92],[510,92,531,115,526,151],[521,188,502,207,463,207],[255,207]],
 'niigata-outer':[[110,207],[54,207,38,173,43,138],[49,108,70,92,110,92],[459,92],[510,92,531,115,526,151],[521,188,502,207,463,207],[110,207]],
 'niigata-dirt':[[270,191],[229,191,211,168,216,143],[221,120,239,108,271,108],[451,108],[488,108,507,125,502,152],[497,178,481,191,451,191],[270,191]],
 'fukushima-turf':[[420,211],[479,211,519,181,513,141],[507,95,453,73,409,72],[156,70],[90,70,55,109,58,151],[60,188,96,211,154,211],[420,211]],
 'fukushima-dirt':[[411,195],[461,195,492,175,487,143],[482,110,445,91,401,90],[163,88],[112,88,80,115,82,148],[84,177,115,195,164,195],[411,195]],
 'sapporo-turf':[[399,212],[460,212,504,180,502,137],[500,94,459,60,401,60],[179,60],[120,60,76,94,75,137],[74,180,119,212,179,212],[399,212]],
 'sapporo-dirt':[[391,194],[442,194,479,171,479,137],[479,103,445,80,393,80],[185,80],[136,80,101,104,100,137],[99,170,136,194,185,194],[391,194]],
 'hakodate-turf':[[414,210],[472,210,505,178,504,137],[503,96,470,66,414,66],[158,66],[102,66,68,96,68,137],[68,178,102,210,158,210],[414,210]],
 'hakodate-dirt':[[405,192],[449,192,478,168,478,137],[478,106,449,84,405,84],[167,84],[123,84,95,106,95,137],[95,168,123,192,167,192],[405,192]],
 'kokura-turf':[[425,215],[483,215,515,178,511,138],[508,95,476,60,421,60],[162,60],[102,60,60,95,60,139],[60,182,101,215,162,215],[425,215]],
 'kokura-dirt':[[414,193],[459,193,488,168,485,137],[482,104,457,83,414,83],[170,83],[122,83,88,106,88,138],[88,171,122,193,170,193],[414,193]]
};
// Corner label positions follow the bends in each plan, not fixed lap fractions.
const COURSE_CORNERS={
 'tokyo-turf':[[53,173],[66,85],[478,81],[490,177]],
 'tokyo-dirt':[[75,172],[90,100],[448,102],[467,173]],
 'nakayama-inner':[[496,183],[488,119],[100,121],[97,187]],
 'nakayama-outer':[[496,183],[470,110],[155,43],[96,187]],
 'nakayama-dirt':[[470,180],[468,129],[123,132],[120,179]],
 'kyoto-inner':[[466,188],[459,98],[133,137],[135,193]],
 'kyoto-outer':[[504,184],[497,69],[133,137],[135,193]],
 'kyoto-dirt':[[442,176],[439,116],[153,149],[157,181]],
 'hanshin-inner':[[423,187],[406,103],[114,156],[112,196]],
 'hanshin-outer':[[490,187],[489,70],[114,156],[112,196]],
 'hanshin-dirt':[[398,178],[387,121],[138,167],[138,189]],
 'chukyo-turf':[[61,176],[85,72],[482,102],[483,181]],
 'chukyo-dirt':[[87,168],[108,91],[455,114],[454,177]],
 'niigata-inner':[[203,183],[210,113],[510,114],[510,183]],
 'niigata-outer':[[55,183],[ 60,113],[510,114],[510,183]],
 'niigata-dirt':[[230,175],[233,124],[489,123],[486,175]],
 'fukushima-turf':[[493,179],[474,96],[83,98],[ 80,180]],
 'fukushima-dirt':[[471,173],[452,113],[103,112],[107,173]],
 'sapporo-turf':[[477,182],[477, 90],[103,90],[103,183]],
 'sapporo-dirt':[[459,171],[456,102],[122,102],[123,171]],
 'hakodate-turf':[[486,180],[484,96],[90,96],[90,180]],
 'hakodate-dirt':[[458,170],[458,107],[115,107],[115,170]],
 'kokura-turf':[[491,184],[487,92],[87,92],[87,184]],
 'kokura-dirt':[[466,169],[465,105],[108,105],[108,169]]
};
// Sample the same polyline used for SVG and distance lookup: no browser-specific
// curve-length approximation can move lap bands relative to distance markers.
function sampleCourse(shape){
 const pts=[{x:shape[0][0],y:shape[0][1]}];
 for(const seg of shape.slice(1)){
  const a=pts.at(-1);
  if(seg.length===2){pts.push({x:seg[0],y:seg[1]});continue}
  for(let i=1;i<=40;i++){const t=i/40,u=1-t;pts.push({x:u*u*u*a.x+3*u*u*t*seg[0]+3*u*t*t*seg[2]+t*t*t*seg[4],y:u*u*u*a.y+3*u*u*t*seg[1]+3*u*t*t*seg[3]+t*t*t*seg[5]})}
 }
 return pts;
}
function courseMorphology(route){
 const shape=COURSE_SHAPES[route.shape_id];if(!shape||!(route.lap_m>0))return null;
 const pts=sampleCourse(shape),lengths=[0];
 for(let i=1;i<pts.length;i++)lengths.push(lengths[i-1]+Math.hypot(pts[i].x-pts[i-1].x,pts[i].y-pts[i-1].y));
 const total=lengths.at(-1),lap=route.lap_m,k=total/lap;
 const rawAt=p=>{p=Math.max(0,Math.min(total,p));let i=1;while(i<lengths.length-1&&lengths[i]<p)i++;const t=(p-lengths[i-1])/(lengths[i]-lengths[i-1]);return {x:pts[i-1].x+(pts[i].x-pts[i-1].x)*t,y:pts[i-1].y+(pts[i].y-pts[i-1].y)*t}};
 // Put the goal on the home straight using the official straight/lap ratio.
 const origin=total-route.straight_m*k,goal=rawAt(origin);
 const rotated=[goal,...pts.filter((_,i)=>lengths[i]>origin),...pts.slice(1).filter((_,i)=>lengths[i+1]<origin),goal];
 const at=s=>{const pt=rawAt((origin+Math.max(0,Math.min(lap,s))*k)%total);return {...pt,zone:pt.y<120?'back':pt.y>190?'home':pt.x<290?'corner-late':'corner-early'}};
 const right=route.turn==='右回り';
 // Labels are visual corner positions, never asserted distance anchors.
 const corners=COURSE_CORNERS[route.shape_id].map(([x,y])=>({x,y}));
 return {mode:'loop',morphology:true,d:route.distance_m,lap,k,total,at,laps:route.distance_m/lap,
  loopPath:rotated.map((p,i)=>`${i?'L':'M'} ${p.x} ${p.y}`).join(' '),cornerArcs:[],
  corners:corners.map((p,i)=>({...p,label:[4,3,2,1][i]+'角',dx:p.x>290?-20:20})),
  right,goalX:goal.x,LX:Math.min(...pts.map(p=>p.x)),RX:Math.max(...pts.map(p=>p.x)),TOP:Math.min(...pts.map(p=>p.y)),BOT:shape[0][1],CY:140};
}

// ---- 全場共通の模式ジオメトリ -------------------------------------------------
// loopGeometry: 公式の「1周距離」と「直線距離」だけを根拠に、1m=一定pxのスタジアム型
// 経路を作る。経路長は s=「ゴールまでの残り距離(m)」で、ゴールが s=0。
function loopGeometry(route,straight_m){
 const lap=route.lap_m,d=route.distance_m;
 if(!(lap>0)||!(straight_m>0))return null;
 const R=72,CY=135,LX=80,RX=500,TOP=CY-R,BOT=CY+R,SB=RX-LX,PERI=2*SB+2*Math.PI*R;
 const k=PERI/lap,A=straight_m*k;
 if(!(A>0)||!(A<SB))return null;
 const gx=LX+A,B=Math.PI*R,C=SB,D=Math.PI*R,E=SB-A;
 const loopPath=`M ${gx.toFixed(2)} ${BOT} L ${LX} ${BOT} A ${R} ${R} 0 0 1 ${LX} ${TOP} L ${RX} ${TOP} A ${R} ${R} 0 0 1 ${RX} ${BOT} L ${gx.toFixed(2)} ${BOT}`;
 const at=s=>{
  const sp=Math.max(0,Math.min(lap,s))*k;
  if(sp<=A)return {x:gx-sp,y:BOT,zone:'home'};
  if(sp<=A+B){const t=(sp-A)/R;return {x:LX-R*Math.sin(t),y:CY+R*Math.cos(t),zone:'corner-late'}}
  if(sp<=A+B+C)return {x:LX+(sp-A-B),y:TOP,zone:'back'};
  if(sp<=A+B+C+D){const t=(sp-A-B-C)/R;return {x:RX+R*Math.sin(t),y:CY-R*Math.cos(t),zone:'corner-early'}}
  return {x:RX-(sp-A-B-C-D),y:BOT,zone:'post-goal'};
 };
 return {mode:'loop',d,lap,k,at,total:PERI,loopPath,goalX:gx,cornerArcs:[
  `M ${LX} ${BOT} A ${R} ${R} 0 0 1 ${LX} ${TOP}`,`M ${RX} ${TOP} A ${R} ${R} 0 0 1 ${RX} ${BOT}`],
  laps:d/lap,straightPx:A,R,CY,LX,RX,TOP,BOT};
}
// straightGeometry: 直線コース。コーナーが無いので形状は実際と一致する。
function straightGeometry(route){
 const d=route.distance_m,X0=40,X1=540,Y=58;
 return {mode:'straight',d,lap:d,k:(X1-X0)/d,total:X1-X0,laps:1,
  loopPath:`M ${X1} ${Y} L ${X0} ${Y}`,
  at:s=>({x:X1-Math.max(0,Math.min(d,s))*((X1-X0)/d),y:Y,zone:'home'}),cornerArcs:[]};
}
function routeGeometry(route){
 const goal=route.distance_m,c3=ROLE(route,'first_corner'),se=ROLE(route,'straight_entry');
 if(!c3||!se||!(c3.m>0)||!(se.m>c3.m)||!(goal>se.m))return null;
 const TOP=58,BOT=214,CX=190,HOME=330,ry=(BOT-TOP)/2,cy=(TOP+BOT)/2;
 const k=HOME/(goal-se.m),rx=ellipseRx((se.m-c3.m)*k,ry),sx=CX+c3.m*k;
 const d=`M ${sx.toFixed(2)} ${TOP} L ${CX} ${TOP} A ${rx.toFixed(3)} ${ry} 0 0 0 ${CX} ${BOT} L ${(CX+HOME).toFixed(2)} ${BOT}`;
 const at=m=>{
  if(m<=c3.m)return {x:CX+(c3.m-m)*k,y:TOP,zone:'back'};
  if(m>=se.m)return {x:CX+(m-se.m)*k,y:BOT,zone:'home'};
  const t=ellipseAngleAt((m-c3.m)*k,rx,ry);return {x:CX-rx*Math.sin(t),y:cy-ry*Math.cos(t),zone:'corner'};
 };
 return {d,k,at,goal,rx,ry,straightEntry:se.m};
}
// 公式に確定しているのは「1周距離」「直線距離」「高低差」だけの距離を描く。
// コーナーまでの距離は数値を持たないので、図の中でも数値を出さず未確定と明記する。
// 起伏プロファイル＋距離目盛。公式に数値がある区間だけを線として描き、
// 数値が無い距離は形状を一切描かず「公式非公表」と示す（波形の創作をしない）。
// 出典の記述を距離軸の標高列へ。up/down は出典どおりの向き、
// 高さは数値がある区間はその値、無い区間は合計からの按分（模式）。
function routeHeightDiff(route){
 const t=route&&route.display&&route.display.hill_fact||'';
 const m=t.match(/高低差\s*([0-9.]+)m/);
 return m?Number(m[1]):null;
}
function elevationSeries(prof,d,route){
 const sh=prof&&prof.shape;if(!sh||!Array.isArray(sh.segments)||!sh.segments.length)return null;
 let list=[];
 for(const sg of sh.segments){
  const a=Math.max(0,d-sg.to_rem),b=Math.min(d,d-sg.from_rem);
  if(b-a<=0.5)continue;
  const mag=typeof sg.rise_m==='number'?Math.abs(sg.rise_m):null;
  list.push({a,b,dir:sg.dir,rise:mag,numeric:sg.precision==='numeric'&&mag!==null});
 }
 if(!list.length)return null;
 list.sort((x,y)=>x.a-y.a);
 // 同じ向きの重複区間は二重加算しない。複数資料の表現が重なる場合は1区間として扱う。
 const merged=[];
 for(const sg of list){
  const z=merged[merged.length-1];
  if(z&&sg.a<z.b-0.5&&sg.dir===z.dir){
   z.b=Math.max(z.b,sg.b);
   if(z.rise===null)z.rise=sg.rise;
   else if(sg.rise!==null)z.rise=Math.max(z.rise,sg.rise);
   z.numeric=z.numeric&&sg.numeric;
  }else merged.push({...sg});
 }
 list=merged;
 const target=(typeof sh.total_m==='number'&&sh.total_m>0)?sh.total_m:routeHeightDiff(route);
 let e=0,minE=0,maxE=0,estimated=!!sh.has_estimated_heights;
 const pts=[[list[0].a,0]];
 for(const sg of list){
  if(pts[pts.length-1][0]<sg.a-0.5)pts.push([sg.a,e]);
  let delta=0;
  if(sg.dir==='up'||sg.dir==='down'){
   let mag=sg.rise;
   if(!(typeof mag==='number'&&mag>0)){
    estimated=true;
    // 高低差の総量は公式値、区間ごとの高さが非公表なら、
    // 方向だけは資料どおりにし、公式高低差の範囲内で模式化する。
    if(target>0){
     if(sg.dir==='up')mag=Math.max(0,(minE+target)-e);
     else mag=Math.max(0,e-(maxE-target));
     if(mag<target*0.12)mag=target*0.35;
    }else mag=1;
   }
   delta=(sg.dir==='up'?1:-1)*mag;
  }
  e+=delta;minE=Math.min(minE,e);maxE=Math.max(maxE,e);
  pts.push([sg.b,e]);
 }
 const lo=Math.min(...pts.map(p=>p[1])),hi=Math.max(...pts.map(p=>p[1]));
 return {pts:pts.map(p=>[p[0],p[1]-lo]),segs:list,range:hi-lo,target,
  estimated,sources:sh.sources};
}
function profilePanel(prof,route,d,label){
 const W=580,H=176,L=52,RG=16,TOPY=34,BASE=104;
 const el=svg('svg',{viewBox:`0 0 ${W} ${H}`,class:'profileSvg',role:'img','aria-label':label});
 const X=m=>L+(W-L-RG)*m/d;
 // 出典の記述から標高列を作る。無ければ数値区間だけで作る。
 const series=elevationSeries(prof,d,route);
 let pts,shaped;
 if(series){pts=series.pts;shaped=true;}
 else{
  pts=[[0,0]];let e2=0;
  for(const sg of prof.numeric_segments){
   if(sg.type==='uphill'&&typeof sg.rise_m==='number'){pts.push([sg.from_m,e2]);e2+=sg.rise_m;pts.push([sg.to_m,e2]);}
  }
  pts.push([d,e2]);shaped=pts.length>3;
 }
 const top=Math.max(series&&series.target||0,...pts.map(q=>q[1]),1);
 const Y=v=>BASE-(BASE-TOPY)*v/top;
 for(let v=0;v<=top+1e-9;v+=(top>2.5?1:0.5)){
  el.append(svg('line',{x1:L,x2:W-RG,y1:Y(v),y2:Y(v),stroke:'#22333f','stroke-width':1}),
   svg('text',{x:L-7,y:Y(v)+4,fill:'#7f93a6','font-size':11,'text-anchor':'end'},`${v.toFixed(1)}m`));
 }
 el.append(svg('line',{x1:L,x2:W-RG,y1:BASE,y2:BASE,stroke:'#41566B','stroke-width':1.5}));
 // 距離アンカーの位置だけを縦線で示す（名前はコース図側に出ている）
 for(const a of route.anchors)
  el.append(svg('line',{x1:X(a.m),x2:X(a.m),y1:TOPY-4,y2:BASE,stroke:'#2c4155','stroke-width':1}));
 const step=d>2400?400:200;
 for(let m=0;m<=d;m+=step)
  el.append(svg('line',{x1:X(m),x2:X(m),y1:BASE,y2:BASE+5,stroke:'#41566B','stroke-width':1}),
   svg('text',{x:X(m),y:BASE+20,fill:'#7f93a6','font-size':11,'text-anchor':'middle'},String(m)));
 el.append(svg('text',{x:W-RG,y:BASE+38,fill:'#7f93a6','font-size':11,'text-anchor':'end'},'通過距離（m）'));
 const dirY=158,dirEnd=W-RG-50;
 el.append(
  svg('text',{x:L,y:dirY+4,fill:'#9FC3D8','font-size':10,'font-weight':700,'text-anchor':'start'},'スタート'),
  svg('line',{x1:L+48,x2:dirEnd,y1:dirY,y2:dirY,stroke:'#9FC3D8','stroke-width':2}),
  svg('path',{d:`M ${dirEnd-8} ${dirY-5} L ${dirEnd} ${dirY} L ${dirEnd-8} ${dirY+5}`,fill:'none',stroke:'#9FC3D8','stroke-width':2,'stroke-linecap':'round','stroke-linejoin':'round'}),
  svg('text',{x:(L+W-RG)/2,y:dirY-6,fill:'#9FC3D8','font-size':10,'font-weight':700,'text-anchor':'middle'},'進行方向'),
  svg('text',{x:W-RG,y:dirY+4,fill:'#9FC3D8','font-size':10,'font-weight':700,'text-anchor':'end'},'ゴール')
 );
 if(shaped){
  const line=pts.map((q,i)=>`${i?'L':'M'} ${X(q[0]).toFixed(1)} ${Y(q[1]).toFixed(1)}`).join(' ');
  el.append(svg('path',{d:`${line} L ${X(d).toFixed(1)} ${BASE} L ${X(0).toFixed(1)} ${BASE} Z`,fill:'#1D3A52',opacity:0.8}),
   svg('path',{d:line,fill:'none',stroke:'#F6C55A','stroke-width':3,'stroke-linejoin':'round'}));
  for(const sg of prof.numeric_segments){
   if(sg.type!=='uphill'||typeof sg.rise_m!=='number')continue;
   el.append(svg('line',{x1:X(sg.from_m),x2:X(sg.to_m),y1:TOPY-14,y2:TOPY-14,stroke:'#FF6B4A','stroke-width':5,'stroke-linecap':'round'}),
    svg('text',{x:(X(sg.from_m)+X(sg.to_m))/2,y:TOPY-20,fill:'#FF9A82','font-size':11,'text-anchor':'middle'},
     `上り ${Math.round(sg.to_m-sg.from_m)}m ／ +${sg.rise_m.toFixed(1)}m`));
  }
  if(series&&series.estimated)
   el.append(svg('text',{x:L,y:H-26,fill:'#7f93a6','font-size':10,'text-anchor':'start'},
    '上り下りの並びは出典の記述どおり。数値が示されている区間はその値、'),
    svg('text',{x:L,y:H-12,fill:'#7f93a6','font-size':10,'text-anchor':'start'},
    '数値の無い区間の高さは公式高低差の範囲内で模式化しています。'));
 }else{
  el.append(svg('line',{x1:X(0),x2:X(d),y1:Y(0),y2:Y(0),stroke:'#6C8095','stroke-width':2.5,'stroke-dasharray':'8 7'}),
   svg('text',{x:(X(0)+X(d))/2,y:TOPY+14,fill:'#8195A8','font-size':11,'text-anchor':'middle'},'区間ごとの起伏の形はJRA公式が非公表のため描いていません'),
   svg('text',{x:(X(0)+X(d))/2,y:TOPY+30,fill:'#8195A8','font-size':11,'text-anchor':'middle'},'（全体の高低差は上の欄に公式値を表示）'));
 }
 return el;
}
function renderSchematicRoute(body,v,s,d,c,laps,routeOverride,compact){
 const route=routeOverride||c.route,prof=bundle['elevation.json'].profiles[`${v}|${s}|${d}`];
 if(!route||!prof||route.distance_m!==d)return false;
 const loop=route.mode==='loop-schematic',straight=route.mode==='straight-course';
 if(!loop&&!straight)return false;
 const geo=loop?(courseMorphology(route)||loopGeometry(route,typeof route.straight_m==='number'?route.straight_m:(typeof c.straight_m==='number'?c.straight_m:0))):straightGeometry(route);
 if(!geo)return false;
 const T=route.display||{};
 const grid=node('div',undefined,'courseGrid'),left=node('div'),right=node('div',undefined,'courseFacts');
 const map=svg('svg',{viewBox:loop?'0 0 580 270':'0 0 580 120',class:'courseSvg',role:'img','aria-label':`${v}${s}${d}m JRA公式平面図準拠・表示用簡略図`});
 if(geo.morphology&&route.companion_shape_id){
  const companion=courseMorphology({...route,shape_id:route.companion_shape_id});
  if(companion)map.append(svg('path',{d:companion.loopPath,fill:'none',stroke:'#536575','stroke-width':9,opacity:.6}));
 }
 map.append(svg('path',{d:geo.loopPath,fill:'none',stroke:'#22432f','stroke-width':22,'stroke-linecap':'round'}));
 // 走行区間（ゴールから距離分だけ遡った範囲）を本線色で重ねる
 const runLen=Math.min(geo.d,geo.lap)*geo.k;
 map.append(svg('path',{d:geo.loopPath,fill:'none',stroke:'#2d5c3f','stroke-width':22,'stroke-linecap':'butt','stroke-dasharray':`${runLen.toFixed(3)} ${(geo.total-runLen).toFixed(3)}`}));
 // ラップ帯は簡略経路の全長に対し距離比例で配置（実地座標ではない）。
 const ss=C.segments(laps,d),lo=Math.min(...ss.map(x=>x.normalized)),hi=Math.max(...ss.map(x=>x.normalized));
 ss.forEach(seg=>{
  const a=Math.max(d-seg.start-seg.distance,0),b=Math.min(d-seg.start,geo.lap);
  if(!(b>a))return;
  map.append(svg('path',{d:geo.loopPath,fill:'none',stroke:color(seg.normalized,lo,hi),'stroke-width':12,'stroke-linecap':'butt','stroke-dasharray':`${((b-a)*geo.k).toFixed(3)} ${(geo.total-(b-a)*geo.k).toFixed(3)}`,'stroke-dashoffset':(-a*geo.k).toFixed(3)}));
 });
 // 旧式のfallbackだけは、模式のコーナーを破線で示す
 for(const arc of geo.cornerArcs)map.append(svg('path',{d:arc,fill:'none',stroke:'#8195A8','stroke-width':2,'stroke-dasharray':'6 6',opacity:0.9}));
 // 距離マーカー（1mあたりの長さが一定なので、位置は距離として正しい）
 const mstep=d<=1200?200:d<=2400?400:600;
 const visibleAnchors=route.anchors.filter(a=>!geo.morphology||(['start','straight_entry','goal'].includes(a.role)&&(a.role==='start'||d-a.m<=geo.lap)));
 const anchorPts=visibleAnchors.map(a=>{const r0=d-a.m;return geo.at(loop?((r0%geo.lap)+geo.lap)%geo.lap:r0)});
 for(let m=mstep;m<d;m+=mstep){
  const rem=d-m;if(geo.morphology&&rem>geo.lap)continue;const pt=geo.at(loop?((rem%geo.lap)+geo.lap)%geo.lap:rem);
  // アンカーのラベルと重なる位置の距離マーカーは出さない
  if(anchorPts.some(q=>Math.hypot(q.x-pt.x,q.y-pt.y)<30))continue;
  const off=pt.zone==='back'?[0,-13]:pt.zone==='corner-late'?[-15,0]:pt.zone==='corner-early'?[15,0]:[0,15];
  map.append(svg('circle',{class:'kmDot',cx:pt.x.toFixed(2),cy:pt.y.toFixed(2),r:2.6,fill:'#E9EFF5',opacity:0.85}),
   svg('text',{x:Math.max(32,Math.min(548,pt.x+off[0])).toFixed(2),y:Math.max(16,Math.min(254,pt.y+off[1]+3)).toFixed(2),fill:'#9fb2c4','font-size':9,
    'text-anchor':'middle'},`${m}m`));
 }
 const placed=[];
 for(const a of visibleAnchors){
  const sRem=d-a.m,pt=geo.at(loop?((sRem%geo.lap)+geo.lap)%geo.lap:sRem),isStart=a.m===0,isGoal=a.m===d;
  // 新図の上半分は経路の上側へ、ホーム側は下側へラベルを置く。
  const down=pt.zone==='back'||pt.y>140;
  let dy=geo.morphology?(pt.y<175?-23:28):(pt.zone==='back'?24:down?28:-18);const dx=isStart?0:isGoal?10:0;
  let lx=Math.max(44,Math.min(536,pt.x+dx));
  if(geo.morphology){
   const candidates=[];
   for(const oy of [dy,dy+28,dy-28,-28,28])for(const ox of [dx,dx-64,dx+64]){
    const x=Math.max(44,Math.min(536,pt.x+ox)),y=Math.max(34,Math.min(240,pt.y+oy));
    candidates.push({x,y});
   }
   const pos=candidates.find(p=>!placed.some(q=>Math.abs(q[0]-p.x)<64&&Math.abs(q[1]-p.y)<36))||candidates[0];
   lx=pos.x;dy=pos.y-pt.y;
  }else while(placed.some(q=>Math.abs(q[0]-lx)<56&&Math.abs(q[1]-(pt.y+dy))<17))dy+=down?26:-26;
  placed.push([lx,pt.y+dy]);
  map.append(svg('circle',{class:'anchorDot',cx:pt.x.toFixed(2),cy:pt.y.toFixed(2),r:5,fill:'#0E161F',stroke:'#E9EFF5','stroke-width':2}),
   svg('text',{x:lx.toFixed(2),y:(pt.y+dy).toFixed(2),fill:'#E9EFF5','font-size':12,'font-weight':700,'text-anchor':'middle'},(geo.morphology&&isStart?'スタート':a.label)),
   svg('text',{x:lx.toFixed(2),y:(pt.y+dy+(dy>0?14:-13)).toFixed(2),fill:'#8195A8','font-size':9,'text-anchor':'middle'},`${Math.round(a.m)}m`));
 }
 if(loop){
  if(geo.morphology){
   for(const p of geo.corners)map.append(svg('text',{x:p.x+p.dx,y:p.y+4,fill:'#EDF5FF','font-size':13,'font-weight':700,'text-anchor':'middle',stroke:'#0E161F','stroke-width':4,'paint-order':'stroke'},p.label));
   map.append(svg('text',{x:290,y:145,fill:'#BDD0DD','font-size':13,'text-anchor':'middle'},`${v} ${route.variant_label||c.variant||s}`),
    svg('text',{x:290,y:164,fill:'#9FB2C4','font-size':11,'text-anchor':'middle'},geo.right?'← 右回り':'左回り →'));
  }
  if(geo.laps>1)map.append(svg('text',{x:572,y:18,fill:'#FF9A82','font-size':10,'text-anchor':'end'},'色帯・距離点は最終1周分'));
 }else{
  map.append(svg('text',{x:290,y:26,fill:'#8195A8','font-size':10,'text-anchor':'middle'},'直線コース（コーナーなし）'));
 }
 left.append(map);
 if(geo.morphology)left.append(node('p','JRA公式平面図準拠・表示用簡略図 ／ スタート位置は距離換算'+(route.companion_shape_id?' ／ 灰線は別回り':''),'note'));
 left.append(profilePanel(prof,route,d,`${v}${s}${d}m 起伏プロファイルと距離目盛`));
 const facts=compact?[['公式アンカー',T.anchor_fact],['高低差',T.hill_fact]]
                    :[['公式アンカー',T.anchor_fact],['高低差',T.hill_fact],['精度',T.precision_fact]];
 for(const [key,val]of facts){if(!val)continue;const f=node('div',undefined,'fact');f.append(node('div',key,'fk'),node('div',val,'fv'));right.append(f)}
 grid.append(left,right);body.append(grid);
 if(!compact){
  for(const q of prof.qualitative)body.append(node('p','起伏：'+q.label,'note'));
  if(T.note)body.append(node('p',T.note,'note'));
  if(c.source_url&&T.source_label){const a=node('a',T.source_label);a.href=c.source_url;a.target='_blank';a.rel='noopener noreferrer';body.append(a)}
 }
 return true;
}
// 内外の別が公式記載から確定できない距離は、両方の場合を並べて出す。
// どちらか一方を推測で選ぶことはしない。
function renderRouteVariants(body,v,s,d,c,laps){
 const vs=c.route_variants;
 if(!Array.isArray(vs)||vs.length<2)return false;
 const blocks=[];
 for(const r of vs){
  const tmp=node('div');
  if(renderSchematicRoute(tmp,v,s,d,c,laps,r,true))blocks.push([r,tmp]);
 }
 if(!blocks.length)return false;
 if(c.route_unavailable_reason)body.append(node('p',c.route_unavailable_reason,'note'));
 for(const [r,tmp] of blocks){
  body.append(node('div',`${r.variant_label}の場合`,'variantHead'));
  for(const ch of [...tmp.children])body.append(ch);
  if(r.display&&r.display.note)body.append(node('p',r.display.note,'note'));
 }
 const prof=bundle['elevation.json'].profiles[`${v}|${s}|${d}`];
 for(const q of prof.qualitative)body.append(node('p','起伏：'+q.label,'note'));
 const T=blocks[0][0].display||{};
 if(T.precision_fact)body.append(node('p',T.precision_fact,'note'));
 if(c.source_url&&T.source_label){const a=node('a',T.source_label);a.href=c.source_url;a.target='_blank';a.rel='noopener noreferrer';body.append(a)}
 return true;
}
function renderAnchoredRoute(body,v,s,d,c,laps){
 const route=c.route,prof=bundle['elevation.json'].profiles[`${v}|${s}|${d}`];
 if(!route||route.mode!=='distance-anchored-schematic'||route.distance_m!==d||!prof)return false;
 const T=route.display||{};
 const geo=routeGeometry(route);if(!geo)return false;
 const grid=node('div',undefined,'courseGrid'),left=node('div'),right=node('div',undefined,'courseFacts');
 const map=svg('svg',{viewBox:'0 0 580 270',class:'courseSvg',role:'img','aria-label':`${v}${s}${d}m 距離アンカー付き模式コース図`});
 map.append(svg('path',{d:geo.d,fill:'none',stroke:'#31465B','stroke-width':20,'stroke-linecap':'round'}));
 // Lap bands use the same px-per-metre scale as the anchors, in user units
 // (no pathLength attribute), so placement does not depend on UA quirks.
 const ss=C.segments(laps,d),lo=Math.min(...ss.map(x=>x.normalized)),hi=Math.max(...ss.map(x=>x.normalized));
 ss.forEach(seg=>map.append(svg('path',{d:geo.d,fill:'none',stroke:color(seg.normalized,lo,hi),'stroke-width':12,'stroke-linecap':'butt','stroke-dasharray':`${(seg.distance*geo.k).toFixed(3)} ${((geo.goal-seg.distance)*geo.k).toFixed(3)}`,'stroke-dashoffset':(-seg.start*geo.k).toFixed(3)})));
 for(const a of route.anchors){
  const pt=geo.at(a.m),first=a.m===0,last=a.m===geo.goal,below=pt.zone==='home'&&a.role==='straight_entry';
  const dx=first?-8:last?8:0,dy=below?25:-20,anchor=first?'end':last?'start':'middle';
  map.append(svg('circle',{class:'anchorDot',cx:pt.x.toFixed(2),cy:pt.y.toFixed(2),r:5,fill:'#0E161F',stroke:'#E9EFF5','stroke-width':2}),
   svg('text',{x:(pt.x+dx).toFixed(2),y:(pt.y+dy).toFixed(2),fill:'#E9EFF5','font-size':12,'font-weight':700,'text-anchor':anchor},a.label.replace(/（.*$/,'')),
   svg('text',{x:(pt.x+dx).toFixed(2),y:(pt.y+dy+14).toFixed(2),fill:'#8195A8','font-size':9,'text-anchor':anchor},`${Math.round(a.m)}m`));
 }
 const hill=prof.numeric_segments.find(x=>x.type==='uphill');
 if(hill){const a=geo.at(hill.from_m),b=geo.at(hill.to_m);
  map.append(svg('line',{x1:a.x.toFixed(2),x2:b.x.toFixed(2),y1:a.y+25,y2:b.y+25,stroke:'#FF6B4A','stroke-width':5,'stroke-linecap':'round'}),
   svg('text',{x:((a.x+b.x)/2).toFixed(2),y:a.y+43,fill:'#FF9A82','font-size':10,'text-anchor':'middle'},`直線坂 ${Math.round(hill.to_m-hill.from_m)}m / +${hill.rise_m.toFixed(1)}m`));
 }
 map.append(svg('text',{x:Math.round((190+geo.at(0).x)/2),y:35,fill:'#8195A8','font-size':10,'text-anchor':'middle'},'向正面'),svg('text',{x:470,y:236,fill:'#8195A8','font-size':10,'text-anchor':'middle'},'ホームストレッチ'));
 left.append(map);
 left.append(profilePanel(prof,route,d,`${v}${s}${d}m 起伏プロファイルと距離目盛`));
 const facts=[['公式アンカー',T.anchor_fact],['直線の坂',T.hill_fact],['精度',T.precision_fact]];
 for(const [k,val]of facts){if(!val)continue;const f=node('div',undefined,'fact');f.append(node('div',k,'fk'),node('div',val,'fv'));right.append(f)}
 grid.append(left,right);body.append(grid);
 for(const q of prof.qualitative)body.append(node('p','起伏（位置範囲未確定）：'+q.label,'note'));
 if(T.note)body.append(node('p',T.note,'note'));
 if(c.source_url&&T.source_label){const a=node('a',T.source_label);a.href=c.source_url;a.target='_blank';a.rel='noopener noreferrer';body.append(a)}
 if(c.route_source_url&&T.route_source_label){body.append(node('span',' ／ '));const a=node('a',T.route_source_label);a.href=c.route_source_url;a.target='_blank';a.rel='noopener noreferrer';body.append(a)}
 return true;
}
function renderCourse(v,s,d,laps){
 $('courseTitle').textContent=`${v}${s}${d}m`;const body=$('courseBody');body.replaceChildren();
 const c=C.resolveCourse(bundle['courses.json'].courses,v,s,d);
 if(!c){empty('courseBody','コース情報・実位置連動は未対応です。');return}
 const facts=node('div',undefined,'courseFacts');
 const entries=[['回り・区分',`${c.turn||'未確認'} ／ ${c.variant}`],['直線距離',c.straight_m===null?'未確認':typeof c.straight_m==='number'?`${c.straight_m}m`:c.straight_m],['高低差',c.height_diff_m===null?'未確認':typeof c.height_diff_m==='number'?`${c.height_diff_m}m`:c.height_diff_m]];
 for(const [k,val]of entries){const f=node('div',undefined,'fact');f.append(node('div',k,'fk'),node('div',val,'fv'));facts.append(f)}
 body.append(facts);
 if(renderAnchoredRoute(body,v,s,d,c,laps))return;
 if(renderSchematicRoute(body,v,s,d,c,laps))return;
 if(renderRouteVariants(body,v,s,d,c,laps))return;
 body.append(node('p','実コース位置・起伏連動：未対応。発走地点と距離別断面の根拠が揃うまで、推測の図や高低差は表示しません。','note'));
 if(c.route_unavailable_reason)body.append(node('p',c.route_unavailable_reason,'note'));
 body.append(node('p',c.verification==='verified-basic'?'基本情報は出典表と照合済みです。':'基本情報はv3.1からの参考値です。距離別の公式照合は未完了です。','note'));
 if(c.source_url){const a=node('a','JRA公式コース図・高低断面図');a.href=c.source_url;a.target='_blank';a.rel='noopener noreferrer';body.append(a)}
 const points=C.segments(laps,d),strip=node('div',undefined,'strip'),lo=Math.min(...points.map(x=>x.normalized)),hi=Math.max(...points.map(x=>x.normalized));
 points.forEach(p=>{const x=node('div',`${p.end}m`);x.style.flex=String(p.distance);x.style.background=color(p.normalized,lo,hi);x.title=`${p.start}–${p.end}m ／ ${p.distance}m区間`;strip.append(x)});
 body.append(node('p','走行距離上のラップ区間（実コース図との連動ではありません）','note'),strip);
}
function renderPedigree(v,s,d,cls,going,grade){
 const bc=C.bloodClass(cls,grade),bcLabel=classLabel(bc);$('pedigreeTitle').textContent=`${v}${s}${d}m ／ ${bcLabel||'集計対象外'}`;
 $('pedigreeMeta').replaceChildren(node('span',`クラス：${bcLabel||'集計対象外'}`,'miniBadge'),node('span',`馬場：${going==='全'?'全馬場':going}`,'miniBadge'));
 if(!bc){empty('pedigreeBody','このクラスは血統集計対象外です。');return}
 const ped=bundle['pedigree_stats.json'];if(!ped.meta.source_rows){empty('pedigreeBody','データ未登録');return}
 const rec=ped.stats[[v,s,d,bc,going].join('|')];if(!rec){empty('pedigreeBody','この条件の血統データは未登録です。');return}
 const pct=(x,n=0)=>x===null?'欠損':`${x.toFixed(1)}%${n?'（欠損'+n+'）':''}`;
 const layers=[['父大系統ランキング','sire_line'],['母父大系統ランキング','damsire_line'],['父大系統 × 母父大系統ランキング','cross_major'],['個別種牡馬ランキング','stallion']];
 const grid=node('div',undefined,'pedigreeGrid');
 for(const [title,key] of layers){
  const card=node('div',undefined,'pedCard');card.append(node('div',title,'pedTitle'));const arr=rec[key]||[];
  if(!arr.length){card.append(node('div','最低出走数を満たすデータがありません。','pedigreeStatus'));grid.append(card);continue}
  const rows=arr.slice(0,7).map((r,i)=>[i+1,r.name,r.starts,pct(r.win_rate),pct(r.place_rate,r.place_missing),pct(r.win_return,r.win_payout_missing),C.confidence(r.starts)]);
  card.append(table(['順位','系統／種牡馬','出走','勝率','複勝率','単回収','信頼度'],rows));grid.append(card);
 }
 $('pedigreeBody').replaceChildren(grid,node('p','信頼度はサンプル数による目安（30走未満：低、30走以上：中、100走以上：高）で、予測精度ではありません。欠損の指標は有効件数のみで算出。最低出走数：系統10、種牡馬5。','note'));
}
function trendText(v,s,d,cls,going,grade,front,back,fastest){
 let text=`${v}${s}${d}mは、収録ラップでは${pace(front.seconds,back.seconds)}。最速区間は${fastest.start}〜${fastest.end}m（200m換算${fastest.normalized.toFixed(1)}秒）です。`;
 const bc=C.bloodClass(cls,grade),ped=bundle['pedigree_stats.json'];
 if(!ped.meta.source_rows)return text+' 血統は実データ未登録のため、ランキングは表示していません。';
 const rec=bc&&ped.stats[[v,s,d,bc,going].join('|')],top=rec?.sire_line?.[0];
 if(top)text+=` 血統では父大系統「${top.name}」が現在の集計上位です（${top.starts}走、勝率${top.win_rate.toFixed(1)}%）。`;
 else text+=' この条件では血統の最低出走数を満たす集計がありません。';
 return text;
}
function render(){
 if(!bundle)return;
 $('paneCond').hidden=mode!=='cond';$('paneGrade').hidden=mode!=='grade';
 $('tabCond').setAttribute('aria-selected',String(mode==='cond'));$('tabGrade').setAttribute('aria-selected',String(mode==='grade'));
 const k=mode==='cond'?currentKey():$('fRace').value,r=mode==='cond'?cond()[k]:grades()[k];
 if(!r){for(const id of ['readout','chart','strip','tbl','legend','courseBody','pedigreeBody','pedigreeMeta'])$(id).replaceChildren();$('note').textContent='';$('trendMemoText').textContent='この条件のデータは未登録です。';empty('readout','この条件のデータは未登録です。');return}
 const [v,s,ds,cls,going]=mode==='cond'?k.split('|'):[r.v,r.s,String(r.dist),'オープン','全'],d=+ds,raw=mode==='cond'?r.l:r.avg;
 const ss=C.segments(raw,d),front=C.section(raw,d),back=C.section(raw,d,600,true);
 const read=node('div',undefined,'readout'),top=node('div',undefined,'rTop'),grid=node('div',undefined,'rGrid');
 top.append(node('span',mode==='cond'?label(k):`${k} ${r.g}`,'rTitle'),node('span',pace(front.seconds,back.seconds),'badge'));
 const fastest=ss.reduce((a,b)=>a.normalized<=b.normalized?a:b);
 const vals=[[`前半3F${front.estimated?'（推定）':''}`,front.seconds.toFixed(1)],['上がり3F',back.seconds.toFixed(1)],['最速区間',`${fastest.start}–${fastest.end}m`],['サンプル',mode==='cond'?`${r.n}R`:`${r.yrs.length}R`]];
 if(mode==='cond')vals.push(['平均勝時計',fmt(r.w)],['最速勝時計',fmt(r.wb)],['前半−上がり',(front.seconds-back.seconds).toFixed(1)],['区間数',raw.length]);
 for(const [a,b]of vals){const x=node('div',undefined,'cell');x.append(node('div',a,'k'),node('div',b,'v'));grid.append(x)}read.append(top,grid);$('readout').replaceChildren(read);
 const series=mode==='cond'?[{raw,color:SER[0],heat:true},...overlays.filter(o=>o!==k&&cond()[o]&&+o.split('|')[2]===d).map((o,i)=>({raw:cond()[o].l,color:SER[(i+1)%SER.length],key:o}))]:[...r.yrs.map(y=>({raw:y.l,color:'#8195A8',thin:true})),{raw,color:SER[0],heat:true}];draw(series,d);
 const legend=$('legend');legend.replaceChildren();
 if(mode==='cond'){series.forEach((x,i)=>{const chip=node('span',i===0?label(k):label(x.key),'chip');if(i){const b=node('button','×');b.type='button';b.setAttribute('aria-label','比較から削除');b.addEventListener('click',()=>{overlays=overlays.filter(o=>o!==x.key);render()});chip.append(b)}legend.append(chip)})}
 else{legend.append(node('span',`${r.yrs.length}R平均`,'chip'));r.yrs.forEach(y=>legend.append(node('span',`${y.y} ${y.c} ${fmt(y.w)}`,'chip')))}
 const lo=Math.min(...ss.map(x=>x.normalized)),hi=Math.max(...ss.map(x=>x.normalized));$('strip').replaceChildren(...ss.map(p=>{const x=node('div',p.normalized.toFixed(1));x.style.flex=String(p.distance);x.style.background=color(p.normalized,lo,hi);x.title=`${p.start}–${p.end}m`;return x}));
 let total=0;const t=table(['通過(m)',...ss.map(x=>x.end)],[['ラップ(秒)',...raw.map(x=>x.toFixed(1))],['累計(秒)',...raw.map(x=>(total+=x).toFixed(1))]]);$('tbl').replaceChildren(...t.childNodes);
 $('note').textContent='前半3Fが区間境界と一致しない場合は区間内を等速として600m分を比例配分した推定値です。グラフは200m換算、横軸は実距離。比較は同距離のみ。表は収録ラップ（集計値）です。';
 renderCourse(v,s,d,raw);renderPedigree(v,s,d,cls,going,mode==='grade');
 $('trendMemoText').textContent=trendText(v,s,d,cls,going,mode==='grade',front,back,fastest);
 // 収録データの実施場を訂正したレースは、その旨を必ず出す
 if(mode==='grade'){
  const fixes=bundle['lapdata.json'].meta.audit?.grade_venue_fixes||[];
  const hit=fixes.find(x=>x.race===k);
  if(hit)$('courseBody').append(node('p',`このレースの収録競馬場を${hit.from}から${hit.to}へ訂正しています（${hit.note}）。コース図は${hit.to}のものです。`,'note'));
  const nt=(bundle['lapdata.json'].meta.audit?.grade_notes||[]).find(x=>x.race===k);
  if(nt)$('courseBody').append(node('p',nt.text,'note'),node('p','根拠：'+nt.sources.join(' ／ '),'note'));
 }
}
function init(){
 for(const id of ['fVenue','fSurf','fDist','fClass','fGoing'])$(id).addEventListener('change',()=>{refreshFilters();render()});
 $('fGradeClass').addEventListener('change',()=>{refreshGradeFilters();render()});
 $('fGradeDist').addEventListener('change',()=>{refreshGradeFilters();render()});
 $('fRace').addEventListener('change',render);
 $('tabCond').addEventListener('click',()=>{mode='cond';render()});$('tabGrade').addEventListener('click',()=>{mode='grade';refreshGradeFilters();render()});
 $('btnAdd').addEventListener('click',()=>{const k=currentKey();if(cond()[k]&&!overlays.includes(k)&&overlays.length<4)overlays.push(k);render()});
 $('btnClear').addEventListener('click',()=>{overlays=[];render()});
 document.querySelectorAll('[data-ped]').forEach(b=>b.addEventListener('click',()=>{pedigreeView=b.dataset.ped;document.querySelectorAll('[data-ped]').forEach(x=>x.classList.toggle('active',x===b));render()}));
 $('btnUpdate').addEventListener('click',()=>{update();if('serviceWorker'in navigator)navigator.serviceWorker.getRegistration().then(r=>r?.update()).catch(()=>{})});
 update(true);
 if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js',{updateViaCache:'none'}).then(r=>{
  const waiting=()=>{if(r.waiting)$('appStatus').textContent='アプリ新版の準備ができました。すべての画面を閉じ、開き直してください。'};waiting();r.addEventListener('updatefound',()=>r.installing?.addEventListener('statechange',waiting));
 }).catch(()=>{$('appStatus').textContent='オフライン起動の準備ができませんでした。'});
}
if(!globalThis.LAP_TEST_MODE)init();
