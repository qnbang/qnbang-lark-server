# -*- coding: utf-8 -*-
"""
구글 시트 '큐앤뱅 지출장부'에 지출 한 줄을 기록합니다.
(이미 만들어 둔 Apps Script 웹앱으로 POST)
"""

import json
import urllib.request
import urllib.error
import 공용


def 기록(엔드포인트, key, 항목):
    """지출 한 줄을 기록한다. 항목 예: {"날짜":"2026/06/05","카테고리":"식비", ...}
    기록에 성공하면 True, 서버까지 못 닿거나(네트워크·타임아웃) 실패면 예외를 올린다.
    → 호출부가 그 실패를 사용자에게 알릴 수 있다(예전엔 실패를 삼켜 '기록됨'이 잘못 나갔음).
    Apps Script 특성상 302/405로도 실제 기록되므로 HTTPError(응답은 왔음)는 성공으로 본다."""
    본문 = dict(항목)
    본문["key"] = key
    데이터 = json.dumps(본문, ensure_ascii=False).encode("utf-8")

    def _보내기():
        req = urllib.request.Request(
            엔드포인트, data=데이터,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=25)
        except urllib.error.HTTPError:
            # 서버가 302/405 등으로 응답 — Apps Script는 이래도 실제로는 기록됨. 성공 취급.
            pass
        return True

    # 네트워크·타임아웃 등 '서버에 못 닿은' 실패만 재시도. 끝까지 실패하면 예외를 그대로 올린다.
    공용.재시도(_보내기, 다시시도예외=(urllib.error.URLError, TimeoutError, OSError))
    공용.로그().info("지출 기록 %s / %s원", 항목.get("지출 내용", ""), 항목.get("비용", ""))
    return True


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

    def _보내기():
        req = urllib.request.Request(자금엔드포인트, data=데이터,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        # 네트워크·타임아웃만 재시도. HTTPError(응답은 옴)는 재시도 말고 본문을 읽어 그대로 반환.
        return 공용.재시도(_보내기, 다시시도예외=(urllib.error.URLError, TimeoutError, OSError),
                        제외예외=(urllib.error.HTTPError,))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTPError"}
    except Exception as e:
        공용.로그().warning("행추가 실패: %s", e)
        return {"ok": False, "error": str(e)}


def 매칭수정(자금엔드포인트, key, 종류, 매칭, 값):
    """자금기록기 웹앱에 '매칭수정' POST → 매칭 칸값으로 행 찾아 지정 칸만 갱신.
    매칭 예: {"계약명":"...","계약금액":880000}  값 예: {"입금일":"...","입금액":880000,"입금상태":"입금완료"}
    응답 JSON(dict) 반환. 실패 시 {'ok':False,'error':...}. (urllib만 사용 — curl -L은 302에서 깨짐)"""
    본문 = {"key": key, "종류": 종류, "매칭수정": {"매칭": 매칭, "값": 값}}
    데이터 = json.dumps(본문, ensure_ascii=False).encode("utf-8")

    def _보내기():
        req = urllib.request.Request(자금엔드포인트, data=데이터,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))

    try:
        # 네트워크·타임아웃만 재시도. HTTPError(응답은 옴)는 재시도 말고 본문을 읽어 그대로 반환.
        return 공용.재시도(_보내기, 다시시도예외=(urllib.error.URLError, TimeoutError, OSError),
                        제외예외=(urllib.error.HTTPError,))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": "HTTPError"}
    except Exception as e:
        공용.로그().warning("매칭수정 실패: %s", e)
        return {"ok": False, "error": str(e)}
