"""工具分两部分：给模型看的说明，以及在本机执行的函数。"""
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


def execute_tool(name, arguments):
    """工具的统一入口：模型给出名称和参数，我们选择对应函数执行。"""
    # 例如 name="read_file"，arguments={"path": "hello.txt"}。
    # 工具说明只告诉模型怎样提出请求；这个分支才把请求接到真实函数。
    if name == "read_file":
        return read_file(arguments["path"])

    # 以后新增工具时，在这里添加分支，并在 TOOL_DEFINITIONS 中添加说明。
    # main.py 的循环就不用跟着每个新工具改动了。
    # 未实现的工具不会执行；把原因交回模型，让它调整下一步。
    return f"执行失败：没有名为 {name} 的工具。"


if __name__ == "__main__":
    # 单独运行这个文件，只测试读取函数，不请求模型。
    print(read_file("hello.txt"))
