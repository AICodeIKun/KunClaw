"""
KunClaw 工具模块

包含所有 Agent 工具的实现：
- bash: 执行 shell 命令
- read_file: 读取文件内容
- write_file: 写入文件
- edit_file: 精确替换文件中的文本
"""

import subprocess
from pathlib import Path
from typing import Any

# ============================================================================
# 常量
# ============================================================================

# 工具输出最大字符数 -- 防止超大输出撑爆上下文
MAX_TOOL_OUTPUT = 50000

# 工作目录 -- 所有文件操作相对于此目录, 防止路径穿越
WORKDIR = Path.cwd()

# ANSI 颜色
DIM = "\033[2m"
RESET = "\033[0m"


# ============================================================================
# 辅助函数
# ============================================================================


def print_tool(name: str, detail: str) -> None:
    """打印工具调用信息."""
    print(f"  {DIM}[tool: {name}] {detail}{RESET}")


def safe_path(raw: str) -> Path:
    """
    将用户/模型传入的路径解析为安全的绝对路径.
    防止路径穿越: 最终路径必须在 WORKDIR 之下.
    """
    target = (WORKDIR / raw).resolve()
    if not str(target).startswith(str(WORKDIR)):
        raise ValueError(f"路径穿越被阻止: {raw} 超出 WORKDIR 范围")
    return target


def truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    """截断过长的输出, 并附上提示."""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [已截断，共 {len(text)} 字符]"


# ============================================================================
# 工具实现
# ============================================================================
# 每个工具函数接收关键字参数 (和 schema 中的 properties 对应),
# 返回字符串结果. 错误通过返回 "Error: ..." 传递给模型.
# ============================================================================


def tool_bash(command: str, timeout: int = 30) -> str:
    """执行 shell 命令并返回输出."""
    # 基础安全检查: 拒绝明显危险的命令
    dangerous = ["rm -rf /", "mkfs", "> /dev/sd", "dd if="]
    for pattern in dangerous:
        if pattern in command:
            return f"错误: 拒绝执行危险命令，包含 '{pattern}'"

    print_tool("bash", command)
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKDIR),
        )
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            output += (
                ("\n--- stderr ---\n" + result.stderr) if output else result.stderr
            )
        if result.returncode != 0:
            output += f"\n[exit code: {result.returncode}]"
        return truncate(output) if output else "[无输出]"
    except subprocess.TimeoutExpired:
        return f"错误: 命令超时 {timeout} 秒"
    except Exception as exc:
        return f"错误: {exc}"


def tool_read_file(file_path: str) -> str:
    """读取文件内容."""
    print_tool("read_file", file_path)
    try:
        target = safe_path(file_path)
        if not target.exists():
            return f"错误: 文件未找到: {file_path}"
        if not target.is_file():
            return f"错误: 不是文件: {file_path}"
        content = target.read_text(encoding="utf-8")
        return truncate(content)
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"错误: {exc}"


def tool_write_file(file_path: str, content: str) -> str:
    """写入内容到文件. 父目录不存在时自动创建."""
    print_tool("write_file", file_path)
    try:
        target = safe_path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"成功写入 {len(content)} 字符到 {file_path}"
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"错误: {exc}"


def tool_edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """
    精确替换文件中的文本.
    old_string 必须在文件中恰好出现一次, 否则报错.
    这和 OpenClaw 的 edit 工具逻辑一致.
    """
    print_tool("edit_file", f"{file_path} (replace {len(old_string)} chars)")
    try:
        target = safe_path(file_path)
        if not target.exists():
            return f"错误: 文件未找到: {file_path}"

        content = target.read_text(encoding="utf-8")
        count = content.count(old_string)

        if count == 0:
            return "错误: 文件中未找到 old_string，请确保完全匹配。"
        if count > 1:
            return f"错误: old_string 找到 {count} 次。必须唯一，请提供更多上下文。"

        new_content = content.replace(old_string, new_string, 1)
        target.write_text(new_content, encoding="utf-8")
        return f"成功编辑 {file_path}"
    except ValueError as exc:
        return str(exc)
    except Exception as exc:
        return f"错误: {exc}"


# ============================================================================
# 工具定义: Schema (传给 API) + Handler 调度表
# ============================================================================

TOOLS = [
    {
        "name": "bash",
        "description": ("执行 shell 命令并返回输出。适用于系统命令、git、包管理器等。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的 shell 命令。",
                },
                "timeout": {
                    "type": "integer",
                    "description": "超时时间（秒）。默认 30。",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "read_file",
        "description": "读取文件内容。",
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径（相对于工作目录）。",
                },
            },
            "required": ["file_path"],
        },
    },
    {
        "name": "write_file",
        "description": ("写入内容到文件。父目录不存在时自动创建。会覆盖已有内容。"),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径（相对于工作目录）。",
                },
                "content": {
                    "type": "string",
                    "description": "要写入的内容。",
                },
            },
            "required": ["file_path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "精确替换文件中的字符串为新字符串。"
            "old_string 必须在文件中恰好出现一次。"
            "编辑前请先读取文件以获取准确的文本。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "文件路径（相对于工作目录）。",
                },
                "old_string": {
                    "type": "string",
                    "description": "要查找并替换的精确文本。必须唯一。",
                },
                "new_string": {
                    "type": "string",
                    "description": "替换后的文本。",
                },
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    },
]

# 调度表: 工具名 -> 处理函数
TOOL_HANDLERS: dict[str, Any] = {
    "bash": tool_bash,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
}


# ============================================================================
# 工具调用处理
# ============================================================================


def process_tool_call(tool_name: str, tool_input: dict) -> str:
    """
    根据工具名分发到对应的处理函数.
    这就是整个 "code" 的核心调度逻辑.
    """
    handler = TOOL_HANDLERS.get(tool_name)
    if handler is None:
        return f"错误: 未知工具 '{tool_name}'"
    try:
        return handler(**tool_input)
    except TypeError as exc:
        return f"错误: {tool_name} 参数无效: {exc}"
    except Exception as exc:
        return f"错误: {tool_name} 执行失败: {exc}"
