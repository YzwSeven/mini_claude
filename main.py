"""先读这个文件：用户提任务 → 模型决定 → 执行工具 → 模型继续回答。"""
import json
import sys

from codex_backend import ask_model
from prompt import build_user_context_reminder
from session import load_session, save_session
from tools import execute_tool
from early_tools import EarlyTools


def run_agent(messages, read_file_state, thinking=False):
    """处理一个任务；只读工具可在 GPT 的流式窗口内提前执行。"""
    # 每次循环是一次模型请求，不是一条用户输入。
    # 如果 GPT 要用工具，执行并回传后还会继续循环；最多请求十次。
    for step in range(10):
        print(f"正在思考……第 {step + 1} 次调用", flush=True)
        # 记录本次尝试中已经流式显示过的输出编号，最终回复不再重复打印。
        streamed_items = set()
        # 每一轮都有独立的任务管理器；异常和退出也会清理线程。
        # early 是当前这一轮的“任务记录本”，不会跨模型请求复用。
        # 传入 execute_tool，使工作线程仍调用原来的工具入口。
        with EarlyTools(execute_tool) as early:
            def show_text(text, output_index):
                """文字即时显示；最终回复按编号避免重复打印。"""
                if not streamed_items:
                    print("助手：", end="", flush=True)
                streamed_items.add(output_index)
                print(text, end="", flush=True)

            def start_tool(call):
                """完整调用到达时，只调度只读工具；线程不会写入聊天历史。"""
                # 这是网络层稍后会调用的函数，不是 GPT 能直接运行的工具。
                # start 返回 True 表示任务交给线程池了，不代表读取已经完成。
                if early.start(call):
                    print(f"\n提前执行工具：{call['name']}（{call['call_id']}）", flush=True)

            def start_attempt():
                """失败后重新请求时，任务结果和文字去重记录都重新开始。"""
                # 每次实际发送请求前都会到这里，首次和失败重试都一样。
                # 旧任务清理完再接新请求，避免相同编号误领上一次结果。
                early.reset()
                streamed_items.clear()

            try:
                # 把三种通知处理函数交给 backend，再由网络层在合适时机调用：
                # show_text：收到文字；start_tool：完整工具请求到达；
                # start_attempt：一次发送/重试即将开始。
                # 传函数名称是“把联系方式交出去”，不是现在就执行它们。
                # ask_model 尚未返回时，工作线程可能已经开始读取文件。
                response = ask_model(
                    messages, on_text=show_text, thinking=thinking,
                    on_tool_call=start_tool, on_attempt_start=start_attempt,
                )
            finally:
                if streamed_items:
                    print(flush=True)
            # 执行到这里说明整轮模型请求成功完成。
            # 提前读取只是节省时间；最终仍以完整 output 为处理依据。
            output = response["output"]
            # 仍然只有整轮请求成功后，才接受完整历史和工具结果。
            # 保存模型自己给出的文字、工具请求和推理项，供下一轮继续使用。
            # 此时还没有追加本地工具结果；下面会按调用编号逐一配对。
            messages.extend(output)
            # 先从完整输出中找出工具请求，按模型给出的顺序收集。
            tool_calls = []
            has_text = False
            for output_index, item in enumerate(output):
                if item["type"] == "message":
                    for content in item.get("content", []):
                        if content["type"] == "output_text" and content["text"]:
                            if output_index not in streamed_items:
                                print("助手：", content["text"])
                            has_text = True
                elif item["type"] == "function_call":
                    tool_calls.append(item)
            # 没有工具请求且有回答，就说明本次用户任务已经结束。
            if not tool_calls:
                if not has_text:
                    raise RuntimeError("模型没有返回文字或工具请求，请重试。")
                return

            for call in tool_calls:
                print("调用工具：", call["name"], call["arguments"])
                try:
                    arguments = json.loads(call["arguments"])
                    # 按原文：先找这个调用已经提前启动的任务，找到就直接取结果。
                    # 当前调用即使是写入，也不清空其他读取任务。
                    result = early.take(call, read_file_state)
                    if result is None:
                        # 没有提前任务才正常执行；写入/编辑通常走这一条。
                        # 前后其他只读调用仍能领取自己的提前结果，不会被写操作清掉。
                        result = execute_tool(call["name"], arguments, read_file_state)
                except (ValueError, KeyError, TypeError, OSError) as error:
                    result = f"工具执行失败：{error}"
                print("工具结果：", result)
                messages.append({
                    "type": "function_call_output",
                    "call_id": call["call_id"],
                    "output": result,
                })
            # 结果按模型给出的顺序配对；下一轮再交回 GPT。
    raise RuntimeError("当前任务已达到 10 次模型调用上限，已暂停。")


