'use strict';
const C=globalThis.LapCore;
const APP_VERSION='3.7.0';
const $=id=>document.getElementById(id);
let bundle=null, mode='cond', pedigreeView='sire', overlays=[], busy=false;
const SER=['#FFB13B','#5BC08A','#4A9BD8','#D9945A','#C58CE0'];
const VORDER=['札幌','函館','福島','新潟','東京','中山','中京','京都','阪神','小倉','大井','船橋','川崎','浦和'];
const SORT=(a,list)=>{const i=list.indexOf(a);return i<0?99:i};
function node(tag,txt,cls){const n=document.createElement(tag);if(txt!==undefined)n.textContent=String(txt);if(cls)n.className=cls;return n}
function svg(tag,attrs,txt){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [k,v]of Object.entries(attrs||{}))n.setAttribute(k,String(v));if(txt!==undefined)n.textContent=String(txt);return n}
function empty(id,msg){$(id).replaceChildren(node('div',msg,'pedigreeStatus'))}
function state(label,detail=''){ $('dataStatus').textContent=label+(detail?' ／ '+detail:'');$('dataStatus').dataset.state=label; }
function summary(){if(!bundle)return '';const m=bundle['lapdata.json'].meta;return `更新 ${bundle.version.updated_at} ／ ラップ ${m.races.toLocaleString()}R ／ 血統 ${bundle['pedigree_stats.json'].meta.source_rows.toLocaleString()}走`}
function currentKey(){return ['fVenue','fSurf','fDist','fClass','fGoing'].map(id=>$(id).value).join('|')}
function cond(){return bundle?.['lapdata.json'].cond||{}}
function grades(){return bundle?.['lapdata.json'].grade||{}}
function fill(id,items,desired){const s=$(id),keep=desired??s.value;s.replaceChildren(...items.map(v=>{const o=node('option',v.label??v);o.value=String(v.value??v);return o}));s.value=items.some(v=>String(v.value??v)===keep)?keep:(items[0]?.value??items[0]??'')}
function refreshFilters(){
 let rs=Object.keys(cond()).map(k=>k.split('|'));
 const ids=['fVenue','fSurf','fDist','fClass','fGoing'];
 ids.forEach((id,i)=>{const values=[...new Set(rs.map(r=>r[i]))].sort(i===0?(a,b)=>SORT(a,VORDER)-SORT(b,VORDER):i===2?(a,b)=>+a-+b:i===3?(a,b)=>SORT(a,C.CLASSES)-SORT(b,C.CLASSES):undefined);fill(id,values);rs=rs.filter(r=>r[i]===$(id).value)});
 const d=+$('fDist').value;overlays=overlays.filter(k=>cond()[k]&&+k.split('|')[2]===d);
}
function rebuild(){
 refreshFilters();
 fill('fRace',Object.keys(grades()).sort((a,b)=>a.localeCompare(b,'ja')).map(k=>({value:k,label:`${grades()[k].g}｜${k}（${grades()[k].v}${grades()[k].s}${grades()[k].dist}）`})));
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
function label(k){const [v,s,d,c,g]=k.split('|');return `${v}${s}${d}m ${c} ${g}`}
function color(t,lo,hi){return `hsl(${8+(t-lo)/((hi-lo)||1)*205},72%,55%)`}
function pace(a,b){const d=a-b;return d<=-1?'ハイペース':d<=-.3?'やや前傾':d<.4?'ミドル':d<1.2?'やや後傾':'スローペース'}
function table(headers,rows){const t=node('table'),head=node('tr');headers.forEach(x=>head.append(node('th',x)));t.append(head);for(const row of rows){const tr=node('tr');row.forEach(x=>tr.append(node('td',x)));t.append(tr)}return t}
function draw(series,dist){
 const chart=$('chart');chart.replaceChildren();const all=series.flatMap(s=>C.segments(s.raw,dist).map(x=>x.normalized));
 const min=Math.min(...all),max=Math.max(...all),pad=(max-min)*.18||.6,lo=min-pad,hi=max+pad;
 const X=d=>44+(700-44-14)*d/dist,Y=v=>16+(340-16-42)*(1-(v-lo)/(hi-lo));
 const step=hi-lo>6?2:hi-lo>3?1:.5;
 for(let t=Math.ceil(lo/step)*step;t<=hi;t+=step){chart.append(svg('line',{x1:44,x2:686,y1:Y(t),y2:Y(t),stroke:'#27384A'}),svg('text',{x:37,y:Y(t)+4,fill:'#8195A8','font-size':11,'text-anchor':'end'},t.toFixed(1)))}
 const ss=C.segments(series[0].raw,dist),stride=ss.length>10?2:1;
 chart.append(svg('text',{x:X(0),y:318,fill:'#8195A8','font-size':10,'text-anchor':'middle'},'0'));
 ss.forEach((s,i)=>{if(i%stride===0||i===ss.length-1)chart.append(svg('text',{x:X(s.end),y:318,fill:'#8195A8','font-size':10,'text-anchor':'middle'},s.end))});
 chart.append(svg('text',{x:350,y:334,fill:'#8195A8','font-size':11,'text-anchor':'middle'},'通過距離 (m)'));
 series.forEach((s,i)=>{const seg=C.segments(s.raw,dist),c=s.color||SER[i%SER.length];chart.append(svg('polyline',{points:seg.map(p=>`${X(p.end)},${Y(p.normalized)}`).join(' '),fill:'none',stroke:c,'stroke-width':s.thin?1.4:2.8,'stroke-opacity':s.thin?.45:1}));if(!s.thin)seg.forEach(p=>{const dot=svg('circle',{cx:X(p.end),cy:Y(p.normalized),r:3.4,fill:c});dot.append(svg('title',{},`${p.start}–${p.end}m ／ ${p.normalized.toFixed(1)}秒（200m換算）`));chart.append(dot)})});
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
function elevationSeries(prof,d){
 const sh=prof&&prof.shape;if(!sh||!Array.isArray(sh.segments)||!sh.segments.length)return null;
 const list=[];
 for(const sg of sh.segments){
  const a=Math.max(0,d-sg.to_rem),b=Math.min(d,d-sg.from_rem);
  if(b-a<=0.5)continue;
  list.push({a,b,dir:sg.dir,rise:sg.rise_m||0,numeric:sg.precision==='numeric'});
 }
 if(!list.length)return null;
 list.sort((x,y)=>x.a-y.a);
 let e=0;const pts=[[list[0].a,0]];
 for(const sg of list){
  if(pts[pts.length-1][0]<sg.a-0.5)pts.push([sg.a,e]);
  e+=sg.dir==='up'?sg.rise:sg.dir==='down'?-sg.rise:0;
  pts.push([sg.b,e]);
 }
 const lo=Math.min(...pts.map(p=>p[1])),hi=Math.max(...pts.map(p=>p[1]));
 return {pts:pts.map(p=>[p[0],p[1]-lo]),segs:list,range:hi-lo,
  estimated:sh.has_estimated_heights,sources:sh.sources};
}
function profilePanel(prof,route,d,label){
 const W=580,H=176,L=52,RG=16,TOPY=34,BASE=104;
 const el=svg('svg',{viewBox:`0 0 ${W} ${H}`,class:'profileSvg',role:'img','aria-label':label});
 const X=m=>L+(W-L-RG)*m/d;
 // 出典の記述から標高列を作る。無ければ数値区間だけで作る。
 const series=elevationSeries(prof,d);
 let pts,shaped;
 if(series){pts=series.pts;shaped=true;}
 else{
  pts=[[0,0]];let e2=0;
  for(const sg of prof.numeric_segments){
   if(sg.type==='uphill'&&typeof sg.rise_m==='number'){pts.push([sg.from_m,e2]);e2+=sg.rise_m;pts.push([sg.to_m,e2]);}
  }
  pts.push([d,e2]);shaped=pts.length>3;
 }
 const top=Math.max(...pts.map(q=>q[1]),1);
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
    '数値の無い区間の高さは合計からの按分（模式）です。'));
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
 const geo=loop?loopGeometry(route,typeof route.straight_m==='number'?route.straight_m:(typeof c.straight_m==='number'?c.straight_m:0)):straightGeometry(route);
 if(!geo)return false;
 const T=route.display||{};
 const grid=node('div',undefined,'courseGrid'),left=node('div'),right=node('div',undefined,'courseFacts');
 const map=svg('svg',{viewBox:loop?'0 0 580 270':'0 0 580 120',class:'courseSvg',role:'img','aria-label':`${v}${s}${d}m 模式コース図（コーナー位置は未確定）`});
 map.append(svg('path',{d:geo.loopPath,fill:'none',stroke:'#22432f','stroke-width':22,'stroke-linecap':'round'}));
 // 走行区間（ゴールから距離分だけ遡った範囲）を本線色で重ねる
 const runLen=Math.min(geo.d,geo.lap)*geo.k;
 map.append(svg('path',{d:geo.loopPath,fill:'none',stroke:'#2d5c3f','stroke-width':22,'stroke-linecap':'butt','stroke-dasharray':`${runLen.toFixed(3)} ${(geo.total-runLen).toFixed(3)}`}));
 // ラップ色。位置は距離そのものなので、図の形が模式でも色の境目は正しい。
 const ss=C.segments(laps,d),lo=Math.min(...ss.map(x=>x.normalized)),hi=Math.max(...ss.map(x=>x.normalized));
 ss.forEach(seg=>{
  const a=Math.max(d-seg.start-seg.distance,0),b=Math.min(d-seg.start,geo.lap);
  if(!(b>a))return;
  map.append(svg('path',{d:geo.loopPath,fill:'none',stroke:color(seg.normalized,lo,hi),'stroke-width':12,'stroke-linecap':'butt','stroke-dasharray':`${((b-a)*geo.k).toFixed(3)} ${(geo.total-(b-a)*geo.k).toFixed(3)}`,'stroke-dashoffset':(-a*geo.k).toFixed(3)}));
 });
 // コーナーは公式非公表なので、模式であることを破線で示す
 for(const arc of geo.cornerArcs)map.append(svg('path',{d:arc,fill:'none',stroke:'#8195A8','stroke-width':2,'stroke-dasharray':'6 6',opacity:0.9}));
 // 距離マーカー（1mあたりの長さが一定なので、位置は距離として正しい）
 const mstep=d<=1200?200:d<=2400?400:600;
 const anchorPts=route.anchors.map(a=>{const r0=d-a.m;return geo.at(loop?((r0%geo.lap)+geo.lap)%geo.lap:r0)});
 for(let m=mstep;m<d;m+=mstep){
  const rem=d-m,pt=geo.at(loop?((rem%geo.lap)+geo.lap)%geo.lap:rem);
  // アンカーのラベルと重なる位置の距離マーカーは出さない
  if(anchorPts.some(q=>Math.hypot(q.x-pt.x,q.y-pt.y)<30))continue;
  const off=pt.zone==='back'?[0,-13]:pt.zone==='corner-late'?[-15,0]:pt.zone==='corner-early'?[15,0]:[0,15];
  map.append(svg('circle',{class:'kmDot',cx:pt.x.toFixed(2),cy:pt.y.toFixed(2),r:2.6,fill:'#E9EFF5',opacity:0.85}),
   svg('text',{x:(pt.x+off[0]).toFixed(2),y:(pt.y+off[1]+3).toFixed(2),fill:'#9fb2c4','font-size':9,
    'text-anchor':off[0]<0?'end':off[0]>0?'start':'middle'},`${m}m`));
 }
 const placed=[];
 for(const a of route.anchors){
  const sRem=d-a.m,pt=geo.at(loop?((sRem%geo.lap)+geo.lap)%geo.lap:sRem),isStart=a.m===0,isGoal=a.m===d;
  // 向正面のラベルは楕円の内側へ置く（上の「向正面」キャプションと重ならないように）
  const down=pt.zone==='back'||pt.y>140;
  let dy=pt.zone==='back'?24:down?28:-18;const dx=isStart?0:isGoal?10:0;
  const lx=Math.max(44,Math.min(536,pt.x+dx));
  // 近すぎるラベルは段をずらす（重なって読めなくなるのを防ぐ）
  while(placed.some(q=>Math.abs(q[0]-lx)<56&&Math.abs(q[1]-(pt.y+dy))<17))dy+=down?26:-26;
  placed.push([lx,pt.y+dy]);
  map.append(svg('circle',{class:'anchorDot',cx:pt.x.toFixed(2),cy:pt.y.toFixed(2),r:5,fill:'#0E161F',stroke:'#E9EFF5','stroke-width':2}),
   svg('text',{x:lx.toFixed(2),y:(pt.y+dy).toFixed(2),fill:'#E9EFF5','font-size':12,'font-weight':700,'text-anchor':'middle'},a.label),
   svg('text',{x:lx.toFixed(2),y:(pt.y+dy+(dy>0?14:-13)).toFixed(2),fill:'#8195A8','font-size':9,'text-anchor':'middle'},`${Math.round(a.m)}m`));
 }
 if(loop){
  map.append(svg('text',{x:(geo.LX+geo.RX)/2,y:geo.TOP-24,fill:'#8195A8','font-size':10,'text-anchor':'middle'},'向正面（長さは模式）'),
   svg('text',{x:(geo.LX+geo.goalX)/2,y:geo.BOT+46,fill:'#8195A8','font-size':10,'text-anchor':'middle'},'ホームストレッチ'),
   svg('text',{x:geo.LX+14,y:geo.CY-2,fill:'#8195A8','font-size':9,'text-anchor':'start'},'コーナー'),
   svg('text',{x:geo.LX+14,y:geo.CY+10,fill:'#8195A8','font-size':9,'text-anchor':'start'},'位置未確定'));
  if(geo.laps>1)map.append(svg('text',{x:572,y:24,fill:'#FF9A82','font-size':10,'text-anchor':'end'},'1周超（色は最終1周分）'));
 }else{
  map.append(svg('text',{x:290,y:26,fill:'#8195A8','font-size':10,'text-anchor':'middle'},'直線コース（コーナーなし）'));
 }
 left.append(map);
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
 const bc=C.bloodClass(cls,grade);$('pedigreeTitle').textContent=`${v}${s}${d}m ／ ${bc||'集計対象外'}`;
 $('pedigreeMeta').replaceChildren(node('span',`クラス：${bc||'集計対象外'}`,'miniBadge'),node('span',`馬場：${going==='全'?'全馬場':going}`,'miniBadge'));
 if(!bc){empty('pedigreeBody','このクラスは血統集計対象外です。');return}
 const ped=bundle['pedigree_stats.json'];if(!ped.meta.source_rows){empty('pedigreeBody','データ未登録');return}
 // Never substitute all-going statistics under a selected-going label.
 const rec=ped.stats[[v,s,d,bc,going].join('|')];if(!rec){empty('pedigreeBody','この条件の血統データは未登録です。');return}
 const layer={sire:'sire_line',damsire:'damsire_line',cross:'cross_major',stallion:'stallion'}[pedigreeView],arr=rec[layer];
 if(!arr.length){empty('pedigreeBody','最低出走数を満たすデータがありません。');return}
 const pct=(x,n=0)=>x===null?'欠損':`${x.toFixed(1)}%${n?'（欠損'+n+'）':''}`;
 const rows=arr.slice(0,10).map(r=>[r.name,r.starts,pct(r.win_rate),pct(r.top2_rate),pct(r.place_rate,r.place_missing),pct(r.win_return,r.win_payout_missing),pct(r.place_return,r.place_payout_missing),C.confidence(r.starts)]);
 const wrap=node('div',undefined,'tblWrap');wrap.append(table(['系統／種牡馬','出走数','勝率','連対率','複勝率','単勝回収率','複勝回収率','信頼度'],rows));
 $('pedigreeBody').replaceChildren(wrap,node('p','信頼度はサンプル数による目安（30走未満：低、30走以上：中、100走以上：高）で、予測精度ではありません。欠損の指標は有効件数のみで算出。最低出走数：系統10、種牡馬5。','note'));
}
function render(){
 if(!bundle)return;
 $('paneCond').hidden=mode!=='cond';$('paneGrade').hidden=mode!=='grade';
 $('tabCond').setAttribute('aria-selected',String(mode==='cond'));$('tabGrade').setAttribute('aria-selected',String(mode==='grade'));
 const k=mode==='cond'?currentKey():$('fRace').value,r=mode==='cond'?cond()[k]:grades()[k];
 if(!r){for(const id of ['readout','chart','strip','tbl','legend','courseBody','pedigreeBody','pedigreeMeta'])$(id).replaceChildren();$('note').textContent='';empty('readout','この条件のデータは未登録です。');return}
 const [v,s,ds,cls,going]=mode==='cond'?k.split('|'):[r.v,r.s,String(r.dist),'オープン','全'],d=+ds,raw=mode==='cond'?r.l:r.avg;
 const ss=C.segments(raw,d),front=C.section(raw,d),back=C.section(raw,d,600,true);
 const read=node('div',undefined,'readout'),top=node('div',undefined,'rTop'),grid=node('div',undefined,'rGrid');
 top.append(node('span',mode==='cond'?label(k):`${k} ${r.g}`,'rTitle'),node('span',pace(front.seconds,back.seconds),'badge'));
 const fastest=ss.reduce((a,b)=>a.normalized<=b.normalized?a:b);
 const vals=[[`前半3F${front.estimated?'（推定）':''}`,front.seconds.toFixed(1)],['上がり3F',back.seconds.toFixed(1)],['最速区間',`${fastest.start}–${fastest.end}m`],['サンプル',mode==='cond'?`${r.n}R`:`${r.yrs.length}R`]];
 if(mode==='cond')vals.push(['平均勝時計',fmt(r.w)],['最速勝時計',fmt(r.wb)],['前半−上がり',(front.seconds-back.seconds).toFixed(1)],['区間数',raw.length]);
 for(const [a,b]of vals){const x=node('div',undefined,'cell');x.append(node('div',a,'k'),node('div',b,'v'));grid.append(x)}read.append(top,grid);$('readout').replaceChildren(read);
 const series=mode==='cond'?[{raw,color:SER[0]},...overlays.filter(o=>o!==k&&cond()[o]&&+o.split('|')[2]===d).map((o,i)=>({raw:cond()[o].l,color:SER[(i+1)%SER.length],key:o}))]:[...r.yrs.map(y=>({raw:y.l,color:'#8195A8',thin:true})),{raw,color:SER[0]}];draw(series,d);
 const legend=$('legend');legend.replaceChildren();
 if(mode==='cond'){series.forEach((x,i)=>{const chip=node('span',i===0?label(k):label(x.key),'chip');if(i){const b=node('button','×');b.type='button';b.setAttribute('aria-label','比較から削除');b.addEventListener('click',()=>{overlays=overlays.filter(o=>o!==x.key);render()});chip.append(b)}legend.append(chip)})}
 else{legend.append(node('span',`${r.yrs.length}R平均`,'chip'));r.yrs.forEach(y=>legend.append(node('span',`${y.y} ${y.c} ${fmt(y.w)}`,'chip')))}
 const lo=Math.min(...ss.map(x=>x.normalized)),hi=Math.max(...ss.map(x=>x.normalized));$('strip').replaceChildren(...ss.map(p=>{const x=node('div',p.normalized.toFixed(1));x.style.flex=String(p.distance);x.style.background=color(p.normalized,lo,hi);x.title=`${p.start}–${p.end}m`;return x}));
 let total=0;const t=table(['通過(m)',...ss.map(x=>x.end)],[['ラップ(秒)',...raw.map(x=>x.toFixed(1))],['累計(秒)',...raw.map(x=>(total+=x).toFixed(1))]]);$('tbl').replaceChildren(...t.childNodes);
 $('note').textContent='前半3Fが区間境界と一致しない場合は区間内を等速として600m分を比例配分した推定値です。グラフは200m換算、横軸は実距離。比較は同距離のみ。表は収録ラップ（集計値）です。';
 renderCourse(v,s,d,raw);renderPedigree(v,s,d,cls,going,mode==='grade');
}
function init(){
 for(const id of ['fVenue','fSurf','fDist','fClass','fGoing'])$(id).addEventListener('change',()=>{refreshFilters();render()});
 $('fRace').addEventListener('change',render);
 $('tabCond').addEventListener('click',()=>{mode='cond';render()});$('tabGrade').addEventListener('click',()=>{mode='grade';render()});
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
