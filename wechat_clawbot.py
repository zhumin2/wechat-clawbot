# -*- coding: utf-8 -*-
"""
wechat_clawbot — 微信 ClawBot (iLink 协议) Python 开发库
=========================================================
零依赖（仅标准库），封装扫码登录、长轮询收消息、发文本/媒体消息。

官方协议参考：
  - https://developers.weixin.qq.com/doc/aispeech/knowledge/openapi/Clawbotrelated.html
  - https://cloud.tencent.com/developer/article/2646635

典型用法
--------
1) 扫码登录（首次，会弹出二维码链接，用手机微信扫）：

    from wechat_clawbot import WeChatClawBot
    bot = WeChatClawBot.login_with_qr(cred_file="ilink_cred.json")

2) 之后直接加载凭据运行：

    bot = WeChatClawBot.load("ilink_cred.json")
    for msg in bot.poll_loop():
        text = msg.item_list[0].text_item.text
        bot.send_text(msg.from_user_id, f"收到：{text}", msg.context_token)

3) 主动推送（用户24小时内发过消息、配额未用尽时）：

    bot.push("【盯盘】紫金矿业触发止盈信号")

配额限制：用户发一条消息后 24 小时内，机器人最多可发 10 条；用户再发会重置。
"""
from __future__ import annotations

import base64
import json
import os
import random
import time
import dataclasses
import urllib.request
import urllib.error
from typing import Callable, Optional, List, Dict, Any

DEFAULT_BASE = "https://ilinkai.weixin.qq.com"
CHANNEL_VERSION = "2.0.0"


class ClawbotError(Exception):
    """iLink 协议错误。"""


class SessionExpiredError(ClawbotError):
    """会话过期（errcode -14），需重新扫码登录。"""


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclasses.dataclass
class TextItem:
    text: str = ""


@dataclasses.dataclass
class MessageItem:
    type: int = 1  # 1=text 2=image 3=voice 4=file 5=video
    text_item: TextItem = dataclasses.field(default_factory=TextItem)
    raw: Dict[str, Any] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class Message:
    from_user_id: str
    to_user_id: str = ""
    context_token: str = ""
    create_time_ms: int = 0
    item_list: List[MessageItem] = dataclasses.field(default_factory=list)

    @property
    def text(self) -> str:
        for it in self.item_list:
            if it.type == 1 and it.text_item:
                return it.text_item.text
        return ""


