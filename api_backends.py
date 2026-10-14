"""第五章：把官方 OpenAI API 转换成 Agent 已有的统一消息格式。"""
import json
import os
from retry import ModelRequestError
from thinking import get_gpt_reasoning_effort, is_gpt_55


def _text(item):
    """用户内容是字符串；助手内容是文字块列表。"""
    content = item.get("content", "")
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content)


def to_chat_messages(messages, instructions):
    """将 Responses 历史转换成 Chat Completions 的角色和工具格式。"""
    result = [{"role": "system", "content": instructions}]
    for item in messages:
        kind = item.get("type")
        if kind == "reasoning":
            # Codex 加密推理不能转交其他协议；切换后端建议开始新会话。
            continue
        if kind == "function_call":
            if result[-1]["role"] != "assistant":
                result.append({"role": "assistant", "content": None})
            result[-1].setdefault("tool_calls", []).append({
                "id": item["call_id"], "type": "function",
                "function": {"name": item["name"], "arguments": item["arguments"]},
            })
        elif kind == "function_call_output":
            result.append({"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]})
        elif item.get("role") in ("user", "assistant"):
            result.append({"role": item["role"], "content": _text(item)})
    return result


def _message(text):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def call_openai(messages, instructions, tools, model, on_text=None, thinking=False):
    """累积 Chat Completions 的文字和工具参数分片，再返回统一输出。"""
    try:
        from openai import OpenAI, APIError
    except ImportError:
        raise RuntimeError("请先运行 .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt") from None
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("openai 后端需要设置 OPENAI_API_KEY。")
    options = {"api_key": key, "max_retries": 0, "timeout": 90}
    if os.environ.get("OPENAI_BASE_URL"):
        options["base_url"] = os.environ["OPENAI_BASE_URL"]
    definitions = [{"type": "function", "function": {k: v for k, v in tool.items() if k != "type"}} for tool in tools]
    # 本次按官方文档核对 GPT-5.5，其他兼容模型保留原请求格式。
    if is_gpt_55(model):
        generation_options = {
            "reasoning_effort": get_gpt_reasoning_effort(thinking),
            # 这个上限包含推理和回答 token，不是独立的“思考预算”。
            "max_completion_tokens": 16384,
        }
    else:
        if thinking:
            raise RuntimeError("本次 GPT 思考开关适配的是 gpt-5.5；请使用该模型或先核对目标模型参数。")
        generation_options = {"max_tokens": 16384}
    text = ""
    calls = {}
    finish_reason = None
    try:
        with OpenAI(**options) as client:
            with client.chat.completions.create(
                model=model, messages=to_chat_messages(messages, instructions),
                tools=definitions, stream=True,
                # ** 将字典展开成 SDK 参数：reasoning_effort=... 等。
                **generation_options,
                stream_options={"include_usage": True},
            ) as stream:
                for chunk in stream:
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    delta = choice.delta
                    if delta.content:
                        text += delta.content
                        if on_text:
                            on_text(delta.content, 0)
                    for piece in delta.tool_calls or []:
                        call = calls.setdefault(piece.index, {"id": "", "name": "", "arguments": ""})
                        if piece.id:
                            call["id"] = piece.id
                        if piece.function:
                            call["name"] += piece.function.name or ""
                            call["arguments"] += piece.function.arguments or ""
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
    except APIError as error:
        # 不显示 SDK 原始响应，避免错误内容包含密钥。
        raise ModelRequestError(f"OpenAI 请求失败：{type(error).__name__}", error) from None
    if finish_reason not in ("stop", "tool_calls"):
        raise RuntimeError(f"OpenAI 响应未完整结束：{finish_reason}")
    output = [_message(text)] if text else []
    for index in sorted(calls):
        call = calls[index]
        if not call["id"] or not call["name"]:
            raise RuntimeError("OpenAI 工具调用缺少编号或名称。")
        json.loads(call["arguments"])
        output.append({"type": "function_call", "call_id": call["id"], "name": call["name"], "arguments": call["arguments"]})
    return {"output": output}
