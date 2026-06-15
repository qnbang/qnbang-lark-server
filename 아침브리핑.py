# -*- coding: utf-8 -*-
"""
매일 아침, 라크 채팅방으로 '오늘의 브리핑'을 보냅니다.
  - 오늘 미팅/일정 : 구글 캘린더(큐앤뱅)의 오늘 일정
  - 안 끝난 할 일   : 업무 대시보드(tasks.json)에서 아직 완료 안 된 일 (어제까지 못 끝낸 것 포함)

사용법:
  ./venv/bin/python 아침브리핑.py            → 실제로 라크에 보냄
  ./venv/bin/python 아침브리핑.py --미리보기   → 보내지 않고 화면에만 출력 (테스트용)
"""

import sys
import json
import urllib.request
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import lark
import calendar_api

TASKS = "/home/charlie/lark-calendar/업무-대시보드/tasks.json"
# 오늘 브리핑을 이미 보냈는지 표시해 두는 파일(하루 한 번만 보내기 위함)
보낸기록파일 = "/Users/charlie/Documents/claude-workspace/projects/큐앤뱅_라크_자동화/브리핑_보낸날짜.txt"
서울 = ZoneInfo("Asia/Seoul")
# 이 시각(9시) 전에는 부팅 실행이어도 보내지 않는다(아침 브리핑이므로)
보내는시각_시 = 9


def 이미보냈나(오늘날짜):
    try:
        with open(보낸기록파일, "r", encoding="utf-8") as f:
            return f.read().strip() == 오늘날짜
    except FileNotFoundError:
        return False


def 보냄표시(오늘날짜):
    with open(보낸기록파일, "w", encoding="utf-8") as f:
        f.write(오늘날짜)

요일한글 = ["월", "화", "수", "목", "금", "토", "일"]

# 할 일 상태 — 대시보드와 동일한 값/순서
상태단계 = [
    ("todo", "🟦 시작 전"),
    ("doing", "🟨 진행 중"),
    ("wait", "🟧 피드백 대기"),
]


