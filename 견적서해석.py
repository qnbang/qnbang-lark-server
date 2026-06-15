# -*- coding: utf-8 -*-
"""
라크 메시지에서 견적서 정보를 추출합니다.

입력 형식:
  고객: 회사명
  작업: 작업명  (없으면 첫 번째 항목명 사용)
  항목명 / 금액
  항목명 / 금액
  특이사항: 내용  (선택)

예시:
  고객: 김창수위스키증류소 주식회사
  작업: 라벨 디자인
  라벨 정보 편집 / 100000
  백그라운드 이미지 제작 / 50000
"""

import re


def 해석(본문):
    lines = [l.strip() for l in 본문.strip().splitlines() if l.strip()]

    고객명 = None
    작업명 = None
    항목들 = []
    특이사항 = None

    for line in lines:
        low = line.lower()
        if low.startswith("고객:") or low.startswith("고객 :"):
            고객명 = line.split(":", 1)[1].strip()
        elif low.startswith("작업:") or low.startswith("작업 :"):
            작업명 = line.split(":", 1)[1].strip()
        elif low.startswith("특이사항:") or low.startswith("특이사항 :"):
            특이사항 = line.split(":", 1)[1].strip()
        elif "/" in line:
            parts = line.rsplit("/", 1)
            세부 = parts[0].strip()
            금액_str = re.sub(r"[^\d]", "", parts[1]) if len(parts) == 2 else ""
            if 세부 and 금액_str:
                항목들.append({"세부": 세부, "금액": int(금액_str)})

    if not 고객명:
        return {"ok": False, "이유": "고객명이 없어요 (예: 고객: 회사명)"}
    if not 항목들:
        return {"ok": False, "이유": "항목/금액이 없어요 (예: 라벨 디자인 / 150000)"}

    if not 작업명:
        작업명 = 항목들[0]["세부"]

    return {
        "ok": True,
        "고객명": 고객명,
        "작업명": 작업명,
        "항목들": 항목들,
        "특이사항": 특이사항 or "",
    }
