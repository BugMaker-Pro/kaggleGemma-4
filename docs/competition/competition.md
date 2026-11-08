# 比赛与执行计划

更新依据：2026-11-08 读取的官方 API、运行说明及 Getting Started Notebook v3。本文统一原先分散的比赛说明、数据清单、主赛道计划和执行记录。

## 两条赛道

| 项目 | 主赛道 | 论文赛道 |
| --- | --- | --- |
| 提交 | agent 的 submission.zip，由官方运行并验证补丁 | Kaggle Writeup，可附公开 PDF |
| 主要评价 | 实际修复成功率 | 新颖性、质量与泛化、相关性、可验证性、清晰度 |
| 北京时间截止 | 2026-12-03 07:59（11 月 8 日 API 核实） | 2026-11-13 07:59（10 月 20 日规则存档） |
| 当前重点 | 跑通官方流程，再比较定位策略的修复收益 | 收紧主线、补强消融、核对最终投稿 |

主赛道每日最多提交 1 次。用户已确认加入，官方文件已成功下载。论文赛道的完整原文另存于[规则摘录](kaggle-paper-track-raw.md)，投稿材料状态见[论文状态](../status.md)。

## 主赛道技术边界

每包统一选择一种官方 Gemma 4 量化模型：31B、12B、E4B 或 E2B。顶层使用声明式 agent.yaml，支持已注册工具及沙箱 skill 脚本；不是任意 Python agent 入口。解压包小于 3 GiB，单 skill 目录上限 50 MiB，上下文上限 32,768 token。具体模型名称、工具和运行命令见 [agent 使用说明](../../agent/README.md)。

完整学习排序器仍需确认权重、依赖、内存和运行预算。当前提示词策略测试不等于部署了论文的 44.7% 融合排序器。

<a id="data-assets"></a>
## 官方数据

官方清单 524 个文件，公开任务 129 条：fastapi 67、requests 13、rich 48、httpx 1。

| 内容 | 用途 |
| --- | --- |
| tasks.jsonl | issue、仓库与提交版本；开发数据另含参考补丁和验证补丁 |
| snapshots/ | 对应任务的修复前仓库 |
| graphs/、embeddings/ | 官方代码图与符号向量 |
| wheels/、docker/、sandbox/ | 离线依赖及环境设置 |
| sample_submission/ | 配置与提示词样例 |
| HARNESS_README.md | 提交、运行、工具和验证合约 |

本机资料位于 `.cache/main-track/official/`。下载脚本会处理官方 HTTP 302 跳转，不向存储域转发 Kaggle 凭据。参考补丁仅用于评测，不得提供给定位或修复 agent。旧数据页中的菜单文本、参与人数和社区问题统计不再重复保留。

<a id="main-track-plan"></a>
## 配对评测协议


### 实验臂


所有比较使用相同官方模型、可用工具、采样设置、任务快照、修复与验证流程。主要差异只在定位阶段。准备的 Markdown 片段位于 `agent/prompts/localization/`，待取得官方提示词后替换同一位置，不能直接当成提交配置。

| 实验臂 | 定位策略 | 作用 |
| --- | --- | --- |
| A | 官方根提示词，统一为 12B、无 adapter、单 agent | 获取匹配配置的参照；不是未经修改的官方样例成绩 |
| B | 精确 issue 证据优先；保留有依据的候选；读取目标定义及必要上下文 | 检验候选组织和证据策略 |
| C | B 加按需一跳图查询；图仅提供补充线索，读取代码验证后才替换候选 | 检验图策略的边际价值 |
| D（有条件） | 完整学习排序器；另做移除图特征并重训的配对版本 | 在规则与资源允许时验证算法本身 |

B 与 C 的非定位流程保持一致。A→B 是一组定位策略的整体效果，不能归因为某一个提示句。只有 B→C 可以作为所定义图策略的边际比较；即便可用工具相同，也要记录实际调用差异。

## 数据划分与预先冻结

取得 tasks.jsonl 后，先按仓库和任务 ID hash 划分工程开发集和确认集，保存完整任务 ID、种子、文件哈希。划分不读取 patch、test_patch、历史成功率或检索收益。初期开发集可取每仓库最多 3 个任务，具体数量由官方数据确认；余下任务冻结为确认集。冒烟任务与调过提示词的任务只属于开发集。

先用单任务检查启动、模型调用、修改、补丁提取和验证链路。再在开发集检查异常与资源开销。修复实现问题后冻结 B/C 提示词与所有配置；确认集上不得根据中途成绩挑样本、反复改提示词或只重跑失败臂。若资源仅够一个确认比较，预先选择 B 对 A；C 留在开发阶段并标为探索性，不事后按哪个显著选择主比较。

