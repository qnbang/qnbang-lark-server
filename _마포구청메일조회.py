# -*- coding: utf-8 -*-
import email, imaplib, sys
from email.header import decode_header
from email.utils import parseaddr
sys.path.insert(0, "/home/charlie/lark-calendar")
import lark

def 문자열(value):
    if not value:
        return ""
    조각 = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            조각.append(text.decode(charset or "utf-8", errors="replace"))
        else:
            조각.append(text)
    return "".join(조각).strip()

def 본문(message):
    후보 = []
    parts = message.walk() if message.is_multipart() else [message]
    for part in parts:
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            try:
                후보.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace"))
            except Exception:
                pass
    if not 후보:
        for part in parts:
            if part.get_content_type() == "text/html":
                try:
                    import re
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    text = re.sub("<[^>]+>", " ", html)
                    후보.append(text)
                except Exception:
                    pass
    return "\n".join(후보).strip()

설정 = lark.설정읽기()
메일 = 설정.get("메일") or {}
host = 메일.get("imap_host", "imap.daouoffice.com")
port = int(메일.get("imap_port", 993))
username = 메일.get("username", "")
password = 메일.get("password", "")
client = imaplib.IMAP4_SSL(host, port)
client.login(username, password)
client.select(메일.get("folder", "Inbox"), readonly=True)

status, data = client.uid("search", None, "ALL")
uids = data[0].split()
print(f"전체 메일 {len(uids)}건 중 마포구청 검색", file=sys.stderr)

found = []
for uid in reversed(uids):
    status, raw = client.uid("fetch", uid, "(RFC822)")
    if status != "OK" or not raw or not raw[0]:
        continue
    message = email.message_from_bytes(raw[0][1])
    제목 = 문자열(message.get("Subject")) or ""
    보낸이헤더 = 문자열(message.get("From")) or ""
    if "마포구청" in 제목 or "마포구청" in 보낸이헤더 or "mapo" in 보낸이헤더.lower():
        날짜 = 문자열(message.get("Date"))
        found.append((uid.decode(), 제목, 보낸이헤더, 날짜, 본문(message)))

client.logout()
print(f"매칭 {len(found)}건", file=sys.stderr)
for uid, 제목, 보낸이, 날짜, 텍스트 in found:
    print("="*60)
    print("UID:", uid)
    print("제목:", 제목)
    print("보낸이:", 보낸이)
    print("날짜:", 날짜)
    print("본문:")
    print(텍스트[:3000])
