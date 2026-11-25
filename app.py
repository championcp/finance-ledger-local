# -*- coding: utf-8 -*-
"""家庭理财台账 · 本地版服务
只监听 127.0.0.1，手机/局域网/外网均无法访问，数据仅存本机 SQLite。
"""
import os
import threading
import datetime
import io
from flask import Flask, request, jsonify, send_from_directory, send_file

import storage
import config

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")

app = Flask(__name__, static_folder=None)

storage.init_db()


@app.after_request
def no_cache(resp):
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")


@app.route("/api/query", methods=["POST"])
def api_query():
    dbid = request.json.get("databaseId", "")
    table = storage.ID_TO_TABLE.get(dbid)
    if not table:
        return jsonify({"results": [], "hasMore": False, "nextCursor": ""})
    return jsonify({"results": storage.query(table), "hasMore": False, "nextCursor": ""})


@app.route("/api/add", methods=["POST"])
def api_add():
    dbid = request.json.get("databaseId", "")
    table = storage.ID_TO_TABLE.get(dbid)
    if not table:
        return jsonify({"_id": ""}), 400
    rid = storage.add(table, request.json.get("properties", {}))
    return jsonify({"_id": rid})


@app.route("/api/update", methods=["POST"])
def api_update():
    dbid = request.json.get("databaseId", "")
    rid = request.json.get("recordId", "")
    table = storage.ID_TO_TABLE.get(dbid)
    if not table:
        return jsonify({"ok": False}), 400
    storage.update(table, rid, request.json.get("properties", {}))
    return jsonify({"ok": True})


@app.route("/api/delete", methods=["POST"])
def api_delete():
    dbid = request.json.get("databaseId", "")
    rid = request.json.get("recordId", "")
    table = storage.ID_TO_TABLE.get(dbid)
    if not table:
        return jsonify({"ok": False}), 400
    storage.delete(table, rid)
    return jsonify({"ok": True})


@app.route("/api/version")
def api_version():
    return jsonify({"v": storage.data_version()})


_refresh_lock = threading.Lock()


@app.route("/api/refresh-nav", methods=["POST"])
def api_refresh_nav():
    if not _refresh_lock.acquire(blocking=False):
        return jsonify({"ok": False, "msg": "正在抓取中，请稍候"})
    try:
        # 延迟导入：抓取模块尚未部署时不影响其余接口
        import nav_fetch
        rs = nav_fetch.run(verbose=True)
        return jsonify({
            "ok": True,
            "results": rs,
            "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    finally:
        _refresh_lock.release()


_rate_lock = threading.Lock()


@app.route("/api/refresh-rate", methods=["POST"])
def api_refresh_rate():
    """自动抓取最新汇率（招行现汇买入价优先）并写回汇率表。"""
    if not _rate_lock.acquire(blocking=False):
        return jsonify({"ok": False, "msg": "正在抓取中，请稍候"})
    try:
        import rate_fetch
        rs = rate_fetch.run(verbose=True)
        rates = {r["currency"]: r["rate"] for r in rs["results"] if r["status"] == "ok"}
        return jsonify({
            "ok": bool(rates),
            "rates": rates,
            "source": rs["source"],
            "time": rs["time"],
            "msg": rs["fallback"],
            "at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
    finally:
        _rate_lock.release()


@app.route("/api/export")
def api_export():
    """导出登记的资产明细为 Excel（只读，不改数据）。"""
    try:
        import exporter
        data = exporter.build_bytes()
        return send_file(
            io.BytesIO(data),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=exporter.filename(),
        )
    except Exception as e:
        return jsonify({"ok": False, "msg": "导出失败：%s" % e}), 500


@app.route("/api/status")
def api_status():
    return jsonify({
        "ok": True,
        "db": storage.DB_PATH,
        "counts": {t: len(storage.query(t)) for t in storage.ID_TO_TABLE.values()},
        "version": storage.data_version(),
    })


if __name__ == "__main__":
    port = config.PORT
    print("=" * 56)
    print("  家庭理财台账 · 本地版已启动")
    print("  打开浏览器访问： http://127.0.0.1:%d" % port)
    print("  数据文件： %s" % storage.DB_PATH)
    print("  仅本机可访问，按 Ctrl+C 停止")
    print("=" * 56)
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True, use_reloader=False)
