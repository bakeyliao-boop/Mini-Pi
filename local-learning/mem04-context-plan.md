# MEM-04：让适用记忆进入本次模型请求

> 2026-10-27整体验收：选定首版技术范围通过，正式复验74项全过，含保存Session到写入/两轮请求的真实临时文件闭环及本地HTTPS的供应商JSON/取消关闭证据，见[验收报告](mem04-acceptance.md)。固定响应不证明真实云模型语义；下列为分段历史，不再作为“待手敲”接续指令。

2026-10-26当前：独立build_context的11项、prepare_context的5项及每轮请求接线8项已分别实际通过；本轮另执行38项相关循环/截止时间/收尾/恢复回归全部通过。核心由学习者手敲，所列错误按明确授权修复。固定embedding、临时SQLite与模拟provider捕获已验证真实消息接线，未新增真实模型调用；整章收口仍需按范围核对，下方各阶段状态保留历史。

## 上游实际行为与学习基准

本章重新查询官方GitHub main：`d5b3de22d0e24a3e9c38a9410d3329b099717283`（提交2026-10-25T08:05:39Z）。固定阅读基准仍为`7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`，未切换。

- [agent-loop.ts:390–412 streamAssistantResponse](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/agent/src/agent-loop.ts#L390)：已有Agent消息→await transformContext(messages,signal)→await convertToLlm→normalizeContext→provider；本次转换后的数组没有赋回原history。
- [types.ts:196–244](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/agent/src/types.ts#L196)：transform可裁剪窗口、注入外部材料；convert转模型消息。约定失败时安全回退而非抛错。并非内置的结构化长期记忆检索。
- [agent.ts:469/517–587](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/agent/src/agent.ts#L469)：请求快照只复制顶层数组；生命周期等待执行器、处理错误/取消再解除idle。返回新数组不代表共享消息对象自动免疫原地修改。
- [compaction.ts:351–405](https://github.com/earendil-works/pi/blob/d5b3de22d0e24a3e9c38a9410d3329b099717283/packages/coding-agent/src/core/compaction/compaction.ts#L351)：不在toolResult处切开调用/结果，不等于整个长回合永远不可切。不能直接用任意messages[-N:]。

固定基准与main的types和coding-agent/messages相同；agent-loop/agent增加identity传递，本章transform→convert→provider及history、工具配对相关行为不变。Pi取消为协作式：signal传transform与provider，convert/getApiKey不收signal，provider前没有统一的取消后短路；不能据此宣称硬截止或准备取消后零provider调用。仅静态审阅，未运行上游。

## 本章完整流程

```text
当前任务、时间和条件（可信调用方明确）
    + 当前任务已确认材料（要求 / 执行观察 / 待核对事项，保留差别）
    + 原始history中的完整近期交互
    + MEM-03 search返回的相关记忆
    → 发请求前再查主记录及适用性
    → 按预算生成仅本次请求使用的messages
    → provider.generate(request_messages, tools)
```

Context是输入给模型的一份材料。MEM-W决定候选如何保存；MEM-03负责找相关且适用的记录；MEM-04负责哪些证据实际进入此次请求以及怎样呈现。组装过程不把注入材料追加到原Session/history，也不自动执行提取、写入或历史工具。

同用户同项目不证明同任务。首版由可信调用方明确选定当前任务材料；不自动把历史所有task_constraint拿来用，不新增自动任务判定模块。材料中的“测试失败”是观察；“保留断言”才是要求；缺参数时保留用户意图和具体缺口，不能编造参数或丢弃要求。检索/工具文本作为带来源材料，不提升为system规则或直接授权操作。

## 同一个具体例子

当前任务：继续修复mini-pi-demo的v2折扣问题。任务已确认要求“保留原测试断言”；工具日志为v2三项测试一项失败；用户说“继续定位失败原因”。长期库里还有“11月1日起尽量用Python举例”。

若问题时间为10月26日，这条未来偏好不进入Context；若时间为11月2日且其余条件适用，则可作为带来源/版本/生效时间的偏好材料进入。两种情况下都保留当前要求及配对完整的近期测试记录，不能把失败说成通过。旧任务的同项目测试观察不自动进入。输出是本次request_messages；数据库及history不是输出。

## 分工、单元顺序与验收

1. **先理解一次请求组装**：展示上述输入与实际期望输出；确定当前任务材料、近期工具组和检索证据如何共同保留。本轮只讲整体，不提前代写核心。
2. **独立组装行为**：学习者分段手敲材料复核及输出决策；助手准备容器、序列化、预算计数与反例。首单元保留传入的完整近期消息顺序，暂不增加裁剪算法；预算单位/算法必须先明确，不能把字符数说成真实token。超预算时明确失败，不静默删除当前约束、当前问题或拆工具配对；摘要不在本步自动生成。注入前核对主记录及适用时间，不一律要求最高版本，历史问题可使用当时有效旧版本。
3. **每次请求接线**：每轮模型调用前await检索/组装，进入现有deadline/取消范围，再向provider发送。助手准备采集provider输入的离线适配及受控本地副作用/取消反例，不新增付费调用。

最终验收须看provider实际收到什么，不能只看builder返回列表或模型答案：正确时间/条件和来源版本；读取期间撤回/变更的复核；原history和Session未受注入污染；固定约束不随近期窗口丢失；tool call/result配对；预算不足/检索错误不当作无记忆继续；准备期间取消等待清理，取消后不再发送。版本核对到真正发送之间不是数据库与模型请求的原子事务，须明确所能保证的时点。

现有D12 run_loop对普通异常缺少统一error/run_end，是请求集成前必须处理的关联缺口。本章接线要让新增准备错误完成一致结算，不能用旧测试掩盖或推到最终遗留；仅处理本章所需边界，不复制原目录冻结D13实现或顺手扩大其模型终态协议。Pi的安全回退约定、Mini-Pi选择的准备失败即停止以及发送前取消复核分别记录。

## 第一段准备（2026-10-26）

用户回复“ok，明白”，可继续分段；仅确认已讲整体关系，不代填实现或各边界已理解。

准备`mini_pi/memory/context.py:15 build_context`，参数直接复用MemoryScope/MemoryHit/MemoryCandidate和现有会话消息，不新增TaskMaterial业务类。可信调用方确认同任务后，只将task_constraint、needs_review候选传入task_material；两种路由仍保留原含义。辅助`context_helpers.py`负责格式、完整工具组检查、近期消息深复制和JSON序列化；导入及格式预处理已准备，核心仍为NotImplementedError。

同一完整组装行为分两段：先由学习者敲任务材料准入、命中重读及状态复核；再敲资料消息插入和字符预算、返回。第一段按来源范围拒绝错误任务材料，只接受task/review路由；记忆按ID重读，不存在/不可变定义不符明确失败，状态和valid_to变化则用is_usable重新判断，保留历史时间有效的superseded版本，不改为读取latest。

最终消息顺序为原system前缀→一条user角色JSON资料→其余完整近期消息；不把资料插入工具调用/结果之间。资料保留候选正文/路由/理由、记忆版本/区间/条件及来源ID/角色/记录时间，完整原文仍可按Source定位。本单元只处理一个明确问题时间，跨时间比较不能由单一at自动完成。

预算明确为`len(json.dumps([asdict(item) for item in messages], ensure_ascii=False, separators=(",", ":")))`对应Python字符数。只覆盖这份messages JSON，不包含tools和供应商封装，不保证真实token窗口；超限明确失败，整份消息不裁剪，空材料不额外插入资料消息。助手进行深复制和工具配对检查是该行为的组成部分，已在手敲前说明，必须随整体反例验收。

已准备`tests/test_memory_context.py`共11项。3个新文件AST语法通过，实际发现11项、0导入错误；0项行为执行，不能记为通过。覆盖正常来源保留、history/Session不变、深复制、未来/条件/历史版本、撤回旧命中、定义变化和读取失败、范围/路由、工具组及字符预算；模型请求接线仍另阶段验证。

目前状态：骨架、辅助和反例已准备，待学习者敲第一段；未新增真实调用、写入业务库或改run_loop，D13原现场及12/30不变。

## 第一段首次核对（2026-10-26）

用户表示已敲入。读盘context.py:36–62，任务材料准入、按命中ID重读、不可变定义比较及对current重新is_usable的顺序正确；第37行validate_candiate_source漏字母，第57行rasie拼错。实际AST检查于第57行报SyntaxError，0项行为执行，未代改核心。先引导修正这两处；末尾消息组装NotImplementedError暂保留，不提前推进后半段或记整函数通过。

用户随后明确要求“帮我调整好”。助手仅修上述两处拼写，AST语法通过；实际运行既有11专项中可独立验收的5项拒绝/异常传播测试，全部通过、0失败/错误/跳过（缺失/定义变化、读取异常原样传播、跨用户/项目、任务路由和来源角色、格式外壳）。其余正常组装、状态过滤输出及预算等6项须待后半段完成再执行，不将5项通过记作整函数通过。消息组装占位保留，核心其余内容未改，无真实模型调用或业务库写入。

## 消息组装段准备（2026-10-26）

用户要求下一步。已重新读取context.py，当前第62行为消息组装占位。沿用本章已核对的Pi请求前transform→convert链，Mini-Pi独立资料注入扩展不变，本轮不另开章节或切换固定基准。

手敲说明围绕同一输入输出：前半段得出的usable及已确认任务材料→已有system前缀后的一条user资料消息→完整近期交互；用户最新问题、工具调用/结果顺序保持。recent_messages在预处理时已深复制，新局部名request_messages指向该请求副本，插入资料不会反写原history。无资料时不插空消息，但仍检查总messages字符上限；超过上限明确抛错，不静默裁剪，等于上限允许返回。

助手提供这一小段完整可照敲代码；未写入核心、未重跑已通过的5项或提前执行剩余测试。待用户敲入后核对并运行完整11项；provider实际输入、每轮接线及取消/失败结算仍在后续阶段。

用户表示消息组装段已敲入后，读盘发现第73行将应有的request_messages.insert(insert_at, material)误写为request_messages_char_count(request_messages) > max_context_chars:。实际AST在73行报SyntaxError，完整11项未运行。资料插入步骤缺失；先引导替换此行，保留75–77行原预算及返回逻辑，未代改核心。

用户随后授权“帮我调整好”，助手仅将第73行恢复为request_messages.insert(insert_at, material)，其余核心保持原样。实际执行python -B -X utf8 -m unittest tests.test_memory_context -v，11项全部通过，0失败/错误/跳过（0.140秒）。覆盖来源/范围/状态复核、未来与条件过滤、历史有效v1、撤回旧命中、完整工具组、原history/Session不变及嵌套参数深隔离、空资料与字符边界；独立组装单元技术验收通过。不将此结果当作模型已消费或整章通过；下一步为请求前检索及每轮接线，并完成错误/取消/总时限与provider输入验收。无真实模型调用、业务库变更、提交或推送。

## 请求准备接线（2026-10-26）

推进时第73行两次再次读到同一错误内容，恢复后11项测试通过仍发生回写，覆盖来源未确定。用户已明确回复关闭context.py旧标签；随后只恢复该行，11专项再次全部通过（0.167秒），未做例行hash或延时复查。

助手新增request_context.py的prepare_context签名/导入/占位及test_memory_request_context.py的5个离线反例。语法与测试发现通过，0导入错误、0新行为执行；核心待学习者敲入。输入为可信调用方明确的query、Scope、时间/条件/检索配置、本任务材料及近期消息；输出为search→build_context生成的独立请求消息。检索前快照材料/近期消息，开始及检索返回后响应取消；不自动由工具结果构造query，不调用回答模型、不写长期记忆。检索/组装错误原样上抛，循环的error/取消/总时限接线仍待下一段，不提前声称已验收。5反例覆盖实际固定embedding/SQLite检索接组装、空库、错误传播、在途取消等待清理、检索返回时取消阻断组装。

用户表示已敲入后，实际核对prepare_context:34–50调用顺序、参数和两处取消检查正确，核心未代改。执行python -B -X utf8 -m unittest tests.test_memory_request_context -v，5项全部通过、0失败/错误/跳过（0.229秒）。正常案例实际使用合成临时SQLite及固定embedding接入既有search/build_context；取消清理证据限测试替身，不据此新增云端停止保证。第51行保留旧NotImplementedError，位于return之后不可达，不影响本次通过，应由学习者删除。请求准备单元技术验收通过；run_loop及provider实际输入、统一准备错误/总时限结算尚未接线，无真实调用或提交推送。

## run_loop接线准备（2026-10-26）

用户要求进入run_loop。已读现有loop、await_before_deadline、finish_run及本章缓存Pi main精确SHA的transform→convert→provider位置；沿用本章已核对来源与固定学习基准，不另称最新核对。助手仅补Awaitable/Callable/deepcopy导入、PrepareMessages类型、可选prepare_messages参数及调用方参数格式检查，尚未代写调用/错误结算核心。

prepare_messages是接收当前history并返回请求消息的异步入口；演示由partial(prepare_context, store, scope, query, 其他明确参数)绑定配置。每轮准备和模型请求分别复用await_before_deadline，使用同一运行deadline，不重新计时。给准备入口深复制history；返回消息只给provider，真实响应/工具结果追加到原history。准备阶段异常记录error并经finish_run结算；用preparing_context标记异常发生阶段，保留原模型异常传播边界。取消/总时限继续由现有专门分支结算，发送前再次经过取消与deadline门禁；同步组装不承诺硬实时抢占，也不承诺复核与发送之间原子一致。

助手已准备test_loop_memory_context.py共8项：真实临时SQLite/固定embedding经过prepare_context进入两轮provider捕获、原Session无注入资料、准备错误及深复制、取消清理后run_end、准备超时、返回时取消、同步超时后零发送、非法入口无副作用及模型错误不误归因。语法/发现通过，0导入错误，0行为执行；核心待学习者在同一请求行为的两个位置敲入，待完成后验8专项与相关旧循环边界。整个MEM-04仍未收口，无真实模型调用或提交推送。

用户表示接线已敲入，读盘发现三处：loop.py79行prepare_message缺s；112行误用prepare_context而非阶段标记preparing_context；119行return缩进8格位于except之外，会导致正常路径提前结束而不追加模型响应。实际只执行两轮正常链路测试1项，在79行报NameError，1错误；因此暂未跑其余7项或旧回归，不记验收通过、未代改核心。先引导修正这三处再验收完整接线。

用户随后授权“帮我调整好”，助手只修上述三个位置，其余核心及旧注释保留。实际执行tests.test_loop_memory_context共8项全部通过（0.389秒）；随后运行tests.test_loop/test_loop_budget/test_loop_cancel/test_loop_timeout/test_loop_session/test_run_deadline/test_run_finish/test_resume_budget共38项全部通过（1.667秒），均0失败/错误/跳过。本轮共46项实际通过，不含此前11+5的重复计数。

接线单元技术验收通过：两轮请求均实际经过准备入口并由模拟provider捕获带来源的记忆；第二轮包含最新工具失败结果；原Session/history不保存注入资料；准备错误产生error/run_end且零模型/工具启动；取消等待准备清理后记录结束；准备超时、返回时取消及同步阻塞超时后均零provider启动。取消等待清理用协程替身，不能扩称本轮新验证了真实网络或云端停止。模型普通异常仍保持既有上抛边界，未顺带实现原冻结D13；未新增真实模型调用、业务库变更、提交或推送，D主线12/30不变。
