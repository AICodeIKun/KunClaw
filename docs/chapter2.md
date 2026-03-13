 # 第二章：龙虾的记忆

> "龙虾没有记忆，但它需要。"
> 
> — KunClaw 哲学


## 概述：让龙虾记住一切

在第一章，我们给龙虾装上了大脑和钳子。但有一个问题：**每次重启，它就忘了之前发生了什么。**

这一章我们要解决记忆问题，让 Agent 能够：
1. **持久化存储**：重启后会话不会丢失
2. **智能压缩**：在有限的 LLM 上下文窗口内保持长期对话
3. **分层管理**：区分短时记忆和长时记忆


## 1. KunClaw极简记忆系统

KunClaw 的会话系统设计受到人类记忆机制的启发，采用了极简的实现方案：

### 1.1 分层记忆设计

| 记忆类型 | 实现方式 | 容量 | 持久性 | 用途 |
|----------|----------|------|--------|------|
| **短时记忆** | `messages[]` 对话历史 | 受上下文窗口限制 | 会话期间 | 维持对话连贯性 |
| **长时记忆** | `JSONL` 文件存储 | 仅受磁盘空间限制 | 永久保存 | 跨会话知识保留 |
| **工作记忆** | 当前处理的消息 | 单条消息 | 即时 | 工具调用和响应生成 |

这种分层设计解决了 **LLM 上下文有限** 与 **长期协作需求** 的矛盾。

### 1.2 JSONL 格式：简单可靠的选择

为什么选择 JSONL 而不是数据库或单个 JSON 文件？
1. **原子性追加**：每行独立，追加写入不会损坏现有数据
2. **流式处理**：可以逐行读取，适合大会话文件
3. **人类可读**：文本格式便于调试和手动检查
4. **容错性强**：单行损坏不会影响整个文件

### 1.3 智能压缩策略

当对话历史超过 LLM 上下文限制时，KunClaw 采用**智能压缩**而非简单截断：
- **保留最近 20%**：最近的对话通常最重要
- **压缩最早 50%**：用 LLM 生成摘要，保留关键信息
- **分层处理**：先尝试截断工具结果，不行再压缩历史

### 1.4 压缩算法实现细节

在 `ContextGuard.compact_history()` 方法中，压缩算法遵循以下精确步骤：

```python
# 1. 计算保留和压缩的数量
keep_count = max(4, int(len(messages) * 0.2))      # 至少保留4条，或20%
compress_count = max(2, int(len(messages) * 0.5))  # 至少压缩2条，或50%
compress_count = min(compress_count, len(messages) - keep_count)

# 2. 序列化要压缩的消息
old_messages = messages[:compress_count]
old_text = self._serialize_for_summary(old_messages)

# 3. 调用 LLM 生成摘要
summary_prompt = f"请简洁地总结以下对话，保留关键信息：\n\n{old_text}\n\n请直接输出摘要："

# 4. 用摘要替换旧消息
compacted = [
    {"role": "user", "content": f"[之前对话摘要]\n{summary}"}
]
compacted.extend(messages[compress_count:])
```

**算法设计要点**：
1. **保底机制**：`max(4, ...)` 和 `max(2, ...)` 确保即使会话很短也有意义
2. **边界检查**：`min(compress_count, len(messages) - keep_count)` 防止压缩数量超过可用消息
3. **摘要提示词优化**：提示词明确要求"直接输出摘要"，避免 LLM 添加多余内容
4. **序列化策略**：`_serialize_for_summary()` 将复杂消息结构转换为纯文本，便于 LLM 处理

这个算法体现了 **"透明可解释"** 的设计原则：每个步骤都简单明了，便于调试和调整。





## 代码结构

