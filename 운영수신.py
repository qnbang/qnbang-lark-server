# -*- coding: utf-8 -*-
"""운영OS 수신함에 원문 사본을 한 번만 남긴다. 기존 라크 자동 처리는 건드리지 않는다."""

import json
import os

import 시트

_기준폴더 = os.path.dirname(os.path.abspath(__file__))
_기록파일 = os.path.join(_기준폴더, "운영수신_처리한_글.json")
_헤더 = ["수신ID", "채널", "메시지ID", "보낸이", "본문", "수신시각", "고객ID", "프로젝트ID", "할일ID", "처리상태", "원문링크", "추천 다음 행동"]


def _읽기():
    try:
        with open(_기록파일, "r", encoding="utf-8") as file:
            return set(json.load(file))
    except Exception:
        return set()


def _쓰기(ids):
    with open(_기록파일, "w", encoding="utf-8") as file:
        json.dump(list(ids)[-1000:], file, ensure_ascii=False)


def 라크원문기록(설정, 메시지ID, 보낸이, 본문, 수신시각):
    """성공한 메시지ID만 별도 기록해 재연결·재시작에도 중복 행을 막는다."""
    if not 설정.get("자금") or not 메시지ID or not 본문:
        return False
    ids = _읽기()
    key = "lark:" + 메시지ID
    if key in ids:
        return True
    result = 시트.행추가(
        설정["자금"]["endpoint"], 설정["자금"]["key"], "수신연결",
        [key, "라크", 메시지ID, 보낸이 or "라크 사용자", 본문, 수신시각 or "", "", "", "", "확인 전", "", "원문 확인 후 기존 OS 할 일로 등록"],
        _헤더,
    )
    if result.get("ok"):
        ids.add(key)
        _쓰기(ids)
        return True
    return False
