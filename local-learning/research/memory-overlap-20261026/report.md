# Mini-Pi 记忆提取分类交集：四仓源码核对与首版建议

> 历史快照：本文与同目录H4补充报告保留2026-10-26各审阅时点的状态，包括“尚未实现”的当时描述。后续见[v2.2两例定向结果](../../memw-reference-v22-results.md)和[MEM-04首版技术验收](../../mem04-acceptance.md)；不回改旧结论或成绩。

核对日期：2026-10-26（北京时间）。本报告只研究和建议，不修改 Mini-Pi 实现、提示、样本或冻结评分；未调用真实模型、评审或付费 API，未读凭据，未执行历史工具或写业务记忆库。四仓 SHA 与逐项证据见下表及 [Claude](claude.md)、[Codex](codex.md)、[Pi/红熊](pi-bear.md) 审计。以下“推荐”是 Mini-Pi 设计判断，**不是任一上游的统一规则**。

## 本地问题与既定边界

当前 [提示](../../../mini_pi/memory/extraction_client.py) 让模型只提出 `content/proposed_route/reason`，程序核对 Scope 并绑定完整 Source；[归组函数](../../../mini_pi/memory/selection.py) 只按建议标签形成五组，不裁判正文是否受 Source 支持，也不执行写入。`task_constraint` 已由用户定为**原任务相关材料**，包括要求、进度和执行观察。Scope 只有用户与项目，尚不能证明候选属于正在进行的任务；MEM-04 Context 消费尚未实现。五出口、三字段及不接 `task_state`/`retain_project_events` 是本轮约束。

冻结的 [S3 样本](../../../examples/fixtures/memory_s3_acceptance_v2.json) 和 [真实验收](../../../local-learning/memw-s3-acceptance-results.md) 记录 2026-10-26 三次定向调用：技术 3/3，正文 5/5，严格路由 4/5，整轮未通过。A-U2 的正文“用户猜测 v2 测试应该通过了，但确认尚未运行”忠实，模型却建议 `task_constraint`；预先固定的准则要求 `needs_review`。三个指代单元本轮均保留未知方案或已给流程的关键信息。旧 v1 六次、v2 旧输出离线 8/9 与本轮 4/5 是不同证据，不能相加或回改。三次授权已经用完。

## 四仓对照

