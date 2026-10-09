"""第五章：把两种官方 API 协议转换成 Agent 已有的统一消息格式。"""
import json
import os


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


def to_anthropic_messages(messages):
    """Anthropic 将工具请求放在助手内容块，工具结果放在用户内容块。"""
    result = []
    for item in messages:
        kind = item.get("type")
        if kind == "reasoning":
            continue
        if kind == "function_call":
            role = "assistant"
            block = {"type": "tool_use", "id": item["call_id"], "name": item["name"], "input": json.loads(item["arguments"])}
        elif kind == "function_call_output":
            role = "user"
            block = {"type": "tool_result", "tool_use_id": item["call_id"], "content": item["output"]}
        elif item.get("role") in ("user", "assistant"):
            role = item["role"]
            block = {"type": "text", "text": _text(item)}
        else:
            continue
        # 同一轮多个工具请求或结果合并，保持 Anthropic 的消息交替结构。
        if not result or result[-1]["role"] != role:
            result.append({"role": role, "content": []})
        result[-1]["content"].append(block)
    return result


def _message(text):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


def call_openai(messages, instructions, tools, model, on_text=None):
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
    text = ""
    calls = {}
    finish_reason = None
    try:
        with OpenAI(**options) as client:
            with client.chat.completions.create(
                model=model, messages=to_chat_messages(messages, instructions),
                tools=definitions, stream=True, max_tokens=16384,
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
        raise RuntimeError(f"OpenAI 请求失败：{type(error).__name__}") from None
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


def call_anthropic(messages, instructions, tools, model, on_text=None):
    """SDK 累积 Anthropic 内容块；文字事件仍立即通知显示层。"""
    try:
        from anthropic import Anthropic, APIError
    except ImportError:
        raise RuntimeError("请先运行 .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt") from None
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("anthropic 后端需要设置 ANTHROPIC_API_KEY。")
    options = {"api_key": key, "max_retries": 0, "timeout": 90}
    if os.environ.get("ANTHROPIC_BASE_URL"):
        options["base_url"] = os.environ["ANTHROPIC_BASE_URL"]
    definitions = [{"name": tool["name"], "description": tool.get("description", ""), "input_schema": tool["parameters"]} for tool in tools]
    try:
        with Anthropic(**options) as client:
            with client.messages.stream(model=model, max_tokens=16384, system=instructions, messages=to_anthropic_messages(messages), tools=definitions) as stream:
                for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta" and on_text:
                        on_text(event.delta.text, event.index)
                reply = stream.get_final_message()
    except APIError as error:
        raise RuntimeError(f"Anthropic 请求失败：{type(error).__name__}") from None
    if reply.stop_reason not in ("end_turn", "tool_use", "stop_sequence"):
        raise RuntimeError(f"Anthropic 响应未完整结束：{reply.stop_reason}")
    output = []
    for block in reply.content:
        if block.type == "text":
            output.append(_message(block.text))
        elif block.type == "tool_use":
            output.append({"type": "function_call", "call_id": block.id, "name": block.name, "arguments": json.dumps(block.input, ensure_ascii=False)})
    return {"output": output}
