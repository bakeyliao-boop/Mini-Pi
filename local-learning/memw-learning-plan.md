# MEM-W 写入选择与候选提取：学习入口

> 当前（2026-10-27）：[MEM-04首版技术验收](mem04-acceptance.md)完成，74项正式复验全过；已串联本页所述的固定提取、明确计划写入、检索、Context及每轮请求。固定响应不证明真实语义泛化，旧试点失败成绩保留；本页“下一步接Session/MEM-04”均为历史，当前接续见memory-resume.md。

> 2026-10-26当前：extract_session学习者核心已核对，5专项全过；保存Session→Source→五组→明确字段计划→临时SQLite写入/重试/新Store读回实际通过，见[接线验收](memw-session-integration-acceptance.md)。固定响应不证明语义泛化；首版字段及动作由可信调用方明确提供，不新增自动元字段模块。现在进入[MEM-04整体框架](mem04-context-plan.md)，核心尚未开始，先说明完整输入输出。下列“下一步Session”均为历史。

> 最新：用户要求few-shot并确认2次后，[v2.2定向小试](memw-reference-v22-results.md)完成，正文/路由2/2，本次通过；两次额度用完。只加一组对照示例，旧6/7等证据不改，不扩字段/出口/核心。下一步可独立继续Session接线，先核对用户已敲代码，不用固定响应替代语义证据。以下v2.1记录保留历史。

> 2026-10-26最新接续：用户确认6次后[v2.1真实复验](memw-overlap-v21-results.md)已完成，技术6/6、正文/路由/严格语义6/7，H4缺参数指代漏判，整体未通过。剩余问题交原侧任务做依据审查，不以反复调参阻塞主对话，不追加第7次。H5部分重叠按冻结允许拆合只计一次。保持3字段5出口、不接开关；旧S3真实4/5与v2离线8/9不改，Session接线独立后续。

> 当前进度（2026-10-23）：第15小段已授权执行6次真实提取、无重试，技术6/6，语义整轮未通过；严格内容+分流6/9，S3未知指代与S4观察分流有明确问题，S1归因为边界。此前代码/辅助测试保留各自口径，MEM-W保持进行中。6次预算已用完，新真实复验另行安排；接续以memory-resume.md为准，未提交推送，不做例行hash。

2026-10-22，MEM-03已按[首版范围技术收口](mem03-acceptance.md)。用户已确认采用[红熊源码核对](memw-memorybear-write-review.md)中的“规范化正文与完整原来源分离”思路。当前进入新候选接口第1小段：助手调整数据容器、格式辅助和测试，新版来源核验已由学习者敲入，13项测试通过；旧quote契约9项验收保留为历史，不作为新接口已通过的证据。独立正文存储/读取及兼容已通过219项记忆测试（203旧回归＋16新增正文用例），Entry.text已由学习者手敲验收；按建议去向归组已验收，旧占位已删除；store.latest及首次新增计划已验收，238项记忆测试全部通过；同候选重试已修复验收，244项记忆测试全部通过；重试/新增整合入口已验收，248项记忆测试全部通过；首次显式更新计划已恢复；首次明确撤回计划已验收，284项记忆测试全部通过，遗留不可达旧占位为非阻塞清理项；完整写入计划及真实提取尚未接线。

## 在现有链路中的位置

```text
已保存的原始会话 + 可信Scope/任务/时间背景
    → MEM-W 提取候选、核验证据并分流
    → MEM-W 与已存系列比较，形成明确写入计划
    → MEM-01 remember / MEM-02 replace或retract
    → MEM-03 按需检索
    → MEM-04 组装实际请求Context
```

MEM-01/02负责可靠保存和版本变更；MEM-03负责读出适用且相关的证据。它们目前都不决定“这句话值不值得记、该提取哪一部分”。MEM-W补上这一步，任务约束走独立出口留给MEM-04。

固定Pi阅读基准仍为7f9e119；会话保存和请求前transformContext是既有行为，本课的Scope/候选核验/写入计划是Mini-Pi新增能力，不冒称Pi原生自动长期记忆。MemoryBear核对固定于a2960b3，已审阅P1规范化偏好提取、原消息trace及独立图写入来源路径；具体证据与保证边界见源码核对文档，不复制其图存储、本体分类或假称整批原子。

## 一个完整例子

可信调用方提供用户A、Mini-Pi项目、当前任务ID、记录时间；完整Source原文为：

> 从现在起，后续学习都用 Python 举例。今天这道题只解释，不改文件。我猜测试应该通过了。谢谢。

| 原文内容 | 分流结果 | 后续用途 |
| --- | --- | --- |
| 从现在起，后续学习都用Python举例 | 长期偏好候选 | 核验后形成semantic Draft；来源仍是用户陈述，不变成客观验证结论 |
| 今天这道题只解释，不改文件 | 当前任务约束 | 留给MEM-04固定约束输入，不推广为跨任务偏好 |
| 我猜测试应该通过了 | 待核对 | 原会话保留，不作为实际测试通过事实写入 |
| 谢谢 | 忽略长期写入 | 原会话仍保留 |

Source始终保留完整原文。新候选保存规范化content，不要求模型生成quote/下标/来源编号；Source由可信程序读取并绑定，不裁剪后伪造新Source，不从模型confidence推断可信身份、真实工具结果或世界事实。需要前文消解指代时须保留所用原记录定位；本小段尚不接上下文或真实提取，无法确定的内容留待核对。

## 按行为分段

1. **新候选及来源核验，暂不写库。** MemoryCandidate(source,content,proposed_route,reason)中Source由可信程序绑定；模型协议仅后三项。助手准备数据容器与格式辅助，学习者将validate_candidate_source改为(scope,candidate)，先检查格式，再比较candidate.source.scope和角色。去掉候选quote/下标/自报编号，不以来源核验证明content语义正确。新版来源核验已敲入，13项格式与来源测试通过；本层仍不授予写入许可。
2. **独立正文保存与兼容。** MemoryDraft已追加content=None：None保持旧原文语义，非空str保存新正文；Entry.text显式判断is not None。原Source不可改写，start/end由程序指向完整来源，当前全文门禁不暗删。旧payload/ID/回执指纹保留；新正文参与draft冲突比较及更新请求指纹，不进入candidate_id，不自动迁移旧记录。先以旧格式固定夹具重验remember/replace/retract，再验证search读取新正文及await后重新核对。
3. **分流、受控写入计划及提取接线。** 候选先分长期/任务约束/忽略/待核对/撤回意图，长期候选的key/kind/conditions/valid_from需明确依据，不能藏在helper中猜测。当前结构尚不足以授予写入许可；核对最新提交版本，不能拿历史适用版本代替CAS。先固定输出验流程，后单独安排真实提取预算和标注样本，分别报告误记/漏记/支持与实际写入；失败/取消不当无记忆或成功。

每段先展示输入/输出、时序和反例，再给一小段可照敲的核心。用户手敲选择、核验、写入决策；助手准备骨架、模型协议外围、格式辅助、测试、运行及证据；骨架中的核心保留占位，敲入后再验收。

## 两个不能省略的设计门槛

