"""Small structural fixtures modeled on mobile responses observed 2026-09-23."""
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'keiba_update_pkg/tools'))
from discover_race_ids import fetch, parse_ids, validate_day

DAY = date(2026, 9, 19)


def page(meetings=()):
    tabs = ''.join(f'<li><a data-date="{day}">{day}</a></li>' for day, _ in meetings)
    blocks = ''.join(
        f'<div class="RaceListDayWrap"><ul class="jyo_tab"><li data-kaisaidate="{day}"></li></ul>'
        '<ul class="RaceList">' + ''.join(
            f'<li><a href="?pid=race_result&amp;race_id={meeting}{n:02}">{n}R</a></li>'
            for n in range(1, 13)) + '</ul></div>' for day, meeting in meetings)
    import json
    kids = json.dumps([meeting for _, meeting in meetings])
    return f'''<!DOCTYPE html><html><head>
<title>レース一覧 | レース情報(JRA) - netkeiba</title></head>
<body id="Netkeiba_RaceTop"><section class="RaceListArea Contents_Box">
<div class="Title_Sec RaceList_Sec"><h2>レース一覧</h2></div>
<div id="KaisaiListTop" class="RaceDayWrap"><div class="RaceDayWrap_Inner">
<div class="RaceDayPrev"></div><div class="Tab_RaceDaySelect"><ul class="Tab fc">{tabs}</ul></div>
<div class="RaceDayNext"></div></div></div>{blocks}
<script>var _data={{pid:"api_get_race_info_top2"}};
_data.kid=JSON.parse('{kids}');</script>
<div class="Description_Box"><table class="Icon_Guide"><tr><td>レース一覧の見方</td></tr></table></div>
</section><footer>{'レースメニュー 開催日程 netkeiba ' * 20}</footer></body></html>'''


def test_normal_empty_list_without_notice():
    html = page()
    assert 'ありません' not in html
    assert parse_ids(html, DAY) == []
    validate_day(html, [], DAY)


def test_multiday_list_selects_requested_day_and_excludes_future():
    html = page([('20260919', '2026060405'), ('20260920', '2026060406'), ('20260922', '2026060407')])
    ids = parse_ids(html, DAY)
    assert ids == [f'2026060405{n:02}' for n in range(1, 13)]
    validate_day(html, ids, DAY)
    later = date(2026, 9, 20)
    assert parse_ids(html, later) == [f'2026060406{n:02}' for n in range(1, 13)]
    validate_day(html, parse_ids(html, later), later)
    with pytest.raises(RuntimeError):
        validate_day(html, parse_ids(html, date(2026, 9, 21)), date(2026, 9, 21))


@pytest.mark.parametrize('old,new', [
    ('Netkeiba_RaceTop', 'Unknown'),
    ('RaceListArea', 'Unknown'),
    ('レース情報(JRA)', '地方競馬'),
    ('<h2>レース一覧</h2>', ''),
    ('Tab_RaceDaySelect', 'Unknown'),
    ('Icon_Guide', 'Unknown'),
    ("_data.kid=JSON.parse('[]');", ''),
    ("_data.kid=JSON.parse('[]');", "_data.kid=JSON.parse('[\"2026060405\"]');"),
    ('<ul class="Tab fc">', '<ul class="Tab fc"><li>unknown</li>'),
    ('</section>', '<div class="RaceListDayWrap"></div></section>'),
    ('</section>', '<a href="?race_id=202643010101">地方</a></section>'),
    ('</section>', '<a href="?race_id=broken">broken</a></section>'),
    ('</section>', '<div>Verify you are human</div></section>'),
    ('</section>', '<script src="/cdn-cgi/challenge-platform/test"></script></section>'),
    ('</body></html>', ''),
    ('footer', 'aside'),
])
def test_empty_layout_corruption_fails_closed(old, new):
    with pytest.raises(RuntimeError):
        validate_day(page().replace(old, new), [], DAY)


@pytest.mark.parametrize('html', [
    '<html>Please sign in</html>',
    '<p>本日の開催はありません</p>',
    '<html><title>Just a moment</title>' + 'challenge ' * 200 + '</html>',
    '<html>' + 'unknown layout ' * 200 + '</html>',
])
def test_challenge_short_and_unknown_pages_fail_closed(html):
    with pytest.raises(RuntimeError):
        validate_day(html, [], DAY)


def test_partial_meeting_and_wrong_date_fail_closed():
    html = page([('20260919', '2026060405')])
    with pytest.raises(RuntimeError, match='incomplete meeting'):
        validate_day(html, parse_ids(html, DAY)[:-1], DAY)
    with pytest.raises(RuntimeError, match='requested date missing'):
        validate_day(html, parse_ids(html, DAY), date(2026, 9, 20))
    with pytest.raises(RuntimeError, match='ambiguous meeting date'):
        parse_ids(html.replace('data-kaisaidate=', 'unknown='), DAY)


def test_fetch_short_response_fails_closed():
    response = SimpleNamespace(content=b'too short', text='too short', raise_for_status=lambda: None)
    session = SimpleNamespace(get=lambda *a, **kw: response)
    with pytest.raises(RuntimeError, match='short response'):
        fetch(session, 'https://example.invalid', retries=1)


def test_other_day_ids_cannot_be_supplied_for_target_day():
    html = page([('20260919', '2026060405'), ('20260920', '2026060406')])
    with pytest.raises(RuntimeError, match='not scoped'):
        validate_day(html, parse_ids(html, date(2026, 9, 20)), DAY)


def test_missing_race_in_html_fails_closed():
    html = page([('20260919', '2026060405')])
    html = html.replace('<li><a href="?pid=race_result&amp;race_id=202606040512">12R</a></li>', '')
    with pytest.raises(RuntimeError, match='incomplete meeting'):
        validate_day(html, parse_ids(html, DAY), DAY)
