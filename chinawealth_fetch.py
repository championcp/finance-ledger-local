# -*- coding: utf-8 -*-
"""净值抓取：中国理财网（银行业理财信息登记系统）公开披露接口。

用途：中银理财官网查不到的产品（如浙银理财）走这里。
接口：https://xinxipilu.chinawealth.com.cn/lcxp-platService/product/getNetValueList

接口非明文开放，请求体 AES-256-ECB 加密、附 RSA 签名与时间戳/随机数校验；
握手参数（AES 密钥、签名私钥）由公开接口 /m/n 与 /product/getInitData 自动取得，
无需登录、无凭据。密钥/私钥按进程缓存（TTL 内复用），避免触发限频与验证码。

查询需要两个标识：
- prodRegCode：产品登记编码（Z 开头，如 Z7011825000176），登记在备注 JSON 的 regCode
- subShareCode：份额/销售代码（如 ZYJXG0006A），即备注 JSON 的 track 或产品代码型号

只写正数净值；失败返回 (None, None, None) 并可通过 last_error() 取到原因。
"""
import os
import re
import json
import time
import base64
import hashlib
import random
import string
import datetime
import urllib.request

BASE = "https://xinxipilu.chinawealth.com.cn/lcxp-platService"
TIMEOUT = 25
TTL = 1800          # 握手缓存 30 分钟
CALL_GAP = 2.5      # 业务请求最小间隔（秒），接口连续请求约 9 次会 503
RETRIES = 2

_SESSION = {"key": None, "priv": None, "at": 0.0, "err": ""}
_LAST_CALL = [0.0]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
    "Origin": "https://xinxipilu.chinawealth.com.cn",
    "Referer": "https://xinxipilu.chinawealth.com.cn/",
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
}


def _crypto():
    """延迟导入加密库：未安装时不影响其余模块，只让本数据源不可用。"""
    from Crypto.PublicKey import RSA
    from Crypto.Cipher import AES, PKCS1_v1_5
    from Crypto.Util.Padding import pad
    from Crypto.Signature import pkcs1_15
    from Crypto.Hash import SHA256
    return RSA, AES, PKCS1_v1_5, pad, pkcs1_15, SHA256


def last_error():
    return _SESSION.get("err", "")


def _post(path, body, headers=None):
    req = urllib.request.Request(
        BASE + path, data=body.encode(), headers={**_HEADERS, **(headers or {})},
        method="POST")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read().decode("utf-8", "ignore")


def _encrypt(plain, aes_key):
    """AES-256-ECB 加密 + 时间戳/随机数/签名头。返回 (密文, 请求头)。"""
    RSA, AES, _PKCS, pad, _SIG, _SHA = _crypto()
    ct = base64.b64encode(
        AES.new(aes_key, AES.MODE_ECB).encrypt(pad(plain.encode("utf-8"), 16))
    ).decode()
    ts = str(int(time.time() * 1000))
    nonce = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(10))
    sign = hashlib.sha256(
        ("data=%s&nonce=%s&timestamp=%s&signKey=hold?fish:palm" % (ct, nonce, ts)).encode()
    ).hexdigest()
    return ct, {"X-Nonce": nonce, "X-Timestamp": ts, "X-Sign": sign}


def _handshake(force=False):
    """取 AES 密钥与签名私钥，TTL 内复用。"""
    now = time.time()
    if not force and _SESSION["key"] and now - _SESSION["at"] < TTL:
        return _SESSION["key"], _SESSION["priv"]
    RSA, _AES, PKCS1_v1_5, _pad, _SIG, _SHA = _crypto()
    # 1) 客户端生成 RSA 公私钥，服务端用公钥加密 AES 密钥后回传
    k = RSA.generate(1024)
    pub = base64.b64encode(k.publickey().export_key(format="DER")).decode()
    wrapped = base64.b64decode(_post("/m/n", pub).strip())
    aes_key = base64.b64decode(PKCS1_v1_5.new(k).decrypt(wrapped, None))
    # 2) getInitData 返回签名私钥（PEM 文本用空格代替换行）
    ct, h = _encrypt("{}", aes_key)
    init = json.loads(_post("/product/getInitData", ct, h))
    pem = "".join(re.findall(r"[A-Za-z0-9+/=]{20,}", init.get("data", "")))
    priv = RSA.import_key(base64.b64decode(pem))
    _SESSION.update({"key": aes_key, "priv": priv, "at": now})
    return aes_key, priv


def _call(path, params, sign=True):
    """发起一次业务请求（加密 body + 可选 RSA 签名），返回 dict。"""
    RSA, _AES, _PKCS, _pad, pkcs1_15, SHA256 = _crypto()
    aes_key, priv = _handshake()
    plain = json.dumps(params, separators=(",", ":"), ensure_ascii=False)
    ct, h = _encrypt(plain, aes_key)
    if sign:
        h["signature"] = base64.b64encode(
            pkcs1_15.new(priv).sign(SHA256.new(plain.encode("utf-8")))
        ).decode()
    gap = CALL_GAP - (time.time() - _LAST_CALL[0])
    if gap > 0:
        time.sleep(gap)
    out = json.loads(_post(path, ct, h))
    _LAST_CALL[0] = time.time()
    return out


def fetch_nav(sub_share_code, prod_reg_code, retries=RETRIES):
    """返回 (净值float, 日期str, 币种str)；失败返回 (None, None, None)。

    sub_share_code：份额/销售代码；prod_reg_code：产品登记编码。
    """
    _SESSION["err"] = ""
    if not sub_share_code or not prod_reg_code:
        _SESSION["err"] = "缺少份额代码或产品登记编码"
        return None, None, None
    params = {
        "subShareCode": str(sub_share_code).strip(),
        "timeType": "1",
        "prodRegCode": str(prod_reg_code).strip(),
        "pageNum": 1,
        "pageSize": 10,
    }
    last = ""
    for attempt in range(retries + 1):
        try:
            out = _call("/product/getNetValueList", params)
            if out.get("code") != 200:
                last = "接口返回 %s：%s" % (out.get("code"), out.get("msg"))
            else:
                data = out.get("data") or {}
                lst = data.get("list") or []
                if not lst:
                    last = "无净值记录"
                else:
                    # 接口按日期降序，第一条即最新
                    latest = lst[0]
                    nv = latest.get("shareNetVal")
                    try:
                        val = float(nv) if nv not in (None, "") else None
                    except (TypeError, ValueError):
                        val = None
                    if val is None or val <= 0:
                        last = "净值无效"
                    else:
                        return (val, latest.get("netValueDate"),
                                latest.get("currency") or "人民币")
        except Exception as e:
            last = "%s: %s" % (type(e).__name__, e)
            # 握手可能过期或服务端换了密钥，强制重建一次
            _SESSION.update({"key": None, "priv": None})
        if attempt < retries:
            time.sleep(CALL_GAP * (attempt + 1))
    _SESSION["err"] = last
    return None, None, None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python chinawealth_fetch.py <份额代码> <登记编码>")
        print("例:   python chinawealth_fetch.py ZYJXG0006A Z7011825000176")
    else:
        nv, d, cur = fetch_nav(sys.argv[1], sys.argv[2])
        if nv is None:
            print("抓取失败：%s" % last_error())
        else:
            print("[OK] 净值 %s · 日期 %s · 币种 %s" % (nv, d, cur))
