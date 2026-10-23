# 本次同步提交范围

日期：2026-10-23。分支：`codex/agent-memory`。本页是已验证快照的具体范围；提交与远端状态以Git结果为准。

拟中文提交说明：**归档MEM-03与MEM-W写入规划并补齐跨设备接续**。

共 **54 个文件**。包括已验收能力和明确的未完成边界；不把MEM-W全链路标为完成。

排除 `.env`、真实Session/业务数据库、Git忽略的原始执行证据、独立Pi/MemoryBear源码缓存，以及原目录D13-A/B未提交代码。公开合成证书是既有测试资产，新增旧格式SQL/JSON也是合成夹具。

## 协作规则与配置模板（3）

- [.env.example](../.env.example)
- [AGENTS.md](../AGENTS.md)
- [requirements.txt](../requirements.txt)

## 学习记录与跨电脑入口（10）

- [README.md](../README.md)
- [local-learning/agent-memory-implementation.md](agent-memory-implementation.md)
- [local-learning/mem03-acceptance.md](mem03-acceptance.md)
- [local-learning/mem03-semantic-evaluation-plan.md](mem03-semantic-evaluation-plan.md)
- [local-learning/memory-resume.md](memory-resume.md)
- [local-learning/memory-sync-checks.md](memory-sync-checks.md)
- [local-learning/memory-sync-manifest.md](memory-sync-manifest.md)
- [local-learning/memw-learning-plan.md](memw-learning-plan.md)
- [local-learning/memw-memorybear-write-review.md](memw-memorybear-write-review.md)
- [local-learning/pi-learning-roadmap.md](pi-learning-roadmap.md)

## 受控示例与固定评测数据（3）

- [examples/fixtures/memory_embedding_eval_v1.json](../examples/fixtures/memory_embedding_eval_v1.json)
- [examples/memory_embedding_eval.py](../examples/memory_embedding_eval.py)
- [examples/memory_embedding_smoke.py](../examples/memory_embedding_smoke.py)

## 记忆源码（13）

- [mini_pi/memory/codec.py](../mini_pi/memory/codec.py)
- [mini_pi/memory/dashscope_embedding.py](../mini_pi/memory/dashscope_embedding.py)
- [mini_pi/memory/embedding.py](../mini_pi/memory/embedding.py)
- [mini_pi/memory/errors.py](../mini_pi/memory/errors.py)
- [mini_pi/memory/models.py](../mini_pi/memory/models.py)
- [mini_pi/memory/operation_codec.py](../mini_pi/memory/operation_codec.py)
- [mini_pi/memory/planning.py](../mini_pi/memory/planning.py)
- [mini_pi/memory/retrieval.py](../mini_pi/memory/retrieval.py)
- [mini_pi/memory/retrieval_helpers.py](../mini_pi/memory/retrieval_helpers.py)
- [mini_pi/memory/selection.py](../mini_pi/memory/selection.py)
- [mini_pi/memory/sqlite_backend.py](../mini_pi/memory/sqlite_backend.py)
- [mini_pi/memory/store.py](../mini_pi/memory/store.py)
- [mini_pi/memory/validation_helpers.py](../mini_pi/memory/validation_helpers.py)

## 学习图与生成提示词（4）

- [pic/mini-pi-memory-read-20261022.png](../pic/mini-pi-memory-read-20261022.png)
- [pic/mini-pi-memory-read-20261022.prompt.txt](../pic/mini-pi-memory-read-20261022.prompt.txt)
- [pic/pi-session-context-20261022.png](../pic/pi-session-context-20261022.png)
- [pic/pi-session-context-20261022.prompt.txt](../pic/pi-session-context-20261022.prompt.txt)

## 离线测试与合成兼容夹具（21）

- [tests/fixtures/memory_legacy_content_v1.json](../tests/fixtures/memory_legacy_content_v1.json)
- [tests/fixtures/memory_legacy_content_v1.sql](../tests/fixtures/memory_legacy_content_v1.sql)
- [tests/test_memory_candidate_source.py](../tests/test_memory_candidate_source.py)
- [tests/test_memory_content.py](../tests/test_memory_content.py)
- [tests/test_memory_dashscope_adapter.py](../tests/test_memory_dashscope_adapter.py)
- [tests/test_memory_dashscope_helpers.py](../tests/test_memory_dashscope_helpers.py)
- [tests/test_memory_dashscope_http.py](../tests/test_memory_dashscope_http.py)
- [tests/test_memory_embedding_batch.py](../tests/test_memory_embedding_batch.py)
- [tests/test_memory_embedding_eval.py](../tests/test_memory_embedding_eval.py)
- [tests/test_memory_embedding_smoke.py](../tests/test_memory_embedding_smoke.py)
- [tests/test_memory_planning.py](../tests/test_memory_planning.py)
- [tests/test_memory_remember_entrypoint.py](../tests/test_memory_remember_entrypoint.py)
- [tests/test_memory_replace_planning.py](../tests/test_memory_replace_planning.py)
- [tests/test_memory_retract_planning.py](../tests/test_memory_retract_planning.py)
- [tests/test_memory_retrieval.py](../tests/test_memory_retrieval.py)
- [tests/test_memory_retry.py](../tests/test_memory_retry.py)
- [tests/test_memory_routing.py](../tests/test_memory_routing.py)
- [tests/test_memory_search.py](../tests/test_memory_search.py)
- [tests/test_memory_selection_shapes.py](../tests/test_memory_selection_shapes.py)
- [tests/test_memory_vector_inputs.py](../tests/test_memory_vector_inputs.py)
- [tests/test_memory_vectors.py](../tests/test_memory_vectors.py)
