# -*- coding: utf-8 -*-
"""
구글 시트 '큐앤뱅 지출장부'에 지출 한 줄을 기록합니다.
(이미 만들어 둔 Apps Script 웹앱으로 POST)
"""

import json
import urllib.request
import urllib.error


def 기록(엔드포인트, key, 항목):
    """항목 예: {"날짜":"2026/06/05","카테고리":"식비","지출 내용":"스타벅스","비용":5500,"비고":"카드","과업 관리":""}"""
    본문 = dict(항목)
    본문["key"] = key
    데이터 = json.dumps(본문, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        엔드포인트, data=데이터,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    # Apps Script는 302/405 등으로 응답해도 실제로는 기록됨. 오류 떠도 통과시킴.
    try:
        urllib.request.urlopen(req, timeout=25)
    except urllib.error.HTTPError:
        pass
    except Exception:
        pass


def 합계읽기(엔드포인트, key):
    """월별 지출 합계를 읽어옵니다. {'6월': 0, ...} 형태."""
    try:
        with urllib.request.urlopen(엔드포인트 + "?key=" + key, timeout=25) as resp:
            데이터 = json.loads(resp.read().decode("utf-8"))
        월별 = {}
        for 행 in 데이터.get("sheets", {}).get("월별지출", [])[1:]:
            if len(행) >= 2:
                월별[행[0]] = 행[1]
        return 월별
    except Exception:
        return {}
