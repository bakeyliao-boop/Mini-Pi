# 记忆模块跨电脑接续

> 整合候选提示（2026-10-27）：本文保留记忆分支原有学习/验收历史。D13冻结及12/30不代表当前主线；当前主线已完成D14/M1、进入D15（14/30）。新接线与边界见[整合候选说明](memory-mainline-integration.md)，原工作区尚未正式合并。

最新整体验收（2026-10-27）：[MEM-04首版技术验收](mem04-acceptance.md)通过，74项正式复验全过、0失败/错误/跳过。完整Session→固定提取→明确计划/临时SQLite写入→每轮检索/组装→两轮模型输入及真实文件工具→run_end已验证；本地HTTPS进一步核对原embedding/回答适配器实际发送的JSON及取消时关闭资源后结束。云调用0次，真实云端语义效果未验证。本次67文件范围已获用户提交推送授权，实际提交和同步结果以当前Git记录及远端分支为准。以下10月26日为历史。

最新接续（2026-10-26）：已核对学习者敲入的extract_session，核心正确且未代改，5项专项全过。助手扩充固定响应示例并实际完成临时SQLite明确写入、原计划重试、同候选重规划及新Store读回，始终一条v1，完整Source和生效时间保留，原Session不变；见[接线验收](memw-session-integration-acceptance.md)。现在进入[MEM-04整体框架](mem04-context-plan.md)，先讲清单次Context输入输出再分段手敲。此前[v2.2定向小试](memw-reference-v22-results.md)2/2通过仅针对两例，所有真实调用额度已用完，不追加；旧6/7、4/5及8/9不改。

最后维护：2026-10-27。学习分支：`codex/agent-memory`。本次归档基线为`b0c0e9a`，执行前已核对远端分支一致；MEM-W/MEM-04这67文件范围已获用户提交推送授权，详见[本次提交清单](memw-mem04-submit-manifest.md)和[准备检查](memw-mem04-submit-checks.md)。

此前代码快照以 `b02a7d1` 提交并推送至 `origin/codex/agent-memory`，当时远端提交已核对一致。该历史快照通过独立源码副本与新虚拟环境验证：全量491项中489通过、2项旧Windows权限跳过。执行口径和推送回执见[同步检查记录](memory-sync-checks.md)，不将其当作本次新范围已推送的回执。

下表包含该历史快照之后的学习结果，属于本次67文件归档；提交前检查是历史快照，执行结果以Git记录和远端分支核对为准。

## 现在学到哪里

| 单元 | 当前状态 |
| --- | --- |
| MEM-01/02 | 来源入库、版本更新、整系列撤回、持久操作回执已验收 |
| MEM-03 | 范围/条件/时间过滤、向量检索、阿里 embedding 适配与小样本试点已验收；便携测试结果见同步检查记录 |
| MEM-W | 正文/来源分离、来源核验、建议归组、latest、新增/重试、首次更新/撤回规划及受控计划执行入口已验收 |
| 最新完成 | MEM-04选定首版技术范围整体验收通过，74项实际全过，含真实临时文件/SQLite及本地HTTPS闭环 |
| 当前课 | 首版技术验收已收口，代码与理解边界见mem04-acceptance.md，不重复已验核心；本轮没有新增核心实现 |
| 后续 | 先按验收报告复盘当前能力；真实云端语义/更多能力另定目标与计划，提交推送仍需具体范围授权，不自动扩大 |

主线仍为 **12/30**。原电脑 D13-A/B 未提交现场及 D13-B 暂停点保留；本分支从 D12 基线发展，没有把那份未完成代码迁入。本次接续的是记忆模块。

## 下一次直接从这里开始

可对另一台电脑上的 Codex 说：

> 请先读AGENTS.md、memory-resume.md和mem04-acceptance.md。2026-10-27首版MEM-04技术验收通过，正式复验74项全过，执行证据evidence/mem04-acceptance-20261027/。核心由学习者手敲，助手只按明确授权修错；无需重写或重复手敲。完整Session/固定提取/明确计划写入/检索/组装/两轮请求及真实文件已串联，本地HTTPS还验证embedding和QwenProvider实际JSON及取消关闭。真实云模型整链语义效果仍未验证，旧MEM-W 6/7、4/5、8/9与v2.2两例定向成绩原样保留。三字段五出口、字段/动作/query/任务归属/单一at由可信调用方明确，字符预算超限停止，不自动摘要或裁剪，不新增自动元字段或任务匹配模块。普通模型异常仍外抛，准备阶段错误才转error并写run_end。D13原现场冻结及D主线12/30不变。所有真实调用额度已用完；没有新预算授权不追加。本次67文件范围已获提交推送授权；后续新增范围仍须先展示清单和中文说明并取得授权；无例行hash。

