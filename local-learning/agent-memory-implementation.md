# Mini-Pi 记忆模块实现

## 当前目标与工作区

- 目标：2026-10-21 10:00（Asia/Shanghai）面试前，优先完成可运行、可验收的记忆模块。本阶段停止以面试口述作为推进主线，按完整行为编码与验证。
- 实现工作区：`C:\Users\hyf\.codex\worktrees\mini-pi-memory\Pi`，分支 `codex/agent-memory`。
- 代码基线：`74b12cb54ff7da0a436b7d9b588f6ed14d7f5eb8`，已归档 D12；固定 Pi 阅读基准仍为 `7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`。
- 原目录 `C:\Users\hyf\Documents\ChatGPT\Pi` 的 D13-A/B 未提交代码保留原样；没有把未完成 Agent 入口作为记忆实现前置条件。本工作区没有暗中复制原目录 D13-A 的消息字段或模型终态协议。
- 当前状态：MEM-01、MEM-02 的来源入库、显式版本更新、整系列撤回及操作回执已通过技术验收；117 项记忆测试全部通过。MEM-03 检索和 MEM-04 Context 集成待实现，技术结果不代填学习者理解状态。
- 2026-10-19 用户已确认本次 20 个文件的范围与中文提交说明，授权提交并推送到 `origin/codex/agent-memory`；实际结果以 Git 提交和远程分支核对为准。其他范围的提交/推送仍需另行授权。

## MEM-01/02 交付与复现

本次交付是独立 `codex/agent-memory` 分支中的来源入库、显式版本更新、整系列撤回和持久操作回执。核心流程由学习者分段手敲，辅助层与反例由助手准备，此前个别段落按授权修正。MEM-03 有效记忆检索和 MEM-04 模型 Context 集成尚未实现；`get` 是原始版本核对入口，不承诺当前可用性过滤。

在仓库根目录使用 Python 3.14 执行：

```powershell
python -B -X utf8 -m unittest discover -s tests -p "test_memory*.py" -v
python -B -X utf8 -m unittest discover -s tests -v
```

2026-10-19 提交准备：记忆专项 117 项全部通过；全仓库 324 项中 322 项通过、2 项因 Windows 符号链接权限（WinError 1314）跳过，0 失败、0 错误。全仓库测试前后源码/测试哈希一致。仅清理 store 模块说明、末尾空行、行尾空白和失效占位注释，函数 AST 一致；另清理 policy 的行尾空白（AST 不变），修正 replace 测试的过时说明。清理后记忆专项 117 项再次全部通过。原始执行日志与快照保留在本地忽略目录 `local-learning/evidence/mem0102-precommit-20261019/`，不随 Git 发布；其他证据目录引用同样仅为本机证据定位。

提交准备范围为 10 个记忆模块文件、7 个记忆测试文件，以及 README、本实现记录、主学习路线入口共 3 份文档。原目录 D13-A/B 学习现场及本地数据库、配置、执行证据均不纳入。中文提交说明为“完成MEM-01来源入库与MEM-02版本更新及撤回”。用户已确认该具体范围，按授权提交并推送到 `origin/codex/agent-memory`；不合并主分支。下文各阶段“未提交或推送”为当时历史状态。

## 首版交付契约

完成的含义是所选行为在实际代码和反例中通过，不能以脚手架、测试预设通过或一次演示代替。

| 单元 | 行为 | 核心手敲与辅助分工 | 验收门禁 |
| --- | --- | --- | --- |
| MEM-01 | 显式来源记录入库，换进程仍能读；错误来源不落库，同候选重试不重复 | 用户敲来源准入与写入决策；助手准备辅助层与反例，并按明确授权修复当前段 | 2026-10-19 技术验收通过：53 个标准记忆测试与 3 个首次写入边界测试，真实 SQLite/JSONL/跨进程/冲突/回滚与资源清理 |
| MEM-02 | 显式 expected_version 替换、整系列立即撤回、持久操作回执；版本与适用时间分开 | 用户敲版本/撤回/重试决策；助手准备辅助与反例，并按明确授权修正此前段落 | 2026-10-19 技术验收通过：117 项记忆测试全绿（含 16 项 replace、10 项完整 retract）；理解确认单独记录 |
| MEM-03 | 在可信用户/项目范围按 key/关键词、条件、问题时间检索适用记忆 | 用户敲可用性/条件选择与排序；助手准备查询 I/O 和测试数据 | 跨用户不返回、错误条件/时间不选、superseded 在原区间可用、retracted 不作为有效记忆 |
| MEM-04 | 每次模型请求组合当前任务、完整近期交互和记忆，原 Session 不被投影污染 | 用户敲 ContextBuilder 和请求前接线；助手准备适配器、快照与集成反例 | 实际 provider 输入、原始 history/Session 不变、调用/结果配对、预算超限、准备失败 error 结算、取消清理及零额外模型/工具 |

SQLite 主记录直接用于首版关键词检索，不先引入独立向量索引，因此不把异步索引一致性列为已实现能力。候选由可信调用方显式指定，首版保存完整原文与元数据；不自动用模型抽取事实、生成摘要或学习可执行技能。摘要接口、自动提取、语义合并和向量索引后续另开单元，需先定义额外模型调用的预算、来源核验、失败和取消门禁，不能靠删减字段暗称已完成。

