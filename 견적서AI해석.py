# -*- coding: utf-8 -*-
"""
라크에 자유롭게 쓴 견적 요청 글을 제미나이(Gemini)로 분석해
항목/내역/세부/금액 구조로 자동 분류합니다.

반환: {"ok": bool, "고객명", "작업명", "항목들":[{항목,내역,세부,금액}], "특이사항"}
"""

import json
import urllib.request
import urllib.error


_스키마 = {
    "type": "object",
    "properties": {
        "고객명": {"type": "string"},
        "작업명": {"type": "string"},
        "특이사항": {"type": "string"},
        "항목들": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "항목": {"type": "string"},
                    "내역": {"type": "string"},
                    "세부": {"type": "string"},
                    "금액": {"type": "integer"},
                },
                "required": ["세부", "금액"],
            },
        },
    },
    "required": ["고객명", "항목들"],
}

_지침 = """너는 디자인 회사 '큐앤뱅'의 견적서 작성 도우미야.
아래 견적 요청 글을 읽고 견적서 표로 쓸 수 있게 분류해서 JSON으로만 답해.

분류 규칙:
- 고객명: 견적을 받는 회사/사람 이름.
- 작업명: 이번 견적 전체를 아우르는 제목. 없으면 핵심 작업으로 자연스럽게 지어.
- 항목들: 각 작업을 한 줄(행)로. 각 줄은 다음을 가진다.
  · 항목(대분류): 이번 견적 전체를 아우르는 큰 묶음 이름을 반드시 채워라. 절대 비우지 마라.
     (예: 랜딩·웹사이트면 "웹사이트 제작", 행사물이면 "행사 디자인", 로고·명함이면 "브랜드 디자인")
  · 내역(중분류): 항목 안에서 성격이 다른 작업을 묶는 중간 분류. 자연스럽게 나뉘면 채우고, 묶을 게 없으면 "".
     (예: 웹 작업이면 "기획", "디자인", "퍼블리싱/개발" 등으로)
  · 세부(구체 작업 설명): 실제 무엇을 하는지.
  · 금액: 원 단위 숫자(부가세 제외 공급가).
- 금액 처리:
  · 세부 작업마다 금액이 명확하면 → 세부를 각각 별도 줄로 나눠라.
  · 세부를 금액으로 쪼개기 애매하면 → 세부 여러 개를 줄바꿈(\\n)으로 한 줄에 묶고 금액은 한 번만 적어라.
- 같은 항목/내역이 연속되면 같은 글자를 반복해서 적어라(표에서 묶어줄 거야).
- 특이사항: 수정 횟수·납기·별도 견적 등 부가 조건. 없으면 "".
- 금액이 전혀 없는 글이면 항목들을 비워서 반환.

반드시 위 형식의 JSON만 출력해."""


def 해석(본문, gemini설정):
    key = gemini설정["key"]
    model = gemini설정.get("model", "gemini-2.5-flash")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "%s:generateContent?key=%s" % (model, key)
    )

    body = {
        "contents": [{"parts": [{"text": _지침 + "\n\n[견적 요청 글]\n" + 본문}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _스키마,
            "temperature": 0.2,
        },
    }
    데이터 = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=데이터,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            결과 = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"ok": False, "이유": "AI 분석 오류: %s" % e.read().decode("utf-8")[:200]}
    except Exception as e:
        return {"ok": False, "이유": "AI 호출 실패: %s" % e}

    try:
        텍스트 = 결과["candidates"][0]["content"]["parts"][0]["text"]
        data = json.loads(텍스트)
    except Exception:
        return {"ok": False, "이유": "AI 응답을 해석하지 못했어요"}

    항목들 = data.get("항목들") or []
    # 금액 숫자 보정
    정리 = []
    for h in 항목들:
        try:
            금액 = int(h.get("금액", 0) or 0)
        except (ValueError, TypeError):
            금액 = 0
        정리.append({
            "항목": (h.get("항목") or "").strip(),
            "내역": (h.get("내역") or "").strip(),
            "세부": (h.get("세부") or "").strip(),
            "금액": 금액,
        })

    if not data.get("고객명"):
        return {"ok": False, "이유": "고객명을 못 찾았어요 (고객사 이름을 적어주세요)"}
    if not 정리:
        return {"ok": False, "이유": "항목/금액을 못 찾았어요"}

    return {
        "ok": True,
        "고객명": data["고객명"].strip(),
        "작업명": (data.get("작업명") or 정리[0]["세부"]).strip(),
        "항목들": 정리,
        "특이사항": (data.get("특이사항") or "").strip(),
    }
