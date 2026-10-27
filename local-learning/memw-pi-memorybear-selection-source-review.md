# Pi与红熊：记忆选择、内容类型及长期保留的源码核对

2026-10-23。按用户要求只调查设计，不修改Mini-Pi实现、提示词、标注或既有验收分数；不提出本轮修复方案，也不运行模型、数据库或服务。

## 核对版本与证据范围

| 项目 | 本次main核对 | 保留的学习基准 |
| --- | --- | --- |
| Pi，earendil-works/pi | `a1836b06c3f93af50c76dbbd468b4d4f8771ef15`，GitHub API，2026-10-23T09:20:01Z | `7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`，未切换checkout |
| 红熊，SuanmoSuanyangTechnology/MemoryBear | `60bb78568796a75d8ecfae8323a9b26d68f47142`，默认分支main，2026-10-21T08:31:10Z | `a2960b3b6313704448d6f7ab0243aefede802238`，不暗中替换 |

实际读取精确SHA的官方原始源码。Pi检查会话/摘要/请求/扩展及代表性示例；红熊检查P1/P2偏好支路、常规/快速写入、当前剪枝服务/提示、语句分类和遗忘入口。红熊全树请求未完整取得，不能据此作全仓不存在判断；以下结论均有具体已读文件或调用链支撑。

缓存分别为`C:\Users\hyf\.codex\external-sources\pi-memory-selection-a1836b0`及`C:\Users\hyf\.codex\external-sources\MemoryBear-selection-60bb785`。本轮无文件hash校验。

## 直接结论

Pi有为继续当前会话选择摘要内容的机制；在已核对默认链路中，没有发现独立的跨会话长期记忆价值选择器。红熊的Coding偏好支路有明确的长期价值筛选，但它不是所有事实/事件的通用保留裁判。常规内容规整、内容分类、偏好写入与写后遗忘分别解决不同问题，不能由名字或episodic一类内容标签推导“必须长期保存”。

## Pi：保存会话与选择续接摘要

