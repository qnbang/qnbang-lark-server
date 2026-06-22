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
          "기한", "고객", "돈종류", "할일", "판정근거", "갱신일", "출처", "계약여부"]
공위치_LIST = ["받은일", "시작전", "내작업", "내회신", "고객대기", "보류", "완수"]

# 상태 전이어 → 공위치 (UPDATE 감지). 자유로운 표현도 최대한 묶고, 글자(현재상태)는 항상 살린다.
상태_KW = [
    (["회신해야", "답해야", "답장해야", "결정해야", "정해야", "컨펌해줘야"], "내회신"),
    (["답옴", "답왔", "회신옴", "회신왔", "피드백옴", "피드백왔", "받음", "받았", "내차례", "내 차례", "수정", "반영"], "내작업"),
    (["완료", "완수", "납품", "마감함", "종료", "끝남", "끝냄"], "완수"),
    (["보류", "홀딩", "멈춤", "중단"], "보류"),
    (["시작전", "착수전", "착수 전", "예정"], "시작전"),
    # 고객대기 = "남(고객/외부)에게 넘겨 답·결과 기다림" — 전달류 + 대기/심사/검토/승인/접수류 다 포함
    (["보냄", "보냈", "전달", "제출", "발송", "넘김", "넘겼", "공유", "올림", "등록", "접수",
      "대기", "기다리", "심사", "검토중", "검토 중", "승인", "컨펌", "확인 중", "답 없", "무응답"], "고객대기"),
]
POS_WORDS = {"받은일": "받은일", "시작전": "시작전", "내작업": "내작업", "내회신": "내회신", "고객대기": "고객대기", "보류": "보류", "완수": "완수"}
BALL_pretty = {"받은일": "📨 받은일", "고객대기": "📥 고객대기", "내작업": "🛠️ 내작업", "내회신": "📤 내회신", "시작전": "🌱 시작전", "보류": "⏸️ 보류", "완수": "✅ 완수"}


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


def 해석(원문, 기본담당="신종호"):
    """새 과업용 파싱 → dict. 담당 디폴트=기본담당(생성자), 메시지에 이름 명시되면 그게 우선."""
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
    담당자 = 기본담당
    for 이름 in ["신종호", "김지영"]:
        if 이름 in 남은:
            담당자 = 이름; 남은 = 남은.replace(이름, " ", 1); break
    for 별칭, 정식 in [("지영", "김지영"), ("종호", "신종호")]:   # 이름 한 단어 위임("롯데 보고서 지영")
        if 담당자 == 기본담당 and 별칭 in 남은:
            담당자 = 정식; 남은 = 남은.replace(별칭, " ", 1); break
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


def 공위치변경(프로젝트, 공위치, 현재상태=None):
    """프로젝트명으로 기존 과업 찾아 공위치(+현재상태) 변경(read→덮어쓰기). 변경 건수 반환."""
    d = json.loads(urllib.request.urlopen(READ + "?key=" + KEY, timeout=40).read())
    rows = d['sheets'].get('과업')
    if not rows or len(rows) < 2:
        return 0, []
    head = [str(h) for h in rows[0]]
    pi = head.index('프로젝트')
    data = [r for r in rows[1:] if any(str(c).strip() for c in r)]
    if len(data) < 5:   # 안전장치: 비정상적으로 적게 읽히면 덮어쓰기 중단(대량 유실 방지)
        답장("⚠️ 과업이 %d건만 읽혀 저장을 막았어요(읽기 오류). 잠시 후 다시." % len(data))
        return 0, []
    매치 = []
    행들 = []
    for r in data:
        row = [_norm(r[head.index(h)] if head.index(h) < len(r) else '') for h in HEADER]
        pj = str(r[pi]) if pi < len(r) else ''
        if 프로젝트 in pj or (pj and pj.split()[0] == 프로젝트):
            row[HEADER.index('공위치')] = 공위치
            if 현재상태:
                row[HEADER.index('현재상태')] = 현재상태
            row[HEADER.index('갱신일')] = _today()
            매치.append(pj)
        행들.append(row)
    if not 매치:
        return 0, []
    _post(WRITE, {"key": KEY, "종류": "과업", "헤더": HEADER, "행들": 행들,
                  "드롭다운": {"공위치": 공위치_LIST, "돈종류": ["매출", "투자"]}, "덮어쓰기": True})
    return len(매치), 매치


