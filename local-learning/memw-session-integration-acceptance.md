# MEM-W：保存会话到受控写入的接线验收

2026-10-26。`extract_session`四行核心已由学习者敲入，本轮读盘正确，未代改。助手扩充已有合成示例的可选临时库执行模式，不新增业务核心或真实模型调用。

## 实际执行

1. `python -B -X utf8 -m unittest tests.test_memory_session_extraction -v`：5项全部通过，0失败、错误、跳过。覆盖保存用户/完整工具记录、非法记录发送前拒绝、响应失败传播及取消收尾；不会重跑历史工具。
2. `examples.memory_session_v2_demo.run_demo()`：固定响应经现有请求/解析/分流/规划核心；用户五组数量为1/1/1/2/0（long_term/task_constraint/ignore/needs_review/withdrawal），工具结果为一条task_constraint。只读规划不创建SQLite目录或文件。
3. `run_demo(execute=True)`：同一临时Session和已核对候选，调用方明确提供action/key/kind/conditions/valid_from；实际执行RememberPlan，再原样重试；同候选重新规划返回MemoryEntry，再透传；新MemoryStore从SQLite读回。

三次计数均为sources=1、entries=1、operation_receipts=0；原计划重试、重新规划与磁盘读回均为同一Entry/v1。完整Source及Draft保留。首次新增不产生replace/retract操作回执。偏好明确从11月1日开始，10月26日is_usable=False，生效时刻=True；库中的active状态不能替代时间核对。原Session字节保持一致。

辅助示例首次执行漏传is_usable必填conditions，明确报TypeError；助手仅修正自己新增的两处调用，再执行两种模式均通过，未修改已学核心。

## 证据与复现

- `evidence/memw-session-integration-20261026/session-tests.txt`：5项专项执行日志。
- `evidence/memw-session-integration-20261026/demo-results.json`：只读及临时写入结果、来源、计数和时间核对。
- `python -B -X utf8 examples/memory_session_v2_demo.py`：默认只读。
- `python -B -X utf8 examples/memory_session_v2_demo.py --execute`：只操作本次新建的合成临时SQLite，结束清理。路径不同会得到不同来源身份，不能据此声称跨路径重试。

## 验收边界及下一步

通过的是选定首版demo的技术接线：保存Session→Source→提取和五组→可信调用方核对并明确补字段→只读计划→明确执行→重试→读回。固定响应不验证真实模型语义。task_constraint、needs_review、ignore在本例非空且未写入长期库；withdrawal为空，本例不提供撤回执行证据。既有撤回专项保持原口径。

不增加自动元字段/动作判断模块。task_constraint保留原任务要求、进度及观察，归组本身不证明当前任务归属，也不把观察变成命令；needs_review并非丢弃已知意图。真实v2.2两例定向通过不推成全面泛化，旧失败结果保留。下一章[MEM-04](mem04-context-plan.md)负责本次模型请求真正消费适用材料。未改原目录D13现场，D主线12/30；无额外真实调用、业务库变更、提交或推送。
