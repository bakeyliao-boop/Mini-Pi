# 记忆模块同步检查

日期：2026-10-23。分支：`codex/agent-memory`。

本页记录已验证的提交快照及实际推送回执。接续操作见[接续页](memory-resume.md)，全部文件见[提交范围](memory-sync-manifest.md)。

## 范围

54个文件：13个记忆源码、21个离线测试/合成夹具、3个示例/固定数据、10个学习记录/入口、4个学习图/提示词、3个协作规则/依赖说明/空凭据模板。

MEM-03与MEM-W已完成子段随本次快照保存；完整自动写入、真实候选提取/保真评测、MEM-04、丢失原计划的恢复及多操作原子提交仍未交付。下一课为统一写入执行入口与单次持久变更边界。D13-B原目录现场保留，主线仍12/30。

## 实际执行结果

| 检查 | 实际结果 |
| --- | --- |
| 当前工作区记忆专项 | 284项全部通过，0失败/错误/跳过 |
| 历史MEM-03组合反例迁移 | 去重为21项标准测试，21项实际通过；映射见[mem03验收](mem03-acceptance.md) |
| 暂存快照导出＋独立新虚拟环境，全量discover | 491项：489通过、2项旧D08符号链接权限跳过，0失败/错误 |
| 无私有配置的默认smoke预览 | 退出码0，未使用--live |
| 无私有配置的默认eval预览 | 退出码0，未使用--live |
| 差异/语法/入口链接/凭据排除 | 检查通过；模板key为空，无真实DB/Session或原始日志进入提交 |

独立验证使用Windows、Python 3.14.5、新venv及requirements.txt中的httpx==0.28.1，未启用系统site-packages。源码由Git暂存树导出，未携带.git元数据、.env、原始evidence或外部Pi/MemoryBear源码缓存；只使用随仓库的合成数据和公开测试证书。没有声称已经在第二台物理电脑或其它操作系统实际运行。

2项跳过为旧 `test_edit_file.EditPathTests.test_symlink_to_outside_workspace_is_rejected` 与 `test_edit_policy.EditPolicyTests.test_symbolic_link_to_outside_the_workspace_is_rejected`，原因均为WinError 1314。记忆专项没有跳过。

原始输出仅保存在本机忽略目录 `local-learning/evidence/memory-sync-prepare/`；这些日志不是新电脑运行测试的输入。验证过程中未新增外部模型调用，历史真实调用授权不延续为新机自动调用许可。

## 提交卫生

- 仅清理行尾空白与已确认不可达的旧占位；实际判断保持不变。旧MEM-01/02的Store核心另以AST核对。
- `.env`、真实Session/业务SQLite、原始运行证据、源码缓存和原目录D13-A/B代码均排除。新增SQL/JSON为合成旧格式兼容夹具。
- 远端分支与本地基线均核对为 `12a3477` 后准备此快照；不用force推送，不改其它分支。
- 中文提交说明：**归档MEM-03与MEM-W写入规划并补齐跨设备接续**。
- 用户已针对所展示54文件范围明确确认提交、推送。

## 实际推送回执

2026-10-23，代码提交 `b02a7d1b211c8db9e9ac4d4e2bb7c1405c04ccb0` 已成功推送至 `origin/codex/agent-memory`；随后用 `git ls-remote --heads` 独立核对远端分支提交一致，本地工作区干净。该提交的源码、测试、夹具与依赖和已验暂存树一致，测试后仅修改文档。

推送后仅在上述已确认范围的4份学习文档补记完成状态，以独立文档提交保存；不会改变已验代码快照。新电脑当前HEAD以拉取后 `git log -1 --oneline` 为准，代码验收对应 `b02a7d1`。
