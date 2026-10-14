# Pi 学习与 Python 实现

通过阅读 Pi 的官方资料和源码，理解单 agent 的执行循环、工具调用、会话管理和上下文管理，再使用 Python 完成一个简化的 Mini-Pi，并加入 reviewer 子 agent。

学习路线和当前进度见 [Pi 阅读与 Python 实现路线](local-learning/pi-learning-roadmap.md)。其中包含 30 个步骤、每步的动作与验收标准，以及学习记录和第一版交付清单。

当前学习进度为 D01–D10 已完成（10/30），下一步为 D11 加载会话与恢复边界。四工具、基础循环、真实模型接入和正常运行的 JSONL 记录已分别验证；D09 完成示例预设的折扣用例修复，D10 确认示例进程退出后会话仍可查看。D10 使用模拟模型，尚未验证加载恢复、模型自主修复或第一版完整交付，后续进度以阅读文件中的总表为准。

## 本地验证 D05

在项目根目录执行，当前已使用 Python 3.14.5 验证，代码仅依赖标准库：

```sh
python -X utf8 -m unittest tests.test_read_file -v
python -X utf8 -m examples.d05_read_file
```

示例生成临时文件，实际调用读取工具，将三种结果保存到本地 `local-learning/evidence/d05-read-file-results.json`。原始结果保持 Git 忽略；它不是模型调用或折扣修复的成功证据。

## 本地验证 D06

在项目根目录执行：

```sh
python -X utf8 -m unittest tests.test_loop tests.test_read_file -v
python -X utf8 -m examples.d06_loop
```

已验证 5 项循环测试和 5 项读取工具测试，共 10 项通过。示例使用预设的模型响应，实际运行核心循环并读取临时文件；第二次请求包含用户消息、assistant 调用请求和匹配的工具结果，最终历史为 4 条。运行状态为 `finished`，`task_passed=None`，未验证折扣修复。

执行轨迹保存在本地 `local-learning/evidence/d06-loop-trace.json`，测试输出保存在 `local-learning/evidence/d06-test-results.txt`，两者保持 Git 忽略。核心循环由用户根据给出的代码分段手敲，最后按用户授权由助手修正缩进和参数名；模拟模型、测试和示例由助手准备。后续协作遵循 [学习协作规则](AGENTS.md)。

若 Windows 中的 `python` 指向未能启动解释器的 `WindowsApps` 入口，可在 PowerShell 中直接调用实际安装的 Python。当前设备已验证以下命令：

```powershell
& 'C:\Users\hyf\AppData\Local\Python\pythoncore-3.14-64\python.exe' -X utf8 -m examples.d06_loop
```

该路径只适用于当前设备；其他设备需使用自己的解释器路径。

## 本地验证 D07

D07 的核心转换函数在 `mini_pi/qwen_provider.py`，真实模型适配器在 `mini_pi/qwen_client.py`。核心逻辑由用户根据助手给出的代码分段手敲；HTTP、配置、记录、测试与示例由助手准备，个别错误按用户明确授权修正。

在项目根目录运行离线测试，不请求模型服务：

```sh
python -X utf8 -m unittest tests.test_qwen_provider tests.test_qwen_transport tests.test_loop tests.test_read_file -v
```

35 项通过：D07 转换 17 项、发送与适配器 8 项、D06 循环 5 项、D05 读取工具 5 项。网络入口在测试中模拟，测试中的 usage 是样例数据，真实 usage 另见下方运行摘要。

真实示例读取临时文件，使用文件中的随机标记检查最终回答是否接收了读取结果。密钥通过 `DASHSCOPE_API_KEY` 读取；可用 `DASHSCOPE_BASE_URL` 和 `QWEN_MODEL` 修改接口与模型，默认采用百炼北京地域的 OpenAI 兼容接口及 `qwen3.8-flash`。

先在本地配置环境变量。PowerShell 可使用隐藏输入，变量只在当前窗口及其子进程中生效：

```powershell
$taskSecret = Read-Host "输入 API Key" -AsSecureString
$env:DASHSCOPE_API_KEY = [System.Net.NetworkCredential]::new("", $taskSecret).Password
$taskSecret.Dispose()
Remove-Variable taskSecret
```

只检查本地配置，不验证服务权限或发送请求：

```sh
python -X utf8 -m examples.d07_qwen --check-config
```

下面的命令实际调用服务并消耗额度。示例配置最多 4 次请求、每次 `max_completion_tokens=1024`、HTTP 超时 30 秒，不自动重试：

```sh
python -X utf8 -m examples.d07_qwen --live
```

Windows 当前设备若遇到 `python` 入口问题，使用前面记录的真实解释器路径，并保留 `-X utf8 -m examples.d07_qwen` 和对应模式参数。必须在项目根目录运行，不能在 `mini_pi` 子目录运行模块命令。

