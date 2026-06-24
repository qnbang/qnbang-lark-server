# -*- coding: utf-8 -*-
"""
라크(Lark)와 대화하는 도구입니다. 외부 라이브러리 없이 동작합니다.

사용법:
  python3 lark.py 연결확인          - 봇 접속이 되는지 확인합니다
  python3 lark.py 방목록            - 봇이 들어가 있는 방 목록(이름·ID)을 보여줍니다
  python3 lark.py 새글              - 아직 처리 안 한 '!일정' 글만 골라 보여줍니다(JSON)
  python3 lark.py 보내기 "내용"      - 방에 답글(메시지)을 보냅니다
  python3 lark.py 처리완료 <글ID>    - 그 글을 '처리함'으로 기록(중복 등록 방지)
"""

import json
import sys
import os
import time
import urllib.request
import urllib.error

기준폴더 = os.path.dirname(os.path.abspath(__file__))
설정파일 = os.path.join(기준폴더, "config.json")
처리기록파일 = os.path.join(기준폴더, "처리한_글.json")
토큰캐시파일 = os.path.join(기준폴더, "토큰캐시.json")
도메인 = "https://open.larksuite.com"


def 설정읽기():
    with open(설정파일, "r", encoding="utf-8") as f:
        return json.load(f)


def 처리기록읽기():
    if not os.path.exists(처리기록파일):
        return []
    with open(처리기록파일, "r", encoding="utf-8") as f:
        return json.load(f)


def 처리기록쓰기(목록):
    with open(처리기록파일, "w", encoding="utf-8") as f:
        json.dump(목록, f, ensure_ascii=False, indent=2)