def 할일읽기():
    try:
        with open(TASKS, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return []


def 일정시각표시(ev):
    s = ev.get("start", {})
    if "date" in s:                       # 하루 종일 일정
        return "하루종일"
    dt = datetime.fromisoformat(s["dateTime"])
    return dt.astimezone(서울).strftime("%H:%M")


def 브리핑만들기():
    오늘 = datetime.now(서울)
    오늘날짜 = 오늘.strftime("%Y-%m-%d")
    머리 = f"☀️ {오늘.strftime('%m월 %d일')}({요일한글[오늘.weekday()]}) 굿모닝!"

    # --- 오늘 일정 (구글 캘린더) ---
    시작 = 오늘.strftime("%Y-%m-%dT00:00:00+09:00")
    끝 = (오늘 + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+09:00")
    try:
        일정들 = calendar_api.일정목록(시작, 끝)
    except Exception as e:
        일정들 = []
        print("캘린더 읽기 실패:", e)

    # 보드 '할일'에서 만든 캘린더 일정만 '미팅/일정'에서 제외한다(할 일 칸에 이미 나오므로).
    # 표식 '#보드할일' 로만 판단한다. (라크 일정방이 넣는 '미팅'은 이 표식이 없으므로 미팅/일정에 정상 표시됨.)
    def 보드할일인가(ev):
        return "#보드할일" in (ev.get("description") or "")

    실제일정 = [ev for ev in 일정들 if not 보드할일인가(ev)]

    일정줄 = []
    for ev in 실제일정:
        일정줄.append(f"  • {일정시각표시(ev)}  {ev.get('summary', '(제목 없음)')}")
    일정구간 = "📅 오늘 미팅/일정\n" + ("\n".join(일정줄) if 일정줄 else "  • 등록된 일정 없음")

    # --- 할 일 (오늘 위주) ---
    미완 = [t for t in 할일읽기() if t.get("status") != "done"]

    def 날짜(t):
        return (t.get("date") or "").strip()

    기한지남 = [t for t in 미완 if 날짜(t) and 날짜(t) < 오늘날짜]
    오늘마감 = [t for t in 미완 if 날짜(t) == 오늘날짜]
    날짜없는진행 = [t for t in 미완 if not 날짜(t) and (t.get("status") == "doing")]
    # 오늘 손대야 할 일 = 기한 지남 + 오늘 마감 + 날짜 없는 진행 중 (미래 날짜는 제외)
    오늘할일 = 기한지남 + 오늘마감 + 날짜없는진행

    상태표 = {"todo": "시작 전", "doing": "진행 중", "wait": "피드백 대기"}

    def 한줄(t):
        c = (t.get("client") or "").strip()
        제목 = t.get("title", "")
        # 제목 앞에 고객명이 붙어 있으면 떼어낸다(중복 방지). [고객] 태그는 항상 앞에 붙인다.
        if c and 제목.startswith(c):
            제목 = 제목[len(c):].lstrip(" -·").strip()
        고객 = f"[{c}] " if c else ""
        급함 = "🔴 " if t.get("urgent") else ""
        d = 날짜(t)
        꼬리 = ""
        if d and d < 오늘날짜:
            꼬리 = f" (⚠️기한 지남 {d})"
        elif d == 오늘날짜:
            꼬리 = " (오늘 마감)"
        return f"    • {급함}{고객}{제목}{꼬리}"

    if 오늘할일:
        블록 = ["🎯 오늘 할 일"]
        # 시작 전 → 진행 중 → 피드백 대기 순, 각 상태 안에서는 고객사별로 모으고 급한 일 먼저
        for 키, 라벨 in 상태단계:
            무리 = [t for t in 오늘할일 if (t.get("status") or "todo") == 키]
            if not 무리:
                continue
            무리.sort(key=lambda t: ((t.get("client") or ""), 0 if t.get("urgent") else 1))
            블록.append(라벨)
            블록.extend(한줄(t) for t in 무리)
        오늘구간 = "\n".join(블록)
    else:
        오늘구간 = "🎯 오늘 할 일\n  • 딱 잡힌 마감은 없어요. 진행 중인 것 이어가면 돼요."

    # 전체 진행 상황은 상태별 개수만 한 줄로
    조각 = []
    for 키, 라벨 in 상태단계:
        n = sum(1 for t in 미완 if (t.get("status") or "todo") == 키)
        조각.append(f"{라벨.split(' ', 1)[1]} {n}")
    그외구간 = "📋 전체 진행 상황\n  • " + " · ".join(조각)

    # 오늘 한마디 (규칙 기반 — 우선순위를 보고 한 줄)
    급한수 = sum(1 for t in 미완 if t.get("urgent"))
    if 기한지남:
        한마디 = f"기한 지난 {len(기한지남)}건부터 털고 가면 마음이 가벼워요."
    elif 오늘마감:
        한마디 = f"오늘 마감 {len(오늘마감)}건 먼저 챙기세요."
    elif 급한수:
        한마디 = f"급한 일 {급한수}건부터 손대는 게 좋아요."
    elif any(t.get("status") == "doing" for t in 미완):
        한마디 = "새로 벌이기보다 진행 중인 것 하나를 끝내는 날로."
    else:
        한마디 = "여유 있는 아침이네요. 밀린 것 하나 당겨오기 좋아요."
    한마디구간 = f"💬 오늘 한마디\n  {한마디}"

    요약 = f"오늘 할 일 {len(오늘할일)}개 · 급함 {급한수}개 · 미팅 {len(실제일정)}건"

    # 요일별 마무리 인사 (월=0 … 일=6)
    요일인사 = {
        0: "새 한 주 시작이에요. 욕심내지 말고 하나씩 가요 💪",
        1: "화요일, 어제 흐름 그대로 이어가면 돼요 🙂",
        2: "벌써 주 중반! 페이스 좋습니다 🐢",
        3: "목요일이에요. 한 고비만 넘기면 주말이 보여요 ⛰️",
        4: "금요일! 오늘만 달리면 주말이에요 🎉",
        5: "주말까지 챙기시네요. 무리하지 말고 ☕",
        6: "일요일도 고생 많아요. 잠깐이라도 쉬어가요 🌿",
    }
    인사 = 요일인사.get(오늘.weekday(), "좋은 하루 보내세요 🙌")

    return f"{머리}\n{요약}\n\n{오늘구간}\n\n{일정구간}\n\n{그외구간}\n\n{한마디구간}\n\n{인사}"


def 웹훅으로보내기(웹훅주소, 내용):
    """라크 '사용자 지정 봇' 웹훅으로 메시지를 보냅니다. (월 API 한도와 무관, 무료)"""
    데이터 = json.dumps(
        {"msg_type": "text", "content": {"text": 내용}}, ensure_ascii=False
    ).encode("utf-8")
    요청 = urllib.request.Request(
        웹훅주소, data=데이터, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(요청, timeout=15) as 응답:
        결과 = json.loads(응답.read().decode("utf-8"))
    # 웹훅 성공 시 {"code":0,...} 또는 {"StatusCode":0,...} 형태
    if 결과.get("code") not in (0, None) or 결과.get("StatusCode", 0) not in (0,):
        if 결과.get("code", 0) != 0:
            print("웹훅 전송 응답:", json.dumps(결과, ensure_ascii=False))
    return 결과


def main():
    # 미리보기: 보내지 않고 화면에만
    if "--미리보기" in sys.argv:
        print(브리핑만들기())
        return

    오늘 = datetime.now(서울)
    오늘날짜 = 오늘.strftime("%Y-%m-%d")
    강제 = "--강제" in sys.argv  # 테스트용: 시간·중복 제한 무시

    if not 강제:
        # 1) 오늘 이미 보냈으면 건너뜀 (부팅 실행으로 두 번 보내지 않도록)
        if 이미보냈나(오늘날짜):
            print(f"오늘({오늘날짜}) 브리핑은 이미 보냈습니다. 건너뜀.")
            return
        # 2) 아침 9시 전이면 보내지 않음 (이른 부팅 실행 대비). 9시 예약 실행이 보냄.
        if 오늘.hour < 보내는시각_시:
            print(f"아직 {보내는시각_시}시 전입니다({오늘.strftime('%H:%M')}). 건너뜀.")
            return

    본문 = 브리핑만들기()
    설정 = lark.설정읽기()
    웹훅 = 설정.get("브리핑_webhook")
    if 웹훅:
        결과 = 웹훅으로보내기(웹훅, 본문)
        print("라크로 아침 브리핑을 보냈습니다. (웹훅)", 결과.get("code", 결과))
    else:
        # 웹훅 주소가 없으면 예전 방식(앱 봇 메시지)으로 보냄
        토큰 = lark.토큰받기(설정)
        lark.메시지보내기(토큰, 설정["chat_id"], 본문)
        print("라크로 아침 브리핑을 보냈습니다. (앱 봇)")

    # 보냈음 도장 — 오늘은 다시 안 보냄
    if not 강제:
        보냄표시(오늘날짜)


if __name__ == "__main__":
    main()
