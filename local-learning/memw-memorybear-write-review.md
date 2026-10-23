# MEM-W：红熊写入提取源码核对与quote争议

2026-10-22，用户明确要求查红熊仓库，质疑LLM改写导致逐字quote门禁拒绝正常候选。本次只做公开源码静态审阅，不运行红熊、不调用模型、不修改Mini-Pi核心，也不把研究结论当新接口已获实施授权。

固定参考提交仍为`a2960b3b6313704448d6f7ab0243aefede802238`，没有暗中换main。完整Git树3850项、truncated=false已读取；新增缓存`C:\Users\hyf\.codex\external-sources\MemoryBear-write-review-a2960b3`，未覆盖原5文件缓存。18个下载文件按该树中的Git blob SHA校验，原始源码行号以下载字节计数；网页文本提取器可能合并空行，不以其显示行号替代GitHub blob行号。

## 直接结论

红熊的偏好写入路径区分“LLM生成的规范化偏好正文preference_text”和“当前原消息正文”。它不在已审阅的P1提取入口要求preference_text是原消息子串。模型允许消解指代、形成独立偏好所需的最小规范化，同时提示要求保留对象、否定、比较对象、强度、条件。提示约束不等于运行时已证明语义正确。

因此，逐字相等适合核验一个明确声明为原文引文的字段；不适合用来限制LLM提炼后的记忆正文。我们当前MemoryCandidate只有quote，Entry.text又直接返回Source片段，尚没有独立的规范化记忆正文能力。前段来源锚定测试只验证其既定原文引用契约，不能被扩张成完整提取设计的合理性证明。

## 固定源码证据

| 已核对行为 | 源码与边界 |
| --- | --- |
| 允许最小规范化，保留否定/强度/条件 | [P1提示59–71行](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/storage_services/preference_engine/prompts/p1_identify_preferences.jinja2#L59-L71) |
| preference_text要求第三人称，source_message不由模型输出 | [P1输出定义138–153行](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/storage_services/preference_engine/prompts/p1_identify_preferences.jinja2#L138-L153)、同文件17行 |
| P1实际使用结构化生成/Pydantic和本体分类合法值筛选，没有在该方法做原文子串比较 | [prompt_runner.py:53–75](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/storage_services/preference_engine/prompt_runner.py#L53-L75)；不由此声称全仓没有任何文本比较 |
| 当前消息ID和原文由程序从target_message写入PreferenceTrace日志 | [processor.py:76–85](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/storage_services/preference_engine/processor.py#L76-L85) |
| 实际创建/更新偏好以mode和preference_text为条目内容 | [processor.py:112–130](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/storage_services/preference_engine/processor.py#L112-L130)、[存储create部分](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/storage/custom/preference.py#L48-L80) |
| P2确实有精确匹配，但old_text是已存偏好快照目标，new_item必须等于本轮P1 incoming，防二次改写 | [processor.py:184–225](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/storage_services/preference_engine/processor.py#L184-L225)；不是preference_text等于用户原消息 |
| 通常图写入路径可把original_text与pruned_text分开保留 | [write_pipeline.py:1015–1024](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/pipelines/write_pipeline.py#L1015-L1024)，UserSource节点及关系进入graph command的[930–948行](https://github.com/SuanmoSuanyangTechnology/MemoryBear/blob/a2960b3b6313704448d6f7ab0243aefede802238/api/app/core/memory/pipelines/write_pipeline.py#L930-L948) |

偏好分支中能直接确认原消息绑定到trace日志；构造PreferenceItem和已审阅写入参数未传原消息引用。不能凭提示里的source_message约定就宣称每条偏好具有完整持久化证据关系。常规图路径UserSource与实体的关联还含语义匹配；不能把该路径的保证无条件套在偏好分支上。

## 对Mini-Pi的最小设计建议（尚未实现）

1. LLM输出“提炼后的记忆内容”和建议处理方式，允许不改变含义的改写；不要求模型逐字复制quote或数字符位置。
2. 程序保留完整不可变Source，绑定可信Scope与source_id。原文由程序取得；是否需要精确片段可作为附加来源定位设计，不先强制模型抄写。
3. 来源引用一致性与提炼内容的语义支持分开。后者检查否定、条件、时间、强度及任务/长期范围，不能用字符相等或结构化JSON合格替代。
4. 不照搬红熊封闭本体、关键词门控、图数据库或复杂更新架构；本次借鉴的是内容/来源分离和明确的写入阶段边界。

举例（说明数据职责，不是已实现结构）：原文“以后请用Python举例”，提炼正文“用户要求后续示例使用Python”，source_id仍由程序绑定原消息。二者不必字符相同，但提炼正文不得凭空增加“只能”“所有场景”等原文未表达内容。

这不能靠删selection.py里的一个if完成：MemoryCandidate、MemoryDraft/Entry.text、序列化/候选身份与入库/更新/读取测试均需明确是否保存派生正文，并保持旧原文数据语义。先展示这一联动方案，再按学习规则分段实施；当前全文门禁及来源不可变规则不静默绕过。

本次不据用户研究请求改现有核心或测试标准。先保留已敲代码及原验收记录，MEM-W进入候选正文/来源接口设计复核，未开始下一段真实提取或写入。代码研究没有证明红熊在具体语句上一定抽取正确，也没有运行其服务或验证真实持久化/取消行为。
