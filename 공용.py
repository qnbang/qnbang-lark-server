# -*- coding: utf-8 -*-
"""
여러 파일에서 함께 쓰는 작은 공용 도구 모음입니다.
 - 재시도: 외부 API(캘린더·시트) 호출이 일시적으로 실패할 때 몇 번 다시 시도.
 - 로그: 파일 로테이션 로그를 남긴다(메시지ID·chat 끝6자리·본문요약·성공/실패·응답코드).
서버감시.py의 '여러 번 시도' 패턴을 함수 하나로 일반화한 것입니다.
"""

import os
import time
import base64
import hashlib
import logging
from logging.handlers import RotatingFileHandler

기준폴더 = os.path.dirname(os.path.abspath(__file__))
로그파일 = os.path.join(기준폴더, "자동화.log")


def 로그():
    """파일 로테이션 로그를 돌려준다(최대 2MB × 3개). 이미 만들어졌으면 재사용."""
    log = logging.getLogger("큐앤뱅자동화")
    if log.handlers:            # 이미 설정됨 — 핸들러 중복 추가 방지
        return log
    log.setLevel(logging.INFO)
    핸들러 = RotatingFileHandler(로그파일, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    핸들러.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(핸들러)
    return log


def 재시도(함수, 횟수=3, 대기=1.0, 다시시도예외=Exception, 제외예외=()):
    """함수()를 최대 '횟수'번 시도한다. 실패 시 대기·2배(지수)로 늘려가며 다시.
    마지막까지 실패하면 마지막 예외를 그대로 올린다.
    '다시시도예외'에 해당하지 않는 예외는 즉시 올린다(재시도 무의미한 오류).
    '제외예외'는 다시시도예외의 하위여도 재시도하지 않고 즉시 올린다
    (예: URLError는 재시도하되 그 하위인 HTTPError는 제외)."""
    남은대기 = 대기
    for 시도 in range(횟수):
        try:
            return 함수()
        except 제외예외:
            raise
        except 다시시도예외:
            if 시도 == 횟수 - 1:
                raise
            time.sleep(남은대기)
            남은대기 *= 2


def 이벤트해시(원본):
    """구글 캘린더 이벤트 id 규칙(base32hex, a-v·0-9, 5~1024자)에 맞는 id를 만든다.
    같은 원본(글ID)이면 항상 같은 id → 재전송돼도 같은 이벤트라 중복 등록이 막힌다."""
    소화 = hashlib.sha1(원본.encode("utf-8")).digest()
    # base32(A-Z2-7)를 소문자로 낮추고 캘린더가 요구하는 base32hex 문자집합(0-9a-v)으로 옮긴다.
    b32 = base64.b32encode(소화).decode("ascii").rstrip("=").lower()
    옮김 = str.maketrans("abcdefghijklmnopqrstuvwxyz234567", "0123456789abcdefghijklmnopqrstuv")
    아이디 = b32.translate(옮김)
    return 아이디[:40]           # 넉넉히 40자(규칙: 5~1024자)


if __name__ == "__main__":
    # 자체검증: 재시도가 실제로 여러 번 부르는지 + 이벤트해시가 규칙을 지키는지.
    호출수 = {"n": 0}

    def 두번실패후성공():
        호출수["n"] += 1
        if 호출수["n"] < 3:
            raise ValueError("일시 실패")
        return "성공"

    assert 재시도(두번실패후성공, 횟수=3, 대기=0.01) == "성공"
    assert 호출수["n"] == 3, 호출수

    # 제외예외: 하위 예외는 재시도하지 않고 즉시 올라와야 함(단 1회 호출)
    제외호출 = {"n": 0}

    def 즉시올림():
        제외호출["n"] += 1
        raise KeyError("제외 대상")   # KeyError는 LookupError의 하위

    try:
        재시도(즉시올림, 횟수=3, 대기=0.01, 다시시도예외=LookupError, 제외예외=(KeyError,))
        raise AssertionError("KeyError가 올라왔어야 함")
    except KeyError:
        pass
    assert 제외호출["n"] == 1, 제외호출

    # 이벤트해시: 같은 입력→같은 출력(멱등), 문자집합·길이 규칙 준수
    허용 = set("0123456789abcdefghijklmnopqrstuv")
    h1 = 이벤트해시("om_message_abc123")
    h2 = 이벤트해시("om_message_abc123")
    h3 = 이벤트해시("om_message_XYZ999")
    assert h1 == h2, "같은 글ID는 같은 이벤트 id여야 함"
    assert h1 != h3, "다른 글ID는 다른 id여야 함"
    assert 5 <= len(h1) <= 1024, len(h1)
    assert set(h1) <= 허용, "base32hex 문자집합 위반: %s" % h1
    print("자체검증 통과: 재시도 3회 호출, 이벤트해시 멱등·규칙 준수 (%s)" % h1)
