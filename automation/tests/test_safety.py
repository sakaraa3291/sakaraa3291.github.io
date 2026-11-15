import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

AUTOMATION = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUTOMATION))
sys.path.insert(0, str(AUTOMATION / 'keiba_update_pkg/tools'))
spec = importlib.util.spec_from_file_location('hosted_runner', AUTOMATION / 'run_update.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from stage_site import public_path
from strict_delta import validate


def test_public_artifact_excludes_private_state():
    for name in ['automation/state/keiba_master.csv.gz','automation/state/manifest.json','.github/workflows/keiba-update.yml','build_release.py']:
        assert not public_path(name)
    for name in ['index.html','lapdata.json','sw.js','v381-test/index.html']:
        assert public_path(name)


def test_missing_gate_fails_before_candidate_copy(tmp_path):
    with pytest.raises(RuntimeError, match='UPDATE_READY missing'):
        runner.check_candidate(tmp_path, tmp_path, tmp_path, '2026-09-13')


def test_require_is_not_disabled_by_optimization():
    cp = subprocess.run([sys.executable,'-O','-c',f"import sys;sys.path.insert(0,{str(AUTOMATION)!r});from run_update import require;require(False,'blocked')"], capture_output=True)
    assert cp.returncode != 0 and b'blocked' in cp.stderr


def fixture_baseline(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'; repo.mkdir()
    state = tmp_path / 'state'; state.mkdir()
    package = tmp_path / 'package'; (package / 'config').mkdir(parents=True)
    ds = 'test-dataset'
    for name in ('courses.json','elevation.json','lapdata.json','pedigree_stats.json'):
        runner.write_json(repo / name, {'meta': {'dataset_id': ds, 'to':'2026-09-13','audit':{'to':'2026-09-13'}}})
    files = {p.name:runner.digest(p) for p in repo.iterdir()}
    runner.write_json(repo / 'data-version.json', {'app_version':'3.8.0','dataset_id':ds,'files':files})
    runner.write_json(package / 'config/pwa_static.json', {'app_version':'3.8.0','dataset_id':ds,
        'courses_sha256':files['courses.json'],'elevation_sha256':files['elevation.json']})
    for name in runner.STATE_FILES:
        (state / name).write_bytes(b'fixture state')
    manifest = {'through':'2026-09-13','files':{n:runner.digest(state/n) for n in runner.STATE_FILES},
                'production':{n:files[n] for n in runner.PUBLIC_FILES[:2]}}
    runner.write_json(state / 'manifest.json', manifest)
    monkeypatch.setattr(runner, 'PACKAGE', package)
    return repo, state


def test_committed_production_baseline_is_consistent():
    """Exercise real checked-in hashes, not only self-consistent fixtures."""
    repo = AUTOMATION.parent
    manifest = runner.check_baseline(repo, AUTOMATION / 'state')
    assert manifest['through'] == runner.read_json(repo / 'lapdata.json')['meta']['to']


@pytest.mark.parametrize('name', ['courses', 'elevation'])
def test_stale_static_pin_fails_closed(tmp_path, monkeypatch, name):
    repo, state = fixture_baseline(tmp_path, monkeypatch)
    config_path = runner.PACKAGE / 'config/pwa_static.json'
    config = runner.read_json(config_path)
    config[f'{name}_sha256'] = '0' * 64
    runner.write_json(config_path, config)
    with pytest.raises(RuntimeError, match=f'static file changed: {name}'):
        runner.check_baseline(repo, state)


def test_noop_is_offline_and_byte_identical(tmp_path, monkeypatch):
    repo, state = fixture_baseline(tmp_path, monkeypatch)
    def forbidden(*args):
        pytest.fail('no-op must not invoke fetch/build tools')
    monkeypatch.setattr(runner,'run_tool',forbidden)
    before = {str(p):runner.digest(p) for folder in (repo,state) for p in folder.iterdir()}
    monkeypatch.setattr(sys,'argv',['run_update.py','--repo',str(repo),'--state',str(state),'--workdir',str(tmp_path/'run'),'--to-date','2026-09-13','--apply'])
    runner.main()
    assert runner.read_json(tmp_path/'run/result.json')['status']=='NO_CHANGES'
    assert before=={str(p):runner.digest(p) for folder in (repo,state) for p in folder.iterdir()}


@pytest.mark.parametrize('corruption',['cutoff','state','production','app'])
def test_baseline_corruption_fails_closed(tmp_path, monkeypatch, corruption):
    repo, state = fixture_baseline(tmp_path, monkeypatch)
    if corruption == 'state':
        (state / runner.STATE_FILES[0]).write_bytes(b'corrupt')
    elif corruption == 'production':
        (repo / 'lapdata.json').write_bytes(b'corrupt')
    elif corruption == 'cutoff':
        m=runner.read_json(state/'manifest.json');m['through']='2026-07-19';runner.write_json(state/'manifest.json',m)
    else:
        m=runner.read_json(repo/'data-version.json');m['app_version']='4.2';runner.write_json(repo/'data-version.json',m)
    with pytest.raises(RuntimeError):
        runner.check_baseline(repo,state)


def test_overlapping_payouts_require_authorization_and_replace_atomically(tmp_path):
    columns=['race_id','券種','組み合わせ','払戻金','人気']
    old=pd.DataFrame([['2','単勝','1','100','1'],['1','単勝','2','200','2']],columns=columns)
    delta=tmp_path/'delta';delta.mkdir()
    old.to_csv(tmp_path/'old.csv',index=False)
    pd.DataFrame([['2','単勝','1','999','1'],['3','単勝','2','300','2']],columns=columns).to_csv(delta/'payout_delta.csv',index=False)
    tool=AUTOMATION/'keiba_update_pkg/tools/update_payout_incremental.py'
    blocked=subprocess.run([sys.executable,str(tool),'--payout',str(tmp_path/'old.csv'),'--delta-dir',str(delta),'--out',str(tmp_path/'blocked.csv')])
    assert blocked.returncode != 0
    pd.DataFrame({'race_id':['2','3']}).to_csv(tmp_path/'authorized.csv',index=False)
    def merge(source, output):
        subprocess.run([sys.executable,str(tool),'--payout',str(source),'--delta-dir',str(delta),'--out',str(output),'--allow-replace-race-ids',str(tmp_path/'authorized.csv')],check=True)
    merge(tmp_path/'old.csv',tmp_path/'one.csv')
    merge(tmp_path/'one.csv',tmp_path/'two.csv')
    one=pd.read_csv(tmp_path/'one.csv',dtype=str)
    assert one.to_dict('records') == [
        {'race_id':'2','券種':'単勝','組み合わせ':'1','払戻金':'999','人気':'1'},
        {'race_id':'1','券種':'単勝','組み合わせ':'2','払戻金':'200','人気':'2'},
        {'race_id':'3','券種':'単勝','組み合わせ':'2','払戻金':'300','人気':'2'},
    ]
    assert (tmp_path/'one.csv').read_bytes()==(tmp_path/'two.csv').read_bytes()


def strict_fixture(tmp_path):
    rid='202606040101'
    def write(name, rows):
        pd.DataFrame(rows).to_csv(tmp_path/name,index=False)
    write('race_meta_delta.csv',[dict(race_id=rid,date='2026-09-13',surface='芝',distance_m='400',レース名='test',馬場状態='良',芝馬場状態='良',ダート馬場状態='',grade='',winner_time='24.0',クラス='新馬')])
    write('horse_details_delta.csv',[dict(race_id=rid,馬番='1',着順='1',タイム='24.0')])
    write('race_corners_delta.csv',[dict(race_id=rid,馬番='1',馬ID='2020100001',出走頭数='1')])
    write('race_laps_delta.csv',[dict(race_id=rid,ラップ='12.0-12.0')])
    write('payout_delta.csv',[dict(race_id=rid,券種=kind,払戻金='100') for kind in ['単勝','複勝']])
    write('horse_pedigree_delta.csv',[dict(馬ID='2020100001',父='a',父父='b',母父='c')])
    target=pd.DataFrame([dict(race_id=rid,date='2026-09-13')])
    return target, tmp_path/'horse_pedigree_delta.csv'


def test_strict_delta_accepts_complete(tmp_path):
    target,ped=strict_fixture(tmp_path)
    validate(target,tmp_path,ped)


@pytest.mark.parametrize('file,column,value',[
    ('race_corners_delta.csv','出走頭数','2'),
    ('race_corners_delta.csv','馬ID',''),
    ('race_laps_delta.csv','ラップ','12.0'),
    ('race_meta_delta.csv','date','2026-09-14'),
    ('horse_details_delta.csv','着順','2'),
])
def test_strict_delta_rejects_incomplete(tmp_path,file,column,value):
    target,ped=strict_fixture(tmp_path)
    frame=pd.read_csv(tmp_path/file,dtype=str);frame[column]=value;frame.to_csv(tmp_path/file,index=False)
    with pytest.raises(ValueError):
        validate(target,tmp_path,ped)


@pytest.mark.parametrize('field,value',[
    ('芝馬場状態',''),
    ('ダート馬場状態','良'),
    ('馬場状態','重'),
    ('grade','invalid'),
    ('grade','GI'),
])
def test_strict_rejects_conflicting_track_or_grade(tmp_path,field,value):
    target,ped=strict_fixture(tmp_path)
    path=tmp_path/'race_meta_delta.csv'
    df=pd.read_csv(path,dtype=str,encoding='utf-8-sig').fillna('')
    df.at[0,field]=value
    df.to_csv(path,index=False,encoding='utf-8-sig')
    with pytest.raises(ValueError):
        validate(target,tmp_path,ped)


def test_master_overlap_merge_is_idempotent_and_preserves_untouched_order(tmp_path):
    target,ped=strict_fixture(tmp_path)
    rid=target.iloc[0].race_id
    columns=['race_id','日付','馬番','馬ID','クラス','条件','距離','馬場','タイム','着順','父','父父','母父']
    old=pd.DataFrame([
        ['202606040099','2026-07-19','1','2020100002','新馬','新馬','400','芝','24.0','1','a','b','c'],
        [rid,'2026-09-13','1','2020100001','その他','その他','400','芝','24.0','1','a','b','c'],
        ['202606040098','2026-07-19','1','2020100003','新馬','新馬','400','芝','24.0','1','a','b','c'],
    ],columns=columns)
    old.to_csv(tmp_path/'base.csv.gz',index=False)
    target.to_csv(tmp_path/'target.csv',index=False)
    script=AUTOMATION/'keiba_update_pkg/tools/update_master_incremental.py'
    def merge(source,out):
        subprocess.run([sys.executable,str(script),'--master',str(source),'--delta-dir',str(tmp_path),
                        '--existing-pedigree',str(ped),'--out-master',str(out),'--out-pedigree',str(tmp_path/'out-ped.csv'),
                        '--allow-replace-race-ids',str(tmp_path/'target.csv')],check=True)
    merge(tmp_path/'base.csv.gz',tmp_path/'one.csv.gz')
    merge(tmp_path/'one.csv.gz',tmp_path/'two.csv.gz')
    one=pd.read_csv(tmp_path/'one.csv.gz',dtype=str).fillna('')
    two=pd.read_csv(tmp_path/'two.csv.gz',dtype=str).fillna('')
    assert one.equals(two)
    assert one[['race_id','馬番']].equals(old[['race_id','馬番']])
    assert one.iloc[[0,2]][list(old.columns)].equals(old.iloc[[0,2]])
    assert one.iloc[[0,2]][['芝馬場状態','ダート馬場状態','grade']].eq('').all().all()
    assert one.iloc[1]['クラス']=='新馬'
    assert one.iloc[1]['芝馬場状態']=='良'
    assert one.iloc[1]['ダート馬場状態']==''
    assert one.iloc[1]['grade']==''


def test_explicit_graded_race_column_preserves_existing_grade_history(tmp_path):
    baseline={'meta':{'to':'2026-10-04'},'cond':{},
        'grade':{'菊花賞':{'g':'GI','v':'京都','s':'芝','dist':3000,
                           'segment_distances':[200]*15,
                           'avg':[12.0]*15,
                           'yrs':[{'y':'2025','d':'2025-10-26','c':'良',
                                   'l':[12.0]*15,'w':180.0}]}}}
    (tmp_path/'lap.json').write_text(json.dumps(baseline),encoding='utf-8')
    pd.DataFrame([
        {'race_id':'202608040911','日付':'2026-10-25','年':'2026','レース名':'菊花賞',
         'grade':'GI','馬場':'芝','競馬場':'京都','距離':'3000','馬場状態':'良',
         'ラップ':'-'.join(['12.0']*15),'着順':'1','走破秒':'180.0'},
        {'race_id':'202605040611','日付':'2026-10-17','年':'2026','レース名':'富士S',
         'grade':'GII','馬場':'芝','競馬場':'東京','距離':'1600','馬場状態':'良',
         'ラップ':'-'.join(['11.0']*8),'着順':'1','走破秒':'88.0'},
    ]).to_csv(tmp_path/'master.csv',index=False,encoding='utf-8-sig')
    subprocess.run([sys.executable,str(AUTOMATION/'keiba_update_pkg/tools/update_grade_records_incremental.py'),
        '--master',str(tmp_path/'master.csv'),'--baseline',str(tmp_path/'lap.json'),
        '--cond',str(tmp_path/'lap.json'),'--out',str(tmp_path/'graded.json'),
        '--to-date','2026-10-25','--dataset-id','test'],check=True)
    got=json.loads((tmp_path/'graded.json').read_text(encoding='utf-8'))['grade']
    assert got['菊花賞']['yrs'][0]==baseline['grade']['菊花賞']['yrs'][0]
    assert len(got['菊花賞']['yrs'])==2
    assert got['菊花賞']['yrs'][1]['d']=='2026-10-25'
    assert got['富士S']['g']=='GII'
    assert got['富士S']['yrs'][0]['d']=='2026-10-17'


def test_graded_years_remain_separate_by_actual_course():
    from update_grade_records_incremental import rebuild_yearly_course_groups
    import copy
    yrs=[
        {'y':'2022','d':'2022-11-12','c':'良','l':[12.0]*8,'w':96.0},
        {'y':'2024','d':'2024-11-09','c':'良','l':[14.0]*8,'w':112.0},
    ]
    original=copy.deepcopy(yrs)
    grade={'デイリー杯2歳S':{
        'g':'GII','v':'阪神','s':'芝','dist':1600,'avg':[13.0]*8,
        'segment_distances':[200]*8,'yrs':yrs}}
    m=pd.DataFrame([
      {'race_id':'202209050311','日付':'2022-11-12',
       '競馬場':'阪神','馬場':'芝','距離':'1600','レース名':'第57回デイリー杯2歳S(GII)',
       'ラップ':'-'.join(['12.0']*8)},
      {'race_id':'202408060311','日付':'2024-11-09',
       '競馬場':'京都','馬場':'芝','距離':'1600','レース名':'第59回デイリー杯2歳S(GII)',
       'ラップ':'-'.join(['14.0']*8)},
    ])
    a=rebuild_yearly_course_groups(grade,m,'2024-11-09')
    r=grade['デイリー杯2歳S']
    assert a['multi_course_races']==1
    assert [(g['v'],g['year_indices']) for g in r['groups']]==[
        ('阪神',[0]),('京都',[1])]
    assert r['avg']==[12.0]*8
    assert r['groups'][1]['avg']==[14.0]*8
    assert all(all(row[key]==value for key,value in before.items())
               for row,before in zip(r['yrs'],original))
    assert [y['v'] for y in r['yrs']]==['阪神','京都']


def test_unverified_title_swap_does_not_contaminate_course_average():
    from update_grade_records_incremental import rebuild_yearly_course_groups
    grade={'プロキオンステークス':{
        'g':'GII','v':'中京','s':'ダート','dist':1800,'avg':[11.5]*9,
        'segment_distances':[200]*9,
        'yrs':[{'y':'2021','d':'2021-01-24','c':'良','l':[11.0]*9,'w':99.0},
               {'y':'2025','d':'2025-01-26','c':'良','l':[12.0]*9,'w':108.0}]}}
    m=pd.DataFrame([
      {'race_id':'202107010811','日付':'2021-01-24','競馬場':'中京','馬場':'ダート',
       '距離':'1800','レース名':'第38回東海テレビ杯東海S(GII)','ラップ':'-'.join(['11.0']*9)},
      {'race_id':'202507010611','日付':'2025-01-26','競馬場':'中京','馬場':'ダート',
       '距離':'1800','レース名':'プロキオンステークス','ラップ':'-'.join(['12.0']*9)},
    ])
    a=rebuild_yearly_course_groups(grade,m,'2025-01-26')
    r=grade['プロキオンステークス']
    assert r['avg']==[12.0]*9
    assert r['yrs'][0]['l']==[11.0]*9 and 'v' not in r['yrs'][0]
    assert len(a['unresolved'])==1 and a['unresolved'][0]['date']=='2021-01-24'
    assert r['groups'][0]['year_indices']==[1]


def test_verified_short_race_title_requires_exact_lap():
    from update_grade_records_incremental import rebuild_yearly_course_groups
    grade={'日刊スポシンザン記念':{
        'g':'GIII','v':'京都','s':'芝','dist':1600,'avg':[11.0]*8,
        'segment_distances':[200]*8,
        'yrs':[{'y':'2024','d':'2024-01-08','c':'良','l':[11.0]*8,'w':88.0}]}}
    m=pd.DataFrame([{'race_id':'202408010311','日付':'2024-01-08',
        '競馬場':'京都','馬場':'芝','距離':'1600','レース名':'シンザン記念',
        'ラップ':'-'.join(['11.0']*8)}])
    a=rebuild_yearly_course_groups(grade,m,'2024-01-08')
    assert a['alias_verified'][0]['source_name']=='シンザン記念'
    assert grade['日刊スポシンザン記念']['groups'][0]['year_indices']==[0]
    m.at[0,'ラップ']='-'.join(['12.0']*8)
    grade['日刊スポシンザン記念']['yrs'][0].pop('v')
    grade['日刊スポシンザン記念']['yrs'][0].pop('s')
    grade['日刊スポシンザン記念']['yrs'][0].pop('dist')
    grade['日刊スポシンザン記念']['yrs'][0].pop('race_id')
    b=rebuild_yearly_course_groups(grade,m,'2024-01-08')
    assert len(b['unresolved'])==1
    assert 'v' not in grade['日刊スポシンザン記念']['yrs'][0]


def test_browser_grade_filter_separates_years_and_course():
    import shutil
    node=shutil.which('node')
    if not node:
        pytest.skip('Node.js is unavailable in this test environment')
    js=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const root=process.argv[1],C=require(root+'/core.js');
const laps=(n)=>Array(8).fill(n);
const year=(y,v,n)=>({y:String(y),d:String(y)+'-11-12',c:'良',l:laps(n),
 w:100,v,s:'芝',dist:1600,race_id:'2026'+String(y).slice(2)+'050311'});
const r={g:'GII',v:'阪神',s:'芝',dist:1600,avg:laps(12),
 segment_distances:laps(200),yrs:[
  year(2021,'阪神',12),year(2022,'阪神',12),year(2023,'京都',14)],
 groups:[{v:'阪神',s:'芝',dist:1600,avg:laps(12),
   segment_distances:laps(200),year_indices:[0,1]},
  {v:'京都',s:'芝',dist:1600,avg:laps(14),
   segment_distances:laps(200),year_indices:[2]}]};
const meta={schema_version:2,dataset_id:'test'};
const ver={schema_version:2,app_version:'3.8.0',dataset_id:'test',
  files:Object.fromEntries(C.FILES.map(f=>[f,'0'.repeat(64)])),
  updated_at:'2026-11-15T00:00:00Z'};
const b={version:ver,
 'lapdata.json':{meta:{...meta,races:0,from:null,to:null,audit:{}},grade:{'デイリー杯2歳S':r},cond:{}},
 'pedigree_stats.json':{meta:{...meta,source_rows:0},stats:{}},
 'courses.json':{meta,courses:{}},
 'elevation.json':{meta,profiles:{}}};
C.validateBundle(b);
const broken=JSON.parse(JSON.stringify(b));
broken['lapdata.json'].grade['デイリー杯2歳S'].groups[1].avg=laps(12);
assert.throws(()=>C.validateBundle(broken),/重賞平均/);
class El{
 constructor(){this.childNodes=[];this.children=this.childNodes;this.style={};
  this.dataset={};this.value='';this.hidden=false;this.textContent='';}
 append(...x){this.childNodes.push(...x);}
 replaceChildren(...x){this.childNodes.splice(0,this.childNodes.length,...x);}
 setAttribute(){}
 addEventListener(){}
}
const fields={};
const document={getElementById(id){return fields[id]??(fields[id]=new El())},
 createElement(){return new El()},createElementNS(){return new El()}};
const c={document,LapCore:C,LAP_TEST_MODE:true};vm.createContext(c);
vm.runInContext(fs.readFileSync(root+'/app.js','utf8'),c);
c.data=b;
vm.runInContext("bundle=globalThis.data;mode='grade';"+
 "draw=(series,dist)=>{globalThis.drawn={series,dist}};"+
 "renderCourse=(venue,surface,dist)=>{globalThis.route={venue,surface,dist}};"+
 "renderPedigree=()=>{};trendText=()=>'';",c);
const rows=vm.runInContext('gradeRows()',c);
assert.equal(rows.length,2);
for(const [venue,count] of [['阪神',2],['京都',1]]){
 document.getElementById('fRace').value=rows.find(x=>x.venue===venue).value;
 vm.runInContext('render()',c);
 assert.equal(c.route.venue,venue);
 assert.equal(c.drawn.series.length,count+1);
 assert(JSON.stringify(fields.readout).includes(String(count)+'R'));
}
'''
    subprocess.run([node,'-e',js,str(AUTOMATION.parent)],capture_output=True,text=True,check=True)


def test_race_class_uses_header_not_navigation():
    from bs4 import BeautifulSoup
    from fetch_netkeiba_delta import parse_meta
    html='<nav>未勝利 1勝</nav><h1>特別競走</h1><div class="RaceData02">3歳以上 ２勝クラス</div>'
    assert parse_meta(BeautifulSoup(html,'lxml'),'202606040101',{})['クラス']=='2勝'


def test_metadata_enrichment_can_resume_twice(tmp_path):
    from fetch_netkeiba_delta_v2 import enrich_meta
    strict_fixture(tmp_path)
    enrich_meta(tmp_path)
    second=enrich_meta(tmp_path)
    assert 'winner_time' in second and 'winner_time_x' not in second
    assert second.iloc[0].winner_time==24.0


def test_pedigree_default_start_date_covers_full_audit_window():
    from rebuild_pedigree_stats import DEFAULT_FROM_DATE
    assert DEFAULT_FROM_DATE == '2021-01-02'


def test_jra_pdf_parser_fails_closed_on_missing_race_headers():
    from audit_jra_sources import parse_result_text
    meeting={'meeting_id':'2023010204','year':2023,'venue':'札幌','url':'https://www.jra.go.jp/example.pdf'}
    text='00001 8月20日 晴 第1競走 x 00002 8月20日 晴 第2競走 x 00005 8月20日 晴 第5競走'
    with pytest.raises(ValueError,match='unresolved result slots'):
        parse_result_text(text,meeting)


def test_nonstarters_are_excluded_but_dnf_counts():
    from rebuild_pedigree_stats import nonstarter_mask
    d=pd.DataFrame({'着順':['1','取消','除外','中止','',''],'単勝':['2.0','','','','','3.0']})
    assert nonstarter_mask(d).tolist()==[False,True,True,False,True,False]


def test_stale_checkpoint_marker_cannot_authorize_noop(tmp_path):
    work=tmp_path/'run';work.mkdir();(work/'UPDATE_READY').write_text('stale')
    baseline=tmp_path/'lap.json';baseline.write_text(json.dumps({'meta':{'to':'2026-09-13'}}))
    subprocess.run([sys.executable,str(AUTOMATION/'keiba_update_pkg/tools/run_incremental_update.py'),
        '--master','unused','--payout','unused','--pedigree','unused','--baseline-lap',str(baseline),
        '--to-date','2026-09-13','--workdir',str(work),'--release-config',str(AUTOMATION/'keiba_update_pkg/config/pwa_static.json')],check=True)
    assert not (work/'UPDATE_READY').exists() and (work/'NO_CHANGES').exists()


def test_empty_grade_increment_preserves_manual_history(tmp_path):
    baseline={'meta':{'to':'2026-09-13','audit':{'manual_note':'keep'}},'grade':{'manual':{'yrs':[{'y':'2021','d':'2021-01-01','l':[12]}]}},'cond':{}}
    (tmp_path/'lap.json').write_text(json.dumps(baseline))
    pd.DataFrame([{'race_id':'202606040101','日付':'2026-09-13','着順':'1','走破秒':'24.0','ラップ':'12-12','レース名':'新馬'}]).to_csv(tmp_path/'master.csv',index=False)
    subprocess.run([sys.executable,str(AUTOMATION/'keiba_update_pkg/tools/update_grade_records_incremental.py'),
        '--master',str(tmp_path/'master.csv'),'--baseline',str(tmp_path/'lap.json'),'--cond',str(tmp_path/'lap.json'),
        '--out',str(tmp_path/'out.json'),'--to-date','2026-09-14'],check=True)
    out=json.loads((tmp_path/'out.json').read_text())
    assert out['grade']==baseline['grade'] and out['meta']['audit']['manual_note']=='keep'


def test_unknown_classes_and_non_jra_targets_fail_closed(tmp_path):
    target,ped=strict_fixture(tmp_path)
    meta=pd.read_csv(tmp_path/'race_meta_delta.csv',dtype=str);meta['クラス']='その他';meta.to_csv(tmp_path/'race_meta_delta.csv',index=False)
    with pytest.raises(ValueError,match='unknown.*flat race class'):
        validate(target,tmp_path,ped)
    strict_fixture(tmp_path)
    old=target.iloc[0].race_id;new='202643080201'
    for path in tmp_path.glob('*.csv'):
        frame=pd.read_csv(path,dtype=str)
        if 'race_id' in frame:frame['race_id']=new;frame.to_csv(path,index=False)
    target['race_id']=new
    with pytest.raises(ValueError,match='non-JRA'):
        validate(target,tmp_path,ped)
