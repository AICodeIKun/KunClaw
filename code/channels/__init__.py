"""
通道模块

包含各种消息通道的实现:
- CLIChannel: 命令行交互通道
- FeishuChannel: 飞书/Lark 消息通道
"""

from .cli import CLIChannel
from .feishu import FeishuChannel

__all__ = ["CLIChannel", "FeishuChannel"]
