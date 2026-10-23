# MEM-03 首版技术验收与冻结

2026-10-22：按用户确认的最小向量检索契约技术验收通过。此结论不代填学习者理解，不代表整个记忆系统完成。下一学习单元为MEM-W，之后MEM-04；原D13-B暂停和主线12/30不变。

## 已验收的行为

| 契约 | 实际证据 |
| --- | --- |
| 自然query、可信范围、条件和问题时间 | search及真实临时SQLite反例；不适用/撤回/他人记录不进入embedding，无候选零调用 |
| 来源、版本与并发复核 | await期间更新/撤回、历史版本区间、不可变来源和定义被一致改写、损坏数据明确失败；保留完整Entry |
| 向量空间与排序 | query/document端口、spec变化、错维/数量/索引/NaN/Inf/零向量拒绝；余弦、阈值包含、稳定降序和最终top_k |
| 真实适配与分批 | native协议、单问题返回、全量输入快照、10条分批及局部索引恢复；第二批失败无部分返回和第三批 |
| 客户端取消/超时/收尾 | 正式HTTPX与真实本地HTTPS socket；等头/等体取消或超时后观察断开，response/client关闭；重复取消不能打断未完成的清理；实际query和第二批document入口均验证 |
| 真实接口连通 | 阿里北京v4/1024两次实际请求，3向量、26 tokens，来源与版本完整返回 |
| 固定语义试点 | 3校准选阈值，冻结后3独立验收，全部无遗漏/额外ID；12次实际请求、20向量、219 tokens，无重试 |
| 成本口径 | 分请求类型、数量、token及准备/search/总耗时留存；人民币费用未核账，明确未知，不当零 |

试点参数为`min_score=0.5506252353514574`、`top_k=2`，只保存为该固定数据集的pilot配置，没有写全局默认。模型revision为客户端协议/预处理声明，不声称锁住供应商权重。

## 本轮最终回归与保全

397项标准仓库测试，加24项已完成阶段/不可变字段补充，共421项：419通过、2项原D08符号链接测试因Windows权限WinError1314跳过，0失败/错误。源码、示例、测试与fixture哈希前后一致；MEM-01/02五个原有store方法AST与提交0e6c7b6一致。原目录99个mini_pi/tests/examples冻结文件逐一与暂停清单核对一致。

本轮没有读取真实凭据或新增真实API调用。证据：`local-learning/evidence/mem03-final-acceptance-f423216d/`，含完整日志、verification.json和前后源码清单。真实调用沿用两轮已授权的冻结证据，不重复执行。

## 可复跑入口与交付边界

标准回归：`python -B -X utf8 -m unittest discover -s tests -v`。

下列是原技术收口时实际复跑的本机阶段脚本索引，保留于Git忽略的历史证据中：

- `mem03-dashscope-prepare-63cdabcc/verify_batch_stage.py`：5项单批核心与4项发送辅助。
- `mem03-dashscope-prepare-63cdabcc/verify_batch_http_core.py`：3项实际单批HTTPS成功/取消/超时。
- `mem03-dashscope-query-prepare-91024159/verify_query_stage.py`：4项实际问题入口。
- `mem03-dashscope-documents-prepare-b8b58d93/verify_documents_stage.py`：5项完整正文分批。
- `mem03-dashscope-documents-prepare-b8b58d93/verify_documents_http_core.py`：2项真实多批HTTPS。
- `mem03-recheck-prepare-5e3b65ef/verify_recheck_stage.py`仅选`RecheckStageTests.test_consistently_rewritten_immutable_fields_raise_explicit_data_error`；其它方法是历史占位阶段观察，不属于当前完整实现回归。

上述路径均相对`local-learning/evidence/`，仅是旧证据定位，不作为新电脑执行入口。2026-10-22跨电脑整理时，已将必要行为去重迁入标准tests：

| 可移植入口 | 用例数 |
| --- | --- |
| `tests/test_memory_dashscope_adapter.py` | 14 |
| `tests/test_memory_dashscope_http.py` | 6 |
| `tests/test_memory_search.py`新增不可变字段一致改写反例 | 1，含4个字段子场景 |

新增21项已实际运行通过，无跳过或外部模型请求；使用已有公开合成证书和本地HTTPS。历史24项中的3项由更强入口覆盖：直接发送辅助的成功和取消分别由实际单批核心成功/取消及公开query取消覆盖，mock的23条成功由真实本地HTTPS的10/10/3三批成功覆盖。未删除原始历史证据，也未把重复用例算作新增覆盖。

这些测试随标准discover运行，不依赖本机路径、原始执行日志或真实凭据。当前全仓库/干净副本的最终计数见[同步检查记录](memory-sync-checks.md)，不将历史421项与当前计数相加。真实阿里调用仅保留已授权历史摘要，不能据本地复跑声称重做在线语义试点；提交推送仍按具体范围授权。

## 非阻塞边界与记录纠正

原定生命周期条款要求取消/超时传到实际请求并核对关闭/停止边界；AGENTS.md明确允许真实受控本地请求。现有正式客户端与真实本地HTTPS证据已覆盖该条款，不需要将新的云端故障注入自动追加为门禁。证明范围是客户端停止等待、关闭连接、完成收尾与记录一致；不保证供应商停止计算、不计费，或硬实时截止。

先前进度记录把“未跑阿里取消/超时、未核账单”持续写成MEM-03未完成，范围表达过宽。本次明确纠正：这些是外部未声明保证和费用未知边界；费用契约本来就要求缺项标缺失。没有放宽客户端取消/清理的已选行为。

六案试点不是生产泛化或正式LongMemEval结果；没有生成答案，因此不证明回答/拒答正确。未实现MEM-W自动提取或MEM-04实际Context注入，不增加缓存、重排、独立向量库或新算法来收口。
