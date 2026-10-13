# D09 归档与提交审核

状态：学习记录已整理，D09 标为完成（9/30），下一步 D10 待开始。用户已授权按本页范围提交并推送；本页保留提交前审核说明，实际提交结果以 Git 记录为准。

目标开发分支：`codex/mini-pi-v0.1`。

## 中文提交说明

建议标题：**完成第九天四工具联调与失败反馈验收**

建议正文：

```text
新增工具名称路由、目录列表和固定命令测试工具，区分参数错误、启动失败、超时和测试未通过。测试输出有长度上限，并保存完整日志及其位置。

归档 D09 理解验收、四工具实际调用轨迹和学习心智图；更新进度为 9/30，下一步 D10。补充核心手敲范围规则，进程配置等外围代码由助手准备。

验证：D09 的 13 项针对性测试通过；独立演示目录的折扣用例修改前失败、修改后通过。本次调用顺序由示例预设，模型请求数为零，不代表模型自主修复验收。
```

## 拟提交范围（13 个文件）

| 类别 | 文件 |
| --- | --- |
| 协作与学习记录 | `AGENTS.md`、`README.md`、`local-learning/pi-learning-roadmap.md`、本审核文件 |
| D09 工具 | `mini_pi/tools/tool_router.py`、`list_files.py`、`run_tests.py` |
| 验证与演示 | `tests/test_tool_router.py`、`test_list_files.py`、`test_run_tests.py`、`examples/d09_tools.py` |
| 图片及生成提示词 | `pic/day9-tools-flow.png`、`pic/day9-tools-flow.prompt.txt` |

不纳入本次提交：已有的 `mini_pi/qwen_provider.py` 修改、独立 `pi-textbook/` 目录、`pic/day4-agent-lifecycle.prompt.txt`。`local-learning/evidence/` 保持 Git 忽略，原始运行记录仅留本地。

## 审核证据

- [第九次学习记录](pi-learning-roadmap.md#第九次学习记录)：明确用户手敲、助手准备及授权修复的分工。
- [学习图](../pic/day9-tools-flow.png)：区分一般模型循环与本次预设调用联调。
- 本地 `local-learning/evidence/d09-test-results.txt`：13 项通过、无跳过。
- 本地 `local-learning/evidence/d09-5074cf7378c2447eafffe519c62f78f5/trace.json`：四工具成功/失败结果、ID 配对和折扣真实断言结果。

边界：仅验证独立演示项目的单个折扣用例，不声称模型自主选择工具、所有业务边界用例或 Mini-Pi 第一版已完成。JSONL 会话存储、进程树取消及运行预算仍属后续学习范围。

根据 [AGENTS.md](../AGENTS.md) 的归档规则，此页展示具体范围与中文说明。用户已在审核后明确要求“先提交推送”，授权按上述范围提交到开发分支并推送。
