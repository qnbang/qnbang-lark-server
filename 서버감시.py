# -*- coding: utf-8 -*-
"""
서버 헬스체크 + 라크 알림 (5분마다 cron 실행)

하는 일:
  - 핵심 서비스(lark-realtime)가 살아있는지 확인
  - 디스크가 꽉 차가는지 확인
  (옛 board/7777 감시는 2026-06-25 폐기, 잔재 코드는 2026-07-13 제거)
  - 문제가 생기면 '무료 라크 웹훅'으로 폰에 알림(브리핑이 쓰는 그 웹훅 재사용)

스팸 방지:
  - 정상 → 장애로 '바뀐 순간'에만 즉시 알림
  - 장애가 계속되면 1시간에 한 번만 다시 알림
  - 장애 → 정상으로 '복구되면' 복구 알림 1회

실행:
  python3 서버감시.py            # 평소(cron) 실행 — 문제 있을 때만 알림
  python3 서버감시.py --상태      # 지금 상태를 화면에 출력(알림 안 보냄)
  python3 서버감시.py --테스트    # 강제로 테스트 알림 한 번 보냄
"""
import json
import os
import subprocess
import time
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

import lark  # 설정읽기() · 웹훅 재사용

기준폴더 = os.path.dirname(os.path.abspath(__file__))
상태파일 = os.path.join(기준폴더, "서버감시_상태.json")
서울 = ZoneInfo("Asia/Seoul")

# 장애가 계속될 때 다시 알리는 간격(초). 5분마다 검사하지만 알림은 1시간에 한 번.
재알림간격 = 60 * 60

# 검사할 systemd 서비스
서비스목록 = ["lark-realtime"]  # board(7777)는 폐기(2026-06-25) — 신규 대시보드로 이전, 감시 제외
# 디스크 경고 기준(%)
디스크경고 = 90


def 지금():
    return datetime.now(서울).strftime("%m/%d %H:%M")


def 상태읽기():
    try:
        with open(상태파일, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def 상태쓰기(d):
    with open(상태파일, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def 서비스살았나(이름, 시도=2, 간격=2):
    """systemctl is-active 가 active면 True. 일시적 실패 대비 재시도."""
    for i in range(시도):
        try:
            결과 = subprocess.run(
                ["systemctl", "is-active", 이름],
                capture_output=True, text=True, timeout=10,
            )
            if 결과.stdout.strip() == "active":
                return True
        except Exception:
            pass
        if i < 시도 - 1:
            time.sleep(간격)
    return False


def 디스크사용률():
    """루트 파티션 사용률(%) 정수. 실패하면 -1."""
    try:
        st = os.statvfs("/")
        전체 = st.f_blocks
        남음 = st.f_bavail
        if 전체 == 0:
            return -1
        return round((전체 - 남음) / 전체 * 100)
    except Exception:
        return -1


def 점검():
    """모든 항목을 검사해 {항목: (정상여부, 설명)} 으로 돌려준다."""
    결과 = {}
    for 이름 in 서비스목록:
        살음 = 서비스살았나(이름)
        결과[f"서비스:{이름}"] = (살음, "정상" if 살음 else "꺼짐(inactive/실패)")
    # 보드웹(7777) 감시 제거 — 2026-06-25 board 폐기(신규 대시보드 dashboard.qnbang.com로 이전)
    사용률 = 디스크사용률()
    디스크정상 = 0 <= 사용률 < 디스크경고
    결과["디스크"] = (디스크정상, f"{사용률}% 사용" if 사용률 >= 0 else "확인 실패")
    return 결과


def 웹훅알림(내용):
    설정 = lark.설정읽기()
    웹훅 = 설정.get("브리핑_webhook")
    if not 웹훅:
        print("브리핑_webhook 주소가 config.json에 없습니다. 알림을 보낼 수 없습니다.")
        return False
    데이터 = json.dumps(
        {"msg_type": "text", "content": {"text": 내용}}, ensure_ascii=False
    ).encode("utf-8")
    요청 = urllib.request.Request(
        웹훅, data=데이터, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(요청, timeout=15) as 응답:
            json.loads(응답.read().decode("utf-8"))
        return True
    except Exception as e:
        print("웹훅 전송 실패:", e)
        return False


def main():
    import sys

    결과 = 점검()

    if "--상태" in sys.argv:
        for 항목, (정상, 설명) in 결과.items():
            print(("✅" if 정상 else "❌"), 항목, "-", 설명)
        return

    if "--테스트" in sys.argv:
        보냄 = 웹훅알림(f"🔔 [서버감시] 테스트 알림입니다. ({지금()})\n감시 시스템이 정상 작동 중입니다.")
        print("테스트 알림", "보냄" if 보냄 else "실패")
        return

    이전 = 상태읽기()
    now = time.time()
    새상태 = {}

    문제항목 = []   # 이번에 새로 장애가 된 것
    지속항목 = []   # 계속 장애인데 재알림 때가 된 것
    복구항목 = []   # 정상으로 돌아온 것

    for 항목, (정상, 설명) in 결과.items():
        이전기록 = 이전.get(항목, {})
        이전정상 = 이전기록.get("정상", True)
        마지막알림 = 이전기록.get("마지막알림", 0)

        if 정상:
            if not 이전정상:
                복구항목.append((항목, 설명))
            새상태[항목] = {"정상": True, "마지막알림": 0}
        else:
            if 이전정상:
                # 정상 → 장애로 막 바뀜: 즉시 알림
                문제항목.append((항목, 설명))
                새상태[항목] = {"정상": False, "마지막알림": now}
            elif now - 마지막알림 >= 재알림간격:
                # 장애 지속 중인데 재알림 때가 됨
                지속항목.append((항목, 설명))
                새상태[항목] = {"정상": False, "마지막알림": now}
            else:
                # 장애 지속 중이지만 아직 재알림 때 아님: 조용히
                새상태[항목] = {"정상": False, "마지막알림": 마지막알림}

    상태쓰기(새상태)

    줄들 = []
    if 문제항목:
        줄들.append("🚨 [서버 장애 발생]")
        for 항목, 설명 in 문제항목:
            줄들.append(f"  ❌ {항목} — {설명}")
    if 지속항목:
        줄들.append("⏳ [장애 지속 중]")
        for 항목, 설명 in 지속항목:
            줄들.append(f"  ❌ {항목} — {설명}")
    if 복구항목:
        줄들.append("✅ [복구됨]")
        for 항목, 설명 in 복구항목:
            줄들.append(f"  ✅ {항목} — {설명}")

    if 줄들:
        줄들.append(f"\n🕒 {지금()}  (서버: lark-calendar-server)")
        본문 = "\n".join(줄들)
        보냄 = 웹훅알림(본문)
        print("알림", "보냄" if 보냄 else "실패")
        print(본문)
    else:
        print(f"{지금()} 모두 정상 — 알림 없음")


if __name__ == "__main__":
    main()
