"""
飞书/Lark 通道实现 - 使用官方 lark_oapi SDK
"""

import json
import threading
from typing import Any, List

try:
    import httpx

    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    from lark_oapi import EventDispatcherHandler, ws, LogLevel

    HAS_LARK = True
except Exception:
    HAS_LARK = False

from .base import Channel, ChannelAccount, InboundMessage


DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
RESET = "\033[0m"


class FeishuChannel(Channel):
    name = "feishu"

    def __init__(self, account: ChannelAccount, msg_queue: List = None) -> None:
        if not HAS_HTTPX:
            raise RuntimeError("FeishuChannel requires httpx: pip install httpx")
        if not HAS_LARK:
            raise RuntimeError(
                "FeishuChannel requires lark-oapi: pip install lark-oapi"
            )

        self.account_id = account.account_id
        self.app_id = account.config.get("app_id", "")
        self.app_secret = account.config.get("app_secret", "")
        self._is_lark = account.config.get("is_lark", False)

        self._msg_queue = msg_queue or []
        self._queue_lock = threading.Lock()

        self._ws_client = None
        self._ws_thread = None
        self._running = False

        self._http = httpx.Client(timeout=15.0)

    def _get_api_base(self) -> str:
        return (
            "https://open.larksuite.com/open-apis"
            if self._is_lark
            else "https://open.feishu.cn/open-apis"
        )

    def _refresh_token(self) -> str:
        try:
            resp = self._http.post(
                f"{self._get_api_base()}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
            )
            data = resp.json()
            if data.get("code") != 0:
                print(f"  {RED}[feishu] Token error: {data.get('msg', '?')}{RESET}")
                return ""
            return data.get("tenant_access_token", "")
        except Exception as exc:
            print(f"  {RED}[feishu] Token error: {exc}{RESET}")
            return ""

    def _handle_message(self, data):
        try:
            event = data.event
            message = event.message

            chat_type = message.chat_type

            sender = event.sender
            sender_id = sender.sender_id
            # 获取 open_id 用于发送消息 (API 需要 open_id)
            open_id = (
                sender_id.open_id
                if hasattr(sender_id, "open_id")
                else sender_id.user_id
                if hasattr(sender_id, "user_id")
                else str(sender_id)
            )
            user_id = (
                sender_id.user_id if hasattr(sender_id, "user_id") else str(sender_id)
            )

            content = message.content
            try:
                content_dict = (
                    json.loads(content) if isinstance(content, str) else content
                )
            except:
                content_dict = {}

            text = content_dict.get("text", "")

            if not text:
                return

            is_group = chat_type == "group"

            inbound = InboundMessage(
                text=text,
                sender_id=user_id,  # user_id 用于标识
                channel="feishu",
                account_id=self.account_id,
                peer_id=open_id,  # open_id 用于发送回复
                is_group=is_group,
                raw={},
            )

            with self._queue_lock:
                self._msg_queue.append(inbound)

            print(f"{DIM}[feishu] Received: {text[:50]}...")

        except Exception as e:
            print(f"  {RED}[feishu] Handle error: {e}{RESET}")

    def start_ws(self) -> None:
        if self._running:
            return

        self._running = True

        event_handler = (
            EventDispatcherHandler.builder(
                self.app_id,
                self.app_secret,
            )
            .register_p2_im_message_receive_v1(self._handle_message)
            .build()
        )

        self._ws_client = ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=event_handler,
            log_level=LogLevel.DEBUG,
        )

        def run_ws():
            print(f"{GREEN}[feishu] WebSocket connecting...{RESET}")
            try:
                self._ws_client.start()
            except Exception as e:
                print(f"  {RED}[feishu] WebSocket error: {e}{RESET}")
            finally:
                self._running = False

        self._ws_thread = threading.Thread(target=run_ws, daemon=True)
        self._ws_thread.start()

        print(f"{GREEN}[feishu] WebSocket started{RESET}")

    def receive(self) -> InboundMessage | None:
        with self._queue_lock:
            if self._msg_queue:
                return self._msg_queue.pop(0)
        return None

    def send(self, to: str, text: str, is_group: bool = False, **kwargs: Any) -> bool:
        """发送消息到飞书。

        Args:
            to: 接收者 ID (user_id/open_id/chat_id)
            text: 消息文本
            is_group: 是否为群聊
        """
        token = self._refresh_token()
        if not token:
            return False

        # 根据聊天类型选择 receive_id_type
        receive_id_type = "chat_id" if is_group else "open_id"

        try:
            resp = self._http.post(
                f"{self._get_api_base()}/im/v1/messages",
                params={"receive_id_type": receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": to,
                    "msg_type": "text",
                    "content": json.dumps({"text": text}),
                },
            )
            data = resp.json()
            if data.get("code") != 0:
                print(f"  {RED}[feishu] Send error: {data.get('msg', '?')}{RESET}")
                return False
            return True
        except Exception as exc:
            print(f"  {RED}[feishu] Send error: {exc}{RESET}")
            return False

    def close(self) -> None:
        self._running = False
        if self._ws_client:
            try:
                self._ws_client.stop()
            except Exception:
                pass
        self._http.close()
