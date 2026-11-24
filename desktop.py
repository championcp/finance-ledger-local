# -*- coding: utf-8 -*-
"""家庭理财台账 · 桌面版入口
用系统 WebKit 打开一个独立窗口，加载本机 Flask 服务。
若服务未运行则自动拉起；退出时只关闭自己拉起的服务，不影响 launchd 常驻服务。
"""
import os
import sys
import time
import socket
import subprocess
import urllib.request

import webview

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
APP = os.path.join(BASE_DIR, "app.py")
HOST = "127.0.0.1"
PORT = int(os.environ.get("FINANCE_PORT", "8765"))
URL = "http://%s:%d" % (HOST, PORT)


def port_open():
    s = socket.socket()
    s.settimeout(0.5)
    try:
        return s.connect_ex((HOST, PORT)) == 0
    finally:
        s.close()


def service_ready():
    try:
        with urllib.request.urlopen(URL + "/api/status", timeout=1) as r:
            return r.status == 200
    except Exception:
        return False


def ensure_service():
    """返回本进程拉起的子进程；服务已存在则返回 None。"""
    if service_ready():
        return None
    log = open(os.path.join(BASE_DIR, "data", "desktop-server.log"), "a")
    proc = subprocess.Popen([PY, APP], stdout=log, stderr=subprocess.STDOUT,
                            cwd=BASE_DIR, start_new_session=True)
    for _ in range(40):
        if service_ready():
            return proc
        if proc.poll() is not None:
            return None
        time.sleep(0.25)
    return proc


def main():
    proc = ensure_service()
    window = webview.create_window(
        "家庭理财台账 · 本地版",
        URL,
        width=1280,
        height=900,
        min_size=(900, 600),
        resizable=True,
        confirm_close=True,
    )

    def on_closed():
        if proc is not None and proc.poll() is None:
            proc.terminate()

    window.closed += on_closed
    webview.start()
    if proc is not None and proc.poll() is None:
        proc.terminate()


if __name__ == "__main__":
    main()
