// Run: node --test v380-test/morphology.test.cjs
const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const crypto=require('node:crypto');
const C=require('./core.js');
const read=f=>JSON.parse(fs.readFileSync(path.join(__dirname,f)));
const bundle={version:read('data-version.json')};
for(const f of C.FILES)bundle[f]=read(f);
class Element{
 constructor(tag){this.tag=tag;this.children=[];this.attrs={}}
 append(...children){this.children.push(...children)}
 setAttribute(k,v){this.attrs[k]=v}
}
const context={LAP_TEST_MODE:true,LapCore:C,document:{createElement:t=>new Element(t),createElementNS:(_,t)=>new Element(t)}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'app.js'),'utf8'),context);
context.testBundle=bundle;
vm.runInContext('bundle=testBundle',context);
const courses=bundle['courses.json'].courses;
const geometry=r=>{context.testRoute=r;return vm.runInContext('courseMorphology(testRoute)',context)};
const paths=s=>s.loopPath.match(/[-+]?\d*\.?\d+(?:e[-+]?\d+)?/gi).map(Number).reduce((out,n,i,a)=>{if(i%2===0)out.push({x:n,y:a[i+1]});return out},[]);
const length=pts=>pts.slice(1).reduce((sum,p,i)=>sum+Math.hypot(p.x-pts[i].x,p.y-pts[i].y),0);
test('four-JSON bundle, manifest hashes and version',()=>{
 C.validateBundle(bundle);
 assert.equal(bundle.version.app_version,'3.8.0');
 assert.equal(bundle.version.dataset_id,'fbeec520667fb2bf4794407b');
 assert.equal(bundle['courses.json'].meta.checked_at,'2026-10-06');
 for(const f of C.FILES)assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(__dirname,f))).digest('hex'),bundle.version.files[f]);
});
test('official distance variants including both choices and outer→inner',()=>{
 for(const [key,id] of Object.entries({'阪神|芝|2000':'hanshin-inner','阪神|芝|1600':'hanshin-outer','中山|芝|2500':'nakayama-inner','中山|芝|2600':'nakayama-outer','中山|芝|4000':'nakayama-outer','新潟|芝|1600':'niigata-outer','東京|芝|1600':'tokyo-turf'}))assert.equal(courses[key].route.shape_id,id);
 for(const key of ['京都|芝|1400','京都|芝|1600','京都|芝|2000','阪神|芝|1400','新潟|芝|1400','新潟|芝|2000'])assert.deepEqual(courses[key].route_variants.map(r=>r.variant_label),['内回り','外回り']);
 for(const v of ['中山','阪神']){const c=courses[v+'|芝|3200'];assert.equal(c.variant,'外→内');assert.equal(c.route_variants,undefined);assert.equal(c.route.sequence.length,2);assert.ok(c.route.shape_id.endsWith('-inner'))}
 assert.equal(courses['新潟|芝|1000'].route.mode,'straight-course');
});
test('all 127 JRA distance routes render; 24 distinct loops stay in view',()=>{
 const shapes=new Map();let count=0;
 for(const [key,c] of Object.entries(courses)){
  if(key.split('|').length!==3)continue;
  const [v,s,dist]=key.split('|'),d=Number(dist);
  const routes=c.route_variants||[c.route];
  for(const r of routes){
   assert.ok(r,`${key}: missing route`);count++;
   if(r.mode!=='straight-course'){
    const g=geometry(r);assert.ok(g?.morphology,`${key}: fallback used`);shapes.set(r.shape_id,g.loopPath);
    const pts=paths(g);assert.ok(Math.abs(length(pts)-g.total)<1e-7,key);
    assert.ok(Math.hypot(g.at(0).x-g.at(g.lap).x,g.at(0).y-g.at(g.lap).y)<1e-7);
    assert.ok(pts.every(p=>p.x>=20&&p.x<=550&&p.y>=20&&p.y<=230),key);
    assert.deepEqual(Array.from(g.corners,p=>p.label),['4角','3角','2角','1角']);
    // Uniform distance scale and straight entrance at the template's start.
    assert.ok(Math.abs(g.k*g.lap-g.total)<1e-8);
    context.id=r.shape_id;
    const entry=vm.runInContext('COURSE_SHAPES[id][0]',context);
    assert.ok(Math.hypot(g.at(r.straight_m).x-entry[0],g.at(r.straight_m).y-entry[1])<1e-7);
   }
   context.args=[new Element('div'),v,s,d,c,Array.from({length:Math.ceil(d/200)},(_,i)=>11+i*.1),r];
   assert.equal(vm.runInContext('renderSchematicRoute(...args)',context),true,key);
   const map=context.args[0].children[0].children[0].children[0];
   assert.equal(map.tag,'svg');
   for(const el of map.children)assert.ok(!Object.values(el.attrs).some(v=>/NaN|Infinity/.test(v)),key);
  }
 }
 assert.equal(shapes.size,24);assert.equal(new Set(shapes.values()).size,24);assert.ok(count>=127);
});
test('lap bands exactly partition the visible distance including fractional laps',()=>{
 for(const key of ['福島|ダート|1150','中山|芝|2500','阪神|芝|3200','東京|芝|1600']){
  const r=courses[key].route,g=geometry(r),d=r.distance_m;
  const segs=C.segments(Array.from({length:Math.ceil(d/200)},()=>12),d);
  const bands=segs.map(seg=>[Math.max(d-seg.end,0),Math.min(d-seg.start,g.lap)]).filter(([a,b])=>b>a).sort((a,b)=>a[0]-b[0]);
  assert.equal(bands[0][0],0);for(let i=1;i<bands.length;i++)assert.equal(bands[i-1][1],bands[i][0]);assert.equal(bands.at(-1)[1],Math.min(d,g.lap));
 }
});
