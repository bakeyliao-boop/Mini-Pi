# MEM-W / MEM-04 本次提交文件清单

2026-10-27。本清单精确列出用户已授权提交推送的**67个文件**（8个已跟踪文件修改、59个新增文件），包含本清单和准备检查记录自身。M/A表示相对下列基线的修改/新增；本页为归档范围记录，实际提交及推送结果以当前git log和远端分支核对为准。

基线：b0c0e9a32cb19da98725595e1162c394399529e0；拟提交并推送到origin/codex/agent-memory。

中文提交标题：**归档MEM-W提取与受控写入并完成MEM-04上下文接线**。

正文、实际检查结果、首轮旧用例异常与复验说明见[准备检查](memw-mem04-submit-checks.md)。

本次包含实现9、测试14、示例与合成样本12、README/学习/研究记录32。核心为学习者实现及已授权修复；本轮只做AST不变的空白整理。

## 实现：9个

| 状态 | 精确路径 |
| --- | --- |
| M | [mini_pi/loop.py](../mini_pi/loop.py) |
| A | [mini_pi/memory/context.py](../mini_pi/memory/context.py) |
| A | [mini_pi/memory/context_helpers.py](../mini_pi/memory/context_helpers.py) |
| A | [mini_pi/memory/execution.py](../mini_pi/memory/execution.py) |
| A | [mini_pi/memory/extraction.py](../mini_pi/memory/extraction.py) |
| A | [mini_pi/memory/extraction_client.py](../mini_pi/memory/extraction_client.py) |
| M | [mini_pi/memory/planning.py](../mini_pi/memory/planning.py) |
| A | [mini_pi/memory/request_context.py](../mini_pi/memory/request_context.py) |
| M | [mini_pi/memory/selection.py](../mini_pi/memory/selection.py) |

## 测试：14个

| 状态 | 精确路径 |
| --- | --- |
| A | [tests/test_loop_memory_context.py](../tests/test_loop_memory_context.py) |
| A | [tests/test_memory_candidate_draft.py](../tests/test_memory_candidate_draft.py) |
| A | [tests/test_memory_candidate_planning.py](../tests/test_memory_candidate_planning.py) |
| A | [tests/test_memory_context.py](../tests/test_memory_context.py) |
| A | [tests/test_memory_context_acceptance.py](../tests/test_memory_context_acceptance.py) |
| A | [tests/test_memory_context_transport.py](../tests/test_memory_context_transport.py) |
| A | [tests/test_memory_extraction.py](../tests/test_memory_extraction.py) |
| A | [tests/test_memory_extraction_client.py](../tests/test_memory_extraction_client.py) |
| A | [tests/test_memory_extraction_eval.py](../tests/test_memory_extraction_eval.py) |
| A | [tests/test_memory_extraction_response.py](../tests/test_memory_extraction_response.py) |
| A | [tests/test_memory_request_context.py](../tests/test_memory_request_context.py) |
| A | [tests/test_memory_retention_instruction.py](../tests/test_memory_retention_instruction.py) |
| A | [tests/test_memory_session_extraction.py](../tests/test_memory_session_extraction.py) |
| A | [tests/test_memory_write_execution.py](../tests/test_memory_write_execution.py) |

## 示例脚本：7个

| 状态 | 精确路径 |
| --- | --- |
| A | [examples/memory_extraction_eval.py](../examples/memory_extraction_eval.py) |
| A | [examples/memory_overlap_preview.py](../examples/memory_overlap_preview.py) |
| A | [examples/memory_overlap_run.py](../examples/memory_overlap_run.py) |
| A | [examples/memory_reference_run.py](../examples/memory_reference_run.py) |
| A | [examples/memory_s3_preview.py](../examples/memory_s3_preview.py) |
| A | [examples/memory_s3_run.py](../examples/memory_s3_run.py) |
| A | [examples/memory_session_v2_demo.py](../examples/memory_session_v2_demo.py) |

## 合成样本：5个

| 状态 | 精确路径 |
| --- | --- |
| A | [examples/fixtures/memory_extraction_eval_v1.json](../examples/fixtures/memory_extraction_eval_v1.json) |
| A | [examples/fixtures/memory_extraction_eval_v2.json](../examples/fixtures/memory_extraction_eval_v2.json) |
| A | [examples/fixtures/memory_overlap_acceptance_v21.json](../examples/fixtures/memory_overlap_acceptance_v21.json) |
| A | [examples/fixtures/memory_reference_acceptance_v22.json](../examples/fixtures/memory_reference_acceptance_v22.json) |
| A | [examples/fixtures/memory_s3_acceptance_v2.json](../examples/fixtures/memory_s3_acceptance_v2.json) |

