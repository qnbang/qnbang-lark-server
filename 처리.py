# -*- coding: utf-8 -*-
"""
라크 메시지 한 건을 처리하는 공통 로직입니다.
폴링(자동실행.py)과 실시간(실시간.py) 양쪽에서 똑같이 씁니다.
"""

from datetime import datetime, timedelta

import lark
import parse_schedule
import calendar_api
import 질의
import 지출해석
import 시트
import json
import 견적서해석
import 견적서AI해석
import 견적서생성

요일이름 = ["월", "화", "수", "목", "금", "토", "일"]


# ---------------- 일정 ----------------
# 라크 일정방은 '캘린더 전용'이다. 날짜가 있는 글은 모두 구글 캘린더에 등록한다.
# (할 일은 라크로 넣지 않는다 — 보드에서 직접/클로드로 관리.)
def _완료문구(결과):
    if 결과["종일"]:
        d = datetime.strptime(결과["시작"], "%Y-%m-%d")
        때 = "%d월 %d일(%s) 종일" % (d.month, d.day, 요일이름[d.weekday()])
    else:
        d = datetime.strptime(결과["시작"], "%Y-%m-%dT%H:%M:%S")
        오전오후 = "오전" if d.hour < 12 else "오후"
        시 = d.hour % 12 or 12
        때 = "%d월 %d일(%s) %s %d:%02d" % (d.month, d.day, 요일이름[d.weekday()], 오전오후, 시, d.minute)
    return "✅ 등록됨 — %s / %s (큐앤뱅 캘린더)" % (결과["제목"], 때)


def 일정메시지처리(토큰, chat_id, 본문, 트리거=""):
    if 트리거 and not 본문.startswith(트리거):
        return False
    if not 본문:
        return False

    # '이번 주 일정 알려줘' 같은 물어보는 글
    if 질의.질의인가(본문):
        시작d, 끝d, 라벨 = 질의.범위(본문)
        시작ISO = 시작d.isoformat() + "T00:00:00+09:00"
        끝ISO = (끝d + timedelta(days=1)).isoformat() + "T00:00:00+09:00"
        이벤트 = calendar_api.일정목록(시작ISO, 끝ISO)
        lark.메시지보내기(토큰, chat_id, 질의.응답만들기(라벨, 이벤트))
        return True

    # 캘린더 전용: 날짜가 있으면 구글 캘린더에 일정으로 등록(시간 없으면 종일).
    결과 = parse_schedule.해석(본문, 트리거, 시간필수=False)

    # 날짜가 없는 글은 잡담으로 보고 무시(트리거가 있으면 되묻기)
    if not 결과["ok"]:
        if 트리거:
            lark.메시지보내기(
                토큰, chat_id,
                "❓ '%s' — %s. 날짜를 넣어 다시 보내주세요. 예) '6월 6일 오후 3시 팀미팅'" % (본문, 결과["이유"]),
            )
            return True
        return False

    try:
        calendar_api.일정등록(
            결과["제목"], 결과["시작"], 결과["끝"],
            종일=결과["종일"], 설명="라크 일정방에서 자동 등록됨",
        )
        lark.메시지보내기(토큰, chat_id, _완료문구(결과))
    except Exception as e:
        lark.메시지보내기(토큰, chat_id, "⚠️ '%s' 처리 중 문제가 생겼어요: %s" % (본문, e))
    return True


# ---------------- 지출 ----------------
def _지출완료문구(r):
    날 = r["날짜"][5:]
    비고 = (" (%s)" % r["비고"]) if r["비고"] else ""
    문구 = "✅ 기록됨 — %s / %s %s원%s [%s]" % (
        r["카테고리"], r["지출 내용"], format(r["비용"], ","), 비고, 날)
    if r.get("추정분류"):
        문구 += "\n   (분류를 '%s'로 추정했어요. 다르면 분류명을 넣어 다시 보내주세요)" % r["카테고리"]
    return 문구


