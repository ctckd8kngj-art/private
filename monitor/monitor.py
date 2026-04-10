"""
FSS 금융감독원 페이지 모니터링 스크립트
- 게시판 목록 ×2: 새 게시글 / 제목 변경 감지
- 특정 게시글: 제목 변경 / 첨부파일 변경 감지
- 변경 감지 시 본문 + 첨부파일 실제 첨부하여 이메일 발송
"""

import json
import os
import smtplib
import time
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ── 설정 ──────────────────────────────────────────────────────────────────────

LISTS = [
    {
        "key":   "list_B0000318",
        "label": "지급여력제도 및 감독회계",
        "url":   "https://www.fss.or.kr/fss/bbs/B0000318/list.do?menuNo=200760",
        "menu":  "200760",
        "bbs":   "B0000318",
    },
    {
        "key":   "list_B0000123",
        "label": "보험업감독업무시행세칙",
        "url":   "https://www.fss.or.kr/fss/bbs/B0000123/list.do?menuNo=200424",
        "menu":  "200424",
        "bbs":   "B0000123",
    },
]

VIEWS = [
    {
        "key":   "view_210264",
        "label": "감독원장 제공자료 (nttId=210264)",
        "url":   "https://www.fss.or.kr/fss/bbs/B0000318/view.do?nttId=210264&menuNo=200760&pageIndex=1",
    },
]

STATE_FILE  = Path(__file__).parent / "state.json"
MAX_ATT_MB  = 10   # 첨부파일 1개당 최대 크기 (MB)

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
    """게시판 목록 → [{nttId, title, date}]"""
    rows = []
    tbody = soup.select_one("table.board_list tbody, table tbody")
    if not tbody:
        print("[WARN] 목록 테이블을 찾을 수 없습니다.")
        return rows

    for tr in tbody.select("tr"):
        tds = tr.select("td")
        if len(tds) < 2:
            continue
        a_tag = tds[1].select_one("a")
        if not a_tag:
            continue

        title  = a_tag.get_text(strip=True)
        href   = a_tag.get("href", "")
        ntt_id = href.split("nttId=")[1].split("&")[0] if "nttId=" in href else ""
        date   = tds[-1].get_text(strip=True)

        if ntt_id:
            rows.append({"nttId": ntt_id, "title": title, "date": date})

    return rows


def scrape_view(soup: BeautifulSoup) -> dict:
    """게시글 상세 → {title, body, attachments}
    attachments: [{name, url}]
    """
    # 제목
    title_el = soup.select_one(".view_title, .bbs_view_title, h4.tit, .subject")
    title    = title_el.get_text(strip=True) if title_el else ""

    # 본문
    body_el = soup.select_one(
        ".dbdata, .bbs_view_con, .view_con, .board_view_content, .cont, #bbs_detail_content"
    )
    def el_to_text(el) -> str:
        """블록 태그 기준으로 줄바꿈 삽입해서 텍스트 추출"""
        import copy
        el = copy.copy(el)
        for tag in el.select("br"):
            tag.replace_with("\n")
        for tag in el.select("p, div, li, tr, h1, h2, h3, h4, h5, h6"):
            tag.insert_before("\n")
        return el.get_text(separator="", strip=False).strip()

    body = el_to_text(body_el) if body_el else ""
    # 3줄 이상 연속 빈 줄 → 2줄로 정리
    body = re.sub(r"\n{3,}", "\n\n", body)
    if len(body) > 1500:
        body = body[:1500] + "\n\n[...본문 생략, 전체 내용은 원문 링크 참조]"

    # 첨부파일: 이름 + 다운로드 URL 함께 수집
    files = []
    base  = "https://www.fss.or.kr"

    selectors = [
        ".file_list a", ".file_wrap a",
        "ul.atchFile a", ".atch_file a",
        "a[href*='fileDown']", "a[href*='atchFileNo']",
    ]
    seen_urls = set()
    for sel in selectors:
        for a in soup.select(sel):
            name = a.get_text(strip=True)
            href = a.get("href", "")
            if not name or not href:
                continue
            full_url = href if href.startswith("http") else base + href
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            files.append({"name": name, "url": full_url})

    return {"title": title, "body": body, "attachments": files}


