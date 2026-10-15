#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LET Deals Radar — 静态站生成器
==============================
读 data/deals.json  ->  生成可部署的静态站 site/

产物:
    site/index.html        单文件站点（数据内嵌，支持 file:// 直接打开）
    site/data/deals.json   给外部消费的 API 端点
    site/robots.txt
    site/sitemap.xml
    site/.nojekyll         供 GitHub Pages 使用

零依赖：只用 Python 标准库。前端用原生 JS，无框架、无 CDN。

用法:
    python build_site.py
    python build_site.py --deals data/deals.json --out site
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

# 汇率仅用于「跨币种粗略排序」，不用于展示成交价。
# 需要更新时改这里即可。
FX_TO_EUR = {"€": 1.00, "$": 0.92, "£": 1.17}
FX_NOTE = "跨币种排序按近似汇率折算（€1.00 / $0.92 / £1.17），仅供参考"

CYCLE_TO_YEAR = {"year": 1.0, "quarter": 4.0, "month": 12.0}
CYCLE_CN = {"year": "/年", "quarter": "/季", "month": "/月"}

EVENT_CN = {
    "anniversary": "周年庆", "black_friday": "黑五", "holiday": "节日促销",
    "launch": "上新/回归", "restock": "补货", "sale": "常规促销",
    "regular": "常规帖",
}
AVAIL_CN = {
    "ON_SALE": "在售", "SOLD_OUT": "售罄", "ENDED": "活动结束",
    "RESTOCKING": "补货中", "LIKELY_SOLD_OUT": "疑似售罄",
    "UNVERIFIED": "待确认", "UNVERIFIED_STALE": "待确认(较旧)",
}
# 活动性质的"力度权重"，用于综合评分
EVENT_WEIGHT = {
    "anniversary": 25, "black_friday": 25, "holiday": 15,
    "launch": 10, "restock": 8, "sale": 5, "regular": 0,
}


def deal_score(r: dict) -> int:
    """活动力度综合评分（0-120）。分越高越"值得看"。"""
    s = 0.0
    d = r.get("discount") or {}
    if d.get("recurring"):
        s += 30                      # 循环/永久折扣最值钱
    pm = d.get("percent_max")
    if pm:
        s += min(pm, 70) * 0.8       # 折扣幅度
    s += EVENT_WEIGHT.get(r.get("event_type"), 0)
    if d.get("extras"):
        s += 10                      # 免费加倍/加赠
    if d.get("codes"):
        s += 5
    s += (r.get("confidence") or 0) * 10
    return int(round(s))


def annual_eur(r: dict) -> float | None:
    """年化价格（欧元近似），仅用于排序。"""
    p = r.get("flagship_price") or (r["prices"][0] if r.get("prices") else None)
    if not p:
        return None
    mult = CYCLE_TO_YEAR.get(p.get("cycle"), 12.0)
    rate = FX_TO_EUR.get(p.get("currency"), 1.0)
    return round(p["amount"] * mult * rate, 2)


def price_text(r: dict) -> str:
    p = r.get("flagship_price") or (r["prices"][0] if r.get("prices") else None)
    if not p:
        return "—"
    return "%s%g%s" % (p["currency"], p["amount"],
                       CYCLE_CN.get(p.get("cycle"), ""))


def spec_text(r: dict) -> str:
    s = r.get("specs") or {}
    bits = []
    if s.get("vcpu"):
        bits.append("%dC" % s["vcpu"])
    if s.get("ram_gb"):
        bits.append("%dG" % int(s["ram_gb"]))
    if s.get("storage_gb"):
        st = s.get("storage_type") or ""
        if st.lower() == "unspecified":
            st = ""
        bits.append("%dG%s" % (int(s["storage_gb"]), st))
    head = "/".join(bits) if bits else "—"
    cpu = ", ".join((r.get("cpu_models") or [])[:2])
    return "%s | %s" % (head, cpu) if cpu else head


def json_for_script(obj) -> str:
    """把 JSON 安全内嵌进 <script>：转义 < 防止 </script> 逃逸。"""
    return (json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("&", "\\u0026"))


