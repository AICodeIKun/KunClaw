# 🦞 KunClaw

> **OpenClaw的核心功能极简实现**

KunClaw 是**OpenClaw的众多小弟之一**，目标是用尽可能易于理解的方式实现OpenClaw的核心功能，我们将一步步实现、组装小龙虾，相信学习最好的方法就是实践。

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.13+-green.svg)](pyproject.toml)

---

## ✨ 核心特性

### 🧠 **大脑** - Agent 循环
- 基于 LLM 的多轮对话引擎
- 支持 Anthropic API 及兼容提供商（OpenRouter、MiniMax 等）
- 工具调用与结果反馈的完整循环

### 🦞 **钳子** - 4 个核心工具
| 工具 | 功能 | 用途 |
|------|------|------|
| `exec` | 执行 shell 命令 | 系统操作、包管理、Git 等 |
| `read_file` | 读取文件内容 | 查看代码、配置、日志 |
| `write_file` | 写入/创建文件 | 生成代码、配置文件 |
| `edit_file` | 精确编辑文件 | 修改代码、修复 bug |

**最小完备集**：这四个工具构成了文件操作和命令执行的完整闭环。

### 🧠 **记忆** - 会话管理
- **JSONL 持久化**：重启不丢失对话历史
- **智能压缩**：当对话过长时，用 LLM 生成摘要保留关键信息
- **3 阶段溢出保护**：截断工具结果 → 压缩历史 → 优雅降级
- **Windows 兼容**：自动消毒文件名，支持跨平台运行

### 🦗 **触角** - 多通道支持
| 通道 | 特点 | 状态 |
|------|------|------|
| **CLI** | 命令行交互，`input()`/`print()` 实现 | ✅ 稳定 |
| **飞书/Lark** | WebSocket 实时推送，官方 SDK | ✅ 可选 |
| **插件架构** | 新通道只需实现 `Channel` 接口 | 🔧 扩展 |

**统一消息入口**：所有外部平台都通过 `InboundMessage` 转换为内部格式。

---

## 🚀 快速开始

### 1. 安装依赖
```bash
cd code
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. 配置环境变量
复制 `.env.example` 为 `.env` 并填写你的 API 密钥：
```bash
cp .env.example .env
# 编辑 .env 文件，填入 ANTHROPIC_API_KEY 等
```

### 3. 运行 Agent
```bash
python agent_runtime.py
```

启动后你会看到：
```
============================================================
  KunClaw  |  工具使用 + 会话管理 + 多通道
  Model: MiniMax-M2.5
  Workdir: D:\KunClaw\agent
  Session: session_1773334198
  Tools: exec, read_file, write_file, edit_file
  Channels: cli, feishu

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
```

---

## 📖 详细文档

| 章节 | 主题 | 核心内容 |
|------|------|----------|
| [第一章](docs/chapter1.md) | 龙虾的大脑和钳子 | Agent 循环 + 4 个核心工具 |
| [第二章](docs/chapter2.md) | 龙虾的记忆 | 会话持久化 + 上下文压缩 |
| [第三章](docs/chapter3.md) | 龙虾的触角 | 通道架构 + CLI/飞书实现 |

### 设计哲学
1. **极简主义**：只实现最小必要功能，避免过度工程
2. **自托管优先**：除了 API 调用，所有数据留在本地
3. **透明可解释**：每行代码都可理解、可修改
4. **组合性力量**：通过工具组合完成复杂任务

### 安全架构
- **路径安全**：所有文件操作限制在工作目录内，防止路径穿越
- **命令安全**：拒绝 `rm -rf /` 等危险命令
- **输出截断**：防止超大输出撑爆 LLM 上下文
- **原子操作**：文件写入和编辑保证一致性

---

## 🔧 进阶配置

### 飞书/Lark 通道（可选）
1. 在飞书开放平台创建应用，获取 `app_id` 和 `app_secret`
2. 在 `.env` 中配置：
   ```
   FEISHU_APP_ID=cli_xxxxxxxx
   FEISHU_APP_SECRET=xxxxxxxx
   FEISHU_DOMAIN=feishu  # 国内用 feishu，国际用 lark
   ```
3. 安装可选依赖：
   ```bash
   pip install ".[feishu]"
   ```
4. 重启 Agent，飞书通道将自动注册

### 自定义 LLM 提供商
支持任何 Anthropic API 兼容的提供商：
```bash
ANTHROPIC_API_KEY=your_api_key
ANTHROPIC_BASE_URL=https://api.your-provider.com/anthropic
MODEL_ID=claude-3-5-sonnet-20241022
```

---

## 🛠️ 开发指南

### 项目结构
```
code/
├── agent_runtime.py          # 主入口
├── core/
│   ├── tools.py             # 4个核心工具实现
│   └── session.py           # 会话管理（JSONL持久化+压缩）
└── channels/
    ├── base.py              # Channel抽象基类
    ├── cli.py               # CLI通道
    ├── feishu.py            # 飞书通道（WebSocket）
    └── manager.py           # 通道管理器
```

### 添加新通道
1. 继承 `Channel` 类，实现 `receive()` 和 `send()` 方法
2. 在 `agent_runtime.py` 中注册
3. 通道自动获得会话隔离、错误边界等所有基础设施

### 运行测试
```bash
# 单元测试
python -m pytest zh/*.py

# 集成测试
python test_integration.py
```

---

## 🤝 贡献指南

1. Fork 本仓库
2. 创建特性分支：`git checkout -b feature/your-feature`
3. 提交更改：`git commit -m 'Add some feature'`
4. 推送到分支：`git push origin feature/your-feature`
5. 提交 Pull Request

### 开发依赖
```bash
pip install ".[dev]"
```

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

KunClaw 的设计受到以下项目启发：
- **OpenClaw**：工具调用和编辑逻辑
- **LangChain**：Agent 概念
- **AutoGPT**：自主任务执行

> "如果龙虾能思考，它还需要钳子来改造世界。"
> — KunClaw 哲学

---

**立即开始**：[阅读第一章文档](docs/chapter1.md) | [查看代码示例](code/agent_runtime.py) | [报告问题](https://github.com/AICodeIKun/KunClaw/issues)