def download_attachments(attachments: list[dict]) -> list[dict]:
    """첨부파일 다운로드 → [{name, data(bytes)}]
    MAX_ATT_MB 초과 파일은 건너뜀
    """
    results = []
    for att in attachments:
        try:
            time.sleep(0.3)
            resp = requests.get(att["url"], headers=HEADERS, timeout=30)
            resp.raise_for_status()

            size_mb = len(resp.content) / (1024 * 1024)
            if size_mb > MAX_ATT_MB:
                print(f"    [SKIP] {att['name']} ({size_mb:.1f}MB > {MAX_ATT_MB}MB 제한)")
                results.append({"name": att["name"], "data": None, "skipped": True, "size_mb": size_mb})
                continue

            # Content-Disposition에서 실제 파일명 추출 시도
            cd = resp.headers.get("Content-Disposition", "")
            fname = att["name"]
            if "filename" in cd:
                for part in cd.split(";"):
                    part = part.strip()
                    if part.lower().startswith("filename"):
                        fname = part.split("=", 1)[-1].strip().strip('"\'')
                        try:
                            fname = fname.encode("latin-1").decode("utf-8")
                        except Exception:
                            pass
                        break

            print(f"    [DOWN] {fname} ({size_mb:.1f}MB)")
            results.append({"name": fname, "data": resp.content, "skipped": False})

        except Exception as e:
            print(f"    [WARN] 다운로드 실패 ({att['name']}): {e}")
            results.append({"name": att["name"], "data": None, "skipped": True, "size_mb": 0})

    return results


def fetch_post_detail(ntt_id: str, bbs: str, menu: str) -> dict:
    """게시글 상세 fetch → {body, attachments(name+url), url}"""
    url = (
        f"https://www.fss.or.kr/fss/bbs/{bbs}/view.do"
        f"?nttId={ntt_id}&menuNo={menu}&pageIndex=1"
    )
    try:
        time.sleep(0.5)
        soup   = fetch_soup(url)
        detail = scrape_view(soup)
        return {
            "body":        detail["body"],
            "attachments": detail["attachments"],
            "url":         url,
        }
    except Exception as e:
        print(f"    [WARN] 상세 fetch 실패 ({ntt_id}): {e}")
        return {"body": "", "attachments": [], "url": url}


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


def migrate_state(state: dict) -> dict:
    if "list_ntt_ids" in state and "list_B0000318" not in state:
        state["list_B0000318"] = [
            {"nttId": nid, "title": "", "date": ""}
            for nid in state.pop("list_ntt_ids")
        ]
        print("[MIGRATE] list_ntt_ids → list_B0000318 변환 완료")

    if "view" in state and "view_210264" not in state:
        state["view_210264"] = {
            "title":       state["view"].get("title", ""),
            "attachments": state["view"].get("attachments", []),
        }
        del state["view"]
        print("[MIGRATE] view → view_210264 변환 완료")

    return state


# ── 이메일 빌더 ───────────────────────────────────────────────────────────────

def _render_body_block(body: str, attachments: list[dict], downloaded: list[dict]) -> str:
    """본문 텍스트 + 첨부파일 목록 HTML 블록
    attachments: [{name, url}]  downloaded: [{name, data, skipped}]
    """
    body_html = ""
    if body:
        escaped = (
            body.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )
        body_html = f"""
        <div style="background:#f9fafb;border-radius:6px;padding:12px 14px;
                    font-size:12px;color:#374151;line-height:1.7;white-space:pre-wrap;
                    margin-top:8px">{escaped}</div>"""

    att_html = ""
    if attachments:
        skipped_names = {d["name"] for d in downloaded if d.get("skipped")}
        items = ""
        for att in attachments:
            is_skip = att["name"] in skipped_names
            suffix  = f' <span style="color:#ef4444;font-size:11px">(용량 초과 - 링크만 제공)</span>' if is_skip else ""
            items += (
                f'<li style="margin:3px 0;color:#4b5563">'
                f'📎 <a href="{att["url"]}" style="color:#1a56db">{att["name"]}</a>{suffix}'
                f'</li>'
            )
        att_html = f"""
        <div style="margin-top:8px">
          <div style="font-size:12px;font-weight:600;color:#6b7280;margin-bottom:4px">
            첨부파일 (메일에 직접 첨부됨)
          </div>
          <ul style="margin:0;padding-left:18px;font-size:12px">{items}</ul>
        </div>"""

    return body_html + att_html


