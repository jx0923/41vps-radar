# GitHub Actions 上线清单（方案 A）

按顺序做，约 15 分钟。**每一步都有验证点**，失败时能立刻定位。

---

## 第 0 步：本地确认（已完成 ✅）

```bash
python -m pytest tests -q          # 应显示 235 passed
bash deploy/run_pipeline.sh        # 应生成 site/ 与 data/deals.json
```

---

## 第 1 步：建 GitHub 仓库并推送

在 GitHub 网页上**新建一个空仓库**（不要勾选 README/.gitignore，避免冲突）：

- 名称建议：`let-deals-radar`
- 可见性：**Public**（Actions 分钟数无限免费）或 Private
  （Private 每月 2000 分钟免费，本工作流每次约 5 分钟，够用）

然后本地推送：

```bash
cd <项目目录>
git remote add origin git@github.com:<你的用户名>/let-deals-radar.git
git push -u origin main
```

> 用 HTTPS 的话改成
> `git remote add origin https://github.com/<你>/let-deals-radar.git`

**验证点**：GitHub 页面上能看到 48 个文件和 2 条提交。

---

## 第 2 步：确认工作流被识别

推上去后，打开仓库的 **Actions** 标签页。

**验证点**：左侧应出现 **"Update deals"**。

若没出现，检查 `.github/workflows/update.yml` 是否真的推上去了：
仓库首页文件列表里应能看到 `.github` 目录。

---

## 第 3 步：手动触发一次（用 recent_days=7 快速验证）

Actions → 左侧 **Update deals** → 右侧 **Run workflow** 按钮：

| 输入项 | 填什么 | 原因 |
|---|---|---|
| `with_replies` | ✅ 勾选 | 验证回帖抓取链路 |
| `recent_days` | `7` | **先小范围验证，跑得快** |

点 **Run workflow**。

**验证点**：几十秒内出现一个新的运行记录，点进去能看到步骤逐个变绿：

```
✅ Checkout
✅ Setup Python
✅ Install test dependency
✅ Run tests              ← 235 passed
✅ Fetch, extract and build site
✅ Verify output is non-empty   ← 记录数: N
✅ Upload site artifact
✅ Commit refreshed data
⏭️ Deploy to own server   ← 灰的（未配服务器，正常跳过）
```

**预计耗时**：3–6 分钟（回帖抓取是主要耗时）。

---

## 第 4 步：检查结果

**① 看日志里的记录数**

点开 `Fetch, extract and build site` 步骤，末尾应有：

```
[5/5] 完成：N 条记录 (let=X, leb=Y)
```

> ⚠️ 若显示 `解析到 0 条` 或报 `HTTP 403`：
> 说明 Cloudflare 拦了 Actions 的 IP。这种情况很少见（Actions 出口 IP 池很大），
> 但若发生，可加 `--no-site` 重试，或改用代理。

**② 看是否自动提交**

回到仓库首页，应看到 `github-actions[bot]` 的新提交：

```
chore: refresh deals [skip ci]
```

**③ 下载站点产物**

该次运行的页面底部 **Artifacts** → 下载 `site-N.zip`，
解压后双击 `index.html` 即可预览（数据内嵌，无需服务器）。

**验证点**：页面能打开、有数据、能筛选和展开详情。

---

## 第 5 步：改成正式参数

验证通过后，把定时任务的窗口改大：

**方式一（推荐）**：改 `.github/workflows/update.yml` 里的默认值

```yaml
RECENT_DAYS: ${{ github.event.inputs.recent_days || '90' }}
```

`'90'` 已经就是 90 天，**默认无需修改** —— 手动触发时填 7 只影响那一次。

**方式二**：手动触发时 `recent_days` 留空或填 `90`，定时任务会自动用 `90`。

**验证点**：下次定时运行（每 6 小时，UTC 的 17 分）产出更多记录。

---

## 第 6 步（可选）：绑定自己的域名

### 6.1 设置站点变量

仓库 **Settings → Secrets and variables → Actions → Variables** 标签页，
点 **New repository variable**，逐个添加：

| 名称 | 示例值 |
|---|---|
| `LDR_SITE_TITLE` | `VPS 活动雷达` |
| `LDR_SITE_URL` | `https://deals.example.com` |
| `LDR_SITE_DESC` | `自动汇总 VPS 优惠活动` |
| `LDR_SITE_FOOTER` | `联系我：@yourname` |

> 设置 `LDR_SITE_URL` 后会生成 canonical 链接、绝对 sitemap URL，
> 并在 `robots.txt` 加 Sitemap 行。

### 6.2 设置部署目标

同页继续加（先在服务器上建好目录和 SSH 密钥）：

| 名称 | 示例值 |
|---|---|
| `LDR_DEPLOY_HOST` | `1.2.3.4` |
| `LDR_DEPLOY_USER` | `deploy` |
| `LDR_DEPLOY_PATH` | `/var/www/deals/` |
| `LDR_DEPLOY_PORT` | `22`（可省） |

**Secrets** 标签页加一个：

| 名称 | 内容 |
|---|---|
| `LDR_DEPLOY_SSH_KEY` | 部署私钥全文（含 `-----BEGIN...` 到 `...END-----`） |

**验证点**：下次运行后，`Deploy to own server` 步骤变绿并显示
`已推送到 deploy@1.2.3.4:/var/www/deals/`。

> 服务器端的 Nginx 配置与目录准备见 [DEPLOY.md](DEPLOY.md)。

---

## 常见问题

**Q：Actions 页面没有 "Update deals"？**
确认 `.github/workflows/update.yml` 已推送，且 `on:` 缩进正确
（YAML 对缩进敏感）。可在本地跑：
`python -c "import yaml;print(yaml.safe_load(open('.github/workflows/update.yml')))"`

**Q：`Run tests` 步骤失败？**
本地跑 `python -m pytest tests -q` 复现。注意测试用的是
`tests/fixtures/` 下的精简夹具，不依赖网络。

**Q：`Verify output is non-empty` 失败？**
说明当时抓到的记录数为 0。**这是保护机制在生效** ——
它拒绝把空数据提交上去，线上仍是上次的好数据。
可在 Actions 页面点 **Re-run** 重试。

**Q：`Commit refreshed data` 失败（push 被拒）？**
通常是同时有别的提交。工作流已设 `concurrency` 避免并发，
若仍发生，点 **Re-run** 即可。

**Q：想改运行频率？**
编辑 `.github/workflows/update.yml` 的 cron：
`'17 */6 * * *'` = 每 6 小时。改成 `'17 */2 * * *'` = 每 2 小时。
注意 GitHub 的 cron 只支持 UTC，且高负载时可能延后几分钟。

**Q：Private 仓库会超免费额度吗？**
本工作流每次约 5 分钟，每 6 小时一次 = 每天约 20 分钟，
每月约 600 分钟 < 2000 分钟免费额度。**Public 仓库则完全不计费**。