```
code/
├── agent_runtime.py  # 主入口
├── tools.py         # 工具模块（第一章）
└── session.py       # 会话管理模块
    ├── SessionStore 类
    │   ├── save_user()         # 保存用户消息
    │   ├── save_assistant()    # 保存助手消息
    │   ├── save_tool_use()     # 保存工具调用
    │   ├── save_tool_result()  # 保存工具结果
    │   ├── load_session()     # 从 JSONL 重建 messages[]
    │   └── list_sessions()     # 列出所有会话
    │
    ├── ContextGuard 类
    │   ├── guard_api_call()    # 包裹 API 调用，溢出时重试
    │   ├── compact_history()   # LLM 摘要压缩历史
    │   └── get_context_usage() # 查看上下文使用情况
    │
    └── 常量
        ├── WORKSPACE_DIR       # 工作目录
        └── CONTEXT_SAFE_LIMIT  # 上下文上限（180K tokens）
```

---

## 第一部分：会话持久化 — SessionStore

### 什么是会话？

当你和 Agent 对话时，会产生大量的消息：

```python
messages = [
    {"role": "user", "content": "法国的首都是什么？"},
    {"role": "assistant", "content": "法国的首都是巴黎。"},
    {"role": "user", "content": "它的人口是多少？"},
    {"role": "assistant", "content": "约 216 万人。"},
    ...
]
```

这些消息就是"会话"。如果我们不保存，每次重启就全丢了。

### JSONL 文件格式

我们使用 **JSONL**（JSON Lines）格式存储会话：

```
workspace/.sessions/session_1234567890.jsonl
```

每行是一条 JSON 记录，四种类型：

```json
{"type": "user", "content": "法国的首都是什么？", "ts": 1234567890}
{"type": "assistant", "content": [{"type": "text", "text": "法国的首都是巴黎。"}], "ts": 1234567891}
{"type": "tool_use", "tool_use_id": "toolu_abc", "name": "bash", "input": {"command": "ls"}, "ts": 1234567892}
{"type": "tool_result", "tool_use_id": "toolu_abc", "content": "file1.txt\nfile2.txt", "ts": 1234567893}
```

**为什么用 JSONL？**
- 追加写入是**原子的**（不需要重写整个文件）
- 读取时一行一行解析即可
- 简单、可靠、易于调试

### SessionStore 实现

```python
class SessionStore:
    def __init__(self, session_id: str = None):
        # 创建新会话或加载已有会话
        self.session_id = session_id or f"session_{int(time.time())}"
        self.session_path = WORKSPACE_DIR / ".sessions" / f"{self.session_id}.jsonl"
    
    def save_user(self, content: str):
        """保存用户消息"""
        self.save_turn({"type": "user", "content": content, "ts": ...})
    
    def save_assistant(self, content):
        """保存助手消息"""
        self.save_turn({"type": "assistant", "content": content, "ts": ...})
    
    def load_session(self) -> list[dict]:
        """从 JSONL 重建 messages[]"""
        messages = []
        for line in open(self.session_path):
            record = json.loads(line)
            # 转换为 API 格式
            messages.append({"role": record["type"], "content": record["content"]})
        return messages
```

### Windows 兼容性设计

考虑到 Windows 文件系统对文件名的限制，KunClaw 实现了文件名消毒机制：

```python
@staticmethod
def sanitize_filename(name: str) -> str:
    # Windows 非法字符: < > : \" / \\ | ? *
    invalid_chars = '<>:\"/\\\\|?*'
    sanitized = name
    for char in invalid_chars:
        sanitized = sanitized.replace(char, '_')
    # 额外处理点号开头的文件（隐藏文件）
    if sanitized.startswith('.'):
        sanitized = '_' + sanitized[1:]
    # 确保文件名不为空
    if not sanitized:
        sanitized = 'default_session'
    return sanitized
```

**作用**：
- 自动替换会话键中的非法字符（如冒号）为下划线
- 确保跨平台兼容性（Windows/Linux/macOS）
- 保持会话隔离性的同时避免文件系统错误

**实际示例**：
| 场景 | 原始会话键 | 消毒后文件名 |
|------|-----------|-------------|
| CLI 用户 | `code:main:direct:cli:cli-user` | `code_main_direct_cli_cli-user.jsonl` |
| 飞书用户 | `code:main:direct:feishu:ou_xxx` | `code_main_direct_feishu_ou_xxx.jsonl` |