这里的来源锚定证明保存了什么原话/观察，不证明用户陈述是客观事实。首版保留完整来源，工具来源只按本次观察作为情景记录；存入程序性文本不授权执行或修改程序规则。

## MEM-01 完整行为与文件联动

```text
可信调用方给 scope + 已保存来源 + 显式候选
               ↓
validate_draft：数据形状 → 身份范围/来源准入/完整原文门禁
               ↓
remember：规范化 → 稳定候选 ID → 单事务检查来源与重放/冲突 → 写入
               ↓
短连接关闭 → MemoryEntry 返回 → 新进程/新 Store 在相同范围读回
```

| 文件 | 职责与所有者 |
| --- | --- |
| `mini_pi/memory/models.py` | 助手准备只读数据容器；Scope、Source、Draft、Entry 不隐藏准入或版本决策 |
| `validation_helpers.py` | 助手准备类型/非空、带时区时间、条件形状和片段位置边界；不决定哪些角色可写 |
| `session_source.py` | 助手准备真实 JSONL 来源读取，保留原始角色和完整工具状态；不执行工具、不写会话，身份范围仍由可信调用方提供 |
| `policy.py` | 学习者手敲四项业务门禁：来源属于当前范围；user/tool 准入；tool 仅情景；首版必须整条原文 |
| `codec.py` | 助手准备规范化、稳定标识、构造和严格 JSON 编解码，不决定记忆有效性 |
| `sqlite_backend.py` | 助手准备参数化 SQL、范围过滤、事务/连接关闭；不 UPSERT、不自动重激活或替换 |
| `store.py` | 学习者手敲 remember 的校验、重放返回、来源/已有版本冲突和首次持久化；get 只是核对已有版本 |
| `tests/test_memory_backend.py` | 助手准备真实 I/O、进程、回滚与损坏数据反例，只能证明辅助层 |
| `tests/test_memory_source.py` | 助手准备真实 Session 读回、来源定位稳定性和错误状态保留反例，不把来源定位等同作者身份认证 |
| `tests/test_memory_write.py` | 助手准备业务反例；核心占位时应真实失败，不能改成 skip 冒称完成 |

### 输入、输出与反例

正常输入：scope=`user_a/project_a`；来源为该用户已保存的整条“后续请用 Python 举例”，带稳定 source_id 与带时区 recorded_at；候选 key=`example_language`、start=0、end=len(source.text)，另给 valid_from。

预期：门禁返回 None 后才准许进入数据库事务；remember 返回带来源和版本的 Entry，原文完全可追溯；同一候选重试返回已有 Entry，不新建副本；换进程按同一 scope/id 仍可读。

反例：来源属于另一个用户；来源实际为 assistant 的猜测；把“不喜欢 Python”仅截取成“喜欢 Python”；tool 观察直接写成脱离场景的语义事实；source_id 被改写原文；同一属性已有另一来源却想隐式覆盖。这些都不能越过本单元门禁或被默默作为正常新增。

MEM-01 先只做首次新增。对同 scope/key/conditions 的已有另一来源返回 MemoryConflict，MEM-02 再通过 expected_version 显式更新。重复已撤回来源必须返回原撤回状态，不将它重置 active。

### 资源、事务与时间边界

- Store/Backend 构造只登记路径，业务拒绝前不创建目录/数据库。
- 合法写入才建立短连接与 schema；一次业务事务使用 BEGIN IMMEDIATE，成功提交，异常回滚，finally 关闭。来源与条目行不允许部分提交；schema 初始化与数据库文件存在本身不等于某条记忆写入成功。
- 只读不存在的库返回空值，不偷偷创建空库。读写 SQL 参数化；scope 查询由辅助层强制带 user_id/project_id，规则与反例一并解释，不要求学习者手敲整段数据库调用。
- recorded_at 是记录时间，valid_from/valid_to 是适用区间；规范化只处理时区/格式，不推断它们相等。MEM-02 不自动解决乱序回填或重叠区间，冲突明确返回待核对。
- 不引入后台写入。未来 provider 侧只读与投影的取消必须完成所选清理后再传播；SQLite 锁等待与同步处理不宣称硬实时停止。整个 run 预算与单请求字符/token 估算分开定义。

## MEM-02 设计契约与辅助准备（历史准备记录，最新状态见顶部）

本阶段继续增加 Mini-Pi 的长期记忆协议；固定 Pi 的 appendMessage/appendCompaction 保留会话来源与投影分工，不提供这里的属性版本、CAS 或撤回协议。2026-10-19 再次核对上游 HEAD 为固定阅读提交。MEM-01 remember 函数保留，新增核心由学习者分段手敲，助手按明确授权修正当前段；辅助层与反例由助手准备，当前阶段进度以本记录顶部和实际证据为准。