def _section_new_posts(board_changes: list[dict]) -> str:
    if not board_changes:
        return ""

    board_blocks = ""
    for bc in board_changes:
        post_blocks = ""

        for p in bc.get("new_posts", []):
            detail = _render_body_block(
                p.get("body", ""), p.get("attachments", []), p.get("downloaded", [])
            )
            post_blocks += f"""
            <div style="border:1px solid #dbeafe;border-radius:6px;
                        padding:12px 14px;margin-bottom:10px">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <span style="font-size:11px;background:#dbeafe;color:#1d4ed8;
                               padding:2px 7px;border-radius:10px;font-weight:600">NEW</span>
                  <a href="{p['url']}" style="margin-left:8px;font-size:13px;font-weight:600;
                                              color:#1a56db;text-decoration:none">{p['title']}</a>
                </div>
                <span style="font-size:11px;color:#9ca3af;white-space:nowrap;
                             margin-left:12px">{p['date']}</span>
              </div>
              {detail}
            </div>"""

        for p in bc.get("modified_posts", []):
            detail = _render_body_block(
                p.get("body", ""), p.get("attachments", []), p.get("downloaded", [])
            )
            post_blocks += f"""
            <div style="border:1px solid #fde68a;border-radius:6px;
                        padding:12px 14px;margin-bottom:10px">
              <div style="display:flex;justify-content:space-between;align-items:flex-start">
                <div>
                  <span style="font-size:11px;background:#fef3c7;color:#92400e;
                               padding:2px 7px;border-radius:10px;font-weight:600">제목변경</span>
                  <a href="{p['url']}" style="margin-left:8px;font-size:13px;font-weight:600;
                                              color:#1a56db;text-decoration:none">{p['title']}</a>
                </div>
                <span style="font-size:11px;color:#9ca3af;white-space:nowrap;
                             margin-left:12px">{p['date']}</span>
              </div>
              <div style="font-size:12px;color:#78350f;margin-top:6px">
                이전 제목: <s>{p['prev_title']}</s>
              </div>
              {detail}
            </div>"""

        board_blocks += f"""
        <div style="margin-bottom:20px">
          <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:8px">
            📌 {bc['label']}
          </div>
          {post_blocks}
        </div>"""

    return f"""
    <div style="margin-bottom:32px">
      <h3 style="margin:0 0 14px;font-size:15px;color:#111827;
                 border-left:4px solid #2563eb;padding-left:10px">
        🆕 게시판 변경 알림
      </h3>
      {board_blocks}
    </div>"""


def _section_view_changes(view_changes: list[dict]) -> str:
    if not view_changes:
        return ""

    change_blocks = ""
    for vc in view_changes:
        detail_rows = ""
        for item in vc["items"]:
            detail_rows += f"""
            <tr>
              <td style="padding:7px 10px;border-bottom:1px solid #eef0f3;font-weight:600;
                         color:#b45309;white-space:nowrap;vertical-align:top;
                         font-size:13px">{item['type']}</td>
              <td style="padding:7px 10px;border-bottom:1px solid #eef0f3;
                         font-size:13px;line-height:1.7">{item['detail']}</td>
            </tr>"""

        body_block = _render_body_block(
            vc.get("body", ""), vc.get("attachments", []), vc.get("downloaded", [])
        )

        change_blocks += f"""
        <div style="margin-bottom:20px">
          <div style="font-size:13px;font-weight:600;color:#374151;margin-bottom:6px">
            📄 <a href="{vc['url']}" style="color:#1a56db;text-decoration:none">{vc['label']}</a>
          </div>
          <table style="width:100%;border-collapse:collapse">
            <tbody>{detail_rows}</tbody>
          </table>
          {body_block}
        </div>"""

    return f"""
    <div style="margin-bottom:32px">
      <h3 style="margin:0 0 14px;font-size:15px;color:#111827;
                 border-left:4px solid #d97706;padding-left:10px">
        ✏️ 관찰 게시글 변경 내역
      </h3>
      {change_blocks}
    </div>"""


