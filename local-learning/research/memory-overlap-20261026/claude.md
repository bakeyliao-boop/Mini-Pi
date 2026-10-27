# Claude Code 记忆分类交集：公开证据审计

核对日期：2026-10-26（北京时间）。官方仓库 `anthropics/claude-code` 的远端 `refs/heads/main` 与本地浅克隆 `HEAD` 均为 [`2eff7a8d21c80be48904f62ebdea36d945d7b504`](https://github.com/anthropics/claude-code/tree/2eff7a8d21c80be48904f62ebdea36d945d7b504)（提交时间 2026-10-25 20:11:24 UTC）。以下不代表用户本机安装的 Claude Code 版本。此次未运行 Claude Code、模型或付费 API。

## 公开源码实际覆盖范围

| 源码证据 | 输入 → 输出 / 能确认的行为 | 边界 |
| --- | --- | --- |
| [`README.md:48–59`](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/README.md#L48-L59) | 仓库说明这里提供可扩展 Claude Code 的插件。 | 未声称发布 CLI 引擎全部源码。 |
| [`mods/README.md:3–18`](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/mods/README.md#L3-L18) | 公开四个随二进制内置的 mod：`sec-default`、`diff`、`telemetry`、`agents-md`，入口是 `register(on, options)` 钩子。 | 公开的是四个 mod 的实现，不是 auto memory 选择器。 |
| [`mods/agents-md/hooks/register.ts:99–165`](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/mods/agents-md/hooks/register.ts#L99-L165) | `prompt.context` 取得引擎交来的 `instructionFiles`；按项目是否已有 `CLAUDE.md` 查找 `AGENTS.md`，以 `Files.withProjectFiles` 合并后传给 `next`。 | 这是**指令文件加载**，不是从 Session 抽取事实，也无五出口优先级。 |
| [`mods/types/claude-code.d.ts:1915–1929`](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/mods/types/claude-code.d.ts#L1915-L1929)、[`:4650–4685`](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/mods/types/claude-code.d.ts#L4650-L4685) | 类型声明将 `CLAUDE.md`、规则文件和 auto-memory 条目称作进入 Context 的 memory file；`InstructionFileKind` 是 `managed/user/project/local/memory`。 | 这是公开钩子**接口类型**，不提供何时提取、如何验证或写入 auto memory 的实现。这里的 `kind=memory` 也不是 Mini-Pi 的 `long_term` 路由。 |
| [`mods/types/claude-code.d.ts:8845–8884`](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/mods/types/claude-code.d.ts#L8845-L8884) | `session.compact` 钩子输入有 `trigger`、`messages`、可选 `instructions`，输出为压缩后的消息或 `{skip}`。 | 能证明压缩作为会话流程的独立接口，不能证明压缩摘要被选入跨会话记忆。 |

对本提交的 1615 个跟踪文件做路径盘点，并在 `mods/` 内搜索 `autoMemory`、`memory.md`、`memory extraction`、`extract memory` 等词，只发现接口说明和旁支引用；没有找到 auto memory 提取提示、候选 schema、路由函数或测试。**结论限于这份公开仓库**：不能从源码给出 Claude 的记忆分类交集优先级、失败/未验证内容策略或模型调用链，不能把官方文档当作隐藏实现的证明。

## 官方文档补充，均非上述源码保证

| 文档证据 | 文档所述行为 | 与本题的关系 |
| --- | --- | --- |
| [Memory 文档：两种跨会话机制](https://code.claude.com/docs/en/memory) | `CLAUDE.md`/`AGENTS.md` 是人写的持久指令；auto memory 是 Claude 写的学习记录。两者作为 Context 加载，不是强制配置。 | 将“用户指令”与“系统自己记下的事实”分开；不定义 Mini-Pi 五出口。 |
| [Memory 文档：Auto memory](https://code.claude.com/docs/en/memory#auto-memory) | 文档列四个 frontmatter `type`：`user`、`feedback`、`project`、`reference`；`project` 可以包含代码或 Git 历史无法推出的持续工作、期限、决定。文档说按未来会话是否有用来选择，不保证每次都写，跳过可从代码推得或 `CLAUDE.md` 已载明的内容。 | 这些 `type` 是**已选择的记忆内容类型**，既不是候选保留/待核对/忽略的决策，也不是不确定性的置信度轴。不能拿 `project` 直接映射 `task_constraint` 或 `long_term`。 |
| [Memory 文档：存储与加载](https://code.claude.com/docs/en/memory#storage-location) | 每仓库自动记忆目录含 `MEMORY.md` 索引和主题文件；索引首 200 行或 25KB 于会话开始加载，主题文件按需读；Claude 可在会话中读写。 | 证明文档描述了跨会话持久层及索引消费，未说明对未证实猜测的自动裁决。 |
| [Sessions 文档：保存与恢复](https://code.claude.com/docs/en/sessions) | 会话作为项目关联的本地 transcript 持续保存，恢复时带回消息、工具调用及结果；压缩过时从摘要和未摘要消息继续。 | 原 Session 与经挑选的持久记忆是两类数据；`ignore` 不应被类比成删除 transcript。 |
| [Context window 文档：压缩](https://code.claude.com/docs/en/context-window#what-survives-compaction) | `/compact` 用结构化摘要替换当前上下文历史；auto memory、项目根指令从磁盘重新注入。 | 摘要是当前会话的上下文机制，不等同 auto memory 提取。 |

文档页面在 2026-10-26 读取，页面未绑定上述 Git SHA；部分说明明确有版本门槛。因此只能记为**当前官方文档表述**，不能推断该 Git 提交或用户安装版本内部逐行如此实现。

## 对 Mini-Pi 两个争议单元的审查意见（推断，不归于 Claude）

- **A-U2**：“用户猜测 v2 测试应该通过，但尚未运行。”内容是真实的*猜测状态*，不是测试通过事实。Claude 公开源码和文档都没有给 `needs_review` 相对 `task_constraint` 的优先级。依本项目已冻结的 [五单元验收规则](../../../examples/fixtures/memory_s3_acceptance_v2.json)，实际结果尚缺证据，路由应为 `needs_review`；若改用宽 `task_constraint` 也必须先改定义与验收，不能把本轮 4/5 回算为通过。正文已保真，问题局限在路由。
- **S4**：有 Source 的工具日志已经观察到 v2 discount 测试 3 项中 1 失败。这是*已发生的失败观察*，不是对未来结果的猜测。按本项目宽 `task_constraint`，可作为原任务材料分组；这不授予执行权限或长期记忆写入，也不自动证明当前正在处理的任务与该日志归属相同。Claude 的 `project` auto-memory 类型不能用来强制它进入长期记忆。
- **类比风险**：Claude 的四种 auto-memory `type`、指令文件 `kind`、会话摘要和 Session transcript 位于不同流程。若把它们合成一套 Claude 官方“分类优先级”，会把文档名词误当成同一候选路由 schema。Mini-Pi 只允许 `content/proposed_route/reason` 和五出口时，分类交集及保真规则应由本项目明确制定；Claude 公开证据仅支持“区分会话、压缩、指令、跨会话记忆”这一结构性参考。

## 尚缺证据

Claude Code 引擎中的 auto memory 候选提取 prompt、调用时点、验证逻辑、写入判定、不确定性处理及冲突优先级均未在此次官方公开仓库找到。未运行安装版行为试验；即使运行，也只能证明对应版本和样本的观察结果，不能补出隐藏源码契约。