- 系列严格由 scope（用户/项目）、key 和规范化 conditions 标识；不同条件组合独立，不自动推断语义重叠。replace 只替换同一系列与记忆类型，来源必须可追溯，不能改写旧 Source。
- replace 输入新 Source/Draft、expected_version 和稳定 operation_id。expected_version 比较最新已提交事实版本，包括尚未生效的未来版本，而非当前时间适用的版本；还须核对系列没有撤回。新生效时间须严格晚于链尾生效时间，不处理插入既有区间中间的复杂回填或乱序修订。
- 同一事务把旧链尾标 superseded 并将 valid_to 设为新 valid_from，再插入 v+1 active。active/superseded 表示版本链位置，适用性仍按左闭右开区间判断；未来 v2 生效前，superseded 的 v1 仍可在原区间使用。
- retract 定义为立即停止使用整个精确系列，不是取消某一个未来版本。提交后该系列各 Entry 标 retracted，原 Source/历史区间保留供独立审计；普通偏好读取不再使用这些内容。未来版本尚未生效时也可撤回，不强行把 valid_to 改到 valid_from 之前。
- 撤回保存真实用户指令来源与操作回执，不把指令伪装成新的偏好事实，也不制造事实 v3；最新事实版本号保留，之后状态检查与持久撤回记录阻止普通写入/替换复活。取消单一未来版本、恢复已撤回系列和复杂回填均需另定义明确操作，本单元不提供隐式恢复。
- operation_receipts 的 schema 与辅助 I/O 已准备：按 scope/operation_id 唯一定位，保存规范化请求指纹、操作来源及结果定位。构造和只读不创建表；合法写事务按需原子创建/迁移，真实临时旧库已验证。业务核心仍需先核对回执重试，再做版本与状态检查；同 ID 改参数冲突，同操作重试不增加版本、不再次执行状态变更。回执说明操作曾提交，不证明目标条目现在仍有效；重试结果必须保留条目的当前撤回状态。
- 版本/状态修改、新来源、结果与回执必须同事务提交，失败全部回滚、关闭连接后才返回；记忆失败不重跑历史工具。SQLite 锁竞争仍显式失败，不伪称硬实时或自动解决并发冲突。

示例时序（手动设计，未执行）：工作日学习偏好 v1 为“晚上”，从 10 月 19 日 09:00 生效；10 月 19 日 15:00 接收“明天起工作日早上学习”，以 expected_version=1 创建 v2，valid_from=10 月 20 日 00:00。此时 v1 区间为 [19 日 09:00,20 日 00:00)，v2 为 [20 日 00:00,无上界)，19 日查询当前偏好仍选 v1，但下一次修改必须基于最新已提交版本 2。随后用户撤回该工作日系列，应保存撤回回执并停止使用全部该系列记录，不回退到 v1；周末系列不受此操作影响。

当前文件联动：models.py 已追加 MemoryReceipt；operation_codec.py 已准备操作参数校验、完整规范请求指纹、回执装配与严格 JSON；sqlite_backend.py 已追加回执 I/O、只修改 state/valid_to 的元数据入口及精确系列读取；store.py 导入和签名由助手准备，学习者已完成 replace 输入准备，MEM-01 remember 函数文本保留。tests/test_memory_operation_codec.py 的 12 项及 tests/test_memory_operation_backend.py 的 21 项辅助反例，与原有 53 项一起实际通过；replace 全行为仍未通过，未 skip/xfail。辅助 SQL 由助手准备，改变哪些版本、何时失效、何时返回仍由学习者分段手敲；不能把辅助就绪当作 replace/retract 已实现。

replace 手敲顺序：先接 validate_draft、validate_operation_input、normalize_source/draft 和 replacement_fingerprint，合法输入暂时停在未完成占位；再接同事务回执核对、来源/候选核验与 CAS、旧区间关闭、新版本和回执提交。shape 校验只检查 expected_version 的正整数形式，不比较数据库真实版本；请求指纹不证明来源真实性或事实有效性。operation_id 标识同一次逻辑操作，重试时保持不变。

2026-10-19 replace 准备段首次读盘：学习者已接入准入、操作参数形状、来源/候选规范化和请求指纹，但 store.py:64 使用了未定义的 expected_verison，应为签名中的 expected_version。语法解析通过；实际运行两个非法输入测试方法（新库拒绝不落盘、已有库内容不变）均通过。正常合法候选实际抛 NameError: expected_verison，数据库及父目录未创建，尚未到达预期占位。测试前后 store.py SHA-256 均为 `1665a247d1323fd3ded39848ecc76f9373a79332f74ac8f5de9c195b1c574084`；助手仅核对并给出具体修正，未代改新核心。源码快照、日志与 verification.json 位于 `local-learning/evidence/mem02-prepare-review-71d04ea1/`。本段未通过，不推进回执代码。

2026-10-19 replace 准备段修正后核验：学习者已将 expected_version 拼写修正。AST 解析通过，两个非法输入测试方法通过；合法候选完成准备后实际到达预期 NotImplementedError，未创建数据库及父目录。测试前后 store.py SHA-256 均为 `04ea551d4444410d26b64a7aa90bad6f6f50b492865788035eae92e6b8f4a76a`；源码快照与结果位于 `local-learning/evidence/mem02-prepare-verified-80b2be35/`。本段代码准备行为通过，助手未代改，未据此宣称回执重放、实际 CAS 或版本替换通过，也不代填理解状态。下一段在同一事务内读取回执，核对 action/请求指纹与结果来源、候选、版本关系，存在相同操作时返回条目当前状态；无回执仍保留未完成占位。

