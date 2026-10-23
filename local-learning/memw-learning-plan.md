# MEM-W 写入选择与候选提取：学习入口

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
