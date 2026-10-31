# -*- coding: utf-8 -*-
"""主动推送示例：扫码登录后直接发消息给自己微信。"""
from wechat_clawbot import WeChatClawBot

# 首次扫码（之后改成 load 即可）
# bot = WeChatClawBot.login_with_qr("ilink_cred.json")

bot = WeChatClawBot.load("ilink_cred.json")
bot.push("hello from wechat-clawbot")
