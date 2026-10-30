# 工作记录（非评审用）

这是开发过程的排期、提交清单、本机环境备注。给评委看的是 [README](../README.md)。

## 关键日期（北京时间，UTC+8）

| 事件 | UTC | 北京时间 |
| --- | --- | --- |
| **论文赛道提交截止** | 2026-11-12 23:59 | **2026-11-13 07:59** |
| 主赛道组队合并截止 | 2026-11-25 23:59 | 2026-11-26 07:59 |
| 主赛道提交截止 | 2026-12-02 23:59 | 2026-12-03 07:59 |

## 论文赛道提交清单

官方规则（[kaggle-paper-track-raw.md](kaggle-paper-track-raw.md)）允许两种载体：正文写进 **Kaggle Writeup**，或者 *"(Optional) Public Project Link: optionally, instead of writing your paper in the Kaggle Writeup, you can also upload an arXiv-ready PDF"*。两条都做。

| 字段 | 内容 |
| --- | --- |
| **Title** | `File-Level Is Not Symbol-Level: What Code Graphs Miss and the Issue Already States` |
| **Subtitle** | `300 tasks, then 2,232: the granularity gap is invariant, the graph is worth two points at symbol level and none at file level, and a three-point hand-written rule was really training data` |
| **Body** | [paper/kaggle_body_img.md](../paper/kaggle_body_img.md)：全文 2,481 词、9 章、**9 个图片位**，按文档顺序上传 `table_resolution` → `table_1` → `fig1` → `table_2` → `table_3` → `table_4` → `table_5` → `table_6` → `table_7`（占位图的 alt 文字就是文件名） |
| **PDF** | [paper/submission.pdf](../paper/submission.pdf)，5 页，`uv run python tools/make_pdf.py` 重新生成 |
| **字数** | 2,481（含图版正文）/ 2,984（全文本 + 标题副标题），上限 3,000；`tools/make_submission.py`、`tools/count_short.py` 复核 |
| **Project Links** | `https://github.com/BugMaker-Pro/kaggleGemma-4` + `https://github.com/BugMaker-Pro/kaggleGemma-4/blob/main/paper/submission.pdf`（`blob` 比 `raw` 稳，raw 域名在国内常不通） |

**为什么表格是图片**：富文本框里竖线表会散，纯数字列表又要默记列序。8 张表各自渲染成书版风格 PNG（表题烘进图里），`tools/make_table_images.py` 生成。

**备选正文**：[paper/kaggle_body_full.md](../paper/kaggle_body_full.md)（2,947 词，表格改成列表）、[paper/kaggle_body.md](../paper/kaggle_body.md)（830 词摘要版，缺 Related Work，**不合规，别用**）。

## 状态

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
- [x] 数字审计 `tools/audit_numbers.py`：220 项，0 失败
- [x] 仓库 public（2026-10-30，匿名 200），PDF 已入库
- [ ] 线上 writeup 修正 Figure 1 错位 + 填 Project Links + 点提交
- [ ] 官方 129 任务那一路（可选，需在主赛道 Join + 接受 Rules）
- [ ] 主赛道首次提交（论文交完再开，主赛道 12/03 截止）

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
