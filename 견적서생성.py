# -*- coding: utf-8 -*-
"""
Apps Script 웹앱에 POST해서 견적서 PDF를 생성하고 드라이브 링크를 받습니다.
(기존 지출 시트.py와 동일한 패턴)
"""

import json
import urllib.request
import urllib.error


def 견적서링크생성(데이터, 엔드포인트):
    """
    데이터 = {
        "고객명": str, "작업명": str,
        "항목들": [{"세부": str, "금액": int}, ...],
        "특이사항": str,
    }
    반환: (pdf_link: str, sheet_link: str, 파일명: str)
    """
    고객명 = 데이터["고객명"]
    작업명 = 데이터["작업명"]
    본문 = {
        "key": "qnbang2026견적서",
        "고객명": 고객명,
        "작업명": 작업명,
        "항목들": 데이터["항목들"][:15],  # 안전 상한 15개 (앱스크립트가 행 자동 추가)
        "특이사항": 데이터.get("특이사항", ""),
        # 제목바(검은 바)·파일명 형식은 여기서 정한다.
        "제목바": "[큐앤뱅] " + 고객명 + "_" + 작업명,
        "파일명": "[큐앤뱅]" + 고객명 + "_" + 작업명 + "_견적서",
    }
    데이터_bytes = json.dumps(본문, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        엔드포인트, data=데이터_bytes,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            결과 = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        본문_텍스트 = e.read().decode("utf-8")
        raise RuntimeError("Apps Script 오류: %s" % 본문_텍스트)

    if not 결과.get("ok"):
        raise RuntimeError("견적서 생성 실패: %s" % 결과.get("error", "알 수 없는 오류"))

    # (PDF 링크, 시트 링크, 파일명)
    return 결과["pdf_link"], 결과["sheet_link"], 결과["filename"]