def build_html(board_changes: list[dict], view_changes: list[dict]) -> str:
    sec1    = _section_new_posts(board_changes)
    sec2    = _section_view_changes(view_changes)
    divider = (
        '<hr style="border:none;border-top:1px solid #e5e7eb;margin:0 0 28px">'
        if sec1 and sec2 else ""
    )
    return f"""
    <html><body style="font-family:'Apple SD Gothic Neo',Malgun Gothic,sans-serif;
                       color:#111827;max-width:700px;margin:auto;padding:24px">
      <div style="background:#1e40af;color:white;padding:16px 20px;border-radius:8px 8px 0 0">
        <div style="font-size:11px;opacity:.75;margin-bottom:2px">금융감독원 모니터링</div>
        <div style="font-size:17px;font-weight:700">FSS 페이지 변경 알림</div>
        <div style="font-size:11px;opacity:.75;margin-top:4px">
          {datetime.now().strftime('%Y-%m-%d %H:%M')} KST
        </div>
      </div>
      <div style="border:1px solid #e5e7eb;border-top:none;padding:24px;
                  border-radius:0 0 8px 8px">
        {sec1}
        {divider}
        {sec2}
        <div style="margin-top:8px;padding-top:16px;border-top:1px solid #f3f4f6;
                    font-size:11px;color:#9ca3af">
          이 메일은 GitHub Actions에 의해 자동 발송됩니다.
        </div>
      </div>
    </body></html>
    """


# ── 이메일 발송 ───────────────────────────────────────────────────────────────

def send_email(subject: str, body_html: str, all_downloaded: list[dict]):
    mail_to   = os.environ.get("MAIL_TO", "")
    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    if not all([mail_to, smtp_user, smtp_pass]):
        print("[WARN] 메일 환경변수가 설정되지 않아 이메일을 건너뜁니다.")
        return

    # mixed: HTML 본문 + 파일 첨부를 함께 담을 수 있는 타입
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = mail_to

    # HTML 본문
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    # 실제 파일 첨부
    attached_count = 0
    for f in all_downloaded:
        if f.get("data") is None:
            continue
        part = MIMEApplication(f["data"])
        # 파일명 인코딩 (한글 대응)
        try:
            fname_encoded = f["name"].encode("utf-8").decode("ascii")
        except Exception:
            from email.header import Header
            fname_encoded = Header(f["name"], "utf-8").encode()
        part.add_header(
            "Content-Disposition", "attachment",
            filename=("utf-8", "", f["name"])
        )
        msg.attach(part)
        attached_count += 1

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, mail_to, msg.as_string())
    print(f"[OK] 이메일 발송 완료 → {mail_to} (첨부파일 {attached_count}개)")


# ── 메인 ──────────────────────────────────────────────────────────────────────

