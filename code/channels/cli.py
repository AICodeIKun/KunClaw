"""
CLI 通道实现

命令行交互通道是最简单的通道实现:
- receive(): 使用 input() 读取用户输入
- send(): 使用 print() 输出助手回复
"""

import sys
from typing import Any

from .base import Channel, InboundMessage


# ANSI 颜色
CYAN = "\033[36m"
GREEN = "\033[32m"
BOLD = "\033[1m"
RESET = "\033[0m"


class CLIChannel(Channel):
    """CLI 通道 - 命令行交互"""

    name = "cli"

    def __init__(self) -> None:
        self.account_id = "cli-local"

    def receive(self) -> InboundMessage | None:
        """接收用户输入。"""
        try:
            text = input(f"{CYAN}{BOLD}You > {RESET}").strip()
        except (KeyboardInterrupt, EOFError):
            return None
        if not text:
            return None
        return InboundMessage(
            text=text,
            sender_id="cli-user",
            channel="cli",
            account_id=self.account_id,
            peer_id="cli-user",
        )

    def send(self, to: str, text: str, **kwargs: Any) -> bool:
        """打印助手回复到标准输出。"""
        print(f"\n{GREEN}{BOLD}Assistant:{RESET} {text}\n")
        return True
