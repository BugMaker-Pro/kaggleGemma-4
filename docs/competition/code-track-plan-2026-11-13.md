# 代码赛道（主赛道）准备计划

日期：2026-11-13。依据：官方 `Evaluation` / `Model Selection, Budget, and Harness Rules` 页、`HARNESS_README.md`、本仓库 11-08 至 11-12 的主赛道记录。

## 结论先行

1. **最大的风险不是分数低，是一次正式提交都还没有。** 线上提交 0 次、确认集 119 任务未跑、正式 Docker 的排序器数值依赖未验证。先拿一次有效提交把流程、隐藏集规模和评分耗时钉死，再谈优化。
2. **真正的硬约束是 12 小时总预算，不是"多给点时间就好"。** 官方写明 12 小时要覆盖全部任务的 Stage 1（含沙箱搭建、不含补丁验证）。按 129 个任务、串行估算，每任务只剩约 5 分钟。之前 3/5 分钟的实验预算不是拍脑袋，是被这个上限逼出来的。
3. **唯一有数据支撑的增益杠杆是"在预算内完成一次编辑"。** 197 条轨迹里 49% 全程没有 `edit_file`/`write_file`，这些 run 解决数为 0；有编辑的 100 条里解决 38%。调排序器、加技能都属于次要项。

## 硬约束（2026-11-13 复核）

| 项 | 值 |
| --- | --- |
| Stage 1 总时长 | 12 小时，覆盖全部任务，含沙箱搭建，不含补丁验证 |
| 每任务预算 | 可选，写在 `submission.zip` 根目录的 `eval_config.yaml` |
| 每日提交 | 1 次；最终可指定 2 个 Final Submission |
| 公开任务 | 129 条；评测时替换为隐藏测试集，规模未公开 |
| 提交包 | 解包 < 3 GiB；单 skill ≤ 50 MiB；单模型（31B/12B/E4B/E2B 量化版） |
| 运行环境 | 4×L4（96 GB）、tp=4、`max_model_len=32768`、8k/16k 输出、沙箱 4 GiB / 2 vCPU |
| 截止 | 组队 11-25 23:59 UTC；最终提交 12-02 23:59 UTC（北京 12-03 07:59） |

**12 小时预算推算**：`129 × (T_agent + T_setup) ≤ 12h`。沙箱搭建按 60–90 秒估计，则 `T_agent` 只有 **4.3–5.3 分钟**。若官方 Stage 1 存在并发，可放宽，但并发数未知，第一次提交必须按串行兜底。

## 现状（截至 2026-11-13）

- 开发集 10 任务、5 分钟：baseline 2/10，ranker 3/10（n=10，不构成显著差异）。
- 54 任务 preloc 配对：baseline 11/54，ranker 10/54；79/108 报 session timeout。
- 60-call 对照（opt-02）：调用次数不是瓶颈，5 分钟墙钟才是；加调用只把"撞上限"换成"超时"。
- 5 分钟以后的效果没有数据：10 分钟方案（visible/runtime 三臂）只写了协议，因 GPU 配额耗尽没跑。
- kaggle 配额：11-11 报告耗尽；通常周六 00:00 UTC（北京周六 08:00）重置，需在 Kaggle 设置页确认。
- 官方提交入口的具体形态（zip 直传还是 notebook 重跑）尚未核验，第一次提交前要在 Submit 页面确认。

## 瓶颈（197 条轨迹的统计）

| 观察 | 数字 | 用途 |
| --- | --- | --- |
| 全程无编辑 | 97/197（49%），解决 0 | 强制早编辑的动机 |
| 有编辑的解决率 | 38/100 | 编辑是必要条件 |
| 首次编辑时间分桶 | 0–60s 10/23、60–120s 17/31、120–180s 7/27、>180s 4/18 | 相关性，不是因果 |
| 两阶段交接延迟 | 31–109 秒后才有首个修复动作，其中 30–50 秒是推理延迟 | 倾向单阶段 |
| 典型失败 | 22 次 read_file / 127 秒（rich_4079）；从不 `submit_patch` | 提示词纪律可修 |

