# 工作记录（非评审用）

这是开发过程的排期、提交清单、本机环境备注。给评委看的是 [README](../README.md)。

## 2026-11-08 当日收尾（北京时间）

按用户要求，今天的本地开发到此收尾；已提交的两组私有 Kaggle 作业继续在后台运行。最近一次查询两组均为 `RUNNING`，这不是实验完成回执。下次先查询远端状态、下载结果和审计，再填写最终效果结论。

已完成：

- 仓库整理：临时文件清理、历史材料无损归档、docs 合并至 16 篇；LibreOffice 固定在 `.tools/libreoffice-kit/`。
- 论文：全量强融合图特征消融及独立审计完成，符号指标 44.70% 对 43.04%；正文、表格、图片和 6 页 PDF 已同步。
- 完整方法部署：原始问题与源码 → AST 图 → BM25 200 候选 → 16 特征＋BGE → 三种子学习排序；部署训练排除比赛仓库，INT8 部署版与论文原估计明确区分。
- 真实接入：第一轮模型跳过技能的结果保留；第二轮改为先检索后修复，实际 full 调用成功、目标函数排名第一、337 个测试通过，最终补丁只含源码。59 项产物核对通过。
- 配套工程：匹配预算检查、输入问题保真检查、调用轨迹审计和对照汇总工具已完成；相关 26 项单元测试通过。可重建实验包在 `artifacts/ranker-agent-v2/`。

仍在 Kaggle 运行：

| 组别 | Notebook | 本地运行目录 | 任务数 |
| --- | --- | --- | --- |
| 完整方法 | `yyyyhhhhwww/gemma4-ranker-development-20261108-v1` | `.cache/main-track/ranker-development-v1` | 10 |
| 匹配证据基线 | `yyyyhhhhwww/gemma4-development-batch-20261108-matched-v2` | `.cache/main-track/ranker-matched-control-v2` | 10 |

两组模型、采样、3 分钟总预算、30 次工具预算、120 秒单命令上限和并发数 2 已核对一致；10 个任务均有空补丁失败、参考补丁通过的环境对照。基线首次启动失败发生在模型发现阶段，未产生修复结果；原始记录保留，修正版为上表 v2。

下一次只需接续：查询两组状态 → 下载全部产物 → 运行 `tools/compare_ranker_development.py` → 冻结结果和哈希索引 → 更新修复率及失败分析。最终结果下载归档前，保留上表两个 `.cache` 运行目录。完整方法是否优于基线仍待结果，119 个确认任务尚未使用。

