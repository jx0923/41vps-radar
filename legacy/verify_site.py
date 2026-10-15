#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
站点校验：确保生成的 index.html 可正常渲染
==========================================
1. 抽取内嵌 <script> 块，交给 Node 做语法校验（node --check）
2. 校验内嵌 JSON 可解析，且与 data/deals.json 一致
3. 校验 HTML 结构完整性（标签配对、无残留占位符）
4. 校验模板占位符已全部替换
"""
import json
import os
import re
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8")
HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
INDEX = os.path.join(SITE, "index.html")
NODE = (r"C:\Users\Administrator\.dsh\dsh-runtimes\dsh-primary-runtime"
        r"\dependencies\node\bin\node.exe")

fails = []
warns = []


def ok(msg):
    print("  [OK]   " + msg)


def fail(msg):
    print("  [FAIL] " + msg)
    fails.append(msg)


def warn(msg):
    print("  [WARN] " + msg)
    warns.append(msg)


html = open(INDEX, encoding="utf-8").read()
print("=" * 72)
print("1. 占位符替换检查")
print("=" * 72)
left = re.findall(r"@@[A-Z_]+@@", html)
if left:
    fail("残留占位符: %s" % set(left))
else:
    ok("所有 @@PLACEHOLDER@@ 已替换")

print()
print("=" * 72)
print("2. 内嵌 JSON 校验 + 与源文件一致性")
print("=" * 72)
m = re.search(r'<script type="application/json" id="deals-data">(.*?)</script>',
              html, re.S)
if not m:
    fail("找不到内嵌 JSON 块")
    embedded = None
else:
    raw = m.group(1)
    try:
        embedded = json.loads(raw)
        ok("内嵌 JSON 可解析，%d 条记录" % len(embedded.get("records", [])))
    except Exception as e:
        fail("内嵌 JSON 解析失败: %s" % e)
        embedded = None

src = json.load(open(os.path.join(HERE, "data", "deals.json"), encoding="utf-8"))
api = json.load(open(os.path.join(SITE, "data", "deals.json"), encoding="utf-8"))

if embedded is not None:
    if len(embedded["records"]) == len(src["records"]):
        ok("内嵌记录数与源一致 (%d)" % len(src["records"]))
    else:
        fail("记录数不一致: 内嵌 %d vs 源 %d"
             % (len(embedded["records"]), len(src["records"])))
    if len(api["records"]) == len(src["records"]):
        ok("API JSON 记录数与源一致 (%d)" % len(api["records"]))
    else:
        fail("API 记录数不一致")
    # 逐条比对 thread_id
    a = [r["thread_id"] for r in embedded["records"]]
    b = [r["thread_id"] for r in src["records"]]
    if a == b:
        ok("记录顺序与 ID 完全一致")
    else:
        fail("记录 ID/顺序不一致")

print()
print("=" * 72)
print("3. 内嵌 JS 语法校验 (node --check)")
print("=" * 72)
js_blocks = re.findall(r"<script>(.*?)</script>", html, re.S)
if not js_blocks:
    fail("找不到内嵌 JS")
else:
    js = "\n".join(js_blocks)
    print("  JS 体积: %.1f KB" % (len(js) / 1024))
    tmp = os.path.join(HERE, "_check.js")
    open(tmp, "w", encoding="utf-8").write(js)
    if os.path.exists(NODE):
        p = subprocess.run([NODE, "--check", tmp],
                           capture_output=True, text=True)
        if p.returncode == 0:
            ok("node --check 通过，无语法错误")
        else:
            fail("node --check 失败:\n" + (p.stderr or "")[:1500])
    else:
        warn("未找到 node，跳过语法校验 (%s)" % NODE)
    os.remove(tmp)

print()
print("=" * 72)
print("4. HTML 结构完整性")
print("=" * 72)
for tag in ("html", "head", "body", "table", "thead", "tbody", "script", "style"):
    o = len(re.findall(r"<%s[\s>]" % tag, html, re.I))
    c = len(re.findall(r"</%s>" % tag, html, re.I))
    if o == c:
        ok("<%s> 配对 (%d)" % (tag, o))
    else:
        fail("<%s> 不配对: 开 %d / 闭 %d" % (tag, o, c))

for need in ('id="tb"', 'id="chips"', 'id="q"', 'id="sort"',
             'id="avail"', 'id="bigonly"', 'id="hideold"', 'id="empty"'):
    if need in html:
        ok("存在挂载点 %s" % need)
    else:
        fail("缺少挂载点 %s" % need)

print()
print("=" * 72)
print("5. 关键数据点抽查（渲染前置）")
print("=" * 72)
bero = [r for r in src["records"] if "BERO" in r["title"].upper()]
if bero:
    b = bero[0]
    print("  BERO 记录:")
    print("    provider : %s" % b["provider"])
    print("    specs    : %s" % b["specs"])
    print("    price    : %s" % (b.get("flagship_price")))
    print("    event    : %s" % b["event_type"])
    if b["specs"].get("ram_gb") == 32 and b["specs"].get("vcpu") == 8:
        ok("BERO 旗舰配置正确 (8C/32G)")
    else:
        fail("BERO 旗舰配置异常: %s" % b["specs"])
    if b.get("flagship_price", {}).get("amount") == 129:
        ok("BERO 旗舰价正确 (€129)")
    else:
        fail("BERO 旗舰价异常: %s" % b.get("flagship_price"))
else:
    warn("样本中未找到 BERO 记录")

# score / annual_eur 是展示层字段，由 build_site.py 计算并写入站点 API JSON
scored = [r for r in api["records"] if "score" in r]
if len(scored) == len(api["records"]):
    ok("API JSON 全部记录已计算 score")
else:
    fail("score 缺失: %d/%d" % (len(scored), len(api["records"])))
priced = [r for r in api["records"] if r.get("annual_eur") is not None]
if priced:
    ok("已计算年化价格 %d/%d" % (len(priced), len(api["records"])))
else:
    warn("没有任何记录能算出年化价格")

# 内嵌数据也应带上这两个字段（前端排序依赖）
if embedded is not None:
    es = [r for r in embedded["records"] if "score" in r]
    if len(es) == len(embedded["records"]):
        ok("内嵌数据已带 score（前端排序可用）")
    else:
        fail("内嵌数据缺 score: %d/%d" % (len(es), len(embedded["records"])))
    sc = sorted(api["records"], key=lambda r: -r.get("score", 0))[:1]
    if sc:
        print("  力度最高: %s (score=%d)" % (sc[0]["provider"], sc[0]["score"]))

print()
print("=" * 72)
if fails:
    print("结果: %d 项失败, %d 项警告" % (len(fails), len(warns)))
    for f in fails:
        print("  - " + f.split("\n")[0])
    sys.exit(1)
print("结果: 全部通过 (%d 项警告)" % len(warns))