# --------------------------------------------------------------------------
# HTML 模板
# --------------------------------------------------------------------------

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>VPS 活动雷达 — LowEndTalk 优惠总览</title>
<meta name="description" content="自动汇总 LowEndTalk Offers 版块的 VPS 优惠活动，标注折扣力度、循环折扣与库存状态。数据每 6 小时更新。">
<style>
:root{
  --bg:#f6f7f9; --card:#fff; --ink:#16181d; --muted:#6b7280; --line:#e5e7eb;
  --accent:#2563eb; --accent-soft:#eff6ff; --good:#059669; --warn:#d97706;
  --bad:#dc2626; --chip:#f3f4f6;
}
@media (prefers-color-scheme:dark){
  :root{ --bg:#0f1115; --card:#171a21; --ink:#e8eaed; --muted:#9aa0a6;
         --line:#272b34; --accent:#60a5fa; --accent-soft:#1e293b;
         --good:#34d399; --warn:#fbbf24; --bad:#f87171; --chip:#1f232b; }
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1400px;margin:0 auto;padding:24px 18px 64px}
header h1{margin:0 0 6px;font-size:24px;letter-spacing:-.3px}
header p{margin:0;color:var(--muted);font-size:13px}
.meta{margin-top:10px;display:flex;flex-wrap:wrap;gap:14px;
  color:var(--muted);font-size:12px}
.meta b{color:var(--ink);font-weight:600}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:16px;margin-top:18px}
.controls{display:flex;flex-wrap:wrap;gap:10px;align-items:center}
input[type=search],select{background:var(--card);color:var(--ink);
  border:1px solid var(--line);border-radius:8px;padding:8px 10px;font-size:13px;
  font-family:inherit;outline:none}
input[type=search]{min-width:240px;flex:1}
input[type=search]:focus,select:focus{border-color:var(--accent)}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px}
.chip{background:var(--chip);border:1px solid var(--line);border-radius:999px;
  padding:5px 12px;font-size:12.5px;cursor:pointer;user-select:none;
  color:var(--ink);white-space:nowrap}