2026-10-19 replace 回执段首次读盘：查询、请求指纹与结果匹配判断已敲入；store.py:71 的 MemoryConfilct 需改为 MemoryConflict，:82 的数据错误 raise 应统一缩进 20 空格，:83 的 return 应为 16 空格。AST 实际在 :83 报 IndentationError（unindent does not match any outer indentation level）。:84 的空 NotImplementedError 应删除，末尾占位应缩进 12 空格放在 with 内，不能留在事务外。尚未运行该分支行为测试，未推进 CAS。当前源码 SHA-256 为 `abbb1d63f7bdf50f7faf96c4a28437b78d59c92f1da102df6e29794096bce3b3`；快照与逐行缩进诊断位于 `local-learning/evidence/mem02-receipt-review-72d29f0c/`。助手未代改核心，先引导修正后再验证。

2026-10-19 replace 回执段授权修复与验收：用户明确要求“帮我调好并验收这一段”。助手只修正当前事务块的异常类拼写、缩进和调用换行，删除多余空占位，将唯一未完成占位置于 with 内；学习者请求/结果匹配判断保持，块外字节完全一致。修前/修后与 change.json 位于 `local-learning/evidence/mem02-receipt-fix-d18a5871/`。修后 store.py SHA-256 为 `17114e864179e15f426006ed1d409e92c01c0f3e97b39fe1cac8b2abd7bd956c`，语法通过。

实际执行 88 项原有/辅助/输入回归，全部通过；另执行 verify_receipt_replay.py 的 5 个方法、19 个场景，0 失败、0 错误、0 跳过。用公开 backend 在真实临时 SQLite 预置已提交版本/回执，验证 active/superseded/retracted 当前状态返回、已有 v3 后原 v2 操作重放、同 opid 改请求/动作冲突、同指纹但坏 expected/result version/source/draft 或结果缺失时报数据错误、无回执/跨用户/项目到达预期占位且数据不变。每次调用均实际检查旧连接 execute 报 ProgrammingError、独立连接立即获取写锁；受控 commit OperationalError 传播且没有成功返回。首次无回执路径回滚所有 schema，不将空文件称更新成功。预置撤回状态不代表 retract API 已实现，受控故障不代表真实磁盘故障验收。运行前后全部记忆源码/测试哈希一致，证据为同目录 regression.json/.txt、receipt-tests.json/.txt、verify_receipt_replay.py。仅本段通过，完整 replace、CAS、新版本提交和 retract 仍待手敲与验收。

2026-10-19 版本门禁及提交段首次读盘：学习者已补齐 latest/CAS、状态/类型/时间、来源不可变与旧候选拒绝，以及旧区间关闭、新 Entry/回执构造、同事务写入顺序。代码静态核对未发现本次新的名称错误；提交段 entry/receipt/if/写入/return 为 14 空格，应与 previous 同级为 12 空格，if 内 insert_source 应为 16 空格。AST 实际在 store.py:107 报 IndentationError: unexpected indent，未运行完整行为测试。:122 仍有 return 后不可达旧占位，需删除。快照与诊断位于 `local-learning/evidence/mem02-commit-review-5b179ad0/`，源码 SHA-256 为 `54b7de6049c2bc1ed0175eb26c2853e274aaa8a388d01a1200a3c779c40ccdf7`。助手未代改核心，待用户修正保存后验收完整 replace；retract 未实现。

## 固定 Pi 对照与新增要求

固定 Pi `packages/coding-agent/src/core/session-manager.ts:1204–1213` 的 appendMessage 追加带来源定位的会话条目；`:543–572` 的 buildSessionProjection 从记录构建模型输入，`:1260–1286` 追加压缩记录而不把原始历史改成投影。本模块保持来源与模型上下文分工。

`packages/agent/src/agent-loop.ts:388–397` 在请求前执行 transformContext/convertToLlm，是后续投影集成的对照位置。固定 Pi 这些函数并不提供本模块的长期事实范围、幂等、版本或撤回协议；它们是 Mini-Pi 新增工程要求，分别写反例。

本工作区 D12 基线的 Message 尚无 D13-A 的 stop_reason/error_message 协议。MEM-04 必须处理请求准备失败的 error/run_end 一致性，不能返回一条普通错误文字导致旧循环判 finished，也不能未处理地宣称集成验收通过。将为预期准备错误设计小范围门禁，保留内部异常与取消的语义；该门禁未通过时 MEM-04 保持进行中。

## 当前记录

2026-10-19：用户明确将目标从面试表述转为剩余时间完成记忆模块。已创建并附加隔离 worktree，建立 `codex/agent-memory`；原目录的暂停代码保留。助手已准备数据容器、格式辅助和核心占位，数据库与反例并行准备；来源准入和 remember 尚待学习者手敲。