## 学习记录：23个

| 状态 | 精确路径 |
| --- | --- |
| M | [local-learning/agent-memory-implementation.md](../local-learning/agent-memory-implementation.md) |
| A | [local-learning/mem04-acceptance.md](../local-learning/mem04-acceptance.md) |
| A | [local-learning/mem04-context-plan.md](../local-learning/mem04-context-plan.md) |
| M | [local-learning/memory-resume.md](../local-learning/memory-resume.md) |
| A | [local-learning/memw-extraction-evaluation-plan.md](../local-learning/memw-extraction-evaluation-plan.md) |
| A | [local-learning/memw-extraction-pilot-results.md](../local-learning/memw-extraction-pilot-results.md) |
| A | [local-learning/memw-extraction-plan.md](../local-learning/memw-extraction-plan.md) |
| A | [local-learning/memw-extraction-repair-proposal-v2.md](../local-learning/memw-extraction-repair-proposal-v2.md) |
| A | [local-learning/memw-extraction-v2-offline-review.md](../local-learning/memw-extraction-v2-offline-review.md) |
| M | [local-learning/memw-learning-plan.md](../local-learning/memw-learning-plan.md) |
| A | [local-learning/memw-mem04-submit-checks.md](../local-learning/memw-mem04-submit-checks.md) |
| A | [local-learning/memw-mem04-submit-manifest.md](../local-learning/memw-mem04-submit-manifest.md) |
| A | [local-learning/memw-overlap-v21-plan.md](../local-learning/memw-overlap-v21-plan.md) |
| A | [local-learning/memw-overlap-v21-results.md](../local-learning/memw-overlap-v21-results.md) |
| A | [local-learning/memw-pi-memorybear-selection-source-review.md](../local-learning/memw-pi-memorybear-selection-source-review.md) |
| A | [local-learning/memw-reference-v22-plan.md](../local-learning/memw-reference-v22-plan.md) |
| A | [local-learning/memw-reference-v22-results.md](../local-learning/memw-reference-v22-results.md) |
| A | [local-learning/memw-request-plan.md](../local-learning/memw-request-plan.md) |
| A | [local-learning/memw-retention-v2-learning.md](../local-learning/memw-retention-v2-learning.md) |
| A | [local-learning/memw-s3-acceptance-plan.md](../local-learning/memw-s3-acceptance-plan.md) |
| A | [local-learning/memw-s3-acceptance-results.md](../local-learning/memw-s3-acceptance-results.md) |
| A | [local-learning/memw-session-integration-acceptance.md](../local-learning/memw-session-integration-acceptance.md) |
| M | [local-learning/pi-learning-roadmap.md](../local-learning/pi-learning-roadmap.md) |

## 来源研究：8个

| 状态 | 精确路径 |
| --- | --- |
| A | [local-learning/research/memory-overlap-20261026/claude.md](../local-learning/research/memory-overlap-20261026/claude.md) |
| A | [local-learning/research/memory-overlap-20261026/codex.md](../local-learning/research/memory-overlap-20261026/codex.md) |
| A | [local-learning/research/memory-overlap-20261026/h4-adversary.md](../local-learning/research/memory-overlap-20261026/h4-adversary.md) |
| A | [local-learning/research/memory-overlap-20261026/h4-followup.md](../local-learning/research/memory-overlap-20261026/h4-followup.md) |
| A | [local-learning/research/memory-overlap-20261026/h4-route.md](../local-learning/research/memory-overlap-20261026/h4-route.md) |
| A | [local-learning/research/memory-overlap-20261026/h4-source.md](../local-learning/research/memory-overlap-20261026/h4-source.md) |
| A | [local-learning/research/memory-overlap-20261026/pi-bear.md](../local-learning/research/memory-overlap-20261026/pi-bear.md) |
| A | [local-learning/research/memory-overlap-20261026/report.md](../local-learning/research/memory-overlap-20261026/report.md) |

## 入口文档：1个

| 状态 | 精确路径 |
| --- | --- |
| M | [README.md](../README.md) |

## 排除范围

原目录D13-A/B现场、.env及真实凭据、个人配置、真实Session/SQLite、local-learning/evidence原始执行记录、外部源码缓存均不在清单中。已有公开合成测试证书由基线跟踪，本次不新增真实私钥。

所有历史云调用额度已用完；提交这些受控runner不构成下一轮调用授权。用户已确认上述67文件范围及中文说明，后续新增范围仍须单独确认。
