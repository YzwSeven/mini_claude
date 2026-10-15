"""第五章：完整收到工具调用后，把连续只读工具分批并行执行。"""
import json
from concurrent.futures import ThreadPoolExecutor
from early_tools import CONCURRENCY_SAFE_TOOLS


def prepare_tool_calls(tool_calls):
    """先准备所有调用的参数；参数错误也保留原编号，稍后作为结果返回。"""
    checked = []
    for call in tool_calls:
        print("调用工具：", call["name"], call["arguments"])
        try:
            arguments = json.loads(call["arguments"])
        except (ValueError, TypeError) as error:
            # 参数错误的调用不能进并行批次，但也不能直接从历史里消失。
            checked.append({
                "call": call, "fn": call["name"], "ready": False,
                "result": f"工具执行失败：{error}",
            })
        else:
            # ready 仅表示参数解析成功，不是假装已经做过权限检查。
            # 原文这里还会检查权限；本项目的权限系统留在第六章实现。
            checked.append({
                "call": call, "fn": call["name"], "inp": arguments, "ready": True,
            })
    return checked


def group_tool_calls(checked):
    """按原文分组：相邻只读调用放一批，其余调用各自单独一批。"""
    batches = []
    for item in checked:
        safe = item["ready"] and item["fn"] in CONCURRENCY_SAFE_TOOLS
        if safe and batches and batches[-1]["concurrent"]:
            # 当前是只读，而且上一批也是只读，就加入上一批。
            # 例如先有 [读A]，再遇到读B，变成 [读A、读B]。
            batches[-1]["items"].append(item)
        else:
            # 写C建立单独一批；后面的读D不能越过写C加入前面的读取批。
            # 参数错误/未知工具同样会切断连续只读批次。
            batches.append({"concurrent": safe, "items": [item]})
    return batches


def _execute_checked(item, execute, read_state):
    """执行一次原有工具；常见异常沿用 main.py 的错误结果处理。"""
    try:
        return execute(item["fn"], item["inp"], read_state)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return f"工具执行失败：{error}"


def _run_read(item, execute):
    """工作线程只返回结果和独立读取记录，不修改 messages 或共享状态。"""
    local_read_state = {}
    result = _execute_checked(item, execute, local_read_state)
    return result, local_read_state


def execute_tool_batches(tool_calls, execute, read_file_state):
    """逐批执行，依次交出（原调用, 结果），由 main.py 写回历史。"""
    checked = prepare_tool_calls(tool_calls)
    batches = group_tool_calls(checked)
    for batch in batches:
        if batch["concurrent"]:
            # 同一批先全部提交给线程池，不提交一个就立即等待它。
            # 最多四个线程；更多任务排队，不会越过当前批次去做写操作。
            with ThreadPoolExecutor(max_workers=4) as pool:
                tasks = [pool.submit(_run_read, item, execute) for item in batch["items"]]
                # 与原文 gather 对应：等待本批所有任务完成，再处理下一批。
                # 按提交顺序收集，所以即便读B先完成，结果仍按读A、读B排列。
                results = [task.result() for task in tasks]
            for item, (result, local_read_state) in zip(batch["items"], results):
                # 只有主线程合并文件读取时间，后面的写入才能使用这些记录。
                read_file_state.update(local_read_state)
                yield item["call"], result
        else:
            for item in batch["items"]:
                if not item["ready"]:
                    yield item["call"], item["result"]
                    continue
                # 写入、编辑、命令直接在当前线程执行。
                # 到这里，前一批的读取已经全部结束、读取记录也已经合并。
                result = _execute_checked(item, execute, read_file_state)
                yield item["call"], result
                # 下一批直到这里执行完才开始，因此写后的读取不会提前越过写入。
