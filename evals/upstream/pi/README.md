# Pi 上游原始样例

这些文件从本地 Pi 阅读副本的固定 Git 提交原样取出，不是 Mini-Pi 改写的题目。

- 仓库：<https://github.com/earendil-works/pi>
- 提交：`7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`
- `smoke.eval.ts` 来源：`packages/evals/evals/smoke.eval.ts`
- `LICENSE` 来源：上游根目录 `LICENSE`
- `edit-replace.excerpt.ts` 来源：`packages/coding-agent/test/tools.test.ts` 第 282–303 行，原样摘录。它是工具单元测试，不是另一个模型评测；只摘录这一个用例，依赖的外层工具、辅助函数与导入没有复制，不能单独作为完整 TypeScript 测试执行。
- `edit-missing-text.excerpt.ts` 来源：同文件第 305–316 行，名称 `should fail if text not found`。原输入仍为 `Hello, world!`，请求替换不存在的 `nonexistent`，原判定为调用拒绝并抛出匹配 `Could not find the exact text` 的错误。已完成 Mini-Pi 返回错误字段的显式映射与实际工具验收，未原生执行 TypeScript 断言。
- `edit-missing-file.excerpt.ts` 来源：同文件第 318–327 行，名称 `should include ENOENT when the edit target does not exist`。目标 `missing.txt` 不存在，原判定要求报错信息包含目标路径及 `ENOENT`。2026-11-04 首次实测暴露诊断缺项，学习者补齐错误文字后适配验收通过；修复前失败与修复后通过分别记录，未原生执行 TypeScript 断言。
- `edit-multiple-matches.excerpt.ts` 来源：同文件第 329–340 行，名称 `should fail if text appears multiple times`。原文件为 `foo foo foo`，请求将 `foo` 换成 `bar`，原断言是调用拒绝且错误匹配 `Found 3 occurrences`。2026-11-04 首次实测暴露次数缺项；学习者补齐统计后适配验收通过，报告3处且文件不变，修复前失败单独保留。未原生执行TypeScript断言。
- `edit-lf-preserve.excerpt.ts` 来源：同文件第1373–1383行，名称 `should preserve LF line endings for LF files`。原文件为`first\nsecond\nthird\n`，将`second\n`替换为`REPLACED\n`，实际读回要求其余行、LF及末尾换行不变。D21第二任务保留这个字节约束，但改用配置文件、历史长读取尾部的批准值及三策略对比，明确属于Mini-Pi派生诊断；未原生执行TypeScript断言。
- 获取方式：`git show <固定提交>:<来源路径>`，保留原始 Git 文件内容。

原始参考样例保持不变。当前已创建 [Python 判定与日志适配](../../README.md)，通过现有 Mini-Pi Harness 执行离线排演和显式百炼真实调用；2026-11-03 一次真实调用已满足原样例五项判定。尚未运行 Pi 原生 TypeScript 评测器；该参考文件依赖 Pi 与 vitest-evals，不能直接作为 Python 测试执行。

第一个样例的原始输入为“What's the capital of France? Respond with only the city name.”。原始判定包括：去除首尾空白后输出为 `Paris`、错误列表为空、provider/model 与配置一致、总 token 用量大于 0；原 harness 禁用全部工具。

后续适配须逐项标记原输入、原判定和 Mini-Pi 接口差异。离线模拟只能证明执行与判定流程；真实 usage 等尚未验证时必须标明，不以模拟值或 0 代替真实证据，也不宣称已通过上游原生评测。

文件编辑用例已完成 Mini-Pi 工具级语义适配和实际运行。原输入为 `Hello, world!`，将唯一的 `world` 换成 `testing`；原断言检查成功文字、结构化 diff/patch 与应用补丁后的结果。Mini-Pi 返回错误字段和 diff 字符串，不含 Pi 的同名 details 对象，差异分别登记。额外磁盘文件检查标明为 Mini-Pi 补充检查，不声称上游这段原测试直接读回了文件。详见 [D20文件编辑说明](../../README.md)。

选择范围与适配安排见 [D20 学习安排](../../../local-learning/d20-handoff.md)。
