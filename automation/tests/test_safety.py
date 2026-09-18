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
    write('race_meta_delta.csv',[dict(race_id=rid,date='2026-09-13',surface='芝',distance_m='400',レース名='test',馬場状態='良',winner_time='24.0',クラス='新馬')])
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
    assert one.iloc[[0,2]].equals(old.iloc[[0,2]])
    assert one.iloc[1]['クラス']=='新馬'


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


def test_discovery_rejects_challenges_and_partial_meetings():
    from discover_race_ids import validate_day
    with pytest.raises(RuntimeError):
        validate_day('<html>Please sign in</html>',[])
    with pytest.raises(RuntimeError):
        validate_day('race list',['202606040101'])
    validate_day('<p>本日の開催はありません</p>',[])
    validate_day('race list',[f'2026060401{n:02}' for n in range(1,13)])


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
