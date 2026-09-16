"""工具分两部分：给模型看的说明，以及在本机执行的函数。"""
import os
import re
import subprocess
from pathlib import Path

# 原教程把单次工具结果限制为 50000 个字符，避免过长内容占满模型上下文。
MAX_RESULT_CHARS = 50000

# 这份说明通过 tools 字段发给模型，不会自动执行下面的函数。
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "name": "read_file",
        "description": "读取当前项目中一个 UTF-8 文本文件的内容。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对于项目根目录的文件路径，例如 hello.txt",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        # pattern 匹配文件名；path 可以不传，不传就从工作目录开始找。
        "type": "function",
        "name": "list_files",
        "description": "按 glob 模式查找文件，例如 **/*.py，最多返回 200 个路径。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "文件名匹配模式，例如 **/*.py"},
                "path": {"type": "string", "description": "起始目录，省略时使用当前工作目录"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        # GPT 协议适配：关闭严格模式，保留原文 path 可省略的含义。
        "strict": False,
    },
    {
        "type": "function",
        "name": "grep_search",
        "description": "用正则表达式搜索文件内容，返回路径、行号和匹配行，最多 100 行。",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "搜索内容的正则表达式"},
                "path": {"type": "string", "description": "搜索目录或文件，省略时使用当前工作目录"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
        # 与 list_files 一样，path 保持可选。
        "strict": False,
    },
    {
        "type": "function",
        "name": "run_shell",
        "description": "执行终端命令并返回输出，可用于测试、git 和安装依赖，超时为 30 秒。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的完整命令；Windows 默认使用 cmd 语法"},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        # url 必填；max_length 可省略，默认最多读取 50000 个字符。
        "type": "function",
        "name": "web_fetch",
        "description": "读取 HTTP 或 HTTPS 地址并返回文本；HTML 页面会去掉标签。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要读取的 HTTP 或 HTTPS 地址"},
                "max_length": {"type": "number", "description": "最多返回多少个字符，默认 50000"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
        # GPT 协议适配：关闭严格模式，保留原文 max_length 可省略的含义。
        "strict": False,
    },
    {
        # 模型需要提供两项信息：保存到哪里，以及保存什么文字。
        "type": "function",
        "name": "write_file",
        "description": "写入 UTF-8 文本文件：不存在则创建，存在则覆盖，自动创建父目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要写入的文件路径，例如 notes/summary.txt"},
                "content": {"type": "string", "description": "要写入文件的完整文字内容"},
            },
            "required": ["file_path", "content"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        # 参数名称和含义来自原教程；parameters 是现有 GPT 接口的格式适配。
        "type": "function",
        "name": "edit_file",
        "description": "将文件中精确匹配且唯一的 old_string 替换为 new_string。找不到或匹配多处时不修改文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "要编辑的文件路径"},
                "old_string": {"type": "string", "description": "要查找的原文，必须精确匹配且唯一"},
                "new_string": {"type": "string", "description": "替换后的文字"},
            },
            "required": ["file_path", "old_string", "new_string"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]

# 以本文件所在目录为项目根目录，避免启动位置不同导致找不到文件。
PROJECT_DIR = Path(__file__).resolve().parent


def read_file(path):
    """返回文件内容；读取失败也返回文字，让模型知道失败原因。"""
    if not isinstance(path, str):
        return "读取失败：path 必须是字符串。"
    try:
        file_path = (PROJECT_DIR / path).resolve()
        # 工具只开放项目内的文件，不允许通过 ../ 读取项目外的内容。
        if not file_path.is_relative_to(PROJECT_DIR):
            return "读取失败：只能读取当前项目中的文件。"
        return file_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        return f"读取失败：{error}"


def _list_files(inp: dict) -> str:
    """按文件名模式找文件；** 可以跨越多层子目录。"""
    import glob as globmod

    try:
        # 省略 path 或传空字符串时，以启动程序的工作目录为起点。
        base = inp.get("path") or "."
        # glob 找出路径后，只留下文件，并按原文过滤依赖和 Git 路径。
        hits = [
            f for f in globmod.glob(os.path.join(base, inp["pattern"]), recursive=True)
            if os.path.isfile(f) and "node_modules" not in f and "/.git/" not in f
        ]
        # 只返回前 200 个，避免把过长清单全塞进模型的上下文。
        return "\n".join(hits[:200]) if hits else "No files found matching the pattern."
    except Exception as e:
        return f"Error listing files: {e}"


def _grep_search(inp: dict) -> str:
    # 优先调用系统 grep；系统没有这个程序时，才交给下面的 Python 备用搜索。
    try:
        # --line-number 添加行号；-r 递归搜索；-- 后面的内容作为搜索参数。
        out = subprocess.run(
            ["grep", "--line-number", "--color=never", "-r", "--", inp["pattern"], inp.get("path") or "."],
            capture_output=True, text=True, timeout=10,
        )
        # grep 用退出码 1 表示没有匹配；0 表示找到了。
        if out.returncode == 1:
            return "No matches found."
        lines = [ln for ln in out.stdout.split("\n") if ln]
        return "\n".join(lines[:100]) if lines else "No matches found."
    except FileNotFoundError:
        return _grep_py(inp["pattern"], inp.get("path") or ".")
    except Exception as e:
        return f"Error: {e}"


def _grep_py(pattern: str, base: str) -> str:
    """系统没有 grep 时，用 Python 逐个目录、逐个文件、逐行搜索。"""
    # 先编译正则；语法不合法时，把原因作为工具结果返回。
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    matches: list[str] = []
    # 原文备用版从目录开始遍历；单文件路径不会被 os.walk 遍历。
    for root, dirs, files in os.walk(base):
        # 原地修改 dirs，让 os.walk 不再进入隐藏目录及 node_modules。
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "node_modules"]
        for name in files:
            full = os.path.join(root, name)
            try:
                # 行号从 1 开始；返回格式为 文件路径:行号:这一行的内容。
                for i, line in enumerate(open(full, encoding="utf-8"), 1):
                    if rx.search(line) and len(matches) < 100:
                        matches.append(f"{full}:{i}:{line.rstrip()}")
            except Exception:
                # 按原文跳过无法读取或无法按 UTF-8 解码的文件。
                pass
    return "\n".join(matches) if matches else "No matches found."


def _run_shell(inp: dict) -> str:
    """把命令交给系统执行，再把输出交回 Agent；不是模型自己执行命令。"""
    try:
        # shell=True 使用系统命令解释器，Windows 通常是 cmd，不是当前 PowerShell。
        # capture_output 收集输出，text 将输出解码为文字，timeout 限制等待时间。
        # 这是原文第一版：直接执行命令，尚无命令审批或沙箱。
        r = subprocess.run(inp["command"], shell=True, capture_output=True, text=True, timeout=30)
        # 退出码非 0 表示命令失败，标准输出和错误输出一起返回便于诊断。
        if r.returncode != 0:
            return f"Command failed (exit {r.returncode})\nStdout: {r.stdout}\nStderr: {r.stderr}"
        return r.stdout or "(no output)"
    except subprocess.TimeoutExpired:
        return "Command timed out after 30000ms"
    except Exception as e:
        return f"Error: {e}"


def _web_fetch(inp: dict) -> str:
    """读取网页或 HTTP 接口；HTML 会转换成更适合模型阅读的纯文本。"""
    # urllib 属于 Python 标准库，不需要通过 pip 安装额外依赖。
    import urllib.error
    import urllib.request

    url = inp.get("url", "")
    max_length = inp.get("max_length", 50000)

    # Python 的 urllib 还能打开 file:// 等地址；这里只允许真正的网页协议。
    if not url.lower().startswith(("http://", "https://")):
        return "Error: only http(s) URLs are supported"

    # User-Agent 告诉网站请求来自我们的程序，部分网站会拒绝没有该请求头的访问。
    req = urllib.request.Request(url, headers={"User-Agent": "mini-claude/1.0"})
    try:
        # 最多等待 30 秒，避免一个无响应的网址卡住整个 Agent 循环。
        with urllib.request.urlopen(req, timeout=30) as resp:
            content_type = resp.headers.get("Content-Type", "")
            # 无法按 UTF-8 解码的字节用替代字符表示，不让整个工具因此失败。
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        # 服务器明确返回 404、500 等 HTTP 状态码时走这里。
        return f"HTTP error: {e.code} {e.reason}"
    except urllib.error.URLError as e:
        # DNS、拒绝连接等网络错误作为普通工具结果交回模型。
        return f"Error fetching {url}: {e.reason}"
    except Exception as e:
        return f"Error fetching {url}: {e}"

    if "html" in content_type:
        # 模型不需要 script 和 style 的代码，先把这两类完整区块删除。
        text = re.sub(r"<script[\s\S]*?</script>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<style[\s\S]*?</style>", "", text, flags=re.IGNORECASE)
        # 删除剩余 HTML 标签，并还原原文处理的常见 HTML 实体。
        text = re.sub(r"<[^>]*>", " ", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        # 合并多余空白，减少无意义内容占用模型上下文。
        text = re.sub(r"\s{2,}", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

    # 这是 WebFetch 自己的可调上限；统一入口之后还会应用所有工具的总上限。
    if len(text) > max_length:
        text = text[:max_length] + f"\n\n[... truncated at {max_length} characters]"

    # 空响应也返回明确文字，避免模型误以为工具没有执行。
    return text or "(empty response)"


def _write_file(inp: dict) -> str:
    """按原教程第二章写入完整文件：不存在就创建，存在就覆盖。"""
    try:
        # file_path 与 content 是原文的参数名，统一入口把参数字典传进来。
        # 相对路径以当前工作目录为基准，与原文一致；请在项目根目录启动。
        d = os.path.dirname(inp["file_path"])
        # 例如 notes/summary.txt 需要先创建 notes；单独 summary.txt 则不需要。
        if d and not os.path.exists(d):
            os.makedirs(d, exist_ok=True)
        # w 会覆盖原有内容，所以 content 必须是想保存的完整文件内容。
        # 局部替换由本章的 edit_file 实现。
        with open(inp["file_path"], "w", encoding="utf-8") as f:
            f.write(inp["content"])
        # 保留原文按换行符拆分计算行数的方式和返回格式。
        n = len(inp["content"].split("\n"))
        return f"Successfully wrote to {inp['file_path']} ({n} lines)"
    except Exception as e:
        # 将失败原因交回模型，由模型结合结果决定下一步。
        return f"Error writing file: {e}"


def _edit_file(inp: dict) -> str:
    """原教程第二章第一版：先检查精确匹配和唯一性，再替换原文。"""
    try:
        # 1. 读取当前文件。相对路径以工作目录为基准，与原文保持一致。
        content = open(inp["file_path"], encoding="utf-8").read()
        # 2. 找不到就返回错误，此时还没有写入，不会改变文件内容。
        if inp["old_string"] not in content:
            return f"Error: old_string not found in {inp['file_path']}"
        # 3. 多处匹配时不能猜测要改哪里，让模型补充更完整的上下文。
        count = content.count(inp["old_string"])
        if count > 1:
            return f"Error: old_string found {count} times in {inp['file_path']}. Must be unique."
        # 4. 先在内存中替换。模型只提供局部改动，其余文字由程序保留。
        updated = content.replace(inp["old_string"], inp["new_string"])
        # 5. 将修改后的完整内容写回原文件，而不是追加到文件末尾。
        with open(inp["file_path"], "w", encoding="utf-8") as f:
            f.write(updated)
        return f"Successfully edited {inp['file_path']}"
    except Exception as e:
        # 6. 把错误作为工具结果交回模型，让它决定如何处理失败。
        return f"Error editing file: {e}"



def _truncate_result(result: str) -> str:
    """结果过长时保留开头和结尾，并明确告诉模型中间省略了多少字符。"""
    # 短结果不需要处理，原样交回模型。
    if len(result) <= MAX_RESULT_CHARS:
        return result

    # 为中间的截断说明预留约 60 个字符，剩余空间平均分给头部和尾部。
    keep_each = (MAX_RESULT_CHARS - 60) // 2
    return (
        result[:keep_each]
        + f"\n\n[... truncated {len(result) - keep_each * 2} chars ...]\n\n"
        + result[-keep_each:]
    )


def _read_file_from_arguments(arguments: dict) -> str:
    """把统一的参数字典转换成当前 read_file 函数需要的 path。"""
    # 当前项目的 read_file 仍是早期教学版；这里只适配调用方式，不改变读取行为。
    return read_file(arguments["path"])


def execute_tool(name, arguments):
    """根据工具名称找到函数，执行后统一截断过长结果。"""
    # 字典表达“工具名称对应哪个 Python 函数”，新增工具时只需增加一项。
    handlers = {
        "read_file": _read_file_from_arguments,
        "write_file": _write_file,
        "edit_file": _edit_file,
        "list_files": _list_files,
        "grep_search": _grep_search,
        "run_shell": _run_shell,
        "web_fetch": _web_fetch,
    }

    # get 找不到名称时返回 None，不会意外执行任何函数。
    handler = handlers.get(name)
    if not handler:
        # 错误也作为普通文字返回，让模型知道自己请求了不存在的工具。
        return f"执行失败：没有名为 {name} 的工具。"

    # 所有已注册工具都经过同一个出口，因此统一受到 50000 字符保护。
    result = handler(arguments)
    return _truncate_result(result)


if __name__ == "__main__":
    # 单独运行这个文件，只测试读取函数，不请求模型。
    print(read_file("hello.txt"))
