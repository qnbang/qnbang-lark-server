# -*- coding: utf-8 -*-
"""
'이번 주 일정 알려줘' 같은 '물어보는 글'을 알아채고,
어느 기간을 묻는지 파악해서, 캘린더 내용을 요일별로 예쁘게 정리합니다.
"""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

서울 = ZoneInfo("Asia/Seoul")
요일 = ["월", "화", "수", "목", "금", "토", "일"]
요일맵 = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

# 이런 말이 들어 있으면 '물어보는 글'로 봅니다
질의표시 = ["알려줘", "알려", "보여줘", "보여", "뭐 있", "뭐있", "뭐 잇", "있어?", "있나",
          "스케줄", "일정?", "확인", "뭐야", "리스트", "목록", "어떻게 돼", "어떻게돼"]


def 질의인가(본문):
    return any(말 in 본문 for 말 in 질의표시)


def 범위(본문):
    """묻는 기간을 (시작날짜, 끝날짜, 라벨)로 돌려줍니다."""
    오늘 = datetime.now(서울).date()
    월요일 = 오늘 - timedelta(days=오늘.weekday())

    if "오늘" in 본문 or "금일" in 본문:
        return 오늘, 오늘, "오늘"
    if "내일모레" in 본문 or "모레" in 본문:
        d = 오늘 + timedelta(days=2)
        return d, d, "모레"
    if "내일" in 본문:
        d = 오늘 + timedelta(days=1)
        return d, d, "내일"
    if "다음주" in 본문 or "다음 주" in 본문 or "담주" in 본문:
        s = 월요일 + timedelta(days=7)
        return s, s + timedelta(days=6), "다음 주"
    if "이번주" in 본문 or "이번 주" in 본문 or "금주" in 본문:
        return 월요일, 월요일 + timedelta(days=6), "이번 주"
    if "다음달" in 본문 or "다음 달" in 본문 or "담달" in 본문:
        s = (오늘.replace(day=1) + timedelta(days=32)).replace(day=1)
        e = (s + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return s, e, "다음 달"
    if "이번달" in 본문 or "이번 달" in 본문 or "이달" in 본문:
        s = 오늘.replace(day=1)
        e = (s + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return s, e, "이번 달"

    m = re.search(r'(\d{1,2})\s*월', 본문)
    if m:
        월 = int(m.group(1))
        s = datetime(오늘.year, 월, 1, tzinfo=서울).date()
        e = (s + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        return s, e, "%d월" % 월

    mw = re.search(r'([월화수목금토일])요일', 본문)
    if mw:
        목표 = 요일맵[mw.group(1)]
        차이 = (목표 - 오늘.weekday()) % 7
        d = 오늘 + timedelta(days=차이)
        return d, d, "%d/%d(%s)" % (d.month, d.day, 요일[d.weekday()])

    # 기간 표현이 없으면 오늘부터 7일
    return 오늘, 오늘 + timedelta(days=6), "앞으로 7일"


def 응답만들기(라벨, 이벤트들):
    if not 이벤트들:
        return "📅 %s 일정이 없어요." % 라벨
    줄 = ["📅 %s 일정" % 라벨]
    현재날 = None
    for e in 이벤트들:
        st = e.get("start", {})
        if "dateTime" in st:
            dt = datetime.fromisoformat(st["dateTime"])
            날 = dt.date()
            시간 = "%02d:%02d" % (dt.hour, dt.minute)
        else:
            날 = datetime.fromisoformat(st["date"]).date()
            시간 = "종일"
        if 날 != 현재날:
            현재날 = 날
            줄.append("\n%d/%d(%s)" % (날.month, 날.day, 요일[날.weekday()]))
        줄.append("  • %s %s" % (시간, e.get("summary", "(제목없음)")))
    return "\n".join(줄)
