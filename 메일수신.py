# -*- coding: utf-8 -*-
"""다우오피스 IMAP 메일을 과업방으로 브리핑한다.

메일은 원래 받은편지함에 그대로 두고, 새 UID만 한 번씩 처리한다.
광고성·자동발송 메일은 조용히 건너뛰며, 답장·일정 확정은 절대 하지 않는다.
"""

import email
import imaplib
import json
import os
import re
import time
from datetime import timezone, timedelta
from email.header import decode_header
from email.utils import parseaddr

import lark
import 공용


기준폴더 = os.path.dirname(os.path.abspath(__file__))
기록파일 = os.path.join(기준폴더, "처리한_메일.json")
서울 = timezone(timedelta(hours=9))
최대본문글자 = 1200

광고단어 = ("수신동의", "광고", "뉴스레터", "혜택", "프로모션", "쿠폰", "이벤트")
할일단어 = ("요청", "확인", "검토", "제출", "회신", "답장", "마감", "까지", "미팅", "회의", "일정", "계약", "견적", "발행")


def _문자열(value):
    """RFC 헤더의 인코딩을 사람이 읽는 한글 문자열로 바꾼다."""
    if not value:
        return ""
    조각 = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            조각.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            조각.append(text)
    return "".join(조각).strip()


def _본문(message):
    """HTML은 태그를 걷어내고, 일반 텍스트 본문을 우선 사용한다."""
    후보 = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        유형 = part.get_content_type()
        if 유형 not in ("text/plain", "text/html"):
            continue
        try:
            raw = part.get_payload(decode=True) or b""
            text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            continue
        if 유형 == "text/html":
            text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.I | re.S)
            text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            후보.append((0 if 유형 == "text/plain" else 1, text))
    return min(후보, default=(0, ""), key=lambda item: item[0])[1][:최대본문글자]


def _중요한가(제목, 본문, 보낸이):
    전체 = (제목 + " " + 본문).lower()
    if any(word in 전체 for word in 광고단어):
        return False
    if "no-reply" in 보낸이.lower() or "noreply" in 보낸이.lower():
        return any(word in 전체 for word in ("계약", "결제", "발행", "마감", "요청"))
    return any(word in 전체 for word in 할일단어)


def _날짜힌트(본문):
    """확정 등록이 아닌, 사람이 볼 날짜·시간 힌트만 뽑는다."""
    patterns = (
        r"\d{1,2}월\s*\d{1,2}일(?:\s*(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?)?",
        r"\d{1,2}[/.]\d{1,2}(?:\s*(?:오전|오후)?\s*\d{1,2}:?\d{0,2})?",
        r"(?:오늘|내일|모레)\s*(?:오전|오후)?\s*\d{0,2}:?\d{0,2}",
    )
    found = []
    for pattern in patterns:
        found.extend(re.findall(pattern, 본문))
    unique = list(dict.fromkeys(x.strip() for x in found if x.strip()))
    return " · ".join(unique[:3])


def _브리핑(제목, 보낸이, 본문):
    줄 = ["📨 메일 할 일 후보", "• " + 제목, "보낸이: " + (보낸이 or "알 수 없음")]
    날짜 = _날짜힌트(본문)
    if 날짜:
        줄.append("일정·마감 힌트: " + 날짜 + " (확정 전)")
    if 본문:
        줄.append("내용: " + 본문[:500])
    줄.append("→ 처리하려면 이 방에 ‘등록’, 일정이면 ‘일정 등록’이라고 답하세요.")
    return "\n".join(줄)


def _기록읽기():
    try:
        with open(기록파일, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"초기화됨": False, "uid": []}


def _기록쓰기(기록):
    기록["uid"] = 기록.get("uid", [])[-500:]
    with open(기록파일, "w", encoding="utf-8") as f:
        json.dump(기록, f, ensure_ascii=False, indent=2)


def _연결(설정):
    메일 = 설정.get("메일") or {}
    host = 메일.get("imap_host", "imap.daouoffice.com")
    port = int(메일.get("imap_port", 993))
    username = 메일.get("username", "")
    password = 메일.get("password", "")
    if not username or not password:
        raise RuntimeError("메일 계정 또는 비밀번호가 설정되지 않았습니다.")
    client = imaplib.IMAP4_SSL(host, port)
    client.login(username, password)
    status, _ = client.select(메일.get("folder", "Inbox"), readonly=True)
    if status != "OK":
        client.logout()
        raise RuntimeError("받은편지함을 열지 못했습니다.")
    return client


def 한번처리(첫실행_건너뛰기=True):
    설정 = lark.설정읽기()
    메일설정 = 설정.get("메일") or {}
    if not 메일설정.get("enabled", False):
        return 0
    기록 = _기록읽기()
    client = _연결(설정)
    try:
        status, data = client.uid("search", None, "ALL")
        if status != "OK":
            raise RuntimeError("메일 목록을 읽지 못했습니다.")
        uids = data[0].split()[-50:]
        if not 기록.get("초기화됨") and 첫실행_건너뛰기:
            기록.update({"초기화됨": True, "uid": [uid.decode() for uid in uids]})
            _기록쓰기(기록)
            return 0

        처리됨 = set(기록.get("uid", []))
        보낸수 = 0
        for uid in uids:
            uid_text = uid.decode()
            if uid_text in 처리됨:
                continue
            status, raw = client.uid("fetch", uid, "(RFC822)")
            if status != "OK" or not raw or not raw[0]:
                continue
            message = email.message_from_bytes(raw[0][1])
            제목 = _문자열(message.get("Subject")) or "제목 없음"
            보낸이 = parseaddr(_문자열(message.get("From")))[1] or _문자열(message.get("From"))
            본문 = _본문(message)
            if _중요한가(제목, 본문, 보낸이):
                token = lark.토큰받기(설정)
                lark.메시지보내기(token, 설정["과업"]["chat_id"], _브리핑(제목, 보낸이, 본문))
                보낸수 += 1
            기록.setdefault("uid", []).append(uid_text)
            _기록쓰기(기록)
        return 보낸수
    finally:
        try:
            client.logout()
        except Exception:
            pass


def main():
    while True:
        try:
            보낸수 = 한번처리()
            if 보낸수:
                공용.로그().info("메일 브리핑 %d건 전송", 보낸수)
        except Exception:
            공용.로그().exception("메일 브리핑 실패")
        time.sleep(90)


if __name__ == "__main__":
    main()
