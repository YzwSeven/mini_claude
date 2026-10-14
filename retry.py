"""第五章：判断临时错误，并对单次模型请求进行指数退避重试。"""
import time


def _is_retryable(error):
    """按原教程检查状态码和临时网络错误文字。"""
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    if status in (429, 503, 529):
        return True
    message = str(error)
    return any(word in message for word in ("overloaded", "ECONNRESET", "ETIMEDOUT"))


class ModelRequestError(RuntimeError):
    """只携带安全说明和重试信息，不把 SDK 原始响应展示给用户。"""

    def __init__(self, message, original):
        super().__init__(message)
        self.status_code = getattr(original, "status_code", None) or getattr(original, "status", None)
        self.retryable = _is_retryable(original)


def with_retry(fn, max_retries=3):
    """fn 只发送一次请求；三次重试加上首次请求，共最多四次。"""
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except Exception as error:
            # 错误已经清理过时，使用清理前记录的判断结果。
            retryable = getattr(error, "retryable", None)
            if retryable is None:
                retryable = _is_retryable(error)
            if attempt >= max_retries or not retryable:
                raise
            # 与原 Python 教程相同：指数部分最多 30 秒，再加不足 1 秒抖动。
            delay = min(1000 * (2 ** attempt), 30000) / 1000 + (hash(str(time.time())) % 1000) / 1000
            status = getattr(error, "status_code", None) or getattr(error, "status", None)
            reason = f"HTTP {status}" if status else "临时网络错误"
            # 换行让此前显示的半段文字与重新生成的内容分开。
            print(f"\n请求失败（{reason}），{delay:.1f} 秒后重试 {attempt + 1}/{max_retries}；此前片段不作为完整回复。", flush=True)
            # 当前项目使用同步请求，因此以 sleep 对应原文的 await asyncio.sleep。
            time.sleep(delay)
