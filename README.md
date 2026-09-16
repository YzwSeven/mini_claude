# mini_claude

最小的编程助手学习项目：用户输入 → 模型请求工具 → 本地执行 → 返回结果 → 模型回答。

## 已实现

- 终端连续对话和内存中的消息历史。
- GPT-5.5 模型调用。
- read_file：读取项目内的 UTF-8 文本文件。
- list_files：按 pattern（例如 **/*.py）查找文件，可选 path，最多返回 200 个。
- grep_search：按正则搜索内容，优先系统 grep，没有则用 Python 遍历目录，最多返回 100 行。
- run_shell：执行命令，返回输出或错误，等待超时为 30 秒。
- write_file：按原教程使用 file_path/content 创建或覆盖 UTF-8 文本文件，自动创建父目录。
- edit_file：按原教程精确替换唯一匹配的原文，找不到或匹配多处时不写入。
- execute_tool：通过名称与函数的映射统一分派工具请求。
- 工具结果截断：超过 50000 字符时保留头尾，并标明中间省略的字符数。
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

工具在本机执行；读取到的文件内容会作为后续模型请求的一部分发送给模型服务。当前六种工具均已接入；写入会覆盖已有文件。run_shell 按原文第一版直接执行命令，尚无审批或沙箱，Windows 通常使用 cmd 语法。write_file 与原文一样以当前工作目录解析相对路径，不额外限制为项目目录。

## 学习参考

本项目跟随 [claude-code-from-scratch](https://github.com/Windy3f3f3f3f/claude-code-from-scratch) 学习 Agent 核心架构，采用 Python 手写逐步实现。

## 当前与原教程的对应关系

write_file 的参数、创建及覆盖行为、行数计算和错误返回与第二章 Python 教学代码一致。工具定义为适配现有 GPT 接口，使用 parameters（原文 Anthropic 使用 input_schema）。read_file 仍是此前教学版本（path 参数、项目内读取），尚未按原文校正。list_files、grep_search、run_shell 已按第二章最初的 Python 实现补齐。list_files 和 grep_search 显式关闭 strict，保留原文 path 可选的含义。

edit_file 当前对应第二章最初的 Python 实现：精确匹配和唯一性检查。尚未添加后文的引号容错、Diff 输出或 mtime 防护。

工具结果截断对应第二章“工具结果截断”：所有已注册工具经过统一入口，短结果原样返回，长结果保留头尾。当前 read_file 仍使用早期教学版的 path 参数，因此分派器中保留了一层参数适配。

## 本次工具阅读与实验

在 tools.py 中先读 TOOL_DEFINITIONS，再读 _list_files、_grep_search / _grep_py、_run_shell，最后读 execute_tool。主循环不需要随工具数量增加而改变。

从项目根目录重新启动 main.py，可依次输入：

```text
请用 list_files 列出当前目录的 *.py 文件。
请用 grep_search 在当前目录搜索 def execute_tool，告诉我文件名和行号。
请用 run_shell 执行 .\.venv\Scripts\python.exe --version，并告诉我实际输出。
```

原文备用搜索使用 os.walk，只支持遍历目录；没有系统 grep 时，请给 path 传目录。glob 是匹配文件名，正则是匹配文件内容，两者语法不同。新工具相对路径基于当前工作目录，请从项目根目录启动。
