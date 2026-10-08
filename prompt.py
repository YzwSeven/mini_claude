"""构造每次请求模型时使用的系统提示词。"""

import os
import platform
import re
import subprocess
from pathlib import Path


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


# 只有整行形如 @./路径、@~/路径 或 @/绝对路径 时，才把它当作文件引用。
_INCLUDE_RE = re.compile(r"^@(\./[^\s]+|~/[^\s]+|/[^\s]+)$", re.MULTILINE)

# 限制引用嵌套层数，避免错误配置无限递归或读取过多文件。
_MAX_INCLUDE_DEPTH = 5


def _resolve_includes(
    content: str,
    base_path: Path,
    visited: set[str] | None = None,
    depth: int = 0,
) -> str:
    """把 Markdown 中单独占一行的 @路径 替换为目标文件内容。"""
    if visited is None:
        visited = set()
    if depth >= _MAX_INCLUDE_DEPTH:
        return content

    def _replace(match: re.Match) -> str:
        raw_path = match.group(1)
        if raw_path.startswith("~/"):
            resolved = Path.home() / raw_path[2:]
        elif raw_path.startswith("/"):
            resolved = Path(raw_path)
        else:
            resolved = base_path / raw_path

        resolved = resolved.resolve()
        key = str(resolved)
        if key in visited:
            return f"<!-- 循环引用：{raw_path} -->"
        if not resolved.is_file():
            return f"<!-- 文件不存在：{raw_path} -->"

        try:
            visited.add(key)
            included = resolved.read_text(encoding="utf-8")
            return _resolve_includes(
                included,
                resolved.parent,
                visited,
                depth + 1,
            )
        except (OSError, UnicodeError):
            return f"<!-- 文件读取失败：{raw_path} -->"

    return _INCLUDE_RE.sub(_replace, content)


def _load_rules_dir(directory: Path) -> str:
    """按文件名顺序加载当前项目 .claude/rules 目录中的 Markdown 规则。"""
    rules_dir = directory / ".claude" / "rules"
    if not rules_dir.is_dir():
        return ""

    try:
        files = sorted(
            file
            for file in rules_dir.iterdir()
            if file.is_file() and file.suffix == ".md"
        )
        parts: list[str] = []
        for file in files:
            try:
                content = file.read_text(encoding="utf-8")
                content = _resolve_includes(content, rules_dir)
                parts.append(f"<!-- 规则文件：{file.name} -->\n{content}")
            except (OSError, UnicodeError):
                # 单个规则文件读取失败时，继续加载其他规则。
                pass
        return "\n\n## 项目规则\n" + "\n\n".join(parts) if parts else ""
    except OSError:
        return ""


def load_claude_md() -> str:
    """从当前目录向上查找 CLAUDE.md，并追加当前项目的规则目录。"""
    parts: list[str] = []
    directory = Path.cwd().resolve()

    while True:
        claude_file = directory / "CLAUDE.md"
        if claude_file.is_file():
            try:
                content = claude_file.read_text(encoding="utf-8")
                content = _resolve_includes(content, directory)
                # 从下往上查找，但父目录规则应该排在子目录规则前面。
                parts.insert(0, content)
            except (OSError, UnicodeError):
                pass

        parent = directory.parent
        if parent == directory:
            break
        directory = parent

    rules = _load_rules_dir(Path.cwd())
    claude_md = ""
    if parts:
        claude_md = (
            "\n\n# 项目指令（CLAUDE.md）\n"
            + "\n\n---\n\n".join(parts)
        )
    return claude_md + rules


def build_user_context_reminder() -> str:
    """把项目规则和日期包装成背景信息，供首条用户消息携带。"""
    from datetime import date

    claude_md = load_claude_md()
    claude_md_section = f"\n{claude_md}\n" if claude_md else ""
    return (
        "<system-reminder>\n"
        "回答用户问题时，可以参考以下背景信息："
        f"{claude_md_section}\n"
        "# 当前日期\n"
        f"今天是 {date.today().isoformat()}。\n\n"
        "注意：这些背景信息可能与当前任务无关，仅在与任务高度相关时使用，"
        "不需要专门回复这些背景信息。\n"
        "</system-reminder>"
    )


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
