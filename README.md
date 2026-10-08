# Pi 学习与 Python 实现

通过阅读 Pi 的官方资料和源码，理解单 agent 的执行循环、工具调用、会话管理和上下文管理，再使用 Python 完成一个简化的 Mini-Pi，并加入 reviewer 子 agent。

学习路线和当前进度见 [Pi 阅读与 Python 实现路线](local-learning/pi-learning-roadmap.md)。其中包含 30 个步骤、每步的动作与验收标准，以及学习记录和第一版交付清单。

当前学习进度为 D01 待开始，代码实现尚未开始。后续进度以阅读文件中的总表为准。

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
