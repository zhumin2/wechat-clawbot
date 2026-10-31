# wechat-clawbot

Python SDK for WeChat **ClawBot / iLink** protocol — zero dependency (Python stdlib only).

扫码登录微信 ClawBot，长轮询收消息、回复、主动推送，无需服务器、无需 OpenClaw。

> 协议参考：
> - 微信官方文档：<https://developers.weixin.qq.com/doc/aispeech/knowledge/openapi/Clawbotrelated.html>
> - 原理拆解：<https://cloud.tencent.com/developer/article/2646635>

## 安装

直接下载 `wechat_clawbot.py` 到项目里即可（纯标准库），或：

```bash
pip install wechat-clawbot
```

## 快速开始

### 1. 扫码登录（首次）

```python
from wechat_clawbot import WeChatClawBot

bot = WeChatClawBot.login_with_qr(
    cred_file="ilink_cred.json",
    on_qr=lambda qrcode, url: print("扫码登录：", url),
)
```

用手机微信扫码确认后，凭据会保存到 `ilink_cred.json`。

### 2. 之后加载凭据

```python
bot = WeChatClawBot.load("ilink_cred.json")
```

### 3. 主动推送（盯盘/告警）

```python
bot.push("【盯盘】紫金矿业触发止盈信号")
```

### 4. 回复消息（机器人）

```python
for msg in bot.poll_loop():
    print("收到:", msg.text)
    bot.send_text(msg.from_user_id, f"收到：{msg.text}", msg.context_token)
```

## API

| 方法 | 说明 |
|---|---|
| `WeChatClawBot.login_with_qr(cred_file, on_qr=...)` | 扫码登录，返回实例并保存凭据 |
| `WeChatClawBot.load(cred_file)` | 加载已登录凭据 |
| `bot.poll()` | 长轮询一次（~35s），返回 `List[Message]` |
| `bot.poll_loop()` | 无限收消息生成器；收到自动刷新并持久化 `context_token` |
| `bot.send_text(to_user_id, text, context_token="")` | 回复某条消息 |
| `bot.push(text)` | 主动推送给绑定的微信用户 |
| `bot.send_typing(to_user_id)` | 显示“对方正在输入…” |
| `bot.save()` | 持久化凭据（含最新 context_token） |

`Message` 对象属性：`from_user_id`、`context_token`、`text`、`item_list`。

## 关键实现细节（踩过的坑）

发送消息体必须包含：

```json
{
  "msg": {
    "from_user_id": "",
    "to_user_id": "...",
    "client_id": "每条消息唯一",
    "message_type": 2,
    "message_state": 2,
    "context_token": "...",
    "item_list": [{"type": 1, "text_item": {"text": "hi"}}]
  }
}
```

- `client_id` 必须每条唯一，重复会被微信**静默丢弃**。
- `message_type=2`（BOT）、`message_state=2`（FINISH）、`from_user_id=""`。
- 这些都已在库内部自动处理。

## 配额限制

用户向机器人发消息后，**24 小时内机器人最多可发 10 条**；用户再发一条会重置配额。因此适合做低频告警（如每日收盘盯盘），不适合高频推送。

## License

MIT
