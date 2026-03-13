# 第三章：龙虾的触角

## 概述：让龙虾接入世界

本章实现了 KunClaw 的消息通道架构，支持通过不同的消息平台与 Agent 交互。目前实现了两个通道：
- **CLI 通道**：命令行交互
- **飞书通道**：飞书/Lark 消息平台（WebSocket 实时推送）

这一章我们要解决的问题是：**如何让 Agent 与外部世界通信**，同时保持系统的**简单性**和**可扩展性**。


## 1. KunClaw极简通道设计

KunClaw 采用极简的通道设计理念：

### 1.1 统一消息入口（Unified Message Gateway）

所有外部消息平台（飞书、Telegram、CLI等）都通过 `InboundMessage` 数据结构转换为内部格式：

```
         Telegram ----.
         Feishu -----+-- InboundMessage ---+-- Agent Loop
         CLI (stdin) --'  (统一消息格式)        '--- 发送回复
```

- **InboundMessage**：统一的消息格式，所有通道都转换为这个结构
- **Channel 抽象基类**：只需实现 `receive()` 和 `send()` 两个方法
- **ChannelManager**：通道管理器，负责注册和获取通道
- **消息队列 + 后台线程**：飞书消息通过 WebSocket 接收，放入队列，由后台线程处理

### 1.2 松耦合设计（Loose Coupling）

`Channel` 抽象基类定义了清晰的接口，通道实现与 Agent 核心逻辑分离：
- 飞书通道的 WebSocket 实现与 CLI 的 `input()`/`print()` 实现互不影响
- 每个通道可以独立开发、测试和部署
- 通道之间通过统一的 `InboundMessage` 格式通信

### 1.3 可插拔架构（Pluggable Architecture）

新通道可以像插件一样轻松接入系统：
1. 实现 `Channel` 接口（`receive()` 和 `send()` 方法）
2. 注册到 `ChannelManager`
3. 新通道立即可用

添加 Telegram、Discord 等通道只需要新增一个文件，无需修改核心代码。

### 1.4 会话隔离（Session Isolation）

不同通道、不同用户的会话完全隔离：
- 通过 `build_session_key(channel, account_id, peer_id)` 生成唯一的会话键
- CLI 会话、飞书私聊、飞书群组都拥有独立的记忆上下文
- 避免状态污染和隐私泄露

### 1.5 错误边界（Error Boundaries）

通道层的错误不会影响核心 Agent 的运行：
- 每个通道在独立的线程中运行
- 异常被捕获并记录日志，不会传递到 Agent 循环
- 飞书 WebSocket 断开不会影响 CLI 通道的正常使用





## 代码结构

### 1. InboundMessage 数据结构

```python
@dataclass
class InboundMessage:
    text: str           # 消息文本
    sender_id: str      # 发送者 ID
    channel: str        # 通道名称 ("cli", "feishu")
    account_id: str     # 机器人账号 ID
    peer_id: str        # 会话 ID（私聊用 user_id/open_id，群聊用 chat_id）
    is_group: bool      # 是否为群组
    media: list         # 媒体附件
    raw: dict           # 原始消息数据
```

### 2. Channel 抽象基类

```python
class Channel(ABC):
    name: str = "unknown"
    
    @abstractmethod
    def receive(self) -> InboundMessage | None:
        """接收消息，返回 None 表示无新消息"""
        ...
    
    @abstractmethod
    def send(self, to: str, text: str, **kwargs) -> bool:
        """发送消息"""
        ...
    
    def close(self) -> None:
        """关闭连接（可选）"""
        pass
```

### 3. CLI 通道

最简单的通道实现：
- `receive()`: 使用 `input()` 阻塞读取用户输入
- `send()`: 使用 `print()` 输出助手回复

### 4. 飞书通道（WebSocket 实时推送）

飞书通道使用 **WebSocket** 接收消息，而不是轮询 webhook：

```
┌─────────────────────────────────────────────────────────┐
│  飞书服务器                                               │
│  ┌─────────────┐    WebSocket     ┌─────────────────┐  │
│  │ 消息事件    │ ──────────────> │  FeishuChannel  │  │
│  └─────────────┘    实时推送      │  _handle_message │  │
│                                   └────────┬────────┘  │
│                                            │           │
│                                   放入消息队列          │
│                                            │           │
│                                   ┌────────▼────────┐  │
│                                   │  后台线程处理    │  │
│                                   │  run_agent_turn │  │
│                                   └────────┬────────┘  │
│                                            │           │
│                                   调用 API 发送回复     │
└────────────────────────────────────────────┼───────────┘
                                             │
                        ┌────────────────────▼──────────┐
                        │  im/v1/messages API          │
                        │  receive_id_type=open_id     │
                        └─────────────────────────────┘
```

#### 4.1 WebSocket 连接

使用官方 `lark_oapi` SDK：

```python
from lark_oapi import EventDispatcherHandler, ws, LogLevel

event_handler = (
    EventDispatcherHandler.builder(app_id, app_secret)
    .register_p2_im_message_receive_v1(self._handle_message)
    .build()
)

self._ws_client = ws.Client(
    app_id, app_secret,
    event_handler=event_handler,
    log_level=LogLevel.DEBUG,
)
self._ws_client.start()
```

#### 4.2 消息回复

飞书发送消息需要使用 `open_id` 而不是 `user_id`：

```python
def send(self, to: str, text: str, is_group: bool = False) -> bool:
    # 根据聊天类型选择 receive_id_type
    receive_id_type = "chat_id" if is_group else "open_id"
    
    resp = self._http.post(
        f"{self._get_api_base()}/im/v1/messages",
        params={"receive_id_type": receive_id_type},
        json={
            "receive_id": to,  # open_id 或 chat_id
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        },
    )
```

