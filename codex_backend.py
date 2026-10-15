"""第二个读这里：模型用哪个、收到什么指令、能请求哪些工具。"""
from codex_transport import send_request
import os
from api_backends import call_openai
from retry import with_retry
from thinking import get_gpt_reasoning_effort
from prompt import build_system_prompt
from tools import get_active_tool_definitions, get_deferred_tool_names

MODEL = "gpt-5.5"


def ask_model(messages, on_text=None, thinking=False, on_tool_call=None, on_attempt_start=None):
    """重试单次模型请求；完整工具回调和重试清理通知由 Agent 处理。"""
    # 这三个回调都是 Python 函数，不会写进发给 GPT 的 JSON：
    # on_text 通知显示文字，on_tool_call 通知一个完整工具请求，
    # on_attempt_start 通知 Agent 清理上一次失败尝试。
    # backend 负责转交通知，不在这里读文件或安排线程。
    def send_once():
        # 回调在每次尝试前运行；重试时清理失败尝试的提前任务和显示编号。
        if on_attempt_start is not None:
            on_attempt_start()
        return _ask_model_once(messages, on_text, thinking, on_tool_call)

    # with_retry 每次调用 send_once，都会先清理再真正发请求。
    # 它重试的是模型请求，不会把 main.py 已经完成的整轮工具循环重跑。
    return with_retry(send_once)


def _ask_model_once(messages, on_text=None, thinking=False, on_tool_call=None):
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

    # 只接入 GPT：默认 Codex，也可显式选择官方 OpenAI API。
    # 显式选择可以避免环境中遗留的密钥意外改变正在使用的服务。
    backend = os.environ.get("MINI_BACKEND", "codex").lower()
    model = os.environ.get("MINI_MODEL") or (MODEL if backend == "codex" else "")
    if backend not in ("codex", "openai"):
        raise RuntimeError("MINI_BACKEND 只能是 codex 或 openai。")
    if not model:
        raise RuntimeError("切换到 API 后端时，请设置 MINI_MODEL 为该服务可用的模型名称。")
    # Chat Completions 没有本项目所用的单项完成通知，所以不转交工具回调。
    # 这个路径还是收完整轮回复后，由 main.py 正常执行工具。
    if backend == "openai":
        # 官方 Chat Completions 使用 reasoning_effort，字段转换在 api_backends.py。
        if thinking:
            response = call_openai(messages, instructions, get_active_tool_definitions(), model, on_text, thinking=True)
        else:
            response = call_openai(messages, instructions, get_active_tool_definitions(), model, on_text)
        # 这是给本地 Agent 看的标记，不发送给模型，也不放进消息历史。
        # Chat 路径等完整回复后分批执行；Codex 继续使用已有提前任务。
        return {**response, "tool_execution_mode": "batch"}
    # 这是发给模型的任务单。messages 中包含用户消息和之前的工具结果。
    payload = {
        "model": model,
        "instructions": instructions,
        "input": messages,
        # 普通工具始终发送；延迟工具只有经过 ToolSearch 激活后才会出现在这里。
        "tools": get_active_tool_definitions(),
        "store": False,
        "stream": True,
        # 我们自己传历史，所以一并保留可续接的加密推理记录。
        # 不需要解密；main.py 会把它随完整输出一起传回去。
        "include": ["reasoning.encrypted_content"],
        # Codex 使用 Responses 风格的嵌套字典配置 GPT 思考强度。
        # True → high；False → low，保留原来默认的低强度。
        "reasoning": {"effort": get_gpt_reasoning_effort(thinking)},
    }
    # 返回完整响应字典，而不是一个字符串，避免丢掉工具调用。
    # 两条同时进行的流程：收到事件时用回调通知 main.py；
    # 收到整轮完成事件后，用 return 把完整回复交回 main.py。
    # 可选回调为 None 时不用它，仍能单独调用 send_request。
    if on_tool_call is not None:
        return send_request(payload, on_text=on_text, on_tool_call=on_tool_call)
    return send_request(payload, on_text=on_text)
