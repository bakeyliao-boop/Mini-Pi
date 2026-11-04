# D20 样例与日志

当前完成 Pi smoke 的案例登记、Python 独立判定及离线/真实调用日志入口。2026-11-03 已通过一次百炼真实调用的全部五项判定。原始参考文件保存在 [upstream/pi](upstream/pi/README.md)，不直接修改原 TypeScript 样例。

另有4个文件编辑工具来源样例已完成适配验收，见文末。当前为1个模型样例、4个工具样例，不合并计算模型成功率。2026-11-04统一核验5例通过、3个判定对照符合预期，入口及历史真实记录复核边界见文末。

## 当前怎样运行

从仓库根目录执行：

```sh
python -X utf8 -m examples.d20_smoke
python -X utf8 -m examples.d20_smoke --answer London
python -X utf8 -m examples.d20_smoke --simulated-error "offline request failed"
```

三个命令都使用预设的模拟响应，经现有 Mini-Pi Harness 运行；不读取 API 凭证，不访问模型服务。模型工具定义为空，路由器也没有可执行工具。默认的预期 provider/model 为本项目后续目标配置，不代表离线模式实际调用过它们。

| 情况 | 运行状态 | 案例判定 | Python 进程退出码 |
| --- | --- | --- | --- |
| 预设回答 `Paris` | `finished` | `unverified`，输出和错误检查通过，真实身份与用量未知 | 2 |
| 预设回答 `London` | `finished` | `failed`，答案不符合原判定 | 1 |
| 模拟调用直接抛异常 | `exception` | `failed`，记录异常类别和原因 | 1 |

判定值为 `passed`、`failed`、`unverified`。完整观测下判定通过才退出 0，失败退出 1，尚有原判定未验证退出 2。PowerShell 或其他命令包装层可能将原生非零码统一显示为 1；以上为本次通过 Python subprocess 实测的进程返回码。

## 显式真实调用

默认仍为离线。已有 `DASHSCOPE_API_KEY` 环境配置时可显式执行：

```sh
python -X utf8 -m examples.d20_smoke --mode live
```

本次实际复用了当前设备已有 Pi 百炼配置，运行命令为：

```sh
python -X utf8 -m examples.d20_smoke --mode live --auth-file "C:\Users\hyf\Documents\ChatGPT\pi-runtime-config\auth.json"
```

只读取已有 `bailian` API Key，不创建或修改凭证。每次最多 1 个模型请求、不自动重试；继续使用本案例 10 秒运行预算，输出上限 128 tokens。真实模式拒绝预设回答/模拟错误参数，离线模式不读取凭证文件。路径只适用于当前设备。

2026-11-03 真实结果：`qwen3.8-flash` 返回 `Paris`，错误列表为空，provider/model 检查及正用量检查通过，`run_status=finished`、`case_verdict=passed`、退出码 0。服务返回输入 39、输出 1、总计 40 tokens；实际请求 1 次，耗时约 1.05 秒。见 [真实结果](../local-learning/evidence/d20-smoke/20261103T075112Z-df4b6999dd/result.json) 和 [实际请求记录](../local-learning/evidence/d20-smoke/20261103T075112Z-df4b6999dd/requests.json)。

这是 Pi 原样例在 Mini-Pi 适配器上的单次真实验收，不是运行上游 TypeScript 评测器，也不代表 D20 其余样例已完成。

## 每次保存什么

入口每次创建新的 `local-learning/evidence/d20-smoke/<UTC时间>-<编号>/`，原记录不覆盖，运行输出按仓库规则保持 Git 忽略。

| 文件 | 内容 |
| --- | --- |
| `protocol.json` | 上游来源、原始输入、工具限制、预期配置、本次 Mini-Pi 预算、模拟模式和运行编号 |
| `session.jsonl` | 现有 SessionStore 实际写入的消息与运行记录 |
| `requests.json` | 本次真正交给模拟模型的历史快照和工具定义 |
| `result.json` | 运行状态、原始输出、错误、耗时、请求次数、各项判定及最终案例结论 |

日志不保存环境变量全集、API Key 或授权头。真实入口复用 QwenProvider 已有请求记录，保存服务原始 usage 和返回模型标识。缺失的真实 usage 和实际模型身份保留为 `null`，对应检查为 `unverified`，不会填成 0 或由离线预期配置冒充实测值。

底层直接抛异常时，评测入口捕获并保存结果；`exception` 是评测入口观察到的异常状态，不冒充运行循环返回的 RunResult。若原运行循环未写出 `run_end`，保留实际会话并记录 `session_has_run_end=false`，不补造结束记录。调用方取消时复用已有稳定等待收尾，再保存取消结果。

## 原判定如何映射