## 策略

1. **先提交，再优化**：第一枪用最简包——无 skill、单阶段、官方 evidence 提示词加收尾纪律，`5 min / 60 calls / 80 turns / 120s` 单命令、8k 输出。目的不是分数，是验证 mechanics 与线上耗时。
2. **按 5 分钟标定智能体**：90 秒内完成首次编辑；最多读 2 个行区间；不在长测试上纠缠；第 4 分钟前 `submit_patch`（空 diff 也提交）。
3. **ranker 包作为第二枪**，前提是正式 Docker 里 numpy/torch/transformers/tokenizers 可用；否则不进正式包，避免整包失败。
4. **确认集（119）只用于最终配置的抽样验证**，不做逐臂调参；开发集 10 条已冻结，继续用配对设计。

## 排期

| 日期 | 事项 | 配额 |
| --- | --- | --- |
| 11-13 周五晚 | 冻结候选包；备好 10 任务演练 notebook；启动 2 臂 × 10 任务（已启动） | ~1h |
| 11-14 至 11-16 | 看抖动结果；只跑一个定向 1h run（单变量或确认集抽样），不跑满配额 | ≤1h |
| 11-17 至 11-20 | 第一次线上提交；按公开 LB 与提交耗时修 1–2 个问题 | 0（若为 Kaggle 重跑） |
| 11-21 至 11-25 | 确认集抽样（10–20 任务）定最终配置 | ≤1h |
| 11-26 至 11-30 | 最终提交 2 次 | 0 |
| 12-01 至 12-02 | 只用最后一次额度；不再改包，只做核对 | 0 |

**配额口径**：面板 `23:15 / 30 hrs` 是已用量，剩约 6h45m。官方 `Upgraded Accelerators` 页写明 **L4x4 按 2 倍速率扣配额**，单卡 L4 是否同样按 2 倍未写明；开发 run 用的是 `NvidiaL4`，实际扣费以面板为准。扣除本次 1h（若 2x 则 2h），本周只剩约 3–6h；上表按“最多 1–2 个 1h run + 1–2h buffer”重排，确认集抽样从 30–40 任务降到 10–20。**若按 Kaggle 的周配额口径在周六 00:00 UTC（北京周六 08:00）重置**，过点后回到 30h，排期可恢复原强度；以面板上的 “resets in …” 为准，不能只按已用量推断。

## 周六实验队列

同一批 10 个冻结开发任务（冻结划分只有 10 条，不能再扩）、同一 12B 模型与采样，配对运行；两臂都已带 `completion.md` 收尾纪律（`build_main_track_batch.py` 里 `completion_guardrails=True` 是固定行为）：

| 臂 | 变化 | 预算 |
| --- | --- | --- |
| A（对照） | 官方根提示词 baseline | 5 min / 60 calls / 80 turns |
| B（处理） | evidence 定位策略 | 5 min / 60 calls / 80 turns |

判读：以 `resolved` 为主，同时记录首次编辑时间、超时数、是否显式 `submit_patch`。n=10 只作方向判断，不写显著性。若要单独检验"收尾纪律"，需要先给构建器加 `--no-completion-guardrails` 开关，属于代码改动，排在这次之后。

## 立即可做（无需 GPU）

- [x] 冻结候选包，并核对：根目录 `agent.yaml`、单模型、扩展名白名单、< 3 GiB、skill ≤ 50 MiB、`!include` 深度。
- [x] 生成 10 任务演练 notebook（concurrency 3），确认 `eval_config` 真正生效。
- [ ] 复核正式 Docker 的排序器数值依赖（CPU 探针即可，先在本地镜像/环境对照）。
- [x] 提交形态已确认（2026-11-13）：纯 zip 直传，文件名必须恰好是 `submission.zip`，不需要 notebook 重跑。
- [ ] 确认官方提交（Kaggle 重跑）是否消耗本机 GPU 配额——若耗，则 6h45m 里必须再削一个 run。
- [x] 记录本周配额重置时间与可用时长。

