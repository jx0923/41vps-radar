# legacy/ — 重构前的独立脚本（归档）

这些脚本是 `letdeals/` 包重构**之前**的原型。它们**不参与运行时**，
也不被任何测试或工作流引用。

## 为什么留着

只有一个用途：**回归比对**。重构时用它们证明"重构没有改变抽取行为"。

```bash
# 1) 用旧脚本生成基线
python legacy/prototype.py --offline data/feed_let.xml \
    --json-out data/old_deals.json --md-out data/old_deals.md

# 2) 用新包生成结果
python -m letdeals --sources let --offline-let data/feed_let.xml \
    --no-site --json-out data/new_deals.json --md-out data/new_deals.md

# 3) 逐字段比对（19 个共有字段）
python tools/regress.py
```

比对结果记录在 [README](../README.md) 的「重构说明」一节：
**19 个共有字段、100 条记录零回归差异**。

## 文件对照

| legacy/ | 现由谁承担 |
|---|---|
| `prototype.py` | `letdeals/extract.py` + `pipeline.py` + `cli.py` |
| `fetch_replies.py` | `letdeals/replies.py` |
| `build_site.py` | `letdeals/render.py` |
| `verify_site.py` | `tests/test_render.py` |
| `audit.py` / `audit_replies.py` | `tools/regress.py` + 测试 |
| `analyze_reply_value.py` | `tools/analyze_leb.py` |

## 注意

- 这些脚本只依赖 Python 标准库，仍可独立运行
- 它们读取的是**实时抓取缓存** `data/feed_*.xml`（已 gitignore），
  需先跑一次 `python -m letdeals` 生成
- 行为已被 `tests/` 中 124 个用例更精确地锁定；
  `legacy/` 仅作历史参照，**修 bug 请改 `letdeals/`，不要改这里**