辅助准备与组合审计已实际执行：21 项 SQLite/编解码测试、13 项真实 Session 来源测试通过；19 个业务测试方法因两个核心占位产生预期错误，合计执行 53 个方法，34 个通过，19 个方法未通过，子场景错误报告 93 条，0 跳过。错误全部是 policy/store 的 MEM-01 NotImplementedError；没有导入、语法或辅助层意外错误。整个组合测试退出码为 1，当前状态是脚手架未完成，不称模块验收通过。

证据位于 `local-learning/evidence/mem01-scaffold-33b44ca8/`，含 test-results.txt、verification.json、source-hashes.json；测试前后新模块与测试文件哈希一致，未调用真实模型。原目录 mini_pi/tests/examples 共 99 个暂停文件仍与冻结清单哈希一致。

首段手敲位置：`mini_pi/memory/policy.py:8` 的 validate_draft。导入、数据容器和格式检查已由助手提供；学习者完成范围相等、来源准入、工具仅情景和整条原文四项决策。输入为 Scope/Source/Draft，成功返回 None，拒绝抛 MemoryPolicyError；该函数本身不打开数据库。MEM-01 整体仍需后续 remember 接线与所有业务反例通过。

来源定位边界：read_memory_source 的 record_index 为解析后的非空记录序号，不是物理行号；同路径追加可保持 ID，搬迁/重排不能假设透明。工具来源保留完整 data JSON 的 error/工具名/调用 ID，而不是只取 output；旧 Session 没有身份认证字段，适配器不证明作者身份。只读缺文件不创建库；首次合法事务失败可留下空 SQLite 文件，不能把空文件当作记忆成功。

下一步：MEM-02 先用一个完整例子说明显式 expected_version、替换/撤回状态转移、时间区间及失败边界，再分段手敲。当前 MEM-01 的技术收口不等于整个记忆模块完成，不改变原 D13-B 暂停点或 12/30 主线计数；后续核心仍由学习者优先手敲，本次“帮我改好”不扩展为后续单元代写授权。

2026-10-19 第一段读盘核验：学习者已保存 `validate_shapes` 调用与 `source.scope != scope` 检查，末尾保留未完成占位。助手实际完成 AST 解析、现有格式与范围两个测试方法（含用户/项目分别不匹配的子场景），均通过；另验证同字段的不同 Scope 对象能越过范围检查并停在预期 NotImplementedError。测试前后 policy.py SHA-256 均为 `74c372c0e918775f630d109955760fe5361786fa0037b615f65c9eddd6e7e47a`，核心未代改。这里只确认本段代码行为，未确认学习者理解或整个策略/MEM-01 验收通过。

2026-10-19 第二段读盘核验：学习者已保存 user/tool 来源准入和 tool 仅 episodic 两项判断，末尾仍保留未完成占位。助手实际完成 AST 解析、现有范围与非法角色两个测试方法，均通过；另验证 5 种角色乘 3 种记忆类型共 15 个组合：11 个正确拒绝，4 个越过来源检查后停在预期占位，尚未返回策略成功。测试前后 policy.py SHA-256 均为 `a1e351b067a1a9583523956004be09390ce7155796619b39bc4a4b645cb980c7`，核验后重新读盘一致。完整原文门禁仍待学习者手敲；助手未修改核心实现。

2026-10-19 第三段读盘核验：学习者已正确添加 start=0、end=len(source.text) 的完整原文门禁，但保留了原来的 NotImplementedError。助手实际运行整组 MemoryPolicyTests：9 个测试方法，7 个通过，2 个方法共 4 条错误报告，全部指向 policy.py:25 的遗留占位；拒绝截断原文的测试通过，合法 user/tool 候选仍无法返回 None。AST 解析通过，测试前后 policy.py SHA-256 均为 `1d2c0f4868a1e5b1e2bc3a9b273691d6c91a0620af920023ad1d374e5b17fcf3`。助手仅指出应删除的占位，未代改核心代码，函数尚未验收通过。

2026-10-19 准入函数收口：读盘确认学习者已删除末尾占位。助手实际运行整组 MemoryPolicyTests，9 个方法全部通过，0 错误、0 失败、0 跳过；AST 解析通过。测试前后 policy.py SHA-256 均为 `29869917fea47cf384eea415762450592a42c84e181573c652dd644502aa6f16`。这些证据确认准入函数的所选行为，不证明学习者已理解、记忆已入库或整个 MEM-01 完成。助手为下一段只准备 codec 辅助导入，remember 核心仍为原占位。

2026-10-19 remember 准备段读盘核验：学习者已依次接入 validate_draft、normalize_source、normalize_draft、candidate_id，保留未完成占位。助手实际运行 AST 解析及现有 test_rejected_inputs_create_no_database_or_parent_directory，20 个拒绝输入子场景通过；另以真实临时路径验证合法候选到预期占位，数据库及父目录均未创建。测试前后 store.py SHA-256 均为 `577fc1a3797a52e372265ccc3676317dceb9e3983590c600ac002e50feb815fd`。仅确认当前门禁顺序与准备段，尚无来源核验、重放返回或实际记忆写入证据；助手未修改核心实现。

