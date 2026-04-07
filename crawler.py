import requests
import pandas as pd
import numpy as np
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

def kofia(date: np.datetime64):
    KOFIA_URL = "https://www.kofiabond.or.kr/proframeWeb/XMLSERVICES/"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/xml",
        "Accept-Encoding": "gzip, deflate, br"
    }
    dt_str = np.datetime_as_string(date, unit='D').replace("-", "")
    print(dt_str)
    xml_data = f'''
        <message>
            <proframeHeader>
                <pfmAppName>BIS-KOFIABOND</pfmAppName>
                <pfmSvcName>BISBndSrtPrcSrchSO</pfmSvcName>
                <pfmFnName>selectDay</pfmFnName>
            </proframeHeader>
            <systemHeader></systemHeader>
            <BISBndSrtPrcDayDTO>
                <standardDt>{dt_str}</standardDt>
                <reportCompCd></reportCompCd>
                <applyGbCd>C00</applyGbCd>
                <val1></val1><val2></val2><val3></val3><val4></val4><val5></val5>
            </BISBndSrtPrcDayDTO>
        </message>
    '''
    response = requests.post(url=KOFIA_URL, data=xml_data, headers=headers)
    root = ET.fromstring(response.text)
    numeric_columns = ["0.25","0.5","0.75","1","1.5","2","2.5","3","4","5","7","10","15","20","30","50"]
    bnd_srt_prc_day_dtos = []
    for dto_element in root.findall('.//BISBndSrtPrcDayDTO'):
        data = {
            "largeCategoryMrk": dto_element.find("largeCategoryMrk").text,
            "creditRnkMrk": dto_element.find("creditRnkMrk").text,
            "typeNmMrk": dto_element.find("typeNmMrk").text,
            "sigaBrnCd": dto_element.find("sigaBrnCd").text,
            "0.25": dto_element.find("val1").text,
            "0.5": dto_element.find("val2").text,
            "0.75": dto_element.find("val3").text,
            "1": dto_element.find("val4").text,
            "1.5": dto_element.find("val5").text,
            "2": dto_element.find("val6").text,
            "2.5": dto_element.find("val7").text,
            "3": dto_element.find("val8").text,
            "4": dto_element.find("val9").text,
            "5": dto_element.find("val10").text,
            "7": dto_element.find("val11").text,
            "10": dto_element.find("val12").text,
            "15": dto_element.find("val13").text,
            "20": dto_element.find("val14").text,
            "30": dto_element.find("val15").text,
            "50": dto_element.find("val16").text,
        }
        bnd_srt_prc_day_dtos.append(data)
    df = pd.DataFrame(bnd_srt_prc_day_dtos)
    if df.empty:
        return pd.DataFrame(columns=["date","largeCategoryMrk","typeNmMrk","creditRnkMrk","sigaBrnCd"] + numeric_columns)
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors='coerce')
    df_average = df.groupby(["largeCategoryMrk","typeNmMrk","creditRnkMrk","sigaBrnCd"])[numeric_columns].mean()

    # 이 줄 추가 (소수점 셋째자리까지 내림)
    df_average = np.floor(df_average * 1000) / 1000
    
    df_average["date"] = date
    df_average = df_average.reset_index()
    return df_average[["date","largeCategoryMrk","typeNmMrk","creditRnkMrk","sigaBrnCd"] + numeric_columns]

# 실행
date_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
date = np.datetime64(date_str, "D")
df = kofia(date)
df.to_excel("kofia.xlsx", index=False)
print("완료!")
