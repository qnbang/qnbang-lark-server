# -*- coding: utf-8 -*-
"""라크 일정방의 수정·삭제 명령을 안전하게 처리한다."""

import json
import os
import re
from datetime import datetime, timedelta

import calendar_api
import parse_schedule

기준폴더 = os.path.dirname(os.path.abspath(__file__))
대기파일 = os.path.join(기준폴더, "일정_삭제대기.json")


def _정리(글):
    return re.sub(r"\s+", "", (글 or "")).lower()


def _대기읽기():
    try:
        with open(대기파일, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _대기쓰기(대기):
    임시 = 대기파일 + ".tmp"
    with open(임시, "w", encoding="utf-8") as f:
        json.dump(대기, f, ensure_ascii=False)
    os.replace(임시, 대기파일)


def _후보찾기(조건):
    해석 = parse_schedule.해석(조건, 트리거="", 시간필수=False)
    if not 해석["ok"]:
        return [], "기존 일정의 날짜를 함께 적어주세요."
    시작 = 해석["시작"]
    날짜 = 시작 if 해석["종일"] else 시작[:10]
    시작ISO = 날짜 + "T00:00:00+09:00"
    끝ISO = (datetime.strptime(날짜, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+09:00")
    제목 = _정리(해석["제목"])
    후보 = []
    for 이벤트 in calendar_api.일정목록(시작ISO, 끝ISO):
        실제제목 = _정리(이벤트.get("summary", ""))
        if 제목 and (제목 in 실제제목 or 실제제목 in 제목):
            후보.append(이벤트)
    if not 후보:
        return [], "해당 날짜와 제목으로 일정을 찾지 못했어요."
    if len(후보) > 1:
        목록 = " / ".join(이벤트.get("summary", "일정") for 이벤트 in 후보[:3])
        return [], "같은 조건의 일정이 여러 개예요(%s). 제목을 더 정확히 적어주세요." % 목록
    return 후보, ""


def 처리(본문, chat_id):
    """편집 명령이면 (True, 답장), 아니면 (False, '')를 반환한다."""
    텍스트 = 본문.strip()
    텍스트 = re.sub(r"^!일정\s*", "", 텍스트).strip()

    if 텍스트 == "삭제 확인":
        대기 = _대기읽기()
        항목 = 대기.get(chat_id)
        if not 항목 or datetime.now().timestamp() - 항목.get("시각", 0) > 600:
            대기.pop(chat_id, None)
            _대기쓰기(대기)
            return True, "삭제 대기 중인 일정이 없거나 확인 시간이 지났어요. 다시 삭제 명령을 보내주세요."
        calendar_api.일정삭제(항목["이벤트ID"])
        대기.pop(chat_id, None)
        _대기쓰기(대기)
        return True, "🗑️ 삭제됨 — %s" % 항목["제목"]

    if 텍스트.startswith("삭제 "):
        후보, 이유 = _후보찾기(텍스트[3:].strip())
        if not 후보:
            return True, "❓ " + 이유
        이벤트 = 후보[0]
        대기 = _대기읽기()
        대기[chat_id] = {"이벤트ID": 이벤트["id"], "제목": 이벤트.get("summary", "일정"), "시각": datetime.now().timestamp()}
        _대기쓰기(대기)
        return True, "⚠️ '%s' 일정을 지웁니다. 10분 안에 '삭제 확인'이라고 답장해주세요." % 이벤트.get("summary", "일정")

    if 텍스트.startswith("수정 "):
        조각 = 텍스트[3:].split(" / ", 1)
        if len(조각) != 2:
            return True, "❓ 수정 형식: '수정 기존 날짜·제목 / 새 날짜·시간·제목'으로 보내주세요."
        후보, 이유 = _후보찾기(조각[0].strip())
        if not 후보:
            return True, "❓ " + 이유
        새일정 = parse_schedule.해석(조각[1].strip(), 트리거="", 시간필수=False)
        if not 새일정["ok"]:
            return True, "❓ 새 일정의 날짜를 확인할 수 없어요. 날짜를 넣어 다시 보내주세요."
        이벤트 = 후보[0]
        calendar_api.일정수정(이벤트["id"], 새일정["제목"], 새일정["시작"], 새일정["끝"], 새일정["종일"], 설명=이벤트.get("description", ""))
        return True, "✏️ 수정됨 — %s" % 새일정["제목"]

    return False, ""
