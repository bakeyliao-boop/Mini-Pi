# H4 跟进：明确沿用意图，配置所指仍未解

日期：2026-10-26。范围仅为只读研究与建议；未修改 Mini-Pi 代码、提示、fixture、评分或 D13 现场，未调用模型/评审 API、执行历史工具、读取凭据或写业务库。复用此前 [四仓固定 SHA 源码审计](report.md)，本轮没有无目的重查远端 `main`。三个 subagent 的独立审查与反例见 [Pi/红熊](h4-source.md)、[Codex/Claude](h4-route.md)、[冻结验收反例](h4-adversary.md)。

## 实际发生了什么

| 层次 | H4 证据与结论 |
| --- | --- |
| 冻结输入/判据 | [v2.1 fixture 的 H4](../../../examples/fixtures/memory_overlap_acceptance_v21.json) 仅含“预发环境的限流参数继续沿用会议里那一版。”；H4-U1 预先要求正文同时保留沿用意图和“本条材料没有该版具体参数、所指待核”，唯一允许 `needs_review`。不能据此断言会议从未定过参数。 |
| 实际发送/返回 | [request-04](../../evidence/memw-overlap-v21-live-20261026-01/request-04.json) 只有 system 规则和该条 `role/recorded_at/text`，没有会议纪要、前后消息、可辨认的版次或工件指针。真实响应正常 `stop`，正文只复述沿用意图，去向 `task_constraint`；理由称“未涉及猜测或需核验的冲突”。**没有编造参数值**。 |
| 现行链路 | [EXTRACTION_PROMPT 第 24–80 行](../../../mini_pi/memory/extraction_client.py) 已说“只根据这条原消息”，第 59–60 行也要求缺少前文、无法解析执行所需配置时 `needs_review` 且正文写缺口。[解析](../../../mini_pi/memory/extraction.py) 核 JSON/来源形状；[归组](../../../mini_pi/memory/selection.py) 只按模型标签分组，不能补做语义裁决或会议检索。 |
| 验收状态 | [人工评阅](../../evidence/memw-overlap-v21-live-20261026-01/semantic-review.json) 判 H4 正文、路由各失败；[整轮验收](../../evidence/memw-overlap-v21-live-20261026-01/acceptance.json) 技术 6/6、正文 6/7、路由 6/7、严格 6/7、整案 5/6，整体未通过；[证据核对](../../evidence/memw-overlap-v21-live-20261026-01/evidence-check.json) 确认 6 次请求与冻结样本匹配、gold 未入请求。本轮 6 次授权已用完。旧 S3 真正 4/5 和 v2 旧输出离线 8/9 均是不同数据，不改分或合并。 |

**H4 不是“用户意图不清”**：用户确实要求预发沿用某个会议版本。缺口是**当前单条提取输入无法辨认应沿用的具体配置**。因此本轮存在两个独立的语义失败：`content` 没写“本条材料缺少所指参数”；`proposed_route` 把先需解引用的候选放进了原任务材料组。仅修改标签或仅在 `reason` 提到缺口，均达不到冻结验收的正文要求。完整 Source 绑定不能自动修补候选正文，因为后续可能只消费正文。

## 是未解指代，还是后续检索职责？

两者处在不同阶段。**提取阶段**只收到一条 Source，必须忠实表达“沿用意图已知、所指尚未从本次输入定位”。**后续阶段**可以在得到可信任务上下文和权限后查会议纪要或配置工件，再核对版本、值和适用环境；MEM-04 及该检索门禁目前未实现。不能因为未来或许能找到会议版，就在本次候选中宣称参数已知；也不能因本条缺参数就说会议从未确定过。

