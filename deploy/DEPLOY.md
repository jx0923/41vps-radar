# 部署指南

两种方案，可单独使用，也可组合。

| 方案 | 抓取方 | 网站托管 | 适合 |
|---|---|---|---|
| **A. GitHub Actions + 自有服务器**（推荐） | Actions（云 IP，不被封） | 你的服务器 + 你的域名 | 想要自有域名，又不想被 Cloudflare 拦 |
| **B. 纯服务器自建** | 你的服务器（固定 IP） | 你的服务器 | 想完全自控，且服务器 IP 能正常抓取 |

> **为什么推荐 A**：论坛前面板有 Cloudflare。云主机固定 IP 被拦的概率高于家庭宽带。
> Actions 每次运行都是不同的云 IP，天然规避这个问题；而站点照样能发到你的域名。

---

## 方案 A：GitHub Actions 抓取 + 推送到自有服务器

### 1. 推到 GitHub

```bash
git init
git add .
git commit -m "init"
git remote add origin git@github.com:<你>/let-deals-radar.git
git push -u origin main
```

### 2. 配置站点变量

仓库 **Settings → Secrets and variables → Actions → Variables**：

| 名称 | 示例 | 说明 |
|---|---|---|
| `LDR_SITE_TITLE` | `VPS 活动雷达` | 站点标题 |
| `LDR_SITE_URL` | `https://deals.example.com` | 你的域名（末尾不带 `/`） |
| `LDR_SITE_DESC` | `自动汇总 VPS 优惠…` | 描述 |
| `LDR_SITE_FOOTER` | `联系我：@xxx` | 页脚附加 |

设置 `LDR_SITE_URL` 后，会自动生成 canonical 链接、绝对 sitemap URL，
并在 `robots.txt` 里加上 Sitemap 行。

### 3. 配置部署目标

同页 **Variables** 再加：

| 名称 | 示例 |
|---|---|
| `LDR_DEPLOY_HOST` | `1.2.3.4` |
| `LDR_DEPLOY_USER` | `deploy` |
| `LDR_DEPLOY_PATH` | `/var/www/deals/` |
| `LDR_DEPLOY_PORT` | `22`（默认，可省） |

**Secrets** 加一个：

| 名称 | 内容 |
|---|---|
| `LDR_DEPLOY_SSH_KEY` | 部署用的**私钥**（对应公钥要放进服务器 `~/.ssh/authorized_keys`） |

配置好后，workflow 每次运行都会在最后自动 `rsync` 到你的服务器。
未配置 `LDR_DEPLOY_HOST` 时该步骤自动跳过。

### 4. 服务器端准备

```bash
# 建目录
sudo mkdir -p /var/www/deals
sudo chown deploy:deploy /var/www/deals
```

Nginx 配置：

```nginx
server {
    listen 80;
    server_name deals.example.com;
    root /var/www/deals;
    index index.html;

    # 数据每 6 小时更新，缓存别设太长
    location = /data/deals.json {
        add_header Cache-Control "public, max-age=1800";
    }
    location / {
        add_header Cache-Control "public, max-age=600";
        try_files $uri $uri/ /index.html;
    }
}
```

HTTPS 用 certbot 一句话搞定：

```bash
sudo certbot --nginx -d deals.example.com
```

### 5. 手动触发一次验证

Actions 页面 → **Update deals** → **Run workflow**。
建议第一次把 `recent_days` 设小（如 7）先验证链路，再改成 90。

---

## 方案 B：纯服务器自建（cron）

### ⚠️ 先做这一步

**在正式配置前，先手动跑一次，确认你的服务器 IP 能抓到数据：**

```bash
cd /opt/let-deals-radar
python3 -m letdeals --limit 20 --no-site
```

- 若输出 `解析到 XX 条` 且记录数 > 0 → IP 可用，继续
- 若报 `HTTP 403` 或记录数为 0 → **被 Cloudflare 拦了**，请改用方案 A

### 安装

```bash
sudo mkdir -p /opt/let-deals-radar
sudo chown $USER /opt/let-deals-radar
git clone <你的仓库> /opt/let-deals-radar
cd /opt/let-deals-radar

# 配置（可选：站点标题/域名）
cp deploy/env.example .env
vim .env
```

### 试跑

```bash
chmod +x deploy/server-update.sh
./deploy/server-update.sh
```

脚本会：拉代码 → 跑管线 → **校验记录数非 0** → 原子替换到 `/var/www/deals`。
上一版会保留在 `/var/www/deals.prev`，便于回滚。

### 定时

```bash
sudo crontab -e
```

加一行：

```cron
0 */6 * * * cd /opt/let-deals-radar && ./deploy/server-update.sh >> /var/log/letdeals.log 2>&1
```

日志：`tail -f /var/log/letdeals.log`

---

## 回滚

方案 A（Actions）：`git revert` 对应提交，或直接重跑上一次成功的 workflow。

方案 B（服务器）：

```bash
sudo rm -rf /var/www/deals && sudo mv /var/www/deals.prev /var/www/deals
```

---

## 常见问题

**Q：站点打开是空白的？**
数据内嵌在 `index.html` 里，若页面结构正常但无数据，检查 `data/deals.json` 的 `count`。
若为 0，说明抓取失败但产物仍被发布 —— 两个方案都已有"记录数为 0 则拒绝发布"的保护。

**Q：想改站点外观？**
编辑 `letdeals/render.py` 里的 `SITE_TEMPLATE`（单文件 HTML + 内联 CSS/JS，无构建步骤）。

**Q：部署后样式或筛选不生效？**
清浏览器缓存，或确认 `LDR_SITE_URL` 与访问地址一致（影响 canonical，不影响功能）。

**Q：抓取很慢？**
回帖抓取是主要耗时（100 帖约 3–4 分钟）。可调小 `--reply-limit`，
或去掉 `--with-replies`（代价是库存判定率下降）。