1. [agent-session.ts:1147–1165](https://github.com/earendil-works/pi/blob/a1836b06c3f93af50c76dbbd468b4d4f8771ef15/packages/coding-agent/src/core/agent-session.ts#L1147)在message_end时将system/user/assistant/toolResult交appendMessage。输入是一条已完成消息，输出是追加后的会话条目；此处没有按工具成功、情景类型或长期价值筛选。
2. [session-manager.ts:1204–1213](https://github.com/earendil-works/pi/blob/a1836b06c3f93af50c76dbbd468b4d4f8771ef15/packages/coding-agent/src/core/session-manager.ts#L1204)包装id、parentId、timestamp和message，再_appendEntry/_persist；启用文件持久化时保存JSONL。持久化会话记录不等于独立长期记忆入库。
3. [compaction.ts:267 shouldCompact](https://github.com/earendil-works/pi/blob/a1836b06c3f93af50c76dbbd468b4d4f8771ef15/packages/coding-agent/src/core/compaction/compaction.ts#L267)、789 findProjectedCutPoint、859 prepareCompaction按token预算和消息/工具配对边界选待摘要旧消息与近期保留区间。
4. [compaction.ts:507–575](https://github.com/earendil-works/pi/blob/a1836b06c3f93af50c76dbbd468b4d4f8771ef15/packages/coding-agent/src/core/compaction/compaction.ts#L507)让模型归纳目标、约束/偏好、进度、关键决策、下一步及续接必需上下文；更新摘要允许移除不再相关信息。这里确有内容选择，不能说Pi完全没有选择。
5. [session-manager.ts:476 buildContextEntries](https://github.com/earendil-works/pi/blob/a1836b06c3f93af50c76dbbd468b4d4f8771ef15/packages/coding-agent/src/core/session-manager.ts#L476)使用摘要与近期保留消息构成模型上下文，旧原文仍留原始Session。其目标是续接任务，不是在episodic/semantic/procedural之间分类或给跨会话长期价值打分。

有扩展入口：[ContextEvent](https://github.com/earendil-works/pi/blob/a1836b06c3f93af50c76dbbd468b4d4f8771ef15/packages/coding-agent/src/core/extensions/types.ts#L885)、session_before_compact及appendEntry允许外部变换请求/摘要或保存扩展状态。官方[todo扩展:114](https://github.com/earendil-works/pi/blob/a1836b06c3f93af50c76dbbd468b4d4f8771ef15/packages/coding-agent/examples/extensions/todo.ts#L114)从特定工具结果重建任务状态；这不是通用长期选择。durable的MemoryStorage是内存存储后端，不能仅凭文件名memory判定为Agent长期记忆系统。

与固定基准相比：会话管理及代表性todo/custom-compaction文件相同；摘要输出预算、自定义指令传递、请求identity等有变化，以上会话保存/续接摘要职责未改变。源码能力与真实运行效果分开，本轮没有运行Pi。

## 红熊：偏好支路确有写前长期价值筛选

### 入口与选择

[write_pipeline.py:345–367](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/pipelines/write_pipeline.py#L345)仅在非pilot、启用preference_engine、当前target为user且有消息ID时启动独立偏好处理；702–725构造完整当前消息及user/assistant历史快照。工具结果不进入这个P1偏好入口。

[processor.py:54–94](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/preference_engine/processor.py#L54)依次为关键词门禁、P1识别、空结果跳过、去重及按subject/situation_key分组。关键词命中只决定是否启动判断，不证明已有可写偏好。

[P1提示:11–48](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/preference_engine/prompts/p1_identify_preferences.jinja2#L11)要求当前用户明确表达、持续/未来适用、后续Coding任务可复用，描述如何回复、实现、用工具、验证或交付。不能可靠确认时可以不输出。历史只用于理解当前指代，不能重新采掘未确认的旧偏好。

该分支排除一次性要求、仓库/代码/配置事实、用户画像及隐性猜测等；它筛的是长期Coding偏好，而非把所有有用信息都装进偏好。比如主要用Python的用户画像事实不属于此P1的目标，尽量Python举例的持续交互要求才可能属于目标。不能把这个排除规则扩成红熊其他路径都不保存用户事实。

### 写入在选择之后

[processor.py:132–177](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/preference_engine/processor.py#L132)先查现有偏好分组。没有节点时可直接create；已有节点才调用P2规划补充/更新/删除/不变，再应用和保存。因此不是每次新增都必经P2，也不是先不加选择地存入再决定偏好价值。

P1的长期性/语义支持主要是LLM提示要求；[prompt_runner.py:64–87](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/preference_engine/prompt_runner.py#L64)实际核对结构及本体合法值，没有通用程序语义裁判。不能把“提示规定长期”说成模型必然判对。

边界例：默认[关键词词表](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/preference_engine/default_keywords.py#L3)含撤销等词但未含撤回。未配自定义关键词时，我方S5原句没有直接命中默认词，按[匹配实现:36–53](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/preference_engine/keyword_gate.py#L36)可能在P1前跳过；这是源码推断，不是实际服务验证。不能只凭P1有撤回语义就声称它实际处理了该样本。

与固定a2960b3对照：P1/P2全文相同；processor增加落库统计、runner增加P3召回路径，P1/P2选择顺序未变。此处没有用episodic标签来决定长期价值。

## 红熊：常规剪枝/分类不是同一个价值筛选器

当前常规入口[write_pipeline.py:410–420](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/pipelines/write_pipeline.py#L410)调用prune_messages，之后分块、_extract，再在非pilot时_store（545–571）。

- [pruning_service.py:123–137](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/data_preprocessing/pruning_service.py#L123)只给user/assistant安排规整任务，其他角色原样返回；本模块没有工具观察专用长期价值判定。
- [extract_pruning.jinja2:45–48](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/utils/prompt/prompts/extract_pruning.jinja2#L45)的助手类型是建议、警告、指令、问题等交互动作，并非episodic/long_term；非空助手内容要求保留最短摘要，即便价值较低也不再输出NULL。
- 即使返回NULL，[pruning_service.py:289](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/data_preprocessing/pruning_service.py#L289)转为空字符串后，当前入口[178–191](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/data_preprocessing/pruning_service.py#L178)仍会回退助手原文。因此不能根据旧注释/字段名宣称无价值内容必然被这个入口阻断。
- 同仓库另一条SemanticPruner.prune_dataset批量路径有NULL删除分支，但不是上述现行write入口，不能把两条路径的行为混在一起。
- [statement_classification.py:30–44](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/steps/statement_classification.py#L30)独立分类事实/观点/其他、时间属性和未解析指代；这也不是跨任务保留价值分数。

角色边界还要继续尊重：[DataPreprocessor._normalize_role:431–456](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/extraction_engine/data_preprocessing/data_preprocessor.py#L431)未知角色默认归User，不能把pruning服务中tool原样返回解释成全系统已建立可信工具观察链。本轮未运行入口schema/角色处理组合，不宣称S4真实工具数据会怎样最终落库。

快速写入[fast_write_pipeline.py:404–439](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/pipelines/fast_write_pipeline.py#L404)构造完整Dialogue节点，另有轻量清洗和持久化；保存对话材料也不能等同P1完成长期偏好选择。

## 红熊：另有写后的保留与遗忘

[ForgettingPipeline.run:22–35](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/pipelines/forgetting_pipeline.py#L22)读取记忆额度并调用ForgetService。当前[ForgetService._run_cycle:93–153](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/forgetting_engine/forget_service.py#L93)在未超触发水位时跳过，超额时先清理无有效关系核心节点，再清理辅助池、寻找新孤立节点，最后进入兜底候选清理；删除为软删除并审计。它管理已入库内容，和写前语义上值不值得成为长期候选是不同阶段。

仓库同时保留ForgettingStrategy、MemoryStrengthCalculator等算法实现，但当前上述入口走ForgetService；不能看到ACT-R或should_retain函数就未经调用链核对宣称当前自动遗忘由它驱动。本轮没有运行调度、数据库或删除行为。

## 对当前争议能得出的源码结论

- Pi支持保存测试观察，以及在需要时将其纳入当前任务摘要；这些动作不能证明它必须进入独立长期记忆。
- 红熊确有专用长期偏好选择，但工具测试观察不属于该用户偏好入口；不能借P1标准替工具事件直接决定保留价值。
- 常规剪枝、内容类型和写后遗忘各有边界，不能用其中某个类型标签或字段名替代业务保留目标。
- 在本次已核对的链路中，没有源码依据支持“测试观察属于情景信息，因此S4必须long_term”。Mini-Pi目前的五出口映射仍是自定义设计，不是两套源码共同规定的标准。

本轮只新增调查记录，未改变S4标注/判分或Mini-Pi实现；没有新增真实模型调用、测试执行、提交推送或D主线进度。