若完整执行 A/B/C，预定主比较为 B-A、C-B 两项，使用 Holm 校正。预定主要效应为逐任务 resolved 比例差；报告配对胜/负和配对二元检验。分仓库报告结果；仓库很少时不把仓库 bootstrap 或大量任务当成强泛化证据。若推理有随机性且预算允许，使用预先固定的匹配运行种子，并在任务内汇总，不能将重复调用当作独立任务。

## 什么才算有用

主要结果来自官方验证的 resolved，分母是事先冻结的全部任务，包括没有可评分符号的任务。候选召回只作机制分析，不能代替修复结果。

同时记录：总运行时间、定位时间、模型 token 用量（仅在 harness 确实提供时）、工具调用数、读取字符量、超时、无效补丁、验证错误、补丁哈希和轨迹路径。未知用量记为缺失，不能写成 0。基础设施错误单列，并按预先约定的相同策略处理各臂，不能选择性删除。

结果解释规则：

- resolved 稳定提高且成本可承受：支持该配置有实际价值；仍限定于已测任务与预算。
- resolved 接近但耗时下降：需要预先定义可接受的修复率损失并有足够证据，不能用“不显著”宣称等效或无损。
- 只有 recall 提高：仍不能证明修复收益。
- 图臂不如 B：部署时保留 B，论文如实报告图干预的实际损失。
- 少量任务 1 胜 0 负：只视为方向性案例，不作为稳定提升或获奖依据。

## 提交步骤与验收

1. 获取并保存官方说明和样例内容及哈希。
2. 校准最小 agent 包，运行官方配置校验器（若提供）。
3. 用打包后的同一个 zip 完成至少一个开发任务的修复与验证；保存正式评分日志。
4. 冻结开发/确认划分与对照配置，完成可负担的配对评测。
5. 核对包内路径、依赖、模型/adapter 政策、体积和无凭据/无标签污染；打包范围以官方规则为准。
6. 提交已验证的候选包，记录 submission ID、包哈希和线上结果。每天只有一次额度，先完成本地校验，不用线上提交调试配置格式。

<a id="main-track-status"></a>
## 主赛道执行记录

已冻结 10 条开发任务和 119 条确认任务；首个工程流程测试为开发集 requests_7433。确认集包含 fastapi 64、requests 10、rich 45 条；httpx 的唯一任务用于开发。以下为最近记录，实时状态以 Notebook 查询为准。

### 云端运行


| 运行 | Kaggle Notebook | 状态 |
| --- | --- | --- |
| v1 | yyyyhhhhwww/gemma4-localization-smoke-20261108 | 安装失败：默认 Python 3.13 无法安装官方 cp312 wheel；未开始推理 |
| v2 | yyyyhhhhwww/gemma4-localization-smoke-20261108-v2 | 已启动，固定到官方 Getting Started 使用的镜像；结果待取回 |

v2 镜像：`gcr.io/kaggle-private-byod/python@sha256:37c64f7dd9c54116ecd1bcc88817c5469b88387388fade02bfa8bf3fc647d461`。Notebook 私有、离线、NvidiaL4、最长 3600 秒；仅挂载官方 wheelhouse、公开比赛数据和 12B 模型。未创建比赛提交。

## 本地产物

- `.cache/main-track/build-v2/manifest.json`：任务划分、官方运行说明 SHA256、三个包及其各文件 SHA256。
- `.cache/main-track/build-v2/{baseline,evidence,evidence_graph}_submission.zip`：待实际运行验证的包。
- `.cache/main-track/build-v2/smoke.ipynb`：基于官方 Notebook 的三个实验臂流程测试。
- `.cache/main-track/build-v2/kernel-launch.json`：私有 Notebook 创建回执。
- `.cache/main-track/build-v2/kernel-status.json` / `kernel.log`：通过状态工具更新。

真实修复结果未取得前，不报告 resolved 提升，也不将生成 ZIP 等同于已通过官方运行验证。流程测试只排查工程问题，之后才在冻结确认集上评测方法。

### 2026-11-08：已取回首轮结果与环境正反对照

实际运行包的 12 个文件、三个 ZIP 内容及轨迹提示词完成 27 项核对，无偏离。原始数据已从缓存复制到固定位置：`experiments/runs/main-track-smoke-20261108-v2/`。

