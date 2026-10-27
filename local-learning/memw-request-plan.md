# MEM-W：提取请求组装与异步发送

2026-10-26口径更新：用户确认五出口保持，task_constraint包含原任务要求、进度和执行观察，S4准确观察可接受；不接入保留开关，不增加task_state或episodic布尔门禁。当前提示已按新契约修改，22项既有提取技术专项本轮通过；旧真实输出按v2离线8/9不等于新提示效果。完整Session接线骨架待手敲，接续以[memw-retention-v2-learning.md](memw-retention-v2-learning.md)为准；以下2026-10-23执行与预算保留历史。

当前接续：请求/异步9项已验，首次6次真实提取已执行，技术6/6而语义未通过；逐条结果见[memw-extraction-pilot-results.md](memw-extraction-pilot-results.md)，固定计划见[memw-extraction-evaluation-plan.md](memw-extraction-evaluation-plan.md)。6次授权已用完，不追加请求。

## 本段源码核对（2026-10-23）

当前上游main为`42cb822f1c5d3153069dd0661bfd297424666cf1`，GitHub API与git ls-remote结果一致；提交时间`2026-10-23T07:05:23Z`，说明`feat(chord): shared watch-handle implementation (Watch, NativeWatch); Durable uses it`。本段实际读取该SHA原始源码，缓存于`C:\Users\hyf\.codex\external-sources\pi-memory-extraction-42cb822f`。上游checkout仍固定`7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`，没有切换或替换固定阅读基准；此前936e5f4的提取章节核对保留历史口径。