- 来源绑定和格式合格不证明字段或结论受支持。规范化必须保留否定、条件、生效时间与强度；工具来源仍保留完整JSON及调用定位，模型“测试通过”不能替代实际结果。保真提示及标注反例揭露提取错误，不伪造通用程序语义证明；不确定项留待核对。
- 现有remember/replace/retract各自拥有独立事务。预检后逐条调用不能宣称整批原子。进入写入段前必须明确单次变更和多变更的提交契约；未实现多变更原子提交时，应整批拒绝或待核对，不能留下部分写入却报告整批失败零写入。

完整验收矩阵沿用agent-memory-implementation.md中已确认的MEM-W契约，包括明确偏好、重复、任务约束、未证实测试、真实工具情景、变更、条件并存、片段错证据、撤回防复活及提取失败/取消。自动技能执行、后台反思、独立向量索引和自由语义合并不在本单元。

## 历史第1小段：旧quote候选与来源锚定

本节为旧接口的历史学习记录；当前执行本文上方的新候选路线。

文件`mini_pi/memory/selection.py`。助手准备frozen MemoryCandidate(source_id,start,end,quote,proposed_route,reason)及validate_candidate_shapes；用户手敲validate_candidate_source的格式接线、Scope/来源编号/角色准入和精确quote一致性核对。使用现有MemoryPolicyError，正常返回None，拒绝则抛错；不创建dummy MemoryDraft，不改MEM-01全文门禁。

Scope由可信调用方提供，Source由已有read_memory_source读取，模型只提供候选。检查仅证明“候选引用与提供的Source一致”，不独立认证原Session作者、不验证事实真实性、片段语义完整性或长期价值。proposed_route/reason只是建议，当前不执行分流、撤回或写入。

示例Source(s1, "以后用 Python 举例。")与同源全文候选可通过，错Scope/编号/角色/quote拒绝；即使“我不喜欢Python”中的“喜欢Python”是精确子串，也不能据锚定通过给予写入许可。现有policy继续拒绝此部分片段，后续明确片段支持核验前不放宽。

准备证据`local-learning/evidence/memw-source-anchor-prepare-8504b628/`，保留MEM-03冻结基线；格式辅助反例进入标准tests，当前核心阶段反例只准备、不预先记通过。未写库、未调用模型，未改既有核心。

格式辅助4项已实际通过，核心5项只准备。MemoryCandidate是可被忽略、待核对或转任务出口的提取建议，因此不强制承载MemoryDraft的key/kind/valid_from；Draft留到后续确认拟写入时构造。当前仅核对scope/source_id/role/quote一致性，助手提供9行可照敲代码，用户替换selection.py第63行占位；不由helper测试或建议字段授予长期写入许可。

首次敲入核对已实际运行5项核心与4项格式测试：格式和非法来源拒绝路径通过；两个正常路径方法仍被可达旧占位阻断（含子场景共11个NotImplementedError），无skip/xfail。本段未验收，指导仅删selection.py:72，合法输入随后自然返回None。原代码快照/完整日志/verification.json位于local-learning/evidence/memw-source-anchor-review-2867079d/，助手未修改源码，MEM-03既有基线未变。

删除占位后实际重验：AST比较证明仅删除该raise，保留九行检查及所有其它模块逻辑；合法输入正常None，来源范围/编号/角色/逐字引用不匹配均拒绝。5项核心与4项辅助共9项全部通过，0失败/错误/跳过；包括不写DB/不执行建议、不可变输入和否定裁剪不能越过既有全文写入门禁。源码与测试哈希稳定，原MEM-03基线未变；证据为local-learning/evidence/memw-source-anchor-acceptance-a965fa74/。仅本小段通过，不据锚定推导语义完整或长期价值；下一段再明确候选分流与证据支持契约。

## 当前第1小段：规范化候选与来源范围核验

输入为可信Scope及MemoryCandidate(source,content,proposed_route,reason)。例如Source原文“以后请用Python举例。”、content“用户要求后续示例使用Python。”；本层只检查格式、来源Scope和user/tool准入，正常None，跨用户/项目或不允许角色抛MemoryPolicyError。不比较content与原文，不执行候选建议，不证明语义保真；真实提取、数据库写入和MEM-04尚未接入。

助手准备新容器、validate_candidate_shapes(scope,candidate)和标准测试；用户已敲入新版validate_candidate_source(scope,candidate)。实际执行6项格式＋7项来源测试共13项全部通过，无失败/错误/跳过；正常隐式None，Scope及角色拒绝行为符合契约，不改写Source、不执行建议或调用DB/模型。助手只删除旧接口过渡注释，模块AST不变；源码副本/执行日志/verification.json位于local-learning/evidence/memw-normalized-source-review/。本小段技术验收通过，尚未接语义核验、写入或真实提取，下一步为独立正文存储与旧格式兼容。

## 当前第2小段：独立正文存储与旧格式兼容

助手准备MemoryDraft.content默认None、严格双格式编解码及正文格式辅助；旧原文payload/候选ID/更新及撤回指纹保持兼容，新正文参与定义比较和更新请求指纹。固定旧JSON与SQL夹具由改动前实现生成，实际重建旧SQLite和回执重放通过；旧回归203项及新增存储/兼容12项全部通过。

学习者已手敲models.py中MemoryEntry.text的三行读取选择：有content时返回独立正文，否则沿用旧Source切片；助手未修改核心。实际运行标准test_memory*.py共219项全部通过，无失败/错误/跳过，含4项正文读取/检索反例：新正文保留原来源、None回退原文、实际向量文档输入为独立正文、await后正文变化被拒绝。旧格式/指纹/SQL库与回执兼容同轮通过。日志及verification.json位于local-learning/evidence/memw-content-acceptance/。本小段技术验收通过，不代填理解；不据此证明提取语义正确或整个MEM-W完成，下一步进入分流及写入计划。

## 当前第3小段：建议归组 → 写入计划 → 现有事务执行

固定Pi仍以7f9e119的SessionManager.appendMessage和请求前transformContext为阅读基准；本段是Mini-Pi新增记忆入口，不冒称Pi原生自动长期记忆。红熊参考仍限规范化正文与原来源分离，不据此复制图存储或本体设计。

完整行为：规范化候选及完整Source → 格式/来源核验 → 按proposed_route归组 → 明确拟写字段和证据依据并读取最新series → 形成remember/noop/replace/retract/review计划 → 限定变更数 → 现有Store事务执行并分别报告结果。归组不证明候选语义、长期价值或控制授权；proposed_route和reason均不能直接触发写库。

示例：已有学习示例语言JavaScript的v1，用户新原话“从现在起，后续学习用Python举例。今天这题只解释、不改代码。我猜测试通过了。谢谢。”，人工确认预期候选分别进入long_term、task_constraint、needs_review、ignore。只有第一条在字段与来源依据明确后拟定replace：同一Scope/key/conditions、semantic、规范化正文、明确valid_from、expected_version=1及程序提供的稳定operation_id；其它出口不新增长期记忆。任务建议在MEM-04消费前由可信调用方绑定任务背景，当前route接口没有task_id，不能据归组就跨任务应用。

与现有方法的关系：

| 计划情形 | 执行入口和边界 |
| --- | --- |
| 目标Scope/key/conditions系列尚不存在 | remember，若并发新增导致冲突则停止，不自动转覆盖 |
| 已确认同一来源候选且完整规范化Source/Draft相等 | noop或利用remember幂等返回；仍须保留当前状态，不能把retracted当有效偏好 |
| 真实新来源明确更新同一系列 | replace，expected_version取主记录最新持久版本，operation_id来自可信调用方；事务内再次CAS及状态/时间核对 |
| 真实用户明确撤回且目标明确 | retract，保留原用户Source作控制依据，精确key/conditions、最新版本及稳定operation_id；withdrawal标签本身不授予权限 |
| 不同来源仅正文相同、来源/条件/时间不足或语义未明 | 不据相似度自动去重或更新，留待核对 |

