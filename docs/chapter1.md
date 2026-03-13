# 第一章：龙虾的大脑和钳子

> "如果龙虾能思考，它还需要钳子来改造世界。"
> 
> — KunClaw 哲学


## 概述：让龙虾能开始干活

在这一章，我们将为龙虾（我们的 Agent）装上两样东西：
1. **大脑** — Agent 循环，让它能思考和对话
2. **钳子** — 4 个核心工具，让它能操作世界


## 1. KunClaw极简设计哲学

KunClaw 是一个极简的 Agent 框架，采用了**最小必要功能**的设计原则：

### 1.1 Agent Runtime：从 Chatbot 到协作伙伴

| 维度 | 传统 Chatbot | KunClaw (Agent Runtime) |
|------|-------------|------------------------|
| **状态管理** | 无状态，每次从零开始 | 有状态，维护完整的 `messages[]` 对话历史 |
| **交互模式** | 一问一答 | 多轮协作，可中断可干预 |
| **能力边界** | 只能输出文本 | 可以操作文件、执行命令、修改代码 |
| **时间感知** | 即时响应 | 支持连续任务执行和工具链调用 |

### 1.2 四个核心工具：最小完备集

为什么是 `bash`、`read_file`、`write_file`、`edit_file` 这四个？

1. **最小完备集**：这四个工具构成了文件操作和命令执行的完整闭环
2. **组合性力量**：通过工具组合可以完成复杂任务，例如：
   ```
   查找文件 → 读取内容 → 搜索关键词 → 生成报告
   bash(find)    read_file     bash(grep)    调用LLM
   ```
3. **LLM友好性**：每个工具功能明确，降低模型选择的认知负荷

### 1.3 自托管优先：掌控你的数据

KunClaw 设计为**本地优先**的 Agent 框架：
- **数据主权**：除了调用 LLM API 必须发送的内容，所有数据留在你的设备上
- **离线能力**：拔掉网线依然可以操作本地文件、执行预设任务
- **可修改性**：Python 代码清晰易懂，你可以按需调整任何部分

这种设计让 KunClaw 成为一个**可以被信任的基础设施**，而不是一个黑盒外部服务。





## 代码结构

```
code/
├── agent_runtime.py  # 主入口
└── tools.py         # 工具模块
    ├── tool_bash()       # 执行 shell 命令
    ├── tool_read_file()  # 读取文件
    ├── tool_write_file() # 写入文件
    ├── tool_edit_file()  # 编辑文件
    ├── TOOLS             # 工具定义（告诉模型有哪些工具）
    ├── TOOL_HANDLERS     # 调度表（工具名 → 函数）
    └── process_tool_call() # 工具调用处理
```

---

## 第一部分：大脑 — Agent 循环

### 什么是 Agent 循环？

Agent 循环是 Agent 的"大脑"，它的核心逻辑非常简单：

```
用户输入 --> 发送给 LLM --> LLM 响应 --> 检查 stop_reason
                                                      |
                                    +-----------------+-----------------+
                                    |                                 |
                              "end_turn"                       "tool_use"
                                    |                                 |
                                打印回复                        执行工具（第二部分）
                                    |                                 |
                                    +-----------------+-----------------+
                                                      |
                                              回到循环开始
```

**就这么简单。** 整个 Agent 系统就是一个 `while True` 加上一个 `stop_reason` 判断。

### 核心概念

#### 1. messages[] — 记忆

`messages` 是一个列表，存储了完整的对话历史：

```python
messages = [
    {"role": "user", "content": "法国的首都是什么？"},
    {"role": "assistant", "content": "法国的首都是巴黎。"},
    {"role": "user", "content": "它的人口是多少？"},
]
```

每次调用 LLM API 时，我们把整个 `messages[]` 发送过去。这样模型就能"记住"之前的对话内容。

#### 2. stop_reason — 决策点

每次 LLM 响应后，会返回一个 `stop_reason`，告诉 Agent 下一步该做什么：

