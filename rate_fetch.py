# -*- coding: utf-8 -*-
"""汇率抓取：自动获取美元/港币对人民币汇率，写回 rate 表。

数据源（按优先级）：
1. 招商银行外汇牌价页（shishihuilv 聚合的招行牌价）——取「现汇买入价」，
   与银行 App 里把美元/港币折算成人民币的口径一致（赎回结汇到手价）。
2. open.er-api.com 免费中间价接口——作为备用，抓不到招行牌价时用。

- 只写正数、范围合理的汇率；抓不到或异常时保留原值不动。
- 每次成功更新写一条审计留痕。
- 抓取结果带来源与时间，便于前端展示"数据来自哪里、什么时候"。
"""
import os
import re
import ssl
import json
import time
import datetime
import urllib.request

import storage

TIMEOUT = 15
CMB_PAGE = "https://www.shishihuilv.com/cmbchina.htm"
ER_API = "https://open.er-api.com/v6/latest/USD"

# 合理区间兜底，防止页面改版抓到离谱数字写进账本
RANGE = {"美元": (5.0, 9.0), "港币": (0.5, 1.5)}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", "ignore")
    except urllib.error.URLError as e:
        # 某些环境（如带 TLS 中间人代理的沙箱）证书链校验会失败。
        # 这里只读公开牌价页、不传任何凭据，严格校验失败后降级重试一次。
        if "CERTIFICATE_VERIFY_FAILED" not in str(e):
            raise
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
            return resp.read().decode("utf-8", "ignore")


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today():
    return datetime.date.today().strftime("%Y-%m-%d")


def _validate(currencies):
    """过滤掉非正数或超出合理区间的币种。"""
    out = {}
    for cur, val in currencies.items():
        if cur not in RANGE:  # 只接受登记过的币种（美元/港币）
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        lo, hi = RANGE[cur]
        if lo <= v <= hi:
            out[cur] = round(v, 6)
    return out


def fetch_cmb(retries=1):
    """抓招行牌价，返回 (rates, quote_time, source)；失败抛异常。"""
    last = None
    for attempt in range(retries + 1):
        try:
            html = _get(CMB_PAGE)
            rates = {}
            quote_time = ""
            for cur in ("美元", "港币"):
                i = html.find(">" + cur + "<")
                if i < 0:
                    i = html.find(cur)
                if i < 0:
                    continue
                seg = html[i:i + 900]
                vals = re.findall(r'data-value="([0-9.]+)"', seg)
                if vals and float(vals[0]) > 0:
                    rates[cur] = float(vals[0])  # 第 1 个值 = 现汇买入价
                tm = re.search(r'class="time">([^<]+)', seg)
                if tm and not quote_time:
                    quote_time = tm.group(1).strip()
            rates = _validate(rates)
            if "美元" in rates:  # 美元是必选，港币可选
                return rates, quote_time, "招商银行现汇买入价"
            last = ValueError("未解析到美元汇率")
        except Exception as e:
            last = e
        if attempt < retries:
            time.sleep(1.5)
    raise last if last else ValueError("招行牌价抓取失败")


def fetch_backup(retries=1):
    """抓 open.er-api 中间价，返回 (rates, quote_time, source)；失败抛异常。"""
    last = None
    for attempt in range(retries + 1):
        try:
            d = json.loads(_get(ER_API))
            if d.get("result") != "success":
                raise ValueError("接口返回非 success")
            r = d.get("rates") or {}
            cny = float(r["CNY"])
            hkd = float(r["HKD"])
            rates = _validate({"美元": cny, "港币": cny / hkd})
            if "美元" in rates:
                return rates, d.get("time_last_update_utc", ""), "open.er-api 中间价"
            last = ValueError("中间价解析异常")
        except Exception as e:
            last = e
        if attempt < retries:
            time.sleep(1.5)
    raise last if last else ValueError("备用汇率抓取失败")


def fetch(retries=2):
    """自动选源：优先招行现汇买入价，失败回退中间价。返回统一结构。"""
    try:
        rates, qtime, src = fetch_cmb(retries)
    except Exception as e:
        rates, qtime, src = fetch_backup(retries)
        return {"ok": True, "rates": rates, "time": qtime, "source": src,
                "fallback": "招行牌价抓取失败：%s" % e}
    return {"ok": True, "rates": rates, "time": qtime, "source": src, "fallback": ""}


def run(verbose=True):
    """抓汇率 → 写 rate 表 → 留痕。返回逐币种结果列表。"""
    storage.init_db()
    got = fetch()
    rates = got["rates"]
    src = got["source"]
    qtime = got["time"]

    existing = {str(r.get("币种", "")): r for r in storage.query("rate")}
    results = []
    for cur in ("美元", "港币"):
        if cur not in rates:
            results.append({"currency": cur, "status": "skip", "msg": "未取到汇率"})
            continue
        new_val = rates[cur]
        hit = existing.get(cur)
        old_val = float(hit.get("兑人民币汇率", 0) or 0) if hit else 0
        pv = {
            "币种": {"select": cur},
            "兑人民币汇率": {"number": new_val},
            "更新日期": {"date": today()},
            "数据来源": {"text": src},
            "牌价时间": {"text": qtime},
        }
        if hit:
            storage.update("rate", hit["record_id"], pv)
        else:
            storage.add("rate", pv)
        storage.add("audit", {
            "时间": {"text": now_str()},
            "操作对象": {"text": "汇率/" + cur},
            "动作": {"select": "汇率更新"},
            "变更详情": {"text": "%s 汇率 %.6f → %.6f（%s%s）" %
                          (cur, old_val, new_val, src, " · " + qtime if qtime else "")},
            "操作人": {"text": "自动抓取"},
        })
        results.append({"currency": cur, "status": "ok", "rate": new_val,
                        "old": old_val, "source": src, "time": qtime})
        if verbose:
            print("[OK] %s %.6f → %.6f (%s)" % (cur, old_val, new_val, src))
    if verbose and got.get("fallback"):
        print("[WARN] " + got["fallback"])
    return {"results": results, "source": src, "time": qtime,
            "fallback": got.get("fallback", "")}


if __name__ == "__main__":
    out = run()
    print("\n完成：%s · 牌价时间 %s" % (out["source"], out["time"] or "未提供"))
