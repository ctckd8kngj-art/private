"""
kofia_history.csv 가 없을 때 최초 1회만 실행
과거 1년치 영업일 데이터를 KOFIA API로 수집해 CSV 생성
analysis.yml 에서 CSV 행 개수 체크 후 조건부 호출
"""
import os
import sys
import time
import requests
import numpy as np
import pandas as pd
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

# build_csv 의 로직 재사용
sys.path.insert(0, os.path.dirname(__file__))
from build_csv import extract_row, CSV_PATH

KOFIA_URL  = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"
HEADERS    = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/xml",
}
TENORS     = ["0.25","0.5","0.75","1","1.5","2","2.5","3","4","5","7","10","15","20","30","50"]


def fetch_kofia(date: str) -> pd.DataFrame:
    """date: 'YYYYMMDD'"""
    xml_body = f"""
    <message>
      <proframeHeader>
        <pfmAppName>BIS-KOFIABOND</pfmAppName>
        <pfmSvcName>BISBndSrtPrcSrchSO</pfmSvcName>
        <pfmFnName>selectDay</pfmFnName>
      </proframeHeader>
      <systemHeader></systemHeader>
      <BISBndSrtPrcDayDTO>
        <standardDt>{date}</standardDt>
        <reportCompCd></reportCompCd>
        <applyGbCd>C00</applyGbCd>
        <val1></val1><val2></val2><val3></val3><val4></val4><val5></val5>
      </BISBndSrtPrcDayDTO>
    </message>"""
    try:
        resp = requests.post(KOFIA_URL, data=xml_body, headers=HEADERS, timeout=30)
        root = ET.fromstring(resp.text)
    except Exception as e:
        print(f"  API 오류 {date}: {e}")
        return pd.DataFrame()

    rows = []
    for el in root.findall(".//BISBndSrtPrcDayDTO"):
        d = {
            "date":             date,
            "largeCategoryMrk": el.find("largeCategoryMrk").text,
            "creditRnkMrk":     el.find("creditRnkMrk").text,
            "typeNmMrk":        el.find("typeNmMrk").text,
            "sigaBrnCd":        el.find("sigaBrnCd").text,
        }
        for i, t in enumerate(TENORS, 1):
            d[t] = el.find(f"val{i}").text
        rows.append(d)

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    df["date"] = np.datetime64(f"{date[:4]}-{date[4:6]}-{date[6:]}", "D")
    for t in TENORS:
        df[t] = pd.to_numeric(df[t], errors="coerce")

    df = df.groupby(["largeCategoryMrk","typeNmMrk","creditRnkMrk","sigaBrnCd"])[TENORS].mean()
    df = np.floor(df * 1000) / 1000
    df["date"] = np.datetime64(f"{date[:4]}-{date[4:6]}-{date[6:]}", "D")
    return df.reset_index()[["date","largeCategoryMrk","typeNmMrk","creditRnkMrk","sigaBrnCd"] + TENORS]


def main():
    print("[backfill] CSV 없음 — 과거 1년치 수집 시작")
    KST = timezone(timedelta(hours=9))
    end   = datetime.now(KST).replace(tzinfo=None) - timedelta(days=1)
    start = end - timedelta(days=365)
    dates = pd.date_range(start=start, end=end, freq="B")  # 영업일만

    records = []
    for d in dates:
        dt_str = d.strftime("%Y%m%d")
        df = fetch_kofia(dt_str)
        if df.empty:
            print(f"  {dt_str} — 휴일/데이터없음 스킵")
            time.sleep(0.3)
            continue
        row = extract_row(df)
        if row:
            records.append(row)
            print(f"  {dt_str} ✓")
        time.sleep(0.3)  # API 부하 방지

    if not records:
        print("[backfill] 수집된 데이터 없음")
        sys.exit(1)

    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    hist = pd.DataFrame(records).sort_values("date").reset_index(drop=True)
    hist.to_csv(CSV_PATH, index=False)
    print(f"[backfill] 완료 — {len(hist)}행 저장")


if __name__ == "__main__":
    main()