def main():
    state = migrate_state(load_state())

    board_changes:  list[dict] = []
    view_changes:   list[dict] = []
    all_downloaded: list[dict] = []   # 메일 첨부용 전체 수집

    # ① 게시판 목록 모니터링
    for board in LISTS:
        print(f"[목록] {board['label']} 스크래핑 중...")
        try:
            soup  = fetch_soup(board["url"])
            posts = scrape_list(soup)
            print(f"  → 파싱된 게시글 수: {len(posts)}")

            prev_list = state.get(board["key"], [])
            is_first  = not prev_list
            prev_map  = {p["nttId"]: p for p in prev_list}
            curr_map  = {p["nttId"]: p for p in posts}

            new_posts = []
            mod_posts = []

            if not is_first:
                for ntt_id, post in curr_map.items():
                    if ntt_id not in prev_map:
                        print(f"  [NEW] {post['title']}")
                        detail     = fetch_post_detail(ntt_id, board["bbs"], board["menu"])
                        downloaded = download_attachments(detail["attachments"])
                        all_downloaded.extend(downloaded)
                        new_posts.append({**post, **detail, "downloaded": downloaded})

                    elif (
                        prev_map[ntt_id]["title"]
                        and post["title"] != prev_map[ntt_id]["title"]
                    ):
                        print(f"  [MOD] {prev_map[ntt_id]['title']} → {post['title']}")
                        detail     = fetch_post_detail(ntt_id, board["bbs"], board["menu"])
                        downloaded = download_attachments(detail["attachments"])
                        all_downloaded.extend(downloaded)
                        mod_posts.append({
                            **post, **detail,
                            "prev_title": prev_map[ntt_id]["title"],
                            "downloaded": downloaded,
                        })
            else:
                print("  첫 실행 - 기준값 저장")

            if new_posts or mod_posts:
                board_changes.append({
                    "label":          board["label"],
                    "url":            board["url"],
                    "new_posts":      new_posts,
                    "modified_posts": mod_posts,
                })

            state[board["key"]] = [
                {"nttId": p["nttId"], "title": p["title"], "date": p["date"]}
                for p in posts
            ]

        except Exception as e:
            print(f"  [ERROR] {e}")

    # ② 게시글 상세 모니터링
    for view in VIEWS:
        print(f"[상세] {view['label']} 스크래핑 중...")
        try:
            soup  = fetch_soup(view["url"])
            curr  = scrape_view(soup)
            prev  = state.get(view["key"], {})
            items = []

            print(f"  제목: {curr['title']}")
            print(f"  첨부: {[a['name'] for a in curr['attachments']]}")

            if prev:
                if curr["title"] != prev.get("title", ""):
                    items.append({
                        "type":   "제목 변경",
                        "detail": (
                            f"이전: {prev.get('title')}<br>"
                            f"현재: <b>{curr['title']}</b>"
                        ),
                    })

                # 첨부파일 비교는 이름 기준
                prev_names = set(prev.get("attachments", []))
                curr_names = {a["name"] for a in curr["attachments"]}
                added      = curr_names - prev_names
                removed    = prev_names - curr_names

                if added:
                    items.append({
                        "type":   "📎 첨부 추가",
                        "detail": "<br>".join(f"+ {f}" for f in sorted(added)),
                    })
                if removed:
                    items.append({
                        "type":   "🗑️ 첨부 삭제",
                        "detail": "<br>".join(f"- {f}" for f in sorted(removed)),
                    })
            else:
                print("  첫 실행 - 기준값 저장")

            if items:
                # 변경된 경우에만 첨부파일 다운로드
                downloaded = download_attachments(curr["attachments"])
                all_downloaded.extend(downloaded)
                view_changes.append({
                    "label":       view["label"],
                    "url":         view["url"],
                    "items":       items,
                    "body":        curr["body"],
                    "attachments": curr["attachments"],
                    "downloaded":  downloaded,
                })

            # state에는 첨부파일 이름만 저장
            state[view["key"]] = {
                "title":       curr["title"],
                "attachments": [a["name"] for a in curr["attachments"]],
            }

        except Exception as e:
            print(f"  [ERROR] {e}")

    # ③ 결과 처리
    save_state(state)

    if board_changes or view_changes:
        parts = []
        if board_changes:
            total_new = sum(len(b["new_posts"])      for b in board_changes)
            total_mod = sum(len(b["modified_posts"]) for b in board_changes)
            if total_new:
                parts.append(f"새 게시글 {total_new}건")
            if total_mod:
                parts.append(f"제목변경 {total_mod}건")
        if view_changes:
            parts.append("관찰게시글 변경")
        subject = f"📋 [FSS 모니터링] {' · '.join(parts)}"

        print(f"\n변경 사항 발견 → 이메일 발송: {subject}")
        print(f"  첨부파일 총 {len([d for d in all_downloaded if d.get('data')])}개")
        html = build_html(board_changes, view_changes)
        send_email(subject, html, all_downloaded)
    else:
        print("\n변경 사항 없음. 이메일 발송 안 함.")


if __name__ == "__main__":
    main()
