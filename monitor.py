"""
FSS 금융감독원 페이지 모니터링 스크립트
- 게시판 목록: 새 게시글 감지
- 특정 게시글: 제목 변경 / 첨부파일 변경 감지
변경 발생 시 이메일 발송
"""

import json
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── 설정 ──────────────────────────────────────────────────────────────────────

LIST_URL  = "https://www.fss.or.kr/fss/bbs/B0000318/list.do?menuNo=200760"
VIEW_URL  = "https://www.fss.or.kr/fss/bbs/B0000318/view.do?nttId=210264&menuNo=200760&pageIndex=1"
STATE_FILE = Path("state.json")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": "https://www.fss.or.kr/",
}

# ── 스크래핑 함수 ─────────────────────────────────────────────────────────────

def fetch_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return BeautifulSoup(resp.text, "lxml")


def scrape_list(soup: BeautifulSoup) -> list[dict]:
    """게시판 목록에서 게시글 id·제목·날짜 추출"""
    rows = []

    # FSS BBS 공통 구조: <table class="board_list"> → <tbody> → <tr>
    tbody = soup.select_one("table.board_list tbody, table tbody")
    if not tbody:
        print("[WARN] 목록 테이블을 찾을 수 없습니다. HTML 구조를 확인하세요.")
        return rows

    for tr in tbody.select("tr"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue
        # 첫 번째 td: 번호(또는 공지), 두 번째 td: 제목 링크
        num_td   = tds[0].get_text(strip=True)
        title_td = tds[1]
        a_tag    = title_td.select_one("a")
        if not a_tag:
            continue

        title = a_tag.get_text(strip=True)
        href  = a_tag.get("href", "")
        # nttId를 href에서 추출
        ntt_id = ""
        if "nttId=" in href:
            ntt_id = href.split("nttId=")[1].split("&")[0]

        # 날짜: 마지막 td가 일반적으로 등록일
        date_text = tds[-1].get_text(strip=True) if tds else ""

        rows.append({"nttId": ntt_id, "num": num_td, "title": title, "date": date_text})

    return rows


def scrape_view(soup: BeautifulSoup) -> dict:
    """게시글 상세: 제목 + 첨부파일 목록 추출"""
    # 제목
    title_el = soup.select_one(".view_title, .bbs_view_title, h4.tit, .subject")
    title = title_el.get_text(strip=True) if title_el else ""

    # 첨부파일: FSS는 <ul class="file_list"> 혹은 <div class="file_wrap"> 안에 파일명
    files = []
    for a in soup.select(".file_list a, .file_wrap a, ul.atchFile a, .atch_file a"):
        name = a.get_text(strip=True)
        if name:
            files.append(name)

    # fallback: href에 atchFileNo= 패턴
    if not files:
        for a in soup.select("a[href*='atchFileNo'], a[href*='fileDown']"):
            name = a.get_text(strip=True)
            if name:
                files.append(name)

    return {"title": title, "attachments": sorted(files)}


# ── State 관리 ────────────────────────────────────────────────────────────────

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: dict):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── 이메일 발송 ───────────────────────────────────────────────────────────────

def send_email(subject: str, body_html: str):
    mail_to   = "heeju.lee@meritz.co.kr"
    mail_from = os.environ.get("SMTP_USER", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not all([smtp_user, smtp_pass]):
        print("[WARN] 메일 환경변수가 설정되지 않아 이메일을 건너뜁니다.")
        print(f"  제목: {subject}")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = mail_from
    msg["To"]      = mail_to
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(mail_from, mail_to, msg.as_string())
    print(f"[OK] 이메일 발송 완료 → {mail_to}")


def build_html(changes: list[dict]) -> str:
    rows = ""
    for c in changes:
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;font-weight:bold;color:#1a56db">
            {c['type']}
          </td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee">{c['detail']}</td>
        </tr>"""

    return f"""
    <html><body style="font-family:sans-serif;color:#222;max-width:700px;margin:auto">
      <h2 style="border-left:4px solid #1a56db;padding-left:12px">
        📋 FSS 금융감독원 페이지 변경 알림
      </h2>
      <p style="color:#666">{datetime.now().strftime('%Y-%m-%d %H:%M')} KST 기준</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px">
        <thead>
          <tr style="background:#f3f4f6">
            <th style="padding:8px 12px;text-align:left;width:160px">구분</th>
            <th style="padding:8px 12px;text-align:left">내용</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:24px">
        <a href="{LIST_URL}" style="color:#1a56db">📌 게시판 바로가기</a>
        &nbsp;|&nbsp;
        <a href="{VIEW_URL}" style="color:#1a56db">📄 게시글 바로가기</a>
      </p>
    </body></html>
    """


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    state   = load_state()
    changes = []

    # ① 게시판 목록 모니터링
    print("게시판 목록 스크래핑 중...")
    try:
        list_soup = fetch_soup(LIST_URL)
        posts     = scrape_list(list_soup)
        print(f"  → 파싱된 게시글 수: {len(posts)}")

        prev_ids = set(state.get("list_ntt_ids", []))
        curr_ids = {p["nttId"] for p in posts if p["nttId"]}

        new_ids = curr_ids - prev_ids
        if new_ids:
            new_posts = [p for p in posts if p["nttId"] in new_ids]
            for p in new_posts:
                changes.append({
                    "type":   "🆕 새 게시글",
                    "detail": f"[{p['date']}] {p['title']} (nttId={p['nttId']})",
                })
                print(f"  [NEW] {p['title']}")
            state["list_ntt_ids"] = sorted(curr_ids)
        else:
            print("  변경 없음")
            # 첫 실행이면 현재 상태를 저장
            if "list_ntt_ids" not in state:
                state["list_ntt_ids"] = sorted(curr_ids)

    except Exception as e:
        print(f"[ERROR] 목록 스크래핑 실패: {e}")

    # ② 게시글 상세 모니터링
    print("게시글 상세 스크래핑 중...")
    try:
        view_soup = fetch_soup(VIEW_URL)
        curr_view = scrape_view(view_soup)
        print(f"  제목: {curr_view['title']}")
        print(f"  첨부: {curr_view['attachments']}")

        prev_view = state.get("view", {})

        # 제목 변경
        if prev_view and curr_view["title"] != prev_view.get("title", ""):
            changes.append({
                "type":   "✏️ 제목 변경",
                "detail": f"이전: {prev_view.get('title')}<br>현재: {curr_view['title']}",
            })

        # 첨부파일 변경
        prev_att = set(prev_view.get("attachments", []))
        curr_att = set(curr_view["attachments"])
        added   = curr_att - prev_att
        removed = prev_att - curr_att

        if added:
            changes.append({
                "type":   "📎 첨부파일 추가",
                "detail": "<br>".join(sorted(added)),
            })
        if removed:
            changes.append({
                "type":   "🗑️ 첨부파일 삭제",
                "detail": "<br>".join(sorted(removed)),
            })

        if not prev_view:
            print("  첫 실행 - 현재 상태를 기준값으로 저장합니다.")
        elif not (added or removed) and curr_view["title"] == prev_view.get("title"):
            print("  변경 없음")

        state["view"] = curr_view

    except Exception as e:
        print(f"[ERROR] 상세 스크래핑 실패: {e}")

    # ③ 결과 처리
    save_state(state)

    if changes:
        print(f"\n변경 사항 {len(changes)}건 발견 → 이메일 발송")
        html = build_html(changes)
        send_email("📋 [FSS 모니터링] 금융감독원 페이지 변경 알림", html)
    else:
        print("\n변경 사항 없음. 이메일 발송 안 함.")


if __name__ == "__main__":
    main()
