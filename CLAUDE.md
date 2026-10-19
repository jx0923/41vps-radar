# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

`letdeals`：抓取 LowEndTalk Offers（LET）与 LowEndBox（LEB）的 RSS，抽取 VPS 规格 / 价格 / 折扣 / 库存状态，生成纯静态站点（`site/`，数据内嵌）。

- **运行时零第三方依赖**：只用 Python 标准库，最低 Python 3.10（用了 `X | None` 语法）。不要给 `letdeals/` 引入第三方包。
- 开发依赖（`requirements-dev.txt`）：`pytest`；`Pillow` 仅 `tools/render_preview.py`、`tools/make_icons.py` 需要。
- 文档、注释、日志均为中文，新代码保持一致。

## 常用命令

```bash
python -m pytest tests -q                                  # 全量测试（约 80 秒）
python -m pytest tests/test_replies.py -q                  # 单个文件
python -m pytest tests/test_extract.py::test_name -q       # 单个用例
python -m pytest tests -q -k "partial"                     # 按名称筛选

python -m letdeals                                         # 联网抓取两源 + 建站
python -m letdeals --with-replies                          # 同时抓 LET 回帖（库存更准，慢）
python -m letdeals --offline-let data/feed_let.xml         # 用上次抓取缓存离线重跑
python -m letdeals --forum-only --forum-dry-run            # 读现有 deals.json，只演练论坛发帖

python tools/regress.py        # 与 legacy/ 原型逐字段回归比对（流程见 legacy/README.md）
python tools/make_fixtures.py  # 从实时缓存重新生成 tests/fixtures/ 精简夹具
```

CI（`.github/workflows/update.yml`）先跑 `pytest`，再通过 `deploy/run_pipeline.sh` 调用管线；本地验证该脚本：`WITH_REPLIES=0 RECENT_DAYS=7 ./deploy/run_pipeline.sh`。

## 架构

数据流（`pipeline.run` 的 5 个阶段）：

```
sources.fetch_source  →  replies.fetch_thread_replies (仅 LET)  →  extract.build_record
   → 时间过滤 → pipeline.dedupe_records  →  pipeline.save + render.build_site  → (可选) forum.post_deals
```

- **数据形态**：源解析器产出 RSS item dict（`thread_id/title/link/description/author/pubDate/source`），`extract.build_record` 把它变成最终 record dict。record 的字段就是 `data/deals.json`、`site/` 前端、`forum.py` 共同依赖的契约 —— 改字段名要同时改 `render.py`（含内嵌 JS 模板）和 `forum.py`。
- **数据源注册**：`sources.SOURCES` 字典（url / parser / cache 文件名 / label）。新增数据源 = 写一个 `parse_xxx_feed` 并注册，不需改 pipeline。单个源失败只打印警告，不中断整体。
- **库存判定优先级**（`extract.availability`）：商家回帖表态 > 帖文关键词 > 用户回帖（只给弱证据 `LIKELY_SOLD_OUT`）> 帖子年龄。商家身份靠 LET 回帖 `<li>` 的 CSS class（`isOriginalPoster` / `Role_PatronProvider`）识别。
- **回帖层**（`replies.py`）：默认 `latest` 策略从末页往前抓（商家表态多在回帖流 75%–100% 处）。`is_valid_statement` 过滤疑问句、否定句、非库存对象、促销资格四类误判。**`STOCK_PATTERNS` 顺序有语义**：`RESTOCKING`（"working on a restock" = 当前缺货）必须排在 `ON_SALE` 之前。回帖缓存在 `data/replies/<thread_id>.json`，TTL 1 小时。
- **表格重建**（`textutil.parse_flat_tables`）：`strip_html` 会把套餐表拍平成一行一个单元格，这里按值类型重建套餐；表格解析成功时用旗舰套餐覆盖 `specs`。
- **厂商链接**必须从**原始 HTML** 抽取（`strip_html` 会丢掉 href），随后经 `affiliate.rewrite` 按 `LDR_AFFILIATES` 改写成推广链接；未配置则不改变行为。
- **跨源去重**：指纹 = 厂商 + 价格 + 旗舰配置；**数据不足时 `dedupe_key` 返回 `None`、不参与合并**（防止空指纹把无关新闻判成重复）。重复时按 `_richness` 保留信息更全的一条，LET 优先。
- **LEB 过滤**：按 `<category>` 硬排除 / 软排除，软排除类别里正文规格描述 ≥2 处仍保留。
- **论坛搬运**（`forum.py`，旁路功能）：默认关闭（`LDR_FORUM_ENABLED`）且默认演练（`LDR_FORUM_DRY_RUN`），以 `data/forum_posted.json` 做幂等，按条数和天数限流；发帖异常不得影响主流程建站。
- **配置**：全部在 `config.py`，以 `LDR_*` 环境变量覆盖（清单见 `deploy/env.example`）。值在 import 时读成模块常量，因此测试用 `monkeypatch.setattr(config, ...)` 改，而不是改环境变量。

## 注意事项

- **生成产物已入库**：`data/deals.json`、`data/deals.md`、`site/`（以及 `data/forum_posted.json`）由 CI 机器人每 6 小时以 `chore: refresh deals [skip ci]` 提交。不要手改这些文件；本地跑 `python -m letdeals` 会联网并覆盖它们，只想验证逻辑时用 `--json-out/--md-out/--site-out` 指向临时目录。`data/feed_*.xml` 与 `data/replies/` 是 gitignore 的抓取缓存。
- **安全网**：CLI 在记录数为 0 时返回 1 且不写文件；CI 与 `deploy/server-update.sh` 也会拒绝发布空数据。改动管线时保持这一保护。
- **测试夹具**：`tests/fixtures/*.xml` 是精简的稳定样本。黄金样本是 BERO 十周年帖（`#221713`），表格重建必须还原其套餐（Anniversary XXL = `8C/32G/300G/25TB/€129`，期望值在 `tests/conftest.py`）。
- **`legacy/` 只读**：仅供 `tools/regress.py` 回归比对，不参与运行和测试；修 bug 改 `letdeals/`。
- `.gitattributes` 强制 LF（尤其 `*.sh`，CRLF 会让 CI 报 bad interpreter）。
- 部署方案（Actions 抓取 + rsync 到自有服务器 / Cloudflare Pages Direct Upload，或服务器 cron）见 `deploy/DEPLOY.md`；推荐 Actions 是因为 Cloudflare 易拦截固定云 IP。新增 `LDR_*` 配置项若要在 CI 生效，必须同时加到 `update.yml` 抓取步骤的 `env`。
