# Mini-Pi D11 验收与后续 Session 交接手册

交接日期：2026-10-14

工作目录：`C:\Users\hyf\Documents\ChatGPT\Pi`

开发分支：`codex/mini-pi-v0.1`

本次学习起点：`9b1aba4ca7ef33880b84deb6307ab84a4476b5d5`（完成第十天会话持久化与记录验收）

当前状态：D11 已于 2026-10-14 完成代码与理解验收。34 项相关测试通过，无跳过；三场景演示通过。用户已授权提交推送 D11，完成后进入 D12；实际同步状态以 Git 提交和远端分支核对为准。

## 新 Session 先做什么

1. 进入上述工作目录，不要 `reset`、`clean`、`stash` 或覆盖当前未提交代码。
2. 先读 [AGENTS.md](../AGENTS.md)、本交接手册、[D11 学习记录](pi-learning-roadmap.md#第十一次学习记录)和[路线中的 D12](pi-learning-roadmap.md#d12-实现预算-超时和取消)。
3. 用 `git status --short` 和 `git log -1` 核对工作区与提交，不按旧聊天结论推断磁盘或版本状态。
4. 先检查磁盘中的实际代码，再判断学习者已经敲入的内容。Codex 文件编辑器曾将旧标签页内容重新保存到磁盘，因此不能只沿用聊天中的旧结论。
5. 进入 D12 前先核对 `run_loop` 当前停止条件，再从最大模型轮数预算的关联、输入、输出和例子开始讲；核心代码分段由学习者手敲。

## 可直接复制给新 Session 的开场提示词

```text
请继续 C:\Users\hyf\Documents\ChatGPT\Pi 的 Mini-Pi D12 学习。

先阅读 AGENTS.md、local-learning/d11-next-session-handoff.md 和学习路线中的 D12，再核对当前磁盘代码、git status 和已有测试。不要重置、清理或覆盖已有代码；新提交推送需按当次授权范围执行。D11 已完成：加载、增量继续、pending 识别、RecoveryPlan 和 resume_session 门禁已实现；34 项相关测试与三场景示例通过。

继续采用 Python 初学者教学方式：先判断我的表述；新函数出现前说明连接位置、输入、输出、目的和具体例子；一次只给一小段可照敲的核心代码。辅助类型、测试、示例和导入由你准备。D12 从最大模型轮数预算入手，先解释计数和停止位置，再分段实现。保留已完成结果，区分预算停止、正常运行结束和业务验收通过。
```

## D01–D10 已建立的心智模型

| 阶段 | 已建立的理解 |
| --- | --- |
| D01–D04 | 模型提出动作，程序执行；循环决定继续或停止；生命周期和队列管理运行状态；运行结束不代表任务通过。 |
| D05–D07 | `Message`、`ToolCall`、`ToolResult` 是统一内部对象；适配器负责服务格式转换，循环负责安排工具执行和反馈。 |
| D08–D09 | 文件工具真实执行；路径、参数、唯一匹配及错误分类有边界；测试失败和工具执行故障分别表达。 |
| D10 | `history` 服务当前循环；JSONL 保存消息、工具结果和运行事件。`run_id` 标识一次完整运行，调用 ID 配对一次工具请求与结果。 |

D11 在 D10 后增加“加载和恢复判断”：

```text
session.jsonl
  → read_session_records：JSONL 文字变为记录字典
  → SessionStore.load：记录字典还原为 Message / ToolResult
  → find_pending_calls：找出有请求但没有结果记录的调用
  → plan_recovery：把情况分为 ready / read_interrupted / needs_review
  → resume_session：非 ready 明确返回；ready 才调用 run_loop
```

## D11 当前已经理解的结论

1. 加载历史是从 JSONL 重建对象，不会自动执行历史 `ToolCall`。
2. `find_pending_calls` 的输入是 `LoadedSession`，输出是缺少配对结果记录的 `PendingCall` 列表。
3. “缺少 `ToolResult`”只表示记录不能确认结果；工具可能尚未执行，也可能已经执行但结果未落盘。
4. 只读工具缺结果不会造成重复修改；写工具缺结果必须先核对实际状态。
5. `plan_recovery` 只返回判断，不执行工具：
   - `ready`：没有缺结果的调用。
   - `read_interrupted`：所有缺结果调用都属于程序明确配置的只读工具。
   - `needs_review`：存在写工具、未知工具或其他未声明只读的工具。

只读工具集合必须由程序配置，例如 `frozenset({"read_file", "list_files"})`。不能根据工具名字猜测；`run_tests` 会执行项目代码，当前默认不算只读工具。

6. 非 `ready` 返回 `ResumeResult(plan=plan, run_result=None)`；函数返回的是对象，只有 `run_result` 字段为 `None`。
7. `loaded.history` 是已保存旧历史；加入新问题后的 `history` 比它多一项。`already_saved` 必须用前者的长度，用后者会漏存当前用户消息。此项已经过用户正确复述。

## 当前代码及职责

| 文件 | 当前职责 | 状态 |
| --- | --- | --- |
| [`mini_pi/session_store.py`](../mini_pi/session_store.py) | 追加 JSONL、还原 `Message`/`ToolResult`、加载 `LoadedSession` | 已实现并通过测试 |
| [`mini_pi/session_records.py`](../mini_pi/session_records.py) | 逐行读取和校验记录，坏记录报告行号 | 助手准备，已通过测试 |
| [`mini_pi/loop.py`](../mini_pi/loop.py) | `already_saved` 只控制增量落盘，完整历史仍交给模型 | 已实现并通过正常继续测试 |
| [`mini_pi/session_recovery.py`](../mini_pi/session_recovery.py) | 校验请求结果配对，返回缺结果的调用 | 已实现并通过测试 |
| [`mini_pi/recovery_policy.py`](../mini_pi/recovery_policy.py) | 将 pending 调用分类为三种恢复状态 | 学习者已敲入，5 项专门测试通过 |
| [`mini_pi/session_resume.py`](../mini_pi/session_resume.py) | 恢复门禁、组装新历史并正常继续 | 学习者分两段手敲核心，6 项门禁测试通过 |

### 用户手敲与助手准备边界

用户分段敲入的核心包括：`_restore_item`、`load`、`already_saved` 切片、`find_pending_calls`、`plan_recovery` 和 `resume_session` 的门禁与继续逻辑。助手准备记录校验、数据容器、函数接口、测试和演示，并在此前用户明确要求时修正缩进、方法边界和字段名。本次没有代改恢复入口核心实现。

后续继续按 [AGENTS.md](../AGENTS.md) 执行：新核心函数出现前，先说明连接位置、问题、输入、输出和具体例子。不要直接丢代码。

## 已实际验证的内容

2026-10-14 使用 Windows Python 3.14.5 运行：

```powershell
& 'C:\Users\hyf\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 -m unittest tests.test_session_resume_gate tests.test_recovery_policy tests.test_session_recovery tests.test_session_restore tests.test_session_resume tests.test_loop_session tests.test_session_store tests.test_loop -v
```

结果：34 项通过，无失败、错误或跳过；原有 23 项、分类 5 项、入口门禁 6 项。

验证范围包括：

- JSONL 记录还原为 `Message`、`ToolCall`、`ToolResult`，加载时不执行工具。
- 正常退出后加载旧历史并加入新用户消息；模型看到完整历史，JSONL 只追加新消息，旧工具不重做。
- 成功结果和错误结果都算已有反馈，不进入 pending。
- 按 `(run_id, call_id)` 配对；跨运行相同调用 ID 不会相互抵消。
- 孤立结果、工具名错配、结果先于请求、重复请求和重复结果会明确拒绝。
- 非 `ready` 和配对异常时，模型及执行器零调用、没有新记录；混合 pending 整体停下。
- 恢复入口的 `ready` 分支传完整上下文，只保存新增消息，返回实际运行结果。

`plan_recovery` 已通过专门测试，分类包括：

```text
无 pending        → ready
只有 read_file    → read_interrupted
只有 edit_file    → needs_review
read + edit 混合  → needs_review
```

分类与入口门禁分别验证；D11 完成的是显式状态与正常继续，不是自动重放中断工具。

## 关键实际示例

[D11 pending 演示](../examples/d11_pending_demo.py) 在忽略目录中创建临时项目并真实执行：

1. 保存 `read_file/call_001` 和 `edit_file/call_002` 的请求。
2. 实际执行并保存读取结果。
3. 实际执行编辑，但故意不保存编辑结果和 `run_end`，模拟中断窗口。
4. 加载记录后，`find_pending_calls` 移除已配对的读取，只返回 `edit_file/call_002`。

实际证据：

- `local-learning/evidence/d11-pending-ac8dd0882c194bc9afab3f60f5322481/session.jsonl`
- 同目录 `summary.json`
- 同目录 `workspace/discount.py`

该文件已经实际变为 `price * (1 - rate)`，但 JSONL 没有编辑结果。这证明 pending 表示“结果未知”，不能解释为“工具没执行”。检查阶段没有重新执行工具，也没有修改 JSONL。

## 恢复入口与三场景验收（已完成）

### 恢复入口门禁

`resume_session` 已连接已有函数：

```text
store.load()
  → find_pending_calls(loaded)
  → plan_recovery(pending, configured_read_only_tools)
  → 根据 plan.state 决定是否允许 run_loop
```

已实现的首版边界：

- `ready`：可以在旧 `history` 后加入新用户消息，再调用 `run_loop`；传 `already_saved=len(loaded.history)`，避免重复写旧历史。
- `read_interrupted`：返回明确状态和 pending 列表，暂不自动重放读取，也不编造旧结果。
- `needs_review`：在任何模型请求、工具执行和新记录写入前停止，返回待核对调用。

这里不要直接把 dangling assistant 工具调用交给模型。若以后希望自动继续只读中断，需要先设计真实、可追溯的恢复反馈，并处理模型协议要求；D11 首版可以停在显式状态。

### 门禁测试

已验证：

1. `ready` 正常继续，已有记录不重复追加。
2. `read_interrupted` 时模型和所有工具零调用，没有新记录。
3. `needs_review` 时模型和所有工具零调用，没有新记录。
4. 混合读取和编辑缺结果时整体为 `needs_review`。

### 三场景执行证据

助手准备并实际运行 [d11_resume_demo](../examples/d11_resume_demo.py)。证据目录：`local-learning/evidence/d11-resume-155c3cf1e86241b3ae12569e13999062/`。

- `ready`：第一个独立进程实际读取并保存后退出，第二个独立进程加载并提问；恢复阶段模拟模型调用 1 次、工具 0 次；只追加四条新记录。
- `read_interrupted`：实际读取但省略结果记录；恢复时返回明确状态，模拟模型和工具均 0 次，记录与文件不变。
- `needs_review`：编辑实际已发生但省略结果记录；恢复时停下，模拟模型和工具均 0 次，没有重复编辑。

三场景共 20 项检查通过。每个场景保留 `session-before-resume.jsonl`、恢复后的 `session.jsonl`、实际 `discount.py` 与摘要；根目录 `summary.json` 汇总场景，`test-verification.json` 是实际测试结果摘要，不是原始终端输出。中断通过省略记录模拟，不是真实崩溃。示例没有请求真实模型服务，没有运行业务测试。

### 下一 Session：D12 预算、超时和取消

先解释当前 `run_loop` 的停止条件，再从最大模型轮数预算开始：预算输入是什么、哪一步计数、在哪里阻止下一次请求、返回何种状态、如何保留已完成消息与结果。不给出完整实现让用户独立补全；仍先关联与例子，再分段提供可直接照敲的核心代码。总时限、取消和测试子进程清理由后续小步分别处理。

D11 学习路线与交接记录已更新。用户已明确授权提交推送 D11，完成后进入 D12；提交说明为“完成第十一天会话加载与恢复门禁验收”。D11 学习收尾时的未提交状态已成为历史记录，新 Session 以当前 Git 状态为准。

## D11 提交范围与独立改动

D11 授权提交范围包括：

```text
AGENTS.md
README.md
local-learning/pi-learning-roadmap.md
mini_pi/loop.py
mini_pi/session_store.py
mini_pi/session_records.py
mini_pi/session_recovery.py
mini_pi/recovery_policy.py
mini_pi/session_resume.py
tests/test_session_restore.py
tests/test_session_resume.py
tests/test_session_recovery.py
tests/test_recovery_policy.py
tests/test_session_resume_gate.py
examples/d11_pending_demo.py
examples/d11_resume_demo.py
pic/day11-recovery-flow.png
pic/day11-recovery-flow.prompt.txt
local-learning/d11-next-session-handoff.md
```

以下是此前已有或独立内容，不要混入 D11 提交，不要重置或删除：

```text
mini_pi/qwen_provider.py
pi-textbook/
pic/day4-agent-lifecycle.prompt.txt
```

`local-learning/evidence/` 由 `.gitignore` 排除，只作为本机实际运行证据。不要在记录、源码或聊天中写入 API Key。

提交准备时已机械清理 `mini_pi/session_store.py`、`mini_pi/session_recovery.py`、`mini_pi/session_resume.py` 的末尾空白与行尾空格，Python AST 核对确认核心逻辑未改变。`mini_pi/qwen_provider.py` 的既存空白问题属于本次范围外，未改动或纳入 D11 提交。

## D11 完成后仍不能声称的内容

- 不能声称所有崩溃都能自动恢复。
- 不能声称缺少结果的写操作一定执行过或一定没执行。
- 不能自动重放 `edit_file`。
- 不能把 `ready`、`finished` 当成业务任务通过。
- 不能声称 Pi 的完整会话树、压缩或分支机制已经实现；Mini-Pi v0.1 当前仍是线性会话。