规划需要key/kind/conditions/valid_from及其依据，当前content/route/reason并不足以自动得到这些字段；先用可信显式字段验证执行行为，再安排模型提取及标注评测，不把猜测藏进helper。最新series已有backend.latest_entry(conn,scope,key,conditions)，Store.latest现已接只读head入口，不开写事务建库读取计划。历史search版本不是CAS head。

首版每份计划最多调用一次持久变更API；replace或整系列retract的多行SQL仍算一次业务变更。多项新增/更新/撤回在批事务未实现前整批转待核对，必须在第一次写入前停止；多个noop、任务建议和待核对可以与一次持久变更并存，不伪称逐条独立提交是整批原子。

本次手敲范围仅route_candidates：输入可信Scope和候选list/tuple，输出五个固定去向的tuple字典，保持组内顺序及重复候选和完整Source。助手准备checked_candidate_batch外壳校验/快照及标准测试；核心已由学习者敲入并验收。核心逐条调用已验validate_candidate_source，按建议归组；中途异常不返回部分结果，也无DB/模型调用。用固定候选检验归组行为，不把该测试当真实提取质量或价值判断完成。

第3小段准备结果：checked_candidate_batch仅验证Scope和list/tuple批次外壳并快照，4项辅助测试实际全部通过。route_candidates仍保留占位，5项来源/五出口/顺序重复/异常无部分返回及撤回建议无副作用的核心反例已准备但未运行。执行日志及verification.json见local-learning/evidence/memw-routing-prepare/。学习者将手敲该完整函数的来源接线和归组逻辑；本段返回的是分组后的建议，不能当写入计划或长期价值判断已完成。

第3小段归组验收：学习者已敲入route_candidates，实际运行test_memory*.py共228项全部通过，含4项批次辅助和5项核心反例，无失败/错误/跳过。五出口/顺序/重复/来源拒绝及无写入或控制副作用符合契约。第103行旧占位在无条件return后不可达，作为非阻塞清理项指导用户删除，助手未修改核心。证据local-learning/evidence/memw-routing-acceptance/；本小段归组行为技术验收通过，不代填理解，也不将建议归组当语义选择或写入计划完成。下一步为读取最新series并形成受控写入计划。

## 当前第4小段：只读最新版本与首次新增计划

用户确认旧占位已删除，实际读盘一致。latest按Scope/key/conditions查询最大持久version，future/retracted也返回；None表示该系列不存在，不表示某时间暂不可用。backend及Store委派为助手准备的I/O辅助，读不到库不创建目录/数据库。已跑228项旧回归＋6项最新读取辅助，全部通过；执行日志/verification.json见local-learning/evidence/memw-first-plan-prepare/。

用户手敲plan_remember(store,scope,source,draft)：输入已经明确来源和字段的拟新增记忆，先走validate_draft与规范化，读取latest；None则返回RememberPlan(scope,source,draft)，已有系列则抛MemoryConflict停止新增分支。返回计划不执行持久变更；实际remember仍在事务里检查，规划之后他人新增不能被覆盖。重复/replace/retract计划后续分段，不由最新条目比较替代旧候选重试。计划容器、导入和测试由助手准备，plan_remember已由学习者敲入；实际238项记忆测试全部通过，含4项新增计划反例，无失败/错误/跳过。证据local-learning/evidence/memw-first-plan-acceptance/；仅本段首次新增计划技术验收通过，不代表完整写入计划或提取语义验收。

第4小段验收：plan_remember保存版本正确且无旧占位，用户核心未被助手改写。238项标准记忆测试全部通过，具体观察到规划零持久写入、规范化完整计划、已有各状态停止，以及原Store执行时拒绝规划后被其它连接抢先新增的交错场景。学习记录已更新，后续已有系列规划须按稳定candidate_id识别旧版本重试，不能只比较latest正文；未开始重复/replace/retract核心实现。

## 当前第5小段：识别同候选重试

沿用remember已有幂等语义，不新增容器：规划前以candidate_id(scope,source,draft)定位历史候选，再通过store.get(scope,id)只读取得完整Entry。完整规范化Source/Draft一致才认作同一次提交重试；同ID但来源、正文或生效时间变更抛MemoryConflict。这里比较两次提交，不比较提炼正文与原文，也不做不同来源的语义去重。

本次用户手敲planning.find_retry。未命中返回None，仅说明此候选不存在；仍须走plan_remember的系列存在检查及实际remember事务中的来源不可变/去重保护。命中可返回superseded v1，即使latest已为v2；retracted也原样返回，不恢复有效状态、不据此注入Context。不调用latest，不写库、不重构已验plan_remember或Store。实际remember继续独立执行事务内的幂等核验，不依赖这次预查作为提交保证。

例：s1曾存为v1，s2已更新成v2；再次提交完全相同s1/Draft时返回v1的当前状态。s3即使正文相同，也不因相似而算作s1重试。完整流程将在后续接为find_retry命中→保留既存结果，未命中→plan_remember或显式变更判断；当前只准备单独识别函数。

第5小段准备：planning.py:39保留find_retry占位，助手补齐candidate_id/MemoryEntry导入；plan_remember及Store函数未改。标准tests/test_memory_retry.py已准备6项反例，AST检查通过，核心尚未运行。准备记录local-learning/evidence/memw-retry-prepare/verification.json；本段不重复运行已通过的旧测试，不据语法通过说重试行为已验收。

第5小段首次核对：find_retry整体多缩进4空格，实际嵌套于plan_remember的return之后，模块无公开find_retry。AST可解析，但新重试测试模块实际ImportError，6项核心行为测试未运行；本段未验收。指导仅将planning.py:38–57整段左移一级，助手未改核心；错误与源码副本见local-learning/evidence/memw-retry-review/，修正后再验。

第5小段修复验收：用户授权后仅左移find_retry整体缩进，并补回保存版本缺少的candidate_id/MemoryEntry辅助导入；原重试判断逻辑和已验plan_remember未变。先前NameError失败日志保留；最终实际244项记忆测试全部通过，含6项重试专项，无失败/错误/跳过。旧版本/撤回状态保留、同ID定义冲突、None不当新增许可等符合契约；证据local-learning/evidence/memw-retry-fix-acceptance/。本小段技术验收通过，不代填理解；尚未将find_retry接入plan_remember，不声称整体写入计划完成。

## 当前第6小段：先识别重试，再规划首次新增

保留已验find_retry和plan_remember，新增小入口plan_remember_or_retry：先调用find_retry，命中直接返回既存MemoryEntry；未命中才调用plan_remember，空系列返回RememberPlan，已有系列继续抛MemoryConflict。顺序不能颠倒，否则完全相同候选会被“系列已存在”阻断。不存在的新候选不自动成为更新，原retracted/superseded条目也不被激活。

输入为同一组store/Scope/Source/Draft，输出为既存MemoryEntry或具体RememberPlan；异常不吞掉。调用方须区分已有结果和拟新增请求，不能一律再次写入；这里仍是两次只读预判，实际提交由原Store事务复核。助手只准备函数骨架及反例，核心接线由学习者手敲，不新增容器或改写已验函数；本段不含replace/retract规划。

