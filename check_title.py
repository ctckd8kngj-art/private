"""
금융감독원 FSS 모니터링
1. 특정 게시글 제목 변경 감지
2. 목록 페이지 새 글 감지
"""

import json
import os
import sys

import requests
from bs4 import BeautifulSoup

# ── 설정 ──────────────────────────────────────────────────────────────────────
VIEW_URL = (
    "https://www.fss.or.kr/fss/bbs/B0000318/view.do"
    "?nttId=210264&menuNo=200760&pageIndex=1"
)
LIST_URL = "https://www.fss.or.kr/fss/bbs/B0000318/list.do?menuNo=200760"
STATE_FILE = "state.json"
BASE_URL = "https://www.fss.or.kr"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
}
# ─────────────────────────────────────────────────────────────────────────────


def get(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


# ── 1. 특정 게시글 제목 크롤링 ───────────────────────────────────────────────
def fetch_view_title() -> str:
    soup = get(VIEW_URL)
    tag = (
        soup.select_one(".view-tit")
        or soup.select_one(".board-view-tit")
        or soup.select_one("h4.tit")
        or soup.select_one("dt.tit")
        or soup.select_one(".cont-tit")
    )
    if not tag:
        raise ValueError("게시글 제목 태그를 찾지 못했습니다.")
    return tag.get_text(strip=True)


# ── 2. 목록 페이지 최신 글 목록 크롤링 ──────────────────────────────────────
def fetch_list_top(n: int = 5) -> list[dict]:
    """목록 페이지 상단 n개 글 반환 (공지 제외)"""
    soup = get(LIST_URL)
    rows = soup.select("table tbody tr")
    items = []
    for row in rows:
        num_td = row.select_one("td:first-child")
        # 공지 행 스킵
        if num_td and "공지" in num_td.get_text():
            continue

        title_td = row.select_one("td.title a") or row.select_one("td a")
        if not title_td:
            continue

        href = title_td.get("href", "")
        full_url = BASE_URL + href if href.startswith("/") else href

        items.append({
            "title": title_td.get_text(strip=True),
            "url": full_url,
            "num": num_td.get_text(strip=True) if num_td else "",
        })
        if len(items) >= n:
            break

    return items


# ── 상태 파일 ─────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ── GitHub Actions output ────────────────────────────────────────────────────
def set_output(key: str, value: str) -> None:
    gho = os.environ.get("GITHUB_OUTPUT")
    if gho:
        delimiter = "EOF_DELIM"
        with open(gho, "a", encoding="utf-8") as f:
            f.write(f"{key}<<{delimiter}\n{value}\n{delimiter}\n")
    else:
        print(f"[OUTPUT] {key}={value}")


# ── 메인 ─────────────────────────────────────────────────────────────────────
def main():
    test_mode = "--test" in sys.argv
    if test_mode:
        print("=" * 55)
        print("🧪 테스트 모드: 실제 크롤링하되 state.json 수정 없음")
        print("   변경이 있는 것처럼 강제로 메일 발송까지 트리거합니다.")
        print("=" * 55)

    state = load_state()
    changed = False
    mail_parts: list[str] = []

    # ── 1) 특정 게시글 제목 변경 체크 ────────────────────────────────────────
    try:
        current_title = fetch_view_title()
        print(f"[게시글 제목] {current_title}")
        last_title = state.get("view_title")

        if test_mode:
            # 테스트: 저장된 값과 무관하게 변경 감지 시뮬레이션
            fake_old = last_title or "(이전 기록 없음)"
            print(f"  → [테스트] 제목 변경 시뮬레이션: '{fake_old}' → '{current_title}'")
            changed = True
            mail_parts.append(
                f"📌 [게시글 제목 변경] (테스트)\n"
                f"  이전: {fake_old}\n"
                f"  현재: {current_title}\n"
                f"  🔗 {VIEW_URL}"
            )
        elif last_title is None:
            print("  → 최초 실행: 제목 저장")
            state["view_title"] = current_title
        elif current_title != last_title:
            print(f"  → 변경!\n    이전: {last_title}\n    현재: {current_title}")
            state["view_title"] = current_title
            changed = True
            mail_parts.append(
                f"📌 [게시글 제목 변경]\n"
                f"  이전: {last_title}\n"
                f"  현재: {current_title}\n"
                f"  🔗 {VIEW_URL}"
            )
        else:
            print("  → 변경 없음")
    except Exception as e:
        print(f"[오류] 게시글 제목 크롤링 실패: {e}", file=sys.stderr)

    # ── 2) 목록 새 글 체크 ───────────────────────────────────────────────────
    try:
        top_items = fetch_list_top(n=5)
        if not top_items:
            print("[오류] 목록 파싱 실패 — 셀렉터를 확인하세요.", file=sys.stderr)
        else:
            print(f"[목록 파싱 성공] {len(top_items)}개 글 확인:")
            for item in top_items:
                print(f"  • [{item['num']}] {item['title']}")

            latest_num   = top_items[0]["num"]
            latest_title = top_items[0]["title"]
            last_num = state.get("list_latest_num")

            if test_mode:
                # 테스트: 첫 번째 글을 새 글로 시뮬레이션
                print(f"  → [테스트] 새 글 감지 시뮬레이션: #{latest_num}")
                changed = True
                new_list_text = "\n".join(
                    f"  • [{item['num']}] {item['title']}\n    🔗 {item['url']}"
                    for item in top_items[:2]  # 상위 2개만 예시로
                )
                mail_parts.append(
                    f"🆕 [새 글 감지] (테스트)\n"
                    f"{new_list_text}\n"
                    f"  📋 목록: {LIST_URL}"
                )
            elif last_num is None:
                print("  → 최초 실행: 목록 상태 저장")
                state["list_latest_num"]   = latest_num
                state["list_latest_title"] = latest_title
            elif latest_num != last_num:
                new_items = []
                for item in top_items:
                    if item["num"] == last_num:
                        break
                    new_items.append(item)

                print(f"  → 새 글 {len(new_items)}개!")
                state["list_latest_num"]   = latest_num
                state["list_latest_title"] = latest_title
                changed = True

                new_list_text = "\n".join(
                    f"  • [{item['num']}] {item['title']}\n    🔗 {item['url']}"
                    for item in new_items
                )
                mail_parts.append(
                    f"🆕 [새 글 {len(new_items)}개 등록]\n"
                    f"{new_list_text}\n"
                    f"  📋 목록: {LIST_URL}"
                )
            else:
                print("  → 새 글 없음")
    except Exception as e:
        print(f"[오류] 목록 크롤링 실패: {e}", file=sys.stderr)

    # ── 상태 저장 & output ───────────────────────────────────────────────────
    if not test_mode:
        save_state(state)
    else:
        print("\n[테스트 모드] state.json 수정하지 않음")

    if changed:
        set_output("changed", "true")
        set_output("mail_body", "\n\n".join(mail_parts))
    else:
        set_output("changed", "false")
        set_output("mail_body", "")


if __name__ == "__main__":
    main()
