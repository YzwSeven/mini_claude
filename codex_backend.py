"""第二个读这里：模型用哪个、收到什么指令、能请求哪些工具。"""
from codex_transport import send_request
from tools import TOOL_DEFINITIONS

MODEL = "gpt-5.5"


def ask_model(messages):
    # 这是发给模型的任务单。messages 中包含用户消息和之前的工具结果。
    payload = {
        "model": MODEL,
        "instructions": (
            "你是一个编程助手，用中文回答。"
            "按文件名查找时使用 list_files，提供 pattern（例如 **/*.py）及可选 path。"
            "需要了解文件内容时，使用 read_file 工具。需要按内容定位代码时，使用 grep_search 的 pattern 和可选 path。"
            "用户要求保存结果时，使用 write_file，提供 file_path 和完整 content；目标不存在则创建，存在则覆盖。"
            "局部修改使用 edit_file，提供 file_path、精确且唯一的 old_string、new_string。"
            "写入或编辑后根据工具返回结果报告是否成功；失败时不要擅自换路径保存。"
            "需要读取网页或 HTTP 接口时使用 web_fetch，提供 url 和可选的 max_length；只支持 HTTP 或 HTTPS。"
            "需要执行测试或命令时使用 run_shell，提供 command；当前是 Windows，命令使用 cmd 语法。不要编造没有读取过的文件内容。"
            "工具执行失败时，如实解释原因。"
        ),
        "input": messages,
        # 这里只提供工具说明；真正执行工具的是 main.py。
        "tools": TOOL_DEFINITIONS,
        "store": False,
        "stream": True,
        # 我们自己传历史，所以一并保留可续接的加密推理记录。
        # 不需要解密；main.py 会把它随完整输出一起传回去。
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"effort": "low"},
    }
    # 返回完整响应字典，而不是一个字符串，避免丢掉工具调用。
    return send_request(payload)
