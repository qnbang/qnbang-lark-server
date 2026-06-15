# -*- coding: utf-8 -*-
"""
구글 캘린더에 일정을 등록하는 도구입니다. (서비스 계정 열쇠 사용)
"""

import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build

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


def 일정등록(제목, 시작ISO, 끝ISO, 종일=False, 설명=""):
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
    결과 = 서비스().events().insert(calendarId=cal, body=본문).execute()
    return 결과


def 일정목록(시작ISO, 끝ISO):
    """시작~끝 기간의 일정을 시간순으로 가져옵니다. (ISO 예: '2026-06-02T00:00:00+09:00')"""
    설정 = 설정읽기()
    결과 = 서비스().events().list(
        calendarId=설정["calendar_id"], timeMin=시작ISO, timeMax=끝ISO,
        singleEvents=True, orderBy="startTime",
    ).execute()
    return 결과.get("items", [])


if __name__ == "__main__":
    # 연결 테스트: 내일 오후 3시에 테스트 일정 하나 넣어봅니다.
    r = 일정등록(
        "🔧 연결 테스트 (지워도 됨)",
        "2026-06-06T15:00:00",
        "2026-06-06T16:00:00",
        설명="서비스 계정 연결 확인용",
    )
    print("등록 성공! 일정 링크:", r.get("htmlLink"))
