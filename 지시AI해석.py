# -*- coding: utf-8 -*-
"""라크 과업방 '오늘 지시' 자유 문장 → 제미나이(AI)로 구조화.

기존 과업해석.py의 정규식·키워드 파서는 자유로운 한국어 지시에서 자주 깨졌다.
(한 키워드가 여러 프로젝트에 걸림 / '-' 불릿을 프로젝트로 오인 / '틀림' 같은 정정을
 새 과업으로 만듦 / 군더더기를 할일에 그대로 남김)
이 모듈은 견적서AI해석.py와 같은 방식으로, 현재 과업 목록과 직전 반영 맥락을
AI에 같이 넘겨 한 번에 정확히 읽힌다.

반환: {"ok": bool, "정정": bool, "항목들": [
         {"프로젝트", "신규": bool, "할일", "기한"(YYYY-MM-DD or ""), "공위치"}]}
"""
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

서울 = timezone(timedelta(hours=9))

공위치_LIST = ["받은일", "시작전", "내작업", "내회신", "고객대기", "보류", "완수"]

_스키마 = {
    "type": "object",
    "properties": {
        "정정": {"type": "boolean"},
        "항목들": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "프로젝트": {"type": "string"},
                    "신규": {"type": "boolean"},
                    "할일": {"type": "string"},
                    "기한": {"type": "string"},
                    "공위치": {"type": "string"},
                },
                "required": ["프로젝트", "신규", "할일"],
            },
        },
    },
    "required": ["항목들"],
}

_지침_틀 = """너는 디자인 회사 '큐앤뱅' 대표의 업무 비서야.
대표가 라크 과업방에 자유롭게 쓴 '오늘 지시'를 읽고, 업무 시트에 반영할 수 있게
JSON으로만 정리해. 오늘 날짜는 {오늘}.

[현재 진행 중인 과업 목록]  (프로젝트 | 고객 | 과업명)
{과업목록}

[공위치(업무 단계) 선택지]
{공위치}
- 모르면 "내작업"으로 둬.

규칙:
1. 매칭: 각 지시를 위 과업 목록에서 가장 잘 맞는 과업 하나에 연결해라.
   프로젝트명·고객명·과업명·맥락으로 판단. 같은 단어(예: '축제')가 여러 프로젝트에
   걸려도 진짜 그 지시가 가리키는 한 곳만 골라라. 정말 둘 다에 해당할 때만 둘로 나눠라.
   맞는 과업이 없으면 신규=true, 프로젝트엔 새 프로젝트(고객) 이름을 적어라.
2. 글머리표·번호('-', '·', '*', '1.', '①')는 무시해라. 절대 프로젝트명으로 쓰지 마라.
   어떤 줄이 바로 윗줄의 하위 항목이면(들여쓰기·불릿) 윗줄과 같은 프로젝트에 묶어라.
3. 할일: 실제 해야 할 행동만 간결히 남겨라. "관련 할 일 추가", "할일 =", "건 처리",
   "~좀" 같은 군더더기·메타 표현은 빼라. 예) "선금 지불가능 여부 상인회에 문의".
4. 기한: '오늘/내일/이번주/N월 N일/N시까지' 같은 표현을 YYYY-MM-DD로 환산해라.
   기한 표현이 없으면 ""로 둬라.
5. 공위치: 지시에 '보냄/제출/완료/보류/회신해야' 같은 단계 신호가 있으면 그에 맞춰라.
   없으면 "내작업".
{정정안내}
한 글자도 지어내지 말고, 위 형식의 JSON만 출력해라."""

_정정_있음 = """6. 정정 처리: 이번 메시지가 '틀림/아니/정정/수정해' 등으로 시작하거나 직전 반영을
   바로잡는 내용이면 정정=true 로 표시해라. 이때 '틀림' 같은 메타 단어 자체는 과업이
   아니다 — 절대 새 과업으로 만들지 마라. 대표가 새로 말한 올바른 내용으로 직전 반영의
   해당 과업을 고쳐서 항목들에 담아라.

[직전에 봇이 반영했던 내용 — 이걸 기준으로 정정 판단]
{직전반영}"""


def _과업목록_텍스트(tasks, 한도=60):
    줄 = []
    for t in tasks[:한도]:
        pj = (t.get("pj") or "").strip()
        cl = (t.get("cl") or "").strip()
        nm = (t.get("name") or "").strip()
        줄.append("- %s | %s | %s" % (pj, cl, nm))
    return "\n".join(줄) or "(없음)"


def 해석(본문, tasks, gemini설정, 직전반영=None):
    """본문(여러 줄 지시) → 구조화. tasks=[{pj,cl,name}], 직전반영=문자열 or None."""
    오늘 = datetime.now(서울).strftime("%Y-%m-%d")
    if 직전반영:
        정정안내 = _정정_있음.format(직전반영=직전반영)
    else:
        정정안내 = ""
    지침 = _지침_틀.format(
        오늘=오늘,
        과업목록=_과업목록_텍스트(tasks),
        공위치=" / ".join(공위치_LIST),
        정정안내=정정안내,
    )

    key = gemini설정["key"]
    model = gemini설정.get("model", "gemini-2.5-flash")
    url = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "%s:generateContent?key=%s" % (model, key))
    body = {
        "contents": [{"parts": [{"text": 지침 + "\n\n[오늘 지시 원문]\n" + 본문}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _스키마,
            "temperature": 0.1,
        },
    }
    데이터 = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=데이터,
                                 headers={"Content-Type": "application/json"}, method="POST")
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

    항목들 = []
    for h in (data.get("항목들") or []):
        프로젝트 = (h.get("프로젝트") or "").strip()
        할일 = (h.get("할일") or "").strip()
        if not 프로젝트:
            continue
        공위치 = (h.get("공위치") or "").strip()
        if 공위치 not in 공위치_LIST:
            공위치 = "내작업"
        항목들.append({
            "프로젝트": 프로젝트,
            "신규": bool(h.get("신규")),
            "할일": 할일,
            "기한": (h.get("기한") or "").strip(),
            "공위치": 공위치,
        })
    return {"ok": True, "정정": bool(data.get("정정")), "항목들": 항목들}
