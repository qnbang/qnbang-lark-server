# -*- coding: utf-8 -*-
"""
업무 대시보드(tasks.json)에 적힌 할 일 중 '날짜가 정해진 것'을 구글 캘린더(큐앤뱅)에 자동 등록합니다.

규칙:
- date 값이 있는 할 일만 캘린더에 올립니다. (date 비어 있으면 건너뜀)
- 이미 완료(done)된 할 일은 올리지 않습니다.
- time 이 있으면 그 시각 1시간짜리 일정, 없으면 그날 하루 종일 일정으로 등록합니다.
- 한 번 등록한 할 일에는 calEventId(캘린더 일정 번호)를 적어두어, 다음에 또 돌려도 중복으로 안 올립니다.

사용법: 이 폴더의 venv 파이썬으로 실행
  ./venv/bin/python 할일동기화.py
"""

import json
from datetime import datetime, timedelta

import calendar_api  # 같은 폴더의 캘린더 도구 재사용

# 업무 대시보드의 할 일 파일 위치
TASKS = "/home/charlie/lark-calendar/업무-대시보드/tasks.json"


def 할일읽기():
    try:
        with open(TASKS, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def 할일쓰기(목록):
    with open(TASKS, "w", encoding="utf-8") as f:
        json.dump(목록, f, ensure_ascii=False, indent=2)


def 동기화():
    할일들 = 할일읽기()
    바뀜 = False
    올린수 = 0

    for t in 할일들:
        날짜 = (t.get("date") or "").strip()
        if not 날짜:
            continue                      # 날짜 없는 할 일은 캘린더에 안 올림
        if t.get("status") == "done":
            continue                      # 완료된 일은 제외
        if t.get("calEventId"):
            continue                      # 이미 올린 일은 건너뜀 (중복 방지)

        고객 = (t.get("client") or "").strip()
        제목 = t.get("title") or "(제목 없음)"
        보이는제목 = f"[{고객}] {제목}" if 고객 else 제목
        메모 = t.get("note") or ""
        설명 = (메모 + "\n\n").strip() + "※ 업무 대시보드에서 자동 등록됨 #보드할일"

        시간 = (t.get("time") or "").strip()
        if 시간:
            # 시각이 있으면 그 시각부터 1시간짜리 일정
            시작 = f"{날짜}T{시간}:00"
            끝dt = datetime.strptime(시작, "%Y-%m-%dT%H:%M:%S") + timedelta(hours=1)
            끝 = 끝dt.strftime("%Y-%m-%dT%H:%M:%S")
            결과 = calendar_api.일정등록(보이는제목, 시작, 끝, 종일=False, 설명=설명)
        else:
            # 시각이 없으면 그날 하루 종일 일정 (끝 날짜는 다음날)
            끝날짜 = (datetime.strptime(날짜, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
            결과 = calendar_api.일정등록(보이는제목, 날짜, 끝날짜, 종일=True, 설명=설명)

        t["calEventId"] = 결과.get("id", "")
        바뀜 = True
        올린수 += 1
        print(f"등록: {보이는제목}  ({날짜} {시간 or '하루종일'})")

    if 바뀜:
        할일쓰기(할일들)
    print(f"\n완료 — 새로 등록한 할 일 {올린수}개")


if __name__ == "__main__":
    동기화()
