# MEM-W 候选提取：本章源码对照与最小范围

## 本章开始核对（2026-10-23）

- 当时上游 `main`：`936e5f40aede9327b9142b63506ed2b68bc6b4ac`，`git ls-remote`及实际fetch结果一致，提交说明为`fix(evals): drop autoevals dependency`。
- 固定阅读基准及上游工作区HEAD仍是`7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`；fetch更新远端引用和对象，没有切换checkout或更改Mini-Pi基准。
- 本次为实际源码静态核对，未运行Pi模型或测试，不用旧快照冒称最新main已对齐，也不进行文件hash校验。

| 最新main文件/函数 | 实际行为与边界 | 对本章的作用 |
| --- | --- | --- |
| [session-manager.ts:1204 appendMessage](https://github.com/earendil-works/pi/blob/936e5f40aede9327b9142b63506ed2b68bc6b4ac/packages/coding-agent/src/core/session-manager.ts#L1204) | 将原消息作为会话条目追加，返回条目ID | 原始会话记录与提取结果分开 |
| [session-manager.ts:1261 appendCompaction](https://github.com/earendil-works/pi/blob/936e5f40aede9327b9142b63506ed2b68bc6b4ac/packages/coding-agent/src/core/session-manager.ts#L1261) | 保存带summary/保留边界的压缩条目 | 摘要不是五出口长期记忆候选 |
| [agent-loop.ts:399 transformContext](https://github.com/earendil-works/pi/blob/936e5f40aede9327b9142b63506ed2b68bc6b4ac/packages/agent/src/agent-loop.ts#L399) | 请求前变换AgentMessage，再convertToLlm | 保留原始Session与请求Context的区别 |
| [compaction.ts:585 getSummarizationFailure](https://github.com/earendil-works/pi/blob/936e5f40aede9327b9142b63506ed2b68bc6b4ac/packages/coding-agent/src/core/compaction/compaction.ts#L585)、[742–747](https://github.com/earendil-works/pi/blob/936e5f40aede9327b9142b63506ed2b68bc6b4ac/packages/coding-agent/src/core/compaction/compaction.ts#L742) | error/length不能当完整摘要；摘要尝试工具调用会被拒绝 | 后续提取适配器同样须在解析前明确终态，不能把截断当空结果 |
| [compaction.ts:618 completeSummarization](https://github.com/earendil-works/pi/blob/936e5f40aede9327b9142b63506ed2b68bc6b4ac/packages/coding-agent/src/core/compaction/compaction.ts#L618) | 将signal传入共享调用/重试链 | 真实提取的取消/重试需要另行定义和验证，不冒称硬截止 |

与固定基准的相关差异：session-manager文件未变；agent-loop新增默认请求identity合并。compaction不再以reserveTokens派生摘要输出上限，split-turn摘要接收customInstructions；reserveTokens仍参与上下文触发判断，error/length与工具调用拒绝行为保留。本章记录差异，不迁移整套新压缩实现。

已搜索agent/coding-agent核心及相关文档，并查看完整路径树中的memory相关文件；未见本项目的`content/proposed_route/reason`五出口长期候选协议。durable的MemoryStorage是内存存储后端，不是候选提取器。本章是Mini-Pi扩展，延续已核对MemoryBear正文/来源分离思路，不称为Pi已有长期记忆实现。

## 本章目标与边界

完整已保存Source与可信Scope→提取模型提出候选→检查请求终态→JSON解码→parse_candidate_items绑定程序Source→route_candidates→已有Draft/计划/显式执行。候选解析及它前面的响应结束检查/JSON解码均已分段验收；下一步接提取请求的组装与异步发送，当前不发送请求、读Session、生成元字段或写库。

模型每项只输出`content/proposed_route/reason`，结果为JSON数组。Source身份/原文/Scope由程序绑定；额外身份字段不接收。当前协议不产出key/kind/conditions/valid_from或action，这些仍来自已确认的调用方输入，后续扩展须明确字段依据与验收。

例：Source原文“以后讲解请尽量用Python举例。今天这题只解释，不改文件。我猜测试应该通过了。”。候选分别为“用户希望后续讲解尽量使用Python示例”(long_term)、“本题只解释，不改文件”(task_constraint)、“用户猜测测试应该通过”(needs_review)。模型建议可规范化但应保留“尽量”、当前任务范围与猜测状态；这不靠逐字相等验证。

合法空数组表示本次没有候选；错误不能降级为合法空结果。整批任一项格式不合格就抛错，不返回前半批；保留顺序和重复，不在解析时做语义合并。解析成功也不授予写入或撤回权限。

## 当前小段与验收

新增`mini_pi/memory/extraction.py`。助手准备`checked_candidate_items`格式/快照辅助：Scope和Source格式、非空原文、列表及每项恰三字段外壳；不替换传入Source。学习者手敲`parse_candidate_items`：范围/角色准入（空数组也检查）、逐项绑定同一完整Source、复用原候选核验、最后统一返回tuple。

6项标准反例在`tests/test_memory_extraction.py`：规范化正文/完整同一Source/顺序重复且零IO、空结果准入、容器与精确字段（含身份额外键）拒绝、坏后项整批错误、跨Scope/不允许角色及工具来源、五建议接入已有归组且无写入。2026-10-23学习者手敲后实际6项全部通过，0失败/错误/跳过，助手未修改核心；本小段技术验收通过。原始日志与verification.json在`local-learning/evidence/memw-extraction-candidate-acceptance/`。解析本身不分组或改写正文，不据此认定提取语义或完整MEM-W通过。

保真另用标注案例检查否定、强度、条件、时间、无依据补充和历史撤回，不用正文逐字相等当语义证明，也不声称解析器会识别全部提取错误。普通聊天按内容判断，不能仅因聊天形式就跳过可长期使用的事实/偏好。

后续真实适配器可复用现有请求转换、异步HTTP和取消收尾；当前QwenProvider.generate接受stop/tool_calls，返回Message不保留finish_reason，不能仅凭有正文就认定提取完整。终态/工具响应/JSON解码/取消和预算将在适配层另验；本轮未读取凭据或发真实模型请求。

## 本轮保存状态处理

重新读盘发现planning.py再次含cnadidate与return后旧占位。用户确认关闭planning.py/execution.py旧标签后，按此前明确授权恢复两处，实际7项CandidatePlanningTests再次全部通过，0失败/错误/跳过。不推断具体覆盖原因，不做文件hash或定时检查；新提取核心仍留给学习者手敲。本轮没有提交推送。

## 下一小段：模型响应的结束检查与JSON解码

2026-10-23继续同一提取章节，沿用本章已核对main与固定基准；再次读取上述getSummarizationFailure及工具调用拒绝代码。Pi摘要不接受截断或工具调用；本课将此边界用于Mini-Pi新增候选提取。当前generate只返回丢失finish_reason的Message，因此新函数接收非流式服务原始响应，不改旧Provider。

正常例：唯一choice的finish_reason=stop、role=assistant，content是三字段候选JSON数组，输出完整Source关联的候选tuple；content为[]时输出()。反例：finish_reason=length，即使content恰好为[]也抛错；失败、拒绝、工具调用或错误JSON不能降级为“无候选”。

助手准备checked_extraction_response外壳/非空正文格式检查，以及JSON重复键与非标准常量拒绝hook；不引入新DTO、存储状态或异常类，不耦合持久化私有解析器。学习者手敲parse_extraction_response的stop/assistant准入、工具/拒绝响应阻断、JSON解码/错误传播及既有parse_candidate_items接线。tool_calls缺失/null/[]可接受，function_call仅缺失/null，refusal仅缺失/null/空串；只接受唯一choice和完整纯JSON，不剥代码围栏或修补输出。字段/数组/来源仍由已验解析函数核验。

7项离线反例准备于tests/test_memory_extraction_response.py：正常内容/完整Source/顺序与输入不变；合法空结果；非stop终态优先拒绝；异常外壳和正文格式；工具/旧function_call/拒绝及畸形值；错误JSON/重复字段/非标准常量；下游Scope/角色/去向/额外身份字段及坏后项拒绝。核心仍占位，准备不计行为通过。实际异步发送、请求预算、取消传输/收尾及真实标注提取另行验收，本轮无真实模型请求或业务库写入。

准备结果：源码与测试AST通过，测试仅发现7项、0加载错误，实际执行0项。新增骨架曾未保留在磁盘，原候选核心完整；用户确认关闭extraction.py旧标签后恢复新增辅助及占位，读盘确认parse_extraction_response在104–114行，核心未代写。覆盖原因未证实，不做hash或循环复查；下一步替换114行占位后才做7项行为验收。

## 本小段验收（2026-10-23）

用户手敲parse_extraction_response第114–136行正确，助手未改核心。首次运行7项有6个方法通过，1个方法产生2条失败记录：辅助测试将sys.getrecursionlimit()+50层JSON假定为必然解码失败。本机独立探测Python3.14.5递归限制1000、1050层JSON实际可成功解码，该测试前提不成立。

仅修辅助测试：删除此深度阈值假设，以可控RecursionError核验解码错误转换/原cause保留，实际嵌套数组仍交下游格式政策拒绝，不给核心新增深度阈值。修正后7项全部通过，0失败/错误/跳过。验证正常候选和空数组、结束/身份准入、工具/拒答阻断、外壳错误、JSON语法/重复字段/非标准常量、下游Scope/格式与原异常传播；解析无网络、SQLite或Store变更调用。

实际初次与最终日志和verification.json在local-learning/evidence/memw-extraction-response-acceptance/。本段离线技术验收通过，整个MEM-W继续进行中；真实请求组装/发送、预算/取消收尾及语义保真评测尚未验收。未重跑其它回归、未做hash、未调用真实模型、未写业务库、未提交推送。
