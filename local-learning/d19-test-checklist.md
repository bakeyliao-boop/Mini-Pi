# D19 行为测试清单与验收

2026-11-03 完成本章技术验收及代表场景的有指导复盘。统一入口为 [examples/d19_behavior_checks.py](../examples/d19_behavior_checks.py)，复用既有测试，不新增核心功能。

## 一次运行

从仓库根目录执行：

```sh
python -X utf8 -m examples.d19_behavior_checks
```

本机已实际使用 Python 3.14.5（Windows）运行。PowerShell 可使用本机解释器：

```powershell
& 'C:\Users\hyf\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 -m examples.d19_behavior_checks
```

入口依次完成既有回归和受控反例；只有常规测试通过、且反例成功发现预期错误时才返回退出码 0。每次创建新的本地输出目录，不覆盖之前的记录。完整用例 ID、失败/跳过原因和输出路径保存在 `result.json`；详细过程保存在 `output.txt`。这些运行输出位于 Git 忽略目录，不自动随仓库同步。

## 路线要求与测试依据

| 路线要求 | 对应测试 | 实际检查 |
| --- | --- | --- |
| 调用与结果配对 | [test_loop.py](../tests/test_loop.py)、[test_session_recovery.py](../tests/test_session_recovery.py) | 编号、工具名、结果顺序及内容正确；拒绝孤立、错配或重复结果 |
| 工具错误后继续 | [test_loop.py](../tests/test_loop.py:122) | 模型收到第一次失败，再提出新调用，随后收到新调用的正确结果 |
| 非法参数不实际操作 | [test_read_file.py](../tests/test_read_file.py:58)、[test_tool_hooks.py](../tests/test_tool_hooks.py) | 数字路径返回参数错误且不读取；规则拒绝时不进入实际执行 |
| 截断反馈与完整重试 | [test_loop_truncated_batch.py](../tests/test_loop_truncated_batch.py)、[test_truncated_call_conversion.py](../tests/test_truncated_call_conversion.py) | 截断调用零执行、保留原编号及错误反馈；完整新调用才执行 |
| 模型次数与运行时限 | [test_loop_budget.py](../tests/test_loop_budget.py)、[test_loop_timeout.py](../tests/test_loop_timeout.py) | 不多发请求；已完成结果保留；等待中的模型/工具正确退出并记录结束原因 |
| 取消与资源收尾 | [test_agent_resources.py](../tests/test_agent_resources.py)、[test_loop_cancel.py](../tests/test_loop_cancel.py)、[test_agent_idle.py](../tests/test_agent_idle.py)、[test_list_cancel.py](../tests/test_list_cancel.py) | 实际连接关闭、受管进程退出、编辑工作退出后才空闲；不丢失已完成结果；单独核对只读扫描的取消边界 |
| 恢复边界 | [test_session_resume.py](../tests/test_session_resume.py)、[test_session_resume_gate.py](../tests/test_session_resume_gate.py)、[test_harness_resume.py](../tests/test_harness_resume.py) | 旧历史可用、旧调用不重新执行、旧记录不重复写；缺少结果时阻止自动恢复 |
| 裁剪与压缩后上下文 | [test_memory_read_output_integration.py](../tests/test_memory_read_output_integration.py)、[test_harness_compaction_resume.py](../tests/test_harness_compaction_resume.py)、[test_auto_compaction_loop.py](../tests/test_auto_compaction_loop.py)、[test_compaction_continuation.py](../tests/test_compaction_continuation.py) | 模型使用裁剪副本或摘要；原始记录完整；摘要失败、超限及新增排队消息不错误放行 |

## 固定测试文件范围

| 组别 | 文件 | 本次项数 |
| --- | --- | --- |
| 工具反馈与执行前保护 | `test_loop.py`、`test_read_file.py`、`test_tool_hooks.py`、`test_loop_truncated_batch.py`、`test_truncated_call_conversion.py` | 35 |
| 运行控制与资源收尾 | `test_loop_budget.py`、`test_loop_timeout.py`、`test_loop_cancel.py`、`test_agent_abort.py`、`test_agent_idle.py`、`test_agent_resources.py`、`test_list_cancel.py` | 28 |
| 会话恢复 | `test_session_resume.py`、`test_session_recovery.py`、`test_session_resume_gate.py`、`test_harness_resume.py` | 21 |
| 请求副本与摘要 | `test_read_output_context.py`、`test_memory_read_output_integration.py`、`test_harness_compaction_resume.py`、`test_auto_compaction_loop.py`、`test_harness_auto_compaction.py`、`test_compaction_continuation.py` | 39 |

这是 D19 选定的 22 个文件，共 123 项，不是整个仓库的全量测试。入口保留明确清单；新增其他测试文件时须有意更新该清单。

## 实际结果

- 执行环境：Python 3.14.5，Windows；功能代码基线为 `50aa96984bd245a4abbdb0ebd1a23d4aecefa557`。
- 工作区另有学习者对四个既有测试文件的注释/格式修改，以及本章新辅助入口和文档；本轮没有修改核心实现。
- 常规回归：123 项通过，0 失败、0 错误、0 跳过。
- 使用模拟回答/摘要模型、固定模拟嵌入，以及实际临时文件、本地记忆、本地 HTTPS 和受控进程；未调用真实云模型。
- 本次 [机器结果](evidence/d19-checks/20261103T064323Z-7z1gyb0u/result.json) 与 [详细输出](evidence/d19-checks/20261103T064323Z-7z1gyb0u/output.txt) 保存在本地。

## 缺少保护时会怎样失败

统一入口在常规回归通过后，仅在当前 Python 进程里停用 `loop.py` 的截断保护，再运行原来的合法参数截断用例。磁盘上的核心源码保持不变。

| 实现 | 实际行为 | 测试结论 |
| --- | --- | --- |
| 正常实现 | 截断批次不执行，文件保持 `value = 1` | 常规用例通过 |
| 内存中停用截断保护 | 错误执行 `edit_001`、`read_001`，真实临时文件变成 `value = 2` | 原用例因执行清单不为空而失败 |

反例必须同时符合“原用例失败、执行编号与错误修改符合预期、核心源码未改动”。这项预期失败单独记录，不计入 123 项常规回归的失败数。它证明测试能发现这一类保护失效，不表示所有检查都已做过逐一停用验证。

## 完成口径与边界

学习者已就四组代表场景作出有指导说明，具体回答见 [D19 学习记录](d19-handoff.md)。这与全部测试的技术结果分别记录，不推断学习者已独立设计全部测试或逐行掌握所有辅助代码。

模型次数和总时限是 Mini-Pi 的工程配置；不据此声称 Pi 提供相同上限。取消写入等待本次工作结束，不承诺回滚已获准的写入；只读目录扫描在取消后可能仍在后台完成，不能把受管进程与写入的收尾保证扩大到所有读取线程。模拟摘要用来验证流程和记录，不能证明真实摘要质量。真实模型任务集与效果评测属于 D20、D21。
