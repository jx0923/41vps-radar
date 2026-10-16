# 生产部署记录（vps.lowseek.ai）

本文档记录**实际在线运行**的部署方式。与 `DEPLOY.md` 里的通用方案不同，
这里是这台机器的**具体实现**，用于故障恢复与后续维护。

---

## 架构

```
GitHub Actions（云 IP，避开 Cloudflare 拦截）
    │  每 6 小时：抓取 → 抽取 → 生成静态站
    │  再提交回仓库 git
    ↓  rsync over SSH（端口 28475）
宿主机 /opt/vps-deals/site/          ← 纯静态文件，可被 Actions 直接更新
    ↓  只读 bind mount
容器 vps-deals-web (nginx:alpine)    ← 监听 127.0.0.1:18310，无状态
    ↓  1Panel 反向代理
https://vps.lowseek.ai               ← Cloudflare 代理 + Let's Encrypt 证书
```

**分层理由**：静态文件放宿主机，Actions 直接 rsync 更新，**无需重建镜像**；
容器无状态只读挂载，随时可删可重建。

---

## 关键参数

| 项目 | 值 |
|---|---|
| 服务器 | `15.204.92.196`（scrapify-vps） |
| SSH 端口 | `28475`（非标准） |
| 部署用户 | `debian` |
| 静态目录 | `/opt/vps-deals/site/` |
| 容器名 | `vps-deals-web` |
| 容器端口 | `127.0.0.1:18310` → 容器内 `80` |
| 镜像 | `nginx:alpine` |
| 配置文件 | `/opt/vps-deals/conf/default.conf` |
| 1Panel 站点 | `vps.lowseek.ai`（反向代理类型） |
| 域名 | `https://vps.lowseek.ai`（Cloudflare 代理） |

---

## 容器重建（若容器丢失）

```bash
sudo docker run -d \
  --name vps-deals-web \
  --restart unless-stopped \
  -p 127.0.0.1:18310:80 \
  -v /opt/vps-deals/site:/usr/share/nginx/html:ro \
  -v /opt/vps-deals/conf/default.conf:/etc/nginx/conf.d/default.conf:ro \
  --memory 64m \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  nginx:alpine
```

**要点**：
- `127.0.0.1:` 前缀 → 只绑本地，**不暴露公网**（与这台机器其他 31 个容器一致）
- `:ro` 只读挂载 → 容器无法改动静态文件
- `--memory 64m` → 限制资源，避免影响其他生产容器

---

## 容器内 nginx 配置

`/opt/vps-deals/conf/default.conf`：

```nginx
server {
    listen 80;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    gzip on;
    gzip_types text/plain text/css application/json application/javascript
               text/xml application/xml image/svg+xml;
    gzip_min_length 1024;

    # 数据文件：短缓存，保证更新及时可见
    location /data/ {
        add_header Cache-Control "public, max-age=1800";
        try_files $uri =404;
    }

    # HTML：短暂缓存
    location = /index.html {
        add_header Cache-Control "public, max-age=600";
    }

    location / {
        try_files $uri $uri/ /index.html;
    }

    location ~ /\. { deny all; }
}
```

---

## GitHub 配置

**Variables**（Settings → Secrets and variables → Actions → Variables）：

| 名称 | 值 |
|---|---|
| `LDR_SITE_TITLE` | `LowSeek 优惠雷达` |
| `LDR_SITE_URL` | `https://vps.lowseek.ai` |
| `LDR_SITE_DESC` | `自动汇总 LowEndTalk / LowEndBox 的 VPS 优惠活动，标注折扣力度与库存状态。` |
| `LDR_SITE_FOOTER` | `LowSeek 低价资源源头社区` |
| `LDR_DEPLOY_HOST` | `15.204.92.196` |
| `LDR_DEPLOY_USER` | `debian` |
| `LDR_DEPLOY_PATH` | `/opt/vps-deals/site/` |
| `LDR_DEPLOY_PORT` | `28475` |

