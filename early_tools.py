"""第五章：完整工具请求到达后，在线程中提前执行只读工具。"""
# 建议先读 main.py 的 start_tool，再来看本文件的 start 和 take。
# main.py 是安排任务的人，本文件是“提前派活和领取结果”的记录本。
# 一次完整调用的路径：start → 线程执行 _execute → take 领取结果。
# 请求失败或重试时走 reset/discard，暂存结果不进入聊天历史。
import json
from concurrent.futures import ThreadPoolExecutor

# 沿用原教程的并发安全名单；写入、编辑、命令和工具激活都不提前执行。
CONCURRENCY_SAFE_TOOLS = frozenset({"read_file", "list_files", "grep_search", "web_fetch"})


class EarlyTools:
    """管理一轮请求的提前任务；重试时丢弃上次尝试的结果。"""

    def __init__(self, execute):
        # main.py 创建 EarlyTools(execute_tool)，所以 execute 就是已有工具入口。
        # 保存函数本身，等工作线程运行时再调用；这里并没有执行工具。
        self.execute = execute
        # 线程池负责安排最多四个工作线程；更多任务先排队。
        # 主线程继续收模型回复，工作线程执行读取，两边可以同时进行。
        self.pool = ThreadPoolExecutor(max_workers=4)
        # 记录格式：调用编号 → (工具与参数的核对信息, Future)。
        # Future 是线程池返回的任务对象，可以理解成“稍后领取结果的凭条”。
        # 例如："read1" → (("read_file", '{"file_path":"main.py"}'), 某个任务)。
        # 这里存的是任务，不是已经得到的文件内容。
        self.tasks = {}

    def __enter__(self):
        # main.py 的 with ... as early 会进入这里。
        # 返回当前管理器，让 main.py 可以调用 early.start、early.take。
        return self

    def __exit__(self, *args):
        # 离开 with 时会到这里：正常结束、异常、提前 return 都会清理。
        # *args 接收 with 提供的异常信息；本方法没有返回 True，不会吞掉异常。
        self.discard()
        # Python 不能强制中止已运行的线程；退出前等待，避免留下后台任务。
        self.pool.shutdown(wait=True, cancel_futures=True)

    def discard(self):
        """请求尝试重置或管理器退出时，清理剩余任务；写操作不调用这里。"""
        # 这是线程生命周期/重试隔离的清理，不是原文所没有的“写前清空”。
        # 成功回复的工具处理循环会优先 take 领取结果，而不是遇写就丢掉。
        # 先复制待清理的任务，再清空记录本，让这些结果不能被后面领取。
        # clear 只清字典，不会让工作线程停止，因此下面还要处理任务本身。
        tasks = list(self.tasks.values())
        self.tasks.clear()
        # 每条记录是 (核对信息, 任务)，_ 表示这里不需要核对信息。
        # cancel 只能取消尚未开始的任务，已经运行的线程不能被强行停下。
        for _, task in tasks:
            task.cancel()
        for _, task in tasks:
            if not task.cancelled():
                try:
                    # 已经开始的只读操作要等它结束；这里取到的结果直接丢弃。
                    # 不合并它的文件读取记录，也不把它写进聊天历史。
                    task.result()
                except Exception:
                    # 这些结果已被舍弃，不再影响成功尝试或会话读取状态。
                    pass

    def reset(self):
        """每次请求尝试开始时调用，包括重试；不复用失败尝试的任务。"""
        # 重试可能又用同一个 call_id，但那已经是新的请求尝试。
        # 必须先丢弃旧任务，不能拿第一次失败请求的结果冒充新请求结果。
        self.discard()

    # 核对工具请求只需要 call，不需要管理器自己的字段，所以用静态方法。
    @staticmethod
    def signature(call):
        """编号之外还核对工具名称与完整参数，防止复用不同请求的结果。"""
        # GPT 返回的 arguments 是 JSON 字符串，先还原成参数字典。
        # 例如 '{"file_path":"main.py"}' → {"file_path": "main.py"}。
        arguments = json.loads(call["arguments"])
        if not isinstance(arguments, dict):
            raise ValueError("工具参数必须是 JSON 对象。")
        # 核对信息由“工具名称 + 排序后的参数 JSON”组成，不是加密签名。
        # 参数键顺序不同但内容相同时，排序后仍能判断为同一个请求。
        # 返回两份东西：核对信息留在记录本，参数字典交给真正的工具。
        return (call["name"], json.dumps(arguments, sort_keys=True, ensure_ascii=False)), arguments

    def start(self, call):
        """返回 True 表示确实启动任务；重复事件或不适合提前执行时返回 False。"""
        # call 是已完整收到的请求，包含 name、call_id、arguments 等字段。
        # start 只决定是否派活，并不等待工具完成。
        name = call.get("name")
        if name not in CONCURRENCY_SAFE_TOOLS:
            # 原文只跳过当前非只读调用，不清空其他任务，也不禁止后续读取。
            return False
        # 有的完整调用没有 status 字段，此时 get 返回 None；兼容这种结构。
        # 明确标为未完成的调用不能提前执行。
        if call.get("status") not in (None, "completed"):
            return False
        call_id = call.get("call_id")
        # 编号既是结果配对依据，也是防重复依据。
        # 同一个完成事件再来一次，已有任务就不再派一次活。
        if not isinstance(call_id, str) or not call_id or call_id in self.tasks:
            return False
        try:
            signature, arguments = self.signature(call)
        except (ValueError, KeyError, TypeError):
            # 最终正常工具处理仍会把参数错误反馈给模型。
            return False
        # submit 把 _execute(name, arguments) 交给线程池，立即返回 Future。
        # 工具可能已经开始，也可能排队；主线程不用等，继续接收 GPT 回复。
        # 把 Future 和核对信息一起按 call_id 存好，最后由 take 来领取结果。
        self.tasks[call_id] = (signature, self.pool.submit(self._execute, name, arguments))
        return True

    def _execute(self, name, arguments):
        """工作线程只更新独立的读取记录，不直接修改会话状态或消息历史。"""
        # 这是本次工具独立的临时读取记录，通常保存“文件路径 → mtime”。
        # 不能直接使用 main.py 的共享 read_file_state：模型请求随后可能失败。
        # 先暂存，只有完整成功回复真正采用结果时，take 才把记录合并回去。
        read_state = {}
        try:
            # self.execute 就是 main.py 传进来的 execute_tool。
            # 因此原来的工具实现、结果截断和错误返回都继续使用。
            result = self.execute(name, arguments, read_state)
        except (ValueError, KeyError, TypeError, OSError) as error:
            result = f"工具执行失败：{error}"
            read_state.clear()
        # 线程返回“工具文字结果 + 临时读取记录”，Future 会保管这两份数据。
        # 工作线程不负责打印结果、不改 messages、也不向 GPT 发送下一次请求。
        return result, read_state

    def take(self, call, read_file_state):
        """完整回复采用同一个调用时，等待它的结果并合并读取记录。"""
        # 用最终回复的 call_id 查找任务，并从记录本移除，表示领取一次。
        # 找不到返回 None，main.py 便会走原来的正常工具执行流程。
        entry = self.tasks.pop(call["call_id"], None)
        if entry is None:
            return None
        # 取出之前保存的核对信息和 Future，确认最终回复仍是同一个请求。
        signature, task = entry
        if signature != self.signature(call)[0]:
            # 完成事件与最终回复不一致，不采用提前结果。
            task.cancel()
            if not task.cancelled():
                task.result()
            return None
        # 任务已完成就立即拿到结果；还没完成则在这里等待。
        # 注意：这里没有再次调用 execute_tool，不会为了领取结果再读一遍。
        result, read_state = task.result()
        # 现在完整请求已经成功，Agent 也确实采用了这次读取结果。
        # 才把临时 mtime 记录并入会话，供后续“编辑前必须读过”检查使用。
        # 这里保留读取时的时间，不改成当前时间，否则会掩盖外部修改。
        read_file_state.update(read_state)
        return result