# ── 여러 줄 "오늘 지시" 처리 ───────────────────────────────────────────
TIME_RE = re.compile(r'오늘\s*중|오늘\s*오전|오늘\s*오후|오늘|오전|오후\s*\d{1,2}\s*시(?:까지)?|\d{1,2}\s*시까지|내일|금일|당일|까지')


def _parse_due(line):
    m = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', line)
    if m:
        return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r'(\d{1,2})\s*[월/]\s*(\d{1,2})', line)
    if m:
        return "%04d-%02d-%02d" % (datetime.now(서울).year, int(m.group(1)), int(m.group(2)))
    if "내일" in line:
        return (datetime.now(서울) + timedelta(days=1)).strftime("%Y-%m-%d")
    if any(w in line for w in ["오늘", "오전", "오후", "금일", "당일", "시까지"]):
        return _today()
    return ""


def _clean_action(line, ptoks):
    """지시 줄에서 시간·날짜·대상(프로젝트)명을 떼고 '할 일'만 남긴다."""
    s = re.sub(r'\([^)]*\)', ' ', line)   # (과업 쪼개기 필요) 같은 괄호 메모 제거
    s = TIME_RE.sub(' ', s)
    s = re.sub(r'(\d{4}-\d{1,2}-\d{1,2})|(\d{1,2}\s*[월/]\s*\d{1,2})', ' ', s)
    for tk in sorted(ptoks, key=len, reverse=True):
        s = s.replace(tk, ' ')
    s = re.sub(r'[/·,]', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def 지시처리(본문, dry_run=False, 기본담당="신종호"):
    """번호 목록 '오늘 지시' → 각 줄을 기존 과업에 매칭해 다음할일·기한·공위치 갱신, 못 찾으면 새 과업(담당=기본담당)."""
    d = json.loads(urllib.request.urlopen(READ + "?key=" + KEY, timeout=40).read())
    rows = d['sheets'].get('과업')
    if not rows or len(rows) < 2:
        return ([], []) if dry_run else 답장("⚠️ 과업 시트를 못 읽었어요")
    head = [str(h) for h in rows[0]]
    pi, ci = head.index('프로젝트'), head.index('고객')
    data = [r for r in rows[1:] if any(str(c).strip() for c in r)]
    if len(data) < 5:   # 안전장치: 비정상적으로 적게 읽히면 중단(대량 유실 방지)
        return ([], []) if dry_run else 답장("⚠️ 과업이 %d건만 읽혀 저장을 막았어요(읽기 오류). 잠시 후 다시." % len(data))
    tasks = []
    for r in data:
        pj = str(r[pi]) if pi < len(r) else ''
        cl = str(r[ci]) if ci < len(r) else ''
        kws = set(t for t in re.split(r'[\s·]+', pj + ' ' + cl) if len(t) >= 2)
        tasks.append({'r': r, 'pj': pj, 'cl': cl, 'kws': kws})
    lines = [re.sub(r'^\s*\d+\s*[.)]\s*', '', l).strip() for l in 본문.splitlines() if l.strip()]
    결과, 신규 = [], []
    for line in lines:
        due = _parse_due(line)
        toks = [w for w in re.split(r'[\s/·]+', line) if len(w) >= 2]
        matched = []
        for t in tasks:
            blob = t['pj'] + ' ' + t['cl']
            if any(k in line for k in t['kws']) or any(w in blob for w in toks):
                matched.append(t)
        split_note = ("쪼개" in line)
        if matched:
            ptoks = set()
            for t in matched:
                ptoks |= t['kws']
            action = _clean_action(line, ptoks)
            for t in matched:
                t['_next'] = action
                t['_due'] = due
                t['_status'] = line   # 형이 쓴 원문 그대로(메모·맥락 보존) → 현재상태
                결과.append((t['pj'].split()[0] if t['pj'].split() else t['pj'], action, due, split_note))
        else:
            action = _clean_action(line, set())
            tk = action.split()
            if tk:
                신규.append({'프로젝트': tk[0], '과업명': ' '.join(tk[1:]) or tk[0], '기한': due})
                결과.append((tk[0] + '(신규)', ' '.join(tk[1:]), due, split_note))
    if dry_run:
        return 결과, 신규
    # 쓰기: matched 갱신 + 신규 추가 → 한 번에 덮어쓰기
    행들 = []
    for t in tasks:
        r = t['r']
        row = [_norm(r[head.index(h)] if head.index(h) < len(r) else '') for h in HEADER]
        if '_next' in t:
            if t['_next']:
                row[HEADER.index('다음할일')] = t['_next']
            if t.get('_status'):
                row[HEADER.index('현재상태')] = t['_status']   # 원문 메모 보존
            if t['_due']:
                row[HEADER.index('기한')] = t['_due']
            row[HEADER.index('공위치')] = '내작업'
            row[HEADER.index('갱신일')] = _today()
        행들.append(row)
    for i, n in enumerate(신규):
        새 = {'id': 'L' + datetime.now(서울).strftime('%y%m%d%H%M%S') + str(i), '프로젝트': n['프로젝트'], '과업명': n['과업명'],
              '담당자': 기본담당, '공위치': '내작업', '현재상태': '', '다음할일': n['과업명'], '기한': n.get('기한', ''),
              '고객': n['프로젝트'], '돈종류': '매출', '할일': '', '판정근거': '', '갱신일': _today(), '출처': '라크지시', '계약여부': ''}
        행들.append([새.get(h, '') for h in HEADER])
    _post(WRITE, {"key": KEY, "종류": "과업", "헤더": HEADER, "행들": 행들,
                  "드롭다운": {"공위치": 공위치_LIST, "돈종류": ["매출", "투자"]}, "덮어쓰기": True})
    줄 = []
    for pj, act, due, note in 결과:
        때 = (" · " + due) if due else ""
        줄.append("• %s: %s%s%s" % (pj, act or "(확인)", 때, " ⚠️쪼개기필요" if note else ""))
    답장("✅ 오늘 지시 %d건 반영\n%s\n매칭 맞나요? 틀리면 고쳐 보내세요." % (len(결과), "\n".join(줄)))


def 과업메시지처리(본문, 과업설정=None, sender_open=""):
    본문 = (본문 or "").strip()
    if not 본문:
        return
    # 담당 디폴트 = 생성자(라크 보낸 사람). 사용자맵에 없으면 기본담당(종호). 메시지에 이름 명시 시 해석/지시가 그걸 우선.
    매핑 = (과업설정 or {}).get("사용자맵", {})
    기본담당 = 매핑.get(sender_open) or (과업설정 or {}).get("기본담당", "신종호")
    # 여러 줄(번호 목록) = "오늘 지시" → 일괄 처리
    if len([l for l in 본문.splitlines() if l.strip()]) >= 2:
        return 지시처리(본문, 기본담당=기본담당)
    토큰 = 본문.split()
    프로젝트 = 토큰[0]
    공위치 = _공위치_찾기(본문)
    has_date = bool(re.search(r'\d{1,2}\s*[월/]\s*\d{1,2}|\d{4}-\d{1,2}-\d{1,2}', 본문))
    # 공위치 단어 있고 날짜 없으면 → 상태 변경(UPDATE). 아니면 새 과업(ADD).
    if 공위치 and not has_date:
        현재상태 = " ".join(토큰[1:]).strip()  # 프로젝트명 뒤 문구 그대로 현재상태로 저장(자유표현 보존)
        n, 매치 = 공위치변경(프로젝트, 공위치, 현재상태)
        if n:
            꼬리 = (" · " + 현재상태) if 현재상태 else ""
            답장("✅ %s → %s%s (%d건)" % (프로젝트, BALL_pretty.get(공위치, 공위치), 꼬리, n))
        else:
            답장("⚠️ '%s' 과업을 못 찾았어요. 새로 만들려면 과업명을 같이 써주세요." % 프로젝트)
    else:
        d = 해석(본문, 기본담당)
        if not d:
            답장("⚠️ 이해 못했어요. 예) '소리쉼 명함 6/20' 또는 '소리쉼 보냄'")
            return
        if 새과업(d):
            때 = (" · " + d["기한"]) if d["기한"] else ""
            담 = (" · 담당 " + d["담당자"]) if d["담당자"] != "신종호" else ""
            답장("✅ 과업 등록 — %s · %s (내작업%s%s)" % (d["프로젝트"], d["과업명"], 때, 담))
        else:
            답장("⚠️ 기록 실패")


if __name__ == "__main__":
    for s in ["소리쉼 명함 6/20", "소리쉼 보냄", "금문도 답옴", "M650 완료", "촌캉스 보류"]:
        본문 = s
        토큰 = 본문.split(); 공 = _공위치_찾기(본문)
        hd = bool(re.search(r'\d{1,2}\s*[월/]\s*\d{1,2}|\d{4}-\d{1,2}-\d{1,2}', 본문))
        print(f"{s:18} → {'상태변경 '+공 if (공 and not hd) else '새과업'}")
