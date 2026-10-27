# MEM-W v2：五出口与Session接线学习单元

2026-10-26当前：学习者已完成extract_session四行核心，实际读盘正确；5项专项全过，核心未代改。固定响应示例已实际通过只读规划和可选临时SQLite写入/原计划重试/同候选重规划/新Store读回，见[接线验收](memw-session-integration-acceptance.md)。当前进入[MEM-04](mem04-context-plan.md)整体框架，不用本次固定响应改写历史语义成绩。以下各阶段记录保留历史。

2026-10-26最新：用户同意三层修复并确认6次后，[v2.1真实复验](memw-overlap-v21-results.md)完成，严格语义6/7、整体未通过，H4参数缺口仍漏。已交原侧任务继续审查，6次已用完，旧4/5不改。下面Session示例/接线仍为独立后续，不作为语义修复依据。

最新顺序调整（2026-10-26）：用户要求先围绕S3验收，并已明确确认最多3次。本轮已执行完毕：[结果](memw-s3-acceptance-results.md)技术3/3、正文5/5、严格语义4/5，整轮未通过，A-U2猜测未运行被放入task_constraint；指代缺口在本轮样例中已保留。先澄清分流优先级，不追加调用。下面Session四行接线只处理保存记录到五组，不纠正S3、不自动补前文，作为独立后续单元，不提前执行或记作S3验收证据。下文“本轮模型调用0次”仅指此前Session准备阶段，当前真实验收以本段链接为准。

2026-10-26，按用户确认的首版demo范围更新。保留五出口，将task_constraint解释为原任务相关材料，包含要求、进度和执行观察；暂不接入保留开关，不增加task_state。核心继续优先由学习者手敲，分段围绕完整行为。

## 当日源码核对

本轮再次通过官方GitHub commits/main API确认Pi main仍为d5b3de22d0e24a3e9c38a9410d3329b099717283（2026-10-25T08:05:39Z）。重新读取相关精确SHA源码，session-manager.ts/compaction.ts与本章缓存相同。固定学习基准7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333未替换。

- [agent-session.ts:1147](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/agent-session.ts#L1147)：message_end保存原消息。
- [session-manager.ts:1204 appendMessage](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/session-manager.ts#L1204)：包装追加；[476 buildContextEntries](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/session-manager.ts#L476)、543/576投影与模型Context有别。
- [compaction.ts:682](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/compaction/compaction.ts#L682)：专用system与待处理材料组成摘要请求；618传取消/重试配置。585、742–747拒error/length及工具调用，不等于本项目严格stop-only协议。
- 与固定基准相比，本章Session保存/Context职责保留；摘要输出预算及分割回合customInstructions传递有已记录差异。未运行上游服务。
- 红熊main仍60bb78568796a75d8ecfae8323a9b26d68f47142，[P1:11](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/60bb78568796a75d8ecfae8323a9b26d68f47142/api/app/core/memory/storage_services/preference_engine/prompts/p1_identify_preferences.jinja2#L11)限定直接证据/历史辅助；61–71保留模态条件、142–148第三人称规范化。P1只选长期Coding偏好，不是通用事实/工具事件模块。提示中的Source补写声明不等于本轮已核实最终持久化链。

Session读取与派生候选分离借鉴Pi，可信Scope/Source、五出口及SQLite规划是Mini-Pi扩展，不冒称Pi已有实现。

## 先固定本版契约

S1普通第三人称转述可接受，真实条件/强度/猜测仍必须保留。S3缺少所指方案时正文说明材料缺口，needs_review；同条已给出方案则可task_constraint。S4准确工具观察可task_constraint；不强制ignore/long_term/needs_review。五出口详见[修复方案](memw-extraction-repair-proposal-v2.md)。

Scope只到用户/项目。分到task_constraint不能证明属于当前任务；原文不删除也不能证明未来Context已保护它。第一版不自动维护要求/状态不同生命周期。

## 一个完整例子及调用方

助手准备合成Session：run_start、用户消息、assistant工具调用、配对tool_result、run_end。用户消息明确“从2026年11月1日起，后续讲解尽量用Python举例”，并包含本次保留测试断言、未运行的测试猜测、缺少细节的旧发布方案与谢谢；工具记录包含项目v2及discount测试3项1失败。

教学脚本明确给出Scope=demo-user/mini-pi-demo，确认临时路径属于这个合成Session。旧JSONL没有认证字段，read_memory_source只绑定调用方给的Scope，不从文件自证身份。record_index按非空记录从0开始：用户为1，工具结果为3；不是物理行号。

完整调用关系（手敲前一起展示）：

1. 调用方选中已保存路径/记录序号，调用extractor.extract_session(scope, path, index)。
2. 新入口read_memory_source一次取得完整原Source：用户原文不裁剪；工具结果保留tool_call_id/tool_name/output/error完整状态，历史工具不重跑。
3. await已有extract，沿用build_extraction_request的system/user材料分隔、父HTTP层、严格终态/JSON解析、Source绑定。没有前文不补造方案。
4. route_candidates返回五组。用户消息中Python偏好归long_term；保留断言归task_constraint；猜测和缺少方案细节归needs_review；致谢ignore；本例withdrawal为空。工具结果归task_constraint，仍是观察。
5. 固定响应已事先按语义核对；演示把唯一长期候选交既有plan_candidate，明确action=remember、key=explanation_language、kind=semantic、conditions=()、valid_from=2026-11-01T00:00:00+08:00（来自明示生效日），形成只读计划。不是模型自动批准新字段。
6. 默认只读模式不调用execute_plans、不产生长期SQLite文件；新增显式--execute模式只将这一个已核对计划写入临时库，核对重试及新Store读回，结束清理。其他组保留；本例withdrawal为空，不据此宣称撤回执行验收。

## 正常和反例

正常：实际读取合成JSONL并构建请求，固定传输响应经真实父extract解析后，候选绑定该Source并保留五组；仅已核对长期候选可形成只读计划。
反例：run_start/run_end没有正文、assistant来源不允许提取、索引非法时零发送；截断/格式失败不吞成空结果；取消传播，不重试；历史工具不执行。Scope许可仍由可信调用方负责，无法由合成文件证明真实身份。

## 分工与手敲位置

助手准备提示、固定响应、Session建立、完整调用示例、参数依据和测试。无需重写已验提取/归组/规划，不为安排手敲新增业务分类模块。
学习者只敲一个完整接线行为：取消检查点 → 读已保存Source → await原extract → 返回五组。修改在既有extraction_client.py的MemoryExtractor.extract_session骨架；示例调用方和已有read/extract/route的联系先讲清，不将其拆成多个孤立函数课。
此入口先同步读取本地小Session，沿用现有reader；不处理全历史批量提取、不自动补前文、选元字段或判断当前任务归属。大Session读取性能不在本单元验收范围。

## 状态与历史练习

此前build_retention_instruction由学习者敲入，3项专项通过，只证明严格布尔与规则拼接。按用户最新决定，函数/常量保留但标为旧练习暂不用，不接入build_extraction_request、extract或plan_candidate，不把已测旧练习等同本版契约。
此前准备时新Session入口仅骨架；2026-10-26现已核对学习者四行实现并完成5专项及完整接线示例验收。旧请求/候选/响应22项保留原验收口径，不证明提示真实效果。
v1冻结证据保留，v2旧输出离线8/9，仅S3-U3仍失败；新提示真实复验另定独立样本/预算。本轮外部模型调用0次、业务记忆写入0次，无例行hash、提交或推送。D13-B保留暂停，D主线12/30不变。
