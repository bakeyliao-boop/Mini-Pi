# 记忆与主线整合说明

日期2026-10-27。本文件描述记忆分支与主线的整合方案及离线验证边界。

- 主线基准：codex/mini-pi-v0.1@d17fbe5，D14/M1完成、D15模块一进行中、14/30。
- 来源：codex/agent-memory@ce0f1826，MEM-01/02/03/MEM-W/MEM-04选定首版完成。旧文档中的D13冻结/12/30是当时历史，不回退当前主线。
- 共同祖先74b12cb；已提交HEAD有README、主线路线、loop三个冲突。原工作区另有4个未提交文件和7个同名未跟踪路径，需单独处理。

## 候选请求顺序

Harness.run/resume（共享Agent，恢复先过ready）→Agent.prompt占位→run_loop预算门禁→steering递送并写原history→prepare_messages(deepcopy(history))→取消/截止复核→ContextProvider的默认FullHistoryContext→实际Provider。

prepare_messages由可信调用方显式传入，可绑定prepare_context(store,scope,query,...,at,conditions,max_context_chars)。默认不启用记忆，CLI不隐式读取数据库或调用embedding。

近期工具组、来源角色、Scope、单一问题时间及条件按MEM-04规则复核。注入资料不写回原history/Session；真实模型回答仍照常保存，不能保证回答不引用资料。

## 必须保留的边界

- D13普通模型错误/aborted、截断逐ID未执行反馈、双队列时点、取消收尾和原始记录配对全部保留。
- 新准备阶段的普通错误转为error并写run_end；取消/总时限保持原分类。Provider或普通自定义builder内部错误仍按主线原规则向外抛，不套大范围except Exception。
- MEM-04校验兼容D13合法截断原文：允许受约束的arguments=None/raw_arguments文本表示，仍保持调用ID/结果配对，不把截断参数补造为字典或执行工具。
- 首版明确拒绝同时配置prepare_messages与自定义context_builder，避免第二次不透明变换破坏已核对材料与字符预算。记忆启用时默认FullHistoryContext只复制传递；未来D16/D17须先明确组合顺序和最终预算再放开。这是本次新增取舍，经用户确认采用。
- 字符预算只统计内部messages JSON，不含tools/供应商封装，不是token窗口保证。max_model_turns计回答请求，embedding消耗不伪装成已统一的token/费用上限。
- 长期记忆是Mini-Pi扩展，不称Pi原生能力；同会话压缩与长期记忆分开。当前不自动摘要、query改写、任务匹配、写入或重放。

## 已实际验证

原主线400项、原记忆分支585项均通过（各2项旧Windows符号链接权限跳过）。隔离候选790项中788通过、2跳过，无失败/错误；包括12项新增跨层反例。

新增反例核对Harness两入口、每轮材料/队列输入及原Session不变、准备错误/超时/取消收尾、模型普通异常、截断原文零执行、字符预算、预算先于下一次检索，以及主线Agent+ContextProvider下原embedding/Qwen的真实本地HTTPS JSON与关闭连接门闩。合成向量和固定回答不证明云语义质量。

机械采用主线loop的反例实际失败；恢复记忆旧校验时，合法截断继续场景实际失败。这两组负例保留，证明不能只看Git自动合并。

测试进程移除API Key并阻止非loopback网络访问，没有追加云API调用、真实SQLite迁移或生产数据写入。历史v1、S3、v2.1失败成绩和v2.2两例定向结果不改，不声称泛化通过。

## 学习与验证边界

整合接线由助手在隔离副本构造，不代表学习者已手敲或完成理解验收。原工作区未提交的学习内容单独保留。后续学习时仍需按AGENTS核对和理解loop、Agent透传、Harness配置与截断校验。离线验证不代替真实云模型语义验收。
