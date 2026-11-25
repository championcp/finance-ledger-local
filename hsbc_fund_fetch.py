# -*- coding: utf-8 -*-
"""基金净值抓取：汇丰（香港）投资单上的单位信托基金。

用途：汇丰银行代销的基金（如汇丰环球货币基金-港元 U50001），
这类基金不在中银理财官网、也不在银行业理财登记系统里，走汇丰投资单的公开报价接口。

接口（来自汇丰投资单基金详情页的网络请求）：
  GET .../wmds/quoteDetail?body=<urlencoded JSON>
返回 priceQuote.priceQuote（单位净值）、currency、exchangeUpdatedTime（净值日期）。

备注 JSON 里带 src="汇丰基金" 时走这里；基金代码取 track（已清理隐藏字符）。
查询需要一段固定的 HSBC 渠道请求头（均为公开网页的常规头，无登录凭据）。
成功返回正数净值；失败返回 (None, None, None)，原因见 last_error()。
"""
import re
import json
import time
import urllib.request
from urllib.parse import quote

BASE = ("https://investments3.personal-banking.hsbc.com.hk/shp/"
        "wealth-mobile-mds-shp-api-hk-hbap-prod-proxy/v0/wmds/quoteDetail")
TIMEOUT = 20
RETRIES = 2
DETAIL = "https://investments3.personal-banking.hsbc.com.hk/public/utb/en-gb/fundDetail/"

# 汇丰投资单网页调用公开报价接口时带的渠道头（公开信息，无账号凭据）
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Accept": "application/json",
    "x-hsbc-chnl-countrycode": "HK",
    "x-hsbc-chnl-lineofbusiness": "PFS",
    "x-hsbc-app-code": "SRBP",
    "x-hsbc-channel-id": "OHI",
    "x-hsbc-locale": "en_GB",
    "x-hsbc-chnl-group-member": "HBAP",
}

_err = ""


def last_error():
    return _err


def clean_code(raw):
    """清理代码里粘贴混入的零宽字符/空白。"""
    return re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff\s]", "", str(raw or ""))


def fetch_nav(fund_code, retries=RETRIES):
    """返回 (净值float, 日期str, 币种str)；失败返回 (None, None, None)。"""
    global _err
    _err = ""
    code = clean_code(fund_code)
    if not code:
        _err = "未登记基金代码"
        return None, None, None
    params = {
        "market": "HK",
        "productType": "UT",
        "prodAltNum": code,
        "prodCdeAltClassCde": "M",
        "delay": True,
        "entityTimezone": "Asia/Hong_Kong",
    }
    url = BASE + "?body=" + quote(json.dumps(params, separators=(",", ":")))
    headers = {**_HEADERS, "referer": DETAIL + code}
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                d = json.loads(resp.read().decode("utf-8", "ignore"))
            pq = d.get("priceQuote") or {}
            nv = pq.get("priceQuote")
            val = float(nv) if nv not in (None, "") else None
            if val is None or val <= 0:
                _err = "未取到有效净值"
            else:
                return (val, pq.get("exchangeUpdatedTime"), pq.get("currency") or "港元")
        except Exception as e:
            _err = "%s: %s" % (type(e).__name__, e)
        if attempt < retries:
            time.sleep(1.5)
    return None, None, None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("用法: python hsbc_fund_fetch.py <基金代码>")
        print("例:   python hsbc_fund_fetch.py U50001")
    else:
        nv, d, cur = fetch_nav(sys.argv[1])
        if nv is None:
            print("抓取失败：%s" % last_error())
        else:
            print("[OK] 净值 %s · 日期 %s · 币种 %s" % (nv, d, cur))