[cases/pi_smoke.json](cases/pi_smoke.json) 保留原题、五项检查和来源版本。原五项为：回答首尾去空白后等于 `Paris`、错误为空、provider 正确、model 正确、真实 token 总量大于 0。Python 适配在 [pi_smoke.py](pi_smoke.py) 中，预算是 Mini-Pi 的执行配置，不属于原始断言。

离线入口只观察到模拟回答与运行错误，身份、用量三项均保留未验证。判定器单元测试使用明确的合成身份和 usage 验证比较逻辑，这些合成值不会作为真实服务观测写入离线案例结果。

原 Pi `packages/evals/src/harness.ts:399` 从所选模型配置取得 `usage.provider` 和 `usage.model`，并使用会话统计用量。本适配在请求收到响应后，用实际选用的百炼适配器和请求记录里的 `requested_model` 对应这两项；服务 `response.model` 另存 `returned_model`。服务原始 `usage.total_tokens` 对应原样例的 `usage.totalTokens`，不自行补零或用合成值代替。这些来源在 `telemetry_note` 中明确记录。

## 验证记录（2026-11-03）

首次离线入口的辅助验证为 10 项通过。新增真实入口后，实际再次执行 `python -X utf8 -m unittest discover -s tests -p test_d20_smoke.py -v`，15 项通过。覆盖原题与五项判定保留、正确与错误输出、缺失信息保持未验证、日志/异常/取消收尾及不覆盖记录，以及单次请求、配置失败、原始 usage 映射和密钥不入日志。辅助测试中的 HTTP 均为模拟，真实一次请求单独见上方记录。

另外实际执行了上述三个离线命令，结果与表格一致，目录分别为：

- [Paris 排演](../local-learning/evidence/d20-smoke/20261103T072651Z-0cb81c50f9/result.json)
- [London 排演](../local-learning/evidence/d20-smoke/20261103T072652Z-5192603c16/result.json)
- [调用异常排演](../local-learning/evidence/d20-smoke/20261103T072652Z-952a645d2b/result.json)

首次验证曾发现直接抛异常时缺少最终结果文件，已在辅助评测入口修复；初次记录保留，并附单独说明。本轮未修改 `mini_pi/` 核心实现。D20 仍在进行；先前模拟结果与当前真实通过结果分别保留，下一步对照具体结果讲解完整通过的依据，再扩展其他上游样例。

首次离线验证摘要、三组模拟结果及最初失败注记路径汇总在 [verification-20261103.json](../local-learning/evidence/d20-smoke/verification-20261103.json)；后续真实调用和15项辅助验证汇总在 [verification-live-20261103.json](../local-learning/evidence/d20-smoke/verification-live-20261103.json)。

## 第二例：直接文件编辑，不使用 LLM

来源为固定 Pi 提交 `7f9e1198` 的 `packages/coding-agent/test/tools.test.ts:282`，名称 `should replace text in file`。原摘录及来源说明在 [upstream/pi](upstream/pi/README.md)，案例定义为 [pi_edit_replace.json](cases/pi_edit_replace.json)。

```sh
python -X utf8 -m examples.d20_edit_replace
```

原输入保持不变：文件 `edit-test.txt` 内容为 `Hello, world!`，将唯一的 `world` 换为 `testing`，预期 `Hello, testing!`，不额外添加换行。入口直接调用现有编辑工具，模型请求为 0，不创建 Agent 会话，不读取 API 凭证。

| 原 Pi 检查或字段 | Mini-Pi 适配 |
| --- | --- |
| 绝对路径、`edits[{oldText,newText}]` | 独立工作目录内相对路径、`old_text/new_text` |
| 成功提示文字 | 实际 ToolResult.error 为 None，不伪造英文提示 |
| `details`、`details.diff` 存在且为字符串 | 实际 ToolResult.output 存在且为字符串，明确为结构映射 |
| diff 包含新文字；patch 的头部、差异行和修改前后内容 | 对实际返回的统一差异逐项检查 |
| `applyPatch(originalContent, patch)` 得到预期文本 | 独立副本写入原文，再用 Git 检查并应用真实补丁，比较重建文本 |
| 原例没有单独读回磁盘文件 | Mini-Pi 额外读取实际文件，检查它确实被修改 |

这是接口语义移植，原 TypeScript 的英文成功文本及 details 对象断言没有原样执行，`native_pi_evaluation=false`；映射在协议和结果中保存。`case_verdict=passed` 表示适配规则及额外磁盘检查通过，不冒充上游原生断言逐字通过，也不计为 LLM 自主编辑成功。

每次新建 `local-learning/evidence/d20-edit-replace/<时间>-<编号>/`，保存协议、工具请求和真实返回、修改前后内容、独立补丁校验及结果。没有伪造 `session.jsonl`，因为本例没有运行 Agent。补丁只允许指向预期文件，独立校验不沿用父 Git 仓库的路径解释，未启用不安全路径选项。缺少 Git 或校验超时时，补丁重建项记为未验证。

