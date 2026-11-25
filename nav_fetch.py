# -*- coding: utf-8 -*-
"""净值抓取：按资产台账登记的跟踪代码，逐个抓中银理财官网净值。

- 接口：https://www.bocwm.cn/webApi/cms/productNetWorth/getNetWorthByCode
- 接口按日期【升序】返回，必须取最后一条才是最新净值。
- 抓到的净值写回「备注」JSON 的 nav / navDate；有份额则自动重算市值。
- 每次成功更新写一条市值快照 + 一条操作留痕。
"""
import os
import json
import time
import datetime
import urllib.request

import storage

API = "https://www.bocwm.cn/webApi/cms/productNetWorth/getNetWorthByCode"
TIMEOUT = 20
DEFAULT_ALIAS = {"ZYD3202A": "QQGPJUSDRKI"}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MAPPING_FILE = os.path.join(BASE_DIR, "mapping.json")


def load_alias():
    alias = dict(DEFAULT_ALIAS)
    if os.path.exists(MAPPING_FILE):
        try:
            with open(MAPPING_FILE, encoding="utf-8") as f:
                alias.update(json.load(f))
        except Exception:
            pass
    return alias


def _get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_nav(code, retries=2):
    """返回 (净值, 日期, 币种)；失败返回 (None, None, None)。"""
    url = "%s?productCode=%s&pageNo=1&pageSize=10" % (API, code)
    for attempt in range(retries + 1):
        try:
            d = _get(url)
            data = d.get("data") or []
            if not data:
                return None, None, None
            latest = data[-1]  # 升序：最后一条才是最新
            nv = latest.get("shareNetWorth")
            return (float(nv) if nv not in (None, "") else None,
                    latest.get("releaseDate"),
                    latest.get("currency"))
        except Exception:
            if attempt < retries:
                time.sleep(1.5)
            else:
                return None, None, None
    return None, None, None


def parse_meta(raw):
    try:
        o = json.loads(raw)
        if isinstance(o, dict):
            return o
    except Exception:
        pass
    return {"memo": raw or ""}


def track_code(rec, alias):
    """确定用于抓取的官网份额代码。

    优先级与前端 navTrack 保持一致：销售代码命中别名映射时优先用官网代码，
    否则才用备注里手填的 track，最后回退销售代码本身。
    """
    meta = parse_meta(rec.get("备注", ""))
    sale = rec.get("产品代码型号", "") or ""
    return alias.get(sale) or meta.get("track") or sale


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.date.today().strftime("%Y-%m-%d")


def run(verbose=True):
    storage.init_db()
    alias = load_alias()
    assets = storage.query("assets")
    results = []
    for rec in assets:
        name = rec.get("名称", "")
        code = track_code(rec, alias)
        meta = parse_meta(rec.get("备注", ""))
        share = meta.get("share", "")
        if not code:
            results.append({"name": name, "status": "skip", "msg": "未登记净值代码"})
            continue
        nv, nvdate, cur = fetch_nav(code)
        if nv is None:
            results.append({"name": name, "status": "fail", "code": code, "msg": "未取到净值"})
            continue

        # 先保存旧净值用于留痕，再覆盖（修复参考实现中"新值→新值"的缺陷）
        old_nav = meta.get("nav", "") or "未登记"
        meta["nav"] = str(nv)
        if nvdate:
            meta["navDate"] = str(nvdate)[:10]
        note = json.dumps(meta, ensure_ascii=False)

        old_mv = float(rec.get("当前市值余额", 0) or 0)
        share_f = float(share) if str(share).strip() not in ("", "None") else 0
        updates = {"备注": note, "更新日期": today()}
        new_mv = old_mv
        if share_f > 0:
            new_mv = round(share_f * nv, 2)
            updates["当前市值余额"] = new_mv
        storage.update("assets", rec["record_id"], updates)

        currency = rec.get("货币种类", "人民币") or "人民币"
        storage.add("snapshot", {
            "日期": {"date": today()},
            "资产名称": {"text": name},
            "市值": {"number": new_mv},
            "备注": {"text": "净值自动更新 · 净值%s · %s" % (nv, nvdate or "")},
            "货币种类": {"select": currency},
        })
        storage.add("audit", {
            "时间": {"text": now_str()},
            "操作对象": {"text": "资产/" + name},
            "动作": {"select": "净值更新"},
            "变更详情": {"text": "净值 %s → %s(%s)，市值 %s" % (old_nav, nv, nvdate, new_mv)},
            "操作人": {"text": "自动抓取"},
        })
        results.append({
            "name": name, "status": "ok", "code": code, "nav": nv,
            "date": nvdate, "currency": cur, "share": share_f,
            "old_mv": old_mv, "new_mv": new_mv,
        })
        if verbose:
            print("[OK] %s | %s | 净值 %s → %s (%s) | 市值 %.2f -> %.2f" %
                  (name, code, old_nav, nv, nvdate, old_mv, new_mv))
    return results


if __name__ == "__main__":
    rs = run()
    ok = sum(1 for r in rs if r["status"] == "ok")
    print("\n完成：成功 %d / 共 %d 条" % (ok, len(rs)))
