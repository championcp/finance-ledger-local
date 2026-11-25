# -*- coding: utf-8 -*-
"""数据库定期备份：用 SQLite 在线备份接口生成一致性快照，按保留策略清理旧备份。

为什么不用 cp：
    数据库开启了 WAL 模式，直接复制 finance.db 可能复制到"半写"状态的页，
    备份不可用。sqlite3.Connection.backup() 是 SQLite 官方在线备份 API，
    能在数据库被网页服务/抓取脚本读写时安全地拿到一致性快照，无需停服。

备份位置： data/backups/finance_YYYYMMDD_HHMMSS.db
保留策略： 默认保留最近 KEEP 份（30 份），多的从最旧开始删。
手动执行： python3 backup.py
"""
import os
import re
import glob
import time
import shutil
import sqlite3
import datetime

import storage

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(BASE_DIR, "data", "backups")
BACKUP_LOG = os.path.join(BASE_DIR, "data", "backup.log")
DB_PATH = storage.DB_PATH
KEEP = int(os.environ.get("FINANCE_BACKUP_KEEP", "30"))

_FNAME_RE = re.compile(r"^finance_(\d{8}_\d{6})(?:_\d+)?\.db$")


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log(msg):
    line = "[%s] %s\n" % (_now(), msg)
    try:
        os.makedirs(os.path.dirname(BACKUP_LOG), exist_ok=True)
        with open(BACKUP_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass
    print(line.rstrip())


def list_backups():
    """按文件名里的升序返回已有备份的完整路径。"""
    if not os.path.isdir(BACKUP_DIR):
        return []
    found = []
    for p in glob.glob(os.path.join(BACKUP_DIR, "finance_*.db")):
        if _FNAME_RE.match(os.path.basename(p)):
            found.append(p)
    return sorted(found)  # 名字含时间戳，字典序即时间序


def _verify(path):
    """对备份文件做完整性检查 + 读出各表记录数。返回 (ok, counts, err)。"""
    counts = {}
    try:
        con = sqlite3.connect(path)
        try:
            chk = con.execute("PRAGMA integrity_check").fetchone()[0]
            if chk != "ok":
                return False, counts, "integrity_check=%s" % chk
            for t in storage.ID_TO_TABLE.values():
                counts[t] = con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
        finally:
            con.close()
        return True, counts, ""
    except Exception as e:
        return False, counts, str(e)


def run(verbose=True):
    """执行一次备份 + 校验 + 轮转。返回结果字典。"""
    storage.init_db()  # 确保库与表结构存在（幂等）
    os.makedirs(BACKUP_DIR, exist_ok=True)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = os.path.join(BACKUP_DIR, "finance_%s.db" % ts)
    # 同一秒内重复触发时避免覆盖
    n = 1
    while os.path.exists(dst):
        dst = os.path.join(BACKUP_DIR, "finance_%s_%d.db" % (ts, n))
        n += 1

    ok, counts, err = False, {}, ""
    try:
        src = sqlite3.connect(DB_PATH, timeout=15)
        try:
            target = sqlite3.connect(dst)
            try:
                src.backup(target)  # 在线一致性备份，WAL 下也安全
            finally:
                target.close()
        finally:
            src.close()
        ok, counts, err = _verify(dst)
        if not ok:
            _log("备份校验失败：%s（保留文件待排查：%s）" % (err, dst))
    except Exception as e:
        err = str(e)
        _log("备份失败：%s" % err)
        # 清理失败产生的残缺文件
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except Exception:
                pass

    removed = []
    if ok:
        _log("备份成功：%s（%s，%d 字节）" % (os.path.basename(dst),
             ", ".join("%s=%d" % (k, v) for k, v in counts.items()),
             os.path.getsize(dst)))
        # 轮转：保留最近 KEEP 份
        all_bk = list_backups()
        while len(all_bk) > KEEP:
            old = all_bk.pop(0)
            try:
                os.remove(old)
                removed.append(os.path.basename(old))
            except Exception as e:
                _log("清理旧备份失败 %s：%s" % (os.path.basename(old), e))
        if removed:
            _log("已清理 %d 份旧备份：%s" % (len(removed), ", ".join(removed)))

    return {
        "ok": ok,
        "path": dst if ok else "",
        "counts": counts,
        "removed": removed,
        "kept": len(list_backups()),
        "at": _now(),
        "error": err,
    }


if __name__ == "__main__":
    r = run()
    print("\n完成：%s | 当前保留 %d 份备份" %
          ("成功" if r["ok"] else "失败（%s）" % r["error"], r["kept"]))
    raise SystemExit(0 if r["ok"] else 1)
