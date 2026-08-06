# -*- coding: utf-8 -*-
"""
구글 캘린더에 일정을 등록하는 도구입니다. (서비스 계정 열쇠 사용)
"""

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import 공용

기준폴더 = os.path.dirname(os.path.abspath(__file__))
열쇠파일 = os.path.join(기준폴더, "google-key.json")
설정파일 = os.path.join(기준폴더, "config.json")


def 설정읽기():
    with open(설정파일, "r", encoding="utf-8") as f:
        return json.load(f)


def 서비스():
    # 인증 방식:
    #  1) 키 파일(google-key.json)이 있으면 그걸로 인증한다(기존 방식).
    #  2) 키 파일이 없으면 VM에 붙은 서비스계정으로 자동 인증한다(ADC).
    #     → 키 파일을 디스크에서 없애도 동작하게 하는 "키리스" 대비.
    스코프 = ["https://www.googleapis.com/auth/calendar"]
    if os.path.exists(열쇠파일):
        인증 = service_account.Credentials.from_service_account_file(
            열쇠파일, scopes=스코프
        )
    else:
        import google.auth
        인증, _ = google.auth.default(scopes=스코프)
    return build("calendar", "v3", credentials=인증, cache_discovery=False)


def 일정등록(제목, 시작ISO, 끝ISO, 종일=False, 설명="", 글ID=None):
    """일정을 구글 캘린더에 등록한다.
    글ID를 주면 그걸 해시해 이벤트 id로 고정한다(멱등 등록) — 같은 글이 재전송되거나
    등록 직후 프로세스가 죽었다 다시 처리돼도 같은 id라 중복 등록되지 않는다.
    이미 있으면 캘린더가 409를 주는데, 그걸 '이미 등록됨'으로 조용히 넘긴다.
    일시적 네트워크·서버 오류는 몇 번 재시도한다."""
    설정 = 설정읽기()
    cal = 설정["calendar_id"]
    tz = 설정.get("time_zone", "Asia/Seoul")
    if 종일:
        본문 = {
            "summary": 제목,
            "description": 설명,
            "start": {"date": 시작ISO},
            "end": {"date": 끝ISO},
        }
    else:
        본문 = {
            "summary": 제목,
            "description": 설명,
            "start": {"dateTime": 시작ISO, "timeZone": tz},
            "end": {"dateTime": 끝ISO, "timeZone": tz},
        }
    if 글ID:
        본문["id"] = 공용.이벤트해시(글ID)

    def _등록():
        return 서비스().events().insert(calendarId=cal, body=본문).execute()

    try:
        # 409(중복)는 재시도 대상이 아니다 → 아래 except HttpError에서 따로 처리하도록,
        # 재시도는 그 외 예외에만 걸리게 한다.
        결과 = 공용.재시도(_등록, 다시시도예외=(ConnectionError, TimeoutError, OSError))
    except HttpError as e:
        if 글ID and getattr(e, "resp", None) is not None and e.resp.status == 409:
            공용.로그().info("캘린더 이미등록(409) 글ID=%s 제목=%s", 글ID, 제목)
            return {"중복": True}          # 이미 등록됨 — 조용히 성공 취급
        raise
    공용.로그().info("캘린더 등록 글ID=%s 제목=%s", 글ID, 제목)
    return 결과


def 일정목록(시작ISO, 끝ISO):
    """시작~끝 기간의 일정을 시간순으로 가져옵니다. (ISO 예: '2026-06-02T00:00:00+09:00')"""
    설정 = 설정읽기()
    결과 = 서비스().events().list(
        calendarId=설정["calendar_id"], timeMin=시작ISO, timeMax=끝ISO,
        singleEvents=True, orderBy="startTime",
    ).execute()
    return 결과.get("items", [])


def 일정수정(이벤트ID, 제목, 시작ISO, 끝ISO, 종일=False, 설명=""):
    """이벤트ID가 가리키는 일정 한 건을 수정한다."""
    설정 = 설정읽기()
    tz = 설정.get("time_zone", "Asia/Seoul")
    본문 = {"summary": 제목, "description": 설명}
    if 종일:
        본문["start"] = {"date": 시작ISO}
        본문["end"] = {"date": 끝ISO}
    else:
        본문["start"] = {"dateTime": 시작ISO, "timeZone": tz}
        본문["end"] = {"dateTime": 끝ISO, "timeZone": tz}

    결과 = 공용.재시도(
        lambda: 서비스().events().patch(
            calendarId=설정["calendar_id"], eventId=이벤트ID, body=본문
        ).execute(),
        다시시도예외=(ConnectionError, TimeoutError, OSError),
    )
    공용.로그().info("캘린더 수정 event=%s 제목=%s", 이벤트ID, 제목)
    return 결과


def 일정삭제(이벤트ID):
    """이벤트ID가 가리키는 일정 한 건을 삭제한다."""
    설정 = 설정읽기()
    공용.재시도(
        lambda: 서비스().events().delete(
            calendarId=설정["calendar_id"], eventId=이벤트ID
        ).execute(),
        다시시도예외=(ConnectionError, TimeoutError, OSError),
    )
    공용.로그().info("캘린더 삭제 event=%s", 이벤트ID)


if __name__ == "__main__":
    # 연결 테스트: 내일 오후 3시에 테스트 일정 하나 넣어봅니다.
    r = 일정등록(
        "🔧 연결 테스트 (지워도 됨)",
        "2026-06-06T15:00:00",
        "2026-06-06T16:00:00",
        설명="서비스 계정 연결 확인용",
    )
    print("등록 성공! 일정 링크:", r.get("htmlLink"))