def main(argv=None):
    # sys.argv[0] 是脚本名称；后面才是用户传入的参数。
    if argv is None:
        argv = sys.argv[1:]
    # --thinking 是启动选项，取出后不能混进用户的提问文字。
    thinking = "--thinking" in argv
    argv = [argument for argument in argv if argument != "--thinking"]
    if thinking:
        print("已开启加强思考：GPT 使用 high 强度。")
    resume = "--resume" in argv
    argv = [argument for argument in argv if argument != "--resume"]
    # 默认开始新会话；只有显式传入 --resume 才读取磁盘上的历史。
    messages = []
    if resume:
        saved = load_session()
        if saved:
            messages = saved
            print(f"已恢复 {len(messages)} 条历史记录。")
    # 记录这个 Agent 读过哪些文件，以及读取时的修改时间。
    # 它放在外层循环外，所以一次读取可供同一对话后续的编辑检查使用。
    read_file_state = {}
    # 恢复聊天历史不恢复文件读取权限；重启后编辑已有文件仍需重新读取。
    # 启动会话时读取一次项目规则和日期，后续通过消息历史保留。
    user_context_reminder = build_user_context_reminder()
    # 剩余参数组成一次提问；没有提问参数时进入交互式聊天。
    one_shot = " ".join(argv).strip()
    print("Mini Claude 已启动，输入 exit 退出，输入 /clear 清空会话。")

    # 外层循环等用户的新任务；run_agent 内层循环处理同一个任务。
    while True:
        try:
            user_input = one_shot if one_shot else input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if not one_shot and user_input in ("exit", "quit"):
            break
        if not one_shot and user_input == "/clear":
            # 对话和读取状态一起清空；下一次提问会重新携带项目背景。
            messages = []
            read_file_state = {}
            save_session(messages)
            print("会话历史已清空。")
            continue
        if not user_input:
            continue

        # 先在历史副本中处理任务。网络失败时，不保留半截工具请求。
        # 这里只回退对话记录，不会撤销已经创建的文件；工具操作不是事务。
        turn_messages = messages.copy()
        # 与对话历史一起使用副本；本轮失败时，不保留没有对应历史的读取记录。
        turn_read_file_state = read_file_state.copy()
        # 只在首条用户消息前加入背景；后续请求会携带已有历史，无需重复。
        # 使用本轮历史副本判断：如果首轮失败，下次尝试仍会正确加入背景。
        is_first_user = not any(message.get("role") == "user" for message in turn_messages)
        content = user_input
        if is_first_user and user_context_reminder:
            content = f"{user_context_reminder}\n\n{user_input}"
        turn_messages.append({"role": "user", "content": content})
        try:
            if thinking:
                run_agent(turn_messages, turn_read_file_state, thinking=True)
            else:
                run_agent(turn_messages, turn_read_file_state)
        except KeyboardInterrupt:
            print("\n已中断本轮，可以输入新任务。")
        except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
            print("本轮失败：", error)
        else:
            messages = turn_messages
            read_file_state = turn_read_file_state
            # 只保存完整成功的一轮，失败的半截工具调用不会覆盖磁盘历史。
            save_session(messages)
        if one_shot:
            # 单次模式执行完一个任务即退出；失败后也不重复执行同一输入。
            break


if __name__ == "__main__":
    main()
