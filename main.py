"""
분석 워크플로우 진입점
analysis.yml 에서 호출: python analysis/main.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from analyze   import run as analyze_run
from gemini    import run as gemini_run
from send_mail import send


def main():
    print("[main] 통계 계산 + 차트 생성...")
    result = analyze_run()

    print("[main] Gemini 이상변동 판단...")
    gemini = gemini_run(result["stats"])
    print(f"[main] notable={gemini['notable']}  reason={gemini['reason']}")

    print("[main] 메일 발송...")
    send(result["stats"], gemini, result["chart_path"])
    print("[main] 완료")


if __name__ == "__main__":
    main()
