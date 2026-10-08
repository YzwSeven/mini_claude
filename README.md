# mini_claude

最小的编程助手学习项目：用户输入 → 模型请求工具 → 本地执行 → 返回结果 → 模型回答。

## 已实现

- 终端连续对话和内存中的消息历史。
- GPT-5.5 模型调用。
- read_file：读取 UTF-8 文本文件并显示行号，同时记录读取时的文件修改时间。
- list_files：按 pattern（例如 **/*.py）查找文件，可选 path，最多返回 200 个。
- grep_search：按正则搜索内容，优先系统 grep，没有则用 Python 遍历目录，最多返回 100 行。
- run_shell：执行命令，返回输出或错误，等待超时为 30 秒。
- web_fetch：读取 HTTP/HTTPS 内容，HTML 会转成纯文本，默认最多返回 50000 字符。
- write_file：按原教程使用 file_path/content 创建或覆盖 UTF-8 文本文件，自动创建父目录。
- edit_file：按原教程精确替换唯一匹配的原文，找不到或匹配多处时不写入。
- execute_tool：通过名称与函数的映射统一分派工具请求。
- 工具结果截断：超过 50000 字符时保留头尾，并标明中间省略的字符数。
- Read-before-edit：已有文件必须先读取；读取后被外部修改时，必须重新读取。
- tool_search：按名称或描述搜索并激活延迟工具，下一次模型请求才发送其完整定义。
- 单次任务最多请求模型 10 次。

## 运行

需要 Python 3.11+，代码仅使用标准库。先通过官方 Codex CLI 使用 ChatGPT 账户登录：

```powershell
codex login
python -m venv .venv
.\.venv\Scripts\python.exe main.py
```

在项目根目录运行，输入：

```text
请读取 hello.txt，并总结内容。
```

输入 exit 退出。对话历史仅保存在内存中。

## 阅读顺序

1. main.py：用户交互、Agent 循环、工具结果回传。
2. codex_backend.py：模型参数、提示词和工具说明。
3. tools.py：工具实现和统一执行入口。
4. codex_transport.py：本机登录读取、HTTP 请求、流式事件解析。

## 模型连接说明

目前使用 Codex 公开客户端对应后端协议的实验性接入，使用现有账户额度，并非公开 API Key 接口。协议更新可能导致需要调整代码。

程序从 CODEX_HOME（未设置时为用户目录下的 .codex）读取已有 auth.json。请勿把登录令牌或该文件提交到仓库。认证失败时重新使用 codex login 登录。

工具在本机执行；读取到的文件和网页内容会作为后续模型请求的一部分发送给模型服务。当前八种工具均已接入；写入会覆盖已有文件。run_shell 按原文第一版直接执行命令，尚无审批或沙箱，Windows 通常使用 cmd 语法。write_file 与原文一样以当前工作目录解析相对路径，不额外限制为项目目录。

## 学习参考

本项目跟随 [claude-code-from-scratch](https://github.com/Windy3f3f3f3f/claude-code-from-scratch) 学习 Agent 核心架构，采用 Python 手写逐步实现。

## 当前与原教程的对应关系

write_file 的参数、创建及覆盖行为、行数计算和错误返回与第二章 Python 教学代码一致。工具定义为适配现有 GPT 接口，使用 parameters（原文 Anthropic 使用 input_schema）。read_file 已改用原文的 file_path 参数并返回行号。list_files、grep_search、run_shell 已按第二章最初的 Python 实现补齐。list_files 和 grep_search 显式关闭 strict，保留原文 path 可选的含义。

edit_file 当前对应第二章最初的精确匹配和唯一性检查，并已接入本节的 Read-before-edit 与 mtime 防护。后续的引号容错和 Diff 输出尚未添加。

工具结果截断对应第二章“工具结果截断”：所有已注册工具经过统一入口，短结果原样返回，长结果保留头尾。

read_file 已对齐原教程的 file_path 参数，并为返回内容添加行号。Agent 在整个运行期间保存绝对路径及读取时的 mtime；写入或编辑已有文件前必须有读取记录且 mtime 未变化。新文件可以直接创建，成功写入或编辑后会更新记录。

web_fetch 对应第二章“WebFetch 工具”。章节展示 TypeScript 代码，本项目使用原仓库 Python 版的标准库 urllib 实现，不需要安装额外依赖。工具只接受 HTTP/HTTPS，等待超时为 30 秒；HTML 会删除 script、style 和标签，网络错误会作为结果返回模型。

ToolSearch 对应第二章“ToolSearch 延迟加载”。普通工具始终发送完整定义；带 deferred 标记的工具在激活前只通过提示词公开名称。tool_search 匹配名称或描述并记录激活状态，下一次请求才发送完整定义，同时从发送副本中删除本地 deferred 字段。当前章节尚无真正的延迟工具；第十章实现 Plan Mode 后才会把计划工具标记为 deferred。

System Prompt 对应第三章。`prompt.py` 把不会随会话改变的身份、行为规则和工具偏好放在静态核心中，再在运行时追加当前目录、操作系统、Shell 和 Git 分支。`codex_backend.py` 调用 `build_system_prompt()`，并把结果映射到 GPT/Codex Responses 请求的 `instructions` 字段。

项目规则读取器会从当前目录向上查找 `CLAUDE.md`，解析其中单独成行的 `@./路径`、`@~/路径` 和 `@/绝对路径` 引用，并加载当前目录下按文件名排序的 `.claude/rules/*.md`。引用最多递归 5 层，并使用已访问路径集合阻止循环引用。会话启动时，`build_user_context_reminder()` 将项目规则和日期包装为 `<system-reminder>`，由 `main.py` 拼到首条用户消息前面；后续通过历史保留，不重复添加。规则更新后重新启动程序即可加载。

## 测试 WebFetch

先在第一个 PowerShell 窗口进入项目目录，启动只供本机访问的临时 HTTP 服务：

```powershell
.\.venv\Scripts\python.exe -m http.server 8000 --bind 127.0.0.1
```

保持它运行，再打开第二个 PowerShell 窗口进入项目目录。可以先绕过模型，直接测试工具：

```powershell
.\.venv\Scripts\python.exe -c "from tools import execute_tool; print(execute_tool('web_fetch', {'url': 'http://127.0.0.1:8000/README.md', 'max_length': 500}))"
```

看到 README 开头以及截断提示后，再启动完整 Agent：

```powershell
.\.venv\Scripts\python.exe main.py
```

输入：

```text
请使用 web_fetch 读取 http://127.0.0.1:8000/README.md，告诉我这个项目已经实现了哪些工具。
```

测试结束后，在第一个窗口按 `Ctrl+C` 停止临时 HTTP 服务。

## 本次工具阅读与实验

在 tools.py 中先读 TOOL_DEFINITIONS，再读 _list_files、_grep_search / _grep_py、_run_shell，最后读 execute_tool。主循环不需要随工具数量增加而改变。

从项目根目录重新启动 main.py，可依次输入：

```text
请用 list_files 列出当前目录的 *.py 文件。
请用 grep_search 在当前目录搜索 def execute_tool，告诉我文件名和行号。
请用 run_shell 执行 .\.venv\Scripts\python.exe --version，并告诉我实际输出。
```

原文备用搜索使用 os.walk，只支持遍历目录；没有系统 grep 时，请给 path 传目录。glob 是匹配文件名，正则是匹配文件内容，两者语法不同。新工具相对路径基于当前工作目录，请从项目根目录启动。