第6小段准备：planning.py:60保留plan_remember_or_retry占位，既有函数AST不变；4项整合反例与语法检查已准备，核心未运行。证据local-learning/evidence/memw-remember-entrypoint-prepare/verification.json。用户只手敲调用顺序与命中分支，不重写已验函数；敲入后再验收。

第6小段验收：用户手敲的先判重后新增顺序正确。保存版本再次缺此前修好的两项辅助导入，单例实测NameError；用户关闭旧planning.py标签后助手仅补回candidate_id/MemoryEntry，函数AST不变。最终248项标准记忆测试全部通过，含4项整合反例，无失败/错误/跳过。第72行无条件return后的旧占位不可达，作为不阻塞行为的清理项提示用户删除；未改核心。证据local-learning/evidence/memw-remember-entrypoint-acceptance/，本段技术验收通过，不宣称完整MEM-W或语义去重完成。

第6小段清理确认：用户已删除旧占位；实际模块AST除该不可达raise外与248项验收版本一致，两项辅助导入仍正确。无需重复旧回归，整合入口本段保持技术验收通过，助手未改核心。下一步为明确更新的计划，先讲新来源、最新版本和operation_id关系。

## 当前第7小段：首次显式更新计划

更新不是“不同候选就覆盖”。输入为已明确更新意图的新原始Source、完整Draft字段及可信调用方提供的operation_id；本段不从proposed_route或相似度猜更新意图。Store.latest按精确Scope/key/conditions读取最高持久版本；缺系列、非active、kind变更或生效时间不晚于head均停止本分支。合法时返回冻结ReplacePlan(scope,source,draft,expected_version=head.version,operation_id)，不写库、不提前递增版本。例：Python v1→新来源明确改TypeScript，计划expected_version=1，实际replace成功后才生成v2。

执行及重试必须把同一计划的完整字段直接交原Store.replace。其既有回执优先→历史结果重放→首次CAS/state/kind/time/source/候选核对顺序不变；规划后若另一请求先更新，首次执行冲突，不能自动刷新expected_version强行重试。原操作已成功后再出现v3或整系列撤回，原计划重试仍由回执返回原结果的当前状态，不复活旧事实。

plan_replace明确只负责首次请求规划，不是重复调用的恢复入口。同操作不得因失败/超时重读latest重建计划；调用方丢失原计划后的恢复目前不承诺。若后续要支持重启后重新进入规划恢复，需稳定原请求直交Store或规划层先核对receipt，不能用当前head挡住历史操作重放；该恢复设计在相关集成前另行明确，不冒称已实现。

助手准备ReplacePlan容器、require_text导入和测试，plan_replace核心留占位供手敲；不改已有规划函数或Store。本段完整行为是校验一次首次更新请求、读取目标head并生成完整请求计划，最终执行仍由原事务复核。语义提取/条件推断/整批提交及撤回规划不由本段通过推导。

第7小段准备：ReplacePlan及require_text导入由助手准备，planning.py:86的plan_replace仍为占位；6项标准反例和AST检查已准备，核心未运行。证据local-learning/evidence/memw-replace-plan-prepare/verification.json。手敲将完成一次首次规划的全部上述检查，不改变原replace回执优先契约；原计划重试直接调用Store，不重新规划。

第7小段首次核对：plan_replace已有两处拼写错误，planning.py:100 conidtions应为conditions，:105 lastest应为latest。6项专项方法实际运行未通过（8条含子测试的错误记录），第一处TypeError遮蔽后续检查。助手仅指出并指导这两处修改，未改核心；记录local-learning/evidence/memw-replace-plan-review/，修正后再验收。

第7小段修复验收：用户授权后仅修正conidtions/lastest，AST确认无其他逻辑变化。实际254项标准记忆测试全部通过，含6项更新计划反例，无失败/错误/跳过；planning.py在测试期间保持同一内容。原计划直接调用replace的回执优先重试，以及并发CAS/撤回不复活等已有行为均通过。证据local-learning/evidence/memw-replace-plan-fix-acceptance/；仅首次显式更新计划本段技术验收通过，丢计划恢复与完整自动写入仍未交付。下一步明确撤回控制计划。

## 当前第8小段：首次明确撤回计划（2026-10-23）

固定Pi基准仍为7f9e119；其原始Session保存与appendContextEdit投影编辑不能替代本课的长期记忆整系列撤回。本段是Mini-Pi在原有Store.retract之上增加的首次请求规划，不改原Session，不物理删除Source。

上层先确认真实用户撤回意图及精确目标，提供可信Scope、已保存的原用户Source、key/conditions和固定operation_id。模型withdrawal标签或Source.role=user本身不证明撤回意图；本函数不充当通用语义授权判断器。助手的normalize_retract_request仅检查格式、规范Source时间及conditions；学习者核心比较Scope、要求user角色，再读取最高持久版本，目标存在且active时返回RetractPlan(scope,source,key,conditions,expected_version=head.version,operation_id)。

例：指定示例语言系列已有v1/v2，用户明确撤回该系列。规划只返回expected_version=2的请求，不递增版本、不设置新valid_from、不写库。Store.retract实际执行时仍先查原回执，再做CAS与状态/来源核对，在同一事务把该精确系列所有版本标记retracted并保存控制来源及回执；其它用户/项目或不同conditions系列不受影响。未来生效但active的head也可撤回，不能用问题时间筛掉它。

首次执行前若出现新版本，旧计划必须冲突；同操作重试直接复用原计划交Store.retract，不重新规划，避免被retracted状态挡住原回执重放。同号改来源/目标/版本属于不同请求，不能复用。丢失原计划后的恢复仍不在本小段交付内；读取/解码失败也不能被当作目标不存在吞掉。

本节先恢复此前已授权修复但保存回退的plan_replace两个拼写，再准备RetractPlan、格式辅助和plan_retract占位；原Store与其回执顺序不改。核心由学习者手敲，固定测试只验证程序约束，不将句子夹具当作通用撤回意图识别。

第8小段准备结果：助手准备RetractPlan、normalize_retract_request及plan_retract占位（planning.py:144），用户只手敲范围/角色/head判断和完整计划返回。恢复先前已授权的更新拼写后，275项旧记忆回归及3项撤回格式测试全部通过，无失败/错误/跳过；6项撤回核心反例未运行。证据local-learning/evidence/memw-retract-plan-prepare/。输入来源仍须由上层确认意图，固定句子测试不充当通用授权识别；本段尚未验收，也未提交推送。

第8小段验收：学习者已敲入plan_retract，实际284项记忆测试全部通过，无失败/错误/跳过，含3项辅助＋6项核心。源码测试期间未变；只读计划、Scope/user、future head、整系列撤回及原计划回执重试/CAS边界符合契约。第169行旧占位不可达，未代改核心。证据local-learning/evidence/memw-retract-plan-acceptance/；本段技术验收通过，下一单元为统一写入执行入口及单次变更边界，不宣称自动意图提取或完整MEM-W完成。

## 当前第9小段：统一执行与一次变更边界（2026-10-23）