| stop_reason | 含义 | 动作 |
|-------------|------|------|
| `end_turn` | 模型完成了回复 | 打印文本，继续等待输入 |
| `tool_use` | 模型想调用工具 | 执行工具，将结果反馈给模型 |
| `max_tokens` | 回复被 token 限制截断 | 打印部分文本 |

### 代码实现

```python
def agent_loop():
    messages = []  # 对话历史
    
    while True:
        # 1. 获取用户输入
        user_input = input("你 > ").strip()
        if user_input.lower() in ("quit", "exit"):
            break
            
        # 2. 追加用户消息
        messages.append({"role": "user", "content": user_input})
        
        # 3. 调用 LLM
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=8096,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        
        # 4. 根据 stop_reason 分支处理
        if response.stop_reason == "end_turn":
            # 提取并打印回复
            assistant_text = ""
            for block in response.content:
                if hasattr(block, "text"):
                    assistant_text += block.text
            print(f"助手: {assistant_text}")
            
            # 追加助手回复到历史
            messages.append({"role": "assistant", "content": response.content})
```

### 关键要点

1. **messages[] 是唯一的状态** — 所有的对话上下文都在这个列表里
2. **stop_reason 是唯一需要判断的东西** — 所有的逻辑分支都基于这个值
3. **循环结构永远不变** — 后续章节（工具、会话、路由）都是在这个循环上叠加功能

---

## 第二部分：钳子 — 4 个核心工具

### 什么是工具？

如果只有大脑，Agent 只能"说"不能"做"。给它装上钳子，它才能真正改变世界。

工具的工作流程：

```
LLM --> "我想读取文件" --> stop_reason = "tool_use"
                                      |
                              调度表查找函数
                                      |
                          tool_read_file("config.json")
                                      |
                              返回文件内容给 LLM
                                      |
                              继续循环，LLM 看到结果
```

### 4 个核心工具

#### 1. bash — 执行 Shell 命令

让 Agent 能运行系统命令。

```python
def tool_bash(command: str, timeout: int = 30) -> str:
    """执行 shell 命令并返回输出."""
```

**用途**：安装包、运行 git、编译代码、执行脚本。

**示例**：
- `bash("git status")` → 查看 Git 状态
- `bash("pip install requests")` → 安装 Python 包
- `bash("ls -la")` → 列出文件

**安全检查**：会自动拒绝危险命令，如 `rm -rf /`。

#### 2. read_file — 读取文件

让 Agent 能查看文件内容。

```python
def tool_read_file(file_path: str) -> str:
    """读取文件内容."""
```

**用途**：查看代码、配置文件、日志等。

**示例**：
- `read_file("main.py")` → 读取 main.py 内容
- `read_file("config/settings.json")` → 读取嵌套路径的文件

#### 3. write_file — 写入文件

让 Agent 能创建或覆盖文件。

```python
def tool_write_file(file_path: str, content: str) -> str:
    """写入内容到文件. 父目录不存在时自动创建."""
```

**用途**：生成代码、创建配置文件、写日志。

**示例**：
- `write_file("hello.txt", "Hello World")` → 创建 hello.txt

#### 4. edit_file — 精确编辑

这是最重要的工具 — 允许 Agent 精确修改文件的一部分。

```python
def tool_edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """精确替换文件中的文本."""
```

**用途**：修改代码、修复 bug、调整配置。

**示例**：
```python
# 把 "Hello World" 改成 "Hello KunClaw"
edit_file("hello.txt", "Hello World", "Hello KunClaw")
```

**规则**：
- `old_string` 必须在文件中恰好出现一次
- 必须完全匹配（包括空格和换行）
- 建议先 `read_file` 再编辑，确保文本准确

### 工具调度表

工具通过调度表（TOOL_HANDLERS）连接到代码：

```python
TOOL_HANDLERS = {
    "bash": tool_bash,
    "read_file": tool_read_file,
    "write_file": tool_write_file,
    "edit_file": tool_edit_file,
}
```

当 LLM 返回 `tool_use` 时：
1. 从 `response.content` 提取工具名和参数
2. 从调度表查找对应的处理函数
3. 执行函数，获取返回结果
4. 将结果作为 `tool_result` 追加到 messages
5. 继续循环，LLM 看到工具结果

