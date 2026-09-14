# mini_claude

最小的编程助手学习项目：用户输入 → 模型请求工具 → 本地执行 → 返回结果 → 模型回答。

## 已实现

- 终端连续对话和内存中的消息历史。
- GPT-5.5 模型调用。
- read_file：读取项目内的 UTF-8 文本文件。
- execute_tool：统一分派工具请求。
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

工具在本机执行；读取到的文件内容会作为后续模型请求的一部分发送给模型服务。当前只支持 read_file，尚未实现列目录、写文件或命令执行工具。

## 学习参考

本项目跟随 [claude-code-from-scratch](https://github.com/Windy3f3f3f3f/claude-code-from-scratch) 学习 Agent 核心架构，采用 Python 手写逐步实现。