`execution.execute_plans(store, scope, items)`接在已确认的规划结果之后。输入为可信Scope及已有MemoryEntry/RememberPlan/ReplacePlan/RetractPlan列表或元组；输出按原顺序排列的MemoryEntry元组。已有Entry原样返回，只是先前读取的结果快照，不承诺执行时最新或读取可用。

执行分两步：先完整核对全部成员类型、与当前Scope一致及变更计划总数不超过1，再调用对应Store方法。Entry不算变更计划；两个计划即使是相同对象或可能命中回执，也保守整批拒绝且零Store变更调用。一次变更指最多一个Store操作，单个撤回仍可在该事务内修改整个系列多行；不宣称实现了任意多操作的批事务。

RememberPlan交给remember；ReplacePlan和RetractPlan携原expected_version、operation_id及完整字段交给replace/retract。不重新latest或重新规划，不刷新版本吞掉CAS冲突，不从withdrawal标签授予意图；执行异常向上传播，不把异常自动解释为零写入或成功。同一原计划的事务回执重试仍由原Store保证；丢计划恢复尚未交付。

助手准备`execution.py`导入、类型别名、批次外壳/tuple快照辅助和测试；用户分段手敲同一execute_plans中的完整预检与执行分派。第一段先完成整批预检，正常路径保留执行未实现占位；未敲完和实际执行反例前，本段保持进行中，不记为已验收。固定Pi基准7f9e119的SessionManager.appendMessage/appendContextEdit与请求前transformContext已重读；长期记忆计划执行是Mini-Pi新增能力。未来确需支持多变更时另行实现批事务并验证后项失败回滚，不以循环调用独立事务代替。

准备检查：execution.py与标准test_memory_write_execution.py语法检查通过，4项ExecutionBatchShapeTests实际全部通过；8项WriteExecutionTests已准备但尚未运行。旧284项记忆验收保持历史原口径，不把本轮辅助通过冒称为核心或完整MEM-W通过。本轮无真实模型调用、业务库写入或提交推送。

第9小段整批预检验收：用户手敲execution.py:37–49，实际读盘确认先快照、完整检查四种类型与当前Scope、仅统计非Entry计划，并在循环后拒绝超过一个计划。实际运行2项标准预检核心测试全部通过：非法尾项/混Scope，以及两个计划/重复同计划均在首个Store调用前拒绝。另以既有合成夹具受控探测空批次、仅Entry、Entry夹一个RememberPlan、单ReplacePlan、单RetractPlan共5组合法输入，均允许到达当前未实现的执行分派占位；Store调用为0，未创建数据库目录。

本轮只验收整批预检，合法路径的NotImplementedError是已知分段占位，不是完整执行成功；其余6项执行核心测试未运行，未重复旧全量回归。核心由用户敲入，助手未代改；结果见local-learning/evidence/memw-execution-precheck-review/verification.json。下一段替换第51行占位为执行分派，保留前置检查；未新增模型调用、业务数据写入或提交推送。

执行分派手敲安排：先以示例语言的新增/同候选重试/更新/撤回四种请求说明完整映射，再分两段敲入。首段将第51行占位替换为结果列表、逐项Entry原快照透传或RememberPlan委派remember、末尾返回tuple；ReplacePlan/RetractPlan暂在else明确抛未实现，不吞成成功。前置整批最多一个计划保证首段遇到未实现的更新/撤回前不会先执行其它写入。首段拟验空批次/Entry快照、实际单新增及异常传播三项既有核心反例；本轮仅提供代码，尚未敲入或执行，不能预记通过。

第二段再补两个elif，完整透传ReplacePlan的scope/source/draft/expected_version/operation_id及RetractPlan的scope/source/key/conditions/expected_version/operation_id，保持原Store回执优先与CAS语义。仍由学习者敲核心，助手不改已验预检或Store；辅助测试已准备，无需重复旧验收或新增模型调用。

执行分派首段验收：用户已敲入execution.py:51–64，Entry原对象透传、RememberPlan完整委派remember、结果按序append且循环外返回tuple。实际运行3项分派核心测试与2项预检回归共5项全部通过，0失败/错误/跳过；观察空批次返回空tuple、Entry原快照/顺序/状态保留且零Store调用，合成临时SQLite中实际新增并读回正文/来源，Store同一异常对象向上传播且仅调用一次，以及尾项非法/混Scope/多计划仍在任何变更前拒绝。

第61行空NotImplementedError仍阻止尚未实现的更新/撤回，仅影响诊断清晰度；第66行旧占位在return之后不可达，作为非阻塞清理项告知用户，助手未代改。本段技术验收通过，剩余3项更新/撤回/并发CAS执行反例未运行，不记为完整execute_plans通过。日志与verification.json见local-learning/evidence/memw-execution-remember-dispatch-review/；未新增模型请求、业务数据写入、提交或推送。

更新/撤回分派讲解准备：用户已清理两处，实际读盘确认else消息明确、return后旧占位已删除，原已验分派判断未变。以v1 Python→更新U1→v2 TypeScript→撤回R1为同一系列例子：更新原计划expected_version=1、operation_id=U1，重试仍带同一完整请求；Store先查回执，命中则返回本操作v2的当前状态，未命中才做最新版本CAS。若首次执行前被其它操作抢先更新，旧计划冲突，不能刷新版本强行重试。撤回v2的原计划使用expected_version=2及独立R1，撤回不新增版本，同请求重试仍优先回执。

本轮先提供ReplacePlan的elif供用户手敲：完整传scope/source/draft及原expected_version、operation_id给Store.replace，保留统一append/tuple返回和前置预检；else暂明确撤回未实现。下一段再接RetractPlan。辅助测试按更新/撤回拆分并发CAS场景，便于各分支独立验收；本轮不执行尚未实现的分派核心，也不提前记通过，不新增模型调用或提交推送。

辅助准备检查：原合并CAS测试已拆为for_replace/for_retract两个独立方法，私有辅助复用原实际SQLite交错场景；版本冲突、零覆盖及禁止重规划断言保留，其它测试未改。AST与测试发现通过，当前模块4项辅助＋9项核心共13项；仅发现未执行，不将发现数量当验收结果。

ReplacePlan分派验收：用户已敲入execution.py:60–65，实际确认完整透传scope/source/draft及原expected_version、operation_id给Store.replace，不重新latest/规划、不吞异常。实际运行2项更新核心与2项预检回归共4项全部通过，0失败/错误/跳过；在合成临时SQLite实际生成v2，后续独立操作生成v3后原计划仍按回执返回superseded v2且无新增写入。另验证首次执行前被其它操作抢先更新时抛MemoryConflict，原有版本/库内容不变；非法尾项/混Scope/多个计划仍在任何变更前拒绝。

本段更新分派、原计划重试和版本冲突技术验收通过，助手未修改核心。撤回仍在第66–67行明确占位，剩余2项撤回执行反例未运行，完整execute_plans保持进行中。证据local-learning/evidence/memw-execution-replace-dispatch-review/含实际tests.log及verification.json；下一段手敲RetractPlan分派，未新增模型请求、业务库写入、提交或推送。

最后撤回分派手敲准备：当前整批预检已限定四类、前三种分支已处理，因此保留第66行else作为剩余RetractPlan，替换未实现占位为Store.retract调用；完整传scope/source/key、conditions、原expected_version和operation_id，保留统一append与tuple返回。撤回没有新Draft，不能误传draft或遗漏条件；示例按周末条件撤回v2，只将该条件系列所有版本标retracted，返回版本仍2，工作日系列保持；同一完整计划重试优先操作回执，不重新规划。

