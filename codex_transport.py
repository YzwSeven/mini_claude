"""最后再读这里：只管登录和网络，不决定要执行什么工具。

这是已验证过的 Codex 后端协议接入，后端更新时可能需要调整。
"""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
from retry import ModelRequestError

ENDPOINT = "https://chatgpt.com/backend-api/codex/responses"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # 不把带登录凭据的请求跟随跳转发送到其他地址。
        return None


def read_login():
    # 每次请求读现有登录，不把令牌硬编码在项目里，也不打印令牌。
    codex_dir = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
    try:
        data = json.loads((codex_dir / "auth.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError("无法读取 Codex 登录，请先运行 codex login。") from None
    tokens = data.get("tokens") or {}
    token = tokens.get("access_token")
    account = tokens.get("account_id")
    if not token or not account:
        raise RuntimeError("缺少 ChatGPT 登录信息，请运行 codex login。")
    return token, account


def send_request(payload, on_text=None, on_tool_call=None):
    """文字片段到达时调用 on_text；完整响应到齐后仍返回包含 output 的字典。"""
    # 本函数只处理通信；on_tool_call 指向 main.py 的 start_tool。
    # 即使它通知工具请求，也不在网络层决定哪些工具可以提前运行。
    token, account = read_login()
    request = urllib.request.Request(
        ENDPOINT,
        # 字典转成 JSON，再编码成网络传输使用的字节。
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "ChatGPT-Account-ID": account,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )
    opener = urllib.request.build_opener(NoRedirect())
    # 一个事件可能由多行 data 组成，先暂存，遇到空行再合并解析。
    event_lines = []
    # 有些后端只在 output_item.done 中给出结果，最后的 output 却为空。
    # 按输出序号收集已经完成的项，避免文字或工具请求再次丢失。
    finished_items = {}
    try:
        with opener.open(request, timeout=90) as response:
            # SSE 会逐行发来事件；空行表示一条事件结束。
            for raw_line in response:
                line = raw_line.decode("utf-8").rstrip("\r\n")
                if line.startswith("data:"):
                    event_lines.append(line[5:].lstrip())
                elif not line and event_lines:
                    raw_event = "\n".join(event_lines)
                    event_lines.clear()
                    if raw_event == "[DONE]":
                        break
                    event = json.loads(raw_event)
                    # 三类重点事件：文字片段、单个输出项完成、整轮响应完成。
                    # “一个工具请求完整”与“整轮回复结束”是两个不同的时刻。
                    kind = event.get("type")

                    # 完成事件包含完整输出：文字、工具请求及推理记录。
                    # 不能只提取文字，否则模型只请求工具时就会返回空串。
                    # 也不能把这个判断套在 output_text.delta 的判断里面：
                    # 同一个事件不可能同时是“文字片段”和“响应完成”。
                    if kind == "response.output_text.delta":
                        # 这里只通知显示层，不把片段另存成历史消息。
                        # 输出序号用于区分同一轮里的多条消息，避免重复打印。
                        text = event.get("delta", "")
                        if text and on_text is not None:
                            on_text(text, event["output_index"])
                    elif kind == "response.output_item.done":
                        # item 是一个完整输出项。若是工具调用，会包含完整名称、
                        # arguments 和 call_id；不需要我们拼接中间参数片段。
                        item = event["item"]
                        finished_items[event["output_index"]] = item
                        # 这里只报告完整调用，是否提前执行由 Agent 决定。
                        # 参数片段、文字项和推理项均不会触发工具回调。
                        if item.get("type") == "function_call" and on_tool_call is not None:
                            # main.py 的 start_tool 在这里被调用，把只读任务交给线程。
                            # 回调返回后，下面的接收循环继续运行，不等读取结果。
                            on_tool_call(item)
                    elif kind == "response.completed":
                        # 到这个事件，整轮回复才算成功，最终处理权交回 main.py。
                        # 已启动的工具可能完成了，也可能还在运行，稍后统一领取结果。
                        result = event["response"]
                        if not result.get("output"):
                            result["output"] = [
                                finished_items[index] for index in sorted(finished_items)
                            ]
                        return result
                    elif kind in ("error", "response.failed", "response.incomplete"):
                        raise RuntimeError(f"模型请求未完成：{kind}")
                    # 参数片段不触发工具；output_item.done 才通知完整调用。
                    # 即便已提前读取，随后发生 failed/incomplete 也必须报错。
                    # Agent 将清理任务，失败结果不会作为成功对话保存。
    except urllib.error.HTTPError as exc:
        exc.status_code = exc.code
        detail = exc.read(4096).decode("utf-8", errors="replace")
        # 即便服务端错误意外包含认证信息，也不把它显示出来。
        detail = detail.replace(token, "[REDACTED]").replace(account, "[REDACTED]")
        if exc.code == 401:
            raise RuntimeError("登录已过期或被拒绝，请运行 codex login 后重试。") from None
        raise ModelRequestError(f"HTTP {exc.code}: {detail}", exc) from None
    except urllib.error.URLError as exc:
        raise ModelRequestError(f"网络请求失败：{exc.reason}", exc) from None
    raise RuntimeError("连接在完整响应到达前结束，请重试。")
