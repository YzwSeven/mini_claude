"""第四章：把完整消息列表保存到磁盘，并在下次启动时恢复。"""
import json
import os


# 按原教程，每个工作目录使用一个会话文件，保存时覆盖上一份历史。
SESSION_FILE = os.path.join(os.getcwd(), ".mini-session.json")


def save_session(messages) -> None:
    """把完整历史写成 JSON，工具调用和工具结果也一起保存。"""
    try:
        with open(SESSION_FILE, "w", encoding="utf-8") as file:
            # 原教程兼容 SDK 消息对象；我们的 Responses 历史已经是字典。
            json.dump(messages, file, indent=2, default=lambda obj: getattr(obj, "model_dump", lambda: str(obj))())
    except Exception:
        # 保留原教程行为：保存失败不打断聊天。
        pass


def load_session():
    """读回保存的消息列表；文件不存在或读取失败时返回 None。"""
    if not os.path.exists(SESSION_FILE):
        return None
    try:
        with open(SESSION_FILE, encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return None
