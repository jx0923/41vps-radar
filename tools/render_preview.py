#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
离线渲染预览图（不依赖浏览器）
=============================
用 Pillow 把 deals.json 渲染成一张「总览表」PNG，
作为静态站的视觉参照 —— 也方便在没有浏览器的环境里检查数据。

用法: python render_preview.py
输出: preview.png
"""
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.stdout.reconfigure(encoding="utf-8")
# 本脚本位于 tools/，项目根在上一级
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

EVENT_CN = {
    "anniversary": "周年庆", "black_friday": "黑五", "holiday": "节日促销",
    "launch": "上新/回归", "restock": "补货", "sale": "常规促销",
    "regular": "常规帖",
}
AVAIL_CN = {
    "ON_SALE": "在售", "SOLD_OUT": "售罄", "ENDED": "结束",
    "RESTOCKING": "补货中", "PARTIAL": "部分售罄",
    "LIKELY_SOLD_OUT": "疑似售罄",
    "UNVERIFIED": "待确认", "UNVERIFIED_STALE": "待确认",
}
CYCLE_CN = {"year": "/年", "quarter": "/季", "month": "/月"}

W, ROW_H, HDR_H = 1560, 34, 42
PAD = 18
COLS = [
    ("厂商", 250), ("活动性质", 92), ("力度", 400),
    ("配置 / CPU", 300), ("旗舰价", 96), ("状态", 78), ("置信", 60),
]


def pick_font(size, bold=False):
    cands = []
    if bold:
        cands += ["C:/Windows/Fonts/msyhbd.ttc", "C:/Windows/Fonts/segoeuib.ttf"]
    cands += ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/segoeui.ttf",
              "C:/Windows/Fonts/simhei.ttf", "C:/Windows/Fonts/arial.ttf"]
    for c in cands:
        if os.path.exists(c):
            try:
                return ImageFont.truetype(c, size)
            except Exception:
                continue
    return ImageFont.load_default()


def spec_text(r):
    s = r.get("specs") or {}
    b = []
    if s.get("vcpu"):
        b.append("%dC" % s["vcpu"])
    if s.get("ram_gb"):
        b.append("%dG" % int(s["ram_gb"]))
    if s.get("storage_gb"):
        t = s.get("storage_type") or ""
        if t.lower() == "unspecified":
            t = ""
        b.append("%dG%s" % (int(s["storage_gb"]), t))
    head = "/".join(b) if b else "—"
    cpu = ", ".join((r.get("cpu_models") or [])[:1])
    return "%s | %s" % (head, cpu) if cpu else head


def price_text(r):
    p = r.get("flagship_price") or ((r.get("prices") or [None])[0])
    if not p:
        return "—"
    return "%s%g%s" % (p["currency"], p["amount"], CYCLE_CN.get(p["cycle"], ""))


def main():
    data = json.load(open(os.path.join(HERE, "data", "deals.json"),
                          encoding="utf-8"))
    recs = data["records"]

    EVENT_RANK = {"anniversary": 0, "black_friday": 1, "holiday": 2,
                  "launch": 3, "restock": 4, "sale": 5, "regular": 6}
    recs = sorted(recs, key=lambda r: (
        EVENT_RANK.get(r["event_type"], 9), -r["confidence"],
        r["age_days"] if r["age_days"] is not None else 9999))[:24]

    H = HDR_H + ROW_H * len(recs) + PAD * 3 + 62
    img = Image.new("RGB", (W, H), "#ffffff")
    d = ImageDraw.Draw(img)

    f_title = pick_font(24, True)
    f_sub = pick_font(13)
    f_head = pick_font(13, True)
    f_cell = pick_font(13)
    f_mono = pick_font(12)

    y = PAD
    d.text((PAD, y), "VPS 活动雷达 — LowEndTalk 优惠总览", "#111827", font=f_title)
    y += 34
    d.text((PAD, y), "数据源: LowEndTalk Offers RSS   ·   共 %d 条记录   ·   生成 %s"
           % (data["count"], data.get("generated_at", "")[:19]),
           "#6b7280", font=f_sub)
    y += 26
    d.line([(PAD, y), (W - PAD, y)], fill="#e5e7eb", width=1)
    y += 10

    # 表头
    x = PAD
    for name, w in COLS:
        d.text((x + 6, y + 10), name, "#6b7280", font=f_head)
        x += w
    y += HDR_H
    d.line([(PAD, y), (W - PAD, y)], fill="#e5e7eb", width=1)

    for i, r in enumerate(recs):
        bg = "#f9fafb" if i % 2 else "#ffffff"
        d.rectangle([PAD, y, W - PAD, y + ROW_H], fill=bg)
        x = PAD
        cy = y + 9

        prov = r["provider"]
        d.text((x + 6, cy), prov[:30], "#111827", font=f_cell)
        x += COLS[0][1]

        ev = EVENT_CN.get(r["event_type"], r["event_type"])
        col = {"anniversary": "#b91c1c", "black_friday": "#b91c1c",
               "holiday": "#b45309", "launch": "#1d4ed8",
               "restock": "#047857", "sale": "#6d28d9"}.get(r["event_type"], "#6b7280")
        d.text((x + 6, cy), ev, col, font=f_cell)
        x += COLS[1][1]

        strength = (r.get("discount") or {}).get("strength") or "—"
        d.text((x + 6, cy), strength[:46], "#374151", font=f_mono)
        x += COLS[2][1]

        d.text((x + 6, cy), spec_text(r)[:34], "#374151", font=f_mono)
        x += COLS[3][1]

        d.text((x + 6, cy), price_text(r), "#111827", font=f_cell)
        x += COLS[4][1]

        av = AVAIL_CN.get(r["availability"], r["availability"])
        acol = {"ON_SALE": "#059669", "SOLD_OUT": "#dc2626",
                "ENDED": "#dc2626"}.get(r["availability"], "#9ca3af")
        d.text((x + 6, cy), av, acol, font=f_cell)
        x += COLS[5][1]

        d.text((x + 6, cy), "%d%%" % round(r["confidence"] * 100),
               "#6b7280", font=f_cell)
        y += ROW_H

    d.line([(PAD, y), (W - PAD, y)], fill="#e5e7eb", width=1)
    y += 12
    d.text((PAD, y), "注：库存状态来自帖文关键词推断，标注「待确认」不等于有货；"
                     "价格与库存请以厂商官网为准。", "#9ca3af", font=f_sub)

    out = os.path.join(HERE, "preview.png")
    img.save(out)
    print("预览图已生成: %s  (%dx%d, %.1f KB)"
          % (out, W, H, os.path.getsize(out) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
