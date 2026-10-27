# MEM-W v2：首版demo的五出口修复方案

> 归档说明（2026-10-27）：下文是10月26日各阶段方案/结果快照，“当前MEM-04未接线”等表述属于当时状态。后续首版技术链路已通过[MEM-04验收](mem04-acceptance.md)；历史真实语义成绩不回改，v2.2两例通过不等于普遍泛化。

2026-10-26最新补充：用户要求few-shot并确认2次后，[v2.2定向小试](memw-reference-v22-results.md)已执行，技术/正文/路由2/2，本次通过。新增一组对照示例区分缺少本条可辨认配置与明确取值对象/步骤，不要求展开全部值。其余契约/核心不变，2次已用完；下文v2.1的6/7等旧结果冻结，不用新两例倒改或宣称普遍泛化。

2026-10-26，已按用户确认更新。当前方案优先于此前关于动态保留开关或新增task_state的讨论。保留已有手敲代码，不把分类修正扩展为新的存储或生命周期模块。

最新进展：用户已同意[三层联合修复v2.1](memw-overlap-v21-plan.md)，并确认最多6次复验。局部原则/3组few-shot已实施，新6案7单元已真实执行：技术6/6、严格语义6/7，H4缺参数指代仍漏，整体未通过。已交原侧任务继续只读审查，不自行追加修复或调用。旧4/5及原始证据不改，五出口契约保持。

## 已确认的范围

首版demo实现可信Source到三字段候选，再按用途分成五组。模型提出content/proposed_route/reason，程序持有完整Source与Scope。出口是后续处理去向，不是穷尽所有信息语义类型的分类体系。

| 出口 | 首版契约 |
| --- | --- |
| long_term | 有明确跨任务复用用途的用户事实、稳定偏好，或需要跨会话回溯的事件；后续仍须核对字段及明确规划/执行 |
| task_constraint | 仅供原任务使用的相关材料，包括要求、进度及执行观察；正文保持各自原意，不将观察改成指令 |
| needs_review | 存在实际猜测、证据缺失、指代不明或冲突，需要核对；不是所有非长期信息的兜底 |
| withdrawal | 明确撤回已有记忆的意图；目标、范围及执行仍需独立核对 |
| ignore | 无需独立提取保留的寒暄或无关冗余；原Session仍保留，不自动删除 |

同组不等于同为强制指令；不因task_constraint标签提高来源权限或执行其内容。首版暂不按标签自动维护要求/状态的生命周期；如以后选中该能力，再定义并验证对应行为。

## S1：修正归因口径，保留真实限定

“我主要用Python开发”转为“用户主要使用Python开发”可接受，不要求每条content重复“用户自述”。程序绑定Source及原作者，不得声称外部核验。
“我猜”“可能”“据某人说”等实际限定必须在content中保留；主要不能强化为只会，尽量不能强化为必须。

## S3：保留本次材料的信息缺口

只给“部署还是按之前那个方案”而未提供方案时，正文保留“用户希望沿用先前方案，但本条材料缺少方案细节，需要核对”，路由needs_review。不能据此断言用户从未确定方案。
同条材料已经给出方案的正例，应正常提取task_constraint；不按“之前/那个”等词机械判断。reason和Source不能补救正文遗漏。

## S4：接受任务内执行观察

实际输出正文准确保留mini-pi-pilot、v2、discount测试命令、3项/1失败及exit_code=1。按本版宽task_constraint契约可以通过，不强制长期保存、待核对或ignore。
当时脚本Scope与日志project一致，返回候选也关联同一Source；程序比较Source.scope，不单独解析日志project证明归属。Scope只有用户/项目，不能证明某记录属于本次正在处理的任务。task_constraint只表示原任务相关候选，当前任务/版本匹配由实际消费时核对，当前MEM-04尚未接线。

## 保留与撤下

保留：三字段、五出口、完整Source、范围/角色门禁、严格响应终态、版本/幂等、原工具来源episodic政策、明确规划后执行。
撤下本轮接线：retain_project_events动态开关、基于它新增的episodic规划门禁、新task_state出口及独立状态存储。已敲build_retention_instruction及其3项通过记录保留，标为旧练习暂不用，既有build/extract/plan_candidate不调用它。
工具事件未来若明确需要长期归档，可走已有长期候选及显式规划；事件类型不自动决定长期价值。

## 源码依据与差异

2026-10-26再次通过官方API核对Pi main=d5b3de22d0e24a3e9c38a9410d3329b099717283，session-manager.ts/compaction.ts与本章先前缓存相同；固定学习基准7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333未替换。
Pi的agent-session.ts:1147与session-manager.ts:1204保存原消息，buildContextEntries:476选摘要及保留消息，compaction.ts:682组装专用请求。它们不是本项目长期候选五出口。
红熊60bb78568796a75d8ecfae8323a9b26d68f47142的P1允许最小第三人称规范化并保留条件/模态，历史限用于当前指代；其偏好支路不负责全部用户事实或工具事件。借鉴来源/正文分工，不照搬其业务范围。
精确源码链接及差异沿用[memw-retention-v2-learning.md](memw-retention-v2-learning.md)当日核对记录。

## 口径、验证与接续

v1样本、原始输出、semantic-review/acceptance及旧评分冻结不变。新建examples/fixtures/memory_extraction_eval_v2.json，旧Sources不改，S1/U1与S4按新契约核对，S3/U3仍要求正文保留缺口。它没有live调用授权，也不是独立泛化集。
对旧六次实际输出逐项离线重评：8/9必需单元通过，S3-U3仍失败；5/6样本整体通过。这是标准调整后的旧输出复核，不是新提示的真实调用结果。详见[memw-extraction-v2-offline-review.md](memw-extraction-v2-offline-review.md)。
本轮提示/请求/解析既有22项专项通过，不能据此称新提示语义已通过；真实复验以后另定独立变体和预算。

此前[S3定向语义验收](memw-s3-acceptance-results.md)已按授权完成3次：技术3/3、正文5/5、严格语义4/5；原指代缺口保留，但A-U2猜测状态误分task_constraint，整轮未通过。其3次已用完。四仓研究后用户同意v2.1三层方案，提示及独立样本已更新，下一步是新提示独立复验，不修改旧gold/评分、不把Session接线当语义证据。

后续独立行为：已保存Session的一条记录 → read_memory_source → MemoryExtractor.extract → parse_extraction_response → route_candidates。既有能力复用，不重复手敲；完整固定响应示例只验证接线，不证明语义修复。输出五组候选可交已有显式规划，不自动execute。
实际Session的任务归属/认证、自动元字段选择、真实提取语义与MEM-04仍未完成，不能称自动记忆闭环已通过。
