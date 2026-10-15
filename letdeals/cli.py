"""命令行入口。

用法示例::

    python -m letdeals                       # 抓取全部数据源并生成站点
    python -m letdeals --with-replies        # 同时抓回帖（库存更准）
    python -m letdeals --sources let         # 只用 LowEndTalk
    python -m letdeals --no-site             # 只产 JSON/Markdown
    python -m letdeals --offline-let data/feed.xml
"""

from __future__ import annotations

import argparse
import os
import sys

from . import config
from . import pipeline
from . import render


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="letdeals",
        description="LowEndTalk / LowEndBox VPS 优惠聚合",
    )
    ap.add_argument("--sources", default="let,leb",
                    help="逗号分隔的数据源：let,leb（默认两者）")
    ap.add_argument("--offline-let", metavar="XML",
                    help="用本地 LET RSS 文件（离线重跑）")
    ap.add_argument("--offline-leb", metavar="XML",
                    help="用本地 LEB RSS 文件")
    ap.add_argument("--limit", type=int, default=0, help="只处理前 N 条")
    ap.add_argument("--recent-days", type=int, default=0,
                    help="只保留最近 N 天")
    ap.add_argument("--with-replies", action="store_true",
                    help="抓取回帖（库存准确率高得多，但更慢）")
    ap.add_argument("--reply-max-pages", type=int, default=2,
                    help="每帖最多抓几页（latest 策略下=末页起抓几页）")
    ap.add_argument("--reply-strategy", choices=["latest", "all"],
                    default="latest",
                    help="latest=末页优先(默认，快且新)；all=从头顺序")
    ap.add_argument("--reply-limit", type=int, default=0,
                    help="只对前 N 个 LET 帖子抓回帖（0=全部）")
    ap.add_argument("--no-dedupe", action="store_true", help="跳跨源去重")
    ap.add_argument("--no-site", action="store_true", help="不生成静态站")
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--md-out", default=None)
    ap.add_argument("--site-out", default=None)
    ap.add_argument("-q", "--quiet", action="store_true")
    return ap


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    args = build_parser().parse_args(argv)
    verbose = not args.quiet

    sources = tuple(s.strip() for s in args.sources.split(",") if s.strip())
    offline = {}
    if args.offline_let:
        offline["let"] = args.offline_let
    if args.offline_leb:
        offline["leb"] = args.offline_leb

    payload = pipeline.run(
        sources=sources,
        offline=offline,
        limit=args.limit,
        recent_days=args.recent_days,
        with_replies=args.with_replies,
        reply_max_pages=args.reply_max_pages,
        reply_strategy=args.reply_strategy,
        reply_limit=args.reply_limit,
        dedupe=not args.no_dedupe,
        verbose=verbose,
    )

    if not payload.get("records"):
        print("!! 没有抓到任何记录；为避免发布空数据，已中止。")
        print("   提示：可用 --offline-let data/feed_let.xml 复用缓存重跑。")
        return 1

    # 输出：JSON + Markdown
    json_out = args.json_out or str(config.DEALS_JSON)
    md_out = args.md_out or str(config.DEALS_MD)
    pipeline.save(payload, json_out, md_out)

    if verbose:
        print()
        print("=" * 72)
        print("字段覆盖率")
        print("=" * 72)
        recs = payload["records"]
        n = len(recs) or 1

        def pct(pred):
            return f"{sum(1 for r in recs if pred(r)) / n * 100:.0f}%"

        print(f"  vCPU          {pct(lambda r: (r.get('specs') or {}).get('vcpu'))}")
        print(f"  RAM           {pct(lambda r: (r.get('specs') or {}).get('ram_gb'))}")
        print(f"  存储          {pct(lambda r: (r.get('specs') or {}).get('storage_gb'))}")
        print(f"  带宽          {pct(lambda r: (r.get('specs') or {}).get('bandwidth_tb'))}")
        print(f"  CPU 型号      {pct(lambda r: r.get('cpu_models'))}")
        print(f"  价格          {pct(lambda r: r.get('prices'))}")
        print(f"  折扣/优惠码    {pct(lambda r: (r.get('discount') or {}).get('strength'))}")
        print(f"  地点          {pct(lambda r: r.get('locations'))}")
        print(f"  套餐表({sum(1 for r in recs if r.get('plans'))}条)")
        if args.with_replies:
            print(f"  回帖已抓取     {pct(lambda r: r.get('replies'))}")
            print(f"  商家库存表态   "
                  f"{pct(lambda r: (r.get('replies') or {}).get('source') == 'vendor')}")
        print(f"  库存已判定     "
              f"{pct(lambda r: r.get('availability') not in ('UNVERIFIED', 'UNVERIFIED_STALE'))}")
        print()
        dist: dict[str, int] = {}
        for r in recs:
            dist[r.get("availability")] = dist.get(r.get("availability"), 0) + 1
        print("库存状态分布: " + ", ".join(
            f"{k}={v}" for k, v in sorted(dist.items(), key=lambda kv: -kv[1])))

    if not args.no_site:
        if verbose:
            print()
        render.build_site(payload, args.site_out, verbose=verbose)

    if verbose:
        print()
        print(f"JSON: {json_out}")
        print(f"MD  : {md_out}")
        if not args.no_site:
            print(f"SITE: {args.site_out or config.SITE_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