受控执行入口已实现：先完整核对批次类型、Scope及最多一个变更计划，再由MemoryEntry原快照透传，或将完整计划委派remember/replace/retract。更新/撤回重试复用原版本和operation_id，不重新规划；多个计划在任何变更前整批拒绝。withdrawal标签本身不授予撤回权限，已有Entry也不代表当前仍有效。候选到Draft/计划、模型响应解析及异步接线已分段技术验收，首次6条真实提取语义试点未通过；整个MEM-W尚未完成。

现有代码：

- [planning.py](../mini_pi/memory/planning.py)：`plan_remember`、`find_retry`、`plan_remember_or_retry`、`plan_replace`、`plan_retract`。
- [execution.py](../mini_pi/memory/execution.py)：`execute_plans`完整预检及四类分派；接受已由可信调用方确认的计划。
- [selection.py](../mini_pi/memory/selection.py)：来源核验、建议归组及draft_from_candidate已分段验收；不证明提取正文语义正确。
- [extraction.py](../mini_pi/memory/extraction.py)：候选检查与完整Source关联此前已验收6项，模型响应结束检查/严格JSON解码本轮已验收7项；本章[最新上游核对/范围/验收](memw-extraction-plan.md)。
- [extraction_client.py](../mini_pi/memory/extraction_client.py)：专用提取请求与异步发送已验收9项；本段[最新源码、输出接线和验收](memw-request-plan.md)。
- [提取小样本与调用计划](memw-extraction-evaluation-plan.md)、[6条固定Source/标注](../examples/fixtures/memory_extraction_eval_v1.json)及[首次真实结果](memw-extraction-pilot-results.md)：实际6次，技术通过、语义未通过。
- [评测辅助](../examples/memory_extraction_eval.py)：默认预览，显式live才读取本地配置；6项离线门禁已通过。本轮已消耗6次授权，不能直接重跑live。
- [store.py](../mini_pi/memory/store.py)：`remember / replace / retract / latest / search`。
- [MEM-W 路线](memw-learning-plan.md)及[详细实现记录](agent-memory-implementation.md)。技术通过与学习者理解确认分开记录。

`plan_replace / plan_retract` 仅做首次规划；同一操作重试必须复用原 ReplacePlan / RetractPlan，直接调用对应 Store 方法。丢失计划后的重新规划恢复尚未交付。跨来源正文相同不自动判重复；多次持久变更的整批提交协议尚未实现。

## 在另一台电脑拉取

首次克隆：

```sh
git clone --branch codex/agent-memory https://github.com/bakeyliao-boop/Mini-Pi.git
cd Mini-Pi
```

已有仓库时，先确认本地改动已妥善保存，再执行：

```sh
git fetch origin
git switch codex/agent-memory
git pull --ff-only origin codex/agent-memory
git log -1 --oneline
```

使用 **Python 3.14**，当前已验证版本为 3.14.5；最低兼容版本未另行验证。依赖固定于 `requirements.txt`（httpx 0.28.1）。

Windows PowerShell：

```powershell
py -3.14 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p "test_memory*.py" -v
```

macOS / Linux：

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -B -X utf8 -m unittest discover -s tests -p 'test_memory*.py' -v
```

上面的test_memory*.py仅覆盖记忆测试，未包含test_loop_memory_context.py等循环测试。完整复现MEM-04的74项请用[验收报告的14模块命令](mem04-acceptance.md)。全量测试将上面的pattern改为test_*.py；Windows缺符号链接权限时，旧D08用例可能跳过，以实际输出为准。

以下命令默认只预览合成数据，不读真实密钥、不调用模型：

```sh
python -B -X utf8 -m examples.memory_embedding_smoke
python -B -X utf8 -m examples.memory_embedding_eval
```

请使用虚拟环境解释器执行；也可以先激活环境后用 `python`。

## 配置、证据与源码边界

- 离线学习和测试无需 `.env`。`.env.example` 仅有空密钥和模型配置；真实凭据需在新电脑本地单独配置，不随 Git 同步。本次没有授权新的真实调用。
- 原始本机执行记录、真实 Session 和业务 SQLite 不随 Git 同步。仓库内 `tests/fixtures/memory_legacy_content_v1.*` 是合成兼容测试数据；本地 HTTPS 使用已公开提交的合成测试证书。
- Session 来源 ID 含原绝对路径，搬迁 JSONL 后重新导入不等于同一候选的透明重试。不要靠复制文件宣称旧库/旧来源已自动迁移。
- 固定 Pi 阅读基准：`7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`。需要继续源码对照时，另行克隆 `https://github.com/earendil-works/pi.git` 并切到该提交；离线测试不依赖该仓库或本机源码缓存。
- MEM-03 六案试点只支持该数据集的检索结论，不证明生产泛化、回答正确或 MEM-W 提取质量。人民币费用仍未知。