**Secrets**：

| 名称 | 内容 |
|---|---|
| `LDR_DEPLOY_SSH_KEY` | 专用部署私钥（ed25519，无口令） |

**部署专用密钥**（与个人密钥分离，可单独吊销）：

- 公钥注释：`github-actions-vps-deals`
- 已追加到服务器 `/home/debian/.ssh/authorized_keys`
- 原个人密钥注释 `scrapify-vps` **保持不动**

---

## 1Panel 侧配置（面板操作，勿手改文件）

1. **网站 → 创建网站** → 类型选 **反向代理**
   - 主域名：`vps.lowseek.ai`
   - 代理地址：`http://127.0.0.1:18310`
2. 站点配置 → **HTTPS** → 申请 Let's Encrypt 证书
3. Cloudflare：`vps` A 记录 → `15.204.92.196`，代理状态**开启**
4. **Cloudflare SSL/TLS 模式必须为 `Full (strict)`**，否则无限重定向

---

## 维护命令

```bash
# 查看容器状态
sudo docker ps --filter name=vps-deals-web

# 查看访问日志（含真实访客 IP，Cloudflare 会带 X-Forwarded-For）
sudo docker logs --tail 50 vps-deals-web

# 查看 1Panel 反代日志
sudo tail -f /opt/1panel/www/sites/vps.lowseek.ai/log/access.log

# 重载容器配置（改 default.conf 后）
sudo docker restart vps-deals-web

# 验证链路（三层）
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:18310/          # 容器
curl -sk --resolve vps.lowseek.ai:443:127.0.0.1 https://vps.lowseek.ai/ -o /dev/null -w '%{http_code}\n'  # 反代
curl -s -o /dev/null -w '%{http_code}\n' https://vps.lowseek.ai/          # 外部
```

> ⚠️ 测试 HTTPS 反代**必须用 `--resolve`**，不能写成 `curl https://127.0.0.1/ -H 'Host: ...'`。
> 后者 SNI 会发成 `127.0.0.1`，导致握手失败（表现为 HTTP 000）。

---

## 已踩过的坑

### 1. 服务器缺少 rsync

Debian 最小安装**不带 rsync**，rsync 部署会报：

```
bash: line 1: rsync: command not found
rsync error: error in rsync protocol data stream (code 12)
```

修复：`sudo apt-get install -y rsync`

### 2. 推送被拒（非快进）

重跑工作流或 cron 延迟时，远端 `main` 可能已被上一次运行推进，导致：

```
! [rejected] main -> main (fetch first)
```

已在 workflow 中修复：提交前先 `git fetch` + `git reset --soft origin/main`，
再在其上重新提交（产物始终以最新一次为准），保证快进推送。

### 3. Windows 上传中文文件被损坏

PowerShell **5.1** 的 `Get-Content` 默认按 **ANSI/GBK** 读取，
会把 UTF-8 中文转成乱码（`优惠雷达` → `浼樻儬闆疯揪`），且可能吃掉相邻字符。

**规避方式**（任选）：
- 用 `scp` 直接传文件（字节安全，推荐）
- `Get-Content -Encoding UTF8`
- 用 `[IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)`

> Actions 的 rsync 走 Linux→Linux，不存在此问题。

### 4. SSH 私钥在 Windows 上权限过宽

Windows 生成的私钥 ACL 默认过宽，OpenSSH 拒绝使用：

```
WARNING: UNPROTECTED PRIVATE KEY FILE!
```

修复：

```powershell
icacls $key /inheritance:r
icacls $key /grant:r "$($env:USERNAME):R"
```

---

## 与既有服务的关系

- **不影响**其他 31 个容器、1Panel 数据库、iptables、系统服务
- 反代需在共享 OpenResty 中新增一个 server 块并**优雅 reload**
  （1Panel 会先 `nginx -t` 校验，失败则拒绝重载，现有站点不受影响）
- 容器只绑 `127.0.0.1`，不开放公网端口
