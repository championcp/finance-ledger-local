# -*- coding: utf-8 -*-
"""家庭理财台账 · 桌面版入口（手动启动模式）

行为：
- 启动时：拉起本机 Flask 服务 → 后台同步一次数据（抓净值 + 刷汇率 + 备份）。
- 运行中：独立 WebKit 窗口加载本机页面。
- 关闭时：彻底终止自己拉起的服务并释放监听端口，不留后台进程。

不使用 launchd 常驻：服务的生命周期与窗口绑定，开则起、关则净。
"""
import os
import sys
import time
import socket
import signal
import subprocess
import threading
import urllib.request

import webview

import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
APP = os.path.join(BASE_DIR, "app.py")
HOST = config.HOST
PORT = config.PORT
URL = config.URL
DESKTOP_LOG = os.path.join(BASE_DIR, "data", "desktop.log")


def _log(msg):
    line = "[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        os.makedirs(os.path.dirname(DESKTOP_LOG), exist_ok=True)
        with open(DESKTOP_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    print(line)


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
    """返回本进程拉起的子进程；服务已在运行则返回 None（不重复拉起）。"""
    if service_ready():
        return None
    os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)
    log = open(DESKTOP_LOG, "a")
    # 关键：不加 start_new_session，让服务与桌面进程同组；关闭时可连带回收。
    proc = subprocess.Popen([PY, APP], stdout=log, stderr=subprocess.STDOUT,
                            cwd=BASE_DIR)
    for _ in range(40):
        if service_ready():
            _log("服务已就绪 (PID %d)" % proc.pid)
            return proc
        if proc.poll() is not None:
            _log("服务启动失败，见 desktop.log")
            return None
        time.sleep(0.25)
    return proc


def sync_once():
    """启动时同步一次数据：抓净值 → 刷汇率 → 备份。返回摘要字典。"""
    summary = {"nav": None, "rate": None, "backup": None}
    try:
        import nav_fetch
        summary["nav"] = nav_fetch.run(verbose=False)
        ok = sum(1 for r in (summary["nav"] or []) if r.get("status") == "ok")
        _log("净值同步完成：成功 %d / 共 %d 条" % (ok, len(summary["nav"] or [])))
    except Exception as e:
        _log("净值同步失败：%s" % e)
    try:
        import rate_fetch
        summary["rate"] = rate_fetch.run(verbose=False)
        _log("汇率同步完成：%s（%s）" %
             (summary["rate"]["source"], summary["rate"]["time"] or "无牌价时间"))
    except Exception as e:
        _log("汇率同步失败：%s" % e)
    try:
        import backup as backup_mod
        summary["backup"] = backup_mod.run(verbose=False)
        _log("备份完成：%s（保留 %d 份）" %
             ("成功" if summary["backup"]["ok"] else "失败",
              summary["backup"]["kept"]))
    except Exception as e:
        _log("备份失败：%s" % e)
    return summary


def _pids_on_port():
    """反查占用 PORT 的 PID 列表（macOS lsof）。"""
    try:
        out = subprocess.check_output(
            ["lsof", "-nP", "-t", "-iTCP:%d" % PORT, "-sTCP:LISTEN"],
            stderr=subprocess.DEVNULL, timeout=5)
        return [int(x) for x in out.decode().split() if x.strip().isdigit()]
    except Exception:
        return []


def stop_service(proc):
    """彻底终止服务并释放端口。可重复调用（幂等）。返回端口是否已释放。"""
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        _log("已终止服务进程 (PID %d)" % proc.pid)

    # 兜底：反查端口，把残留的监听进程也清掉（含非本进程拉起的情况）
    for pid in _pids_on_port():
        try:
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.3)
            if _is_pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
            _log("已清理端口残留进程 (PID %d)" % pid)
        except Exception as e:
            _log("清理端口残留进程 %d 失败：%s" % (pid, e))

    # 等待端口真正释放（最多约 6 秒）
    for _ in range(24):
        if not port_open():
            _log("端口 %d 已释放" % PORT)
            return True
        time.sleep(0.25)
    _log("端口 %d 仍被占用（请检查是否有其他程序使用）" % PORT)
    return False


def _is_pid_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def main():
    proc = ensure_service()

    # 后台同步一次数据，不阻塞窗口出现；页面靠 /api/version 轮询自动刷新。
    def _bg_sync():
        sync_once()
    threading.Thread(target=_bg_sync, daemon=True).start()

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
        stop_service(proc)

    # pywebview 6.x：关闭事件挂在 window.events.closed 上
    window.events.closed += on_closed
    try:
        webview.start()
    finally:
        # 兜底：无论事件是否触发，退出时都确保服务停、端口放。
        stop_service(proc)


if __name__ == "__main__":
    main()
