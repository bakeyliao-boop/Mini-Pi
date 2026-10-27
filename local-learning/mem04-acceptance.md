# MEM-04 首版技术验收

日期：2026-10-27。工作区`C:\Users\hyf\.codex\worktrees\mini-pi-memory\Pi`，分支`codex/agent-memory`。结论：**选定首版技术范围验收通过**。本轮正式复验74项全部通过，0失败/错误/跳过，云API调用0次；不等于真实云模型语义质量或整个Mini-Pi完成。

## 本章做成的完整行为

保存的Session→程序绑定完整Source→固定响应提取/五出口→调用方明确核对候选、字段和动作→只读计划→明确执行写入临时SQLite→每轮search→build_context复核主记录/状态及组装→provider接收独立消息→真实文件工具结果追加原Session→结束记录。

MEM-04核心由学习者分段手敲；助手仅按用户明确授权修正已指出的拼写/缩进，准备辅助层、固定响应、测试和验收记录。本轮新增的是辅助整链/本地传输反例，仅更新过时模块说明，不修改功能核心。用户已明确理解准备错误结果与外抛异常的职责边界；其他理解不由测试代填。

## 来源与对应关系

沿用本章2026-10-26已核对的Pi main `d5b3de22d0e24a3e9c38a9410d3329b099717283`，固定学习基准`7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`保持。本轮为章节验收，没有重新声称核对2026-10-27最新main。函数与差异见[章节方案](mem04-context-plan.md)：Pi请求前transform→convert→provider提供投影入口；长期事实检索、可信Scope、状态复核、字符预算、准备失败即停止及发送前门禁是Mini-Pi选定扩展。

## 验收矩阵

| 行为 | 直接证据 | 结论边界 |
| --- | --- | --- |
| 来源/范围/条件/问题时间、历史有效v1与撤回 | `test_memory_context.py`核对主记录和is_usable，跨范围与定义变化拒绝 | 不是语义真实性判定；按复核时点生效 |
| 原始记录与请求消息分开 | 深复制嵌套工具参数；新请求含资料，原history和保存Session不含注入块 | 真实模型回答仍作为原始事件保存，不能承诺模型不会引用资料 |
| 工具配对及材料状态保留 | 完整工具组、task_constraint/needs_review及Source角色/编号/时间 | task_constraint可包含观察，不自动提升为要求；同项目不等于同任务 |
| 明确写入后，每轮实际重新检索 | `test_memory_context_acceptance.py`从保存Session、固定提取、计划/执行和新Store起步，捕获两轮provider输入 | 固定响应、固定向量证明接线，不证明云模型语义 |
| 轮间replace/retract | 第一次真实read_file完成后更新或撤回；下一轮分别取v2或排除偏好 | 不使用缓存复活旧偏好；复核与发送不是原子事务 |
| 第二轮检索失败 | 第一次真实文件读取及ToolResult保留；仅一次回答模型/工具调用，单一error/run_end | 与第一次工具实际成败分别记录，不自动重放 |
| 实际字符超限 | 真正search→build_context路径报错，provider/工具均零启动 | 统计内部messages JSON字符数，不是token或供应商完整payload上限 |
| 准备错误/取消/超时收尾 | 回调清理门闩、取消后发送前检查、同步准备超时反例与run_end | 无硬实时抢占保证；普通provider异常保持原样上抛 |
| 真实本地HTTPS与API消息 | 原DashScopeEmbedder发送query/document→原QwenProvider发送chat；本地回答服务器收到的JSON含Source与最新问题。取消时连接关闭门闩放行前无run_end，关闭后cancelled且零回答/工具调用 | 固定服务器响应，不是云模型效果、云端停止或账单证据 |

## 当前选定范围

- 调用方明确给出可信Scope、同任务材料、query、单一问题时间和场景条件，不自动做任务匹配或query改写。跨时间对比不由一个at自动完成。
- 记忆准备入口需由调用方通过run_loop的prepare_messages显式注入；未配置时沿用原始history请求方式。没有自动更改所有CLI或启动脚本的默认行为。
- 任务材料独立于记忆相似度检索传入，每轮明确加入；近期消息保持完整顺序，不实现自动摘要、窗口裁剪或token预算。超限停止，不默默丢约束或拆工具组。
- 来源保存、提取建议、规划和执行分离。long_term标签不是写入许可；规范化正文与完整原Source分开，来源原文仍可定位。无模型语义评审或自动纠错新模块。
- Context准备普通错误转为error结果，并经finish_run保存run_end；模型普通异常仍上抛、不保证run_end，原冻结D13的模型终态/生命周期问题保持原边界。
- 数据复核只保证已完成的读取时点，不能保证到模型发送间没有并发变更；同步本地I/O及序列化不可硬实时抢占。
- 固定提取/向量/回答及本地HTTPS用于受控验证。真实云端端到端语义质量未验证；此前MEM-W失败成绩保留，v2.2仅两例定向通过，不推成泛化。
- 整链文件案例的问题时间明确模拟为2026-11-02，以验证11月1日起生效的偏好，不将其当作10月27日已适用。真实文件工具只读取合成代码；正常run.finished不表示折扣缺陷已修复或业务测试已通过，task_passed仍未作成功断言。

## 正式执行记录

正式执行：2026-10-27 09:59（Asia/Shanghai），Python 3.14，`-B -X utf8`，14个选定测试模块共74项全部通过，0失败/错误/跳过；测试批次耗时3.471秒，不含开发、评阅及此前运行时间，不是系统性能指标。

| 测试组 | 本次实际执行数 |
| --- | ---: |
| 独立Context组装 | 11 |
| 请求准备 | 5 |
| 每轮循环接线 | 8 |
| 保存Session的读取/提取接线 | 5 |
| 新增保存Session→写入→两轮请求/真实文件整链 | 5 |
| 新增真实本地HTTPS成功/取消闭环 | 2 |
| 既有循环/预算/取消/超时/Session/截止时间/收尾/恢复回归 | 38 |
| 合计 | 74 |

记录：`evidence/mem04-acceptance-20261027/unittest.log`与`verification.json`。模块清单、执行数、状态和测试批次耗时均在JSON中；证据目录受gitignore保护，不含真实凭据。新增两个辅助测试文件可复现整链及传输检查。没有把历史通过次数叠加为本次用例数；一条测试中的多个断言/变体也不另外计数。

新电脑不依赖原始evidence即可复现这74项。在仓库根目录使用Python 3.14执行下列命令（按环境替换python的解释器路径）：

```sh
python -B -X utf8 -m unittest tests.test_memory_context tests.test_memory_request_context tests.test_loop_memory_context tests.test_memory_context_acceptance tests.test_memory_context_transport tests.test_memory_session_extraction tests.test_loop tests.test_loop_budget tests.test_loop_cancel tests.test_loop_timeout tests.test_loop_session tests.test_run_deadline tests.test_run_finish tests.test_resume_budget -v
```

## 接续

本章首版技术范围已收口，后续从本报告及memory-resume.md接续，不重复已验核心。真实云端整链语义效果、token窗口/摘要、自动任务匹配等保持各自边界；需要新目标和验收计划，不自动增加模块或云调用。用户已明确理解prepare_context异常向上传播与run_loop按职责返回error结果的区别。

D主线仍12/30，原目录D13-B现场保持冻结。本轮无云API调用、真实凭据读取、业务库变更、hash扫描或提交推送。
