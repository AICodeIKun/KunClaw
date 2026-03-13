"""
KunClaw Agent 运行时 - 工具使用 + 会话管理 + 多通道支持
"""

import os
import sys
from pathlib import Path

# 将当前目录加入 path，以便导入同目录模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
from anthropic import Anthropic

from core import (
    TOOLS,
    TOOL_HANDLERS,
    WORKDIR,
    process_tool_call,
    SessionStore,
    ContextGuard,
)
from channels.base import InboundMessage, ChannelAccount
from channels.manager import ChannelManager
from channels import CLIChannel, FeishuChannel


try:
    import importlib.util

    HAS_HTTPX = importlib.util.find_spec("httpx") is not None
except Exception:
    HAS_HTTPX = False

try:
    import importlib.util
    HAS_LARK = importlib.util.find_spec("lark_oapi") is not None
except Exception:
    HAS_LARK = False


load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

MODEL_ID = os.getenv("MODEL_ID", "MiniMax-M2.5")
client = Anthropic(
    api_key=os.getenv("ANTHROPIC_API_KEY"),
    base_url=os.getenv("ANTHROPIC_BASE_URL") or None,
)

SYSTEM_PROMPT = (
    "你的名字是KunClaw，你是一个有用的AI助手，可以访问工具。\n"
    "使用工具帮助用户处理文件操作和Shell命令。\n"
    "编辑文件之前一定要先阅读文件内容。\n"
    "使用 edit_file 时，old_string 必须完全匹配（包括空白字符）。"
)


def build_session_key(channel: str, account_id: str, peer_id: str) -> str:
    return f"code:main:direct:{channel}:{peer_id}"


# ============================================================================
# ANSI 颜色
# ============================================================================

CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"
BOLD = "\033[1m"
MAGENTA = "\033[35m"
BLUE = "\033[34m"


def colored_prompt() -> str:
    return f"{CYAN}{BOLD}你 > {RESET}"


def print_assistant(text: str) -> None:
    print(f"\n{GREEN}{BOLD}助手:{RESET} {text}\n")


def print_info(text: str) -> None:
    print(f"{DIM}{text}{RESET}")


def print_warn(text: str) -> None:
    print(f"{YELLOW}{text}{RESET}")


def print_session(text: str) -> None:
    print(f"{MAGENTA}{text}{RESET}")


def print_channel(text: str) -> None:
    print(f"{BLUE}{text}{RESET}")


# ============================================================================
# REPL 命令处理
# ============================================================================