**文件创建时机**：
- `/new` 命令会**立即**创建空的 `.jsonl` 文件
- 确保新会话在 `/list` 中立即可见
- 避免惰性创建导致的会话"消失"问题

### 重放机制

会话恢复的核心是 `_rebuild_history()` —— 把扁平的 JSONL 记录转换回 API 格式：

```python
def load_session(self) -> list[dict]:
    messages = []
    
    for record in jsonl_records:
        if record["type"] == "user":
            messages.append({"role": "user", "content": record["content"]})
        
        elif record["type"] == "assistant":
            # 字符串转文本块
            content = record["content"]
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            messages.append({"role": "assistant", "content": content})
        
        elif record["type"] == "tool_use":
            # 合并到最后的 assistant 消息
            block = {"type": "tool_use", "id": record["tool_use_id"], ...}
            messages[-1]["content"].append(block)
        
        elif record["type"] == "tool_result":
            # 合并到最后的 user 消息
            ...
    
    return messages
```

---

## 第二部分：上下文保护 — ContextGuard

### 上下文溢出问题

LLM 有上下文窗口限制（比如 200K tokens）。当对话越来越长时：

```
正常调用 --> 成功 ✓
继续对话 --> 继续对话 --> 上下文溢出！ ❌
```

这时 API 会返回错误：`context length exceeded`

### 3 阶段保护策略

我们设计了 3 个阶段的保护：

| 阶段 | 策略 | 说明 |
|------|------|------|
| 0 | 正常调用 | 首次尝试 |
| 1 | 截断工具结果 | 如果工具输出太大，截断它 |
| 2 | 历史压缩 | 用 LLM 生成摘要，替换旧消息 |
| 3 | 失败 | 抛出异常 |

### 阶段 1：截断工具结果

当工具返回超大输出时（比如读取大文件），我们截断它：

```python
def _truncate_large_tool_results(self, messages, max_length=10000):
    truncated = []
    
    for msg in messages:
        if msg["role"] == "user" and isinstance(msg["content"], list):
            new_content = []
            for block in msg["content"]:
                if block["type"] == "tool_result":
                    content = block["content"]
                    if len(content) > max_length:
                        # 截断并标注
                        content = content[:max_length] + f"\n... [共 {len(content)} 字符]"
                    block["content"] = content
                new_content.append(block)
            truncated.append({"role": msg["role"], "content": new_content})
        else:
            truncated.append(msg)
    
    return truncated
```

### 阶段 2：历史压缩

如果截断还不够，就用 LLM 生成摘要。逻辑是：**保留最近 20% 的消息，压缩最早的 50%**。

假设有 10 条消息：

```python
keep_count = max(4, int(10 * 0.2))     # 保留：max(4, 2) = 4 条
compress_count = max(2, int(10 * 0.5))  # 压缩：max(2, 5) = 5 条
compress_count = min(5, 10 - 4)  # 确保压缩数不超过：min(5, 6) = 5 条
```

| 变量 | 公式 | 含义                        |
|------|------|---------------------------|
| `keep_count` | `max(4, 20%)` | 至少保留 4 条，或者 20% 的消息       |
| `compress_count` | `max(2, 50%)` | 至少压缩 2 条，或者 50% 的消息       |
| `compress_count` | `min(..., 剩余)` | 确保压缩数不超过可压缩的剩余消息数 |


压缩后保留最近的 4 条，压缩最早的 5 条变成摘要。

如果截断还不够，就用 LLM 生成摘要：

```
原始消息 (50%):
  用户: 帮我写一个 Python 排序算法
  助手: 好的，我给你写快速排序...
  用户: 再优化一下性能
  助手: 可以用归并排序...

压缩后:
  用户: [之前对话摘要] 助手帮用户写了排序算法，用户要求优化性能
  助手: 明白了，我会记住这些上下文。
  (保留的近期消息)
```

