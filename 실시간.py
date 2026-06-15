# -*- coding: utf-8 -*-
"""
라크 롱커넥션(WebSocket)으로 메시지를 '즉시' 받아 처리합니다.
주기적으로 물어보지 않으므로 라크 호출 한도를 거의 쓰지 않습니다.
연결이 끊겨도 SDK가 자동으로 다시 붙습니다.
"""

import json
import lark as 라크          # 우리 도구 (메시지보내기, 설정읽기, 처리기록 등)
import 처리
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

        본문 = _텍스트뽑기(msg.content)
        if not 본문:
            return

        토큰 = 라크.토큰받기(설정)
        chat_id = msg.chat_id

        if chat_id == 설정.get("chat_id"):
            처리.일정메시지처리(토큰, chat_id, 본문, 설정.get("trigger", ""))
        elif "지출" in 설정 and chat_id == 설정["지출"].get("chat_id"):
            처리.지출메시지처리(토큰, 설정["지출"], 본문)
        elif "견적서" in 설정 and chat_id == 설정["견적서"].get("chat_id"):
            처리.견적서메시지처리(토큰, 설정["견적서"], 본문)
        else:
            return  # 우리가 쓰는 방이 아니면 무시

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
