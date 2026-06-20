# -*- coding: utf-8 -*-
"""라크 '과업방' 처리 (P3b) — 한 줄로 ① 새 과업 추가 ② 기존 공위치 변경.
받기=WebSocket(실시간.py), 답장=무료 웹훅(라크 API 한도와 무관). 시트 쓰기=자금기록기 엔드포인트.

  "소리쉼 명함 6/20"        → 새 과업 생성(기한 6/20, 내작업)
  "소리쉼 보냄" / "금문도 답옴" → 기존 과업 공위치 변경(보냄→고객대기, 답옴→내작업)
"""
import re, json, urllib.request
from datetime import datetime, timezone, timedelta

서울 = timezone(timedelta(hours=9))
WRITE = "https://script.google.com/macros/s/AKfycbxPt24eFUbUP1cPwsv5Gspc3pak_hvqIdGf7T4cbvqJSxKkKimCdEhxdSll0yMPJ5dPAw/exec"
READ = "https://script.google.com/macros/s/AKfycbwh6lSVmDXCcvjZwDLPCUtvaEG4aOQmTfrVGRbsaJjB5CYtulRzdnd27oKEAyc69RTp/exec"
WEBHOOK = "https://open.larksuite.com/open-apis/bot/v2/hook/4d631621-630b-49aa-9036-f26297e02e26"
KEY = "qnbang2026"
HEADER = ["id", "프로젝트", "과업명", "담당자", "공위치", "현재상태", "다음할일",
          "기한", "고객", "돈종류", "할일", "판정근거", "갱신일", "출처"]
공위치_LIST = ["시작전", "내작업", "내회신", "고객대기", "보류", "완수"]

# 상태 전이어 → 공위치 (UPDATE 감지)
상태_KW = [
    (["보냄", "보냈", "전달", "제출", "발송", "넘김", "넘겼", "공유", "올림", "등록함"], "고객대기"),
    (["답옴", "답왔", "회신옴", "회신왔", "피드백옴", "피드백왔", "받음", "받았", "내차례", "내 차례"], "내작업"),
    (["완료", "완수", "납품", "마감함", "종료", "끝남", "끝냄"], "완수"),
    (["보류", "홀딩", "멈춤"], "보류"),
    (["회신해야", "답해야", "결정해야", "정해야"], "내회신"),
]
POS_WORDS = {"시작전": "시작전", "내작업": "내작업", "내회신": "내회신", "고객대기": "고객대기", "보류": "보류", "완수": "완수"}
BALL_pretty = {"고객대기": "📥 고객대기", "내작업": "🛠️ 내작업", "내회신": "📤 내회신", "시작전": "🌱 시작전", "보류": "⏸️ 보류", "완수": "✅ 완수"}


def _today():
    return datetime.now(서울).strftime("%Y-%m-%d")


def _post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8")


def 답장(text):
    try:
        _post(WEBHOOK, {"msg_type": "text", "content": {"text": text}})
    except Exception as e:
        print("과업방 답장 실패:", e)


def _공위치_찾기(본문):
    for kws, pos in 상태_KW:
        if any(k in 본문 for k in kws):
            return pos
    for w, pos in POS_WORDS.items():
        if w in 본문:
            return pos
    return None


def 해석(원문):
    """새 과업용 파싱 → dict."""
    남은 = " " + 원문.strip() + " "
    기한 = ""
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', 남은) or re.search(r'(\d{1,2})\s*[월/]\s*(\d{1,2})\s*일?', 남은)
    if m:
        try:
            if len(m.groups()) == 3:
                기한 = "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
            else:
                기한 = "%04d-%02d-%02d" % (datetime.now(서울).year, int(m.group(1)), int(m.group(2)))
            남은 = 남은[:m.start()] + " " + 남은[m.end():]
        except ValueError:
            pass
    남은 = 남은.replace("까지", " ")
    담당자 = "신종호"
    for 이름 in ["신종호", "김지영"]:
        if 이름 in 남은:
            담당자 = 이름; 남은 = 남은.replace(이름, " ", 1); break
    토큰 = [t for t in re.split(r'[\s·,]+', 남은) if t]
    if not 토큰:
        return None
    return {"프로젝트": 토큰[0], "과업명": " ".join(토큰[1:]) or 토큰[0], "담당자": 담당자, "기한": 기한}


