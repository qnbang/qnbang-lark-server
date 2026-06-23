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


def 탭읽기(엔드포인트, key, 탭명):
    """지정 탭을 행 배열(첫 행=헤더)로 읽어옵니다. 실패 시 []."""
    try:
        with urllib.request.urlopen(엔드포인트 + "?key=" + key, timeout=25) as resp:
            데이터 = json.loads(resp.read().decode("utf-8"))
        return 데이터.get("sheets", {}).get(탭명, [])
    except Exception:
        return []


def 행추가(자금엔드포인트, key, 종류, 행배열, 헤더=None):
    """자금기록기 웹앱에 새 행 1개 추가. 행배열은 헤더 순서대로. 헤더를 주면 그 순서로 정렬·기록.
    응답 JSON(dict) 반환. (urllib만 사용 — curl -L은 302에서 깨짐)"""
    본문 = {"key": key, "종류": 종류, "행들": [행배열]}
    if 헤더:
        본문["헤더"] = 헤더
    데이터 = json.dumps(본문, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(자금엔드포인트, data=데이터,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTPError"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def 매칭수정(자금엔드포인트, key, 종류, 매칭, 값):
    """자금기록기 웹앱에 '매칭수정' POST → 매칭 칸값으로 행 찾아 지정 칸만 갱신.
    매칭 예: {"계약명":"...","계약금액":880000}  값 예: {"입금일":"...","입금액":880000,"입금상태":"입금완료"}
    응답 JSON(dict) 반환. 실패 시 {'ok':False,'error':...}. (urllib만 사용 — curl -L은 302에서 깨짐)"""
    본문 = {"key": key, "종류": 종류, "매칭수정": {"매칭": 매칭, "값": 값}}
    데이터 = json.dumps(본문, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(자금엔드포인트, data=데이터,
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTPError"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
