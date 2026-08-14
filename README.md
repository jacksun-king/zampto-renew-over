# 🖥 Zampto 自动续期

基于 GitHub Actions 的 [Zampto.net](https://dash.zampto.net) 免费服务器自动续期脚本。

## 🔐 Secrets 配置

| Secret 名称 | 是否必填 | 说明 |
|---|---|---|
| `ZAMPTO_EMAIL` | ✅ 必填 | 登录邮箱 |
| `ZAMPTO_PASSWORD` | ✅ 必填 | 登录密码 |
| `NODE_LINK` | ❌ 可选 | 代理链接，如 vless:// vmess:// tuic:// hysteria2:// |
| `TG_BOT_TOKEN` | ❌ 可选 | Telegram Bot Token |
| `TG_CHAT_ID` | ❌ 可选 | Telegram Chat ID |

## 📋 Variables 配置

| Variable 名称 | 默认值 | 说明 |
|---|---|---|
| `SERVER_ID` | `13421` | 服务器 ID |

## ⏱ 执行流程

1. 工作流触发（定时或手动）
2. 启动浏览器 → 登录 → Turnstile 验证 → 续期 → Telegram 通知
3. 清理旧工作流记录

## ⏰ 定时

每周四 UTC 08:00（北京时间 16:00）执行。可根据服务器的到期时间修改 cron。