def handle_command(
    user_input: str,
    session_store: SessionStore,
    context_guard,
    messages,
    mgr: ChannelManager,
) -> tuple[SessionStore | None, list | None, bool]:
    """
    处理命令，返回更新后的session_store和messages
    
    Returns:
        (new_session_store, new_messages, handled)
        - new_session_store: 更新后的会话存储，如果无变化则为None
        - new_messages: 更新后的消息列表，如果无变化则为None
        - handled: 是否处理了命令
    """
    if not user_input.startswith("/"):
        return None, None, False

    parts = user_input.split()
    command = parts[0].lower()

    if command == "/new":
        import time
        new_session_id = f"session_{int(time.time() * 1000)}"
        new_session_store = SessionStore(new_session_id)
        print_session(f"已创建新会话: {new_session_store.session_id}")
        return new_session_store, None, True

    elif command == "/switch":
        if len(parts) < 2:
            print_warn("用法: /switch <会话ID>")
            return None, None, True
        target_id = parts[1]
        sessions = session_store.list_sessions()
        matches = [s for s in sessions if s.startswith(target_id)]
        if len(matches) == 0:
            print_warn(f"未找到会话: {target_id}")
            return None, None, True
        elif len(matches) == 1:
            session_store = SessionStore(matches[0])
            print_session(f"已切换到会话: {matches[0]}")
            return session_store, None, True
        else:
            print_warn(f"多个匹配: {', '.join(matches)}")
            return None, None, True

    elif command == "/list":
        sessions = session_store.list_sessions()
        if not sessions:
            print_info("暂无会话")
        else:
            print_info(f"会话列表 ({len(sessions)} 个):")
            for s in sessions:
                marker = " *" if s == session_store.session_id else ""
                print(f"  - {s}{marker}")
        return None, None, True

    elif command == "/context":
        messages = session_store.load_session()
        total = sum(len(str(m.get("content", ""))) // 4 for m in messages)
        limit = 180000
        percent = min(100, total * 100 // limit)
        bar = "[" + "#" * (percent // 5) + "-" * (20 - percent // 5) + "]"
        print_info(f"Context usage: ~{total:,} / {limit:,} tokens")
        print_info(f"{bar} {percent}%")
        return None, None, True

    elif command == "/compact":
        try:
            compacted = context_guard.compact_history(messages, SYSTEM_PROMPT)
            messages.clear()
            messages.extend(compacted)
            print_session(f"已压缩历史，保留 {len(messages)} 条消息")
        except Exception as e:
            print_warn(f"压缩失败: {e}")
        return None, messages, True

    elif command == "/channels":
        print_info("已注册的通道:")
        for name in mgr.list_channels():
            print_info(f"  - {name}")
        return None, None, True

    elif command == "/accounts":
        print_info("已配置的账号:")
        for acc in mgr.accounts:
            masked = acc.token[:8] + "..." if len(acc.token) > 8 else "(none)"
            print_info(f"  - {acc.channel}/{acc.account_id}  token={masked}")
        return None, None, True

    elif command == "/help":
        print_info("可用命令:")
        print_info("  /new       - 创建新会话")
        print_info("  /switch    - 切换会话")
        print_info("  /list      - 列出所有会话")
        print_info("  /context   - 查看上下文使用")
        print_info("  /compact   - 手动压缩历史")
        print_info("  /channels  - 列出已注册的通道")
        print_info("  /accounts  - 显示 bot 账号")
        print_info("  /help      - 显示帮助")
        return None, None, True

    else:
        print_warn(f"未知命令: {command}")
        return None, None, True


# ============================================================================
# Agent 回合处理
# ============================================================================


def run_agent_turn(
    inbound: InboundMessage,
    conversations: dict,
    mgr: ChannelManager,
) -> None:
    sk = build_session_key(inbound.channel, inbound.account_id, inbound.peer_id)
    if sk not in conversations:
        conversations[sk] = []
    messages = conversations[sk]
    messages.append({"role": "user", "content": inbound.text})

    session_store = SessionStore(sk)
    context_guard = ContextGuard(session_store, client, MODEL_ID)

    while True:
        try:
            response = context_guard.guard_api_call(
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=TOOLS,
            )
        except Exception as exc:
            print(f"\n{YELLOW}API 错误: {exc}{RESET}\n")
            while messages and messages[-1]["role"] != "user":
                messages.pop()
            if messages:
                messages.pop()
            break

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            if text:
                ch = mgr.get(inbound.channel)
                if ch:
                    ch.send(inbound.peer_id, text, is_group=inbound.is_group)
                    # 飞书回复打印到后台
                    if inbound.channel == "feishu":
                        print_info(f"[feishu] 回复已发送: {text}")
                else:
                    print_assistant(text)
            break

        elif response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                result = process_tool_call(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

            messages.append({"role": "user", "content": tool_results})
            continue

        else:
            text = "".join(b.text for b in response.content if hasattr(b, "text"))
            if text:
                ch = mgr.get(inbound.channel)
                if ch:
                    ch.send(inbound.peer_id, text, is_group=inbound.is_group)
                    # 飞书回复打印到后台
                    if inbound.channel == "feishu":
                        print_info(f"[feishu] 回复已发送: {text}")
                else:
                    print_assistant(text)
            break


# ============================================================================
# Agent 主循环
# ============================================================================


def agent_loop() -> None:
    mgr = ChannelManager()

    cli = CLIChannel()
    mgr.register(cli)

    # 飞书消息队列
    feishu_queue = []
    feishu_channel = None
    
    fs_id = os.getenv("FEISHU_APP_ID", "").strip()
    fs_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if fs_id and fs_secret and HAS_LARK and HAS_HTTPX:
        fs_acc = ChannelAccount(
            channel="feishu",
            account_id="feishu-primary",
            config={
                "app_id": fs_id,
                "app_secret": fs_secret,
                "is_lark": os.getenv("FEISHU_DOMAIN", "feishu").lower() == "lark",
            },
        )
        feishu_channel = FeishuChannel(fs_acc, feishu_queue)
        mgr.accounts.append(fs_acc)
        mgr.register(feishu_channel)
        feishu_channel.start_ws()
        print_channel("  [+] Channel registered: feishu")

    session_store = SessionStore()
    context_guard = ContextGuard(session_store, client, MODEL_ID)
    messages = session_store.load_session()

    conversations: dict = {}

    print_info("=" * 60)
    print_info("  KunClaw  |  工具使用 + 会话管理 + 多通道")
    print_info(f"  Model: {MODEL_ID}")
    print_info(f"  Workdir: {WORKDIR}")
    print_info(f"  Session: {session_store.session_id}")
    print_info(f"  Tools: {', '.join(TOOL_HANDLERS.keys())}")
    print_info(f"  Channels: {', '.join(mgr.list_channels())}")
    print_info(f"  Messages loaded: {len(messages)}")
    print_info("")
    print_info("命令说明:")
    print_info("  /new       - 创建新会话")
    print_info("  /switch    - 切换会话 (例: /switch session_123)")
    print_info("  /list      - 列出所有会话")
    print_info("  /context   - 查看上下文使用情况")
    print_info("  /compact   - 手动压缩历史")
    print_info("  /channels  - 列出已注册的通道")
    print_info("  /accounts  - 显示 bot 账号")
    print_info("  /help      - 显示帮助")
    print_info("")
    print_info("输入 'quit' 或 'exit' 退出")
    print_info("=" * 60)
    print()

    # 用 threading 让飞书消息处理在后台运行
    import threading
    import time
    
    processing = [False]  # 防止并发处理
    running = [True]  # 控制线程退出
    
    def process_feishu_queue():
        while running[0]:
            fs_msg = None
            if feishu_channel:
                fs_msg = feishu_channel.receive()
            
            if fs_msg:
                if not processing[0]:
                    processing[0] = True
                    print_channel(f"\n  [feishu] {fs_msg.sender_id}: {fs_msg.text[:80]}")
                    run_agent_turn(fs_msg, conversations, mgr)
                    processing[0] = False
            
            time.sleep(0.1)
    
    # 启动飞书消息处理线程
    if feishu_channel:
        fs_thread = threading.Thread(target=process_feishu_queue, daemon=True)
        fs_thread.start()

    while True:
        # CLI 阻塞等待输入
        msg = cli.receive()
        
        if msg is None:
            print(f"\n{DIM}再见.{RESET}")
            break

        if msg.text.lower() in ("quit", "exit"):
            print(f"{DIM}再见.{RESET}")
            break

        if msg.text.startswith("/"):
            new_session_store, new_messages, handled = handle_command(msg.text, session_store, context_guard, messages, mgr)
            if new_session_store is not None:
                session_store = new_session_store
            if new_messages is not None:
                messages = new_messages
            continue

        run_agent_turn(msg, conversations, mgr)

    # 关闭飞书通道
    running[0] = False
    if feishu_channel:
        feishu_channel.close()


# ============================================================================
# 程序入口
# ============================================================================


def main() -> None:
    if not os.getenv("ANTHROPIC_API_KEY"):
        print(f"{YELLOW}错误: ANTHROPIC_API_KEY 未设置.{RESET}")
        sys.exit(1)

    agent_loop()


if __name__ == "__main__":
    main()
