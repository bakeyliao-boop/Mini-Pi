# MEM-W：真实模型提取的小样本与调用计划

状态：2026-10-23，用户授权后已按固定计划实际执行6次，无重试；技术6/6通过，语义整轮未通过。以下样本/标准为执行前固定方案，实际逐条输出与成本见[memw-extraction-pilot-results.md](memw-extraction-pilot-results.md)。本轮未写长期记忆，6次授权已用完。

## 本阶段源码依据

2026-10-23再次通过GitHub API核对Pi上游main，仍为`42cb822f1c5d3153069dd0661bfd297424666cf1`；读取该精确SHA缓存的[compaction.ts:682](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/coding-agent/src/core/compaction/compaction.ts#L682)独立system/user摘要请求、[742–752](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/coding-agent/src/core/compaction/compaction.ts#L742)失败/工具调用拒绝及text/usage返回。与固定`7f9e119`的差异沿用[memw-request-plan.md](memw-request-plan.md)，固定checkout不变。

Pi这些摘要行为不等于候选提取正确性评测。本项目三字段/五出口、严格stop及本阶段语义标注都是Mini-Pi扩展；不能由9项合成/本地HTTPS通过推断真实LLM保真。真实调用本阶段只验提取和归组，不接实际Session、写入计划或Store，不验证完整长期记忆系统。

## 具体输入、处理与输出

输入是一条已保存消息对应的可信Scope和完整Source，不是检索问题。以下用S3的完整原文：

> 这次修复必须保留原测试断言，不要改测试掩盖问题。我猜v2测试应该通过了，但还没有运行。部署还是按之前那个方案来。

程序先核对来源范围/角色，构造固定提取规则与原消息材料；真实LLM只提出content/proposed_route/reason。已验parse_extraction_response检查正常结束、无工具/拒答及完整JSON，再由parse_candidate_items关联同一完整Source，返回候选tuple，调用方交route_candidates归组。

| 预期候选含义（非逐字答案） | 建议去向 | 理由示例 |
| --- | --- | --- |
| 本次修复保留原测试断言，不能改测试掩盖问题 | task_constraint | 当前任务要求 |
| v2测试通过只是猜测，尚未运行 | needs_review | 没有实际执行证据 |
| 部署希望沿用先前方案，但该方案细节未给出 | needs_review；明确保留未知的task_constraint也允许 | 缺少前文 |

允许改写，不要求quote或下标。将第二条改成“v2测试已通过”、把第三条补成Docker部署，都算提取错误；reason或原Source里写着未知不能补救content中的错误断言。模型提取成功也没有授予长期写入或撤回权限；key/kind/conditions/valid_from和明确动作仍属下一阶段有依据的规划输入。

## 六条固定合成样本

数据：[examples/fixtures/memory_extraction_eval_v1.json](../examples/fixtures/memory_extraction_eval_v1.json)，版本`memw-extraction-pilot-v1`，共6条Source、9个必需语义单元。全部合成，不读取真实Session。S4是合成工具观察，不声称已实际执行其中业务测试。

| 样本 | 原文主题 | 必需语义单元 | 核对重点 |
| --- | --- | --- | --- |
| S1 | 普通聊天中主要用Python开发、后续尽量Python举例 | 2 | 聊天形式不跳过事实/偏好；主要/尽量不强化 |
| S2 | 2026-11-01起工作日只能早上、周末更喜欢晚上 | 2 | 两条件并存、未来日期、只能/偏好的区别 |
| S3 | 本次保留断言、v2通过仅猜测未运行、部署按未给出的旧方案 | 3 | 原任务范围、猜测、上下文不足 |
| S4 | v2 discount测试3项、1项失败的合成工具JSON | 1 | 原项目/版本/范围、数值与失败状态；仅一次观察 |
| S5 | 撤回旧“必须Java示例”偏好 | 1 | 只记录撤回意图，不复活旧偏好或声称已执行 |
| S6 | 你好，谢谢 | 0 | 正常[]或ignore均可；不推断人格和长期偏好 |

标准和允许去向在执行前固定，只在本地评阅，不加入system提示或user材料。模型实际看到的仍只有固定EXTRACTION_PROMPT及Source的role/recorded_at/text。允许同用途单元拆分或合并，不要求候选条数等于单元数；跨用途混成一条、丢失限定或靠reason补全content不算覆盖。

S3的未明方案允许needs_review或显式保留未知的task_constraint；S4观察允许long_term或有依据的needs_review，后者单列保守分流，不能等同可写候选；S5允许withdrawal或明确保留撤回意图/目标待核对的needs_review。S1/S2的清楚长期信息不能全部塞进needs_review而宣称用途分流正确。S6允许空数组或有原文依据的ignore；技术异常不属于任何正常空结果。

## 验收口径

1. 技术层：每个已请求样本均正常结束、返回合法数组/三字段，候选关联原Source且未错Scope，无工具/拒答/截断被转为空结果。技术失败单独报告，不做语义成功评分。
2. 覆盖层：9个必需语义单元全部被支持的候选覆盖；按含义而非字面判定。同一单元重复只计一次覆盖，遗漏逐项列出。
3. 保真层：每条候选content和reason都需有给定原文支持。否定、对象、条件、时间、强度和猜测状态保留在content。无依据新事实、猜测升格、范围扩大、工具观察泛化、撤回变新增等错误为0；reason不能充当外部证据。
4. 分流层：每单元进入预先允许去向。纯寒暄不变长期偏好，任务约束不无条件推广。安全保守待核对与直接可用长期候选分开计数，不以安全拒绝替代有效提取。
5. 结论层：逐样本列实际候选/理由/去向、对应单元、遗漏、无依据新增、限定变化、保守分流与重复；分别报告技术通过数、覆盖数/9、支持情况及分流情况。额外但确有原文支持且去向合理的候选单列，不机械判误记。无候选的支持率无定义时标不适用，不能记100%。

6条全满足才记本轮试点通过；任何单元错误不能被平均值掩盖。每条只请求一次，不能证明稳定性或泛化，也不据此记整个MEM-W完成。评阅由助手逐条对照标注并给出依据，可供学习者复核；不调用额外judge模型，不用正文逐字相等替代语义判断。

## 调用计划与预算

- 固定`qwen3.8-flash`、华北2（北京）、`https://dashscope.aliyuncs.com/compatible-mode/v1`，使用现有MemoryExtractor，不用embedding模型做提取。`enable_thinking=False`、非流式、无工具、不增加结构化输出等新参数。
- 一个专用实例`max_requests=6`，按S1→S6串行、每条最多一次；S1兼作首个真实连通样例，包含在6次内。每次`max_completion_tokens=1536`，整轮请求输出上限参数合计9216；不自动重试或添加评审模型请求。
- 请求timeout参数30秒；它是既有HTTP超时参数，不声称整轮硬截止。取消继续沿用已验实际传输和关闭行为。
- 执行前只核对既有本地聊天密钥是否可用及地域/模型/接口配置，不回显密钥、不把embedding凭据可用当聊天权限已验证；本轮没有读取.env。实际配置不符合所列模型/地域时停止，不悄悄换模型或地址。无需把密钥再次发到聊天。
- HTTP/鉴权/限流/传输/取消/截断/解析等技术问题立即停止后续真实请求，已发生次数/用量照记，未运行样本标未执行。纯语义错误保留输出，按原定顺序完成剩余样本；不边跑边改提示或重试直到通过。
- 真实调用前运行辅助需能保留合成Source、实际请求、原始响应、解析后的候选和分组，以及错误与实际usage/耗时；不保存认证头或密钥。现有request_records的received仅说明已收到响应，不能当提取通过。原始响应采集不得改变发送、取消、解析或重试行为。
- 运行辅助只发送Source材料，标注/预期去向留本地。输出仅落本轮报告，不调用plan_*或execute_plans，不写现有长期记忆库或真实会话。

## 成本口径

2026-10-23核对[官方qwen3.8-flash页面](https://help.aliyun.com/zh/model-studio/qwen3-8-flash)：北京标准输入0.8元/百万tokens、输出2.7元/百万tokens。按每条输入预留4000 tokens、输出上限1536估算，6次约`(6×4000×0.8+6×1536×2.7)/1000000=0.0440832元`，可按约0.05元理解。这是粗估，不是已计费金额或硬金额上限；输入token未实际预分词，不用UTF-8字节数冒充tokens，不假设缓存/免费额度/优惠。

实际分别报告准备阶段、每请求可得的输入/输出/缓存tokens、失败与请求次数、请求耗时、提取端到端耗时及评阅过程。无法独立测量的阶段合并或标未知，不靠相减编造指标。费用按usage与实际计价估算，最终核账另记；缺失usage不能当0。本次未运行的写入、索引、检索等不包含在试点成本中，不把本轮提取成本称完整记忆系统成本。

## 已完成的准备与保存冲突处理

开始读盘再次发现extraction_client.py回到此前record_at/messgaes两处旧错，未据旧通过记录直接发真实请求。用户确认关闭该文件旧标签后，依据此前明确修复授权仅恢复这两处，实际重跑9项全部通过，0失败/错误/跳过；覆盖原因未证实，未做hash或定时复查。证据local-learning/evidence/memw-extraction-client-restore-before-pilot/。

实际离线组装6条请求成功：6条Source、9个必需单元，user材料仅role/recorded_at/text，无工具，模型请求中未加入gold；消息正文最大2347 UTF-8字节（不是token计量）。请求预览和preview-verification.json在local-learning/evidence/memw-extraction-pilot-prepare/。该检查不读取凭据、不联网或开库，也不是语义验收。

上述为准备阶段状态，当时真实调用0次；后续用户授权执行见下节。无提交推送、真实Session/业务库写入或全库hash，原D13-B继续暂停，D主线12/30不变。

## 已授权执行与验收结果

用户明确确认后，运行辅助examples/memory_extraction_eval.py及6项离线门禁已准备并实际通过。先安全核对本地配置（不输出凭据）与固定模型/北京接口，再由唯一live进程执行S1至S6，6次正常stop并解析，Source关联与实际wire材料均核对通过。辅助只观察既有发送路径，gold留本地，原始响应/usage/分组完整留存；没有更改提示、标注或重跑。

语义整轮未通过：S3缺“方案未知/待核对”且加入确定性，S4将忠实工具观察分入task_constraint；S1自述归因按预标注保守记边界。严格完整内容7/9，内容与有效分流6/9；3案完整通过、2案明确失败、1案边界。边界若在后续改口径可多通过一单元，仍不改变本轮S3/S4失败，本轮标准和输出不改。

输入3126、输出692、总3818 tokens，缓存0；调用采集进程总墙钟18.796538秒，按标准原价估算0.0043692元，账单/优惠未核对。采集进程外的辅助开发、标注、离线测试与评阅耗时未计量，不冒称零成本或完整记忆系统总成本。

逐条可读结果在memw-extraction-pilot-results.md，真实证据在local-learning/evidence/memw-extraction-live-20261023-01/，result.json是技术采集，semantic-review.json和acceptance.json是后续语义核对与综合未通过判定。真实请求6次已耗尽授权，停止新增调用；下一步先离线分析并提出最小提示改进，新真实复验另定预算。实际Session/元字段动作/完整写入链路及MEM-04未完成，D13-B/12/30不变。
