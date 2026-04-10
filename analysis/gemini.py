"""
analyze.py 결과를 Gemini에 넘겨
1) 이상변동 여부 판단 (YES/NO)
2) YES 이면 코멘트 생성
환경변수 GEMINI_API_KEY 필요
"""
import os
import json
import requests

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def _call(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise ValueError("GEMINI_API_KEY 환경변수 없음")
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    resp = requests.post(
        f"{ENDPOINT}?key={api_key}",
        json=payload,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def _build_summary(stats: dict) -> str:
    """통계 dict → 텍스트 요약 (프롬프트용)"""
    lines = [f"기준일: {stats['date']}", ""]
    for col, v in stats["columns"].items():
        if v["current"] is None:
            continue
        d1 = f"{v['d1']:+.1f}" if v["d1"] is not None else "N/A"
        d5 = f"{v['d5']:+.1f}" if v["d5"] is not None else "N/A"
        lines.append(
            f"{col}: {v['current']}{v['unit']}  "
            f"전일대비{d1}{v['unit']}  전주대비{d5}{v['unit']}  "
            f"YTD고{v['ytd_high']}/저{v['ytd_low']} (퍼센타일{v['ytd_pct']}%)  "
            f"1Y고{v['r1y_high']}/저{v['r1y_low']} (퍼센타일{v['r1y_pct']}%)"
        )
    return "\n".join(lines)


JUDGE_PROMPT = """
당신은 한국 채권시장 분석 전문가입니다.
아래 금리 데이터를 보고, 오늘 시장이 '주목할 만한 이상변동'이 있는지 판단하세요.

판단 기준 (참고용, 반드시 이 수치에 국한하지 않아도 됨):
- 최근 변동성 대비 오늘 변동폭이 큰 경우
- 연중(YTD) 또는 1년 퍼센타일이 극단적인 경우 (10% 미만 또는 90% 초과)
- 장단기 스프레드나 신용 스프레드의 급격한 변화
- 복수 지표가 동시에 같은 방향으로 크게 움직인 경우

{data}

위 데이터를 종합적으로 판단하여 아래 JSON 형식으로만 답하세요. 다른 말은 하지 마세요.
{{"notable": true or false, "reason": "한 줄 이유 (notable=false 이면 빈 문자열)"}}
"""

COMMENT_PROMPT = """
당신은 한국 보험사 리스크관리 담당자에게 매일 아침 금리 브리핑을 제공하는 분석가입니다.
아래 금리 데이터를 바탕으로 간결하고 실무적인 코멘트를 작성하세요.

{data}

작성 지침:
- 전체 4~6문장 이내
- 오늘 금리 움직임의 맥락과 원인 (시장 흐름, 이슈)
- 장단기 스프레드 및 신용 스프레드 시사점
- 보험사 ALM 관점에서 주목할 점 한두 가지
- 단정적 예측은 피하고 현황 중심으로 작성
- 한국어로 작성
"""


def run(stats: dict) -> dict:
    """
    Returns:
        {"notable": bool, "comment": str or None, "reason": str}
    """
    summary = _build_summary(stats)

    # 1) 이상변동 판단
    try:
        judge_resp = _call(JUDGE_PROMPT.format(data=summary))
        clean = judge_resp.replace("```json", "").replace("```", "").strip()
        judge = json.loads(clean)
    except Exception as e:
        print(f"[gemini] 판단 실패 — 폴백 notable=False: {e}")
        return {"notable": False, "comment": None, "reason": "Gemini 호출 실패"}

    notable = bool(judge.get("notable", False))
    reason  = judge.get("reason", "")

    comment = None
    if notable:
        try:
            comment = _call(COMMENT_PROMPT.format(data=summary))
        except Exception as e:
            print(f"[gemini] 코멘트 생성 실패: {e}")
            comment = None

    return {"notable": notable, "comment": comment, "reason": reason}


if __name__ == "__main__":
    # 테스트용 더미 stats
    import sys, json as _json
    dummy = {
        "date": "2026-04-09",
        "columns": {
            "국고3Y":  {"current": 2.85, "unit": "%", "d1": -8.0, "d5": -12.0,
                       "ytd_high": 3.10, "ytd_low": 2.80, "ytd_pct": 5.0,
                       "r1y_high": 3.20, "r1y_low": 2.75, "r1y_pct": 8.0},
            "국고10Y": {"current": 3.10, "unit": "%", "d1": -10.0, "d5": -15.0,
                       "ytd_high": 3.40, "ytd_low": 3.05, "ytd_pct": 3.0,
                       "r1y_high": 3.50, "r1y_low": 3.00, "r1y_pct": 5.0},
        }
    }
    result = run(dummy)
    print(_json.dumps(result, ensure_ascii=False, indent=2))
