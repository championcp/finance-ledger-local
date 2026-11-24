# -*- coding: utf-8 -*-
"""本地数据层：SQLite 持久化，提供与页面一致的数据表读写契约。

关键点：页面写入的 properties 是 {text/number/date/select: 值} 包裹格式，
读取时返回扁平标量，否则前端 num()/opt() 会把数字解析成 0 或空。
"""
import os
import json
import uuid
import sqlite3
import threading
import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SEED_DIR = os.path.join(BASE_DIR, "seed")
DB_PATH = os.path.join(DATA_DIR, "finance.db")

# databaseId -> (物理表名, seed 文件名)
TABLES = {
    "R4EP1k4l2TSnv3MWALkCiN": ("assets", "assets.json"),
    "470rjrUP5bjKVeFfzTH0qU": ("txn", "txn.json"),
    "Epene6sRljkIPqp7deopV8": ("snapshot", "snapshot.json"),
    "hpr7iAwVjW4B1yUKR4Iym9": ("audit", "audit.json"),
    "L2XpEYpZb71srUm0Jt3fXN": ("rate", "rate.json"),
}
ID_TO_TABLE = {k: v[0] for k, v in TABLES.items()}
TABLE_TO_ID = {v[0]: k for k, v in TABLES.items()}

_write_lock = threading.Lock()


def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db(force_seed=False):
    """建表 + 首次从 seed 导入。seed 为空时得到空表，不写入任何示例数据。"""
    os.makedirs(DATA_DIR, exist_ok=True)
    with _conn() as c:
        for t in ID_TO_TABLE.values():
            c.execute(
                "CREATE TABLE IF NOT EXISTS %s ("
                "record_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL)" % t
            )
        total = sum(c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
                    for t in ID_TO_TABLE.values())
        if total == 0 or force_seed:
            for t, seedfile in TABLES.values():
                c.execute("DELETE FROM %s" % t)
                path = os.path.join(SEED_DIR, seedfile)
                if not os.path.exists(path):
                    continue
                with open(path, encoding="utf-8") as f:
                    obj = json.load(f)
                for r in obj.get("results", []):
                    rid = r.get("record_id") or r.get("_id") or uuid.uuid4().hex[:12]
                    flat = {k: v for k, v in r.items() if k not in ("record_id", "_id")}
                    c.execute(
                        "INSERT OR REPLACE INTO %s (record_id,data,updated_at) VALUES (?,?,?)" % t,
                        (rid, json.dumps(flat, ensure_ascii=False), _now()),
                    )
    return True


def flatten(props):
    """把 {text/number/date/select: v} 解包成标量 v；已是标量则原样。"""
    out = {}
    for k, v in (props or {}).items():
        if isinstance(v, dict):
            for key in ("number", "text", "date", "select"):
                if key in v:
                    out[k] = v[key]
                    break
            else:
                out[k] = ""
        else:
            out[k] = v
    return out


def query(table):
    with _conn() as c:
        rows = c.execute("SELECT record_id,data FROM %s" % table).fetchall()
    out = []
    for row in rows:
        rec = json.loads(row["data"])
        rec["record_id"] = row["record_id"]
        out.append(rec)
    return out


def add(table, props):
    flat = flatten(props)
    rid = uuid.uuid4().hex[:12]
    with _write_lock, _conn() as c:
        c.execute(
            "INSERT INTO %s (record_id,data,updated_at) VALUES (?,?,?)" % table,
            (rid, json.dumps(flat, ensure_ascii=False), _now()),
        )
    return rid


def update(table, rid, props):
    flat = flatten(props)
    with _write_lock, _conn() as c:
        row = c.execute("SELECT data FROM %s WHERE record_id=?" % table, (rid,)).fetchone()
        merged = json.loads(row["data"]) if row else {}
        merged.update(flat)
        c.execute(
            "UPDATE %s SET data=?,updated_at=? WHERE record_id=?" % table,
            (json.dumps(merged, ensure_ascii=False), _now(), rid),
        )
    return True


def delete(table, rid):
    with _write_lock, _conn() as c:
        c.execute("DELETE FROM %s WHERE record_id=?" % table, (rid,))
    return True


def replace_record(table, rid, flat):
    """整条替换（抓取脚本更新备注 JSON 时用）。"""
    with _write_lock, _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO %s (record_id,data,updated_at) VALUES (?,?,?)" % table,
            (rid, json.dumps(flat, ensure_ascii=False), _now()),
        )
    return True


def data_version():
    """所有表记录数 + 最新更新时间的摘要，供前端轮询判断后台是否写入。"""
    with _conn() as c:
        parts = []
        for t in ID_TO_TABLE.values():
            n = c.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0]
            mx = c.execute("SELECT MAX(updated_at) FROM %s" % t).fetchone()[0] or ""
            parts.append("%s:%s:%s" % (t, n, mx))
    return "|".join(parts)
