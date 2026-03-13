"""
KunClaw 会话管理模块

功能：
- SessionStore: JSONL 文件持久化，追加写入，读取重放
- ContextGuard: 3 阶段上下文溢出保护
"""

import json
import time
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

# ============================================================================
# 常量
# ============================================================================

# 工作空间目录 - 基于项目根目录
# session.py 在 code/core/ 下，所以 parent.parent 是项目根目录
WORKSPACE_DIR = Path(__file__).resolve().parent.parent.parent / "workspace"

# 上下文安全上限 - 180K tokens (Claude 3.5/3.7 Sonnet)
CONTEXT_SAFE_LIMIT = 180000


# ============================================================================
# SessionStore: 会话持久化
# ============================================================================
class SessionStore:
    """
    会话存储 - 基于 JSONL 文件

    文件结构：
    workspace/.sessions/{session_id}.jsonl

    四种记录类型：
    - user: 用户消息
    - assistant: 助手回复
    - tool_use: 工具调用
    - tool_result: 工具结果
    """

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """
        消毒文件名，替换 Windows 非法字符

        Windows 非法字符: < > : \" / \\ | ? *
        """
        # Windows 文件名非法字符
        invalid_chars = '<>:\"/\\\\|?*'
        sanitized = name
        for char in invalid_chars:
            sanitized = sanitized.replace(char, '_')
        # 额外替换点号开头的文件（隐藏文件）
        if sanitized.startswith('.'):
            sanitized = '_' + sanitized[1:]
        # 确保文件名不为空
        if not sanitized:
            sanitized = 'default_session'
        return sanitized

    def __init__(self, session_id: str | None = None):
        """
        初始化会话存储

        Args:
            session_id: 会话ID。如果为None，则自动加载最后一个会话
        """
        self.session_dir = WORKSPACE_DIR / ".sessions"
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # 如果没有指定会话 ID，加载最后一个会话
        if session_id is None:
            sessions = self.list_sessions()
            if sessions:
                # 按时间戳排序，取最新的
                sessions.sort()
                session_id = sessions[-1]
            else:
                # 没有会话，创建新的
                session_id = f"session_{int(time.time())}"

        self.session_id = session_id
        # 消毒文件名，替换 Windows 非法字符
        sanitized_id = self.sanitize_filename(session_id)
        self.session_path = self.session_dir / f"{sanitized_id}.jsonl"
        # 确保会话文件存在（即使为空）
        if not self.session_path.exists():
            self.session_path.touch(exist_ok=True)

    def save_turn(self, record: dict) -> None:
        """
        追加一条记录到 JSONL 文件

        追加写入是原子的，不需要重写整个文件
        """
        with open(self.session_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def save_user(self, content: str) -> None:
        """保存用户消息"""
        self.save_turn(
            {
                "type": "user",
                "content": content,
                "ts": datetime.now(timezone.utc).timestamp(),
            }
        )

    def save_assistant(self, content: Any) -> None:
        """
        保存助手消息

        需要将 Anthropic API 返回的 content 对象转换为可 JSON 序列化的格式
        （因为可能包含 ThinkingBlock 等复杂对象）
        """
        # 将 content 转换为可 JSON 序列化的格式
        serializable_content = []
        if isinstance(content, list):
            for block in content:
                if hasattr(block, "type"):
                    block_dict = {"type": block.type}
                    if hasattr(block, "text"):
                        block_dict["text"] = block.text
                    if hasattr(block, "id"):
                        block_dict["id"] = block.id
                    if hasattr(block, "name"):
                        block_dict["name"] = block.name
                    if hasattr(block, "input"):
                        block_dict["input"] = block.input
                    serializable_content.append(block_dict)
                else:
                    serializable_content.append(str(block))
        else:
            serializable_content = str(content)

        self.save_turn(
            {
                "type": "assistant",
                "content": serializable_content,
                "ts": datetime.now(timezone.utc).timestamp(),
            }
        )

    def save_tool_use(self, tool_use_id: str, name: str, input_data: dict) -> None:
        """保存工具调用"""
        self.save_turn(
            {
                "type": "tool_use",
                "tool_use_id": tool_use_id,
                "name": name,
                "input": input_data,
                "ts": datetime.now(timezone.utc).timestamp(),
            }
        )

    def save_tool_result(self, tool_use_id: str, content: str) -> None:
        """保存工具结果"""
        self.save_turn(
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": content,
                "ts": datetime.now(timezone.utc).timestamp(),
            }
        )

    def load_session(self) -> list[dict]:
        """
        从 JSONL 文件重建 messages[]

        将扁平的 JSONL 记录转换回 Anthropic API 格式

        Returns:
            messages 列表，符合 API 格式要求
        """
        if not self.session_path.exists():
            return []

        messages: list[dict] = []

        with open(self.session_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                record = json.loads(line)
                rtype = record.get("type")

                if rtype == "user":
                    messages.append({"role": "user", "content": record["content"]})
                elif rtype == "assistant":
                    content = record["content"]
                    # 如果是字符串，转为文本块
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}]
                    messages.append({"role": "assistant", "content": content})
                elif rtype == "tool_use":
                    # 合并到最后的 assistant 消息
                    block = {
                        "type": "tool_use",
                        "id": record["tool_use_id"],
                        "name": record["name"],
                        "input": record["input"],
                    }
                    if messages and messages[-1]["role"] == "assistant":
                        messages[-1]["content"].append(block)
                    else:
                        messages.append({"role": "assistant", "content": [block]})
                elif rtype == "tool_result":
                    # 合并到最后的 user 消息
                    result_block = {
                        "type": "tool_result",
                        "tool_use_id": record["tool_use_id"],
                        "content": record["content"],
                    }
                    if (
                        messages
                        and messages[-1]["role"] == "user"
                        and isinstance(messages[-1]["content"], list)
                        and messages[-1]["content"]
                        and messages[-1]["content"][0].get("type") == "tool_result"
                    ):
                        messages[-1]["content"].append(result_block)
                    else:
                        messages.append({"role": "user", "content": [result_block]})

        return messages

    def list_sessions(self) -> list[str]:
        """列出所有会话"""
        if not self.session_dir.exists():
            return []
        return [p.stem for p in self.session_dir.glob("*.jsonl")]