```python
def compact_history(self, messages, system):
    # 保留最近 20%，压缩最早的 50%
    keep_count = max(4, int(len(messages) * 0.2))
    compress_count = max(2, int(len(messages) * 0.5))
    
    # 让 LLM 生成摘要
    old_text = serialize_messages(messages[:compress_count])
    summary = llm_summarize(old_text)
    
    # 替换为摘要
    compacted = [
        {"role": "user", "content": f"[之前对话摘要]\n{summary}"},
        {"role": "assistant", "content": [{"type": "text", "text": "明白了。"}]}
    ]
    compacted.extend(messages[compress_count:])
    
    return compacted
```

### 保护流程图

```
用户输入
    |
    v
ContextGuard.guard_api_call()
    |
    +-- Attempt 0: 正常调用
    |       |
    |   溢出? --no--> 成功 ✓
    |       |yes
    +-- Attempt 1: 截断工具结果
            |
        溢出? --no--> 成功 ✓
            |yes
        +-- Attempt 2: 压缩历史
                |
            溢出? --no--> 成功 ✓
                |yes
            --> 抛出异常 ❌
```

---

## 第三部分：REPL 命令

在 REPL 模式下，我们支持一些会话管理命令：

| 命令 | 功能 | 行为变化 |
|------|------|----------|
| `/new` | 创建新会话 | **立即**创建空的 `.jsonl` 文件，确保会话立即可见 |
| `/switch <id>` | 切换会话 | 使用消毒后的会话ID（可从 `/list` 输出复制） |
| `/list` | 列出所有会话 | 显示所有会话（包括新建的）而不仅仅是包含消息的会话 |
| `/context` | 查看上下文使用情况 | 显示当前会话的token使用情况 |
| `/compact` | 手动压缩历史 | 使用LLM摘要替换旧消息，释放上下文空间 |
| `/help` | 显示帮助 | 显示所有可用命令 |
### 查看上下文使用

```
You > /context
Context usage: ~45,000 / 180,000 tokens
[################------------] 25%
```

---

---
---

## REPL 命令

```
# 本章实现的代码结构：
code/
├── agent_runtime.py  # 主入口
├── tools.py         # 工具模块（第一章）
└── session.py       # 会话管理模块
    ├── SessionStore 类
    │   ├── save_user()         # 保存用户消息
    │   ├── save_assistant()    # 保存助手消息
    │   ├── save_tool_use()     # 保存工具调用
    │   ├── save_tool_result()  # 保存工具结果
    │   ├── load_session()     # 从 JSONL 重建 messages[]
    │   └── list_sessions()     # 列出所有会话
    │   ├── ContextGuard 类
    │   ├── guard_api_call()    # 包裹 API 调用，溢出时重试
    │   ├── compact_history()   # LLM 摘要压缩历史
    │   └── get_context_usage() # 查看上下文使用情况
    │   └── 常量
        ├── WORKSPACE_DIR       # 工作目录
        └── CONTEXT_SAFE_LIMIT  # 上下文上限（180K tokens）
```

---

## REPL 命令

| 命令 | 功能 |
|------|------|
| `/new` | 创建新会话 |
| `/switch <id>` | 切换会话 |
| `/list` | 列出所有会话 |
| `/context` | 查看上下文使用情况 |
| `/compact` | 手动压缩历史 |
| `/help` | 显示帮助 |

---



## 总结

在这一章，我们学会了：

| 概念 | 描述 |
|------|------|
| **SessionStore** | JSONL 持久化，追加写入，读取重放 |
| **JSONL** | 每行一条 JSON，简单可靠的存储格式 |
| **重放** | 从 JSONL 重建 messages[] |
| **ContextGuard** | 3 阶段溢出保护 |
| **截断** | 截断过大的工具输出 |
| **压缩** | 用 LLM 摘要替换旧消息 |
| **code/session.py** | 会话管理模块，含 SessionStore 和 ContextGuard |
| **Windows 兼容性** | 自动消毒文件名，替换非法字符，确保跨平台运行 |
| **REPL 命令** | /new /switch /list /context /compact /help |

这就是 KunClaw 的**记忆系统**。

在下一章，我们将学习如何让 Agent 接入外部通讯渠道，例如飞书等。

---


