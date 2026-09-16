"""工具分两部分：给模型看的说明，以及在本机执行的函数。"""
import os
from pathlib import Path

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
        # 这份说明告诉模型：不知道文件名时，先查看目录再决定读什么。
        "type": "function",
        "name": "list_files",
        "description": "列出项目中指定目录下的文件和子目录，不递归。不知道文件名时先用它查看。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "相对项目根目录的目录路径；查看项目根目录时传入 .",
                }
            },
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
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


def list_files(path):
    """只列指定目录的直接内容，返回模型可以阅读的文件清单。"""
    if not isinstance(path, str):
        return "查看失败：path 必须是字符串。"
    try:
        # 模型传入 . 时，就是查看项目根目录；不依赖终端启动位置。
        directory = (PROJECT_DIR / path).resolve()
        if not directory.is_relative_to(PROJECT_DIR):
            return "查看失败：只能查看当前项目中的目录。"
        if not directory.is_dir():
            return "查看失败：目录不存在，或者传入的是一个文件。"

        entries = []
        # 只看一层，不自动钻进 .venv 等子目录，避免一次返回大量文件。
        for item in sorted(directory.iterdir()):
            # 类型标签让模型区分：文件可以读，目录可以继续列。
            kind = "目录" if item.is_dir() else "文件"
            entries.append(f"[{kind}] {item.name}")
        return "\n".join(entries) or "这个目录是空的。"
    except (OSError, ValueError) as error:
        # 失败也返回文字，Agent 会把原因交回模型，让它决定下一步。
        return f"查看失败：{error}"


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
        # 局部替换由后续章节中的 edit_file 实现。
        with open(inp["file_path"], "w", encoding="utf-8") as f:
            f.write(inp["content"])
        # 保留原文按换行符拆分计算行数的方式和返回格式。
        n = len(inp["content"].split("\n"))
        return f"Successfully wrote to {inp['file_path']} ({n} lines)"
    except Exception as e:
        # 将失败原因交回模型，由模型结合结果决定下一步。
        return f"Error writing file: {e}"


def execute_tool(name, arguments):
    """工具的统一入口：模型给出名称和参数，我们选择对应函数执行。"""
    # 例如 name="read_file"，arguments={"path": "hello.txt"}。
    # 工具说明只告诉模型怎样提出请求；这个分支才把请求接到真实函数。
    if name == "read_file":
        return read_file(arguments["path"])

    # 统一入口把不同工具请求交给对应函数，main.py 的循环不需要改。
    if name == "list_files":
        return list_files(arguments["path"])

    # 写文件需要两个参数；模型负责生成内容，工具负责实际保存。
    if name == "write_file":
        return _write_file(arguments)

    # 以后新增工具时，在这里添加分支，并在 TOOL_DEFINITIONS 中添加说明。
    # main.py 的循环就不用跟着每个新工具改动了。
    # 未实现的工具不会执行；把原因交回模型，让它调整下一步。
    return f"执行失败：没有名为 {name} 的工具。"


if __name__ == "__main__":
    # 单独运行这个文件，只测试读取函数，不请求模型。
    print(read_file("hello.txt"))
