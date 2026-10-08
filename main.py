"""先读这个文件：用户提任务 → 模型决定 → 执行工具 → 模型继续回答。"""
import json
import sys

from codex_backend import ask_model
from prompt import build_user_context_reminder
from session import load_session, save_session
from tools import execute_tool


def run_agent(messages, read_file_state):
    """完成一个用户任务。一次任务可能需要多次请求模型。"""
    # 这就是 Agent 的内层循环。限制次数，防止模型一直要求调用工具。
    for step in range(10):
        print(f"正在思考……第 {step + 1} 次调用", flush=True)
        response = ask_model(messages)
        output = response["output"]

        # 保存模型完整输出：既有说给用户的文字，也可能有工具调用。
        # 不要再单独添加一条 assistant 消息，否则会重复保存回答。
        messages.extend(output)
        tool_calls = []
        has_text = False

        for item in output:
            if item["type"] == "message":
                # 一条消息可以包含多个内容块；这里只显示回答文字。
                for content in item.get("content", []):
                    if content["type"] == "output_text" and content["text"]:
                        print("助手：", content["text"])
                        has_text = True
            elif item["type"] == "function_call":
                # 模型说“我要用这个工具”。现在还没执行，先收集起来。
                tool_calls.append(item)

        if not tool_calls:
            # 没有下一步行动请求，本轮就结束，回去等待用户的新任务。
            if not has_text:
                raise RuntimeError("模型没有返回文字或工具请求，请重试。")
            return

        for call in tool_calls:
            print("调用工具：", call["name"], call["arguments"])
            try:
                # arguments 是 JSON 字符串，把它还原成工具需要的参数字典。
                arguments = json.loads(call["arguments"])
                # Agent 只把工具名称和参数交出去，不关心具体怎么读取文件。
                # 同一份读取状态也交给 tools.py，用来保护后续写入和编辑。
                result = execute_tool(call["name"], arguments, read_file_state)
            except (ValueError, KeyError, TypeError, OSError) as error:
                # 参数错误也作为结果交回模型，让它有机会修正请求。
                result = f"工具执行失败：{error}"

            print("工具结果：", result)
            # print 只能让用户看到；放进历史，下一次请求模型才能看到。
            # call_id 把这个结果与模型刚才的那次工具请求对应起来。
            messages.append({
                "type": "function_call_output",
                "call_id": call["call_id"],
                "output": result,
            })

        # 循环回到 ask_model：这次历史里已经包含了工具执行结果。
    raise RuntimeError("当前任务已达到 10 次模型调用上限，已暂停。")


def main(argv=None):
    # sys.argv[0] 是脚本名称；后面才是用户传入的参数。
    if argv is None:
        argv = sys.argv[1:]
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