**注意**：
- 私聊用 `open_id`（如 `ou_249b2cc4a89127fabdc2f392b21d9cae`）
- 群聊用 `chat_id`（如 `oc_xxx`）

### 5. ChannelManager

```python
class ChannelManager:
    def register(self, channel: Channel) -> None:
        """注册通道"""
    
    def get(self, name: str) -> Channel | None:
        """获取通道"""
    
    def list_channels(self) -> list[str]:
        """列出所有通道"""
    
    accounts: list[ChannelAccount] = []  # 机器人账号列表
```

### 6. 后台消息处理

使用 threading 实现飞书消息的并行处理：

```python
def agent_loop():
    # 主线程：处理 CLI 输入（阻塞）
    while True:
        msg = cli.receive()
        if msg:
            run_agent_turn(msg, conversations, mgr)
    
    # 后台线程：处理飞书消息（非阻塞）
    def process_feishu_queue():
        while running:
            fs_msg = feishu_channel.receive()
            if fs_msg:
                run_agent_turn(fs_msg, conversations, mgr)
            time.sleep(0.1)
    
    fs_thread = threading.Thread(target=process_feishu_queue, daemon=True)
    fs_thread.start()
```

### 7. 回复打印规则

- **CLI 回复**：打印到前台 `Assistant: xxx`
- **飞书回复**：打印到后台日志 `[feishu] 回复已发送: xxx`（飞书本身会显示）

## 配置

### 环境变量

```bash
# 必需
ANTHROPIC_API_KEY=sk-ant-xxxxx
MODEL_ID=MiniMax-M2.5

# 飞书配置（可选）
FEISHU_APP_ID=cli_xxxxxxxx      # 飞书应用 ID
FEISHU_APP_SECRET=xxxxxxxx      # 飞书应用密钥
FEISHU_DOMAIN=feishu           # "feishu" 或 "lark"，默认 feishu
```

不配置飞书变量时，CLI 通道仍可正常使用。

## 运行

```bash
cd code
python agent_runtime.py
```

输出示例：

```
============================================================
  KunClaw  |  工具使用 + 会话管理 + 多通道
  Model: MiniMax-M2.5
  Workdir: D:\KunClaw\agent
  Session: session_1773334198
  Tools: bash, read_file, write_file, edit_file
  Channels: cli, feishu
  Messages loaded: 4

命令说明:
  /new       - 创建新会话
  /switch    - 切换会话
  /list      - 列出所有会话
  /context   - 查看上下文使用
  /compact   - 手动压缩历史
  /channels  - 列出已注册的通道
  /accounts  - 显示 bot 账号
  /help      - 显示帮助

输入 'quit' 或 'exit' 退出
============================================================

[feishu] WebSocket connecting...
[feishu] WebSocket started
  [+] Channel registered: feishu
```

## REPL 命令

| 命令 | 功能 |
|------|------|
| `/new` | 创建新会话 |
| `/switch <会话ID>` | 切换会话 |
| `/list` | 列出所有会话 |
| `/context` | 查看上下文使用 |
| `/compact` | 手动压缩历史 |
| `/channels` | 列出已注册的通道 |
| `/accounts` | 显示 bot 账号 |
| `/help` | 显示帮助 |

## 会话隔离

每个通道的消息会话相互隔离：

```python
def build_session_key(channel: str, account_id: str, peer_id: str) -> str:
    return f"code:main:direct:{channel}:{peer_id}"
```

这确保了：
- CLI 的会话与飞书的会话互不影响
- 不同的飞书用户有不同的会话历史

**Windows 兼容性设计**：

生成的会话键（如 `code:main:direct:cli:cli-user`）在保存到文件系统时会自动消毒：

```
原始会话键:  code:main:direct:cli:cli-user
消毒后文件名: code_main_direct_cli_cli-user.jsonl
```

**为什么需要消毒？**
- **Windows 限制**：Windows 文件系统禁止在文件名中使用冒号（`:`）
- **跨平台兼容**：确保代码可在所有操作系统（Windows/Linux/macOS）上运行
- **透明处理**：开发者无需关心平台差异，系统自动处理

**消毒规则**：
- 非法字符（`< > : " / \ | ? *`）替换为下划线（`_`）
- 点号开头的文件添加前缀下划线（避免隐藏文件）
- 空文件名转换为 `default_session`

**实际影响**：
- 使用 `/list` 查看消毒后的会话ID
- 切换会话时使用 `/switch <消毒后ID>`
- 文件系统看到的是消毒后的文件名，但会话管理逻辑不变


## 总结

在这一章，我们学会了：

| 概念 | 描述 |
|------|------|
| **统一消息入口** | 所有通道都通过 `InboundMessage` 数据结构转换为统一格式 |
| **Channel 抽象基类** | 定义了 `receive()` 和 `send()` 两个核心方法，实现松耦合 |
| **ChannelManager** | 通道管理器，负责注册、获取和管理所有通道 |
| **CLI 通道** | 使用 `input()`/`print()` 实现的命令行交互通道 |
| **飞书通道** | 基于 WebSocket 的实时消息推送，支持飞书/Lark 平台 |
| **会话隔离** | 通过 `build_session_key()` 确保不同通道、不同用户的会话独立 |
| **错误边界** | 通道层错误不会影响核心 Agent，异常被捕获并记录日志 |
| **可插拔架构** | 新通道只需实现 `Channel` 接口并注册，无需修改核心代码 |
| **code/channels/** | 通道模块，包含 base.py、manager.py、cli.py、feishu.py |

这就是 KunClaw 的**通道系统**，让 Agent 能够接入外部世界，同时保持系统的简单性和可扩展性。



## 下一步

- 添加 Telegram 通道支持
- 添加更多通道（Discord, Slack 等）
- 添加消息撤回/编辑支持
