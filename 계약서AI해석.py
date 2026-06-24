# -*- coding: utf-8 -*-
"""
계약서 파일(PDF·이미지·docx·txt)을 제미나이(Gemini)로 읽어 매출/정기매출 등록 정보를 뽑는다.
견적서AI해석.py와 같은 방식(responseSchema로 구조화). PDF·이미지는 멀티모달, docx·txt는 텍스트로.

반환: {"ok": bool, "종류":"매출|정기매출", "거래처", "계약명",
       "금액"(부가세 포함 총액), "계약일", "시작월", "종료월", "비고"}
"""

import os
import re
import html
import json
import base64
import zipfile
import urllib.request
import urllib.error


_스키마 = {
    "type": "object",
    "properties": {
        "종류": {"type": "string", "enum": ["매출", "정기매출"]},
        "거래처": {"type": "string"},
        "계약명": {"type": "string"},
        "금액": {"type": "integer"},
        "계약일": {"type": "string"},
        "시작월": {"type": "string"},
        "종료월": {"type": "string"},
        "비고": {"type": "string"},
    },
    "required": ["종류", "거래처", "계약명", "금액"],
}

_지침 = """너는 디자인 회사 '큐앤뱅'(사업자명 '딥사이트'로도 계약함)의 계약 담당이야.
첨부/아래 계약서를 읽고, 매출 장부에 등록할 정보를 JSON으로만 뽑아줘.

판단 규칙:
- 종류: 매월 반복되는 계약(리테이너·구독·월 단위 대행 등)이면 "정기매출",
        한 번 하고 끝나는 일회성 용역이면 "매출".
- 거래처: 큐앤뱅(딥사이트)에 일을 맡기고 '돈을 내는' 발주처/고객 이름.
         공급자(우리=큐앤뱅·딥사이트·"업체")가 아니라 '점프' 같은 발주처를 골라라.
- 계약명: 계약의 일/프로젝트 이름(용역명). 명확한 제목이 없으면 핵심 업무로 자연스럽게.
- 금액: 부가세 '포함' 총액 숫자(원). 매출이면 계약 총액, 정기매출이면 '월 금액'.
        'VAT 포함'이면 그 금액 그대로, 공급가+부가세가 따로면 합산. 한글 금액(육백만원)도 숫자로.
- 계약일: 계약 체결일 YYYY-MM-DD. 없으면 "".
- 시작월/종료월: 정기매출이면 시작·종료를 YYYY-MM 으로. 매출이거나 미정이면 "".
- 비고: 분할납·지급조건·수행기간 등 짧게. 없으면 "".
- 금액을 못 찾으면 0.

반드시 위 형식의 JSON만 출력해."""

_MIME = {
    ".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp", ".heic": "image/heic",
}


def _제미나이(parts, gemini설정):
    """parts(제미나이 contents.parts)를 보내 구조화 JSON dict를 받는다. 실패 시 {'_err':...}."""
    key = gemini설정["key"]
    model = gemini설정.get("model", "gemini-2.5-flash")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "%s:generateContent?key=%s" % (model, key))
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _스키마,
            "temperature": 0.2,
        },
    }
    데이터 = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=데이터, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            결과 = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"_err": "AI 분석 오류: %s" % e.read().decode("utf-8")[:300]}
    except Exception as e:
        return {"_err": "AI 호출 실패: %s" % e}
    try:
        텍스트 = 결과["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(텍스트)
    except Exception:
        return {"_err": "AI 응답을 해석하지 못했어요"}


def _정리(d):
    if "_err" in d:
        return {"ok": False, "이유": d["_err"]}
    try:
        금액 = int(d.get("금액", 0) or 0)
    except (ValueError, TypeError):
        금액 = 0
    if not d.get("거래처") or not 금액:
        return {"ok": False, "이유": "계약서에서 거래처/금액을 못 찾았어요", "원시": d}
    return {
        "ok": True,
        "종류": d.get("종류", "매출"),
        "거래처": d["거래처"].strip(),
        "계약명": (d.get("계약명") or "").strip(),
        "금액": 금액,
        "계약일": (d.get("계약일") or "").strip(),
        "시작월": (d.get("시작월") or "").strip(),
        "종료월": (d.get("종료월") or "").strip(),
        "비고": (d.get("비고") or "").strip(),
    }


def 해석_텍스트(본문, gemini설정):
    return _정리(_제미나이([{"text": _지침 + "\n\n[계약서 내용]\n" + 본문}], gemini설정))


def 해석_바이트(파일바이트, mime, gemini설정):
    parts = [{"text": _지침}, {"inline_data": {"mime_type": mime,
             "data": base64.b64encode(파일바이트).decode("ascii")}}]
    return _정리(_제미나이(parts, gemini설정))


def _docx텍스트(파일바이트):
    """docx(zip)에서 본문 텍스트를 뽑는다(python-docx 없이 표준 라이브러리만)."""
    import io
    with zipfile.ZipFile(io.BytesIO(파일바이트)) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    xml = xml.replace("</w:p>", "\n")
    return html.unescape(re.sub(r"<[^>]+>", "", xml)).strip()


def 해석_파일(파일경로, gemini설정):
    ext = os.path.splitext(파일경로)[1].lower()
    with open(파일경로, "rb") as f:
        바이트 = f.read()
    if ext in _MIME:                      # PDF·이미지 → 멀티모달
        return 해석_바이트(바이트, _MIME[ext], gemini설정)
    if ext == ".docx":                    # 워드 → 텍스트 추출 후
        return 해석_텍스트(_docx텍스트(바이트), gemini설정)
    if ext in (".txt", ".md"):
        return 해석_텍스트(바이트.decode("utf-8", "ignore"), gemini설정)
    return {"ok": False, "이유": "지원 안 하는 형식이에요: %s (PDF·jpg·png·docx)" % ext}


if __name__ == "__main__":
    import sys
    import lark as 라크
    if len(sys.argv) < 2:
        print("사용법: python 계약서AI해석.py <계약서파일경로>")
        raise SystemExit(1)
    설정 = 라크.설정읽기()
    g = 설정["견적서"]["gemini"]
    결과 = 해석_파일(sys.argv[1], g)
    print(json.dumps(결과, ensure_ascii=False, indent=2))
