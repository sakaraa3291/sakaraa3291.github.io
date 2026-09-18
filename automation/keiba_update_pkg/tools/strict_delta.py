"""Production-only completeness checks; never accept merely one row per race."""
import math
import pandas as pd


def validate(target, directory, base_pedigree, allow_nar=False):
    def read(name):
        return pd.read_csv(directory / name, dtype=str).fillna('')
    def require(ok, message):
        if not ok:
            raise ValueError(message)
    meta, horses, corners, laps, payout = [read(n) for n in (
        'race_meta_delta.csv', 'horse_details_delta.csv', 'race_corners_delta.csv',
        'race_laps_delta.csv', 'payout_delta.csv')]
    wanted = set(target.race_id)
    target_jra = target.race_id.str[4:6].isin({f'{n:02d}' for n in range(1, 11)})
    require(allow_nar or target_jra.all(), 'non-JRA race ID in target')
    require(not meta.race_id.duplicated().any() and set(meta.race_id) == wanted, 'metadata target mismatch')
    for frame in (horses, corners, payout):
        require(set(frame.race_id) == wanted, 'extra/missing race data')
    # JRA venue codes are 01..10. Local NAR races can legitimately use their
    # own class labels and are excluded from the central pedigree aggregates.
    jra = meta.race_id.str[4:6].isin({f'{n:02d}' for n in range(1, 11)})
    require(allow_nar or jra.all(), 'non-JRA race in update target')
    require(meta.loc[jra & (meta.surface != '障'), 'クラス'].isin({'未勝利','新馬','1勝','2勝','3勝','オープン'}).all(), 'unknown flat race class')
    require(set(meta.surface) <= {'芝','ダ','ダート','障'}, 'unknown surface')
    require(meta[['レース名','date','distance_m','馬場状態','winner_time']].ne('').all().all(), 'blank metadata')
    require(dict(zip(meta.race_id, meta.date)) == dict(zip(target.race_id, target.date)), 'race dates differ from discovery')
    keys = ['race_id','馬番']
    for frame in (horses, corners):
        require(not frame.duplicated(keys).any(), 'duplicate horse rows')
    require(set(map(tuple, horses[keys].values)) == set(map(tuple, corners[keys].values)), 'horse/corner mismatch')
    require(corners['馬ID'].str.fullmatch(r'\d{10}').all(), 'missing/invalid horse ID')
    counts = corners.groupby('race_id').size()
    # 出走頭数 can exclude scratches; never allow fewer rows than declared starters.
    require(all(counts[r.race_id] >= int(float(r.出走頭数)) > 0 for r in corners.itertuples()), 'truncated horse rows')
    require(not laps.race_id.duplicated().any(), 'duplicate lap rows')
    lapmap = dict(zip(laps.race_id, laps['ラップ']))
    require(set(lapmap) == set(meta.loc[meta.surface != '障', 'race_id']), 'lap race coverage mismatch')
    for row in meta.itertuples():
        winners = horses[(horses.race_id == row.race_id) & (horses['着順'].isin(['1','1.0']))]
        require(len(winners) > 0 and winners['タイム'].ne('').all(), 'missing winning result')
        pay = payout[payout.race_id == row.race_id]
        require({'単勝','複勝'} <= set(pay['券種']), 'missing win/place payout')
        amounts = pd.to_numeric(pay['払戻金'].str.replace(',','').str.replace('円',''), errors='coerce')
        require(amounts.notna().all() and (amounts > 0).all(), 'invalid payout')
        if row.surface != '障':
            values = [float(v) for v in lapmap[row.race_id].split('-')]
            require(len(values) == math.ceil(float(row.distance_m)/200) and all(math.isfinite(v) and v > 0 for v in values), 'invalid lap segments')
    ped = pd.concat([pd.read_csv(base_pedigree, dtype=str).fillna(''), read('horse_pedigree_delta.csv')]).drop_duplicates('馬ID',keep='first').set_index('馬ID')
    require(set(corners['馬ID']) <= set(ped.index), 'missing pedigree')
    require(ped.loc[list(set(corners['馬ID'])), ['父','父父','母父']].ne('').all().all(), 'blank pedigree')
