"""
通道管理器模块

ChannelManager 负责管理所有注册的通道:
- register(): 注册新通道
- get(): 获取指定通道
- list_channels(): 列出所有通道
- close_all(): 关闭所有通道
"""

from .base import Channel, ChannelAccount


class ChannelManager:
    """通道管理器 - 持有所有活跃通道的注册中心"""

    def __init__(self) -> None:
        self.channels: dict[str, Channel] = {}
        self.accounts: list[ChannelAccount] = []

    def register(self, channel: Channel) -> None:
        self.channels[channel.name] = channel

    def list_channels(self) -> list[str]:
        return list(self.channels.keys())

    def get(self, name: str) -> Channel | None:
        return self.channels.get(name)

    def close_all(self) -> None:
        for ch in self.channels.values():
            ch.close()
