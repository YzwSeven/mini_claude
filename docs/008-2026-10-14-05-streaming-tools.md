# 008：GPT 流式工具提前执行

## 原教程出处与目的

原项目 docs/05-streaming.md:456 “流式工具执行”；Python agent.py:1500 提前任务管理，:1633 完整工具块回调。原文在一个工具块完整后启动只读工具，响应结束后复用已有任务，让读取与模型生成后续内容重叠。本项目仅接 GPT，事件对应为 response.output_item.done 中的完整 function_call。

OpenAI 官方事件参考：https://developers.openai.com/api/reference/resources/responses/streaming-events 。参数中间片段不执行，也不靠 JSON 恰好能解析来判断结束。默认 Codex 沿用项目已接通的 Responses 风格事件；这不是官方公共 API 对内部 endpoint 的兼容保证。

## 修改文件与逐步说明

1. codex_transport.py：send_request 增加可选 on_tool_call。output_item.done 先照旧保存 item；若为 function_call，就通知上层。文字和推理项不触发，完整 response.completed 返回逻辑与空 output 补齐保持。
2. codex_backend.py：ask_model 增加 on_tool_call 和 on_attempt_start；每次重试调用 send_once，先通知清理旧任务，再发送请求。仅 Codex 路径将工具回调传给 transport；官方 Chat Completions 仍等待整轮结束。
3. early_tools.py：EarlyTools 管理线程池与 tasks 字典，调用编号映射到（工具名称/完整参数签名，Future）。名单严格是 read_file、list_files、grep_search、web_fetch。start 校验完整参数为对象、编号非空、状态已完成；重复完成事件不重复启动。
4. _execute 在线程里调用原 execute_tool，使用独立 read_state。不会从工作线程写入聊天历史或共享读取状态。take 核对最终调用编号、名称、参数，匹配后等待 Future 并采用结果；只有此时合并读取记录。错误与原流程一样作为工具文字结果。
5. main.py：每轮用 with EarlyTools 管理任务；start_tool 接受完整事件并打印“提前执行工具”；start_attempt 清理重试缓存与文字编号。完整响应后仍按原顺序输出结果与 call_id 配对；有提前任务则 take，没有则正常 execute_tool。

## 完整执行流程

用户提问 → ask_model → 尝试开始清空提前缓存 → SSE 收到完整 read_file 调用 → 线程读取 → 主线程继续接收后续流 → response.completed → Agent 接受完整 output → 根据 call_id 取任务结果 → 合并本次读取状态 → 添加 function_call_output → 下一轮 GPT。

线程池最多四个工作线程，使用标准库，无新增依赖。Future 相当于“领取结果的凭条”，结果尚未完成时 take 会等待，完成了则直接取出。线程不负责打印和发送下一轮请求。

## 重试、失败与顺序

- 同一成功尝试的调用只启动一次，最终处理复用结果，不再执行第二次。
- 重试前取消排队任务、等待已启动只读任务、丢弃结果；下一次请求即便重复使用 call_id，也重新建立任务。失败尝试可能已经做了只读访问，不能声称整个重试期间工具物理上只执行一次，但这些结果不进入历史或读取权限。
- 整轮断流时，main 原有历史副本不会保存；提前任务使用独立状态，不把失败请求的读取记录混入会话。
- 按原文，回调只跳过当前非只读调用，不停止后续只读任务；最终处理每个调用时，有提前任务就直接领取，没有才正常执行。遇到写操作不会清空其他读取任务。此前额外添加的“写前整批清空”及 allow_early 停止调度已于 010 删除。
- 完成事件与最终回复名称/参数不同则不采用缓存。只有最终回复中被消费的任务才能更新读取状态，最终没有出现的请求结果全部丢弃。
- Python 不能强行中止已运行的线程；取消和退出可能要等待只读工具返回。网络工具沿用自身超时，目录读取等耗时仍由原工具实现决定。

## 原文差异、权限与未完成部分

原文异步 asyncio.Task；本项目同步网络与工具，所以用 ThreadPoolExecutor/Future 实现同一重叠执行机制。原文使用权限检查，当前项目尚未实现第六章权限系统，本节只有固定只读名单，不能称为完整权限实现。第六章接入后，提前入口也必须通过相同权限判断，不允许旁路执行需要确认的调用。本次不提前添加完整后续章节。

仅默认 GPT/Codex 路径提前执行。官方 OpenAI Chat Completions 没有相同的单项结束事件，不擅自推测工具参数是否完成，保持请求结束后执行。工具定义、参数、读取结果截断、mtime 保护与本地规则语义不变。下一节“并行工具执行”尚未实现一般批量调度，不能把这里四个只读任务的提前运行当作全部完成。

## 直接测试与验证

运行 `python main.py`，直接问“读取 main.py 和 codex_backend.py，比较它们的作用”。若模型流中给出完整读请求，会先看到“提前执行工具”，随后正常显示工具结果和回答。模型也可能先用 list_files，仍属于提前名单。这里只读访问真实网页也沿用 web_fetch。

离线通过受控模拟 SSE 和线程事件验证：完整请求在响应结束前执行、重复完成事件只一次、参数片段不执行、写/编辑/命令不提前、结果 call_id 配对、暂存读取记录仅成功采用后合并、断流和重试隔离、写操作不清空其他提前结果、未匹配任务丢弃、两条 GPT 路径和流式回归。以上验证全部通过；工作区 verify_early_tools.py 验证受控时序和状态隔离，verify_streaming_lesson.py 与 verify_gpt_backends.py 回归通过，git diff --check 通过。不读取登录或调用真实模型。


2026-10-15 纠正：原文不保证同一批中位于写调用之后的提前读取一定看到写后的文件。若需要模型根据读取内容决定如何修改，通常是读结果回传后，下一次模型请求再提出修改；若要验证修改内容，应在修改结果回传后的下一次请求中读取。当前实现不再擅自给原文增加写前清空规则，详见 [010 纠正记录](010-2026-10-15-05-align-early-tools.md)。
