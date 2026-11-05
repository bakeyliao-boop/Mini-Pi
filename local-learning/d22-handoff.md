# D22 子 Agent 委派流程

D22 已完成有指导复盘，下一步进入 D23。2026-11-05 核对 Pi 上游 `main` 为 `a013448fb5e64b09588ea2b4aebeb2ab8cc34168`，固定阅读基准为 `7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`。本次使用 Git 获取并对照两版源码，以固定版的单次委派开始。证据来自源码，下面的折扣审查是教学推演。 [固定版示例](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/README.md) · [当日 main 示例](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/README.md)

## 从一次折扣审查开始

沿用 D14 的折扣修复场景。假设父 Agent 改好了 `discount.py`，希望另一个 Agent 检查「100 元减免 20% 后应实付 80 元」是否与改动一致。父 Agent 提供 reviewer 的名字和这段任务文字，审查者返回位置和理由。 [D14 任务记录](d14-acceptance-summary.md) · [D22 委派总图](../pic/day22-subagent-flow-20261105.png)

| 阶段 | 固定版 Pi 的行为 | 源码 |
| --- | --- | --- |
| 交出任务 | 父模型发出 `subagent` 工具调用，参数为 `agent=reviewer`、`task` 和可选的工作目录 `cwd`。单次入口调用并等待 `runSingleAgent`。 | [参数](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L459) · [单次入口](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L688) |
| 启动审查 | 从 Agent 定义读取角色提示、模型和工具列表。角色正文通过 `--append-system-prompt` 传入，新 Pi 进程以 `Task: ...` 开始，并通过 `--no-session` 使用内存会话。模型未指定时沿用父会话模型与思考级别。 | [Agent 发现](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/agents.ts#L128) · [reviewer 定义](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/agents/reviewer.md#L1) · [组装进程参数](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L300) · [内存会话](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/src/main.ts#L364) |
| 等待子进程 | 子进程逐行输出 JSON 事件。扩展从标准输出收集消息和模型用量，另记标准错误，处理关闭、启动错误和取消。 | [JSON 输出](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/src/modes/print-mode.ts#L108) · [接收事件](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L353) · [结束与取消](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L401) |
| 返回父流程 | 扩展取最近的助手文本作为工具结果正文，子消息与用量放在结果详情中。父循环按原工具调用 ID 生成工具结果消息，后续轮次据此继续。 | [提取文本](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L170) · [单次结果](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L701) · [工具结果配对](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/agent/src/agent-loop.ts#L930) |

子 Agent 的起始任务是传入的 `task`，因此父 Agent 先前读过的文件内容需要明确附在任务里，或由子 Agent 用工具重新取得。这里的 `cwd` 是子进程从哪个文件目录开始工作，省略时使用父会话目录。两个会话各管各的消息，默认仍能读到同一份 `discount.py`。Pi 示例 reviewer 声明的工具包括 `bash`，其只用读取命令的约束写在角色提示里。 [启动参数与目录](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L334) · [reviewer 定义](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/agents/reviewer.md#L1)

## 当日 main 的相关变化

- 单次委派仍以独立 Pi 进程执行，收集 JSON 消息，并把提取的文本交回父 Agent。角色配置现在按任务的有效 `cwd` 查找，指定相对目录时以父会话目录解析。 [目录解析](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/index.ts#L327) · [启动](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/index.ts#L494) · [单次结果](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/index.ts#L851)
- 当前实现区分启动失败、非零退出、信号终止和主动取消，并保留已收集的消息、错误与用量。取消时先尝试 `SIGTERM`，仍未结束时再尝试 `SIGKILL`。单次和链式返回给模型的正文增加长度限制，详情仍保留原结果。 [取消与收尾](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/index.ts#L475) · [状态分类](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/index.ts#L534) · [输出限制](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/index.ts#L234)
- 固定版单次失败返回顶层 `isError`。当前示例将失败标记写入 `details.isError` 并返回错误正文，当前 Agent 核心仍读取顶层 `isError` 生成工具消息的错误标志。这是两版的源码差异。 [固定版失败返回](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/index.ts#L701) · [当前失败返回](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/coding-agent/examples/extensions/subagent/index.ts#L862) · [当前核心读取](https://github.com/earendil-works/pi/blob/a013448fb5e64b09588ea2b4aebeb2ab8cc34168/packages/agent/src/agent-loop.ts#L854)

## Mini-Pi 的范围与验收

现有 `Harness`、`SessionStore`、`RunBudget` 和工具路由支撑单 Agent。D23 计划复用这些组件，给 reviewer 独立的 Agent、记录和预算。它的输入是目标、改动、测试结果与必要文件，工具配置为 `list_files` 和 `read_file`。D24 再由父流程串联 worker、独立测试、reviewer 和有限返工。串行能让审查针对 worker 写完并完成测试的那一版文件。 [Harness](../mini_pi/harness.py) · [D23 至 D25 路线](pi-learning-roadmap.md#d23-创建独立-reviewer-会话)

D22 的理解检查围绕一次完整交接，能指出任务文本和审查结果各走哪条路径，以及默认工作目录与会话的关系。D23 用独立会话记录和对编辑调用的拒绝验收消息与工具边界，D24 查验审查意见确实传回父流程，D25 用错误和取消用例检查收尾。

任务交接练习已写明审查文件、测试预期、观察值和反馈要求。固定版收到 `message_end` 时先收集消息并报告进度，子进程正常关闭后再组装工具结果。学习者已指出父 Agent 需要等工具结果传回，之后确认进程关闭与正式返回的时机。当前结合固定版源码阅读失败和取消。

学习者已区分 `subagent` 工具和由其启动的 Pi 子进程，并区分审查执行成功与审查发现问题。下一步用 D14 折扣例映射 Mini-Pi 的独立审查会话和工具配置。

2026-11-05 再次核对上游 `main` 为 `5732bac0607b9e72fed6b76b8db4a702e6af2c08`。固定版与该提交的 reviewer 定义一致，单次委派仍把任务、角色说明及工具选择传给 Pi 子进程。D23 计划用新的 `Harness` 组装独立 `Agent`，为其单独提供会话记录、预算及只含 `list_files`、`read_file` 的工具路由。该计划尚未实现。 [固定 reviewer](https://github.com/earendil-works/pi/blob/7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333/packages/coding-agent/examples/extensions/subagent/agents/reviewer.md#L1) · [核对时 main](https://github.com/earendil-works/pi/blob/5732bac0607b9e72fed6b76b8db4a702e6af2c08/packages/coding-agent/examples/extensions/subagent/index.ts#L358)

后续实现需核对两处已有行为。普通新会话的 `session_id` 目前只在自动摘要路径按需生成，不能把 `run_id` 当成已保存的会话编号。共用同一个 `QwenProvider` 对象会共享它的请求计数，因此 reviewer 的独立预算需明确提供者实例的归属。这两项留在 D23 的设计和验收中。 [会话编号](../mini_pi/session_store.py) · [模型请求计数](../mini_pi/qwen_client.py)

2026-11-05 完成 D22 的有指导复盘。学习者练习了委派任务，说明父 Agent 等待工具结果，区分工具与子进程，以及正常审查发现问题和执行失败。对独立会话、共享目录和工具限制已结合例子讲解，下一章继续验证其实现。 [D23 路线](pi-learning-roadmap.md#d23-创建独立-reviewer-会话)