def 새과업(d):
    행 = {"id": "L" + datetime.now(서울).strftime("%y%m%d%H%M%S"), "프로젝트": d["프로젝트"], "과업명": d["과업명"],
          "담당자": d["담당자"], "공위치": "내작업", "현재상태": "", "다음할일": "", "기한": d.get("기한", ""),
          "고객": d["프로젝트"], "돈종류": "매출", "할일": "", "판정근거": "", "갱신일": _today(), "출처": "라크"}
    res = json.loads(_post(WRITE, {"key": KEY, "종류": "과업", "헤더": HEADER, "행": 행,
                                   "드롭다운": {"공위치": 공위치_LIST, "돈종류": ["매출", "투자"]}}))
    return res.get("ok")


def _norm(v):
    s = str(v or '')
    if re.match(r'^\d{4}-\d{2}-\d{2}T', s):
        try:
            return datetime.fromisoformat(s.replace('Z', '+00:00')).astimezone(서울).strftime('%Y-%m-%d')
        except Exception:
            return s
    return s


def 공위치변경(프로젝트, 공위치):
    """프로젝트명으로 기존 과업 찾아 공위치 변경(read→덮어쓰기). 변경 건수 반환."""
    d = json.loads(urllib.request.urlopen(READ + "?key=" + KEY, timeout=40).read())
    rows = d['sheets'].get('과업')
    if not rows or len(rows) < 2:
        return 0, []
    head = [str(h) for h in rows[0]]
    pi, ci, ui = head.index('프로젝트'), head.index('공위치'), head.index('갱신일')
    data = [r for r in rows[1:] if any(str(c).strip() for c in r)]
    매치 = []
    행들 = []
    for r in data:
        row = [_norm(r[head.index(h)] if head.index(h) < len(r) else '') for h in HEADER]
        pj = str(r[pi]) if pi < len(r) else ''
        if 프로젝트 in pj or (pj and pj.split()[0] == 프로젝트):
            row[HEADER.index('공위치')] = 공위치
            row[HEADER.index('갱신일')] = _today()
            매치.append(pj)
        행들.append(row)
    if not 매치:
        return 0, []
    _post(WRITE, {"key": KEY, "종류": "과업", "헤더": HEADER, "행들": 행들,
                  "드롭다운": {"공위치": 공위치_LIST, "돈종류": ["매출", "투자"]}, "덮어쓰기": True})
    return len(매치), 매치


def 과업메시지처리(본문):
    본문 = (본문 or "").strip()
    if not 본문:
        return
    토큰 = 본문.split()
    프로젝트 = 토큰[0]
    공위치 = _공위치_찾기(본문)
    has_date = bool(re.search(r'\d{1,2}\s*[월/]\s*\d{1,2}|\d{4}-\d{1,2}-\d{1,2}', 본문))
    # 공위치 단어 있고 날짜 없으면 → 상태 변경(UPDATE). 아니면 새 과업(ADD).
    if 공위치 and not has_date:
        n, 매치 = 공위치변경(프로젝트, 공위치)
        if n:
            답장("✅ %s → %s (%d건 갱신)" % (프로젝트, BALL_pretty.get(공위치, 공위치), n))
        else:
            답장("⚠️ '%s' 과업을 못 찾았어요. 새로 만들려면 과업명을 같이 써주세요." % 프로젝트)
    else:
        d = 해석(본문)
        if not d:
            답장("⚠️ 이해 못했어요. 예) '소리쉼 명함 6/20' 또는 '소리쉼 보냄'")
            return
        if 새과업(d):
            때 = (" · " + d["기한"]) if d["기한"] else ""
            답장("✅ 과업 등록 — %s · %s (내작업%s)" % (d["프로젝트"], d["과업명"], 때))
        else:
            답장("⚠️ 기록 실패")


if __name__ == "__main__":
    for s in ["소리쉼 명함 6/20", "소리쉼 보냄", "금문도 답옴", "M650 완료", "촌캉스 보류"]:
        본문 = s
        토큰 = 본문.split(); 공 = _공위치_찾기(본문)
        hd = bool(re.search(r'\d{1,2}\s*[월/]\s*\d{1,2}|\d{4}-\d{1,2}-\d{1,2}', 본문))
        print(f"{s:18} → {'상태변경 '+공 if (공 and not hd) else '새과업'}")