### 带工具的 Agent 循环

```python
def agent_loop():
    messages = []
    
    while True:
        user_input = input("你 > ").strip()
        messages.append({"role": "user", "content": user_input})
        
        # 内层循环：处理连续工具调用
        while True:
            response = client.messages.create(
                model=MODEL_ID,
                max_tokens=8096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,  # 告诉模型有哪些工具可用
                messages=messages,
            )
            
            messages.append({"role": "assistant", "content": response.content})
            
            if response.stop_reason == "end_turn":
                # 打印回复
                print_assistant(response.content)
                break
                
            elif response.stop_reason == "tool_use":
                # 执行工具
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        result = process_tool_call(block.name, block.input)
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                        })
                
                # 将工具结果反馈给 LLM
                messages.append({"role": "user", "content": tool_results})
                # 继续循环，LLM 会看到工具结果
```

### 工具安全

为防止 Agent 搞破坏，我们加了多层保护：

### 1. 路径安全 — 防止目录穿越
```python
def safe_path(raw: str) -> Path:
    """将用户/模型传入的路径解析为安全的绝对路径."""
    target = (WORKDIR / raw).resolve()
    if not str(target).startswith(str(WORKDIR)):
        raise ValueError(f"路径穿越被阻止: {raw} 超出 WORKDIR 范围")
    return target
```
- 所有文件操作相对于 `WORKDIR` 目录
- 自动解析 `.`、`..`、符号链接等
- 确保最终路径在 `WORKDIR` 之下，防止 `../../../etc/passwd` 攻击

### 2. 命令安全 — 拒绝危险操作
```python
dangerous = ["rm -rf /", "mkfs", "> /dev/sd", "dd if="]
for pattern in dangerous:
    if pattern in command:
        return f"错误: 拒绝执行危险命令，包含 '{pattern}'"
```
- 基础模式匹配拒绝明显危险的命令
- 默认 30 秒超时，防止命令卡死
- 执行失败时返回错误信息给 LLM，而非崩溃

### 3. 输出截断 — 保护上下文窗口
```python
MAX_TOOL_OUTPUT = 50000
def truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [已截断，共 {len(text)} 字符]"
```
- 防止 `cat huge_log.log` 撑爆 LLM 上下文
- 保留前 50,000 字符，添加截断提示
- LLM 可请求分段读取大文件

### 4. 原子性与一致性
- **write_file**：自动创建父目录 (`mkdir -p`)，原子写入
- **edit_file**：严格唯一匹配检查，防止误改多处
- **错误处理**：统一返回 `"错误: ..."` 格式，让 LLM 理解问题

### 5. 工具描述工程
在 `TOOLS` 列表中，每个工具都有详细的 `description` 和 `input_schema`：
```python
{"name": "bash", "description": "执行 shell 命令并返回输出。适用于系统命令、git、包管理器等。", ...}
```
- 清晰的描述帮助 LLM 准确选择工具
- 结构化参数定义确保调用格式正确
- 这是 **LLM 与工具系统** 的唯一接口

---

## 总结

在这一章，我们学会了：

| 概念 | 描述 |
|------|------|
| **设计哲学** | Agent Runtime vs Chatbot，极简主义，自托管优先 |
| **Agent 循环** | while True + stop_reason 的基本架构 |
| **messages[]** | 对话历史，LLM 的记忆 |
| **stop_reason** | 决策点：end_turn / tool_use / 其他 |
| **4 个工具** | bash / read_file / write_file / edit_file 的最小完备集 |
| **工具调度** | TOOL_HANDLERS 调度表，process_tool_call 统一分发 |
| **安全架构** | 路径安全、命令安全、输出截断、原子性操作 |
| **代码结构** | code/tools.py（工具）+ code/agent_runtime.py（主入口） |

这就是 KunClaw 的**大脑和钳子**。

在下一章，我们将学习如何让 Agent 记住更多东西 — 会话管理。