2026-10-12 实际验证：服务返回模型 `qwen3.8-flash`，共 3 次请求、2 次文件读取，耗时约 12.10 秒。供应商 usage 合计输入 1,314、输出 232、总计 1,546 tokens；调用 ID 配对及工具结果回传均通过，最终解释包含文件中的随机标记。正常结束时 `task_passed=None`；D07 接入验收结论由记录和人工解释核对得出，不自动修改该字段。

原始轨迹和测试输出保持 Git 忽略，保存在 `local-learning/evidence/`。示例会打印本次唯一的轨迹路径；源码和学习记录不保存密钥。自动检查不证明折扣修复正确，也不证明完整的取消、会话与预算控制已经实现。

接口格式对照 [百炼 Chat API](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/) 与 [Function Calling 文档](https://help.aliyun.com/zh/model-studio/qwen-function-calling)。

## 本地验证 D08

D08 在 `mini_pi/tools/edit_file.py`、`edit_policy.py` 和 `edit_executor.py` 中实现受约束的文件编辑；[学习记录](local-learning/pi-learning-roadmap.md#第八次学习记录) 和 [执行图](pic/day8-edit-flow.png) 展示从 `ToolCall` 到实际读写、差异反馈的过程。在项目根目录运行：

```sh
python -X utf8 -m unittest discover -s tests -p "test_edit_*.py"
python -X utf8 -m examples.d08_edit_trace
```

当前设备的 Windows `python` 入口如不能启动，使用上文记录的实际解释器路径。Windows 下 48 项测试有 46 项通过，2 项因 WinError 1314 无法创建符号链接而跳过；在 Ubuntu WSL 的同一份工作区代码上 48 项全部通过，包括两项真实符号链接越界拒绝。示例构造 `ToolCall` 并真实修改临时文件，结果含差异和原调用 ID；不调用模型服务，也不判断折扣业务测试通过。原始输出保留在本地忽略目录 `local-learning/evidence/`。

## 本地验证 D09

D09 新增 `ToolRouter`、`list_files` 和 `run_tests`，复用已有读取、编辑工具。测试命令由程序固定；结果区分测试失败、超时和启动失败，截断时给出完整日志位置。实现与用户/助手分工见[学习记录](local-learning/pi-learning-roadmap.md#第九次学习记录)，流程见[心智图](pic/day9-tools-flow.png)。

在项目根目录运行，不请求模型服务：

```sh
python -X utf8 -m unittest tests.test_run_tests tests.test_list_files tests.test_tool_router -v
python -X utf8 -m examples.d09_tools
```

13 项针对性测试通过。联调示例在 `local-learning/evidence/d09-<运行ID>/workspace/` 内创建演示项目，记录四工具的成功和失败结果，并实际测试折扣公式修改前失败、修改后通过；示例调用顺序预先安排，不能证明模型能自主修复。完整轨迹和测试输出保留在本地忽略目录，重复运行会生成新的证据目录。

## 本地验证 D10

`SessionStore` 在 `mini_pi/session_store.py` 中保存线性 JSONL；给 `run_loop` 传入可选的 `session_store` 后，初始消息、模型响应、工具结果和正常结束状态逐条追加。运行 ID 和时间戳位于记录外层，实际消息或结果位于 `data`。实现分工与验收边界见[第十次学习记录](local-learning/pi-learning-roadmap.md#第十次学习记录)，两条保存路径见[心智图](pic/day10-session-flow.png)。

在项目根目录运行，不请求模型服务：

```sh
python -X utf8 -m unittest tests.test_loop_session tests.test_session_store tests.test_loop -v
python -X utf8 -m examples.d10_session
```

11 项相关测试通过。示例使用模拟模型和实际读取工具，生成 `local-learning/evidence/d10-<运行ID>/session.jsonl` 与 `summary.json`，正常退出后可重新读取；原始记录保持 Git 忽略。示例含六条记录，最终 `history` 为四项；运行开始和结束事件不作为模型消息。D10 实现保存，不实现加载继续运行、未完成写操作核对或异常恢复。

## 跨设备继续学习

远程仓库为 [bakeyliao-boop/Mini-Pi](https://github.com/bakeyliao-boop/Mini-Pi)。首次在其他设备使用时：

```sh
git clone https://github.com/bakeyliao-boop/Mini-Pi.git
cd Mini-Pi
```

在其他设备克隆本仓库后，打开阅读文件的“当前进度与下一步”。每次开始学习前执行 `git pull --ff-only`，结束后提交阅读文件与本次代码改动，再执行 `git push`。

遇到远程进度更新或冲突时，先核对两台设备的学习记录，再合并内容，保留双方实际完成的动作与证据。

阅读路线和学习进度随仓库同步。`local-learning/evidence/` 中的原始执行记录、模型输出，以及 `.env` 等凭证文件由 `.gitignore` 排除，仅保存在本地。

## 上游项目

- [Pi 源码](https://github.com/earendil-works/pi)
- [How Pi Works](https://pi.dev/docs/latest/how-pi-works)

本项目是围绕 Pi 的学习与 Python 简化实现，具体设计借鉴和实现边界会随学习记录更新。
