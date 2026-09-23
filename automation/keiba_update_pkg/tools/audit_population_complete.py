#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd

JRA_CODES={f"{n:02}" for n in range(1,11)}
PED_COLS=["父","父父","母父"]

def read_master(path: str) -> pd.DataFrame:
    with open(path,"rb") as f:
        head=f.read(2)
    comp="gzip" if head==b"\x1f\x8b" else None
    return pd.read_csv(path,dtype=str,encoding="utf-8-sig",low_memory=False,compression=comp).fillna("")

def official_races(source_path: str, rules_path: str, from_date: str, to_date: str) -> pd.DataFrame:
    obj=json.load(open(source_path,encoding="utf-8"))
    rows=[r for m in obj["meetings"] for r in m.get("races",[])
          if from_date <= str(r.get("date","")) <= to_date]
    rules=json.load(open(rules_path,encoding="utf-8"))
    for r in rules.get("manual_pdf_repairs",[]):
        if from_date <= str(r.get("date","")) <= to_date:
            rows.append({**r,"source_serial":"","result_status":"result"})
    d=pd.DataFrame(rows).fillna("")
    if d.empty:
        raise SystemExit("official race universe is empty")
    if d["race_id"].duplicated().any():
        d=d.drop_duplicates("race_id",keep="last")
    if not d["race_id"].astype(str).str.fullmatch(r"\d{12}").all():
        raise SystemExit("invalid official race_id")
    if not d["race_id"].astype(str).str.slice(4,6).isin(JRA_CODES).all():
        raise SystemExit("non-JRA official race_id")
    return d.sort_values(["date","race_id"]).reset_index(drop=True)

def main() -> int:
    ap=argparse.ArgumentParser(description="Audit JRA population completeness against independent official evidence.")
    ap.add_argument("--official-sources",required=True)
    ap.add_argument("--rules",required=True)
    ap.add_argument("--master",required=True)
    ap.add_argument("--pedigree",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--from-date",default="2021-01-02")
    ap.add_argument("--to-date",required=True)
    a=ap.parse_args()

    off=official_races(a.official_sources,a.rules,a.from_date,a.to_date)
    m=read_master(a.master)
    jra=m[m["race_id"].astype(str).str.slice(4,6).isin(JRA_CODES)].copy()
    jra=jra[jra["日付"].astype(str).between(a.from_date,a.to_date)]
    race=jra.drop_duplicates("race_id",keep="first").copy()
    official_ids=set(off["race_id"].astype(str))
    master_ids=set(race["race_id"].astype(str))
    missing=sorted(official_ids-master_ids)
    extra=sorted(master_ids-official_ids)
    obstacle=(race.get("馬場",pd.Series("",index=race.index)).astype(str).isin(["障","障害"])
              | race.get("条件",pd.Series("",index=race.index)).astype(str).str.contains("障害",na=False)
              | race.get("レース名",pd.Series("",index=race.index)).astype(str).str.contains("障害",na=False))
    flat=race[~obstacle].copy()
    flat_lap_missing=flat.loc[flat["ラップ"].astype(str).str.strip().eq(""),"race_id"].astype(str).tolist()

    p=pd.read_csv(a.pedigree,dtype=str,encoding="utf-8-sig",low_memory=False).fillna("")
    p=p.drop_duplicates("馬ID",keep="last")
    pids=set(p["馬ID"].astype(str))
    horse_ids={x for x in jra["馬ID"].astype(str) if x}
    missing_pedigree_ids=sorted(horse_ids-pids)
    embedded_blank={c:int(jra[c].astype(str).str.strip().eq("").sum()) for c in PED_COLS}
    ped_index=p.set_index("馬ID")
    ped_blank={}
    for c in PED_COLS:
        ids=[x for x in horse_ids & pids if str(ped_index.at[x,c]).strip()==""]
        ped_blank[c]=len(ids)

    rules=json.load(open(a.rules,encoding="utf-8"))
    annual={str(k):int(v) for k,v in rules.get("annual_totals",{}).items()}
    official_year=off.groupby(off["date"].astype(str).str[:4]).size().astype(int).to_dict()
    annual_mismatch={y:{"expected":n,"actual":int(official_year.get(y,0))}
                     for y,n in annual.items() if int(official_year.get(y,0))!=n}
    summary={
        "from":a.from_date,"to":a.to_date,
        "official_races":len(official_ids),
        "master_jra_races":len(master_ids),
        "missing_races":len(missing),"extra_races":len(extra),
        "missing_ids":missing,"extra_ids":extra,
        "official_by_year":official_year,"annual_total_mismatch":annual_mismatch,
        "obstacle_races":int(obstacle.sum()),
        "flat_races":len(flat),
        "flat_lap_present":len(flat)-len(flat_lap_missing),
        "flat_lap_missing":len(flat_lap_missing),
        "flat_lap_missing_ids":flat_lap_missing,
        "jra_horse_ids":len(horse_ids),
        "pedigree_missing_ids":len(missing_pedigree_ids),
        "pedigree_missing_id_list":missing_pedigree_ids,
        "embedded_pedigree_blank_rows":embedded_blank,
        "pedigree_table_blank_horses":ped_blank,
    }
    Path(a.out).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False))
    bad=bool(missing or extra or flat_lap_missing or missing_pedigree_ids or annual_mismatch
             or any(embedded_blank.values()) or any(ped_blank.values()))
    return 2 if bad else 0

if __name__=="__main__":
    raise SystemExit(main())