| 配置 | harness resolved | 计费工具调用 | 首次修改 | 实际图调用 | 显式提交 |
| --- | --- | --- | --- | --- | --- |
| 官方提示词基线 | false | 17 | 20.2 秒 | 0 | 是 |
| 证据优先 | false | 30 | 20.8 秒 | 0 | 否 |
| 证据＋图策略 | false | 30 | 20.7 秒 | 0 | 否 |

三者均很快定位并修改同一目标函数。证据与图策略在后续搜索、构造复现脚本上用尽预算；图策略未调用图工具，不能从本例推断图方法效用。计费工具数与轨迹中的全部调用数不同：轨迹包含免费提交和被预算拒绝的调用。

首版 Notebook 沿用官方逐任务示例，未调用 `append_task_result`，因此没有保留完整 agent patch 与 Phase 2 输出；不能从补丁哈希反推出完整补丁。已修复构建器，后续运行保存完整补丁、验证日志与逐任务结果。

独立 CPU 正反对照使用原样官方验证器和相同开发任务，分别输入空补丁、参考补丁，以及从基线轨迹重建的单次编辑差异。三者均失败；参考补丁报告 142 passed、195 errors，主要错误为 `recursive dependency involving fixture 'httpbin' detected`。本地环境缺失或未注册提供 httpbin 的测试插件，导致参考补丁也无法通过，因此首轮 false 不能直接归因于方法或补丁逻辑。

正反对照位于 `experiments/runs/main-track-verification-20261108-v1/`。重建的单次编辑明确标为 edit-only，不冒充原 agent 的完整补丁；参考补丁只提供给无模型的验证控制，不输入 agent。

当前正在单独的私有 CPU Notebook 准备 pytest-httpbin 依赖，然后在独立离线环境重复同样正反对照。保持 pytest 版本、测试目标和官方验证器不变，不跳过失败测试。修复本地依赖后的结果也要与未经修改的比赛评分区分。确认参考补丁通过、空补丁失败后，才继续开发集方法测试。

收尾指令修订已准备在 `agent/prompts/completion.md`，统一用于全部实验臂：限制重复测试搜索、复现脚本放 /tmp、保留最后五次调用用于检查与显式提交。它来自开发轨迹诊断，不包含具体任务答案；尚未确认带来收益。构建器通过 `--completion-guardrails` 显式启用，保持模型、采样和预算一致。

工程任务切换只允许 `--engineering-task-id` 指定冻结开发集内的任务，禁止以流程调试名义读取确认集。为区分 Requests 特有环境问题，另对原冻结开发顺序中的首个 Rich 任务 `rich_3942` 启动无模型、原样环境的空补丁/参考补丁检查；Requests 的失败继续完整记录。

### 验证环境检查的后续结果

补齐真实测试插件后，Requests 参考补丁仍有 4 项失败。完整测试堆栈显示从 `/usr/local/lib/python3.12/dist-packages/requests/` 导入了宿主包，而非任务快照下的 src/requests。官方 swegemma 0.2.11 的本地 SubprocessManager 路径跳过了 editable 安装和测试依赖设置，这与 src 布局的导入问题一致。当前用第三组 CPU 对照补上 workspace/src 的 PYTHONPATH，并断言实际导入路径位于快照内；不修改测试和评分代码，结果仍单列为本地环境修正实验。

Rich 开发任务 `rich_3942` 在未经修改的官方环境中通过正反对照：空补丁失败（exit 1），参考补丁通过（8 passed，exit 0）。完整产物保存于 `experiments/runs/main-track-rich-preflight-20261108-v1/`。已在同一环境启动匹配的三组 12B 模型流程测试，全部统一加入通用收尾指令；仍只有一个开发任务，不代表总体方法收益。

模型试跑入口现在要求保存的验证门槛通过，并核对任务 ID、镜像、依赖来源和环境设置代码哈希。参考补丁不能通过时，不继续消耗 GPU 来比较该环境下的方案。

工具入口：

```powershell
.venv/Scripts/python.exe tools/audit_main_track.py --run-dir experiments/runs/main-track-smoke-20261108-v2
.venv/Scripts/python.exe tools/audit_main_track.py --verification-dir .cache/main-track/verification-rich-v1  # 已归档删除，见 docs/cleanup-20261108.md
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_main_track_notebook.ps1 -Action Status -BuildDirectory .cache/main-track/build-rich-v1
```

准备与审计测试目前 10 项通过。日志保存修复不会改变原三个 agent 包；通用收尾指令是另一个显式开发修订，不能与首轮直接合并成同一配置的重复实验。

### Requests 本地验证已恢复

