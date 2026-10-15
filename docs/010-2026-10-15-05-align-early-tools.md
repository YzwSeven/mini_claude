# 010：按原文删除写操作前清空提前任务的逻辑

## 原教程出处与明确纠错

原项目 docs/05-streaming.md:456 流式工具执行；该节 Python 示例和 python/mini_claude/agent.py:1500、:1575。原文在只读且权限允许时启动任务；完整回复后按编号查找，有则 await 取结果并 continue，没有才权限检查与执行。

原文没有“遇到写入/编辑/命令就清空其他提前结果”，也没有“看到非只读请求后，禁止后面的只读工具提前启动”。这是此前助手额外添加的行为，不是 GPT 协议适配所必需。用户要求删除，本次纠正。

原文中 for task in early_executions.values(): task.cancel() 所在分支是预算超限停止处理（agent.py:1555），不是普通写入前的步骤。

## 文件与修改步骤

1. main.py：删除非只读调用时 early.discard() 的条件块；删除不再使用的 CONCURRENCY_SAFE_TOOLS 导入。最终处理每个调用直接 take；只有 None 才 execute_tool。写调用不干涉其他读取任务。
2. early_tools.py：删除 allow_early 字段及设置/判断。start 遇到非只读工具只 return False，跳过当前请求。后面的只读请求仍可提前执行。discard 注释明确仅用于重试或退出的剩余任务清理。
3. 008/009：移除把写前清空说成必要步骤的解释，纠正“后读必定是写后内容”的保证；同步改为原文有任务就用的流程。
4. 本篇记录纠错、实际数据流、验证和限制；索引从 010 连续编号。工作区原测试删掉旧的写后强制重读断言，改为验证原文行为。

## 按改后代码理解数据流

```python
arguments = json.loads(call["arguments"])
result = early.take(call, read_file_state)
if result is None:
    result = execute_tool(call["name"], arguments, read_file_state)
```

假设完整回复有 read1、write1、read2，两个读任务都可能已经在流中开始。处理 read1：取提前结果并保存读取状态；处理 write1：没有提前写任务，直接执行写入，不清空 read2；处理 read2：取它已经启动的结果，不再重新读取。每个结果按各自 call_id 放入 messages。

重点：这里按模型给出的顺序处理/追加结果，不代表后台任务开始时间同样按顺序。read2 若在写入之前完成，得到的是旧内容；若在写入后读取，可能是新内容。本次不凭空保证“同一批里写后面的读一定看到修改结果”，与原文一致。

通常根据内容修改的流程：第 1 次模型请求提出读取 → 领取结果放入 messages → 第 2 次模型请求看到内容，提出写入。上一轮文件内容和 mtime 已经保存，不会因为写入而删除。修改后确认：拿到写入结果再由下一次请求提出读取，才发生在写入之后。

## 保留的协议适配与未完成内容

保留 GPT Codex 完整 output_item.done 通知、同步线程池/Future、编号与参数匹配、重复事件去重、独立读取状态和失败尝试隔离。discard 仍用于重试与管理器退出，不能误解为还存在写前清空。没有新增模型 API 或参数，不涉及凭据。

这些管理细节不声称逐字等同原 Python asyncio；第六章权限系统仍未实现，提前入口仅有固定只读名单。官方 OpenAI Chat 路径仍待整轮结束执行。下一节并行工具执行未开始。

## 验证方式及结果

使用受控模拟 SSE：read1/write1/read2 的完成事件依次到达，响应完成前等待两个读任务都读到旧内容。验证 write1 不提前执行、read2 可以提前启动且最终只执行一次、两个结果都被复用、不会因写入重新读取。另验证分两轮读后写，文件内容回传后再执行写入及 mtime 保护保持。

重跑完整到达时序、重复事件、参数片段、断流/重试隔离和 GPT 后端/流式回归；检查 diff。全部通过：verify_early_tools.py 的受控时序、写调用不清空与真实文件跨轮读后写验证通过；verify_gpt_backends.py 与 verify_streaming_lesson.py 回归通过；git diff --check 通过。不调用真实模型，未提交、未推送。