2026-11-03 实际运行一次真实编辑：磁盘文件和补丁重建文本均为 `Hello, testing!`，适配验收通过，模型0次。见 [本例结果](../local-learning/evidence/d20-edit-replace/20261103T084811Z-eb77b4d9b7/result.json)、[工具返回](../local-learning/evidence/d20-edit-replace/20261103T084811Z-eb77b4d9b7/tool_result.json)及[补丁检查](../local-learning/evidence/d20-edit-replace/20261103T084811Z-eb77b4d9b7/patch-check.json)。

本例 `test_d20_edit_replace.py` 10 项辅助测试通过，包括成功提示但未改文件、补丁正确但实际文件没改、文件正确但补丁错误等反例。共用 JSON 日志函数提取后，smoke 的 15 项辅助测试再次通过，HTTP 为模拟；本轮没有新增真实模型请求。辅助测试数量和上游来源样例数量分别统计。

## 第三例：旧文字不存在，预期工具报错

来源为固定 Pi `7f9e1198` 的 `packages/coding-agent/test/tools.test.ts:305`，名称 `should fail if text not found`；原摘录在 [edit-missing-text.excerpt.ts](upstream/pi/edit-missing-text.excerpt.ts)，定义在 [pi_edit_missing_text.json](cases/pi_edit_missing_text.json)。

```sh
python -X utf8 -m examples.d20_edit_missing_text
```

文件 `Hello, world!` 中不存在 `nonexistent`，原请求仍要求将它换成 `testing`。原 Pi 判定是调用拒绝，错误匹配 `Could not find the exact text`；Mini-Pi 映射为 ToolResult.error 存在并包含当前错误文字“未找到代替换的旧文本”。检查磁盘不变和无成功补丁是明确标记的补充检查。

2026-11-03 实际执行工具1次，模型0次，结果为 `run_status=finished`、`tool_outcome=error`、`expected_tool_outcome=error`、`case_verdict=passed`，before/after 均为 `Hello, world!`。`finished` 指外层样例执行器走完，`error` 是保留的实际工具拒绝，`passed` 指它符合本题预期；不能见到 errors 非空就自动判案例失败。

见 [本例结果](../local-learning/evidence/d20-edit-missing-text/20261103T100205Z-673f383c11/result.json)和[工具返回](../local-learning/evidence/d20-edit-missing-text/20261103T100205Z-673f383c11/tool_result.json)。复用编辑成功样例的日志与执行流程，原始错误不清空、不伪装成功；本题不要求成功补丁，`patch-check.json` 为 `not_applicable`，不是缺少必需验证。没有创建 Agent 会话或执行原 TypeScript 断言。

新增7项辅助测试通过，覆盖正确错误、意外成功、其他错误原因、错误但误改文件、把错误文字放在成功输出等情况；原编辑成功的10项回归也通过。适配源码记录抛异常与返回错误字段的差异，本结果仅表示 Mini-Pi 语义适配规则通过。本轮未修改核心实现或新增真实模型请求。

## 第四例：目标文件不存在，错误必须带路径与 ENOENT

固定 Pi `7f9e1198` 的 `tools.test.ts:318–327` 为来源，原文在 [edit-missing-file.excerpt.ts](upstream/pi/edit-missing-file.excerpt.ts)，固定定义在 [pi_edit_missing_file.json](cases/pi_edit_missing_file.json)。目标 missing.txt 不存在，合法参数为 hello → world；不创建空文件冒充这一初始条件。此例直接调用工具，不使用 LLM。

```sh
python -X utf8 -m examples.d20_edit_missing_file
```

原判定要求拒绝编辑并返回包含目标路径和 ENOENT 的完整错误信息。Mini-Pi 明确映射为 ToolResult.error 中的文件不存在原因、实际完整路径、字面 ENOENT；英文措辞和异常接口不原样执行。文件仍不存在、无成功补丁是额外检查。没有给 ToolResult 新增字段。

2026-11-04 修复前实际运行：`run_status=finished`、`tool_outcome=error`、`case_verdict=failed`；失败项为 `error_contains_target_path` 与 `error_code_matches`，目标前后均不存在。见 [首次结果](../local-learning/evidence/d20-edit-missing-file/20261104T014844Z-21643f75dd/result.json)、[真实工具返回](../local-learning/evidence/d20-edit-missing-file/20261104T014844Z-21643f75dd/tool_result.json)和[验证汇总](../local-learning/evidence/d20-edit-missing-file/20261104T014844Z-21643f75dd/verification.json)。日志用 initial-state.json 和 before_exists/after_exists 表示不存在，不伪造 before.txt/after.txt 或会话记录。