第三组 CPU 对照完成：空补丁只在目标回归测试失败（336 passed、1 failed）；参考补丁通过（337 passed）；从基线轨迹重建的单次代码编辑也通过（337 passed）。三个 sandbox 的实际 requests 导入路径均经断言检查，位于对应快照的 workspace/src/requests。

这证明重建的代码编辑能通过修复后的本地验证；首轮完整 agent 补丁没有保存，不能据此回填原始 resolved 为 true。保留首轮 false 和全部环境对照，避免混淆原实验与事后重建。完整材料：`experiments/runs/main-track-verification-20261108-v3/`。

已准备使用同一依赖及导入路径修正、统一收尾指令的 Requests 重跑包（`.cache/main-track/build-requests-ready/`），通过环境设置哈希核对，尚未启动新的 GPU 重跑。当前唯一在运行的模型任务是 Rich 三组开发试跑；两组环境 CPU 对照均已结束。

### 最新状态：Rich 已结束，修正环境下的 Requests 正在复跑

Rich `rich_3942` 三组模型运行已结束；31 项产物核对通过。任务 issue 仅为“Update to markdown styles / Updates to Markdown styling”，具体样式要求未说明。保留这一任务限制，不依据失败删除样本。

| 配置 | 结果 | 工具调用 | 失败原因 | 图调用 |
| --- | --- | --- | --- | --- |
| 官方提示词＋共用收尾指令 | 未修复，空补丁 | 20 | 3 分钟超时 | 0 |
| 证据优先＋共用收尾指令 | 未修复，空补丁 | 14 | 输入超过约 16K，叠加 16,384 输出预留超出 32K | 0 |
| 证据＋图策略＋共用收尾指令 | 未修复，358 字符补丁 | 18 | 3 分钟超时；补丁测试 6 failed / 2 passed | 0 |

完整记录：`experiments/runs/main-track-rich-smoke-20261108-v1/`。本例图策略没有调用图，不能归因图信号有效或无效。该轮预算及输出设置保持原样，错误结果不回写。

下一轮已实际启动：私有 Notebook `yyyyhhhhwww/gemma4-localization-smoke-20261108-requests-ready`，任务仍为开发集 requests_7433。三组均使用修正且通过正反对照的本地环境、相同收尾指令、12B 模型、3 分钟／30 次工具调用，输出预留统一降至 8,192（thinking budget 4,096 不变）。环境设置代码哈希与正反对照相符；正式测试、评分和确认集均未修改。

运行材料：`.cache/main-track/build-requests-ready/`。本轮尚待完成，不提前报告修复收益；不会把开发集上的修订后结果当作独立验证。当前没有创建比赛提交。准备和审计测试 11 项通过，论文出版检查仍通过，正文未因这些工程试跑改写。

### 2026-11-08：修复通过、开发环境复核与并发试跑

修正环境下的 Requests 三组试跑已全部结束，三组均通过官方测试（337 passed）。完整包和补丁核对 33 项通过，保存于 `experiments/runs/main-track-requests-repaired-20261108-v1/`。

| 配置 | resolved | 工具调用 | 补丁字符 | 首次修改 | 显式提交 |
| --- | --- | --- | --- | --- | --- |
| 基线 | true | 30 | 1,779 | 38.7 秒 | 否 |
| 证据优先 | true | 30 | 584 | 28.7 秒 | 否 |
| 证据＋图策略 | true | 30 | 584 | 42.6 秒 | 否 |

三组均未调用图工具，且都用完预算后由 harness 自动提取补丁，不能称为某种策略胜出。基线额外生成了复现文件；正式提交前仍需改善最小补丁与收尾纪律。

剩余 8 个开发任务的 CPU 正反对照已完成，最初 7 个通过；fastapi_13713 因缺少 dirty_equals 失败。单独离线补齐真实 dirty-equals 0.11 后，该任务也满足空补丁失败、参考补丁通过。原始失败与修正结果分别保留于 `main-track-development-preflight-20261108-v1/`、`main-track-fastapi-preflight-20261108-v2/`。

两任务并发试跑使用 rich_4079、rich_3882，同一模型、基线提示词和预算，先顺序再并发。顺序 365.93 秒，并发 181.02 秒，约 2.02×；但两轮均 0/2 且触及超时，因此只说明并发机制正常，不能据此保证有效修复吞吐翻倍。固定执行顺序和共享缓存也限制比较解释。完整产物在 `experiments/runs/main-track-throughput-20261108-v1/`，16 项产物核对通过。

