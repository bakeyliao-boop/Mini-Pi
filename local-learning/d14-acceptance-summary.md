# D14 单 Agent 真实修复验收

验收日期：2026-10-26。D14 和 M1 单 Agent 可用首版已完成；有指导复盘通过，不代表独立闭卷实现或 Mini-Pi v0.1 全部交付。

## 任务与权限

在每次新建的隔离副本中修复折扣计算。rate表示减免比例，100元减免20%应实付80元。

- 仅允许编辑 `discount.py`，固定测试 `test_discount.py` 不允许模型修改。
- 工具：list_files、read_file、edit_file、run_tests；测试命令由程序固定，模型不能替换。
- 真实验收使用qwen3.8-flash，最多6次请求、每次输出上限1024 token、循环时限120秒；工具测试自身时限30秒，资源收尾可能延长。

## 三类运行必须区分

- prepare：只创建新副本并执行修复前测试，不调用模型。
- offline：使用助手提供答案的MockProvider，通过真实文件、测试进程和JSONL验证接线；不算真实自主修复。
- live：使用真实QwenProvider自主选择工具和修改。付费运行需单独授权；本次只执行了一次，6次请求。

## 真实轨迹与结果

1. list_files：查看隔离项目。
2. read_file两次：读取源码和固定测试。
3. run_tests：5项中4项失败，取得实际失败反馈。
4. edit_file：仅修改discount.py一行，由`price * rate`改为`price * (1 - rate)`。
5. run_tests：5项全部通过。
6. 无工具调用：模型读取通过反馈后给出最终总结；本轮本身不执行测试。

验收器另外独立运行同一固定测试，5项全通过；固定测试未改、没有额外源文件，JSONL与返回历史一致、Agent已idle。RunResult.status为finished，task_passed仍为null，独立验收结论另存，未将外部结果伪装成循环自己的判断。

真实usage：输入9321 token、输出402 token、合计9723 token。输入中cached_tokens为5120，已经包含在输入计数中；不重复相加，不虚构账单金额。

## 验收器修正及回归

第一次报告把“模型看到通过测试反馈”误记为false：原检查在两层JSON编码后的字符串中搜索未转义字面量，产生假阴性。修正为按真实run_tests调用ID配对，解码API消息外壳及output两层JSON，再核对tests_passed和exit_code=0。第6次请求实际携带该反馈。

原acceptance.json保留，复核另存acceptance.rechecked.json；修正验收器没有再调用模型，也没有修改业务循环。4项反例覆盖嵌套JSON、错误调用ID/assistant声明、失败/工具错误和坏JSON。

Python3.14.5全量400项：398通过、0失败/错误、2项旧Windows符号链接权限跳过。预算/时限、生命周期/重入、队列时序、模型错误/截断、真实连接/进程取消、恢复门禁、CLI和四工具的用例关联于closure.json。

## 如何使用

在项目根目录、已安装requirements.txt的Python3.14.5环境中：

```powershell
python -X utf8 -m examples.d14_acceptance --mode prepare
python -X utf8 -m examples.d14_acceptance --mode offline
```

`--mode live`会产生真实模型请求，只在明确授权并在运行进程中配置DASHSCOPE_API_KEY后使用。脚本默认prepare，不隐式启动付费运行。每次使用新副本，练习模板保留原始bug。

## 证据与理解边界

本机原始证据位于忽略目录`local-learning/evidence/d14-live-e8b6fc30ceed/`：config.json、baseline-tests.txt、session.jsonl、model-requests.json、change.diff、independent-tests.txt、acceptance.json、acceptance.rechecked.json、full-regression.txt、closure.json。原始执行记录与凭证不随本次提交上传；仓库保留验收摘要和可重新运行的辅助代码，不宣称原始云请求可离线复现。

有指导复盘确认三点：改动没越界、确实修了问题、测试确实通过。授权业务源码可以修改，固定验收测试不能为通过而放宽；模型最终总结依赖测试反馈，不能替代实际证据。

本次只证明一个受控折扣任务通过，不外推任意项目可修复。上下文压缩、reviewer和后续评测仍待完成。
