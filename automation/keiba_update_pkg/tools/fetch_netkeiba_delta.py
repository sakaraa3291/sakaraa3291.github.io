#!/usr/bin/env python3
"""Incrementally fetch netkeiba race result data without touching production files.

Input CSV columns: race_id (required), date/venue/レース名 optional.
Outputs are delta CSVs only. Existing historical files are never overwritten.
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import time
from pathlib import Path
from typing import Iterable

import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = "https://race.netkeiba.com/race/result.html?race_id={race_id}"
BET_TYPES = {"単勝","複勝","枠連","馬連","ワイド","馬単","三連複","3連複","三連単","3連単"}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"


def clean(s: object) -> str:
    return re.sub(r"\s+", "", str(s or "").replace("\u3000", " "))


def decode_html(content: bytes) -> str:
    # netkeiba historically serves EUC-JP, but tolerate UTF-8 pages as well.
    candidates = []
    for enc in ("euc_jp", "utf-8", "cp932"):
        try:
            txt = content.decode(enc, errors="replace")
            score = sum(txt.count(x) for x in ("レース", "馬名", "ラップ", "払い戻し", "払戻"))
            candidates.append((score, txt))
        except Exception:
            pass
    return max(candidates, key=lambda x: x[0])[1] if candidates else content.decode("utf-8", errors="replace")


def get(session: requests.Session, url: str, delay: float, retries: int = 3) -> str:
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=30)
            if r.status_code == 200 and len(r.content) > 1000:
                text = decode_html(r.content)
                if "netkeiba" in text.lower() or "レース" in text or "馬名" in text:
                    time.sleep(delay)
                    return text
            last = RuntimeError(f"HTTP {r.status_code}, {len(r.content)} bytes")
        except Exception as e:
            last = e
        time.sleep(delay * (i + 1))
    raise RuntimeError(f"fetch failed: {url}: {last}")


def find_result_table(soup: BeautifulSoup):
    for table in soup.find_all("table"):
        headers = [clean(x.get_text(" ", strip=True)) for x in table.find_all("th")]
        joined = "|".join(headers)
        if "馬名" in joined and "馬番" in joined and "タイム" in joined and ("着順" in joined or "着" in joined):
            return table
    return None


def header_map(table) -> tuple[list[str], dict[str,int]]:
    # Prefer a row whose TH cells define the result columns.
    best: list[str] = []
    for tr in table.find_all("tr"):
        hs = [clean(x.get_text(" ", strip=True)) for x in tr.find_all("th")]
        if len(hs) > len(best) and "馬名" in hs:
            best = hs
    aliases = {
        "着順": ("着順","着"), "馬番": ("馬番","馬"), "馬名": ("馬名",),
        "タイム": ("タイム",), "着差": ("着差",), "通過順": ("通過","コーナー通過順"),
        "上がり3F": ("上り","上がり","上り3F","上がり3F","後3F"),
    }
    out = {}
    for key, names in aliases.items():
        for i,h in enumerate(best):
            if h in names:
                out[key] = i; break
    return best, out


def get_cell(cells, idxmap, key) -> str:
    i = idxmap.get(key)
    if i is None or i >= len(cells): return ""
    return cells[i].get_text(" ", strip=True).replace("\xa0", " ").strip()


def parse_meta(soup: BeautifulSoup, race_id: str, fallback: dict) -> dict:
    text = soup.get_text(" ", strip=True)
    # Title/name
    race_name = soup.select_one('.RaceName')
    h1 = soup.find("h1")
    if race_name and race_name.get_text(" ", strip=True):
        name = race_name.get_text(" ", strip=True)
    elif h1 and h1.get_text(" ", strip=True):
        name = h1.get_text(" ", strip=True)
    else:
        name = str(fallback.get("レース名", ""))
    # Date
    mdate = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", text)
    date = f"{int(mdate.group(1)):04d}-{int(mdate.group(2)):02d}-{int(mdate.group(3)):02d}" if mdate else str(fallback.get("date", ""))
    # Venue from the standard meeting phrase.
    mvenue = re.search(r"\d+回\s*([^\d\s]+?)\s*\d+日目", text)
    venue = mvenue.group(1) if mvenue else str(fallback.get("venue", ""))
    # Surface/distance. Examples: 芝右2200m, ダ左1400m, 芝直1000m.
    md = re.search(r"(芝|ダ|障)[^0-9]{0,8}(\d{3,4})m", text)
    surface_raw = md.group(1) if md else ""
    distance = int(md.group(2)) if md else None
    surface = "ダート" if surface_raw == "ダ" else surface_raw
    # Going. Netkeiba labels are usually 芝 : 良 / ダート : 重.
    mg = re.search(r"(?:芝|ダート)\s*[:：]\s*(良|稍重|稍|重|不良|不)", text)
    if not mg:
        header_text = " ".join(x.get_text(" ", strip=True) for x in soup.select('.RaceData01, .RaceData02'))
        mg = re.search(r"馬場\s*[:：]\s*(良|稍重|稍|重|不良|不)", header_text)
    going = mg.group(1) if mg else ""
    going = {'稍':'稍重','不':'不良'}.get(going,going)
    # Class from page text/name.
    # Scope class parsing to the race header: navigation/other races may mention 未勝利.
    headers=soup.select('.RaceData02, .data_intro, .race_data, .RaceData01')
    class_src = " ".join(node.get_text(" ",strip=True) for node in headers) + " " + name
    import unicodedata
    class_src = unicodedata.normalize('NFKC',class_src)
    if "未勝利" in class_src: klass="未勝利"
    elif "新馬" in class_src: klass="新馬"
    elif re.search(r"(?:1勝|500万)", class_src): klass="1勝"
    elif re.search(r"(?:2勝|1000万)", class_src): klass="2勝"
    elif re.search(r"(?:3勝|1600万)", class_src): klass="3勝"
    elif "オープン" in class_src or re.search(r"\((?:G[I1]+|Jpn[I1]+|OP|L)\)", name, re.I): klass="オープン"
    else: klass="その他"
    return {"race_id":race_id,"date":date,"venue":venue,"レース名":name,"distance_m":distance,"surface":surface,"馬場状態":going,"クラス":klass}


def parse_results(soup: BeautifulSoup, race_id: str):
    table = find_result_table(soup)
    if table is None:
        raise ValueError("result table not found")
    headers, idx = header_map(table)
    details=[]; entries=[]
    for tr in table.find_all("tr"):
        cells=tr.find_all("td")
        if not cells: continue
        hlink=tr.find("a", href=re.compile(r"/horse/[^/]+/?"))
        # require horse link; this excludes headers/summary rows
        if not hlink: continue
        hm=re.search(r"/horse/([^/?#]+)/?", hlink.get("href", ""))
        horse_id=hm.group(1) if hm else ""
        jlink=tr.find("a", href=re.compile(r"/jockey/"))
        jm=re.search(r"/jockey/(?:result/recent/)?([^/?#]+)/?", jlink.get("href", "")) if jlink else None
        jockey_id=jm.group(1) if jm else ""
        horse_name=hlink.get_text(" ", strip=True)
        horse_no=get_cell(cells,idx,"馬番")
        if not horse_no:
            # fallback: find a small integer cell before the horse-name link
            prior=[]
            for td in cells:
                if td.find("a", href=re.compile(r"/horse/")): break
                t=clean(td.get_text(" ",strip=True))
                if re.fullmatch(r"\d{1,2}",t): prior.append(t)
            horse_no=prior[-1] if prior else ""
        finish=get_cell(cells,idx,"着順")
        detail={
            "race_id":race_id,"馬番":horse_no,"馬名":horse_name,"着順":finish,
            "タイム":get_cell(cells,idx,"タイム"),"着差":get_cell(cells,idx,"着差"),
            "通過順":get_cell(cells,idx,"通過順"),"上がり3F":get_cell(cells,idx,"上がり3F"),
        }
        details.append(detail)
        entries.append({"race_id":race_id,"馬番":horse_no,"馬名":horse_name,"馬ID":horse_id,"騎手ID":jockey_id,"通過順":detail["通過順"]})
    if not details:
        raise ValueError(f"no horse rows parsed; headers={headers}")
    return details, entries


def parse_lap(soup: BeautifulSoup, race_id: str, distance: int | None) -> dict | None:
    vals=None
    for tr in soup.find_all("tr"):
        cells=tr.find_all(["th","td"])
        if not cells: continue
        head=clean(cells[0].get_text(" ",strip=True))
        if head == "ラップ" or head.startswith("ラップ"):
            nums=[float(x) for x in re.findall(r"(?<!\d)(\d{1,2}\.\d)(?!\d)", tr.get_text(" ",strip=True))]
            if nums:
                vals=nums; break
    if not vals:
        table=soup.select_one('table.Race_HaronTime')
        if table is not None:
            candidates=[]
            for tr in table.select('tr.HaronTime'):
                raw=[clean(td.get_text(" ",strip=True)) for td in tr.find_all('td')]
                if raw and all(re.fullmatch(r"\d{1,2}\.\d",x) for x in raw):
                    candidates.append([float(x) for x in raw])
            if candidates:
                vals=candidates[-1]
    if not vals:
        return None
    if distance and distance >= 600:
        expected=math.ceil(distance/200)
        if len(vals) != expected:
            raise ValueError(f"lap segment count mismatch: {len(vals)} != {expected} (distance {distance})")
    cumulative=[]; total=0.0
    for x in vals:
        total=round(total+x,1); cumulative.append(total)
    first3=round(sum(vals[:3]),1) if len(vals)>=3 else None
    last3=round(sum(vals[-3:]),1) if len(vals)>=3 else None
    return {
        "race_id":race_id,
        "ラップ":"-".join(f"{x:.1f}" for x in vals),
        "累計ペース":" - ".join(f"{x:.1f}" for x in cumulative),
        "前半3F":first3,"後半3F":last3,"ハロン数":len(vals),
    }


def parse_payouts(soup: BeautifulSoup, race_id: str) -> list[dict]:
    out=[]
    for tr in soup.find_all("tr"):
        th=tr.find("th")
        if th is None: continue
        kind=clean(th.get_text(" ",strip=True)).replace("3連複","三連複").replace("3連単","三連単")
        if kind not in {"単勝","複勝","枠連","馬連","ワイド","馬単","三連複","三連単"}: continue
        result=tr.find("td",class_=lambda c: c and 'Result' in (c if isinstance(c,str) else ' '.join(c)))
        payout=tr.find("td",class_=lambda c: c and 'Payout' in (c if isinstance(c,str) else ' '.join(c)))
        ninki=tr.find("td",class_=lambda c: c and 'Ninki' in (c if isinstance(c,str) else ' '.join(c)))
        if result is None or payout is None: continue
        combos=[]
        groups=result.find_all('ul',recursive=False)
        if groups:
            for ul in groups:
                nums=[clean(x.get_text(" ",strip=True)) for x in ul.find_all('li')]
                nums=[x for x in nums if x]
                if nums: combos.append('-'.join(nums))
        else:
            combos=[clean(x) for x in result.stripped_strings if clean(x)]
        pays=[clean(x) for x in payout.stripped_strings if clean(x)]
        pops=[clean(x) for x in ninki.stripped_strings if clean(x)] if ninki is not None else []
        if not pops: pops=['']*len(pays)
        if not (len(combos)==len(pays)==len(pops)):
            continue
        for c,p,po in zip(combos,pays,pops):
            amount=re.sub(r"[^0-9,]","",p)
            popularity=re.sub(r"[^0-9]","",po)
            if c and amount:
                out.append({"race_id":race_id,"券種":kind,"組み合わせ":c,"払戻金":amount,"人気":popularity})
    seen=set(); ded=[]
    for row in out:
        key=tuple(row.values())
        if key not in seen:
            seen.add(key); ded.append(row)
    return ded

def classify_style(last_pos: str, field_size: int) -> str:
    try: p=int(last_pos)
    except Exception: return ""
    if p==1: return "逃げ"
    if p/field_size <= .33: return "先行"
    if p/field_size <= .66: return "差し"
    return "追込"


def corners_from_entries(entries: list[dict]) -> list[dict]:
    # entries can contain multiple races in one checkpoint batch.  Field size must
    # be counted per race, never across the whole accumulated batch.
    counts={}
    for e in entries:
        rid=str(e.get("race_id", ""))
        counts[rid]=counts.get(rid,0)+1
    out=[]
    for e in entries:
        rid=str(e.get("race_id", "")); n=counts[rid]
        vals=[x for x in re.split(r"[-－]", str(e.get("通過順", ""))) if re.fullmatch(r"\d+",x.strip())]
        # Standard flat-race convention: shorter passage sequences correspond to later corners.
        pos=[""]*(4-len(vals))+vals if len(vals)<=4 else vals[-4:]
        out.append({"race_id":e["race_id"],"馬番":e["馬番"],"馬名":e["馬名"],"馬ID":e["馬ID"],"騎手ID":e["騎手ID"],
                    "1コーナー順":pos[0] if len(pos)>0 else "","2コーナー順":pos[1] if len(pos)>1 else "",
                    "3コーナー順":pos[2] if len(pos)>2 else "","4コーナー順":pos[3] if len(pos)>3 else "",
                    "出走頭数":n,"脚質":classify_style(pos[3] if len(pos)>3 else "",n)})
    return out


def save_csv(path: Path, rows: list[dict], columns: list[str]):
    df=pd.DataFrame(rows, columns=columns)
    if not df.empty: df=df.drop_duplicates()
    df.to_csv(path,index=False,encoding="utf-8-sig")


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--out",default="delta_out")
    ap.add_argument("--delay",type=float,default=1.5)
    ap.add_argument("--limit",type=int,default=0)
    args=ap.parse_args()
    inp=pd.read_csv(args.input,dtype=str,encoding="utf-8-sig",low_memory=False).fillna("")
    if args.limit: inp=inp.head(args.limit)
    outdir=Path(args.out); outdir.mkdir(parents=True,exist_ok=True)
    session=requests.Session(); session.headers.update({"User-Agent":UA,"Accept-Language":"ja,en;q=0.8"})
    metas=[]; laps=[]; details=[]; entries_all=[]; payouts=[]; errors=[]
    for i,row in inp.iterrows():
        rid=str(row["race_id"])
        try:
            html=get(session,BASE.format(race_id=rid),args.delay)
            soup=BeautifulSoup(html,"lxml")
            meta=parse_meta(soup,rid,row.to_dict())
            ds,es=parse_results(soup,rid)
            lp=parse_lap(soup,rid,meta["distance_m"])
            ps=parse_payouts(soup,rid)
            metas.append(meta); details.extend(ds); entries_all.extend(es); payouts.extend(ps)
            if lp: laps.append(lp)
            print(f"OK {rid}: {meta['venue']} {meta['surface']}{meta['distance_m']} {meta['馬場状態']} horses={len(ds)} lap={'yes' if lp else 'no'} payouts={len(ps)}",flush=True)
        except Exception as e:
            errors.append({"race_id":rid,"error":repr(e)})
            print(f"ERROR {rid}: {e!r}",flush=True)
        # checkpoint after every race so an interrupted run preserves progress.
        save_csv(outdir/"race_meta_delta.csv",metas,["race_id","date","venue","レース名","distance_m","surface","馬場状態","クラス"])
        save_csv(outdir/"race_laps_delta.csv",laps,["race_id","ラップ","累計ペース","前半3F","後半3F","ハロン数"])
        save_csv(outdir/"horse_details_delta.csv",details,["race_id","馬番","馬名","着順","タイム","着差","通過順","上がり3F"])
        save_csv(outdir/"race_corners_delta.csv",corners_from_entries(entries_all),["race_id","馬番","馬名","馬ID","騎手ID","1コーナー順","2コーナー順","3コーナー順","4コーナー順","出走頭数","脚質"])
        save_csv(outdir/"payout_delta.csv",payouts,["race_id","券種","組み合わせ","払戻金","人気"])
        save_csv(outdir/"errors.csv",errors,["race_id","error"])
    if errors:
        raise SystemExit(f"{len(errors)} race(s) failed; see errors.csv")

if __name__=="__main__":
    main()