| 精确源码 | 实际行为 | 本段映射 |
| --- | --- | --- |
| [compaction.ts:682 buildSummarizationContext](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/coding-agent/src/core/compaction/compaction.ts#L682) | 专用system提示与user正文构成独立摘要请求，此处无tools | 单独提取提示与完整原消息材料，沿用已有请求转换 |
| [compaction.ts:618 completeSummarization](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/coding-agent/src/core/compaction/compaction.ts#L618) | 传options/signal，取得完整AssistantMessage，经配置的重试入口返回 | await原HTTP层后保留完整原始响应，再做已验解析 |
| [compaction.ts:585](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/coding-agent/src/core/compaction/compaction.ts#L585)、[742–752](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/coding-agent/src/core/compaction/compaction.ts#L742) | 摘要显式拒error/length及toolCall，输出text/usage | Mini-Pi严格stop、JSON数组和候选对象仍是自定义提取契约，不能说Pi仅接受正常stop |
| [retry.ts:205 retryAssistantCall](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/ai/src/utils/retry.ts#L205) | 配置有界重试可重试error，aborted不重试，退避接收signal；length返回后由摘要层拒绝 | 首版明确不自动重试，失败或取消不能返回空候选；不搬完整重试机制 |
| [agent-loop.ts:390 streamAssistantResponse](https://github.com/earendil-works/pi/blob/42cb822f1c5d3153069dd0661bfd297424666cf1/packages/agent/src/agent-loop.ts#L390) | transformContext→convertToLlm→模型调用，传signal并收最终结果 | 提取单独发请求，原Session和后续Context接线仍分阶段推进 |

固定基准差异：摘要输出上限不再从reserveTokens派生，分割回合摘要新增customInstructions；Agent请求增加identity合并；重试分类增加部分临时断流错误并收紧状态码/限额判断。独立上下文、signal和相关失败/工具调用拒绝边界仍在。本次只是静态核对；上述文件未见本项目的长期候选五出口协议，不据此推断已排查全仓。

## 对齐此前问题的输入与输出

输入仍是程序从已保存记录得到的可信Scope与完整Source。Scope在发送前核对，模型只看必要的原消息role、recorded_at和完整text；用户/项目/来源身份由程序保留，不让模型重新生成。首版一次分析一条原消息，没有前文时不能声称支持跨消息指代；recorded_at也不自动变成事件时间或valid_from。

模型只输出JSON数组，每项三个非空字符串：content、proposed_route、reason。正文允许最小规范化，不要求quote、下标或原文逐字一致；必须保留否定、条件、时间、尽量/必须、猜测及用户自述性质。普通聊天也可能含长期事实/偏好，不能按聊天形式直接丢弃。工具观察不能被泛化为未经验证的程序技能。系统提示与原消息材料分开；材料中的指令不改变提取任务。

返回的原始响应交parse_extraction_response，再经parse_candidate_items形成关联同一完整Source的候选tuple。extract只返回此tuple，调用方再交route_candidates分五组。固定字段和五组是处理协议，不是把可记忆的信息属性枚举成固定key。

| 输出建议 | 进入下一阶段的方式 | 当前边界 |
| --- | --- | --- |
| long_term | 核对正文及key/kind/conditions/valid_from和remember/replace动作，再plan_candidate；收齐计划后显式execute_plans | 三字段建议本身不足以自动确定写入字段或覆盖已有系列 |
| task_constraint | 保留原任务相关材料，含要求/进度/执行观察；正文保持其性质 | MEM-04待实现；不能把全部材料当强制指令，也不能自动变成当前新任务信息或长期偏好 |
| needs_review | 保留待核对建议；原Session仍保留 | 尚无独立持久化审核队列，不当作已验证事实 |
| withdrawal | 核对明确用户意图、目标系列/条件及operation_id后plan_retract，再显式执行 | 标签不授予撤回权限，不经普通长期Draft路径 |
| ignore | 不进入长期写入 | 不删除原Session |

例：原消息包含“以后尽量用Python举例”“今天只解释不改文件”“我猜测试通过了”。提取正文分别保留尽量、原任务范围、猜测状态；去向建议分别long_term/task_constraint/needs_review。修改措辞允许，但把猜测改成实际测试通过是提取错误；当前运行时格式/来源检查不能证明语义正确，后续必须用标注样本验误记、漏记和支持。

## 最小实现与分工

新增extraction_client.py，避免改动当前已验提取解析文件。助手准备固定提取提示、输入格式辅助、导入/签名与占位、离线及本地HTTPS测试。学习者手敲两段核心：build_extraction_request在格式检查后做Scope/角色准入、组装system/user请求；MemoryExtractor.extract先用异步检查点响应已有取消，再组装→await发送→交已验解析。提取异常原样传播，不把错误降级为空结果。

MemoryExtractor轻量继承QwenProvider构造及_send，复用已有异步HTTP、响应/客户端关闭、实例请求计数及输出限制，不复制配置或新建HTTP层，不调用会丢失finish_reason的generate。专用实例的次数预算覆盖已进入发送的尝试，包含发送失败、取消、收到响应后的解析失败；没有自动重试。timeout沿用HTTP请求参数，不是总运行硬截止时间；原文不静默截断，输出上限导致length则已有解析拒绝。

request_records沿用父类，会在实例内存暂存含原消息正文的request_body及usage，不默认打印或落盘、不含密钥。received只表示HTTP响应收到，不等于提取或语义验收通过。当前全部合成样例；真实用户数据的正文记录策略在实际接入时明确，不把内存请求记录称为长期记忆。

## 本段验收

tests/test_memory_extraction_client.py准备9项：完整材料/提示分隔/请求协议；错Scope/角色/格式零发送；合成响应经真实父_send进入候选；发送异常/截断/坏JSON不重试；次数耗尽；已有取消零发送；真实本地HTTPS成功/关闭；真实请求取消/断开/关闭；真实请求超时/断开/不重试。使用合成凭据和现有LocalHttpsServer，禁止外部模型、SQLite或Store变更。提示词静态存在不当作真实语义效果通过。

当前核心占位，准备不计行为通过；用户敲入后再执行上述专项。无真实模型调用、业务库写入、提交推送或hash；原D13-B暂停及12/30不变。

准备检查：源文件AST通过；测试AST/仅发现通过，共9项（组装1项＋异步8项），0加载错误、0实际执行。主线程已读取全部专项内容；核心占位当前为build_extraction_request第65行、extract第81行，修改首段后后续行号会后移，按函数名定位。新文件辅助和测试准备不替代核心行为或提取语义验收。

## 首次手敲核对（2026-10-23，待修/待验）

用户已敲入组装第65–81行，且extract第97–100行也已有四步实现。当前组装有两处阻塞：第74行record_at键和source.record_at属性应为recorded_at，第81行messgaes应为messages；其他流程与既定方案一致，列表括号内现有对齐不影响Python语法，不要求额外改动。

实际只运行1项组装测试，user/tool两个子场景均在第74行AttributeError，共2错误记录、0断言失败/跳过；第81行后续NameError是源码判断，尚被首错遮蔽。extract顺序源码核对正确，余下8项未运行。本次未修核心、未发网络请求或执行Store写入；实际日志和verification.json在local-learning/evidence/memw-extraction-request-review/。先修两处再验组装/异步行为，不重复要求学习者敲已有extract。

## 授权修复与本段验收（2026-10-23）

用户明确要求调整后，仅修第74行record_at键/属性为recorded_at、第81行messgaes为messages，其他组装/异步代码保留。实际完整9项专项全部通过，0失败/错误/跳过。固定响应通过真实父_send进入候选解析，保留完整Source；错范围/角色/格式不发请求，错误和截断不自动重试，实例预算耗尽不发第二次，已请求取消在进入发送前生效。

3项实际本地HTTPS验证完整请求和资源关闭；等待正文期间取消使服务观察断开，重复取消不会突破客户端close门闩，完成收尾后才上抛；响应头超时同样断开/关闭且无重试。本段请求组装和异步接线技术验收通过；外部模型请求0次、长期记忆/业务库写入0次，语义保真不据合成响应通过。

最终原始日志与verification.json在local-learning/evidence/memw-extraction-client-fix-acceptance/，此前失败证据保留。下一步先制定真实提取的小样本标注/调用计划，包含内容与去向支持、否定/条件/时间/猜测、误记/漏记及准备/查询成本边界；真实调用另行安排。实际Session、四元字段/动作和完整写入链路仍需接线，整个MEM-W继续进行中；不做hash、重复其它回归或提交推送。