正式 Docker 依赖、额外编码器的最终参赛适用性、线上 Writeup 更新和榜单提交仍待后续处理。本次未执行 Git commit/push 或线上提交。完整开发过程、失败记录和接续命令见 [比赛开发记录](competition/competition.md#2026-11-08-当日收尾与接续)。
## 关键日期（北京时间，UTC+8）

| 事件 | UTC | 北京时间 |
| --- | --- | --- |
| **论文赛道提交截止** | 2026-11-12 23:59 | **2026-11-13 07:59** |
| 主赛道组队合并截止 | 2026-11-25 23:59 | 2026-11-26 07:59 |
| 主赛道提交截止 | 2026-12-02 23:59 | 2026-12-03 07:59 |

## 论文赛道提交清单

官方规则（[kaggle-paper-track-raw.md](competition/kaggle-paper-track-raw.md)）允许两种载体：正文写进 **Kaggle Writeup**，或者 *"(Optional) Public Project Link: optionally, instead of writing your paper in the Kaggle Writeup, you can also upload an arXiv-ready PDF"*。两条都做。

| 字段 | 内容 |
| --- | --- |
| **Title** | `Beyond File Hits: Candidate Coverage and Graph Utility in Code Localization` |
| **Subtitle** | `A controlled retrieval study of graph reach, shortlist displacement, and index content on SWE-bench Lite and the full test split` |
| **Body** | [paper/kaggle_body_img.md](../paper/kaggle_body_img.md)：2,480 词（仅文字，另含表图内容）、10 个小节、**5 个图片位**；顺序为 `table_1` → `table_2` → `table_3` → `fig1` → `table_4` |
| **PDF** | [paper/submission.pdf](../paper/submission.pdf)，5 页（参考文献独立一页）；与 Markdown 同源生成，`check_publication.py` 已对照 PDF 核对 68 个源块 |
| **字数** | 完整文本含标题、副标题和表格，按仓库计数规则 **2,850 词**；限额 3,000，预留 **150**。图片版文字少不代表字数豁免；线上计数最终核对 |
| **Project Links** | `https://github.com/BugMaker-Pro/kaggleGemma-4` + `https://github.com/BugMaker-Pro/kaggleGemma-4/blob/main/paper/submission.pdf` |

2026-11-08 叙事重排：主结果改为全定量表拓扑对照（Table 1），学习排序与全量结果合并为一张两尺度表（Table 2）。随后按“删掉不承载主张的实验”精简：删除 null-derived denoiser 段、证据子集表、覆盖与位移表；学习排序的 290 任务数字并入正文。表格从 8 张降到 4 张，PDF 从 6 页降到 5 页，字数从 2,996 降到 2,728（余量 150），并把 Figure 1 前移以消除半页空白。

表格图共 4 张：Table 1 全量拓扑对照、Table 2 两尺度召回、Table 3 符号/文件粒度、Table 4 Lite 八臂；另有 Figure 1，共 5 个图片位。旧 `table_resolution.png` 与 `table_5`–`table_8.png` 已删除。

备选全文：[paper/kaggle_body_full.md](../paper/kaggle_body_full.md)，2,891 词，表格转列表。`paper/kaggle_body.md` 仅是简短项目介绍，不能代替完整论文提交。

2026-11-01 修订：收窄图效应与粒度结论，纠正等字符预算，补全两折仓库评估，说明 Lite/全量重叠与子采样统计边界，补入 Bellam（2026-10-25）近邻引用。新颖性风险和后续实验见 [novelty-review.md](novelty-review.md)，复现协议见 [reproduction.md](reproduction.md)。这些修改尚未上传或替换线上 Writeup。

## 状态

- [x] 2026-11-08 强融合模型图特征消融：44.70% → 43.04%；图增量 +1.66 点，仓库区间 [0.66, 2.42]，p=0.0103。历史 4,464 项指标先复现一致，独立审计 8,949 项通过。
- [x] 新结果已加入摘要、Table 5 和讨论；正文 2,915 词、PDF 6 页、8 张表，表格数值对齐已统一，完成页面渲染检查。

- [x] **拓扑控制实验完成**：2,232/2,232；三种表示、两类匹配随机图、同文件控制；输入哈希固定；734,354 项独立审计检查零失败。见 [结果](graph-control-results.md) 与 [解释](novelty-review.md#graph-control-interpretation)。
- [x] dense 历史并列处理敏感性：一个任务的基线 recall 改变，五项主要推断不变。
- [x] 投稿摘要/方法/结果/讨论已纳入新实验；强调结构信号与具体干预净收益的区别，交互不显著。

- [x] 规则核实（3000 词、五维评分、奖项、评委、Non-Archival）
- [x] 选题 v4 定稿：候选生成才是天花板（底座 SWE-bench Lite，不依赖 22 GB 比赛数据）
- [x] E0–E3：diff 解析 + 符号解析 + stdlib 建图 + BM25 定位 + 一跳扩散
- [x] 八臂（text / rerank / open / open2 / fuse / fuse_precise / ppr / ppr_text）+ 文件级 recall
- [x] 消融（种子数 / 跳数 / 池大小 / λ）+ 边解析率归因
- [x] file-first 分层基线 + 乘积分解（`file_oracle` = 0.665）
- [x] 三个证据通道（路径 / traceback 帧 / issue 引用的代码）→ 合并 0.352
- [x] **扩到全量 2,232 任务**（2,174 快照 / 18.45 GB）：gap 2.27×→2.28×；图从"看不见"变成 +2.2 点；2.9 点证据规则不复现
- [x] 模型当特征 / 当重排器（bge-reranker-v2-m3 fp16@1024）：+4.1 / −2.8…−37.8
- [x] **答案纸审计**：独立实现 279/300 一致；换修复金标 recall 变化 ≤0.7 点
- [x] 数字审计 `tools/audit_numbers.py`：零失败；不再在论文中维护易漂移的固定断言数量
- [x] 仓库 public（2026-10-30，匿名 200），PDF 已入库
- [ ] 线上 Writeup 更新为本轮标题与正文、重新上传 Figure 1 和表格图、填 Project Links 并确认正式提交
- [x] 已 Join 主赛道；官方 129 任务已固定为 10 个开发任务和 119 个确认任务，开发评测进行中。
- [ ] 主赛道正式环境与附加编码器适用性确认、确认集评测及首次提交；当前开发结果不作为榜单成绩。

## 发布内容（哪些必须入库）

| 路径 | 作用 |
| --- | --- |
| `data/gold_symbols.jsonl` | 354 个黄金符号，300 任务，答案纸本身 |
| `data/swebench_lite.jsonl` | 300 条任务元数据（issue、patch、base_commit） |
| `data/experiment_v3.jsonl` | 八臂主实验，含每臂前 50 名与每个符号的名次 |
| `data/experiment_ff.jsonl` / `_fr2` / `_ev` / `_body` / `_combo2` | 分层基线、文件投票、证据、正文证据、组合臂 |
| `data/ablation.jsonl` | 种子数 / 跳数 / 池大小的消融 |
| `data/features_full.jsonl` | 全量 2,232 任务的候选池 + 16 特征 + 标签 |
| `data/combo_ltr*.jsonl`、`data/rerank_full_1024.jsonl` | 学习排序分数与完整排名、模型分数 |
| `data/gold_fixed.jsonl`、`data/gold_impact.json` | 答案纸审计的三套金标与换标重算结果 |

不入库：`data/repos/*.tar.gz`（18.45 GB，`tools/fetch_repos.py` 重拉）、`models/`（2.12 GB，`tools/fetch_model.py`）、`docs/papers/*.pdf`（版权）。

## 预注册：body-rank 实验的判读规则（2026-10-31，看结果之前写）

实验：给 ranker 加两个特征（`body_in_pool`、`body_rank`，来自一个含 body 的 BM25 索引），池、fold、种子、其余 16 特征全不动。

| 结果 | 论文怎么写 | 为什么 |
| --- | --- | --- |
| delta ≥ +1.5 且 CI 排除 0 | "索引层面 +3.8，且在该排序器之上仍余 +X" | body 是两层都有效的信号 |
| +0.3 < delta < +1.5 | "索引层面 +3.8，到了排序器只剩 +X——大部分已被 body-quote 特征吃掉" | 诚实，且解释了为什么最强臂没有跟着涨 |
| delta ≤ 0 或 CI 含 0 | 只在 §5 保留"索引层面"的结论，明确写"这是候选生成/索引的发现，不是排序器的增益" | 避免把索引层的收益错记到排序层 |

同时记录：无论哪一档，**摘要里的 1.97× 不变**（那是索引层面、已由 noise 控制验证的结论）。

## 实验结论汇总（2026-11-01）

| 信号 | 用法 | 结果 |
| --- | --- | --- |
| 候选自身 body | 文档文本（BM25） | **+3.8 点**（CI 2.1–5.4，399/274）；noise 控制 −12.0 |
| 候选自身 body | 两个额外特征 | **+2.6 点**（202/94，0.361→0.387） |
| 稠密语义分数 | 一个额外特征 | **+8.6 点**（418/83，0.361→0.447） |
| 稠密 + body 特征 | 三个额外特征 | 0.444（比只加稠密还低，body 被稠密吸收） |
| 图 | 排序先验（8 臂） | 0 或负；全量 +2.2 符号 / +0.0 文件 |
| 图（调用点行） | 文档文本 | −0.3 符号 / +1.0 文件，仅 5 个任务变化 → 未观察到效应 |
| 稠密全库索引 | 扩大候选池（并集） | **一个都没捞回来**：BM25 62.8% → 并集 62.8%，天花板 0.600 不变；单独稠密只有 51.7% |
| BM25+余弦 50/50 融合（无训练） | Lite 排序 | 0.354，介于 16 特征 0.332 和 +证据 0.361 之间 |
| 尾部 80 个任务 | 诊断（精确通道） | **只覆盖 12/80（15%）**：名字 5、body 1、路径 1、frame 8；68 个任务只描述行为、从不点名代码 |
| 粒度成本 | 上下文预算 | 金标文件 median **28,950 字符** vs 被改定义 **1,726**（**16.1×**，均值 48.2×）；定义占文件 6.2%；文件内 48 个定义；112/290 任务 ≥25× |
| 尾部短语索引（未入文） | 仓库级 6-gram 原文 | 80 个尾部任务里 10 个的 issue 含 ≥6 token 原文代码段（最长 37）→ 天花板约 +2.3 点 |

审查修订（2026-11-02）：当前实验支持候选自身内容和语义分数具有收益，但不能概括为“图结构没有价值”。后续拓扑对照区分了结构信号与具体重排规则的净收益：metadata 和 dense 上的真实拓扑相对约束随机图存在优势，简单重排相对原排序的净收益则依表示而异，详见[拓扑对照研究判断](novelty-review.md#graph-control-interpretation)。尾部诊断只说明当前精确匹配与已测试的 dense 扩池未解决这些遗漏，不能排除检索器、表示或查询策略的局限；“行为到代码的映射不足”保留为待验证解释。

后续方法研究按[修订计划](archive/history.md#research-directions)依次检验固定动作选择空间、代码反馈生成价值和显式证据状态的增量价值。2026-11-02 已完成 12 条历史任务的[固定菜单探索性试跑](experiments/query-generation.md#query-pilot)：oracle 相对固定组合的候选覆盖差值为 +8.33 点，但描述性区间跨过预定门槛，结论为“不确定”；差距全部来自避免一个任务的退步。随后完成[轮转候选保留对照](experiments/query-generation.md#candidate-retention)，固定组合覆盖下降 4.17 点，未采用该替代规则。[单轮反馈流程与 24 份配对输入](experiments/feedback.md#feedback-pilot)已实现并验证，已通过 [Flash API 试跑](experiments/feedback.md#deepseek-feedback-results)：23 次正常响应、1 次异常未重发，11 个完整配对的 recall@10 从 40.91% 到 50.00%，仅一个任务改善；已知用量估算费用约 0.034 元，异常账单未知。后续[35 条不重叠任务扩样](experiments/feedback.md#flash-replication)的 70 次调用全部正常，反馈 recall@10 为 55.24%，预规划为 56.67%，差值 −1.43 点；2 改善、2 退步，区间较宽，未复现稳定收益。该轮估算约 0.106 元，全部 155 项测试通过。2026-11-03 的[强排序器诊断](experiments/query-generation.md#strong-query)复现全部 2,232 条历史成绩；35 条上只看 issue 生成查询的候选池相对原正文池 recall@10 从 60.48% 到 70.00%，4 改善、零退步，区间下界为零，判断仍不确定。三条改善本来已被 metadata 池覆盖，尚未排除简单池融合解释；本轮零新增 API 费用，165 项测试通过。后续[简单融合对照](experiments/query-generation.md#simple-fusion)为 63.33%，生成查询为 70.00%，差值 +6.67 点，3 改善、零退步，区间下界为零；仅一个目标超出原 metadata 与正文候选并集，其余两个收益与截断有关。本轮零 API 费用，174 项测试通过。暂缓多轮反馈与证据状态控制器训练；这些诊断不改写已投稿结果。

## 本机环境备注（Windows）

- 本机 `pwsh` 实际是 **Windows PowerShell 5.1**，脚本别用 7 才有的语法（`??`、三元、`-Parallel`）。
- 主解释器 `D:\pyenv\cpython-3.12.13-windows-x86_64-none\python.exe`；实验用 `.venv\Scripts\python.exe`。
- 本机 torch 是用**本地拼装的 CUDA wheel** 装的（`tools/fetch_wheel.ps1` 从 SJTU 镜像 8 段并行拉，断点续传），所以在这台机器上别随手 `uv sync`——它会把同一版本从 cu128 索引重下 2.6 GB。`tools/setup.py` 检测到已装好会跳过。
- 构建 PDF / 表格图片要 LibreOffice Kit：设置 `LIBREOFFICE_KIT_CLI`（以及需要时的 `NODE_BIN`）。这是可选工具，评审复算数字不需要它。
- 2026-10-30 之前 `4f48dc7` 误把 2.6 GB 的 CUDA wheel 和 8 个分片提交进历史，已从全部 commit 清除（`.git` 5.2 GB → 19 MB）；`.gitignore` 现在挡 `*.whl` 与 `tools/tmp_wheel/`。
- 代理不稳：`github.com` 时通时断，push 用 `git -c http.version=HTTP/1.1 -c http.postBuffer=524288000 push`。

## 论文版式约定

- **表格题注在上、图注在下**（IEEE/ACM 惯例：表格先给列，图先看图），两者标签都用粗斜体，看起来是一族。
- 表体只用横线（顶线、表头线、底线），列宽按内容比例分配，行内禁止跨页断行，表头跨页重复。
- 这些由 `tools/make_pdf.py` 实现；writeup 里的表格图片与 PDF 同源。

## 2026-11-03 不重叠任务验证已收尾

[新批次记录](experiments/query-generation.md#query-validation)：排除此前 47 条任务，37 条全部生成及评分完成，35 条有可评分符号、2 条无符号目标。固定简单融合 recall@10 58.57%，生成查询 61.43%，差值 +2.86 点；1 条改善、零退步，仓库描述性区间 [0, 9.09] 点，仍不确定。新增补回 django 的 BaseFormSet.empty_form 不在原两池并集中。新增 API 估算闲时约 0.03005 元，180 项测试及独立审计通过。按用户要求，今日到此结束，不开新实验。
