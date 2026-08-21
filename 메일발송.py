# -*- coding: utf-8 -*-
"""다우오피스 메일 발송과 보낸메일함 기록을 한 번에 처리한다.

SMTP 발송만으로는 다우오피스 보낸메일함에 사본이 남지 않으므로,
성공적으로 발송한 원문을 같은 계정의 Sent 메일함에 바로 저장한다.
"""

import argparse
import imaplib
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

import lark


def 발송(수신자, 제목, 본문, 참조=()):
    """메일을 발송하고, 성공한 동일 원문을 보낸메일함에 기록한다."""
    설정 = lark.설정읽기()
    메일 = 설정.get("메일") or {}
    계정 = 메일.get("username", "")
    비밀번호 = 메일.get("password", "")
    if not 계정 or not 비밀번호:
        raise RuntimeError("다우오피스 발송 계정 설정이 없습니다.")

    메시지 = EmailMessage()
    메시지["Date"] = formatdate(localtime=True)
    메시지["Message-ID"] = make_msgid(domain="qnbang.com")
    메시지["From"] = 계정
    메시지["To"] = 수신자
    메시지["Subject"] = 제목
    if 참조:
        메시지["Cc"] = ", ".join(참조)
    메시지.set_content(본문)

    smtp_host = 메일.get("smtp_host", "smtp.daouoffice.com")
    smtp_port = int(메일.get("smtp_port", 465))
    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as 서버:
        서버.login(계정, 비밀번호)
        거부됨 = 서버.send_message(메시지)
    if 거부됨:
        raise RuntimeError(f"수신 거부: {거부됨}")

    imap_host = 메일.get("imap_host", "imap.daouoffice.com")
    imap_port = int(메일.get("imap_port", 993))
    with imaplib.IMAP4_SSL(imap_host, imap_port) as 서버:
        서버.login(계정, 비밀번호)
        상태, 응답 = 서버.append("Sent", "\\Seen", None, 메시지.as_bytes())
        if 상태 != "OK":
            raise RuntimeError(f"발송은 완료됐지만 보낸메일함 기록에 실패했습니다: {응답}")


def main():
    파서 = argparse.ArgumentParser(description="다우오피스 메일 발송 후 보낸메일함에 자동 기록")
    파서.add_argument("--수신자", required=True)
    파서.add_argument("--제목", required=True)
    파서.add_argument("--본문파일", required=True)
    파서.add_argument("--참조", action="append", default=[])
    인자 = 파서.parse_args()
    본문 = Path(인자.본문파일).read_text(encoding="utf-8")
    발송(인자.수신자, 인자.제목, 본문, 인자.참조)
    print("발송 및 보낸메일함 기록 완료")


if __name__ == "__main__":
    main()
