/* Shared, dependency-free validation and distance calculations. */
(function(root){
'use strict';
const APP_VERSION='3.5.5', SCHEMA=2;
const CLASSES=['新馬','未勝利','1勝','2勝','3勝','オープン'];
const FILES=['lapdata.json','courses.json','elevation.json','pedigree_stats.json'];
function assert(ok,msg){if(!ok)throw new Error(msg)}
function obj(x){return x!==null&&typeof x==='object'&&!Array.isArray(x)}
function num(x,min=0,max=Infinity){return typeof x==='number'&&Number.isFinite(x)&&x>=min&&x<=max}
function text(x){return typeof x==='string'&&x.trim().length>0&&!/[|\u0000-\u001f]/.test(x)}
function distance(d){assert(Number.isInteger(d)&&d>=600&&d<=5000&&d%50===0,'不正距離')}
function segments(laps,dist,provided){
 distance(dist);assert(Array.isArray(laps)&&laps.length===Math.ceil(dist/200),'不正ラップ配列長');
 assert(laps.every(x=>num(x,0.01,120)),'不正ラップ値');
 const ds=laps.map((_,i)=>i?200:dist-200*(laps.length-1));
 if(provided!==undefined)assert(Array.isArray(provided)&&provided.length===ds.length&&provided.every((x,i)=>x===ds[i]),'区間距離不一致');
 let end=0;return laps.map((time,i)=>({distance:ds[i],start:end,end:(end+=ds[i]),time,normalized:time*200/ds[i]}));
}
function section(laps,dist,target=600,fromEnd=false){
 let ss=segments(laps,dist);if(fromEnd)ss=ss.slice().reverse();let need=target,total=0,estimated=false;
 for(const s of ss){if(!need)break;const take=Math.min(need,s.distance);total+=s.time*take/s.distance;estimated ||= take<s.distance;need-=take}
 assert(need===0,'区間距離不足');return {seconds:total,estimated};
}
function bloodClass(c,grade=false){return grade?'オープン':CLASSES.includes(c)?c:null}
function confidence(n){return n>=100?'高':n>=30?'中':'低'}
function validateMeta(m,id){assert(obj(m)&&m.schema_version===SCHEMA&&m.dataset_id===id,'JSON世代不一致')}
function lapRecord(r,dist,avg=false){
 assert(obj(r),'ラップレコード不正');segments(avg?r.avg:r.l,dist,r.segment_distances);
 if(!avg){assert(Number.isInteger(r.n)&&r.n>0,'件数不正');for(const k of ['w','wb'])assert(r[k]===null||num(r[k],0.01),'勝時計不正')}
}
function validateBundle(b){
 assert(obj(b)&&obj(b.version),'版情報なし');const v=b.version;
 assert(v.schema_version===SCHEMA&&v.app_version===APP_VERSION,'アプリ本体の更新が必要です');
 assert(text(v.dataset_id)&&typeof v.updated_at==='string'&&Number.isFinite(Date.parse(v.updated_at)),'版情報不正');
 assert(obj(v.files)&&FILES.every(f=>/^[a-f0-9]{64}$/.test(v.files[f])),'ファイルハッシュ不正');
 for(const f of FILES){assert(obj(b[f]),f+' がありません');validateMeta(b[f].meta,v.dataset_id)}
 const lap=b['lapdata.json'];assert(obj(lap.cond)&&obj(lap.grade),'ラップ必須キーなし');
 for(const [k,r] of Object.entries(lap.cond)){
  const p=k.split('|');assert(p.length===5&&p.every(text)&&['芝','ダート'].includes(p[1])&&[...CLASSES,'その他'].includes(p[3])&&['良','道悪','全'].includes(p[4]),'条件キー不正');lapRecord(r,Number(p[2]));
 }
 for(const [k,r] of Object.entries(lap.grade)){
  assert(text(k)&&obj(r)&&text(r.v)&&['芝','ダート'].includes(r.s)&&text(r.g),'重賞キー不正');lapRecord(r,r.dist,true);
  assert(Array.isArray(r.yrs)&&r.yrs.length>0,'重賞年次なし');
  for(const y of r.yrs){assert(obj(y)&&text(y.y)&&text(y.d)&&text(y.c)&&num(y.w,0.01),'重賞年次不正');segments(y.l,r.dist,y.segment_distances)}
 }
 assert(Number.isInteger(lap.meta.races)&&lap.meta.races>=0&&lap.meta.races===Object.values(lap.cond).reduce((n,r)=>n+r.n,0),'収録件数不一致');
 for(const k of ['from','to'])assert(lap.meta[k]===null||(typeof lap.meta[k]==='string'&&Number.isFinite(Date.parse(lap.meta[k]))),'収録期間不正');
 assert(obj(b['courses.json'].courses),'コース必須キーなし');
 for(const [k,c] of Object.entries(b['courses.json'].courses)){
  assert(text(k.replaceAll('|','/'))&&obj(c)&&['右回り','左回り','直線',null].includes(c.turn),'コース不正');
  const kp=k.split('|');assert((kp.length===2||kp.length===3)&&kp.every(text),'コースキー不正');
  if(kp.length===3)distance(Number(kp[2]));
  for(const f of ['straight_m','height_diff_m'])assert(c[f]===null||num(c[f])||text(c[f]),'コース数値不正');
  assert(Array.isArray(c.notes)&&c.notes.every(x=>typeof x==='string'),'コース注記不正');
  assert(c.route_unavailable_reason===undefined||text(c.route_unavailable_reason),'コース図未対応理由不正');
  for(const f of ['source_url','route_source_url'])assert(c[f]===undefined||c[f]===null||(typeof c[f]==='string'&&c[f].startsWith('https://www.jra.go.jp/')),'コース出典不正');
  // A route is only accepted when every anchor carries a distance, a role and a stated basis.
  const checkRoute=r=>{
   assert(obj(r)&&text(r.mode)&&text(r.precision_note)&&Number.isInteger(r.distance_m)&&Array.isArray(r.anchors)&&r.anchors.length>=2,'コース経路不正');
   assert(kp.length===3&&r.distance_m===Number(kp[2]),'経路距離不一致');
   let prev=-1;const roles=new Set();
   for(const a of r.anchors){
    assert(obj(a)&&num(a.m,0,r.distance_m)&&a.m>prev&&text(a.label)&&text(a.basis)&&text(a.role),'経路アンカー不正');
    assert(!roles.has(a.role),'経路ロール重複');roles.add(a.role);prev=a.m;
   }
   assert(r.anchors[0].m===0&&r.anchors.at(-1).m===r.distance_m,'経路アンカー端点不正');
   // Display wording lives in the data so app.js carries no per-distance text.
   if(r.display!==undefined){
    assert(obj(r.display),'経路表示文不正');
    for(const [f,val] of Object.entries(r.display))assert(['anchor_fact','hill_fact','precision_fact','note','source_label','route_source_label'].includes(f)&&text(val),'経路表示文不正');
   }
   // Each mode states exactly which anchors it can prove. Nothing is inferred for the others.
   assert(['distance-anchored-schematic','loop-schematic','straight-course'].includes(r.mode),'経路モード不正');
   const at=role=>r.anchors.find(a=>a.role===role).m;
   const need=r.mode==='straight-course'?['start','goal']:r.mode==='loop-schematic'?['start','straight_entry','goal']:['start','first_corner','straight_entry','goal'];
   for(const role of need)assert(roles.has(role),'経路ロール不足');
   assert(at('start')===0,'経路スタート位置不正');
   if(r.mode==='distance-anchored-schematic')assert(at('start')<at('first_corner')&&at('first_corner')<at('straight_entry')&&at('straight_entry')<at('goal'),'経路アンカー順序不正');
   if(r.mode==='loop-schematic'){
    assert(num(r.lap_m,1)&&num(r.straight_m,1)&&at('straight_entry')<at('goal'),'ループ経路不正');
    assert(Math.abs(r.distance_m-at('straight_entry')-r.straight_m)<0.05,'直線入口が直線距離と不一致');
    if(roles.has('first_corner'))assert(at('first_corner')<at('straight_entry'),'経路アンカー順序不正');
   }
   if(r.mode==='straight-course')assert(r.anchors.length===2&&r.lap_m===undefined,'直線経路不正');
   // A route that hides an unconfirmed anchor behind a drawn shape must say so in the data.
   if(r.mode!=='distance-anchored-schematic'){
    assert(Array.isArray(r.unconfirmed)&&r.unconfirmed.length>0&&r.unconfirmed.every(text),'未確定項目の明示なし');
   }
  };
  if(c.route!==undefined)checkRoute(c.route);
  // Where the official inner/outer assignment cannot be confirmed, both cases are published
  // side by side. Each case must be a complete, self-labelled route.
  if(c.route_variants!==undefined){
   assert(Array.isArray(c.route_variants)&&c.route_variants.length>=2&&c.route===undefined,'経路バリアント不正');
   const labels=new Set();
   for(const r of c.route_variants){
    assert(obj(r)&&text(r.variant_label)&&!labels.has(r.variant_label),'経路バリアント名不正');
    labels.add(r.variant_label);checkRoute(r);
    assert(r.unconfirmed.includes('inner_or_outer_course'),'内外未確定の明示なし');
   }
   assert(text(c.route_unavailable_reason),'内外未確定の理由文なし');
  }
 }
 // Elevation profiles must be explicit about what is measured, derived or qualitative.
 const elev=b['elevation.json'];assert(obj(elev.profiles),'起伏必須キーなし');
 for(const [k,p] of Object.entries(elev.profiles)){
  const a=k.split('|');assert(a.length===3&&a.every(text)&&['芝','ダート'].includes(a[1]),'起伏キー不正');distance(Number(a[2]));
  assert(obj(p)&&p.distance_m===Number(a[2])&&Array.isArray(p.numeric_segments)&&Array.isArray(p.qualitative),'起伏プロファイル不正');
  for(const q of p.qualitative)assert(obj(q)&&text(q.label)&&text(q.position)&&text(q.precision),'起伏注記不正');
  for(const seg of p.numeric_segments){assert(obj(seg)&&num(seg.from_m,0,p.distance_m)&&num(seg.to_m,0,p.distance_m)&&seg.to_m>seg.from_m&&text(seg.type)&&text(seg.label)&&text(seg.precision),'起伏区間不正');if(seg.rise_m!==undefined)assert(num(seg.rise_m,0,20),'起伏高低差不正')}
 }
 const ped=b['pedigree_stats.json'];assert(obj(ped.stats)&&Number.isInteger(ped.meta.source_rows)&&ped.meta.source_rows>=0,'血統必須キー不正');
 if(ped.meta.source_rows===0)assert(Object.keys(ped.stats).length===0,'0件の血統ランキング');
 for(const [k,r] of Object.entries(ped.stats)){
  const p=k.split('|');assert(p.length===5&&p.every(text)&&['芝','ダート'].includes(p[1])&&CLASSES.includes(p[3])&&['良','道悪','全'].includes(p[4]),'血統条件不正');distance(Number(p[2]));
  assert(obj(r)&&Number.isInteger(r.n)&&r.n>0,'血統件数不正');
  for(const layer of ['sire_line','damsire_line','cross_major','stallion']){
   assert(Array.isArray(r[layer]),'血統4層不足');
   for(const x of r[layer]){
    assert(obj(x)&&text(x.name)&&Number.isInteger(x.starts)&&x.starts>0&&x.starts<=r.n,'血統名称/出走数不正');
    for(const m of ['win_rate','top2_rate','place_rate','win_return','place_return'])assert(x[m]===null||num(x[m],0,m.endsWith('rate')?100:Infinity),'血統指標不正');
    for(const m of ['place_missing','win_payout_missing','place_payout_missing'])assert(Number.isInteger(x[m])&&x[m]>=0&&x[m]<=x.starts,'欠損件数不正');
   }
  }
 }
 return b;
}
function resolveCourse(db,venue,surface,dist){
 const c=db[`${venue}|${surface}|${dist}`]||db[`${venue}|${surface}`];if(!c)return null;
 const out={...c};out.variant=c.distance_variants?.[String(dist)]??c.variant??'区分未確認';
 if(venue==='新潟'&&surface==='芝'&&dist===1000){out.turn='直線';out.variant='直線';out.straight_m=null;out.height_diff_m=null;out.notes=['直線1000mコース。内・外回りの直線距離・起伏は適用しません。']}
 return out;
}
const api={APP_VERSION,SCHEMA,CLASSES,FILES,assert,segments,section,bloodClass,confidence,validateBundle,resolveCourse};
if(typeof module!=='undefined')module.exports=api;root.LapCore=api;
})(typeof globalThis==='undefined'?this:globalThis);