三个编辑案例辅助测试合计24项，23通过、1失败。新增真实工具契约检查暴露了缺少诊断信息的问题，其余6项新判定检查及原17项回归通过。核心仍未修改，待学习者补齐错误文字后复验，不将预期应报错等同于本次验收通过。

2026-11-04 学习者手敲补齐第42行错误文字后复验：第四例 `case_verdict=passed`，六项检查全通过，工具仍按预期返回 error，目标文件前后均不存在，模型0次。见 [修复后结果](../local-learning/evidence/d20-edit-missing-file/20261104T020006Z-6f7b2a5180/result.json)及[验证汇总](../local-learning/evidence/d20-edit-missing-file/20261104T020006Z-6f7b2a5180/verification.json)。三个编辑案例的24项辅助测试及原文件访问4项回归均通过，完整输出保存同目录 tests-output.txt。原失败记录不覆盖；本次仅为工具级语义适配验收，不宣称上游 TypeScript 断言原生通过。

## 第五例：旧文字出现多次，须拒绝并报告3处

固定Pi `7f9e1198` 的 tools.test.ts 第329–340行为来源，原摘录在 [edit-multiple-matches.excerpt.ts](upstream/pi/edit-multiple-matches.excerpt.ts)，定义在 [pi_edit_multiple_matches.json](cases/pi_edit_multiple_matches.json)。保留原文件 foo foo foo 和 foo → bar 请求，原判定 rejects.toThrow(/Found 3 occurrences/) 映射为 ToolResult.error 中的多处匹配原因及明确的“共3处”。按整数比较次数，13或2不能通过。文件不变及无成功补丁为额外检查，不冒充原TypeScript断言。

```sh
python -X utf8 -m examples.d20_edit_multiple_matches
```

2026-11-04 修复前实际执行：外层 finished、工具 error、案例 failed，仅 occurrence_count_matches 未通过；文件前后仍为 foo foo foo，模型0次。见 [首次结果](../local-learning/evidence/d20-edit-multiple-matches/20261104T022430Z-9df23ce7f2/result.json)及[验证汇总](../local-learning/evidence/d20-edit-multiple-matches/20261104T022430Z-9df23ce7f2/verification.json)。四个编辑案例辅助测试合计31项，30通过、1失败；原24项回归均通过，待核心次数补齐后复验。

原输入仅含3处独立精确匹配。Mini-Pi现有额外边界为拒绝重叠的精确匹配，固定Pi在模糊归一化后作非重叠计数；本案例保留该范围差异，不宣称已对齐完整模糊匹配能力。

2026-11-04 学习者手敲统计逻辑后复验：第五例 case_verdict=passed，五项检查均通过；错误说明“共3处”，文件前后仍为 foo foo foo，模型0次。见 [修复后结果](../local-learning/evidence/d20-edit-multiple-matches/20261104T023102Z-07cfb34c2b/result.json)及[验证汇总](../local-learning/evidence/d20-edit-multiple-matches/20261104T023102Z-07cfb34c2b/verification.json)。四个编辑案例的31项辅助测试和原唯一匹配/文本替换8项回归均通过（合计39项）。原失败记录不覆盖，D20已适配通过5个来源样例，整章仍进行中。

## 统一核验入口

```sh
python -X utf8 -m examples.d20_checks --smoke-evidence local-learning/evidence/d20-smoke/20261103T075112Z-df4b6999dd/result.json
```

每次新建 d20-checks 目录，重跑4个工具样例及3个离线对照，按保存观测重新判定历史真实smoke。不会自动请求真实模型，不读取凭证，不沿用旧passed标签。历史观测路径由参数显式指定；不提供或缺失时仍运行离线检查，但smoke保持unverified，整体退出2。日志默认Git忽略，换设备后若无该文件会保留这一未验证状态；已有真实入口的调用须另行明确安排，统一入口不自动付费补跑。

2026-11-04实际统一结果为5例passed、3个对照符合预期，suite_verdict=passed、退出0，本轮真实模型新增0次。见 [机器结果](../local-learning/evidence/d20-checks/20261104T024426Z-2e244ff7ee/result.json)和[核验汇总](../local-learning/evidence/d20-checks/20261104T024426Z-2e244ff7ee/verification.json)。smoke的40 tokens来自2026-11-03已保存的真实观测，本轮4个工具实际重跑；3个对照为Paris模拟unverified、London模拟failed、调用异常failed。它们不是3个新增Pi来源样例，错误判定符合预期才算对照检查生效。

统一执行52项D20辅助测试全部通过，命令为 `python -X utf8 -m unittest discover -s tests -p 'test_d20_*.py' -v`。合成记录仅验证聚合和判定接口，HTTP为模拟，不冒充真实模型请求。取消先沿用单例已有清理并保存结果，然后停止后续样例。D20首版适配案例库完成；原生Pi评测、LLM自主修复成功率和D21上下文策略效果均不据此宣称通过。
