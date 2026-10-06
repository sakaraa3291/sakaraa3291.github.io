const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('fs');
const vm=require('vm');
const C=require('./core.js');

class E{
 constructor(tag){this.tag=tag;this.children=[];this.attrs={}}
 append(...x){this.children.push(...x)}
 setAttribute(k,v){this.attrs[k]=v}
}
const ctx={LAP_TEST_MODE:true,LapCore:C,document:{createElement:t=>new E(t),createElementNS:(_,t)=>new E(t)}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(__dirname+'/app.js','utf8'),ctx);
const bundle={version:JSON.parse(fs.readFileSync(__dirname+'/data-version.json'))};
for(const f of C.FILES)bundle[f]=JSON.parse(fs.readFileSync(__dirname+'/'+f));
ctx.b=bundle;vm.runInContext('bundle=b',ctx);

function series(key,variant){
 const c=bundle['courses.json'].courses[key];
 const route=(c.route_variants||[c.route]).find(x=>!variant||x.variant_label===variant);
 ctx.p=bundle['elevation.json'].profiles[key];ctx.r=route;ctx.d=Number(key.split('|')[2]);
 return {
  base:vm.runInContext('resolvedElevationLap(p,r)',ctx),
  series:vm.runInContext('elevationSeries(p,r,d)',ctx),
  route
 };
}

test('all 133 route variants have finite elevation profiles',()=>{
 let count=0;
 for(const [key,c] of Object.entries(bundle['courses.json'].courses)){
  if(key.split('|').length!==3)continue;
  const d=Number(key.split('|')[2]),prof=bundle['elevation.json'].profiles[key];
  for(const route of c.route_variants||[c.route]){
   if(!route)continue;count++;
   if(route.mode==='straight-course')continue;
   ctx.p=prof;ctx.r=route;ctx.d=d;
   const base=vm.runInContext('resolvedElevationLap(p,r)',ctx);
   const s=vm.runInContext('elevationSeries(p,r,d)',ctx);
   assert.ok(base&&s,key);
   assert.equal(s.pts[0][0],0,key);
   assert.ok(Math.abs(s.pts.at(-1)[0]-d)<0.01,key);
   assert.ok(s.pts.every(p=>Number.isFinite(p[0])&&Number.isFinite(p[1])),key);
   for(const part of base.parts){
    if(part.dir==='up'||part.dir==='down')assert.ok(part.delta>0,key+' '+part.dir);
   }
   if(base.estimated&&base.target>0&&s.range>0)assert.ok(Math.abs(s.range-base.target)<0.01,key);
  }
 }
 assert.equal(count,133);
});

test('Kyoto turf 2000 inner climbs then descends into the straight',()=>{
 const x=series('京都|芝|2000','内回り');
 const up=x.series.segs.find(s=>s.dir==='up'&&s.rise>0);
 const down=x.series.segs.find(s=>s.dir==='down'&&s.rise>0);
 assert.ok(up&&down);
 assert.ok(up.a<down.a);
 assert.ok(Math.abs(down.b-x.route.anchors.find(a=>a.role==='straight_entry').m)<1);
 assert.ok(Math.abs(x.series.range-3.1)<0.01);
});

test('inner/outer elevation templates use each route high difference',()=>{
 for(const [key,inner,outer] of [
  ['京都|芝|2000',3.1,4.3],
  ['阪神|芝|1400',1.9,2.4],
  ['新潟|芝|1400',0.8,2.2]
 ]){
  assert.ok(Math.abs(series(key,'内回り').series.range-inner)<0.01,key+' inner');
  assert.ok(Math.abs(series(key,'外回り').series.range-outer)<0.01,key+' outer');
 }
});