既有上游只能支持这个**分层思路**，不能替 Mini-Pi 决定唯一出口：Pi 把[原始 Session](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/session-manager.ts#L976-L985)与[摘要/当前 Context 投影](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/session-manager.ts#L469-L583)分开；MemoryBear [target/context 抽取提示](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/utils/prompt/prompts/extract_statement_temporal.jinja2#L20-L48) 允许可信上下文消解 target 已有指代、不能借上下文生造新事实，[分类](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/steps/statement_classification.py#L136-L193) 又把未解指代与陈述类型分轴。Codex [v2 提取提示](https://github.com/openai/codex/blob/970111f6cb62cc02fe36a82ea7d71b37a2889c97/codex-rs/memories/write/templates/memories/stage_one_system_v2.md#L1-L52) 要保留未决状态，但没有五出口；Claude 公开仓库未给出 auto memory 提取器的核心源码，官方文档不能证明 H4 路由实现。上述源码/提示也未在本侧实际运行。

## 首版最小判准与反例（建议，未实施）

建议将局部交集规则表述为：**对一条独立候选，先判断本次输入是否给出可辨认的执行目标或明确的取值步骤。若只是引用一个无法定位的外部版本，而执行要依赖该版本，正文须保留已知意图和“本条材料未提供可辨认配置”的缺口，首要去向为 `needs_review`。** 这不是按“那版/之前”关键词，也不是“凡未列出数值就待核对”。

| 对照输入 | 首版拟定处理，均未实测 |
| --- | --- |
| H4 原句；无会议标识、参数、工件指针或取值步骤 | `needs_review`；“希望预发沿用会议版；本条未给出可定位的版次/参数，须先核对所指”。这是冻结判据，不回改。 |
| 同条明确“会议版 QPS=120、并发=40”，或给出可唯一寻址的仓库/文件/profile/提交标识 | 可 `task_constraint`，正文保留具体值或指针，**不声称**文件已读、已存在或获批；执行前仍核值与权限。数值纯为构造反例，并非 H4 事实。 |
| “部署时使用指定仓库 `main` 当时的 HEAD 中指定配置，并先读取确认” | 若仓库、文件和动态选择时点都说清，是明确的**动态规则**，可为 `task_constraint`；不能仅因非不可变 SHA 就待核对。漂移和可访问性由执行前门禁检查。 |
| “先查指定会议纪要第 3 节，确认参数后再改预发” | 若纪要本身可辨认，“先查、确认、再改”是明确条件式要求，可 `task_constraint`；不能把未知参数编入正文。若纪要仍无法辨认，可将明确的查核要求与未解对象分开保留。 |
| “先不要改配置；限流沿用会议那版”，而会议版仍不明 | 独立的“暂不改”可 `task_constraint`，未解版次另 `needs_review`；不能用一个标签吞掉另一条已知要求。 |
| “那一版已经审批”但本条无审批记录 | 沿用要求与**未核实的审批结果**分开判断；精确工件指针也不等于审批已获证。 |

**判准的限制**：独立、可寻址的指针让“用户要求使用哪个对象”更清楚，不证明目标存在、可读、值安全或审批完成；这些要到实际消费/执行前核对。反过来，H4 连唯一指针或明确取值步骤也没有。`needs_review` 必须保留“沿用会议版”的已知意图并形成待澄清项，不能在 MEM-04 静默丢弃。`task_constraint` 从不授予修改限流配置的权限。

## subagent 交叉质疑后收敛的意见

1. **反例审查对原建议的修正**：不能把“必须给不可变版本 ID”写成规则；用户明确指定“执行时取最新版”是清楚的动态选择规则。也不能因读取尚未发生，就把所有精确指针一律降到 `needs_review`。若读取失败或指针冲突，那是新的阻塞事实，应在消费阶段另行待核对。
2. **源码审查对来源的限制**：Pi/MemoryBear 支持区分原文、辅助上下文和未解指代维度；Codex/Claude 也区分会话、摘要与持久记忆。但四仓没有 Mini-Pi 的五出口优先级。“有唯一指针可 `task_constraint`”及 H4 的首要处理都是本项目的契约推断，不冒称上游行为。
3. **对失败原因的分歧边界**：当前提示第 59 行的“缺少前文”可能只让模型想到聊天前文，而 H4 引用外部会议工件；真实 `reason` 排除了猜测/冲突却没处理所指缺口。这是**有证据支持的措辞假说，不是已证明的因果**。一例输出不能分离提示措辞、few-shot 分布和模型波动的贡献。

**当前最小动作**是先明确上述人工判准与消费边界，保持本轮 6/7 未通过。若以后授权修改，优先评估将“缺少前文”澄清为“本次可信输入中的执行目标/外部引用无法辨认”，同时要求正文写出缺口；现有规则本就接近，单改词或再加一个同词 few-shot 都不能保证真实模型遵守。无需此刻新增出口、字段、关键词硬规则或自动会议检索模块，也不能事后放宽 H4 的 gold。

将来若有新预算，应先冻结**独立措辞**的“模糊会议版 / 同条给值 / 明确工件指针 / 动态选择规则 / 指定先查再改 / 混合独立要求”样本与正文、路由、禁止推断标准，再分别报告真实技术、正文、路由、整案结果；本地固定响应只验接线。MEM-04 另需验证可信任务归属、待澄清信息如何呈现、找到外部材料后的来源对应及执行门禁。当前这些都**尚未实现或验收**。
