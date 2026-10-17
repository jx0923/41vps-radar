# 联盟推广（AFF）配置指南

把厂商链接换成**你自己的推广链接**，用户下单你拿佣金。

> **默认不启用。** 不配置就完全不影响现有行为。

---

## 现状：现在没有 AFF 链接

我扫过全部 105 条原帖，命中的「带参数链接」分三类，**都不是能拿佣金的**：

| 类型 | 例子 | 能拿佣金吗 |
|---|---|---|
| UTM 追踪 | `?utm_source=lowendtalk` | ❌ 只是流量统计 |
| 优惠码 | `?promo=LOWENDTALK`、`?coupon=LETB25` | ❌ 是折扣码 |
| 厂商联盟招募页 | `cloudcone.com/affiliate/` | ❌ 那是招募会员的页面 |

**原因**：这些是商家自己发的促销帖，链接指向自家官网，没必要用返佣链接。

**要拿佣金，得你自己去申请。**

---

## 怎么开

### 1. 申请联盟账号

去厂商后台找 **Affiliate / Referral / 推广** 页面注册。常见门槛：

- 多数**注册即可**（RackNerd、CloudCone 等）
- 部分需**人工审核**（要填网站地址、推广渠道）
- 多数需累计 **$50–$100** 才能提现
- Cookie 有效期通常 **30–90 天**

> ⚠️ **申请前务必读条款**。多数厂商明确禁止：
> - 自己下单赚自己佣金（会被封号）
> - 脚本批量注册
> - 投竞品品牌词广告
>
> **优惠聚合站属于部分商家限制的推广场景**，先确认再投精力。

### 2. 拿到专属链接

形如 `https://my.racknerd.com/aff.php?aff=123`。

**注意**：每家参数格式不同（`?aff=` / `/?ref=` / `/go/xxx`）。
所以本模块**要求给完整链接**，不做参数拼接猜测 —— 拼错会丢佣金且很难发现。

### 3. 填入配置

**方式一：环境变量**（推荐，不改代码）

```bash
LDR_AFFILIATES='{"racknerd.com":"https://my.racknerd.com/aff.php?aff=123"}'
```

GitHub Actions 里配成 Variable `LDR_AFFILIATES`。

**方式二：改代码**

编辑 `letdeals/affiliate.py` 的 `DEFAULTS`：

```python
DEFAULTS = {
    "racknerd.com": "https://my.racknerd.com/aff.php?aff=123",
    "cloudcone.com": "https://cloudcone.com/?aff=456",
}
```

### 4. 验证

```bash
python -c "from letdeals import affiliate; print(affiliate.summary())"
# 已配置 2 家厂商的推广链接：cloudcone.com、racknerd.com
```

---

## 匹配规则

按**厂商域名**匹配，与帖子内容无关：

| 记录里的链接 | 命中规则 | 结果 |
|---|---|---|
| `https://racknerd.com/deals` | `racknerd.com` | ✅ 替换 |
| `https://www.racknerd.com/BlackFriday/` | `racknerd.com` | ✅ 替换（忽略 www） |
| `https://my.racknerd.com/store/vps` | `racknerd.com` | ✅ 替换（子域归并） |
| `https://other.com/deals` | — | 原样保留 |

**子域优先级**：同时配了 `a.com` 和 `my.a.com` 时，`my.a.com` 优先。

---

## 示例

```bash
export LDR_AFFILIATES='{
  "racknerd.com": "https://my.racknerd.com/aff.php?aff=123",
  "cloudcone.com": "https://cloudcone.com/?aff=456",
  "greencloudvps.com": "https://greencloudvps.com/billing/aff.php?aff=789"
}'

python -m letdeals --offline-let data/feed_let.xml
```

打开站点，点厂商名 → 会走你的推广链接。

---

## 建议：明示推广关系

行业里两种做法：

| 做法 | 效果 |
|---|---|
| **明示**「部分链接含推广佣金」 | ✅ 坦诚，用户普遍能接受 |
| 不说明 | ⚠️ 被发现后信任受损 |

**佣金由商家从利润中出，不影响用户支付的价格** —— 这点可以明说。

如果要做，改 `letdeals/render.py` 的页脚加一行即可。

---

## 容错

| 情况 | 行为 |
|---|---|
| 未配置 | 用原始链接（**现有行为不变**） |
| JSON 写错 | 静默回退到空表，**不影响抓取** |
| 值不是 http 开头 | 该条被忽略 |
| 厂商没配 | 用原始链接 |

**最坏情况只是没有推广链接**，不会导致抓取或建站失败。

---

## 灰度建议

1. **先申请 2–3 家**（RackNerd、CloudCone 门槛最低）
2. 填进配置，观察是否正常跳转
3. 确认有佣金入账，再扩到更多厂商
4. 流量起来后再谈更好的比例（**有量才有议价权**）
