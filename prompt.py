"""构造每次请求模型时使用的系统提示词。"""

import os
import platform
import subprocess


# 静态核心只保存不会随着机器、目录或会话变化的内容。
# 这一部分每次生成都完全相同，后面的上下文缓存章节会利用这个特点。
STATIC_CORE = """你是 Mini Claude Code，一个小型的命令行编程助手。
你使用现有工具帮助用户完成软件工程任务，并使用中文回答。

# 完成任务
 - 不要对尚未读取的代码提出修改方案，必须先读取文件。
 - 没有必要时不要创建新文件，优先编辑已有文件。
 - 避免过度设计，只完成用户要求的修改。

# 谨慎执行操作
 - 优先执行可以撤销的操作。执行高风险或破坏性操作前，例如 rm -rf、
   git push 或删除数据库表，必须先得到用户确认。

# 使用工具
 - 使用 read_file、edit_file、list_files、grep_search 代替 shell 中的 cat、
   sed、ls、grep。run_shell 只用于真正需要终端执行的操作。
 - 如果多个工具调用互不依赖，可以并行调用。
 - 需要保存完整结果时，使用 write_file，并提供 file_path 和完整 content。
 - 需要读取 HTTP 或 HTTPS 页面时，使用 web_fetch，并提供 url 和可选的 max_length。
 - 修改已有文件前，必须先用 read_file 读取。如果读取后文件发生变化，
   必须重新读取才能继续编辑。

# 语气和格式
 - 回答保持简短，先说结论。
 - 引用代码时使用“文件路径:行号”的格式。
 - 工具执行失败时，如实说明原因。"""


def _environment_context() -> str:
    """收集当前运行环境；这些信息可能在不同项目或机器之间变化。"""
    git = ""
    try:
        # 这里只读取当前分支；不在 Git 仓库中或 Git 不可用时保持为空。
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        ).stdout.strip()
        if branch:
            git = f"\nGit 分支：{branch}"
    except Exception:
        # Git 信息只是辅助上下文，读取失败不应阻止模型请求。
        pass

    # Windows 使用 ComSpec；其他系统通常从 SHELL 环境变量取得终端路径。
    if os.name == "nt":
        shell = os.environ.get("ComSpec", "cmd.exe")
    else:
        shell = os.environ.get("SHELL", "/bin/sh")

    return (
        "# 运行环境\n"
        f"当前工作目录：{os.getcwd()}\n"
        f"操作系统：{platform.system()} {platform.machine()}\n"
        f"Shell：{shell}{git}"
    )


def build_system_prompt() -> str:
    """按照原教程的顺序，把静态核心放在前面，把动态环境放在后面。"""
    return f"{STATIC_CORE}\n\n{_environment_context()}"
