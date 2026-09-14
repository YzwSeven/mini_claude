"""最后再读这里：只管登录和网络，不决定要执行什么工具。

这是已验证过的 Codex 后端协议接入，后端更新时可能需要调整。
"""
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

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


def send_request(payload):
    """发送一轮请求，等完整响应到齐后返回字典（包含 output 列表）。"""
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
                    kind = event.get("type")

                    # 完成事件包含完整输出：文字、工具请求及推理记录。
                    # 不能只提取文字，否则模型只请求工具时就会返回空串。
                    # 也不能把这个判断套在 output_text.delta 的判断里面：
                    # 同一个事件不可能同时是“文字片段”和“响应完成”。
                    if kind == "response.output_item.done":
                        finished_items[event["output_index"]] = event["item"]
                    elif kind == "response.completed":
                        result = event["response"]
                        if not result.get("output"):
                            result["output"] = [
                                finished_items[index] for index in sorted(finished_items)
                            ]
                        return result
                    elif kind in ("error", "response.failed", "response.incomplete"):
                        raise RuntimeError(f"模型请求未完成：{kind}")
                    # 其他中间事件暂时忽略；这个教学版等完整回答后才显示。
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        # 即便服务端错误意外包含认证信息，也不把它显示出来。
        detail = detail.replace(token, "[REDACTED]").replace(account, "[REDACTED]")
        if exc.code == 401:
            raise RuntimeError("登录已过期或被拒绝，请运行 codex login 后重试。") from None
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(f"网络请求失败：{exc.reason}") from None
    raise RuntimeError("连接在完整响应到达前结束，请重试。")