批量开发评测已准备，统一依赖、源码导入路径、12B、8,192 输出预留、3 分钟及 30 工具调用，采用两任务并发。分为非 Requests 的 7 个任务和 Requests 的 3 个任务，共 30 次模型修复。先对合并后的同一环境复核全部 10 个任务，门槛通过后才启动。确认集 119 个任务仍未开始。

论文线同时完成 2,232 任务强融合排序器的图特征消融：44.70% 对 43.04%，增量 +1.66 点，独立审计 8,949 项通过。已纳入 2,915 词的新版稿件和 PDF，尚未替换线上 Writeup。

### 当前批量评测已启动

合并后的同一离线环境复核已完成：10 个开发任务的空补丁全部失败、参考补丁全部通过，20 个对照结果及每任务门槛已审计。固定材料在 `experiments/runs/main-track-canonical-preflight-20261108-v1/`。

两批 GPU 评测采用完全相同的模型、提示词版本、采样、预算和环境代码；任务仍来自原冻结开发集，没有使用确认集：

- `yyyyhhhhwww/gemma4-development-batch-20261108-nonrequests-v1`：3 个 Rich、1 个 HTTPX、3 个 FastAPI，共 7×3=21 次。
- `yyyyhhhhwww/gemma4-development-batch-20261108-requests-v1`：3 个 Requests，共 3×3=9 次。

每批共享一份 12B 模型服务，两个任务并发，最长 1 小时。调用官方 Evaluator.run 保存逐任务完整结果、补丁、验证日志和轨迹；失败任务保留，不因失败改换样本。跑完使用 `tools/audit_main_track.py --batch-dir <本地运行目录>` 统一检查。

本轮是开发评测，结果用于决定部署和后续固定方案，不能作为未见测试集成绩。确认集 119 个任务尚未开始，比赛榜单尚未提交。当前新增准备与审计测试共 15 项通过；论文数字审计与出版检查通过。

### 完整学习排序器接入（进行中）

用户要求实际接入论文算法，已实现运行时链路：原始 issue＋当前源码 → AST 图 → BM25 前 200 → 16 特征＋本地 BGE 编码 → 学习排序前十。推理不读取参考补丁或金标；部署排序器在 2,189 条历史任务上训练，排除全部比赛仓库。

单 skill 受 50 MiB 限制，且官方 ADK 目录加载器跳过二进制资源。当前部署版采用按行 INT8 编码器和无损压缩排序树，共约 39.4 MiB。它不同于论文原始浮点编码器和两折估计；一个历史样本前十排名一致只作兼容性检查，不宣称量化无损。

官方 `RunSkillScriptTool`＋`AdkSandboxCodeExecutor` 离线 CPU 验证成功：requests_7433 的 200 候选完成 full 排序，目标 prepare_body 位列第一，仓库未修改，耗时 80.6 秒。固定产物：`experiments/runs/main-track-ranker-tool-20261108-v1/`；可构建的源文件与说明在 `agent/ranker/`，完整 ZIP 与私有数据集回执在 `artifacts/ranker-agent-v1/`。

已启动私有离线 GPU Notebook `yyyyhhhhwww/gemma4-full-ranker-integration-20261108-v1`，将真实 ranker 调用与相同 12B、3 分钟、30 次工具调用、120 秒单命令限制的证据基线比较。检索计算计入总预算，后续须核对实际调用、原始 issue 完整性、full 模式结果和修复测试。

正式竞赛 Docker 的 numpy/torch/transformers/tokenizers 可用性尚未验证。当前只证明官方接口在本地 subprocess 后端可执行，不把它表述为已通过正式评分环境或已经提高修复率。没有提交比赛榜单，119 个确认任务未运行。

### 30 次提示词策略开发评测已结束

两批结果均已完成，168 项包／任务／补丁核对通过。合并 10 个冻结开发任务：baseline 1/10、evidence 2/10、evidence_graph 1/10；三组全部没有调用图工具。额外成功来自 evidence 的 rich_3882；共同成功为 requests_7433。这是开发集上的小样本描述，不作显著性或泛化主张，也不等同于完整排序器效果。

固定数据保存在 `main-track-development-nonrequests-20261108-v1/` 与 `main-track-development-requests-20261108-v1/`。完整 ranker 的 agent 对照另行执行，必须以实际 skill 调用、完整 issue 输入、full 排名输出和修复验证共同确认接入成功。


### 完整排序器第一轮轨迹审计：模型跳过工具

`gemma4-full-ranker-integration-20261108-v1` 已完成，66 项产物核对通过。两组 requests_7433 均通过 337 个验证测试；但 ranker 组实际 `run_skill_script` 调用为零，因此 `integration_executed=false`。模型跳过了提示词要求，直接搜索源码；该结果不能归因于完整排序器。ranker 补丁还夹带了 `reproduce_issue.py`，会话触及 3 分钟时限，由评测器提取补丁后验证。

