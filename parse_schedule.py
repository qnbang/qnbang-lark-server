# -*- coding: utf-8 -*-
"""
'!일정 6월 10일 오후 3시 큐앤뱅 미팅' 같은 한국어 글에서
날짜·시간·제목을 알아서 뽑아냅니다.

해석(원문) -> 딕셔너리
  성공: {"ok": True, "제목": ..., "시작": "2026-06-10T15:00:00", "끝": ..., "종일": False}
  실패: {"ok": False, "이유": "날짜가 없어요"}   (등록 안 하고 되묻기용)

규칙:
- 끝나는 시간을 안 적으면 시작 +1시간으로 잡습니다.
- 오전/오후를 안 적은 경우: 1~6시는 오후, 7~11시는 오전, 12시는 정오로 봅니다.
- '종일'이라고 쓰면 하루종일 일정으로 만듭니다.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

서울 = ZoneInfo("Asia/Seoul")
요일맵 = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}
# 숫자 없이 '저녁'처럼 시간대만 말했을 때 쓰는 기본 시각
기본시각 = {"새벽": 6, "아침": 8, "점심": 12, "낮": 13, "저녁": 18, "밤": 20}


def 지금():
    return datetime.now(서울)


def _연도보정(오늘, 월, 일):
    해 = 오늘.year
    try:
        후보 = datetime(해, 월, 일, tzinfo=서울).date()
    except ValueError:
        return None
    if 후보 < 오늘.date():
        후보 = datetime(해 + 1, 월, 일, tzinfo=서울).date()
    return 후보


def _요일계산(오늘, 목표, 기준):
    기준요일 = 오늘.weekday()
    이번주월 = 오늘.date() - timedelta(days=기준요일)
    if "다음" in 기준 or "담" in 기준:
        return 이번주월 + timedelta(days=7 + 목표)
    if "이번" in 기준:
        return 이번주월 + timedelta(days=목표)
    차이 = (목표 - 기준요일) % 7
    return 오늘.date() + timedelta(days=차이)


def 해석(원문, 트리거="!일정", 시간필수=True):
    텍스트 = 원문.strip()
    if 텍스트.startswith(트리거):
        텍스트 = 텍스트[len(트리거):].strip()
    남은 = 텍스트
    오늘 = 지금()
    날짜 = None
    종일 = False

    # ---------- 날짜 찾기 ----------
    # 긴 표현을 먼저 확인합니다 ("내일모레"가 "내일"보다 앞서야 함)
    for 말, d in [("내일모레", 2), ("내일 모레", 2), ("글피", 3), ("모레", 2),
                 ("오늘", 0), ("금일", 0), ("내일", 1), ("낼", 1)]:
        if 말 in 남은:
            날짜 = (오늘 + timedelta(days=d)).date()
            남은 = 남은.replace(말, " ", 1)
            break

    if 날짜 is None:
        m = re.search(r'(\d{1,2})\s*월\s*(\d{1,2})\s*일?', 남은)
        if m:
            날짜 = _연도보정(오늘, int(m.group(1)), int(m.group(2)))
            남은 = 남은[:m.start()] + " " + 남은[m.end():]

    if 날짜 is None:
        m = re.search(r'(\d{1,2})[./](\d{1,2})', 남은)
        if m:
            날짜 = _연도보정(오늘, int(m.group(1)), int(m.group(2)))
            남은 = 남은[:m.start()] + " " + 남은[m.end():]

    if 날짜 is None:
        m = re.search(r'(다음\s*주|담주|이번\s*주|이번주)?\s*([월화수목금토일])요일', 남은)
        if m:
            날짜 = _요일계산(오늘, 요일맵[m.group(2)], m.group(1) or "")
            남은 = 남은[:m.start()] + " " + 남은[m.end():]

    if 날짜 is None:
        return {"ok": False, "이유": "며칠인지 안 적혀 있어요"}

    # ---------- 시간 찾기 ----------
    시각, 분 = None, 0
    if any(말 in 남은 for 말 in ["하루종일", "온종일", "종일"]):
        종일 = True
        for 말 in ["하루종일", "온종일", "종일"]:
            남은 = 남은.replace(말, " ")
    else:
        오전오후 = None
        mo = re.search(r'(오전|오후|새벽|아침|점심|저녁|밤|낮|정오|자정)', 남은)
        if mo:
            오전오후 = mo.group(1)
            남은 = 남은.replace(오전오후, " ", 1)

        if 오전오후 == "정오":
            시각, 분 = 12, 0
        elif 오전오후 == "자정":
            시각, 분 = 0, 0
        else:
            m = re.search(r'(\d{1,2})\s*:\s*(\d{2})', 남은)
            if m:
                시각, 분 = int(m.group(1)), int(m.group(2))
                남은 = 남은[:m.start()] + " " + 남은[m.end():]
            else:
                m = re.search(r'(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분)?(\s*반)?', 남은)
                if m:
                    시각 = int(m.group(1))
                    if m.group(2):
                        분 = int(m.group(2))
                    elif m.group(3):
                        분 = 30
                    남은 = 남은[:m.start()] + " " + 남은[m.end():]

        # 숫자 없이 '저녁'처럼 시간대만 말한 경우 -> 기본 시각 사용
        기본사용 = False
        if 시각 is None and 오전오후 in 기본시각:
            시각, 분 = 기본시각[오전오후], 0
            기본사용 = True

        if 시각 is None:
            if 시간필수:
                return {"ok": False, "이유": "몇 시인지 안 적혀 있어요"}
            종일 = True   # 시간을 안 적었으면 '날짜만 있는 할 일'로 처리(할일용)

        # 오전/오후 보정 (시간대 기본값을 쓴 경우엔 보정하지 않음)
        if not 종일 and not 기본사용:
            if 오전오후 in ("오후", "저녁", "밤"):
                if 시각 < 12:
                    시각 += 12
            elif 오전오후 in ("오전", "아침", "낮"):
                if 시각 == 12:
                    시각 = 0
            elif 오전오후 is None:
                # 안 적었을 때: 1~6시는 오후, 7~11시는 오전, 12시는 정오
                if 1 <= 시각 <= 6:
                    시각 += 12

    # ---------- 제목 정리 ----------
    제목 = re.sub(r'\s+', ' ', 남은).strip(" ·-,").strip()
    # 앞에 덜렁 남은 조사(에/에서/은/는 등) 떼기
    제목 = re.sub(r'^(에서|에는|에|은|는|이|가|을|를)\s+', '', 제목).strip()
    if not 제목:
        제목 = "일정"

    # ---------- 결과 만들기 ----------
    if 종일:
        시작 = 날짜.isoformat()
        끝 = (날짜 + timedelta(days=1)).isoformat()
        return {"ok": True, "제목": 제목, "시작": 시작, "끝": 끝, "종일": True}

    시작dt = datetime(날짜.year, 날짜.month, 날짜.day, 시각, 분, tzinfo=서울)
    끝dt = 시작dt + timedelta(hours=1)
    return {
        "ok": True,
        "제목": 제목,
        "시작": 시작dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "끝": 끝dt.strftime("%Y-%m-%dT%H:%M:%S"),
        "종일": False,
    }


if __name__ == "__main__":
    예시 = [
        "!일정 6월 10일 오후 3시 큐앤뱅 팀미팅",
        "!일정 내일 9시 세무사 통화",
        "!일정 6/12 종일 휴무",
        "!일정 다음주 월요일 오후 2시 30분 미팅",
        "!일정 큐앤뱅 미팅",          # 날짜 없음 -> 되묻기
        "!일정 6월 5일 큐앤뱅 회의",   # 시간 없음 -> 되묻기
    ]
    import json
    for e in 예시:
        print(e)
        print("  ->", json.dumps(해석(e), ensure_ascii=False))