| 仓库与 2026-10-26 核对提交 | 源码输入 → 输出和处理 | 与分类交集的关系、证据边界 |
| --- | --- | --- |
| [Claude Code `2eff7a8d21c80be48904f62ebdea36d945d7b504`](https://github.com/anthropics/claude-code/tree/2eff7a8d21c80be48904f62ebdea36d945d7b504)：见 [独立审计](claude.md) | [agents-md `register`](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/mods/agents-md/hooks/register.ts#L99-L165) 接收 `prompt.context` 的 instruction files 并合并 AGENTS.md；[公开接口](https://github.com/anthropics/claude-code/blob/2eff7a8d21c80be48904f62ebdea36d945d7b504/mods/types/claude-code.d.ts#L8845-L8884) 声明会话压缩钩子。 | **已实际源码核对**的是插件、mod 和接口；公开仓库未提供 auto memory 提取提示/路由/验证链。`user/feedback/project/reference` 四类仅见[官方 Memory 文档](https://code.claude.com/docs/en/memory#auto-memory)，属于已选记忆主题，**不是源码核实的五出口优先级**。引擎内部行为尚缺证据。 |
| [Codex `970111f6cb62cc02fe36a82ea7d71b37a2889c97`](https://github.com/openai/codex/tree/970111f6cb62cc02fe36a82ea7d71b37a2889c97)：见 [独立审计](codex.md) | [MemoryTool 默认关闭](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/features/src/lib.rs#L1335-L1340)。启用后按[配置条件](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/core/src/config/mod.rs#L3659-L3672)选 v1/v2；[Phase 1 `job::sample`](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/memories/write/src/phase1.rs#L258-L321) 从受限 rollout 取摘要，v1 schema 含 `raw_memory/rollout_summary/rollout_slug`，v2 只含后两者；[Phase 2](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/memories/write/src/phase2.rs#L50-L225) 再整合长期文件，读取注入和当前会话 compaction 另有链路。 | **已实际源码核对**的是条件启动和两版提示/schema，未运行此管线，不能外推桌面版开关。v1 提示的 `success/partial/uncertain/fail` 是任务结果分析，[v2 提示](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/memories/write/templates/memories/stage_one_system_v2.md#L1-L52) 主要要求保留猜测/未验证状态；两版均无 Mini-Pi 五出口优先级。官方 Docs 仅补充产品术语，非源码保证。 |
| [Pi `d5b3de22d0e24a3e9c38a9410d3329b099717283`](https://github.com/earendil-works/pi/tree/d5b3de22d0e24a3e9c38a9410d3329b099717283)：见 [独立审计](pi-bear.md) | [`buildContextEntries`](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/session-manager.ts#L469-L583) 从原始 Session 树投影最近压缩摘要和保留尾段供模型继续；[`compact`](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/compaction/compaction.ts#L507-L575) 对旧消息归纳目标、约束、进度、决策和下一步。 | **已实际源码核对**的是会话续接摘要，未见内建同构五出口或跨会话候选选择器。约束与进度可同处摘要，不构成二者路由优先级。路线固定基准仍为 `7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`，本次 main 没有替换它。 |
| [MemoryBear（红熊 AI）`60bb78568796a75d8ecfae8323a9b26d68f47142`](https://github.com/SuanmoSuanyangTechnology/MemoryBear/tree/60bb78568796a75d8ecfae8323a9b26d68f47142)：见 [独立审计](pi-bear.md) | [`StatementClassifier`](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/steps/statement_classification.py#L136-L193) 对 statement 文本分别产出 `statement_type/temporal_type/has_unsolved_reference`；[`WritePipeline` 的 P1 偏好分支](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/pipelines/write_pipeline.py#L345-L368) 并行从当前 user 消息选可跨任务复用的 Coding 偏好。 | **已实际源码核对**的是不同轴及不同分支，非互斥单出口。`FACT` 表示陈述类型，并不保证已核实；未解指代限制三元组生成是[提示要求](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/utils/prompt/prompts/extract_triplet.jinja2#L410-L427)，不是程序强制跳过或删除全部陈述。P1 排除一次性任务，不能外推普通写入。未运行服务，效果尚缺证据。 |

“已实际源码核对”只指读到的固定 SHA 文件和静态调用链；提示要求不等于模型实际遵守，代码路径不等于当前产品所有版本启用。Claude 文档、若有的产品说明另标“仅官方文档”。未运行四个上游的模型/服务，因此没有四仓运行效果数据。

## 交集判定：先保真，再决定首个处理去向

**首版推荐（Mini-Pi 推断）：维持单个 `proposed_route`，将它明确定义为“这条候选接下来主要如何处理”，而非事实类型或权限。** 一条 Source 含多个独立意思时先拆成候选，完整 Source 仍由程序绑定；每条正文必须保留猜测、否定、条件、未运行、所指缺失及观察范围。对“可用于判断结果/执行动作的关键命题”若仍缺证据或所指内容，则优先建议 `needs_review`，即使它也与原任务有关。这里是 `task_constraint` 与 `needs_review` 的**局部交集规则**，不是五出口的全局排序，也不按“猜/之前”关键词机械分流。

| 反例 / 正例 | 忠实候选的关键点 | 建议首个去向及原因 |
| --- | --- | --- |
| “我猜 v2 测试通过了，但还没运行” | 用户的猜测状态是可确认的；“测试通过”仍未被运行证明。 | `needs_review`：若后续要使用测试结果，必须先核对；保留已知的猜测与未运行事实。符合冻结 A-U2 标准。 |
| “如果测试通过，再部署” | 这是已明确的**条件式要求**，没有声称条件已经成立。 | `task_constraint`：保存条件本身，不能改写为已通过或可立即部署。 |
| “部署照之前那个方案”，本条没有方案 | 保留沿用意图，同时写出**本次材料缺少方案细节**；不能推断用户从未确定方案。 | `needs_review`：执行所需的所指未解析。若同条已经给出步骤，则正常 `task_constraint`。 |
| 经程序绑定为真实工具执行结果的日志：v2 discount 测试 3 项、1 失败 | 是一次有来源的执行观察；不扩大成永久失败或要求测试失败。 | `task_constraint`：原任务材料可包含观察；项目匹配仍不足以证明当前任务归属。用户粘贴的示例日志或 assistant 转述不能伪装成已执行的 tool Source。 |
| “我听说部署已成功，尚未核对” | 报告来源和核验状态都要留在正文。 | `needs_review`：不能作为已成功的事实供后续执行。 |

这条规则的关键是**未决事项是否挡住对候选所声称结果/步骤的安全使用**。它不把所有含条件、引述、用户主观状态或工具记录的候选一律待核对，也不把 `task_constraint` 解释成强制命令。尤其 A-U2 在“记录用户猜测”这一狭义用途下确有任务相关性；选择 `needs_review` 是本项目当前单出口、冻结验收和后续可能使用测试状态的取舍。**待核对的是测试结果，不是用户是否说过猜测。**未来如果消费方只需要引用用户猜测，可从原 Source 按限定展示；当前还没有自动 Context 消费能力来验证这一行为。

同理，“部署照之前那个方案”是确定的沿用意图，但关键所指未知。放入 `needs_review` 只能阻断将未知方案当可执行细节，**不能丢掉沿用意图**。若将来 MEM-04 只读取 `task_constraint` 而静默丢弃 `needs_review`，此首版路由会丢失已知要求；MEM-04 必须定义待核对候选如何作为待澄清事项进入当前任务。Source 保留也不能替代这一尚未实现的消费门禁。

## 方案比较与实施边界

| 选择 | 得到什么 | 主要反例 / 首版结论 |
| --- | --- | --- |
| 全局固定优先级 `needs_review > task_constraint` | 规则短，A-U2 会落待核对。 | 会把“若测试通过才部署”误当作不完整要求，也可能把明确的工具失败观察误判为可疑；**不推荐**。 |
| 只看正文保真、允许两出口集合 | A-U2 的两个标签都可解释为“任务相关”。 | 两组未来消费用途不同；事后给 A-U2 放宽 `gold` 违反冻结标准。只能在未来**预先定义**的不同消费契约中考虑，当前不采纳。 |
| 增加 `evidence_status`、多标签或独立 `task_state` | 可分别表达用途、证据状态和任务阶段。 | 会扩充三字段、五出口及消费层；当前尚无必要性证据，不在首版实施。若单出口将来导致确定的误用，再据反例评估。 |
| **按候选的主要后续处理和阻塞缺口判断** | 保留五出口，显式处理 A-U2，同时让条件要求和已观察失败保持任务材料。 | 依赖模型语义判断，提示不能保证正确；建议作为下一版提示/人工验收口径，严格保持现轮未通过，不声称已修复。 |

若用户随后批准实现，本次建议的**最小范围**是澄清 `needs_review` 与宽 `task_constraint` 的局部冲突规则、提供上表正反例，并更新相应未来样本的预先标注及人工评阅说明。`route_candidates` 继续只归组；无需新增出口、保留开关、长期写入门禁或关键词分类器。不能把旧练习 `build_retention_instruction` 接到现行请求里。任务归属/版本校验及 Context 注入留给 MEM-04 另行定义，不能通过此次改提示假称完成。

## 可执行验收计划（尚未执行）

1. **先冻结新样本与标准**：同一材料混合明确要求、未运行猜测、缺失指代；另列已解析指代、确定条件式要求、真实工具失败观察、第三方未核实说法。逐单元预标注正文必保留点、允许拆分、唯一主要去向及禁止推断；旧样本和分数保持原样。
2. **本地零调用检查**：核对请求只带规则/原 Source，不带 gold；解析接受正常 JSON、拒截断/工具/拒答/格式错；Source/Scope 不被模型伪造；固定响应仅检验接线和归组，不算语义成功。
3. **未来另获预算后才做真实复验**：预定模型、样本、次数与停止规则；分别报告技术完成、正文保真、路由、整案通过。对失败保留原请求/响应和人工理由，不临时放宽 gold 或自动追加调用。现有授权余额为 0。
4. **MEM-04 消费门禁另验**：带可信任务标识匹配后才供原任务消费；`needs_review` 要保留并呈现已知意图与待澄清点，不能被静默丢弃，也不能作为已通过结果或完整部署步骤；`task_constraint` 中观察不转成指令；完成显式规划前不写长期库。以上目前是设计前提，**尚非已实现行为**。

## subagent 交叉质疑与结论边界

三名 subagent 各自读仓库后互读审计、审查上述建议，提出以下反例，已在结论中吸收：

1. **Claude 审查 Codex/红熊**：Codex v1 `uncertain` 是任务结果分析，v2 没有此输出枚举；红熊 `FACT`/未解指代是并列轴，P1 偏好另起分支；Claude 文档四类是已入选的记忆主题。不能把其中任何词直译为 Mini-Pi 的去向优先级。A-U2 若只记录“用户确实猜过”，这一说话事实不需再核实；本项目要核实的是被猜测的测试结果。后者及冻结标准才支持本轮 `needs_review`。
2. **Codex 审查单出口建议**：“部署照之前那个方案”同时有确定的指令意图和未知所指。`needs_review` 不能使沿用意图消失；MEM-04 必须消费待澄清候选，而不把它当可执行方案。Codex v2 提示支持保留缺口，但不规定 Mini-Pi 路由。
3. **Pi/红熊审查来源**：有来源的测试失败须是实际工具结果且对应原任务/版本。用户贴的外部示例日志即便全文保存，也不证明本任务已运行；完整 Source 与事实核验不能混为一谈。确定条件式要求保留条件，原任务内仍可 `task_constraint`。

分歧不通过“多数同意”消解：四仓源码共同支持**会话、摘要、证据状态、长期选择不可混作一个标签**，但都未给出本项目五出口的唯一优先级。因此以上局部规则只以 Mini-Pi 的已确认契约、预冻结样本、真实响应和下游消费风险为依据。现有 4/5 的未通过结论保持不变；未来提示或消费层修改尚未实施、未验收。
