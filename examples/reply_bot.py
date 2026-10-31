# -*- coding: utf-8 -*-
"""自动回复机器人示例：收到用户消息就回一句。"""
from wechat_clawbot import WeChatClawBot

bot = WeChatClawBot.load("ilink_cred.json")
print("监听中... 给微信 ClawBot 发消息试试")
for msg in bot.poll_loop():
    print("收到:", msg.text)
    bot.send_text(msg.from_user_id, f"你刚才说：{msg.text}", msg.context_token)