助手准备必要的非空conditions隔离反例，弥补已有撤回执行测试仅用空条件时无法揭露漏传conditions的缺口；核心仍由用户手敲，本轮不运行未实现撤回测试，也不提前宣称完整执行入口通过。敲入后先验撤回/回执重试/CAS/条件隔离，再验完整执行入口与记忆回归；无新模型调用授权，不提交推送。

新增标准反例test_retract_forwards_conditions_and_withdraws_only_target_series_all_versions：非空周末系列和空条件默认系列都推进到v2，再撤回周末系列，必须仅修改目标全部版本、保留其它系列及原事实Source；两系列相同head版本可揭露漏传conditions造成误撤，避免仅因版本不等而侥幸拒绝。AST及仅发现检查通过，模块当前4辅助＋10核心共14项，未执行新增核心。撤回待验反例现为3项：原计划回执重试、首次并发CAS、非空条件隔离。

最后撤回分派首次核对未通过：用户已敲入，但execution.py:71将item.operation_id误写为item_operation_id，第73行调用后仍有旧NotImplementedError。只实际运行1项原计划撤回/回执测试，1项NameError错误、0失败/跳过，发生在参数求值阶段，尚未调用Store.retract。第二处由源码确定且被首个错误遮蔽：仅修拼写后可能先完成撤回事务再抛未实现异常，不能将此报错理解为零写入。

指导用户将第71行改为operation_id=item.operation_id并删除第73行旧占位，保留其后统一append/return；助手未修改核心。其它2项撤回专项、完整14项入口及记忆回归暂未运行，保持待修/待验，不预记通过。首次实际日志与verification.json在local-learning/evidence/memw-execution-retract-dispatch-review/；无凭据读取、模型请求、业务数据写入或提交推送。

最后撤回分派修复与完整验收：用户明确授权“帮我调整好”后，助手仅将item_operation_id改为item.operation_id并删除调用后的旧NotImplementedError，文本比较确认除此两处外与修复前一致，未改规划或Store。一次标准记忆套件按撤回3项→其余入口11项→其余记忆284项顺序执行，298项全部通过，0失败/错误/跳过；入口14项包含撤回3项，均为298项子集，不重复相加。实际覆盖整系列撤回与事实Source保留、原计划回执重试、非空周末条件不影响默认系列、并发CAS拒绝，以及完整入口的批次准入/Scope/最多一计划/四类分派/顺序快照/异常传播。

本段受控计划执行入口技术验收通过，学习者理解确认仍另记；核心由用户手敲，助手按明确授权修复两处。执行期间源码保持不变，证据local-learning/evidence/memw-execution-final-acceptance/含修复前后单文件、实际tests.log及verification.json。未运行无关全项目测试，不把历史491项全量当本轮结果；未新增真实模型调用、业务库写入或提交推送。整个MEM-W仍进行中：下一步讲清候选→Draft字段依据及五出口，用固定候选接通规划/执行，再安排真实提取与保真评测，之后MEM-04。

## 当前第10小段：候选到Draft，再接已有规划/执行（2026-10-23）

整体链路为可信Scope与完整Source→固定候选→route_candidates归组→上层核对长期适用性、正文及字段依据→draft_from_candidate装配Draft→收齐只读计划→一次execute_plans。长期出口才进入本装配入口；任务约束留给当前任务/MEM-04，忽略和待核对不写长期库；withdrawal建议不能自行产生控制权限，明确撤回另用plan_retract，不经过Draft。所有候选先转换/规划后统一执行，不能边转换边写，继续保留最多一个变更计划的门禁。

完整例子：原Source记录于2026-10-23、上海时区，原文“从2026年11月1日起，周末学习用Python举例。今天这题只解释，不改文件。我猜测试应该通过了。谢谢。”。四个固定候选分别进入long_term/task_constraint/needs_review/ignore。本例上层确认长期候选正文仅为周末学习示例偏好，明确key=example_language（属性名称）、kind=semantic（持续偏好）、conditions=((period,weekend),)（原文周末条件）、valid_from=2026-11-01T00:00:00+08:00（原文明确生效日期），不自动用记录时间替代生效时间。

装配函数新增在selection.py，签名draft_from_candidate(scope,candidate,*,key,kind,conditions,valid_from)->MemoryDraft，四字段必须显式提供，不新增DTO或approved布尔。核心由用户手敲：复用validate_candidate_source、要求long_term去向、构造完整Source定位start=0/end=len(source.text)且content=candidate.content、复用validate_draft、返回Draft。完整原Source不改写，生成正文无需是原文子串；规范化继续由既有规划函数承担。标签/格式/来源准入不证明语义保真，字段若无依据应留待核对而不是补默认值。工具来源的kind仍由原policy限制为episodic。

空目标系列接plan_remember_or_retry得到RememberPlan，execute_plans实际保存v1；同候选重试由原入口返回已有Entry，有系列但不是同候选时停止新增，不自动覆盖，明确更新再走plan_replace。key/conditions必须维持同一系列含义，不能改名绕过更新或撤回；跨来源语义去重尚未交付。本段先完成单候选装配，下一段接批次规划；真实提取及保真评测另行安排。

助手仅准备导入、函数签名/说明/占位及标准反例。固定Pi 7f9e119的SessionManager.appendMessage（会话追加）和agent-loop请求前transformContext已重新定位；此候选装配与计划接线是Mini-Pi新增能力，延续已核对MemoryBear a2960b3的正文/来源分离思路。语法与AST对照确认原selection类/函数未改，核心仍占位，不预记验收通过；无真实模型调用、业务库写入或提交推送。

准备检查：tests/test_memory_candidate_draft.py新增6项核心反例，覆盖完整来源/允许规范化正文/显式未来时间且零SQL或模型I/O、四个非长期出口拒绝、来源Scope/角色拒绝、tool仅episodic、非法或缺失显式字段，以及固定四出口→一个Draft→RememberPlan→显式执行→同候选重试的合成闭环。语法及仅发现检查通过，发现6项、加载错误0、实际执行0；本段尚未敲入，不沿用之前298项结果冒称新增行为通过。

第10小段首次手敲核对：用户保存的来源检查、long_term门禁和Draft字段对应与本段设计一致，但selection.py:135–136的validate_draft和return多缩进4空格。第134行关闭括号处于参数列表内，其缩进本身不阻塞，建议134–136一起左移4空格与第126行draft赋值对齐。实际AST检查在第135行触发IndentationError: unexpected indent；6项行为测试均未运行，不能记为通过。

助手未修改核心，指导用户修正这三行缩进，并按用户本轮新版规则在所展示Python行尾使用#注释对应解释。失败源码及syntax-check.json保存在local-learning/evidence/memw-candidate-draft-review/；修正后再验本段，未新增模型请求、业务库写入或提交推送。

第10小段缩进修复验收：用户明确授权后，助手仅将134–136三行左移4空格，文本比较确认其它内容未变，语法检查通过。实际运行test_memory_candidate_draft.CandidateDraftTests六项全部通过，0失败/错误/跳过；验证完整来源保留、规范化正文及显式未来字段、非长期四出口/错误Scope或角色拒绝、工具仅episodic、非法/缺失字段拒绝，以及固定四出口→单长期Draft→只读规划→显式SQLite保存v1→同候选重试仅读回/透传。

