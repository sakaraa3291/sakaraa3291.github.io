"""CI-only provenance emitter. Final publication assertion follows deploy job success."""
import hashlib, json, os, re, subprocess, sys, uuid
from pathlib import Path

def sha(v):
    if not re.fullmatch('[0-9a-f]{40}',v): raise ValueError('InvalidCommit')
    return v

def git(*args): return subprocess.check_output(['git',*args],timeout=15).decode().strip()

def update(env):
    checkout=sha(env['CHECKOUT_SHA']); head=sha(git('rev-parse','HEAD'))
    committed=env.get('COMMITTED_SHA',''); dry=env['DRY_RUN']=='true'
    result=json.loads(Path('automation/runs/current/result.json').read_bytes())
    if result['status'] not in ('NO_CHANGES','UPDATE_READY'): raise ValueError('UpdateResult')
    if committed:
        if dry or result['status']!='UPDATE_READY' or sha(committed)!=head or git('rev-parse','HEAD^')!=checkout: raise ValueError('CommitBinding')
        outcome='UPDATE'
    else:
        if head!=checkout: raise ValueError('UnexpectedCommit')
        if not dry and result['status']!='NO_CHANGES': raise ValueError('MissingPublishedCommit')
        outcome='DRY_RUN' if dry else 'NO_CHANGES'
    raw=subprocess.check_output(['git','show',head+':data-version.json'],timeout=15)
    return dict(checkout_sha=checkout,saved_commit=head,committed_sha=committed,outcome=outcome,version_sha256=hashlib.sha256(raw).hexdigest())

def final(env):
    request=env['REQUEST_ID']
    if request and str(uuid.UUID(request))!=request: raise ValueError('UUID')
    outcome=env['OUTCOME']; published=None
    if env['UPDATE_RESULT']!='success': outcome='FAILED'
    elif outcome=='UPDATE':
        if env['DEPLOY_RESULT']=='success' and env['DEPLOY_CHECKOUT']==env['COMMITTED_SHA']:
            published=sha(env['COMMITTED_SHA']); outcome='DEPLOYED'
        else: outcome='FAILED'
    elif outcome not in ('NO_CHANGES','DRY_RUN') or env['DEPLOY_RESULT']!='skipped': outcome='FAILED'
    return dict(schema=1,repository=env['GITHUB_REPOSITORY'],workflow='keiba-update.yml',
        run_id=int(env['GITHUB_RUN_ID']),run_attempt=int(env['GITHUB_RUN_ATTEMPT']),
        request_id=request,event=env['GITHUB_EVENT_NAME'],head_sha=sha(env['GITHUB_SHA']),
        to_date=env['REQUESTED_DATE'],dry_run=env['DRY_RUN']=='true',
        checkout_sha=env['CHECKOUT_SHA'],saved_commit=env['SAVED_COMMIT'],
        committed_sha=env['COMMITTED_SHA'] or None,published_sha=published,
        deployment_checkout_sha=env['DEPLOY_CHECKOUT'] or None,
        update_result=env['UPDATE_RESULT'],deployment_result=env['DEPLOY_RESULT'],
        outcome=outcome,version_sha256=env['VERSION_SHA256'])

if __name__=='__main__':
    if sys.argv[1:] == ['update']:
        values=update(os.environ)
        with open(os.environ['GITHUB_OUTPUT'],'a') as out:
            for key,value in values.items(): out.write(key+'='+value+'\n')
    elif sys.argv[1:] == ['final']:
        Path('provenance.json').write_text(json.dumps(final(os.environ),sort_keys=True)+'\n')
    else: raise ValueError('FixedMode')