## 执行记录

- 2026-11-13 约 20:10 启动 `yyyyhhhhwww/gemma4-development-batch-code-a11y-20261113`（kernelId 144792199）：10 个冻结开发任务 × baseline/evidence 两臂，5 min / 60 calls / 80 turns / 60s 单命令、并发 3、私有 NvidiaL4。10 个 `verification-gate-*.json` 从 `experiments/runs/main-track-canonical-preflight-20261108-v1/` 复制复用，四段环境 setup 代码哈希与 gate 完全一致，未重跑 CPU 对照。
- 本地启动脚本在沙箱下 schannel 报 `SEC_E_NO_CREDENTIALS`（PowerShell TLS 取不到系统证书）；同一路径用 Python `urllib` 正常。本次以 `danger-full-access` 放宽一次完成启动，不改会话权限模式。后续 Status/Fetch 同样需要这条路径或 Python 版封装。
- 2026-11-13 23:00 `code-free4`（kernelId 144809562，10 任务 × 15 min / 200 calls / 200 turns、并发 4、中性收尾提示词）完成：**5/10 resolved**。新增救援 `rich_4079`（54 calls / 906s，10 分钟档时是空跑），其余 4 个与 a12y 相同（fastapi_14463、rich_3882、requests_7433、requests_7502）。失败面：3 个撞 15 分钟上限（requests_7205 59 calls、fastapi_13713 46 calls、httpx_3672 75 calls），2 个非超时失败——`rich_3942` 19 calls / 518s 只写了 344 字符补丁，`fastapi_15661` 56 calls 写出 **661 KB 补丁**（大量重写文件）后测试 exit 2。成功补丁都在 0.6–1.9 KB，说明小步编辑才是有效路径，大重写是负向信号。
- 2026-11-13 23:00 **完成第一次线上提交**（ref 58312803，团队 bugmaker）：`submission.zip` 即 a12y 包（evidence 提示词 v2，5 min / 60 calls / 80 turns），SHA256 `4bd54a9f…22dca735`。机制已钉死：**文件必须恰好叫 `submission.zip`**（否则 400 `Submission files must be named "submission.zip"`）；纯 zip 直传可用，走 `StartSubmissionUpload → PUT createUrl → CreateSubmission`，不需要 notebook 重跑；`maxDailySubmissions=1`，提交后 `GetSubmissionLimits` 返回 `numToday=1`。提交接口日志：`.cache/main-track/submit_main_track.py`、状态：`.cache/main-track/submission_status.py`（传 ref 可查 episodes）。

## 风险与未知

- 隐藏测试集规模未知：12 小时按串行 129 任务估算，若隐藏集更大，需要压低每任务预算。
- 官方 Stage 1 并发数未知：第一次提交按串行兜底，宁可浪费预算也不要把后面的任务饿死。
- 本地验证与正式环境存在差异（Requests 的 src 布局、pytest 插件）：所有 patch 结论以官方 harness 为准。
- 排序器 INT8 量化、lossless 压缩只在本地 CPU 探针验证过，尚未在正式 4×L4 + vLLM 组合上跑过。
- 开发机加速器：官方评分是 4×L4；`gemma-4-12b-it-qat-w4a16-ct` 是 compressed-tensors W4A16，T4（SM75）缺少 Marlin 所需算力且不支持 bf16，速度慢或直接起不来。开发跑也用官方 starter 的 `NvidiaL4`，不要用 T4 x2 测时间预算。
- 配额：2026-11-13 用户报告面板显示 `23:15 / 30 hrs`，口径是**已用 23h15m**，剩约 **6h45m**。一次 10 任务 × 2 臂、5 分钟、并发 3 的演练约消耗 1 小时；本周最多再排 2–3 个 1 小时 run，必须留 1–2 小时 buffer 给失败重跑。
