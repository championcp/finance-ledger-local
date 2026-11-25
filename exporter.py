# -*- coding: utf-8 -*-
"""明细导出：把「我的理财」登记的资产台账导出为 Excel。

只导出用户登记的数据（assets 主表），不夹带系统自动生成的流水/快照/留痕。
列与页面主表一致；备注里的净值跟踪信息（份额/净值/净值日期/代码）拆成独立列；
多币种按汇率表折合人民币；负债类收益显示 “—”；末尾附合计行。

导出只读，不改动任何数据。
"""
import io
import json
import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

import storage

LIAB_CATS = {"房贷", "车贷", "信用卡欠款"}
DEFAULT_RATE = {"美元": 7.25, "港币": 0.93}

HEADERS = [
    "名称", "产品代码型号", "分类", "归属人", "机构", "货币种类", "购买日",
    "投入本金(原币)", "当前金额(原币)", "净值代码", "持有份额", "最新净值", "净值日期",
    "投入本金(折合¥)", "当前金额(折合¥)", "收益(¥)", "到期日", "更新日期", "状态", "备注",
]

# 收益口径：已落袋（卖出/取出/转出/利息/分红）计入收益；追加投入（买入/存入/转入/费用）计入成本。
CASH_IN = {"卖出", "取出", "转出", "利息", "分红"}
CASH_OUT = {"买入", "存入", "转入", "费用"}


def _cash_sum(txn, name, types):
    return sum(_num(r.get("金额")) for r in txn
               if (r.get("关联资产") or "") == name and (r.get("类型") or "") in types)


def _num(v):
    try:
        n = float(v)
        return n
    except (TypeError, ValueError):
        return 0.0


def _d10(v):
    return str(v)[:10] if v else ""


def _meta(raw):
    """解析备注里的净值跟踪 JSON；非 JSON 则当纯文本备注。"""
    raw = raw or ""
    try:
        o = json.loads(raw)
        if isinstance(o, dict):
            return o, (o.get("memo") or "")
    except (ValueError, TypeError):
        pass
    return {}, raw


def _rates():
    out = {}
    for r in storage.query("rate"):
        cur = r.get("币种", "")
        v = _num(r.get("兑人民币汇率"))
        if cur and v > 0:
            out[cur] = v
    return out


def _rate_of(cur, rates):
    if not cur or cur == "人民币":
        return 1.0
    return rates.get(cur) or DEFAULT_RATE.get(cur) or 1.0


def build_workbook():
    """返回一个 openpyxl Workbook（内存中），不落盘。"""
    rates = _rates()
    assets = storage.query("assets")
    txn = storage.query("txn")

    wb = Workbook()
    ws = wb.active
    ws.title = "理财明细"

    thin = Side(style="thin", color="D0D7DE")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    head_fill = PatternFill("solid", fgColor="2563EB")
    head_font = Font(color="FFFFFF", bold=True, size=11)
    total_fill = PatternFill("solid", fgColor="EFF4FF")
    up_font = Font(color="D92D20")    # 中国习惯：涨=红
    down_font = Font(color="079455")  # 跌=绿

    ws.append(HEADERS)
    for c in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = border
    ws.freeze_panes = "A2"

    tot_principal = tot_market = tot_gain = 0.0
    row = 2
    for rec in assets:
        meta, memo = _meta(rec.get("备注", ""))
        name = rec.get("名称", "") or ""
        cat = rec.get("分类", "") or ""
        cur = rec.get("货币种类", "") or "人民币"
        principal = _num(rec.get("投入本金"))
        market = _num(rec.get("当前市值余额"))
        rate = _rate_of(cur, rates)
        cny_p = principal * rate
        cny_m = market * rate
        is_liab = cat in LIAB_CATS
        cashed = _cash_sum(txn, name, CASH_IN)      # 已落袋（原币）
        invested = _cash_sum(txn, name, CASH_OUT)   # 追加投入（原币）
        gain = "—" if is_liab else round((market + cashed - principal - invested) * rate, 2)
        if not is_liab:
            tot_principal += cny_p
            tot_market += cny_m
            tot_gain += gain

        values = [
            name, rec.get("产品代码型号", ""), cat, rec.get("归属人", ""), rec.get("机构", ""),
            cur, _d10(rec.get("购买日")), round(principal, 2), round(market, 2),
            meta.get("track", ""), meta.get("share", ""), meta.get("nav", ""), meta.get("navDate", ""),
            round(cny_p, 2), round(cny_m, 2), gain,
            _d10(rec.get("到期日")), _d10(rec.get("更新日期")), rec.get("状态", ""), memo,
        ]
        ws.append(values)
        for c in range(1, len(HEADERS) + 1):
            ws.cell(row=row, column=c).border = border
        # 金额列两位小数
        for c in (8, 9, 14, 15, 16):
            cell = ws.cell(row=row, column=c)
            if isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0.00"
        gain_cell = ws.cell(row=row, column=16)
        if isinstance(gain_cell.value, (int, float)):
            gain_cell.font = up_font if gain_cell.value > 0 else (down_font if gain_cell.value < 0 else Font())
        row += 1

    # 合计行（仅资产类，负债不计入；收益红涨绿跌）
    ws.append([
        "合计", "", "", "", "", "", "", "", "", "", "", "", "",
        round(tot_principal, 2), round(tot_market, 2), round(tot_gain, 2),
        "", "", "", "",
    ])
    for c in range(1, len(HEADERS) + 1):
        cell = ws.cell(row=row, column=c)
        cell.fill = total_fill
        cell.font = Font(bold=True)
        cell.border = border
    for c in (14, 15, 16):
        ws.cell(row=row, column=c).number_format = "#,##0.00"
    gc = ws.cell(row=row, column=16)
    gc.font = up_font if gc.value > 0 else (down_font if gc.value < 0 else Font(bold=True))

    widths = [26, 16, 12, 10, 14, 10, 12, 16, 16, 16, 14, 12, 12, 18, 18, 14, 12, 12, 10, 30]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    # 导出元信息放在第二个 sheet，不污染明细表
    info = wb.create_sheet("导出说明")
    info.append(["项目", "内容"])
    info["A1"].font = Font(bold=True, color="FFFFFF")
    info["A1"].fill = head_fill
    info["B1"].font = Font(bold=True, color="FFFFFF")
    info["B1"].fill = head_fill
    info_rows = [
        ("导出时间", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("数据来源", "本机家庭理财台账 · 资产台账（仅登记明细）"),
        ("记录数", len(assets)),
        ("折合说明", "投入本金/当前金额(折合¥) 按汇率表折算；人民币汇率=1"),
        ("收益说明", "收益=(当前金额+已卖出/已落袋-投入本金-追加投入)×汇率；份额市值按最新登记值，记一笔不重复扣减；负债类显示 —"),
        ("颜色说明", "收益红色为浮动盈利，绿色为浮动亏损（中国习惯）"),
        ("隐私提醒", "本文件含真实资产信息，请勿上传公开网盘或代码仓库"),
    ]
    for k, v in info_rows:
        info.append([k, v])
    info.column_dimensions["A"].width = 16
    info.column_dimensions["B"].width = 60

    return wb


def build_bytes():
    """返回 xlsx 文件的字节流。"""
    wb = build_workbook()
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def filename():
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return "家庭理财台账_明细_%s.xlsx" % stamp