# ============================================================================
# ContextGuard: 上下文溢出保护
# ============================================================================


class ContextGuard:
    """
    上下文保护 - 3 阶段溢出重试

    阶段 0: 正常调用
    阶段 1: 截断过大的工具结果
    阶段 2: 压缩历史（LLM 摘要）
    阶段 3: 失败，抛出异常
    """

    def __init__(self, session_store: SessionStore, api_client, model: str):
        """
        初始化上下文保护

        Args:
            session_store: 会话存储实例
            api_client: Anthropic API 客户端
            model: 使用的模型名称
        """
        self.session = session_store
        self.client = api_client
        self.model = model

    def guard_api_call(
        self, system: str, messages: list[dict], tools=None, max_retries: int = 2
    ) -> Any:
        """
        包裹 API 调用的保护函数

        如果上下文溢出，自动尝试恢复策略：
        1. 第一次溢出：截断过大的工具输出
        2. 第二次溢出：用 LLM 压缩历史
        3. 还是溢出：抛出异常

        Args:
            system: 系统提示词
            messages: 消息列表
            tools: 工具定义（可选）
            max_retries: 最大重试次数，默认 2

        Returns:
            API 响应对象
        """
        current_messages = messages

        for attempt in range(max_retries + 1):
            try:
                result = self.client.messages.create(
                    model=self.model,
                    max_tokens=8096,
                    system=system,
                    messages=current_messages,
                    **({"tools": tools} if tools else {}),
                )

                # 如果修改了消息，更新原始列表
                if current_messages is not messages:
                    messages.clear()
                    messages.extend(current_messages)

                return result

            except Exception as exc:
                error_str = str(exc).lower()
                is_overflow = "context" in error_str or "token" in error_str

                # 非溢出错误 或 已达最大重试次数
                if not is_overflow or attempt >= max_retries:
                    raise

                # 阶段 1: 截断过大的工具结果
                if attempt == 0:
                    current_messages = self._truncate_large_tool_results(
                        current_messages
                    )
                # 阶段 2: 压缩历史
                elif attempt == 1:
                    current_messages = self.compact_history(current_messages, system)

    def _truncate_large_tool_results(
        self, messages: list[dict], max_length: int = 10000
    ) -> list[dict]:
        """
        截断过大的工具结果

        Args:
            messages: 消息列表
            max_length: 单个工具结果的最大长度，默认 10000 字符

        Returns:
            截断后的消息列表
        """
        truncated = []

        for msg in messages:
            if msg.get("role") == "user" and isinstance(msg.get("content"), list):
                new_content = []
                for block in msg["content"]:
                    if block.get("type") == "tool_result":
                        content = block.get("content", "")
                        if len(content) > max_length:
                            content = (
                                content[:max_length]
                                + f"\n... [截断，共 {len(content)} 字符]"
                            )
                        block = block.copy()
                        block["content"] = content
                    new_content.append(block)
                truncated.append({**msg, "content": new_content})
            else:
                truncated.append(msg)

        return truncated

    def compact_history(self, messages: list[dict], system: str) -> list[dict]:
        """
        压缩历史 - 用 LLM 生成摘要替换旧消息

        保留最近 20% 的消息，对最早的 50% 进行摘要

        Args:
            messages: 消息列表
            system: 系统提示词

        Returns:
            压缩后的消息列表
        """
        if len(messages) <= 4:
            # 消息太少，不压缩，直接返回
            return messages

        # 计算保留和压缩的数量
        keep_count = max(4, int(len(messages) * 0.2))
        compress_count = max(2, int(len(messages) * 0.5))
        compress_count = min(compress_count, len(messages) - keep_count)

        # 序列化要压缩的消息
        old_messages = messages[:compress_count]
        old_text = self._serialize_for_summary(old_messages)

        # 让 LLM 生成摘要
        summary_prompt = f"""请简洁地总结以下对话，保留关键信息：

{old_text}

请直接输出摘要："""

        summary_resp = self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system="你是一个对话摘要助手。",
            messages=[{"role": "user", "content": summary_prompt}],
        )

        # 提取摘要
        summary = ""
        for block in summary_resp.content:
            if hasattr(block, "text"):
                summary += block.text
        summary = summary.strip()

        # 用摘要 + 确认回复替换旧消息
        compacted = [
            {"role": "user", "content": f"[之前对话摘要]\n{summary}"},
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "明白了，我会记住这些上下文。"}],
            },
        ]
        compacted.extend(messages[compress_count:])

        return compacted

    def _serialize_for_summary(self, messages: list[dict]) -> str:
        """
        将消息序列化为纯文本（用于摘要）

        Args:
            messages: 消息列表

        Returns:
            格式化的文本字符串
        """
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")

            if isinstance(content, str):
                lines.append(f"{role}: {content}")
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        lines.append(f"{role}: {block.get('text', '')}")
                    elif block.get("type") == "tool_use":
                        lines.append(f"{role} 调用工具: {block.get('name')}")
                    elif block.get("type") == "tool_result":
                        result = block.get("content", "")
                        if len(result) > 200:
                            result = result[:200] + "..."
                        lines.append(f"工具结果: {result}")

        return "\n".join(lines)

    def count_tokens(self, text: str) -> int:
        """
        估算 token 数量

        简单启发式：每 4 个字符约等于 1 个 token

        Args:
            text: 文本字符串

        Returns:
            估算的 token 数量
        """
        return len(text) // 4

    def get_context_usage(self, messages: list[dict]) -> tuple[int, int]:
        """
        获取上下文使用情况

        Args:
            messages: 消息列表

        Returns:
            (已用 token 数, 上限)
        """
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += self.count_tokens(content)
            elif isinstance(content, list):
                for block in content:
                    total += self.count_tokens(str(block.get("content", "")))

        return total, CONTEXT_SAFE_LIMIT
