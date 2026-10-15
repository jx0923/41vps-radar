#!/usr/bin/env bash
#
# 在自有服务器上更新站点（服务端方案）
# ====================================
# 适用场景：希望完全自控，不用 GitHub Actions。
#
# 流程：拉取代码 → 跑管线 → 原子替换站点目录
#
# 用法：
#   ./deploy/server-update.sh
#
# 建议用 cron 每 6 小时跑一次：
#   0 */6 * * * /opt/let-deals-radar/deploy/server-update.sh >> /var/log/letdeals.log 2>&1
#
# ⚠️ 注意：本方案使用服务器的**固定 IP** 抓取。
#    Cloudflare 可能拦截云主机 IP —— 部署前务必先手动跑一次确认能抓到数据。
#    若被拦截，请改用 GitHub Actions 抓取 + rsync 推送（见 update.yml）。

set -euo pipefail

# ---------------------------------------------------------------------------
# 配置（可用环境变量覆盖）
# ---------------------------------------------------------------------------

REPO_DIR="${LDR_REPO_DIR:-/opt/let-deals-radar}"
WEBROOT="${LDR_WEBROOT:-/var/www/deals}"
PYTHON="${LDR_PYTHON:-python3}"
# 抓取参数
WITH_REPLIES="${LDR_WITH_REPLIES:-1}"
RECENT_DAYS="${LDR_RECENT_DAYS:-90}"

cd "$REPO_DIR"

log() { echo "[$(date '+%F %T')] $*"; }

log "=== 开始更新 ==="

# ---------------------------------------------------------------------------
# 1) 拉取最新代码（若为 git 仓库）
# ---------------------------------------------------------------------------
if [ -d .git ]; then
  log "拉取代码 ..."
  git pull --ff-only || log "警告：git pull 失败，继续使用当前代码"
fi

# ---------------------------------------------------------------------------
# 2) 运行管线
# ---------------------------------------------------------------------------
ARGS=""
if [ "$WITH_REPLIES" = "1" ]; then
  ARGS="$ARGS --with-replies --reply-max-pages 1 --reply-strategy latest"
fi
if [ "$RECENT_DAYS" != "0" ]; then
  ARGS="$ARGS --recent-days $RECENT_DAYS"
fi

log "运行管线: $PYTHON -m letdeals $ARGS"
# shellcheck disable=SC2086
if ! $PYTHON -m letdeals $ARGS; then
  log "!! 管线失败；保留现有站点，不做替换"
  exit 1
fi

# ---------------------------------------------------------------------------
# 3) 校验产物（防止把空数据发布上线）
# ---------------------------------------------------------------------------
COUNT=$($PYTHON -c "import json;print(json.load(open('data/deals.json'))['count'])")
log "记录数: $COUNT"
if [ "$COUNT" -lt 1 ]; then
  log "!! 记录数为 0，拒绝发布（保留上次数据）"
  exit 1
fi

if [ ! -f site/index.html ]; then
  log "!! 缺少 site/index.html，拒绝发布"
  exit 1
fi

# ---------------------------------------------------------------------------
# 4) 原子替换到 webroot
#    先写入临时目录再整体替换，避免访问者看到写一半的站点。
# ---------------------------------------------------------------------------
TMP="${WEBROOT}.new.$$"
log "同步到 $WEBROOT ..."
mkdir -p "$WEBROOT"
rm -rf "$TMP"
cp -a site "$TMP"

# 备份上一版（保留 1 份），便于回滚
if [ -d "$WEBROOT" ] && [ "$(ls -A "$WEBROOT" 2>/dev/null || true)" ]; then
  rm -rf "${WEBROOT}.prev"
  mv "$WEBROOT" "${WEBROOT}.prev"
fi
mv "$TMP" "$WEBROOT"

# 权限：交由 web 服务器读取（按需调整用户/组）
if id -u www-data >/dev/null 2>&1; then
  chown -R www-data:www-data "$WEBROOT" 2>/dev/null || true
fi
chmod -R a+rX "$WEBROOT"

log "=== 更新完成：$COUNT 条记录 ==="
log "回滚方式：rm -rf $WEBROOT && mv ${WEBROOT}.prev $WEBROOT"