本段单候选装配及固定单例闭环技术验收通过，核心由用户手敲，助手按授权仅修缩进；不由此推导语义提取质量、完整批次接线或整个MEM-W已完成。证据local-learning/evidence/memw-candidate-draft-fix-acceptance/含修复前后单文件、实际tests.log及verification.json，测试期间源码未变。按用户本次范围仅运行六项，不重复此前298项或全仓验收，也不将六项加总后伪称全回归已运行；无真实模型调用、业务库变更、提交或推送。下一步先讲清候选到只读写入计划的接线，再分段手敲；Python讲解继续在对应行尾加#注释。

## 当前第11小段：按明确动作形成只读计划（2026-10-23）

开始核对发现execution.py完全等于此前修复前快照，仅恢复了item_operation_id误写及撤回后可达占位两处旧问题。按此前明确修复授权恢复同两处，并实际运行入口模块14项全部通过，0失败/错误/跳过；恢复后与此前已验源码相同，未确认外部回退原因。定向差异及准备记录在local-learning/evidence/memw-planning-connection-prepare/，没有进行全库哈希或定时反复检查。

本段只新增薄入口planning.plan_candidate(store,scope,candidate,*,action,key,kind,conditions,valid_from,operation_id=None)，不再包装route_candidates或execute_plans，不新增DTO/回调。四个元字段及action由可信调用方根据来源明确提供；先拒绝未知action、remember多余编号和replace缺失/空编号，再复用draft_from_candidate。remember委派plan_remember_or_retry，输出既有Entry或RememberPlan；replace只做首次明确更新，委派plan_replace并传原operation_id，输出ReplacePlan。异常原样传播，规划不写库。更新重试直接复用原计划执行，不重新进入plan_candidate；丢计划恢复仍未交付。

完整例子：同一用户/项目的周末示例语言系列已有v1=Java，新Source明确“2026年11月1日起周末改用Python举例”，还包含“本题只解释”“猜测测试通过”“谢谢”。route_candidates保留五组；只把long_term候选及明确字段交新入口，调用方依据更新意图传action=replace、operation_id=U1。Draft装配后plan_replace读取v1生成expected_version=1的ReplacePlan，此时数据库不变；收齐计划后execute_plans才产生v2。若把同一新来源选为remember，已有系列会阻止新增，不能自动转更新；任务约束、待核对、忽略和撤回建议均保留各自出口，明确撤回独立走plan_retract。若拟变更多于一个，统一执行入口整体拒绝，不能逐项规划后立即执行。

助手准备导入、带行尾注释的签名/说明/占位及7项反例，用户本段手敲完整单候选准入→Draft→规划分派约二十行；按完整行为交付，不再将同函数拆成两轮占位。固定Pi 7f9e119会话追加与请求前Context转换已重新定位，新入口仍是Mini-Pi长期记忆扩展。AST对照确认既有planning类/函数未变，新测试语法及仅发现通过（7项、0加载错误、0实际执行），核心尚占位，不预记通过。反例覆盖新建只读、旧状态重试、禁止隐式更新、动作/编号早拒绝、更新原计划重放、来源门禁、五出口保留及两计划执行前拒绝。无真实模型请求、业务库写入或提交推送。

第11小段首次手敲核对未通过：用户已实现动作/编号准入、Draft装配及两个规划分支，但planning.py:205将candidate.source误写为cnadidate.source。实际按要求运行全部7项，3项通过、4项方法报错，含旧候选superseded/retracted两个子场景共5条错误记录，0断言失败/跳过；不能用错误记录数倒算通过方法数。通过项为明确更新及v3后原计划回执重放、非法动作/编号在查询前拒绝、来源/去向/字段门禁；remember相关路径均被NameError阻断。

第211行旧NotImplementedError位于无条件return之后不可达，仅为非阻塞清理项。指导用户第205行改为candidate.source并删除第211行旧占位，代码说明使用对应行尾#注释；助手未修改核心。实际日志、用户源码及verification.json在local-learning/evidence/memw-candidate-planning-review/。执行器仍与此前已验源码一致，未再次回退；未重复其它回归，无真实模型请求、业务库变更、提交或推送。

第11小段修复验收：用户明确授权修正拼写、删除不可达占位并要求仅跑7项、停止不必要hash校验。助手只修这两处，实际运行CandidatePlanningTests七项全部通过，0失败/错误/跳过。本段明确动作准入、只读新增/更新规划、旧状态候选重试、不隐式覆盖、原更新计划重放，以及五出口保留/两计划执行前整体拒绝均符合预期。

受控候选到只读计划接线技术验收通过，核心由用户手敲、助手按授权修两处；实际tests.log及verification.json在local-learning/evidence/memw-candidate-planning-fix-acceptance/。未做文件hash或快照对比，未重跑旧全量、调用真实模型、写业务库、提交或推送。下一步先设计真实候选提取协议与保真评测，不由固定案例通过推导整个MEM-W已完成。

## 当前第12小段：模型候选协议与Source绑定（2026-10-23）

按新版AGENTS要求，实际核对上游当时main=936e5f40aede9327b9142b63506ed2b68bc6b4ac，固定基准与上游checkout仍7f9e119；相关函数、差异和章节门禁见[memw-extraction-plan.md](memw-extraction-plan.md)，不是仅用旧快照对齐。当前小段只处理已解码模型数组→程序绑定完整Source的候选，不发模型请求或写库。模型字段仅content/proposed_route/reason，Scope和Source不能由模型自报，现有四元字段及显式action不由本小段生成；合法空数组与提取失败分开。

助手准备extraction.py格式/快照辅助和parse_candidate_items签名/说明/占位，用户手敲来源Scope/角色准入、逐项构造并核验候选、整批tuple返回；6项反例仅语法/发现通过，行为尚未运行。保真评测另验否定/尽量/条件/时间/猜测，不把格式或来源合格当语义证明，后续再接带完整终态与取消/预算的真实适配器。

本轮先解决新的保存回退：planning.py又含此前拼写错误及旧占位，用户确认关闭两个旧标签后，按原授权恢复并实际7专项全部通过。覆盖原因未确定，未做hash或定时复查；不将新协议进度掩盖旧缺陷。新核心未代写，无真实模型请求、业务库变更、提交或推送。

第12小段手敲验收：parse_candidate_items保存内容正确，助手未修改核心；实际运行CandidateExtractionTests共6项全部通过，0失败/错误/跳过。覆盖同一完整Source/顺序重复、合法空结果仍准入、非法容器与身份字段、坏后项整批拒绝、Scope/角色及五类建议接入route_candidates；解析函数自身不分组、不改写正文、不做IO或写入。格式与来源合格不证明语义保真，原消息关联也不授予写入许可。

实际日志和verification.json在local-learning/evidence/memw-extraction-candidate-acceptance/。下一步讲解并接入请求终态与JSON解码，区分正常空结果与失败/截断/错误JSON；真实模型调用另行安排。本轮未重跑其它回归，无真实模型调用、业务库写入、提交或推送，D主线仍12/30。

## 当前第13小段：模型响应结束检查与JSON解码

