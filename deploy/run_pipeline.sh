#!/usr/bin/env bash
#
# 构建参数并运行管线
# ==================
# 由 GitHub Actions 与服务器 cron 共用。
# 抽出成独立脚本而非写在 workflow 的 run 块里，原因是：
#   1) 可以在本地直接测试（workflow 里的 shell 无法本地验证）
#   2) 避免把 ${{ }} 表达式直接插值进 shell（易错且有注入风险）
#
# 输入（环境变量）：
#   WITH_REPLIES  1/true=抓回帖，其他=不抓（默认 1）
#   RECENT_DAYS   只保留最近 N 天，0=全部（默认 90）
#   REPLY_MAX_PAGES     每帖抓几页（默认 1）
#   REPLY_STRATEGY      latest/all（默认 latest）
#   REPLY_LIMIT         只对前 N 帖抓回帖，0=全部（默认 0）
#   PYTHON              python 可执行文件（默认 python3）
#
# 用法：
#   WITH_REPLIES=1 RECENT_DAYS=7 ./deploy/run_pipeline.sh

set -euo pipefail

PYTHON="${PYTHON:-python3}"
WITH_REPLIES="${WITH_REPLIES:-1}"
RECENT_DAYS="${RECENT_DAYS:-90}"
REPLY_MAX_PAGES="${REPLY_MAX_PAGES:-1}"
REPLY_STRATEGY="${REPLY_STRATEGY:-latest}"
REPLY_LIMIT="${REPLY_LIMIT:-0}"

# 规范化布尔值：接受 1/true/yes/on
_is_true() {
  case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

ARGS=""

if _is_true "$WITH_REPLIES"; then
  ARGS="$ARGS --with-replies"
  ARGS="$ARGS --reply-max-pages $REPLY_MAX_PAGES"
  ARGS="$ARGS --reply-strategy $REPLY_STRATEGY"
  if [ "$REPLY_LIMIT" != "0" ]; then
    ARGS="$ARGS --reply-limit $REPLY_LIMIT"
  fi
fi

if [ "$RECENT_DAYS" != "0" ]; then
  ARGS="$ARGS --recent-days $RECENT_DAYS"
fi

echo "运行: $PYTHON -m letdeals $ARGS"
# shellcheck disable=SC2086  # 需要分词以传递多个参数
exec $PYTHON -m letdeals $ARGS
