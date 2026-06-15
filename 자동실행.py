# -*- coding: utf-8 -*-
"""
이 파일 하나가 전체 자동화입니다. 한 번 실행하면 두 방을 처리합니다.
  · 일정 방 → 글 읽어 해석 → 큐앤뱅 구글 캘린더 등록 → 답글
  · 지출 방 → 글 읽어 해석 → 큐앤뱅 지출장부(시트) 기록 → 답글
  · '알려줘' 류는 읽어서 정리해 답해줌
  · 같은 글을 두 번 처리하지 않게 기록(중복방지)

서버에서 10초마다 이 파일을 실행하면 '진짜 자동'이 됩니다.
"""

from datetime import datetime, timedelta

import lark
import parse_schedule
import calendar_api
import 질의
import 지출해석
import 시트

요일이름 = ["월", "화", "수", "목", "금", "토", "일"]


def _쓸만한글인가(글, 이미처리):
    """봇 답글·시스템 알림·이미 처리한 글을 걸러냅니다."""
    if 글.get("msg_type") == "system":
        return False
    if 글.get("sender", {}).get("sender_type") != "user":
        return False
    if 글.get("message_id") in 이미처리:
        return False
    return True


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


# ---------------------------- 일정 방 ----------------------------
def 일정방처리(토큰, chat_id, 트리거, 이미처리, 처리됨):
    처리수 = 0
    for 글 in lark.최근글(토큰, chat_id):
        if not _쓸만한글인가(글, 이미처리):
            continue
        글ID = 글.get("message_id")
        본문 = lark.글에서_본문뽑기(글)
        if 트리거 and not 본문.startswith(트리거):
            continue
        if not 본문:
            continue

        # '이번 주 일정 알려줘' 같은 물어보는 글이면, 캘린더를 읽어서 답해줌
        if 질의.질의인가(본문):
            시작d, 끝d, 라벨 = 질의.범위(본문)
            시작ISO = 시작d.isoformat() + "T00:00:00+09:00"
            끝ISO = (끝d + timedelta(days=1)).isoformat() + "T00:00:00+09:00"
            이벤트 = calendar_api.일정목록(시작ISO, 끝ISO)
            lark.메시지보내기(토큰, chat_id, 질의.응답만들기(라벨, 이벤트))
            처리됨.append(글ID)
            처리수 += 1
            continue

        결과 = parse_schedule.해석(본문, 트리거)
        # 날짜 자체가 없는 글은 잡담으로 보고 조용히 무시
        if not 결과["ok"] and not 트리거 and "며칠" in 결과.get("이유", ""):
            처리됨.append(글ID)
            continue

        처리수 += 1
        try:
            if 결과["ok"]:
                calendar_api.일정등록(
                    결과["제목"], 결과["시작"], 결과["끝"],
                    종일=결과["종일"], 설명="라크 일정 방에서 자동 등록됨",
                )
                lark.메시지보내기(토큰, chat_id, _완료문구(결과))
            else:
                lark.메시지보내기(
                    토큰, chat_id,
                    "❓ '%s' — %s. 날짜·시간을 넣어 다시 보내주세요. 예) 6월 6일 오후 3시 미팅"
                    % (본문, 결과["이유"]),
                )
        except Exception as e:
            lark.메시지보내기(토큰, chat_id, "⚠️ '%s' 처리 중 문제가 생겼어요: %s" % (본문, e))
        처리됨.append(글ID)
    return 처리수


# ---------------------------- 지출 방 ----------------------------
def _지출완료문구(r):
    날 = r["날짜"][5:].replace("/", "/")  # MM/DD
    비고 = (" (%s)" % r["비고"]) if r["비고"] else ""
    문구 = "✅ 기록됨 — %s / %s %s원%s [%s]" % (
        r["카테고리"], r["지출 내용"], format(r["비용"], ","), 비고, 날)
    if r.get("추정분류"):
        문구 += "\n   (분류를 '%s'로 추정했어요. 다르면 분류명을 넣어 다시 보내주세요)" % r["카테고리"]
    return 문구


def 지출방처리(토큰, 지출설정, 이미처리, 처리됨):
    chat_id = 지출설정["chat_id"]
    엔드포인트 = 지출설정["endpoint"]
    key = 지출설정["key"]
    처리수 = 0
    for 글 in lark.최근글(토큰, chat_id):
        if not _쓸만한글인가(글, 이미처리):
            continue
        글ID = 글.get("message_id")
        본문 = lark.글에서_본문뽑기(글)
        if not 본문:
            continue

        # '이번 달 지출 얼마' 같은 물어보는 글 → 월별 합계 답
        if 질의.질의인가(본문) or "얼마" in 본문 or "합계" in 본문:
            월별 = 시트.합계읽기(엔드포인트, key)
            줄 = ["💰 월별 지출"]
            for 월, 금액 in 월별.items():
                if 금액:
                    줄.append("  %s  %s원" % (월, format(int(금액), ",")))
            합계 = sum(int(v) for v in 월별.values() if v)
            줄.append("  ─ 합계  %s원" % format(합계, ","))
            lark.메시지보내기(토큰, chat_id, "\n".join(줄))
            처리됨.append(글ID)
            처리수 += 1
            continue

        결과 = 지출해석.해석(본문)
        # 금액이 없는 글은 잡담으로 보고 조용히 무시
        if not 결과["ok"]:
            처리됨.append(글ID)
            continue

        처리수 += 1
        try:
            시트.기록(엔드포인트, key, {
                "날짜": 결과["날짜"], "카테고리": 결과["카테고리"],
                "지출 내용": 결과["지출 내용"], "비용": 결과["비용"],
                "비고": 결과["비고"], "과업 관리": "",
            })
            lark.메시지보내기(토큰, chat_id, _지출완료문구(결과))
        except Exception as e:
            lark.메시지보내기(토큰, chat_id, "⚠️ '%s' 기록 중 문제가 생겼어요: %s" % (본문, e))
        처리됨.append(글ID)
    return 처리수


def 한번실행():
    설정 = lark.설정읽기()
    토큰 = lark.토큰받기(설정)
    이미처리 = set(lark.처리기록읽기())
    처리됨 = list(이미처리)

    일정수 = 일정방처리(토큰, 설정["chat_id"], 설정.get("trigger", ""), 이미처리, 처리됨)
    지출수 = 0
    if "지출" in 설정 and 설정["지출"].get("chat_id"):
        지출수 = 지출방처리(토큰, 설정["지출"], 이미처리, 처리됨)

    lark.처리기록쓰기(처리됨)
    if 일정수 or 지출수:
        print("[%s] 일정 %d건 / 지출 %d건 처리"
              % (datetime.now().strftime("%m-%d %H:%M:%S"), 일정수, 지출수))


if __name__ == "__main__":
    한번실행()