# --------------------------------------------------------------------------- #
# 主类
# --------------------------------------------------------------------------- #
class WeChatClawBot:
    def __init__(self, bot_token: str, chat_user_id: str,
                 base_url: str = DEFAULT_BASE,
                 ilink_bot_id: str = "", context_token: str = "",
                 cred_file: Optional[str] = None):
        self.bot_token = bot_token
        self.chat_user_id = chat_user_id      # 你的微信 id（推送给谁）
        self.base_url = base_url.rstrip("/")
        self.ilink_bot_id = ilink_bot_id
        self.context_token = context_token    # 最近一次收到的上下文 token
        self.cred_file = cred_file
        self._cursor = ""

    # ----------------------------- HTTP 底层 ----------------------------- #
    def _headers(self) -> Dict[str, str]:
        uin = base64.b64encode(str(random.randint(1, 2 ** 31)).encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.bot_token}",
            "AuthorizationType": "ilink_bot_token",
            "X-WECHAT-UIN": uin,
        }

    def _post(self, path: str, body: Dict[str, Any], timeout: int = 60) -> Dict[str, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(self.base_url + path, data=data, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise ClawbotError(f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}") from e

    # ----------------------------- 凭据存取 ----------------------------- #
    def save(self, cred_file: Optional[str] = None):
        path = cred_file or self.cred_file
        if not path:
            raise ClawbotError("未指定 cred_file")
        data = {
            "bot_token": self.bot_token,
            "ilink_bot_id": self.ilink_bot_id,
            "ilink_user_id": self.chat_user_id,
            "chat_user_id": self.chat_user_id,
            "baseurl": self.base_url,
            "context_token": self.context_token,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, cred_file: str) -> "WeChatClawBot":
        with open(cred_file, encoding="utf-8") as f:
            c = json.load(f)
        return cls(
            bot_token=c["bot_token"],
            chat_user_id=c.get("chat_user_id") or c.get("ilink_user_id"),
            base_url=c.get("baseurl", DEFAULT_BASE),
            ilink_bot_id=c.get("ilink_bot_id", ""),
            context_token=c.get("context_token", ""),
            cred_file=cred_file,
        )

    # ----------------------------- 扫码登录 ----------------------------- #
    @classmethod
    def login_with_qr(cls, cred_file: str = "ilink_cred.json",
                      on_qr: Optional[Callable[[str, str], None]] = None,
                      timeout: int = 300,
                      qr_ttl: int = 80) -> "WeChatClawBot":
        """
        扫码登录。on_qr(qrcode, qr_url) 回调让你展示二维码（打印/生成图片都行）。
        二维码约 90 秒过期，到期自动申请新码并再次回调 on_qr，无需重启。
        阻塞直到用户扫码确认或超过 timeout。
        """
        deadline = time.time() + timeout
        qrcode = qr_url = ""

        def fetch_qr():
            nonlocal qrcode, qr_url
            r = cls._static_get(f"{DEFAULT_BASE}/ilink/bot/get_bot_qrcode?bot_type=3")
            qrcode, qr_url = r["qrcode"], r.get("qrcode_img_content", "")
            if on_qr:
                on_qr(qrcode, qr_url)
            else:
                print(f"请用手机微信扫码登录：{qr_url}")

        fetch_qr()
        last_refresh = time.time()

        while time.time() < deadline:
            # 二维码快过期，自动换一张新码
            if time.time() - last_refresh >= qr_ttl:
                fetch_qr()
                last_refresh = time.time()
            s = cls._static_get(f"{DEFAULT_BASE}/ilink/bot/get_qrcode_status?qrcode={qrcode}")
            status = s.get("status")
            if status == "confirmed":
                bot = cls(
                    bot_token=s["bot_token"],
                    chat_user_id=s.get("ilink_user_id", ""),
                    base_url=s.get("baseurl", DEFAULT_BASE),
                    ilink_bot_id=s.get("ilink_bot_id", ""),
                    cred_file=cred_file,
                )
                bot.save()
                return bot
            if status == "expired":
                fetch_qr()  # 立即换新码
                last_refresh = time.time()
            time.sleep(2)
        raise ClawbotError("扫码超时")

    @staticmethod
    def _static_get(url: str) -> Dict[str, Any]:
        req = urllib.request.Request(url, headers={"User-Agent": "wechat-clawbot/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))

    # ----------------------------- 收消息 ----------------------------- #
    def poll(self) -> List[Message]:
        """长轮询一次（约35s），返回新消息列表。"""
        r = self._post("/ilink/bot/getupdates", {
            "base_info": {"channel_version": CHANNEL_VERSION},
            "get_updates_buf": self._cursor,
        }, timeout=60)
        if r.get("errcode") == -14:
            raise SessionExpiredError("会话过期，需重新扫码登录")
        self._cursor = r.get("get_updates_buf", self._cursor)
        out = []
        for m in r.get("msgs") or []:
            items = []
            for it in m.get("item_list") or []:
                items.append(MessageItem(
                    type=it.get("type", 1),
                    text_item=TextItem(text=(it.get("text_item") or {}).get("text", "")),
                    raw=it,
                ))
            out.append(Message(
                from_user_id=m.get("from_user_id", ""),
                to_user_id=m.get("to_user_id", ""),
                context_token=m.get("context_token", ""),
                create_time_ms=m.get("create_time_ms", 0),
                item_list=items,
            ))
        # 刷新并持久化最新 context_token
        if out and out[-1].context_token:
            self.context_token = out[-1].context_token
            if self.cred_file:
                try:
                    self.save()
                except Exception:
                    pass
        return out

    def poll_loop(self):
        """无限收消息的生成器。"""
        while True:
            try:
                yield from self.poll()
            except ClawbotError as e:
                raise e
            except Exception as e:
                print(f"[poll] {e}")
                time.sleep(3)

    # ----------------------------- 发消息 ----------------------------- #
    def _client_id(self) -> str:
        return f"{random.randint(1, 2**31)}-{time.time_ns()}"

    def send_message(self, to_user_id: str, item_list: List[Dict[str, Any]],
                     context_token: str = "") -> Dict[str, Any]:
        """底层发送。item_list 形如 [{"type":1,"text_item":{"text":"hi"}}]。"""
        body = {
            "base_info": {"channel_version": CHANNEL_VERSION},
            "msg": {
                "from_user_id": "",                 # 必须留空
                "to_user_id": to_user_id,
                "client_id": self._client_id(),     # 每条唯一，重复会被静默丢弃
                "message_type": 2,                  # BOT
                "message_state": 2,                 # FINISH
                "context_token": context_token or self.context_token,
                "item_list": item_list,
            },
        }
        r = self._post("/ilink/bot/sendmessage", body, timeout=15)
        if r.get("errcode") == -14:
            raise SessionExpiredError("会话过期，需重新扫码登录")
        return r

    def send_text(self, to_user_id: str, text: str,
                  context_token: str = "") -> Dict[str, Any]:
        """回复某用户的消息（建议带上对方发来的 context_token）。"""
        return self.send_message(to_user_id,
                                 [{"type": 1, "text_item": {"text": text}}],
                                 context_token=context_token)

    def push(self, text: str) -> bool:
        """主动推送给绑定的微信用户（无需回复某条消息）。
        返回是否成功。注意 24h/10 条配额。"""
        if not self.chat_user_id:
            raise ClawbotError("未绑定 chat_user_id")
        r = self.send_text(self.chat_user_id, text, context_token=self.context_token)
        return "message_id" in r

    def send_typing(self, to_user_id: str, context_token: str = ""):
        """显示“对方正在输入…”。"""
        cfg = self._post("/ilink/bot/getconfig", {
            "base_info": {"channel_version": CHANNEL_VERSION},
            "ilink_user_id": to_user_id,
            "context_token": context_token or self.context_token,
        }, timeout=15)
        ticket = cfg.get("typing_ticket")
        if ticket:
            return self._post("/ilink/bot/sendtyping", {
                "base_info": {"channel_version": CHANNEL_VERSION},
                "ilink_user_id": to_user_id,
                "typing_ticket": ticket,
                "status": 1,
            }, timeout=15)


# --------------------------------------------------------------------------- #
# 命令行自检：python -m wechat_clawbot
# --------------------------------------------------------------------------- #
def _selftest():
    cred = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ilink_cred.json")
    bot = WeChatClawBot.load(cred)
    print("已加载凭据，chat_user_id =", bot.chat_user_id)
    bot.push("✅ wechat_clawbot 库自检成功")
    print("已推送测试消息到微信。")


if __name__ == "__main__":
    _selftest()
