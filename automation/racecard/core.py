from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')
DYNAMIC = ('win_odds', 'popularity', 'body_weight', 'body_weight_diff', 'weather', 'going')
PREDICTIONS = ('expected_running_style', 'start_reliability', 'front_position_rate',
               'early_position_tendency', 'late_speed_tendency', 'same_jockey_flag',
               'same_jockey_streak', 'jockey_change_flag', 'previous_jockey',
               'soft_ground_hint', 'distance_fit_hint', 'course_fit_hint')
VOLATILE = {'generated_at', 'fetched_at', 'history_fetched_at', 'observed_at', 'updated_at', 'content_sha256'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def target_date(requested='', now=None, schedule=''):
    now = now or datetime.now(JST)
    require(now.tzinfo is not None, 'timezone-aware clock required')
    local = now.astimezone(JST)
    if requested:
        require(bool(re.fullmatch(r'\d{4}-\d{2}-\d{2}', requested)), 'target_date must be YYYY-MM-DD')
        return date.fromisoformat(requested)
    # Schedules delayed across midnight still refer to the last scheduled JST slot.
    slots = {'0 12 * * *': (21, 0, 1), '0 22 * * *': (7, 0, 0), '30 2 * * *': (11, 30, 0)}
    if schedule:
        require(schedule in slots, 'unrecognized schedule')
        hour, minute, offset = slots[schedule]
        slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if slot > local:
            slot -= timedelta(days=1)
        return slot.date() + timedelta(days=offset)
    return local.date() + timedelta(days=int(local.hour >= 21))


def normalized(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value or ''))


def grade(value):
    match = re.search(r'Jpn(III|II|I)(?![IVX])', unicodedata.normalize('NFKC', value), re.I)
    return 'Jpn' + match[1].upper() if match else None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in VOLATILE}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def digest(value):
    return hashlib.sha256(canonical(semantic(value))).hexdigest()


def dynamic(obj, key, value, timestamp, unavailable='not_published'):
    obj[key] = value
    obj.setdefault('availability', {})[key] = 'available' if value is not None else unavailable
    obj.setdefault('observed_at', {})[key] = timestamp


def validate_race(race):
    from jsonschema import Draft202012Validator
    from pathlib import Path
    schema = json.loads(Path(__file__).with_name('schema.json').read_text())
    Draft202012Validator(schema).validate(race)
    require(date.fromisoformat(race['target_date']).isoformat() == race['target_date'], 'invalid date')
    horses = race['horses']
    require(len(horses) == race['declared_entry_count'], 'partial racecard: declared count mismatch')
    require(len({h['horse_id'] for h in horses}) == len(horses), 'duplicate horse ID')
    require(len({h['horse_number'] for h in horses}) == len(horses), 'duplicate horse number')
    require(race['organization'] != 'NAR' or race['grade'] in ('JpnI', 'JpnII', 'JpnIII'), 'non-Jpn race')
    for obj, fields in [(race, ('weather', 'going'))] + [(h, DYNAMIC[:4]) for h in horses]:
        for key in fields:
            require((obj[key] is not None) == (obj['availability'][key] == 'available'), 'availability/value mismatch')
            datetime.fromisoformat(obj['observed_at'][key])
    for horse in horses:
        for past in horse['past_performances']:
            require(past['date'] < race['target_date'], 'future/current race leaked into history')
        require(len(horse['past_performances']) <= 5, 'history must be last five starts')
        dates = [p['date'] for p in horse['past_performances']]
        require(dates == sorted(dates, reverse=True), 'history order')


def reconcile(race, old):
    """Never silently delete an entry/race; changes are keyed by stable source IDs."""
    if not old:
        race['changes'] = []
        return race
    require(old['schema_version'] == 1, 'unsupported previous schema')
    require(old['target_date'] == race['target_date'], 'previous date mismatch')
    before = {h['horse_id']: h for h in old['horses']}
    after = {h['horse_id']: h for h in race['horses']}
    require(before.keys() <= after.keys(), 'previous horse disappeared without explicit cancellation status')
    changes = copy.deepcopy(old.get('changes', []))
    for key in ('race_status', 'start_time', 'distance_m'):
        if old[key] != race[key]:
            changes.append({'field': key, 'before': old[key], 'after': race[key], 'observed_at': race['fetched_at']})
    for hid, h in after.items():
        if hid not in before:
            changes.append({'horse_id': hid, 'field': 'entry_added', 'before': None,
                            'after': h['horse_number'], 'observed_at': race['fetched_at']})
            continue
        for key in ('entry_status', 'jockey_id', 'carried_weight', 'horse_number', 'gate_number'):
            if before[hid][key] != h[key]:
                changes.append({'horse_id': hid, 'field': key, 'before': before[hid][key],
                                'after': h[key], 'observed_at': race['fetched_at']})
    race['changes'] = changes
    return race