2026-10-19 remember 来源段读盘核验：学习者新增事务及来源核对，但 store.py:29 的 if 为 14 个空格，AST 实际报 IndentationError: unexpected indent，尚未运行行为测试；其下冲突 raise 为 18 个空格，末尾占位为 8 个空格且落在 with 外。应分别修正为 12/16/12 个空格，保证未完成占位在事务内触发回滚。核验前后 store.py SHA-256 均为 `0b517afbf1a09a223dd22dff44bbf6980dd031bc1bc71a042ec36c58c4bee87b`。助手未代改核心代码，先由学习者修正保存后再核验，不推进候选去重。

2026-10-19 当前来源段授权修复与验收：用户明确要求“帮我调好并验收”。助手仅修改 store.py 当前来源核验块：修正 if/冲突 raise 的缩进、整理当前调用换行、将未完成占位移入 with 并更新提示；块外的学习者代码逐字节保留。修前/修后快照和 change.json 保存在 `local-learning/evidence/mem01-source-guard-fix-a0f8d3ed/`。修后 store.py SHA-256 为 `356a205103d6eef8a7d55f9db890b1ba8f955697c5c9b3b164b3537acbb8499b`，语法解析通过。

本段实际验证：10 个现有准入/拒绝不建库回归测试方法全部通过；另以真实临时 SQLite 执行 6 个来源核验阶段测试方法、12 个场景，0 失败、0 错误、0 跳过。覆盖首次来源、完整相同来源、等价时区、原文/角色/记录时间改写冲突、用户与项目隔离、首次 schema 回滚、原来源/Entry/数据库字节不变、实际连接关闭及独立连接立即获取写锁。正常路径预期到达 NotImplementedError 仅表示后半段未完成，不是写入成功。脚本与实际输出为同目录 verify_source_guard.py/.json/.txt，回归输出为 regression-results.txt 与 regression.json；运行前后源码哈希一致，助手未实现后续去重或写入，不将本段通过记为 MEM-01 整体验收通过或学习者理解确认。

2026-10-19 保存漂移复核：用户确认后，下一轮重新读盘发现 store.py 再次与修前快照逐字节相同（SHA-256 `0b517afbf1a09a223dd22dff44bbf6980dd031bc1bc71a042ec36c58c4bee87b`），AST 再现第 29 行 IndentationError。原因未确认，旧编辑缓冲区再次保存仅为可能解释。助手依据此前同一来源段修复授权，保留漂移前快照后恢复已验收块，块外字节一致；重新执行 6 个来源阶段测试（12 场景）和 10 个回归方法，全部通过，源码回到 `356a205103d6eef8a7d55f9db890b1ba8f955697c5c9b3b164b3537acbb8499b`。新证据位于 `local-learning/evidence/mem01-source-guard-resave-490e734d/`；后续指导前先核对编辑内容与当前磁盘一致，候选重放核心仍待学习者手敲。

2026-10-19 候选重放段首次读盘：学习者已敲入 existing 查询、source/draft 比较与 return，但整个候选段缩进为 8 个空格，位于 with 外；来源 if/冲突 raise 又出现旧 14/18 空格缩进。AST 实际在 store.py:29 报 IndentationError，尚未运行本段行为测试；修正来源缩进后，事务外查询仍会使用已关闭的连接。当前 SHA-256 为 `f53ea2e62012bf82fd1dafd30a34ab313716a5d2a429c9f9441c5a46bc1cfef4`。用户确认使用 Codex 内置编辑器，覆盖原因尚未确认。助手保留当前新代码快照并提供包含来源核验与重放判断的完整事务块供统一修正，本轮未代改核心实现；此前 16 项通过仅对应旧修复哈希，不覆盖当前磁盘版本。

2026-10-19 当前重放段授权修复：用户再次明确要求“帮我调好并验收”。助手保留新敲的候选比较与 return，仅修正当前来源/重放事务块的缩进、查询换行与占位提示；块外代码逐字节不变，属性冲突检查和首次写入仍未实现。修前/修后源码与 change.json 位于 `local-learning/evidence/mem01-replay-fix-7c2f3555/`，修后 SHA-256 为 `0ab4599cafd06f8841e561fc226cf5f14c0b098c0ee30b504bf4e16aff0ef610`。

本段实际验收：11 个现有回归方法（9 个准入、拒绝不建库、预置撤回记录重放）全部通过；另执行 7 个真实 SQLite 阶段测试方法、17 个场景，0 失败、0 错误、0 跳过。覆盖 active/superseded/retracted 的非初始版本重放、Entry/version/state/written_at 保持与无新增行、时区/条件顺序等价、同编号 valid_from 冲突、来源内容/角色/记录时间冲突、范围隔离与缺失候选止点、正常 return/冲突/占位后的实际连接关闭及锁释放。另用真实 Connection 子类对 commit 做受控 OperationalError 注入，确认错误传播且没有成功返回，关闭连接、释放锁并保持数据不变；该项不称真实磁盘故障验收。脚本与输出为同目录 verify_replay.py/.json/.txt、regression.json、regression-results.txt，运行前后源码哈希一致。本段通过不等于完整 remember 或 MEM-01 通过，也不代填学习者理解状态；编辑器未保存缓冲区与磁盘同步仍需在继续编辑前核对。

