# 记忆模块跨电脑接续

更新：2026-10-23。学习分支：`codex/agent-memory`。当前提交以 `git log -1 --oneline` 为准。

接续快照已通过独立源码副本与新虚拟环境验证：全量491项中489通过、2项旧Windows权限跳过。执行口径和提交状态见[同步检查记录](memory-sync-checks.md)。

## 现在学到哪里

| 单元 | 当前状态 |
| --- | --- |
| MEM-01/02 | 来源入库、版本更新、整系列撤回、持久操作回执已验收 |
| MEM-03 | 范围/条件/时间过滤、向量检索、阿里 embedding 适配与小样本试点已验收；便携测试结果见同步检查记录 |
| MEM-W | 正文/来源分离、来源核验、建议归组、latest、新增/重试及首次更新/撤回计划已验收 |
| 最新完成 | 首次明确撤回计划已验收；284项记忆测试通过，不可达旧占位已清理 |
| 下一课 | 统一写入执行入口与一次持久变更边界，先说明调用顺序再手敲 |
| 后续 | 完整写入入口、真实 LLM 候选提取与保真评测、MEM-04 实际 Context 注入 |

主线仍为 **12/30**。原电脑 D13-A/B 未提交现场及 D13-B 暂停点保留；本分支从 D12 基线发展，没有把那份未完成代码迁入。本次接续的是记忆模块。

## 下一次直接从这里开始

可对另一台电脑上的 Codex 说：

> 请先读 AGENTS.md 和 local-learning/memory-resume.md，继续 MEM-W 的统一写入执行入口。新增/重试、首次显式更新与首次明确撤回计划都已分段验收。先用一个例子讲清如何区分 MemoryEntry、RememberPlan、ReplacePlan、RetractPlan，以及最多一次持久变更的执行顺序，再带我分段手敲。保持说明简洁，辅助代码和测试由你准备。

明确撤回计划已实现：输入可信 Scope、原用户 Source、明确 key/conditions 和固定 operation_id，规划不写库；执行/重试复用原计划交给 Store.retract。下一课把已形成的计划交给现有 Store 方法，已有 MemoryEntry 直接返回；多个持久变更在批事务未实现前应整体拒绝或待核对，不能先写一半。withdrawal 标签本身不授予撤回权限。

现有代码：

- [planning.py](../mini_pi/memory/planning.py)：`plan_remember`、`find_retry`、`plan_remember_or_retry`、`plan_replace`、`plan_retract`。
- [selection.py](../mini_pi/memory/selection.py)：来源核验和建议归组；不证明提取正文语义正确。
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

全量测试将上面的 pattern 改为 `test_*.py`。Windows 缺符号链接权限时，旧 D08 用例可能跳过，以实际输出为准。

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
