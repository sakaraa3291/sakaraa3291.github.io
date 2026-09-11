'use strict';
const C=globalThis.LapCore;
const APP_VERSION='3.2.0';
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
function renderCourse(v,s,d,laps){
 $('courseTitle').textContent=`${v}${s}${d}m`;const body=$('courseBody');body.replaceChildren();
 const c=C.resolveCourse(bundle['courses.json'].courses,v,s,d);
 if(!c){empty('courseBody','コース情報・実位置連動は未対応です。');return}
 const facts=node('div',undefined,'courseFacts');
 const entries=[['回り・区分',`${c.turn||'未確認'} ／ ${c.variant}`],['直線距離',c.straight_m===null?'未確認':typeof c.straight_m==='number'?`${c.straight_m}m`:c.straight_m],['高低差',c.height_diff_m===null?'未確認':typeof c.height_diff_m==='number'?`${c.height_diff_m}m`:c.height_diff_m]];
 for(const [k,val]of entries){const f=node('div',undefined,'fact');f.append(node('div',k,'fk'),node('div',val,'fv'));facts.append(f)}
 body.append(facts);
 body.append(node('p','実コース位置・起伏連動：未対応。発走地点と距離別断面の根拠が揃うまで、推測の図や高低差は表示しません。','note'));
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
