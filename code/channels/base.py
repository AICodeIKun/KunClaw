"""
通道基础模块

定义所有通道共用的数据结构:
- InboundMessage: 统一的消息格式
- ChannelAccount: 机器人账号信息
- Channel: 通道抽象基类
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)


# ============================================================================
# 数据结构
# ============================================================================


@dataclass
class InboundMessage:
    """
    所有通道都规范化为此结构。Agent 循环只看到 InboundMessage。

    属性说明:
    - text: 消息文本内容
    - sender_id: 发送者 ID
    - channel: 通道名称 ("cli", "feishu", "telegram" 等)
    - account_id: 接收消息的机器人账号 ID
    - peer_id: 会话 ID
        - 私聊: user_id
        - 群组: chat_id
        - 话题: chat_id:topic:thread_id
    - is_group: 是否为群组消息
    - media: 媒体附件列表
    - raw: 原始消息数据(平台特定)
    """

    text: str
    sender_id: str
    channel: str = ""
    account_id: str = ""
    peer_id: str = ""
    is_group: bool = False
    media: list = field(default_factory=list)
    raw: dict = field(default_factory=dict)


@dataclass
class ChannelAccount:
    """
    每个 bot 的配置。同一通道类型可以运行多个 bot。

    属性说明:
    - channel: 通道类型 ("cli", "feishu", "telegram" 等)
    - account_id: 账号唯一标识
    - token: 认证令牌 (API key, bot token 等)
    - config: 额外配置字典
    """

    channel: str
    account_id: str
    token: str = ""
    config: dict = field(default_factory=dict)


# ============================================================================
# Channel 抽象基类
# ============================================================================


class Channel(ABC):
    """
    通道抽象基类。所有通道必须实现以下接口:

    - receive(): 接收下一条消息，返回 None 表示无消息
    - send(to, text, **kwargs): 发送消息到指定目标
    - close(): 关闭连接(可选实现)
    """

    name: str = "unknown"

    @abstractmethod
    def receive(self) -> InboundMessage | None:
        """接收下一条消息。返回 None 表示当前无新消息。"""
        ...

    @abstractmethod
    def send(self, to: str, text: str, **kwargs: Any) -> bool:
        """
        发送消息到指定目标。

        参数:
            to: 目标标识 (user_id, chat_id 等)
            text: 消息文本
            **kwargs: 额外参数 (如 markdown, keyboard 等)

        返回:
            发送成功返回 True，否则返回 False
        """
        ...

    def close(self) -> None:
        """关闭通道连接。子类可重写。"""
        pass