def _요청(method, 경로, 토큰=None, 본문=None):
    url = 도메인 + 경로
    헤더 = {"Content-Type": "application/json; charset=utf-8"}
    if 토큰:
        헤더["Authorization"] = "Bearer " + 토큰
    데이터 = json.dumps(본문).encode("utf-8") if 본문 is not None else None
    req = urllib.request.Request(url, data=데이터, headers=헤더, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def 토큰받기(설정):
    # 아직 살아있는 토큰이 있으면 새로 받지 않고 재사용합니다 (10초마다 새로 받는 낭비 방지)
    try:
        with open(토큰캐시파일, "r", encoding="utf-8") as f:
            캐시 = json.load(f)
        if 캐시.get("만료", 0) - 60 > time.time():
            return 캐시["token"]
    except Exception:
        pass

    결과 = _요청(
        "POST",
        "/open-apis/auth/v3/tenant_access_token/internal",
        본문={"app_id": 설정["app_id"], "app_secret": 설정["app_secret"]},
    )
    if 결과.get("code") != 0:
        raise SystemExit("토큰 발급 실패: " + json.dumps(결과, ensure_ascii=False))
    토큰 = 결과["tenant_access_token"]

    try:
        만료 = time.time() + 결과.get("expire", 7200)
        with open(토큰캐시파일, "w", encoding="utf-8") as f:
            json.dump({"token": 토큰, "만료": 만료}, f)
    except Exception:
        pass
    return 토큰


def 방목록(토큰):
    결과 = _요청("GET", "/open-apis/im/v1/chats?page_size=100", 토큰=토큰)
    if 결과.get("code") != 0:
        raise SystemExit("방 목록 실패: " + json.dumps(결과, ensure_ascii=False))
    return 결과.get("data", {}).get("items", [])


def 최근글(토큰, chat_id, 개수=30):
    경로 = (
        "/open-apis/im/v1/messages?container_id_type=chat"
        "&container_id=" + chat_id + "&sort_type=ByCreateTimeAsc&page_size=" + str(개수)
    )
    결과 = _요청("GET", 경로, 토큰=토큰)
    if 결과.get("code") != 0:
        raise SystemExit("글 읽기 실패: " + json.dumps(결과, ensure_ascii=False))
    return 결과.get("data", {}).get("items", [])


def 글에서_본문뽑기(글):
    """텍스트 글이든 코드블록 글이든, 안에 들어있는 모든 글자를 모아 한 줄로 만듭니다."""
    raw = 글.get("body", {}).get("content", "")
    try:
        파싱 = json.loads(raw)
    except Exception:
        return raw.strip()
    모음 = []

    def 훑기(obj):
        if isinstance(obj, dict):
            if "text" in obj and isinstance(obj["text"], str):
                모음.append(obj["text"])
            for v in obj.values():
                훑기(v)
        elif isinstance(obj, list):
            for v in obj:
                훑기(v)

    훑기(파싱)
    return " ".join(t.strip() for t in 모음 if t.strip()).strip()


def 파일보내기(토큰, chat_id, 파일바이트, 파일명):
    """PDF 등 파일을 라크 방에 업로드하고 메시지로 전송합니다."""
    boundary = b"----LarkFileBoundary"
    crlf = b"\r\n"

    def _field(이름, 값):
        return (
            b"--" + boundary + crlf
            + b'Content-Disposition: form-data; name="' + 이름.encode() + b'"' + crlf
            + crlf
            + (값 if isinstance(값, bytes) else 값.encode("utf-8"))
            + crlf
        )

    def _file_field(이름, 파일명, 내용):
        return (
            b"--" + boundary + crlf
            + b'Content-Disposition: form-data; name="' + 이름.encode()
            + b'"; filename="' + 파일명.encode("utf-8") + b'"' + crlf
            + b"Content-Type: application/octet-stream" + crlf
            + crlf
            + 내용
            + crlf
        )

    body = (
        _field("file_type", "stream")
        + _field("file_name", 파일명)
        + _file_field("file", 파일명, 파일바이트)
        + b"--" + boundary + b"--" + crlf
    )

    req = urllib.request.Request(
        도메인 + "/open-apis/im/v1/files",
        data=body,
        headers={
            "Authorization": "Bearer " + 토큰,
            "Content-Type": "multipart/form-data; boundary=" + boundary.decode(),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            결과 = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        결과 = json.loads(e.read().decode("utf-8"))

    if 결과.get("code") != 0:
        raise RuntimeError("파일 업로드 실패: " + str(결과.get("msg")))

    file_key = 결과["data"]["file_key"]

    # 파일 메시지 전송
    _요청(
        "POST",
        "/open-apis/im/v1/messages?receive_id_type=chat_id",
        토큰=토큰,
        본문={
            "receive_id": chat_id,
            "msg_type": "file",
            "content": json.dumps({"file_key": file_key}, ensure_ascii=False),
        },
    )


def 메시지보내기(토큰, chat_id, 내용):
    본문 = {
        "receive_id": chat_id,
        "msg_type": "text",
        "content": json.dumps({"text": 내용}, ensure_ascii=False),
    }
    결과 = _요청(
        "POST",
        "/open-apis/im/v1/messages?receive_id_type=chat_id",
        토큰=토큰,
        본문=본문,
    )
    if 결과.get("code") != 0:
        # 답글 전송이 실패해도(예: 라크 월 한도 초과) 프로그램을 죽이지 않고 조용히 넘어갑니다.
        # 기록(캘린더·시트)은 이미 됐으므로 핵심 기능은 유지됩니다.
        print("답글 전송 실패(무시):", 결과.get("code"), 결과.get("msg"))
    return 결과


def 파일다운로드(토큰, message_id, file_key, 종류="file"):
    """라크 메시지의 첨부 파일/이미지를 바이트로 받는다. (종류: file | image)"""
    url = (도메인 + "/open-apis/im/v1/messages/%s/resources/%s?type=%s"
           % (message_id, file_key, 종류))
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + 토큰}, method="GET")
    with urllib.request.urlopen(req) as resp:
        return resp.read()


def 웹훅보내기(웹훅url, text):
    """무료 사용자지정봇 웹훅으로 텍스트 전송(봇 API 월 한도와 무관)."""
    데이터 = json.dumps({"msg_type": "text", "content": {"text": text}},
                      ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(웹훅url, data=데이터,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def main():
    명령 = sys.argv[1] if len(sys.argv) > 1 else "연결확인"
    설정 = 설정읽기()

    if "App_Secret" in 설정.get("app_secret", ""):
        raise SystemExit("⚠️  config.json에 App Secret을 아직 안 넣으셨어요. 먼저 넣어주세요.")

    토큰 = 토큰받기(설정)
    chat_id = 설정.get("chat_id", "")
    트리거 = 설정.get("trigger", "!일정")

    if 명령 == "연결확인":
        print("✅ 봇 접속 성공! App Secret이 올바릅니다.")
        return

    if 명령 == "방목록":
        방들 = 방목록(토큰)
        if not 방들:
            print("봇이 아직 어떤 방에도 안 들어가 있어요.")
            return
        for 방 in 방들:
            print("  - 이름: %s   |   방ID: %s" % (방.get("name", "(이름없음)"), 방.get("chat_id")))
        return

    if 명령 == "새글":
        if not chat_id:
            raise SystemExit("config.json의 chat_id가 비어 있어요.")
        이미처리 = set(처리기록읽기())
        새것 = []
        for 글 in 최근글(토큰, chat_id):
            글ID = 글.get("message_id")
            본문 = 글에서_본문뽑기(글)
            if 본문.startswith(트리거) and 글ID not in 이미처리:
                새것.append({"글ID": 글ID, "본문": 본문})
        print(json.dumps(새것, ensure_ascii=False, indent=2))
        return

    if 명령 == "보내기":
        if len(sys.argv) < 3:
            raise SystemExit("보낼 내용을 적어주세요. 예: python3 lark.py 보내기 \"등록됐어요\"")
        메시지보내기(토큰, chat_id, sys.argv[2])
        print("보냈습니다.")
        return

    if 명령 == "처리완료":
        if len(sys.argv) < 3:
            raise SystemExit("처리할 글ID를 적어주세요.")
        기록 = 처리기록읽기()
        for 글ID in sys.argv[2:]:
            if 글ID not in 기록:
                기록.append(글ID)
        처리기록쓰기(기록)
        print("기록했습니다.")
        return

    print("알 수 없는 명령입니다.")


if __name__ == "__main__":
    main()
