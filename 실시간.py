# -*- coding: utf-8 -*-
"""
라크 롱커넥션(WebSocket)으로 메시지를 '즉시' 받아 처리합니다.
주기적으로 물어보지 않으므로 라크 호출 한도를 거의 쓰지 않습니다.
연결이 끊겨도 SDK가 자동으로 다시 붙습니다.
"""

import json
import lark as 라크          # 우리 도구 (메시지보내기, 설정읽기, 처리기록 등)
import 처리
import 매출해석
import lark_oapi


def _텍스트뽑기(content):
    """이벤트로 온 메시지 본문에서 글자만 뽑습니다."""
    try:
        d = json.loads(content or "")
    except Exception:
        return (content or "").strip()
    if isinstance(d, dict) and isinstance(d.get("text"), str):
        return d["text"].strip()
    모음 = []

    def 훑(o):
        if isinstance(o, dict):
            if isinstance(o.get("text"), str):
                모음.append(o["text"])
            for v in o.values():
                훑(v)
        elif isinstance(o, list):
            for v in o:
                훑(v)

    훑(d)
    return " ".join(모음).strip()


def _첨부뽑기(content, msg_type):
    """파일/이미지 메시지에서 (file_key, 파일명, 종류)를 뽑는다. 첨부 아니면 (None, '', 'file')."""
    try:
        d = json.loads(content or "{}")
    except Exception:
        return None, "", "file"
    if msg_type == "file":
        return d.get("file_key"), d.get("file_name", "계약서.pdf"), "file"
    if msg_type == "image":
        return d.get("image_key"), "계약서.jpg", "image"
    return None, "", "file"


def _이미처리(글ID):
    return 글ID in set(라크.처리기록읽기())


def _처리표시(글ID):
    기록 = 라크.처리기록읽기()
    if 글ID not in 기록:
        기록.append(글ID)
        라크.처리기록쓰기(기록[-500:])   # 최근 500개만 유지


def 메시지왔을때(data):
    try:
        설정 = 라크.설정읽기()
        ev = data.event
        msg = ev.message
        글ID = msg.message_id

        # 봇 자기 메시지·시스템 메시지 제외
        if getattr(ev.sender, "sender_type", "") != "user":
            return
        if _이미처리(글ID):
            return

        토큰 = 라크.토큰받기(설정)
        chat_id = msg.chat_id
        msg_type = getattr(msg, "message_type", "")

        # 매출/지출 방에 계약서 파일(PDF·사진)을 올리면 → AI로 읽어 매출/정기매출 등록
        if ("지출" in 설정 and chat_id == 설정["지출"].get("chat_id")
                and msg_type in ("file", "image")):
            file_key, 파일명, 파일종류 = _첨부뽑기(msg.content, msg_type)
            if file_key:
                계약서설정 = {"gemini": 설정.get("견적서", {}).get("gemini")}
                처리.계약서메시지처리(토큰, 계약서설정, 설정.get("자금"),
                                chat_id, 글ID, file_key, 파일명, 파일종류)
                _처리표시(글ID)
            return

        본문 = _텍스트뽑기(msg.content)
        if not 본문:
            return

        if chat_id == 설정.get("chat_id"):
            처리.일정메시지처리(토큰, chat_id, 본문, 설정.get("trigger", ""))
        elif "지출" in 설정 and chat_id == 설정["지출"].get("chat_id"):
            # 같은 지출방: '입금'/'매출' 글이면 매출 칸에 입금으로, 아니면 지출로 기록
            if "자금" in 설정 and 매출해석.매출글인가(본문):
                처리.매출메시지처리(토큰, 설정["지출"], 설정["자금"], 본문)
            else:
                처리.지출메시지처리(토큰, 설정["지출"], 본문)
        elif "견적서" in 설정 and chat_id == 설정["견적서"].get("chat_id"):
            처리.견적서메시지처리(토큰, 설정["견적서"], 본문)
        elif "과업" in 설정 and chat_id == 설정["과업"].get("chat_id"):
            import 과업해석   # 보낸 사람 open_id로 담당 자동(생성자 디폴트)
            sender_open = getattr(getattr(ev.sender, "sender_id", None), "open_id", "") or ""
            과업설정 = dict(설정["과업"])   # 자유 문장 지시를 AI로 해석(견적서 제미나이 키 재사용)
            과업설정.setdefault("gemini", 설정.get("견적서", {}).get("gemini"))
            과업해석.과업메시지처리(본문, 과업설정, sender_open)
        else:
            print("미등록방 chat_id:", chat_id, "|", 본문[:20])  # 새 방 등록용
            return

        _처리표시(글ID)
        print("처리:", chat_id[-6:], 본문[:30])
    except Exception as e:
        print("처리 오류:", e)


def main():
    설정 = 라크.설정읽기()
    핸들러 = (
        lark_oapi.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(메시지왔을때)
        .build()
    )
    client = lark_oapi.ws.Client(
        설정["app_id"], 설정["app_secret"],
        event_handler=핸들러,
        domain=lark_oapi.LARK_DOMAIN,        # 라크(국제) 주소로 연결
        log_level=lark_oapi.LogLevel.INFO,
    )
    print("실시간 연결 시작...")
    client.start()   # 여기서 계속 떠 있으면서 메시지를 기다림


if __name__ == "__main__":
    main()