2026-10-19 最后写入段首次读盘与完整测试：学习者已接 latest_entry 检查、make_entry、来源与 Entry 插入和 return，缩进与设计顺序正确。store.py:42 的 MemoryConfilct 应为 MemoryConflict；:45 的 self._backend.insert.source 应为 self._backend.insert_source；:48 是 return 后不可达的旧占位。实际执行 tests.test_memory_backend、tests.test_memory_source、tests.test_memory_write 共 53 个方法，8 个错误报告均为 AttributeError（backend 没有 insert 属性），0 断言失败、0 跳过。另用公开 backend 预置真实 SQLite 记忆，提交另一来源但相同属性/条件，实际复现 NameError: MemoryConfilct，原数据库字节不变。语法解析通过，测试前后 store.py SHA-256 均为 `58652b8ebb75885f6cce32bb09db28de6a2650bd0df31808794daa8849f4cb3f`；学习者核对期间新增注释，故证据锁定实际运行版本而非最初读盘哈希。快照、完整输出和 verification.json 位于 `local-learning/evidence/mem01-final-write-review-f2976556/`。助手未代改当前核心实现，待学习者修正保存后再验收。

2026-10-19 最终修复与 MEM-01 技术收口：用户明确要求“帮我改好”。助手只修正最后写入段两处名称、将提示中的“显示”改为“显式”，并删除不可达的旧占位，保留学习者流程、注释与其余字节。修前/修后快照和 change.json 位于 `local-learning/evidence/mem01-acceptance-5d4b3390/`；最终 store.py SHA-256 为 `6e095055de589ac8e44229fddd0ca540ab4527e08876d048c144130d4515d260`。

完整记忆测试实际执行 53 个方法（backend 21、source 13、write/policy 19），全部通过；覆盖真实原始 Session 只读、完整来源与角色/范围/时间门禁、规范化与重放、冲突无孤立来源、撤回重放保持、真实 SQLite 持久化及独立进程读回，所有记忆源码/测试哈希前后一致。另执行首次写入边界 3 个方法：成功返回后独立连接读取原 Source/Entry 且原连接关闭；真实插入后受控异常与受控 commit OperationalError 均观察到事务内 1 条来源和 1 条记忆后完整回滚，实际连接关闭、写锁释放且不成功返回。故障注入不代表真实磁盘故障或断电持久化验收。合计 56 个方法，0 失败、0 错误、0 跳过。

原目录 mini_pi/tests/examples 的 99 个冻结文件再次逐一核对，全部与暂停清单一致。验收脚本、标准输出、JSON、源码快照与保全结果均在上述证据目录。MEM-01 按所选来源入库/幂等/持久化契约技术验收通过；未由测试代填学习者理解，未宣称 MEM-02 更新/撤回 API、MEM-03 检索或 MEM-04 Context 集成完成；没有真实模型调用、提交或推送，D13-B 暂停点及 12/30 不变。

2026-10-19 replace 最终段授权调整与技术验收：用户要求“帮我调整”。助手仅修正 store.py 原 104–122 行提交段缩进、换行，并删除 return 后不可达的旧占位，保留学习者判断逻辑与块外字节。修前/修后快照及 change.json 位于 local-learning/evidence/mem02-replace-acceptance-6965a65b/。修后 SHA-256 为 2d85a3c2fbf539c214643df3dfba3dbcc2fa063f9ebaa8330a2aa3a517908b56，测试前后一致；记忆源码及测试 AST 解析通过。

实际执行全部 102 项记忆测试，0 失败、0 错误、0 跳过，其中 16 项 replace 测试覆盖版本/生效区间、回执重试、CAS、范围隔离、来源不可改写、撤回状态防复活、真实 SQLite 持久化及跨进程读回。真实插入来源、新版本及回执后受控异常，核对旧元数据与所有新行完整回滚、实际连接关闭和写锁释放；该注入不代表真实磁盘故障验收。完整日志、结果 JSON 与 verification.json 在同一证据目录。原目录 99 个冻结代码文件逐一哈希核对一致，D13-B 和 12/30 不变。replace 按所选契约技术验收通过；retract API、MEM-03/04 未实现，MEM-02 整体尚未完成；技术结果不代填学习者理解，没有提交、推送或真实模型调用。下一步先讲清整系列撤回的输入输出与事务联动，再分段手敲核心。


2026-10-19 retract 辅助准备：用户确认简化场景（撤回学习时间时停用 v1/v2，保留原来源供审计），不由此代填复杂边界理解。助手添加撤回输入格式校验、完整请求指纹与独立指令来源回执装配，准备 store.retract 签名/导入/明确占位及 10 个完整行为反例；未实现核心来源准入、回执重放、版本检查和整系列状态变更。已有 store 函数 AST 核对保持一致。

实际执行 102 项既有记忆测试及 5 项撤回辅助测试，共 107 项全通过；10 项 retract 行为测试产生 18 个错误报告（包含子场景），全部为明确占位 NotImplementedError，无断言失败、无 skip/xfail。源码/测试解析通过，测试前后哈希一致；快照、日志与 verification.json 位于 local-learning/evidence/mem02-retract-scaffold-20261019/。辅助通过不代表撤回功能通过。第一段学习者手敲仅为输入形状校验、同 Scope 且 user 来源的准入、来源与条件规范化和请求指纹，保留事务前占位；不创建数据库，不自动解析自然语言授权。可信调用方应负责将真实用户明确指令映射到目标系列，role 字段本身不等于身份认证。未提交或推送。

