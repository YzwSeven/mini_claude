"""先读这个文件：用户提任务 → 模型决定 → 执行工具 → 模型继续回答。"""
import json

from codex_backend import ask_model
from tools import execute_tool


def run_agent(messages):
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
                # arguments 是 JSON 字符串，把它还原成包含 path 的字典。
                arguments = json.loads(call["arguments"])
                # Agent 只把工具名称和参数交出去，不关心具体怎么读取文件。
                # tools.py 负责选择函数并执行，返回值仍是交给模型的结果文字。
                result = execute_tool(call["name"], arguments)
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


def main():
    # 这份历史在程序运行期间保留；退出后不会自动保存到硬盘。
    messages = []
    print("Mini Claude 已启动，输入 exit 退出。")

    # 外层循环等用户的新任务；run_agent 内层循环处理同一个任务。
    while True:
        try:
            user_input = input("你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if user_input == "exit":
            break
        if not user_input:
            continue

        # 先在历史副本中处理任务。网络失败时，不保留半截工具请求。
        # 这里只回退对话记录，不会撤销已经创建的文件；工具操作不是事务。
        turn_messages = messages.copy()
        turn_messages.append({"role": "user", "content": user_input})
        try:
            run_agent(turn_messages)
        except KeyboardInterrupt:
            print("\n已中断本轮，可以输入新任务。")
        except (RuntimeError, OSError, ValueError, KeyError, TypeError) as error:
            print("本轮失败：", error)
        else:
            messages = turn_messages


if __name__ == "__main__":
    main()