原始轨迹、补丁、测试日志、实际运行包与哈希索引保留于 `experiments/runs/main-track-ranker-agent-20261108-v1/`，不覆写或隐藏这个未接入的结果。

修正版 v2 使用官方声明式 SequentialAgent：仅能调用 ranker 技能的定位阶段先执行，再由同一 Gemma 模型的修复阶段接收定位报告。两个阶段共享原来的 3 分钟、30 次工具调用预算。v2 为单臂接入验证，不重跑已完成的基线，也不构成新的同步效果对照。模型权重与检索脚本保持同一已验证数据集，仅覆盖工作流配置和提示词。审计分别记录完全相同的 issue 与仅 CRLF/LF 换行不同的完整 issue，任何文字改写都不能被计作原始问题成功调用。

### 完整排序器第二轮：真实接入通过

`gemma4-full-ranker-integration-20261108-v2` 已完成，59 项产物核对通过。定位阶段实际调用一次 `run_skill_script`，返回 `status=ok, mode=full`，对 200 个候选完成排序，第一名为 `src.requests.models.PreparedRequest.prepare_body`。脚本内部耗时 27.534 秒，轨迹记录的工具往返约 29.673 秒；这与独立 CPU 探针的 80.6 秒属于不同运行环境，不视为算法提速对照。

调用包含全部原始正文与代码；8 处 CRLF 被转换为 LF，并新增一个末尾换行。原始字节一致检查仍为 false；单独的文本等价检查通过，仅允许换行编码及最多一个末尾换行变化。没有把文字改写或摘要认作原始问题。

同一模型的修复阶段接收前三位定位报告，修改 `src/requests/models.py`，显式提交补丁，337 个测试通过。临时复现文件在提交前移除，最终补丁仅含源码修改。评测器计数 15 次工具调用；完整轨迹还包含技能发现、加载等不计费调用，两者不能混用。该单任务证明接入成功，不能证明总体修复率改善。

固定产物在 `experiments/runs/main-track-ranker-agent-20261108-v2/`；可重建的分阶段实验包为 `artifacts/ranker-agent-v2/`，运行文件哈希与本轮远端包一致。它仍是 INT8 部署变体，正式 Docker 的数值依赖和额外编码器最终参赛适用性尚未确认。

已启动 `yyyyhhhhwww/gemma4-ranker-development-20261108-v1`，对原冻结开发集 10 个任务使用完全相同的已审计 agent、3 分钟和 30 次工具预算、两任务并发。该轮是开发评测；119 个确认任务保持未使用。

### 2026-11-08 当日收尾与接续

用户决定让实验继续在 Kaggle 后台运行，先结束今天的本地工作。最后查询时以下两组均为 RUNNING；没有据此填写最终分数，也没有将后台作业标成完成。

| 作业 | Notebook | Kernel ID | 本地目录 |
| --- | --- | --- | --- |
| 完整方法，10 任务 | `yyyyhhhhwww/gemma4-ranker-development-20261108-v1` | 143378981 | `.cache/main-track/ranker-development-v1` |
| 匹配证据基线，10 任务 | `yyyyhhhhwww/gemma4-development-batch-20261108-matched-v2` | 143380260 | `.cache/main-track/ranker-matched-control-v2` |

本轮收尾前的重要开发决策与修复：

1. 第一轮仅挂载技能时模型没有调用它，保留 `integration_executed=false`，没有将成功补丁归因于算法。
2. 改成声明式 SequentialAgent：定位阶段只提供技能工具，输出报告后交给同模型的修复阶段；时间与调用预算由整个会话共享。第二轮实际调用及补丁验证通过。
3. 输入保真审计保留原始字节一致检查；另列只允许 CRLF/LF 和最多一个末尾换行变化的文本等价检查。第二轮属于文本等价、字节不一致，正文和代码未改写。
4. 旧 30 次提示词评测使用 60 秒单命令上限，新完整方法使用 120 秒，因此新增同为 120 秒的证据基线；没有直接把旧结果当作预算匹配的对照。
5. 单独运行 evidence 时，旧 Notebook 初始化硬编码了 baseline 目录，导致模型发现阶段失败。已改为选择实际存在的首个实验臂，并增加执行 Notebook 物化代码的回归测试。失败记录在 `experiments/runs/main-track-ranker-control-startup-failure-20261108-v1/`，不计为 10 任务修复结果。
6. Kaggle 返回的实际 slug 可能与请求值不同，状态和下载操作改用启动回执中的 ref；已有启动回执的目录拒绝重复启动。新增优先取回小体积证据的 `-EvidenceOnly` 选项，并关闭 PowerShell 下载进度渲染。
7. `tools/compare_ranker_development.py` 检查同一冻结任务集、模型、采样、预算、并发和参考对照，逐题汇总两组结果及实际 full 调用。相关测试共 26 项通过；PowerShell 语法检查通过。

