# D17 学习进度与续学交接

> **2026-10-30 真实摘要验证：**用户授权一次调用，百炼 `qwen3.8-flash` 对合成登录排查历史生成的摘要保留了目标、约束、修改文件、失败测试和待办；输入 157、输出 97 tokens，摘要进入后续模拟回答请求，原始历史保留。完整记录见 [真实摘要验证记录](evidence/d17-real-summary-20261030/README.md)。这是单样本，未调用真实回答模型；D17 仍待整体理解与验收确认。

> **2026-10-30 模拟验证：**下方早期状态保留为历史。已接通摘要保存与模拟继续回答，模拟模型的成功、失败、窗口和预算验证及原始记录见 [D17 模拟验证记录](evidence/d17-verification-20261030/README.md)。85 项相关测试通过；该模拟场景的 usage 不可用，预设摘要不能证明真实模型质量。后续一次真实摘要调用及实际 usage 见上方记录。D17 尚未宣布完成，CLI 未默认启用摘要。`loop.py` 曾出现回退，模拟验证期间前后指纹一致，但回退原因尚未查明。

更新时间：2026-10-28（北京时间）。本文件记录进行中的工作，不代表 D17 已完成或验收。

## 学习约定

遵循仓库根目录 `AGENTS.md`：先用具体例子解释完整行为和 Pi 对照，再分段由学习者手敲核心；助手准备辅助代码、测试，以及按用户授权修正的代码。讲解简洁，不以测试通过代替理解确认。

## 当前理解与源码依据

- D17 是将较早的会话过程压缩为摘要、保留近期原文和原始会话记录，并在失败或超限时安全停止。
- 摘要从会话记录选择；本轮临时参考资料保持独立，摘要完成后才加入请求。角色同为 `user` 不代表来源相同。已加入会话记录的资料是否参与摘要，取决于记录与压缩范围，不能笼统地排除所有资料。
- 固定 Pi 学习基准 `7f9e1198f2f7a8cf5ea18d5010ba081d4d60c333`；上次核对上游 main 为 `973b74c55fcf096ad5976f8d8850c147ee2e62d4`，日期 2026-10-27。来源为 `packages/coding-agent/src/core/compaction/compaction.ts` 和 `session-manager.ts`；以后进入新章节时按 AGENTS 再核对最新上游。
- Pi 根据会话路径选择压缩范围并记录摘要及保留起点，保留原始记录；Pi 支持对较长的同一轮进行特定切分。Mini-Pi 首版拟采用更保守的完整工具组切点、每次触发最多尝试一次摘要，这些是 Mini-Pi 的选择。

## 已实现与验证范围

- `mini_pi/memory/context.py` 可准备参考资料、将资料加入请求；`reference_only=True` 只返回资料，默认路径保留旧行为。`mini_pi/memory/request_context.py` 已透传该开关。只返回资料时绕过完整请求字符检查，不可直接当成完整请求发送。
- `mini_pi/context.py` 已定义 `ContextParts`、`build_separate_context` 和 `check_request_chars`。分开组装的辅助函数先把历史交给构建器，再加入参考资料；字符检查函数尚未接入实际请求。
- 离线测试 `tests/test_context_parts.py`、`tests/test_memory_context.py`、`tests/test_memory_request_context.py`、`tests/test_memory_read_output_integration.py` 覆盖当前独立函数、新旧记忆准备模式及现有 D16 联合路径。具体通过结果以交接时实际运行记录为准。
- 当前 `ContextProvider.generate` **尚未接收 `ContextParts`**，外层 `run_loop`/Harness 也未接入分开流程；上一轮已经讲解待手敲的接线，但当前文件尚未实施。摘要、安全切点、摘要保存/恢复及摘要预算都尚未实现；不能把来源分离或 D17 标记为完成。

## 下一步

先从 `mini_pi/context.py` 的 `ContextProvider.generate` 接线继续：保持原有列表路径，同时为 `ContextParts` 新路径要求明确的完整请求字符上限和窗口预算，让构建器只处理历史、之后加入资料，并在发送前检查配对、字符上限、窗口及同一次运行的取消/截止时间。给学习者按段讲解并核对代码，再用反例验证；这一步还不能直接启用 `reference_only=True` 的外层调用。

再接通外层 `run_loop`/Harness：确保只取资料的模式不会把资料列表误当完整请求；保留会话历史、各项失败状态、字符与窗口门禁，以及现有 D16 路径。之后才推进完整工具组切点、摘要生成与失败、摘要记录及跨运行恢复、再次压缩、真实消耗/调用次数与时间预算。现有 Provider 只返回 Message，不提供实际 token usage；不能把估算当真实消耗。

## Mac 上的文件边界

- `local-learning/evidence/` 被 `.gitignore` 排除，Git 拉取不会带上这些本地证据；不能声称其已在新设备可用。
- `pi-textbook/` 是独立仓库，不是 Mini-Pi 的普通子目录或已配置的子模块。此设备所见为 `https://github.com/hahhforest/pi-textbook.git` 的 `main`，本地提交 `20dd3a7`，工作区干净。需要时在 Mac 上单独克隆，并核对对应提交。
