#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
업무 대시보드용 작은 로컬 서버.

- 화면(index.html)을 띄워주고,
- 할 일 데이터(tasks.json)를 읽고/저장하는 통로 역할을 합니다.
- 맥에 기본으로 깔린 파이썬만 쓰므로 따로 설치할 게 없습니다.
"""

import http.server
import socketserver
import json
import os
import sys
import threading
import time
import webbrowser

# 여러 명이 동시에 추가/수정해도 서로 안 덮어쓰게,
# 파일을 읽고-고치고-저장하는 동안 한 번에 한 요청만 들어가도록 잠급니다.
DATA_LOCK = threading.Lock()

# VS Code 안(Simple Browser)에서 띄울 때는 외부 브라우저를 열지 않습니다.
# (실행할 때 --no-browser 를 붙이면 자동 열기를 끕니다.)
OPEN_BROWSER = "--no-browser" not in sys.argv

PORT = 7777                       # 화면 주소: http://localhost:7777
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "tasks.json")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # 이 폴더의 파일을 기준으로 서비스합니다.
        super().__init__(*args, directory=HERE, **kwargs)

    def end_headers(self):
        # 화면(index.html)·projects.json 등 정적 파일이 브라우저 캐시에 묶여
        # 옛 화면이 보이는 걸 막는다. (배포 후 강력 새로고침 안 해도 최신이 뜨게)
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        # 요청 본문(JSON)을 읽어 파이썬 값으로 돌려줍니다. 잘못된 형식이면 None.
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _load_tasks():
        try:
            with open(DATA, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    @staticmethod
    def _save_tasks(data):
        with open(DATA, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _task_id_in_path(self):
        # "/api/tasks/<id>" 형태면 <id>를, 그냥 "/api/tasks" 면 None을 돌려줍니다.
        rest = self.path[len("/api/tasks"):].split("?", 1)[0].strip("/")
        return rest or None

    def do_GET(self):
        # 할 일 목록 요청이면 tasks.json 내용을 돌려줍니다.
        if self.path.startswith("/api/tasks"):
            with DATA_LOCK:
                return self._send_json(self._load_tasks())
        # 그 외에는 일반 파일(화면 등)을 서비스합니다.
        return super().do_GET()

    def do_POST(self):
        # 할 일 "한 건"만 추가합니다. (전체를 다시 보낼 필요 없음)
        # 서버가 직접 현재 목록을 읽어 끝에 덧붙이므로, 동시에 추가해도 안 날아갑니다.
        if self.path.startswith("/api/tasks"):
            item = self._read_body()
            if not isinstance(item, dict):
                return self._send_json({"error": "할 일 한 건(객체)을 보내주세요"}, status=400)
            with DATA_LOCK:
                tasks = self._load_tasks()
                # id·createdAt 없으면 서버가 채워줍니다. (기존 데이터 관례: epoch 밀리초)
                now_ms = int(time.time() * 1000)
                if not item.get("id"):
                    item["id"] = str(now_ms)
                item.setdefault("status", "todo")
                item.setdefault("createdAt", now_ms)
                tasks.append(item)
                self._save_tasks(tasks)
            return self._send_json({"ok": True, "task": item}, status=201)
        self.send_response(404)
        self.end_headers()

    def do_PATCH(self):
        # 할 일 "한 건"만 수정합니다. /api/tasks/<id> 로 보내거나 본문에 id를 넣습니다.
        # 보낸 항목(필드)만 바꾸고 나머지는 그대로 둡니다.
        if self.path.startswith("/api/tasks"):
            changes = self._read_body()
            if not isinstance(changes, dict):
                return self._send_json({"error": "바꿀 내용(객체)을 보내주세요"}, status=400)
            task_id = self._task_id_in_path() or changes.get("id")
            if not task_id:
                return self._send_json({"error": "어떤 할 일인지 id가 필요합니다"}, status=400)
            with DATA_LOCK:
                tasks = self._load_tasks()
                for t in tasks:
                    if str(t.get("id")) == str(task_id):
                        t.update({k: v for k, v in changes.items() if k != "id"})
                        self._save_tasks(tasks)
                        return self._send_json({"ok": True, "task": t})
            return self._send_json({"error": "그 id의 할 일을 못 찾았습니다"}, status=404)
        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        # 할 일 "한 건"만 삭제합니다. /api/tasks/<id> 로 보냅니다.
        if self.path.startswith("/api/tasks"):
            task_id = self._task_id_in_path()
            if not task_id:
                body = self._read_body()
                task_id = body.get("id") if isinstance(body, dict) else None
            if not task_id:
                return self._send_json({"error": "삭제할 할 일의 id가 필요합니다"}, status=400)
            with DATA_LOCK:
                tasks = self._load_tasks()
                kept = [t for t in tasks if str(t.get("id")) != str(task_id)]
                if len(kept) == len(tasks):
                    return self._send_json({"error": "그 id의 할 일을 못 찾았습니다"}, status=404)
                self._save_tasks(kept)
            return self._send_json({"ok": True})
        self.send_response(404)
        self.end_headers()

    def do_PUT(self):
        # (기존 호환) 화면에서 보낸 목록 전체를 통째로 저장합니다.
        # 새로 추가/수정할 때는 위의 POST/PATCH 를 쓰는 게 안전합니다.
        if self.path.startswith("/api/tasks"):
            data = self._read_body()
            if not isinstance(data, list):
                return self._send_json({"error": "잘못된 형식(목록 전체를 보내야 함)"}, status=400)
            with DATA_LOCK:
                self._save_tasks(data)
            return self._send_json({"ok": True})
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        # 터미널에 매 요청 로그를 찍지 않아 화면이 깔끔합니다.
        pass


def main():
    socketserver.TCPServer.allow_reuse_address = True
    # 0.0.0.0 으로 묶어야 텔스케일(100.91.167.85)에서 접속됨. 서버 배포본은 반드시 이 값.
    with socketserver.TCPServer(("0.0.0.0", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/index.html"
        print("=" * 48)
        print("  업무 대시보드가 켜졌어요.")
        print(f"  화면 주소: {url}")
        print("  이 창을 닫으면 대시보드가 꺼집니다.")
        print("=" * 48)
        # (외부 브라우저로 쓸 때만) 잠시 뒤 화면을 자동으로 엽니다.
        if OPEN_BROWSER:
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n대시보드를 종료합니다.")


if __name__ == "__main__":
    main()
