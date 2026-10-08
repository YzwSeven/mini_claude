"""第二个读这里：模型用哪个、收到什么指令、能请求哪些工具。"""
from codex_transport import send_request
from prompt import build_system_prompt
from tools import get_active_tool_definitions, get_deferred_tool_names

MODEL = "gpt-5.5"


def ask_model(messages, on_text=None):
    # 延迟工具只把名称写进提示词；完整定义要等 ToolSearch 激活后再发送。
    deferred_names = get_deferred_tool_names()
    deferred_instruction = ""
    if deferred_names:
        deferred_instruction = (
            "以下延迟工具可以通过 tool_search 激活："
            + "、".join(deferred_names)
            + "。需要时先调用 tool_search 获取完整定义。"
        )

    # 系统提示词由 prompt.py 统一构造，这里只负责放进模型请求。
    instructions = build_system_prompt()
    if deferred_instruction:
        instructions += f"\n\n{deferred_instruction}"

    # 这是发给模型的任务单。messages 中包含用户消息和之前的工具结果。
    payload = {
        "model": MODEL,
        "instructions": instructions,
        "input": messages,
        # 普通工具始终发送；延迟工具只有经过 ToolSearch 激活后才会出现在这里。
        "tools": get_active_tool_definitions(),
        "store": False,
        "stream": True,
        # 我们自己传历史，所以一并保留可续接的加密推理记录。
        # 不需要解密；main.py 会把它随完整输出一起传回去。
        "include": ["reasoning.encrypted_content"],
        "reasoning": {"effort": "low"},
    }
    # 返回完整响应字典，而不是一个字符串，避免丢掉工具调用。
    # 回调只负责实时显示文字，返回值仍然是模型完整响应。
    return send_request(payload, on_text=on_text)