接在已验parse_candidate_items之前：parse_extraction_response接收非流式原始响应，只在唯一结果、stop结束、assistant纯正文且无工具/拒绝时解码JSON，再交已有解析函数。正常[]可返回空tuple，截断时即使正文[]也必须抛错；JSON错误、重复字段、非标准常量不修补或吞为空。助手准备外壳/正文格式辅助及两个严格JSON hook，学习者敲入上述准入和接线核心，7项离线反例待行为验收。沿用当前提取章节最新main核对，原Provider不变；尚未接入异步发送/预算/取消收尾或真实效果评测，完整MEM-W继续进行中。详见memw-extraction-plan.md。

第13小段手敲验收：保存代码符合契约，助手未修改核心。首次实际7项中6个方法通过，1个方法有2条失败记录；原因是辅助测试假设1050层JSON在当前Python必然抛RecursionError，但本机3.14.5实际成功解码，不能据此要求核心增加深度限制。助手将此反例改为可控解码器RecursionError传播检查，并补嵌套数组走既有候选结构拒绝；随后仍为7项专项，全部通过，0失败/错误/跳过。

本段正常/空结果、失败或截断不进入候选解析、工具/拒答阻断、严格JSON、来源政策与原异常传播均通过离线技术验收。初次日志和修正后日志/verification.json保存在local-learning/evidence/memw-extraction-response-acceptance/，不以测试通过填写理解确认。下一步设计提取请求组装与异步发送、预算/取消收尾；未新增真实模型调用、业务库写入、全量回归、hash、提交或推送，D主线仍12/30。

## 当前第14小段：提取请求组装与异步发送

按用户此前关于quote、范围、哪些值得记、失败与无候选、输出如何接线的疑问，明确模型仍只提出content/proposed_route/reason；完整Source和身份由程序保留，候选tuple归组后再按出口处理，长期写入仍需有依据的四元字段及明确动作。模型建议标签不授予写入/撤回权限，结构与来源合格不证明语义保真。输出接线表见memw-request-plan.md。

本段已重新核对最新main=42cb822f（API与ls-remote一致），实际读取专用摘要请求/取消/重试及Agent请求源码，固定7f9e119 checkout不变。Pi摘要显式拒error/length/toolCall，不可等同于本项目严格stop及JSON候选协议；后者是Mini-Pi扩展。新建extraction_client.py提示/输入辅助及两个占位，核心由学习者手敲；轻量子类复用原Provider的配置/_send/HTTP收尾与实例次数，未复制网络层，未修改已验解析或原Provider。

9项合成/本地HTTPS专项准备，核心待敲，准备不计行为通过。单条完整Source、无工具、无跨消息指代；请求次数包含失败/取消或解析失败，不重试；原request_records只在内存保留请求正文，不默认打印/落盘，received仅表示收到响应。真实提取效果、实际Session及MEM-04仍待实现。无凭据读取、真实模型调用、业务库写入、hash或提交推送，D13-B及12/30不变。

第14小段首次手敲核对：组装第74行误写record_at键及source.record_at属性，第81行误写messgaes。实际仅运行ExtractionRequestTests的1项，user/tool两个子场景均在前一属性处AttributeError，合计2条错误记录、0断言失败/跳过；后一未定义变量仅源码发现，未实际触发。其余组装流程未见实质问题；extract第97–100行四步已敲入、源码顺序正确，8项异步行为未运行，不能据源码收口。

助手只指出两处精确修改位置，未代改核心；日志/verification.json在local-learning/evidence/memw-extraction-request-review/。当前先修组装，再验整段，不要求重复敲extract；不做hash、其它回归、真实模型调用、业务库写入或提交推送。

第14小段授权修复验收：用户明确要求调整后，仅将record_at键/属性改为recorded_at、messgaes改为messages；保留用户已敲的其余组装和extract实现。实际运行test_memory_extraction_client全部9项（组装1＋异步8），全部通过，0失败/错误/跳过；正常/错误来源、原始响应解析、错误不吞、次数预算与已到达取消零发送均符合契约。

3项真实本地HTTPS同时验证成功请求及关闭、超时实际断开且无重试、重复取消在close门闩释放前不报告结束，释放后响应/客户端关闭并上抛取消。本段请求与异步接线技术验收通过，未调用外部模型或写入业务库；实际日志及verification.json在local-learning/evidence/memw-extraction-client-fix-acceptance/。下一步设计真实提取的标注与调用计划，语义保真、实际Session和完整MEM-W仍待验，不以测试替学习者确认理解。未做hash、其它回归或提交推送，D13-B及12/30不变。

## 当前第15小段：真实提取小样本与调用计划

6条合成Source涵盖普通聊天事实/偏好、未来日期和条件并存、原任务约束/猜测/未知前文、带版本范围与数值的合成工具观察、撤回旧偏好、纯寒暄。9个必需语义单元按含义核对，允许改写与同用途拆合，限定须在content中保留；合理保守needs_review和可用长期候选分开报告。固定数据examples/fixtures/memory_extraction_eval_v1.json及完整门禁/调用计划见memw-extraction-evaluation-plan.md，gold不发模型。

计划固定qwen3.8-flash北京，最多6次串行，每条一次、输出上限1536/次、无自动重试或额外judge API；技术错误停后续，语义错误保留继续原案例，不改提示重跑。官方价已查，按每条输入预留4k粗估整轮约0.044元，非硬金额上限，usage缺失记未知，费用以实际计价/核账为准。本轮仅准备样本/计划/离线预览，真实调用0次；下一步先准备运行辅助和预览，实际执行需明确授权。

开始读盘发现旧拼写再次恢复，用户确认关闭extraction_client.py后按既有授权恢复两处，实际9项再次通过，未猜测覆盖原因。随后实际组装6条请求，确认材料仅role/recorded_at/text、无gold或tools，最大消息2347 UTF-8字节（不等同tokens）；证据分别在memw-extraction-client-restore-before-pilot及memw-extraction-pilot-prepare。无凭据读取、真实模型/业务库调用、hash、其它回归或提交推送，D13-B及12/30不变，不把语义计划当实际通过。

第15小段授权执行结果：新增默认预览的examples/memory_extraction_eval.py记录辅助，不改已有核心提取/Store；6项离线门禁实际全通过后，唯一live进程按S1–S6串行真实执行6次，全部stop/解析/Source绑定通过。发送前ledger与6个原始响应逐一核对，无重试/额外judge/gold泄露，未写长期记忆库；所有输入是合成样本。

逐案语义核对未通过：S3未知先前方案写成“之前确定的方案”，缺未知限定且加强确定性；S4工具测试观察错分task_constraint，正文项目/v2/范围/3项1失败正确；S1用户事实未显式保留自述归因，按冻结标准保守记边界，不等同虚构事实。完整内容7/9、内容及有效分流6/9；3案全过、2案明确错、1案边界。S2额外约束有原文支持、S6 ignore正确，不因输出数量或非逐字改写判错。

实际输入3126＋输出692＝3818 tokens，缓存0，调用采集进程约18.797秒，按北京标准价估算0.0043692元、账单未核对；辅助开发/标注/评阅耗时未计量，不当作0或完整系统总成本。可携带报告memw-extraction-pilot-results.md，真实原始/语义/综合验收证据local-learning/evidence/memw-extraction-live-20261023-01/。6次授权已用完，不改提示/标注重跑；下一步先澄清归因口径并离线改进未知指代和工具观察分流，新真实复验另定预算。MEM-W仍进行中，D13-B/12/30不变，未提交推送或全库hash。