已完成的 CPU 探针、未调用技能的第一轮、成功接入的第二轮和基线启动失败均有独立目录与哈希索引。分阶段实验包 `artifacts/ranker-agent-v2/` 的运行文件哈希与第二轮远端包一致。当前两组批量结果尚未取回，先保留本地运行目录。

下次接续命令（在仓库根目录执行，先确认两组均完成再下载）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_main_track_notebook.ps1 -Action Status -BuildDirectory .cache/main-track/ranker-development-v1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_main_track_notebook.ps1 -Action Status -BuildDirectory .cache/main-track/ranker-matched-control-v2
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_main_track_notebook.ps1 -Action Fetch -BuildDirectory .cache/main-track/ranker-development-v1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_main_track_notebook.ps1 -Action Fetch -BuildDirectory .cache/main-track/ranker-matched-control-v2
.venv/Scripts/python.exe tools/compare_ranker_development.py --ranker-run .cache/main-track/ranker-development-v1 --control-run .cache/main-track/ranker-matched-control-v2
```

汇总工具会生成两组 `audit.json` 和完整方法目录的 `comparison.json`。它必须保留全部 10 个任务，包括超时、空补丁和技能失败；不得只统计调用成功子集。完成后连同配置、补丁、测试日志、轨迹与哈希索引保存到 `experiments/runs/`，再更新本记录和 `docs/status.md`。辅助冻结脚本在 `.cache/main-track/freeze_ranker_run.py`，会拒绝覆盖已有冻结目录。

今天本地收尾不代表正式参赛提交完成：119 个确认任务未使用，正式 Docker 的数值依赖和额外编码器适用性仍待确认，线上 Writeup、Git 推送及榜单均未在本轮更新。后续先形成这轮开发对照的可信结论，再确定下一阶段工作。

### 2026-11-08 开发对照结果与轨迹诊断

两组开发评测已取回并冻结：`experiments/runs/main-track-ranker-development-20261108-v1/`（完整排序器，10 任务）与 `experiments/runs/main-track-ranker-matched-control-20261108-v2/`（匹配证据基线，10 任务）。配对设置核对一致：同模型、同采样与预算哈希、同环境与参考对照。

| 指标 | 完整排序器 | 匹配证据基线 |
| --- | ---: | ---: |
| resolved | 1/10 | 2/10 |
| 成功任务 | requests_7433 | requests_7433、fastapi_14463 |
| 仅本臂成功 | 0 | 1 |
| 产物核对 | 104 项通过 | 48 项通过 |

`comparison.json` 记录：`actual_full_output_tasks=8`，`original_text_equivalent_tasks=6`，确认集使用 0。排序器内部耗时 16.9–30.2 秒，说明技能确实被调用并返回 full 排名，这一轮不是“模型跳过技能”。

逐条轨迹（`output/results/ranker/traces/`）显示的失败结构与最初从日志推断的不同：

1. **定位阶段并不慢**：8/10 任务的定位阶段在 2.2–14.2 秒内结束；例外是 fastapi_13713（51.3 秒）、requests_7205（65.4 秒）和 fastapi_14463（158.6 秒仍未结束）。
2. **修复阶段把剩余时间全花在读文件上**：10 个任务里 9 个的 `edit_file`/`write_file` 次数为 0，只有 requests_7433 写了 6 次并修复成功。rich_4079 在 127 秒内读了 22 次 `read_file`（`rich/table.py` 反复分页）和 6 次 `run_command`，没有一次编辑；`grep` 退出码 1 后仍不断换关键词重试。
3. **工具调用形状错误会吞掉整个会话**：fastapi_14463 连续三次把 `skill_name`/`file_path` 嵌进 `args`，返回 `INVALID_ARGUMENTS`，直到 158.6 秒超时都没发出合法调用。rich_4079 也先错一次后自行纠正。
4. **从未调用 `submit_patch`**：所有补丁都来自 harness 兜底 `git diff`，空补丁即 `resolved=false`。

因此空补丁的直接原因是**修复阶段在读取循环中耗尽 3 分钟预算**，不是定位阶段抢时间。两阶段设计仍有一项成本：修复阶段首个工具动作出现在任务开始后 31–109 秒，其中 30–50 秒是交接后的模型推理延迟。

据此修正（`tools/build_ranker_agent_probe.py`，仅用于下一轮，不改已冻结结果）：

- `prompts/localize.md` 给出精确 JSON 形状，明确 `skill_name`/`file_path`/`args` 三者平级、禁止嵌套，并规定 `INVALID_ARGUMENTS` 时立即按原样重发而不是重新规划；报告必须是三行 `<path>:<start_line>-<end_line> <symbol>`，保留行号。
- `prompts/system.md`（修复阶段）规定顺序：最多读两个行区间、第三次工具调用前完成编辑、最多一次定向测试、`submit_patch`；`grep` 退出码 1 不重试；空 diff 记零分，时间不够也要提交部分修复。
- 新增 `configs/locator_sampling.yaml`，把定位阶段 `thinking_budget` 降到 1024（该阶段只需一次调用）；修复阶段与对照臂保持 4096，`manifest.json` 记录 `locator_thinking_budget` 并在 `fairness` 中注明。

未做：技能瘦身到 16 MB 以下（ADK 提示 41,337,079 字节超出建议上限）、分阶段计时预算。验证运行 `gemma4-ranker-20261108-v3` 只用单个已知可解任务 fastapi_14463，先确认调用形状与“编辑先于读完”是否成立，再决定是否重跑 10 任务。

### 2026-11-08 预算对照（v1 / v10 / v11）

四组开发对照，同一批冻结任务、同模型、同采样与并发，只改预算与排序器臂提示词。v10 的排序器包与 v1 逐字节相同（manifest 哈希核对，唯一差异 `eval_config.yaml` 的 3→5 分钟）。

| 轮次 | 预算 | 排序器提示词 | 排序器 resolved | 基线 resolved |
| --- | --- | --- | ---: | ---: |
| v1 / matched-v2 | 3 分钟 | v1 | 1/10 | 2/10 |
| v10 / control-v4 | 5 分钟 | 与 v1 相同 | 3/10 | 2/10 |
| v11 / control-v4 | 5 分钟 | v1 + 两处修正 | 3/10 | 2/10 |

配对结果：

- v10：双成功 `requests_7433`；仅排序器 `requests_7502`、`rich_3882`；仅基线 `fastapi_14463`。
- v11：双成功 `requests_7433`；仅排序器 `requests_7502`、`httpx_3672`；仅基线 `fastapi_14463`。

解释边界：

1. 提示词不变、预算 3→5 分钟时，排序器 1/10→3/10，基线 2/10→2/10。方向为正，但 n=10。
2. 两处修正后仍是 3/10，且“仅排序器成功”的任务从 `{7502, 3882}` 变成 `{7502, 3672}`，说明这些任务处于阈值附近，不支持稳定效应。
3. `comparison.json` 记录 `actual_full_output_tasks` 6/10、`original_text_equivalent_tasks` 3/10：排序器并非每个任务都拿到完整原文，解释具体任务收益时必须逐条核对。

轨迹中的失败模式（原文摘录）：

- 定位阶段去翻技能接口（`fastapi_14463`：“Okay, I have the instructions for the `ranker` skill. I need to call `run_skill_script`…”，0 次有效调用即超时）。
- 误读接口（`rich_3942`：“the script `localize.py` requires the `--issue` arg”）。
- 修复阶段占位符缺失导致硬失败（v10 的 `fastapi_13713` 报 `Context variable not found: localization_report`，105 秒退出）。v11 去掉占位符后该任务恢复产出补丁（1,002 字符），测试仍失败。
- reasoning channel 循环（`<|channel>thought` 重复）仍在 3 个任务出现，属于模型侧缺陷，不能用提示词完全消除。

中间轮次 `v5`（定位阶段 thinking 1024）、`v6`/`v7`（过度收紧的调用形状与“立即重发”指令）是自引入的回归，保留在 `.cache` 作为记录，不进入结论。`v5` 的循环任务与 `v6` 完全重合（`requests_7205`、`requests_7502`、`rich_3942`），`v1` 用旧提示词跑同样任务零循环。

冻结产物：`experiments/runs/main-track-ranker-5min-20261108-v10/`（88 个文件）、`main-track-ranker-5min-20261108-v11/`（90）、`main-track-control-5min-20261108-v4/`（63）。确认集 119 个任务仍未使用；本轮不构成榜单成绩或显著性主张。



