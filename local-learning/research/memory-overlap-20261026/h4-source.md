# H4 指代与配置缺口：Pi / MemoryBear 源码跟进

核对日期：2026-10-26。只读复用此前已核对的官方源码固定提交：Pi [`d5b3de22d0e24a3e9c38a9410d3329b099717283`](https://github.com/earendil-works/pi/tree/d5b3de22d0e24a3e9c38a9410d3329b099717283)、MemoryBear [`60bb78568796a75d8ecfae8323a9b26d68f47142`](https://github.com/SuanmoSuanyangTechnology/MemoryBear/tree/60bb78568796a75d8ecfae8323a9b26d68f47142)。Pi 学习路线固定基准仍是 `7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`；本跟进没有重查当日 `main` 或替换基准。未调用模型/评审 API、未运行上游服务。

## H4 证据和问题定位

- 冻结 [H4 fixture](../../../examples/fixtures/memory_overlap_acceptance_v21.json) 第 71–83 行：原文“预发环境的限流参数继续沿用会议里那一版。”；要求同时保留沿用意图、**本次材料没有具体参数且需核对所指**，唯一允许路由 `needs_review`。这项冻结标准只约束本轮 H4，不自动成为所有指代样本的通用规则。
- [request-04](../../evidence/memw-overlap-v21-live-20261026-01/request-04.json) 的请求只有 system 提示与该条 Source 的 `role/recorded_at/text`；没有会议纪要、可唯一定位的版本 ID/工件路径、前后会话。实际响应为“用户要求预发环境的限流参数继续沿用会议里的那一版。”、`task_constraint`，理由说“未涉及猜测或需核验的冲突”。它没有编造参数，却把**无猜测、无冲突**误当成**已能确定所指配置**。
- [当前提示](../../../mini_pi/memory/extraction_client.py) 第 59–61 行明确写“缺少前文而无法解析执行所需的方案、步骤或配置时，应 needs_review”。但 H4 的“会议里那一版”可能指向外部会议工件，并不必然是聊天“前文”；规则的“前文”措辞覆盖不够精确。当前请求又明确“只根据这条原消息提取”，因此不能推断别处确有、没有或已经核过那份配置。
- [人工复核](../../evidence/memw-overlap-v21-live-20261026-01/semantic-review.json) 将 H4 正文与路由均判未通过；本轮技术 6/6、正文 6/7、路由 6/7、严格 6/7、整案 5/6。旧 S3 的 4/5 与本轮不同，不合并或改分。

H4 是两个并存状态：**用户的沿用意图已经表达清楚**，但**所指“那一版”的身份和具体限流参数，在提供给提取器的材料中无法确定**。这不是用户在猜结果，也不是已经证实会议没有决定参数。路由争议应基于后续能否安全使用这个要求，而非单看“继续沿用”是否为明确命令。`content` 应直接写出“本次材料未给出/未能定位所指参数”，不能仅把缺口放在 `reason`，因为候选正文可能被单独消费。

## 上游源码能支持什么

| 来源 | 已实际核对的源码行为 | 对 H4 的有限启发和边界 |
| --- | --- | --- |
| Pi | [SessionManager](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/session-manager.ts#L976-L985) 保留原始 entry 树；[`buildContextEntries`](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/session-manager.ts#L469-L511) 对当前分支投影压缩摘要与保留尾段；[`compact` 提示](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/compaction/compaction.ts#L507-L575) 分别保留目标、约束、进度、阻塞与关键上下文。 | 原始会话、当前可见上下文、跨会话候选是不同对象。Pi 的续接摘要可容纳未知细节，但源码没有 Mini-Pi 的五出口，也没有“找不到会议版就 needs_review”的内建路由规则。 |
| MemoryBear 抽取 | [`StatementTemporalExtractionStep.render_prompt`](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/steps/statement_temporal_step.py#L105-L150) 传入目标文本与 `supporting_context.before_msgs/after_msgs`。[抽取提示](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/utils/prompt/prompts/extract_statement_temporal.jinja2#L20-L48) 仅允许从 target 产生新候选，context 只辅助消解已有槽位，不能新增 target 未说的事实值；[引用清晰度规则](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/utils/prompt/prompts/extract_statement_temporal.jinja2#L419-L425) 要求 context 能唯一映射才算消解。 | 若可信 context 真能唯一定位“那一版”，可在另一个设计里消解；当前 Mini-Pi 请求并无 context。不能把 MemoryBear 的多消息输入假装成 Mini-Pi 本次已有证据，也不能用 context 生成原文没有的限流值。该规则是提示语义，不是本次真实模型输出保证。 |
| MemoryBear 分类与后续 | [分类提示](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/utils/prompt/prompts/statement_classification_fallback.jinja2#L66-L73) 把仍需外部上下文才能识别的对象/事件指代标为 `has_unsolved_reference`；缺日期或真假未核实本身不触发此标志。[分类器](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/steps/statement_classification.py#L136-L193) 把它与陈述类型、时间类型并列输出。[三元组提示](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/utils/prompt/prompts/extract_triplet.jinja2#L410-L427) 要求 unresolved 时空结果，但 [triplet_step](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/steps/triplet_step.py#L116-L160) 仍调用模型，没有程序级跳过。 | “指代是否已解”与“是否确定的要求/事实类型”可并存；不能因为 H4 是明确要求就认为配置已解。是否把 H4 归 `needs_review` 是 Mini-Pi 单出口契约的推断，**不是** MemoryBear 源码规定。MemoryBear 的未解引用主要判断实体/事件指代，未验证内容真假是另一问题。 |

Mini-Pi 当前 [`build_extraction_request`](../../../mini_pi/memory/extraction_client.py) 第 115–141 行仅向模型发送单条 Source 的三项原文字段；`Scope` 只核对用户/项目，不证明本次任务归属。[`parse_candidate_items`](../../../mini_pi/memory/extraction.py) 第 44–69 行只核对输出形状/来源绑定，`route_candidates` 仅按模型标签归组，不重新判断语义。因此 H4 不会被程序自动补成“待核对”。这属于当前 Mini-Pi 行为，而不是 Pi/MemoryBear 的行为。

## 最小建议与强反例（Mini-Pi 设计推断，未实施）

可将局部规则里的“缺少前文”精确化为：**“仅凭本次提供的原消息及明确允许的可信材料，既无法确定执行所需的方案/配置，也没有可辨认的目标指针或明确的选择/核对步骤时，保留已知沿用意图和所指缺口，建议 `needs_review`；不要推断该方案从未确定。”** H4 只有“会议里那一版”，没有会议日期、纪要、版本 ID、工件指针或先查哪份材料的步骤，符合该边界。以后若允许引入上下文，必须另行定义可信输入、来源映射和更新时点；本轮不能回填。

**反例 1，防止“缺具体数值就 needs_review”过宽**：用户说“预发限流继续沿用仓库 `config/staging/rate-limit.yaml` 在提交 `abc123...` 的版本。”即使本条未列 QPS/并发数，已给可独立寻址且唯一的配置指针。若首版只抽取“沿用该工件所载配置”的要求，正文保留指针、不得补写数值，可以建议 `task_constraint`；这不声称工件存在、可访问或数值已核对。真正执行时仍须验证仓库/提交/文件、权限、值和适用环境。**这条路由边界没有来自 Pi/MemoryBear 的直接规则，是 Mini-Pi 的消费契约选择。**若指针其实有多个版本、无法定位或读取失败，消费层须转入待澄清，不能照未知参数实施。

**反例 2，防止按“那版”关键词分类**：用户说“预发限流继续沿用会议里那版，即 QPS=120、并发=40，配置文件为 `config/staging/rate-limit.yaml`。”这里正文已有所指值，通常可作 `task_constraint`；要核对的是后续执行是否与之相符，而不是提取时把明确要求误标为未解。反过来“先记录我要沿用会议版的意图，暂不改配置”也是清楚的记录/不执行要求，即便参数未给，也不应借 H4 规则推断可以直接实施。

**反例 3，防止把“不可变版本号”当唯一清晰形式**：用户明确说“执行时使用配置仓库 `main` 上 `config/staging/rate-limit.yaml` 的最新版，变更前先读取确认。”虽然分支会漂移，但目标选择规则与先核对步骤本身明确，可作为 `task_constraint` 的条件式要求；具体值、当时的提交与操作许可仍待执行时核验。H4 没有这种可操作的选择规则。

不建议仅堆一条 H4 同词 few-shot、按“那版/之前”关键词硬转路由、改本轮冻结 gold 或新增一个未经需求证明的字段/检索模块。若将来改提示，先冻结“无定位指针 / 有唯一指针无数值 / 同条给出值 / 仅记录意图不执行 / 有指针但消费时不可读取”的正反例，分别核对正文、路由和后续执行阻断；需另获模型调用预算才能声称真实提取改进。当前冻结 **6/7 严格语义未通过** 保持不变。