def 지출메시지처리(토큰, 지출설정, 본문):
    if not 본문:
        return False
    엔드포인트 = 지출설정["endpoint"]
    key = 지출설정["key"]
    chat_id = 지출설정["chat_id"]

    # '이번 달 지출 얼마' 같은 물어보는 글
    if 질의.질의인가(본문) or "얼마" in 본문 or "합계" in 본문:
        월별 = 시트.합계읽기(엔드포인트, key)
        줄 = ["💰 월별 지출"]
        for 월, 금액 in 월별.items():
            if 금액:
                줄.append("  %s  %s원" % (월, format(int(금액), ",")))
        합계 = sum(int(v) for v in 월별.values() if v)
        줄.append("  ─ 합계  %s원" % format(합계, ","))
        lark.메시지보내기(토큰, chat_id, "\n".join(줄))
        return True

    결과 = 지출해석.해석(본문)
    if not 결과["ok"]:  # 금액 없는 글은 잡담으로 무시
        return False

    try:
        시트.기록(엔드포인트, key, {
            "날짜": 결과["날짜"], "카테고리": 결과["카테고리"],
            "지출 내용": 결과["지출 내용"], "비용": 결과["비용"],
            "비고": 결과["비고"], "과업 관리": "",
        })
        lark.메시지보내기(토큰, chat_id, _지출완료문구(결과))
    except Exception as e:
        lark.메시지보내기(토큰, chat_id, "⚠️ '%s' 기록 중 문제가 생겼어요: %s" % (본문, e))
    return True


# ---------------- 견적서 ----------------
_입력_안내 = (
    "📋 견적서 형식:\n"
    "고객: 회사명\n"
    "작업: 작업명 (선택)\n"
    "항목명 / 금액\n"
    "항목명 / 금액\n"
    "특이사항: 내용 (선택)\n\n"
    "예)\n"
    "고객: 김창수위스키증류소 주식회사\n"
    "작업: 라벨 디자인\n"
    "라벨 정보 편집 / 100000\n"
    "백그라운드 이미지 제작 / 50000"
)


def _웹훅보내기(webhook_url, 내용):
    import urllib.request
    데이터 = json.dumps(
        {"msg_type": "text", "content": {"text": 내용}}, ensure_ascii=False
    ).encode("utf-8")
    req = urllib.request.Request(
        webhook_url, data=데이터,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
    except Exception:
        pass


def 견적서메시지처리(토큰, 견적서설정, 본문):
    if not 본문:
        return False

    webhook    = 견적서설정["webhook"]
    엔드포인트 = 견적서설정["endpoint"]

    # 제미나이(AI)로 자유 형식 글을 항목/내역/세부/금액으로 분류.
    # gemini 설정이 없으면 예전 규칙 파서로 안전하게 대체.
    if 견적서설정.get("gemini", {}).get("key"):
        결과 = 견적서AI해석.해석(본문, 견적서설정["gemini"])
    else:
        결과 = 견적서해석.해석(본문)
    if not 결과["ok"]:
        _웹훅보내기(webhook, "❓ %s\n\n%s" % (결과["이유"], _입력_안내))
        return True

    try:
        _웹훅보내기(webhook, "⏳ 견적서 생성 중...")
        pdf링크, 시트링크, 파일명 = 견적서생성.견적서링크생성(결과, 엔드포인트)
        합계 = sum(h["금액"] for h in 결과["항목들"])
        _웹훅보내기(
            webhook,
            "✅ 견적서 완성!\n"
            "고객: %s\n"
            "작업: %s\n"
            "합계: ₩%s (VAT 포함)\n\n"
            "📄 PDF (고객 전달용)\n%s\n\n"
            "📝 수정용 시트\n%s" % (
                결과["고객명"], 결과["작업명"],
                format(int(합계 * 1.1), ","),
                pdf링크, 시트링크,
            )
        )
    except Exception as e:
        _웹훅보내기(webhook, "⚠️ 견적서 생성 중 오류가 생겼어요: %s" % e)
    return True