2026-10-19 retract 输入准备段读盘核验：学习者准入、规范化与指纹代码和缩进正确；store.py:141 残留不可达旧占位，需删除。AST 解析通过，实际执行 107 项既有/辅助回归、1 项撤回非法输入反例与 3 项准备阶段测试，共 111 项全通过，无失败、错误或跳过。合法输入到达预期事务前占位且新数据库/父目录未创建；指纹调用实参验证 UTC 来源时间及排序条件，原文不变；已有数据库在正常占位及非法来源拒绝后字节不变。测试前后 store.py SHA-256 均为 c299f3e66a74d0b488acebc7be9962db63a8b6510dd1104dd7ba005ec5c65ff5。源码快照、日志与 verification.json 位于 local-learning/evidence/mem02-retract-prepare-review-20261019/。助手未代改核心；本段通过不代表撤回事务或完整 retract 通过。下一段先在事务内核对持久回执，同请求返回已撤回结果，不同请求冲突；无回执保持未完成占位。

2026-10-19 retract 回执段核验：学习者代码与提供设计一致，缩进及不可达旧占位已清理。实际执行 108 项既有/辅助/非法输入回归及 7 项真实 SQLite 回执阶段测试，共 115 项，0 失败、0 错误、0 跳过；回执由公开 backend 预置，不将其声称为首次 retract 成功。覆盖相同请求重试返回当前 retracted 条目、等价时区、请求/动作变化冲突、回执 expected_version/控制来源不一致、非撤回结果拒绝、无回执到达指定占位及首次 schema 回滚；各路径实际连接关闭、独立连接立即获得写锁。所有记忆源码/测试哈希前后一致，store.py SHA-256 为 a6f14f109699a14891fa9343dcfdea0ab73e068590a8386a8a344700bc092f33。源码快照、可复跑脚本、完整输出与 verification.json 位于 local-learning/evidence/mem02-retract-receipt-review-20261019/。助手未代改核心；首次撤回、完整 MEM-02 仍未验收，技术结果不代填理解。下一段核对系列最新版本、active 状态与指令来源不可改写，仍保留事务内占位。

2026-10-19 retract 首次撤回门禁段核验：学习者最新版本、active 状态与来源不可改写门禁正确，AST 解析通过。实际执行 108 项既有/辅助/非法输入回归、6 项原回执反例及 6 项门禁阶段测试，共 120 项全部通过，无失败、错误或跳过。旧阶段无系列到占位的断言由本阶段无系列冲突取代，未改动完整功能测试或使用 skip/xfail。合法新/已存相同指令来源均到达提交前占位，数据库字节不变且未写入来源/回执/状态；旧版本（包括未来链尾）、缺失系列/条件、其他范围、已撤回链尾及改写来源均拒绝。实际连接关闭、独立写锁释放及新库 schema 回滚已核对。所有记忆源码/测试哈希前后一致，store.py SHA-256 为 8654c442e65c9c3814f1492fbb75df073999ccd9362c48c03b153cd39ef0cae6。快照、可复跑脚本、完整输出与 verification.json 位于 local-learning/evidence/mem02-retract-gates-review-20261019/。助手未代改核心；状态提交及完整 retract 尚待实现，技术结果不代填理解。下一段由学习者手敲整系列状态更新、指令来源/操作回执同事务提交，保留历史区间与事实版本。

2026-10-19 retract 最终提交段与 MEM-02 技术验收：学习者已手敲整系列读取、retracted 副本、独立控制来源回执、Source 按需写入、逐版本更新、回执插入与 return，顺序及缩进正确；原占位只留作注释，不执行。助手未代改核心。本次全部 117 项记忆测试（原有 102、撤回辅助 5、完整撤回 10）实际通过，0 失败、0 错误、0 跳过；覆盖整系列及未来版本撤回、原文/区间/事实版本保留、作用域/条件隔离、回执幂等/冲突、版本门禁、来源不可改写、remember/replace 与旧回执不能复活、跨进程读回。真实写入所有状态和撤回回执后受控异常，确认所有条目、控制来源、回执完整回滚，实际连接关闭及写锁释放；此注入不代表真实磁盘故障验收。

源码和测试 AST 解析通过，测试前后哈希一致，store.py SHA-256 为 204f42426fb8b4a9207f8d140d8b1e3a752e749c2f2797bf0090dfd8576efc2b。快照、完整输出和 verification.json 位于 local-learning/evidence/mem02-retract-acceptance-20261019/。原目录 99 个冻结代码文件逐一哈希一致，D13-B 暂停点与 12/30 不变。MEM-02 的显式版本更新、整系列撤回与持久回执按所选契约技术验收通过，技术结果不代填学习者理解；MEM-03 有效检索、MEM-04 Context 集成尚未实现。没有真实模型调用、提交或推送。下一步先回顾 remember/replace/retract 的完整关系，再讲 MEM-03 检索的整体流程与文件联动。