.chip:hover{border-color:var(--accent)}
.chip.on{background:var(--accent);border-color:var(--accent);color:#fff}
.chip .n{opacity:.6;margin-left:5px;font-variant-numeric:tabular-nums}
.chip.on .n{opacity:.85}
label.toggle{display:inline-flex;align-items:center;gap:6px;font-size:13px;
  color:var(--ink);cursor:pointer;white-space:nowrap}
.tblwrap{overflow-x:auto;margin-top:4px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:10px 10px;text-align:left;border-bottom:1px solid var(--line);
  vertical-align:top}
th{position:sticky;top:0;background:var(--card);font-weight:600;font-size:12px;
  color:var(--muted);text-transform:uppercase;letter-spacing:.4px;z-index:1;
  cursor:pointer;user-select:none;white-space:nowrap}
th:hover{color:var(--accent)}
th .ar{opacity:.45;font-size:10px}
tr.row{cursor:pointer}
tr.row:hover{background:var(--accent-soft)}
tr.row.open{background:var(--accent-soft)}
.pv{font-weight:600}
.tt{color:var(--muted);font-size:12px;margin-top:2px;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
  overflow:hidden}
.spec{font-variant-numeric:tabular-nums;white-space:nowrap}
.price{font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
.badge{display:inline-block;border-radius:6px;padding:2px 7px;font-size:11.5px;
  font-weight:600;white-space:nowrap}
.b-anniversary,.b-black_friday{background:#fee2e2;color:#b91c1c}
.b-holiday{background:#fef3c7;color:#b45309}
.b-launch{background:#dbeafe;color:#1d4ed8}
.b-restock{background:#d1fae5;color:#047857}
.b-sale{background:#ede9fe;color:#6d28d9}
.b-regular{background:var(--chip);color:var(--muted)}
@media (prefers-color-scheme:dark){
  .b-anniversary,.b-black_friday{background:#450a0a;color:#fca5a5}
  .b-holiday{background:#451a03;color:#fcd34d}
  .b-launch{background:#172554;color:#93c5fd}
  .b-restock{background:#022c22;color:#6ee7b7}
  .b-sale{background:#2e1065;color:#c4b5fd}
}
.av{font-size:12px;white-space:nowrap}
.av-ON_SALE{color:var(--good);font-weight:600}
.av-SOLD_OUT{color:var(--bad);font-weight:600}
.av-ENDED{color:var(--bad)}
.av-RESTOCKING{color:var(--warn);font-weight:600}
.av-LIKELY_SOLD_OUT{color:var(--warn)}
.av-UNVERIFIED,.av-UNVERIFIED_STALE{color:var(--muted)}
.bar{display:inline-block;width:44px;height:6px;border-radius:3px;
  background:var(--line);vertical-align:middle;margin-right:6px;overflow:hidden}
.bar i{display:block;height:100%;background:var(--accent)}
.det{background:var(--bg)}
.det>td{padding:0}
.detin{padding:14px 16px;border-left:3px solid var(--accent)}
.detin h4{margin:0 0 8px;font-size:12px;color:var(--muted);
  text-transform:uppercase;letter-spacing:.4px}
.pt{width:100%;border-collapse:collapse;font-size:12.5px;margin-bottom:12px}
.pt th,.pt td{padding:5px 8px;border-bottom:1px solid var(--line)}
.pt th{position:static;background:transparent;font-size:11px}
.kv{display:flex;flex-wrap:wrap;gap:8px 20px;font-size:12.5px;color:var(--muted)}
.kv b{color:var(--ink);font-weight:600}
.tag{display:inline-block;background:var(--chip);border-radius:5px;
  padding:1px 6px;font-size:11.5px;margin-right:4px;font-family:ui-monospace,
  SFMono-Regular,Menlo,monospace}
.empty{text-align:center;color:var(--muted);padding:48px 0}
footer{margin-top:28px;color:var(--muted);font-size:12px;line-height:1.9}
.note{background:var(--chip);border-left:3px solid var(--warn);border-radius:0 8px 8px 0;
  padding:10px 14px;font-size:12.5px;color:var(--muted);margin-top:14px}
code{background:var(--chip);padding:1px 5px;border-radius:4px;font-size:12px}
@media(max-width:760px){
  .hidesm{display:none}
  input[type=search]{min-width:100%}
}
</style>
</head>
<body>
<div class="wrap">

<header>
  <h1>VPS 活动雷达</h1>
  <p>自动汇总 LowEndTalk <b>Offers</b> 版块的 VPS 优惠，标注折扣力度、循环折扣与库存状态。</p>
  <div class="meta">
    <span>数据源 <a href="@@SOURCE@@" target="_blank" rel="noopener">LowEndTalk Offers RSS</a></span>
    <span>共 <b id="m-total">@@COUNT@@</b> 条</span>
    <span>生成于 <b>@@GENERATED@@</b></span>
    <span><a href="data/deals.json">原始 JSON</a></span>
  </div>
</header>

<div class="card">
  <div class="controls">
    <input type="search" id="q" placeholder="搜索厂商 / CPU / 优惠码 / 地点…">
    <select id="avail">
      <option value="all">全部状态</option>
      <option value="ON_SALE">在售</option>
      <option value="SOLD_OUT">售罄</option>
      <option value="UNVERIFIED">待确认</option>
    </select>
    <select id="sort">
      <option value="score">按活动力度</option>
      <option value="new">按最新</option>
      <option value="price">按价格(低→高)</option>
      <option value="conf">按置信度</option>
      <option value="provider">按厂商</option>
    </select>
    <label class="toggle">
      <input type="checkbox" id="bigonly"> 只看大力度
    </label>
    <label class="toggle">
      <input type="checkbox" id="hideold"> 隐藏 30 天前的
    </label>
  </div>
  <div class="chips" id="chips"></div>
  <div class="note">
    <b>关于「库存」</b>：库存判定优先采信<b>商家本人在回帖中的表态</b>（点开任意一行可看证据原文）；
    无商家表态时退回帖文关键词，仍无法判定则标「待确认」。
    <b>「待确认」不等于有货</b>，下单前请点进原帖或到厂商官网核实。
  </div>
</div>

<div class="card">
  <div class="tblwrap">
    <table>
      <thead>
        <tr>
          <th data-s="provider">厂商 <span class="ar"></span></th>
          <th data-s="event">活动性质 <span class="ar"></span></th>
          <th data-s="score">力度 <span class="ar"></span></th>
          <th data-s="spec">配置 / CPU <span class="ar"></span></th>
          <th data-s="price">旗舰价 <span class="ar"></span></th>
          <th data-s="avail">状态 <span class="ar"></span></th>
          <th data-s="conf">置信度 <span class="ar"></span></th>
          <th class="hidesm" data-s="age">发布于 <span class="ar"></span></th>
        </tr>
      </thead>
      <tbody id="tb"></tbody>
    </table>
  </div>
  <div class="empty" id="empty" style="display:none">没有匹配的条目</div>
</div>

<footer>
  <div>数据来自 LowEndTalk 公开 RSS，仅作信息聚合，<b>不构成购买建议</b>。</div>
  <div>@@FXNOTE@@</div>
  <div>库存与价格以厂商官网为准；本站标注的「待确认」表示未能自动验证。</div>
</footer>

</div>

<script type="application/json" id="deals-data">@@DATA@@</script>
<script>
(function(){
  var DATA = JSON.parse(document.getElementById('deals-data').textContent);
  var R = DATA.records || [];

  var EVENT_CN = @@EVENT_CN@@;
  var AVAIL_CN = @@AVAIL_CN@@;

  var st = { q:'', event:'all', avail:'all', big:false, hideold:false,
             sort:'score', open:{} };

  function esc(s){
    return String(s==null?'':s).replace(/[&<>"']/g, function(c){
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
    });
  }
  function specText(r){
    var s=r.specs||{}, b=[];
    if(s.vcpu) b.push(s.vcpu+'C');
    if(s.ram_gb) b.push(Math.round(s.ram_gb)+'G');
    if(s.storage_gb){
      var t=(s.storage_type||'').toLowerCase()==='unspecified'?'':(s.storage_type||'');
      b.push(Math.round(s.storage_gb)+'G'+t);
    }
    var head=b.length?b.join('/'):'—';
    var cpu=(r.cpu_models||[]).slice(0,2).join(', ');
    return cpu?head+' | '+cpu:head;
  }
  function priceText(r){
    var p=r.flagship_price||((r.prices||[])[0]);
    if(!p) return '—';
    var c={year:'/年',quarter:'/季',month:'/月'}[p.cycle]||'';
    return p.currency+(+p.amount)+c;
  }
  function ageText(r){
    if(r.age_days==null) return '—';
    if(r.age_days===0) return '今天';
    return r.age_days+' 天前';
  }
  function bigDeal(r){
    var d=r.discount||{};
    return !!(d.recurring || (d.percent_max&&d.percent_max>=30)
              || r.event_type==='anniversary' || r.event_type==='black_friday');
  }

  function passes(r){
    if(st.event!=='all' && r.event_type!==st.event) return false;
    if(st.avail!=='all'){
      if(st.avail==='UNVERIFIED'){
        if(r.availability!=='UNVERIFIED' && r.availability!=='UNVERIFIED_STALE') return false;
      } else if(r.availability!==st.avail) return false;
    }
    if(st.big && !bigDeal(r)) return false;
    if(st.hideold && r.age_days!=null && r.age_days>30) return false;
    if(st.q){
      var hay=[r.provider,r.title,(r.cpu_models||[]).join(' '),
               (r.locations||[]).join(' '),
               ((r.discount||{}).codes||[]).join(' '),
               ((r.discount||{}).strength||''),
               (r.specs_all?JSON.stringify(r.specs_all):'')]
              .join(' ').toLowerCase();
      if(hay.indexOf(st.q.toLowerCase())<0) return false;
    }
    return true;
  }

  function cmp(a,b){
    switch(st.sort){
      case 'new':
        return (a.age_days==null?1e9:a.age_days)-(b.age_days==null?1e9:b.age_days);
      case 'price':{
        var x=a.annual_eur==null?1e12:a.annual_eur,
            y=b.annual_eur==null?1e12:b.annual_eur;
        return x-y;
      }
      case 'conf': return (b.confidence||0)-(a.confidence||0);
      case 'provider': return String(a.provider).localeCompare(String(b.provider));
      case 'event': return (b.score||0)-(a.score||0);
      case 'avail': return String(a.availability).localeCompare(String(b.availability));
      case 'age': return (a.age_days==null?1e9:a.age_days)-(b.age_days==null?1e9:b.age_days);
      default: return (b.score||0)-(a.score||0);
    }
  }

  function planRows(r){
    var ps=r.plans||[];
    if(!ps.length) return '';
    // 同一帖子可能含多条产品线（如 EPYC / Ryzen / IPv6-only），套餐名会重复。
    // 分组规则：某套餐名首次出现时记录其"指纹"；当该名字再次出现且指纹不同，
    // 说明进入了新的产品线，组号 +1。
    var firstKey={}, group=0;
    var rowsHtml='';
    ps.forEach(function(p){
      var key=(p.vcpu||'')+'/'+(p.ram_gb||'')+'/'+(p.storage_gb||'')+'/'+
              ((p.price&&p.price.amount)||'');
      if(firstKey[p.name]===undefined){
        firstKey[p.name]=key;
      } else if(firstKey[p.name]!==key){
        group++;
        firstKey[p.name]=key;   // 重置为该组指纹，避免连续误增
      }
      var label=esc(p.name);
      if(group>0) label+=' <span style="opacity:.5;font-size:11px">#'+(group+1)+'</span>';
      rowsHtml+='<tr><td>'+label+'</td>'+
         '<td>'+(p.vcpu?p.vcpu+'C':'—')+'</td>'+
         '<td>'+(p.ram_gb?Math.round(p.ram_gb)+'G':'—')+'</td>'+
         '<td>'+(p.storage_gb?Math.round(p.storage_gb)+'G'+
              ((p.storage_type&&p.storage_type!=='unspecified')?' '+esc(p.storage_type):''):'—')+'</td>'+
         '<td>'+(p.bandwidth_tb?p.bandwidth_tb+'TB':'—')+'</td>'+
         '<td>'+(p.price?(p.price.currency+(+p.price.amount)+'/年'):'—')+'</td></tr>';
    });
    return '<h4>套餐明细（自动解析 '+ps.length+' 条）</h4>'+
           '<table class="pt"><thead><tr>'+
           '<th>套餐</th><th>CPU</th><th>内存</th><th>存储</th><th>流量</th><th>价格</th>'+
           '</tr></thead><tbody>'+rowsHtml+'</tbody></table>';
  }

  function detail(r){
    var d=r.discount||{}, codes=d.codes||[], ex=d.extras||[];
    var h='<div class="detin">';
    h+=planRows(r);
    h+='<h4>抽取信息</h4><div class="kv">';
    h+='<span>地点 <b>'+((r.locations||[]).join(', ')||'—')+'</b></span>';
    h+='<span>活动性质 <b>'+(EVENT_CN[r.event_type]||r.event_type)+'</b></span>';
    h+='<span>置信度 <b>'+Math.round((r.confidence||0)*100)+'%</b></span>';
    h+='<span>循环折扣 <b>'+(d.recurring?'是':'否/未提及')+'</b></span>';
    if(d.percent_max) h+='<span>最大折扣 <b>'+d.percent_max+'%</b></span>';
    if(r.age_days!=null) h+='<span>发布 <b>'+ageText(r)+'</b></span>';
    if(r.author) h+='<span>发帖人 <b>'+esc(r.author)+'</b></span>';
    h+='</div>';
    if(codes.length){
      h+='<h4 style="margin-top:12px">优惠码（需复核）</h4><div>';
      codes.forEach(function(c){ h+='<span class="tag">'+esc(c)+'</span>'; });
      h+='</div>';
    }
    if(ex.length){
      h+='<h4 style="margin-top:12px">加赠</h4><div>';
      ex.forEach(function(c){ h+='<span class="tag">'+esc(c)+'</span>'; });
      h+='</div>';
    }
    if(r.stock_hints&&r.stock_hints.length){
      h+='<h4 style="margin-top:12px">帖文库存关键词</h4><div>';
      r.stock_hints.forEach(function(c){ h+='<span class="tag">'+esc(c)+'</span>'; });
      h+='</div>';
    }
    // 回帖证据（库存的权威来源）
    var rp=r.replies;
    if(rp){
      h+='<h4 style="margin-top:12px">回帖证据（库存判定来源）</h4>';
      h+='<div class="kv" style="margin-bottom:6px">';
      h+='<span>回帖总数 <b>'+(rp.reply_count||0)+'</b></span>';
      h+='<span>商家回复 <b>'+(rp.vendor_reply_count||0)+'</b></span>';
      h+='<span>判定来源 <b>'+(rp.source==='vendor'?'商家表态':rp.source==='user'?'用户提及(弱证据)':'无')+'</b></span>';
      h+='</div>';
      var ev=rp.evidence;
      if(ev){
        h+='<div style="background:var(--chip);border-radius:8px;padding:8px 10px;font-size:12.5px;margin-bottom:8px">';
        h+='<div style="color:var(--muted);margin-bottom:3px">'+
           esc(ev.author||'?')+(ev.is_vendor?'（商家）':'（用户）')+
           (ev.datetime?(' · '+esc(String(ev.datetime).slice(0,10))):'')+'</div>';
        h+='<div>'+esc(ev.snippet||'')+'</div></div>';
      }
      if(rp.vendor_signals&&rp.vendor_signals.length){
        h+='<div style="font-size:12px;color:var(--muted);line-height:1.9">';
        rp.vendor_signals.forEach(function(s){
          h+='<div><span class="tag">'+esc(s.status)+'</span> '+
             esc(String(s.datetime||'').slice(0,10))+' — '+esc((s.snippet||'').slice(0,110))+'</div>';
        });
        h+='</div>';
      }
    }
    h+='<div style="margin-top:12px"><a href="'+esc(r.url)+
       '" target="_blank" rel="noopener">查看原帖 &rarr;</a></div>';
    return h+'</div>';
  }

  function render(){
    var rows=R.filter(passes).sort(cmp);
    var tb=document.getElementById('tb');
    var out='';
    rows.forEach(function(r){
      var open=!!st.open[r.thread_id];
      out+='<tr class="row'+(open?' open':'')+'" data-id="'+esc(r.thread_id)+'">';
      out+='<td><div class="pv">'+esc(r.provider)+'</div>'+
           '<div class="tt">'+esc(r.title)+'</div></td>';
      out+='<td><span class="badge b-'+esc(r.event_type)+'">'+
           esc(EVENT_CN[r.event_type]||r.event_type)+'</span></td>';
      out+='<td>'+(esc((r.discount||{}).strength)||'<span style="color:var(--muted)">—</span>')+'</td>';
      out+='<td class="spec">'+esc(specText(r))+'</td>';
      out+='<td class="price">'+esc(priceText(r))+'</td>';
      out+='<td><span class="av av-'+esc(r.availability)+'">'+
           esc(AVAIL_CN[r.availability]||r.availability)+'</span></td>';
      out+='<td><span class="bar"><i style="width:'+
           Math.round((r.confidence||0)*100)+'%"></i></span>'+
           Math.round((r.confidence||0)*100)+'%</td>';
      out+='<td class="hidesm">'+esc(ageText(r))+'</td>';
      out+='</tr>';
      if(open){
        out+='<tr class="det"><td colspan="8">'+detail(r)+'</td></tr>';
      }
    });
    tb.innerHTML=out;
    document.getElementById('empty').style.display=rows.length?'none':'block';
    document.getElementById('m-total').textContent=rows.length+' / '+R.length;
  }

  function buildChips(){
    var cnt={};
    R.forEach(function(r){ cnt[r.event_type]=(cnt[r.event_type]||0)+1; });
    var keys=Object.keys(cnt).sort(function(a,b){ return cnt[b]-cnt[a]; });
    var h='<div class="chip on" data-e="all">全部<span class="n">'+R.length+'</span></div>';
    keys.forEach(function(k){
      h+='<div class="chip" data-e="'+esc(k)+'">'+esc(EVENT_CN[k]||k)+
         '<span class="n">'+cnt[k]+'</span></div>';
    });
    var box=document.getElementById('chips');
    box.innerHTML=h;
    box.addEventListener('click',function(e){
      var c=e.target.closest('.chip'); if(!c) return;
      st.event=c.getAttribute('data-e');
      Array.prototype.forEach.call(box.querySelectorAll('.chip'),function(x){
        x.classList.toggle('on',x===c);
      });
      render();
    });
  }

  // 事件绑定
  document.getElementById('q').addEventListener('input',function(e){
    st.q=e.target.value.trim(); render();
  });
  document.getElementById('avail').addEventListener('change',function(e){
    st.avail=e.target.value; render();
  });
  document.getElementById('sort').addEventListener('change',function(e){
    st.sort=e.target.value; render();
  });
  document.getElementById('bigonly').addEventListener('change',function(e){
    st.big=e.target.checked; render();
  });
  document.getElementById('hideold').addEventListener('change',function(e){
    st.hideold=e.target.checked; render();
  });
  document.getElementById('tb').addEventListener('click',function(e){
    var tr=e.target.closest('tr.row'); if(!tr) return;
    var id=tr.getAttribute('data-id');
    st.open[id]=!st.open[id];
    render();
  });
  // 表头点击排序
  Array.prototype.forEach.call(document.querySelectorAll('th[data-s]'),function(th){
    th.addEventListener('click',function(){
      st.sort=th.getAttribute('data-s');
      document.getElementById('sort').value=st.sort;
      render();
    });
  });

  buildChips();
  render();
})();
</script>
</body>
</html>
"""


def build(deals_path: str, out_dir: str) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    with open(deals_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    records = data.get("records", [])
    for r in records:
        r["score"] = deal_score(r)
        r["annual_eur"] = annual_eur(r)

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(os.path.join(out_dir, "data"), exist_ok=True)

    # 供外部消费的 API 端点
    api_path = os.path.join(out_dir, "data", "deals.json")
    with open(api_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    html_out = (TEMPLATE
                .replace("@@DATA@@", json_for_script(data))
                .replace("@@COUNT@@", str(len(records)))
                .replace("@@GENERATED@@", generated)
                .replace("@@SOURCE@@", html.escape(data.get("source", ""), quote=True))
                .replace("@@EVENT_CN@@", json.dumps(EVENT_CN, ensure_ascii=False))
                .replace("@@AVAIL_CN@@", json.dumps(AVAIL_CN, ensure_ascii=False))
                .replace("@@FXNOTE@@", html.escape(FX_NOTE)))

    index_path = os.path.join(out_dir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    # 部署辅助文件
    with open(os.path.join(out_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write("User-agent: *\nAllow: /\n")
    with open(os.path.join(out_dir, ".nojekyll"), "w", encoding="utf-8") as f:
        f.write("")
    with open(os.path.join(out_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
                '  <url><loc>/</loc><lastmod>%s</lastmod></url>\n'
                '</urlset>\n' % datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    # 统计
    print("站点已生成 -> %s" % os.path.abspath(out_dir))
    print("  index.html      %8.1f KB" % (os.path.getsize(index_path) / 1024))
    print("  data/deals.json %8.1f KB" % (os.path.getsize(api_path) / 1024))
    print()
    print("记录数 %d" % len(records))
    ev = {}
    for r in records:
        ev[r["event_type"]] = ev.get(r["event_type"], 0) + 1
    print("活动分布: " + ", ".join(
        "%s=%d" % (EVENT_CN.get(k, k), v)
        for k, v in sorted(ev.items(), key=lambda kv: -kv[1])))
    scored = sorted(records, key=lambda r: -r["score"])[:5]
    print()
    print("力度 Top5:")
    for r in scored:
        print("  %3d  %-26s %-10s %s" % (
            r["score"], r["provider"][:26],
            EVENT_CN.get(r["event_type"], r["event_type"]),
            price_text(r)))
    print()
    print("本地预览: 直接双击 site/index.html（数据已内嵌，无需服务器）")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="LET Deals Radar 静态站生成器")
    ap.add_argument("--deals", default=os.path.join(HERE, "data", "deals.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "site"))
    args = ap.parse_args()
    if not os.path.exists(args.deals):
        print("找不到 %s，请先运行: python prototype.py" % args.deals)
        return 2
    return build(args.deals, args.out)


if __name__ == "__main__":
    sys.exit(main())
