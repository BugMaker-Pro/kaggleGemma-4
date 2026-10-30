# kaggleGemma-4

参加 **Google – The Gemma 4 Developer Agent** 系列赛：**主攻论文赛道**，主赛道 11/14 之后再用同一套东西去交一版。

论文选题：**代码图的符号级覆盖率，以及它到底值多少定位收益**——图里到底有没有「参考修复动过的那几个符号」？补全它，检索排序能提多少？
（完整协议见 [docs/paper-topic.md](docs/paper-topic.md)）

**实验底座**：SWE-bench Lite（300 任务 / 12 个 Python 仓库），不依赖 22 GB 比赛数据；同一套流水线可以原样切到官方 129 任务上。

## 关键日期（北京时间，UTC+8）

| 事件 | UTC | 北京时间 |
| --- | --- | --- |
| **论文赛道提交截止** | 2026-11-12 23:59 | **2026-11-13 07:59** |
| 主赛道组队合并截止 | 2026-11-25 23:59 | 2026-11-26 07:59 |
| 主赛道提交截止 | 2026-12-02 23:59 | 2026-12-03 07:59 |

## 论文赛道提交清单（2026-11-13 07:59 前）

官方规则原文（[docs/kaggle-paper-track-raw.md](docs/kaggle-paper-track-raw.md)）允许两种载体：正文直接写在 **Kaggle Writeup** 里，或者 *"(Optional) Public Project Link: optionally, instead of writing your paper in the Kaggle Writeup, you can also upload an arXiv-ready (LaTeX/Word) PDF"*。所以下面两条都做：正文用富文本（评委在页面里直接读），PDF 放 Project Links（表格不会变形）。

| 字段 | 内容 |
| --- | --- |
| **Title** | `File-Level Is Not Symbol-Level: What Code Graphs Miss and the Issue Already States` |
| **Subtitle** | `300 tasks, then 2,232: the granularity gap is invariant, the graph is worth two points at symbol level and none at file level, and a three-point hand-written rule was really training data` |
| **Body** | [paper/kaggle_body_img.md](paper/kaggle_body_img.md) —— 全文 **2,532 词**（表格变成图片，所以数字不占词），9 章 + **8 个图片位**。逐个上传 `paper/` 下的：`table_resolution` → `table_1` → `fig1` → `table_2` → `table_3` → `table_5` → `table_6` → `table_7`（每个占位图的 alt 文字就是文件名，从上往下点即可） |
| **PDF** | [paper/submission.pdf](paper/submission.pdf)，5 页 / 452 KB，`python tools/make_pdf.py` 重新生成；放进 Project Links（表格的排版版） |
| **字数** | 短版 830 / 全文版 2,946 / 含标题副标题 2,992，上限 3,000；`python tools/make_submission.py` 与 `tools/count_short.py` 复核 |
| **图片** | 短版里图注在正文、图要手动传：删掉 `![Figure 1](fig1.png)` 那一行，光标留在原位 → 编辑器图片按钮 → 上传 [paper/fig1.png](paper/fig1.png)（1152×864） |
| **Project link** | `https://github.com/BugMaker-Pro/kaggleGemma-4`（**必须先设 public**，当前匿名访问返回 404） |

**粘贴方式：全文 + 表格图片。** 表格在富文本框里没救——竖线会散，纯数字列表又难读（要默记列序）。所以正文用 [paper/kaggle_body_img.md](paper/kaggle_body_img.md)：全文 2,532 词，**7 张表各自渲染成一张书版风格的 PNG**（表题已烘进图里），在正文里用 8 个占位图（7 表 + Figure 1）落位。上传顺序就是文档顺序，每个占位图的 alt 文字写着该传哪个文件。列表化版本 [paper/kaggle_body_full.md](paper/kaggle_body_full.md)（2,947 词）保留作对照，[paper/kaggle_body.md](paper/kaggle_body.md) 是 830 词摘要版。

提交后仍可编辑并重新提交，所以先把这一版交上去，再用同一套 harness 补实验。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/paper-topic.md](docs/paper-topic.md) | **主线**：选题定稿 v4、三个天花板（黄金符号 / 候选池 / 图扩散）、E0–E3 协议与实测结果、3000 词预算、19 天排期 |
| [docs/kaggle-paper-track-raw.md](docs/kaggle-paper-track-raw.md) | **官方规则原文**（2026-10-20 核实）：3000 词、五维评分、三个奖、题目清单、评委 |
| [docs/data-assets.md](docs/data-assets.md) | **官方数据资产清单**（主赛道 Data 页原文）：22.42 GB / 524 文件、graph 与 embedding 的 schema、策展流程 |
| [docs/competition.md](docs/competition.md) | 两个赛道的完整机制：任务形态、约束、数据构成、评分方式 |
| [docs/task-walkthrough.md](docs/task-walkthrough.md) | 主赛道单任务流程：任务包字段、两阶段评测、六步循环、七个吃分的坑 |
| [paper/main.md](paper/main.md) | 论文正文（2,992 词，Kaggle 口径）：两尺度八臂 + 四表一图 + References；[paper/submission.md](paper/submission.md) 是可直接粘贴的版本 |
| [docs/file-first.md](docs/file-first.md) | **2026-10-27 新实验**：file-first 分层基线 + 乘积分解（预算同时买文件与符号） |
| [docs/papers/notes.md](docs/papers/notes.md) | 10 篇参考文献的逐条核实（引文原句 + 页码位置） |
| [agent/README.md](agent/README.md) | 主赛道提交包结构（11/14 之后才用） |
| [agent/prompts/system.md](agent/prompts/system.md) | 主赛道系统提示词第一版 |

## 状态

- [x] 竞赛资料梳理 + 任务流程
- [x] 官方规则核实（字数、评分维度、奖项、评委）——靠 Edge 无头渲染抓取
- [x] 选题 v4 定稿：候选生成才是天花板（底座换成 SWE-bench Lite，不依赖 22 GB 比赛数据）
- [x] 论文骨架（3000 词预算）
- [x] shell 转完全权限；Python 3.12 在 `D:\pyenv\cpython-3.12.13-windows-x86_64-none\python.exe`
- [x] **E0 代码**：diff 解析 + 符号解析 + 单次解压读 tar（不落盘）
- [x] **E1 代码**：graph 读取 + 符号级覆盖率四分类（exact/suffix/module_only/miss）
- [x] **E2 代码**：stdlib 建图器，输出与官方 graph 同 schema（`nodes[id,name,text]` / `edges[source,target,type,key]`）
- [x] **E3 代码**：BM25 定位 + 一跳图扩散，同预算对照
- [x] 数据落地：SWE-bench Lite 300 任务元数据 + 297 个 base_commit 源码快照（2.5 GB，`data/`）
- [x] 全量跑 E0/E2/E3：295/300 任务落地 `data/experiment.jsonl`（0 报错，348 个黄金符号）
- [x] **五条图臂**（rerank / open / open2 / fuse / fuse_precise）+ 文件级 recall：300/300 任务，290 个有黄金符号
- [x] 消融（种子数 / 跳数 / 池大小 / λ）+ 边解析率归因 → `data/ablation.jsonl`
- [x] **加 PPR 臂**（`graph_ppr` / `graph_ppr_text`）+ 完整排名导出 + 球内构成 → `data/experiment_v3.jsonl`
- [x] 主图 `paper/fig1.png`（八臂 recall@k 曲线 + 两种粒度对照）
- [x] 3000 词初稿收尾：正文 **2,984 词**（含 References），三个占位符全部填掉
- [x] **数字审计** `tools/audit_numbers.py`：210 项逐一重算并比对正文，0 失败
- [x] 引用补齐：References 7 条（标题/作者从 PDF 原页抽），删掉未核实的 OrcaLoca / RepoGraph
- [x] 图在 50% 缩放下复核可读（1050×367）
- [x] **file-first 分层基线**（`ff_k1..k5` / `ff_graph` / `file_oracle`）：不赢；但乘积分解 r@10 ≈ P(文件) × 回收率 成立，`file_oracle` = 0.665 → `docs/file-first.md`
- [x] **文件排序改进 + 消融**：`fr_mix_nop` = **0.305**（+3.0 点，p=0.031）；去掉图信号反而更好 → 增益来自词法聚合，不是图
- [x] **三个证据通道**（2026-10-28）：路径 / traceback 帧 / issue 引用的代码 → 合并 **0.352**（+7.7 点，30 胜 4 负，p<0.001），字符 1535<1615 → `docs/evidence.md`
- [x] 正文并入（§5 新增证据一节 + 表 5；摘要/§1/§6/§8 改口径）
- [x] **扩到全量 2,232 任务**（2,174 快照 / 18.45 GB）：gap 2.27×→2.28× 不变；图从"看不见"变成 +2.2 点（CI 0.013–0.031）；2.9 点的证据规则**不复现** → 表 6/7、`docs/scale-check.md`
- [x] **模型当特征 / 当重排器**：bge-reranker-v2-m3 fp16@1024，当特征 +4.1 点（非引用桶 +7.2），当短名单重排器 −2.8 → −37.8 → `docs/model-rerank.md`
- [x] **答案纸审计**：独立实现复算 279/300 完全一致；换修复版金标 recall 变化 ≤0.7 点；10 个掉标任务实际是 2 个模块级 + 8 个只新增定义 → `docs/gold-audit.md`
- [x] 定稿 **2,992 词**（Kaggle 口径），审计 210 项 0 失败
- [ ] 更新线上 writeup（新版正文 + 图 + 证据表）
- [ ] 把仓库设为 public 并在 Project Links 填入 `https://github.com/BugMaker-Pro/kaggleGemma-4`
- [ ] 11/12 之前提交；提交后按 Non-Archival 规则再公开
- [ ] 官方 129 任务那一路（可选：需在主赛道 Join + 接受 Rules）
- [ ] 主赛道首次提交（论文赛道交完再开；主赛道 12/03 截止，时间够）

## 实验流水线

```powershell
$py = 'D:\pyenv\cpython-3.12.13-windows-x86_64-none\python.exe'

# 1. 元数据（走 hf-mirror，huggingface.co 直连被墙）
& .\.venv\Scripts\python.exe tools\fetch_swebench.py

# 2. 297 个 base_commit 源码快照（codeload，断了重跑会自动续）
& $py tools\fetch_repos.py --jobs 6

# 3. 黄金符号（参考修复动过的符号 = 所有覆盖率的分母）
& $py experiments\gold.py --tasks data\swebench_lite.jsonl --out data\gold_symbols.jsonl --snapshots data\repos

# 4. 建图 → 覆盖率 → 同预算定位对照
& $py tools\run_experiment.py --jobs 6

# 测试
& $py -m unittest discover -s tests -t .
```

产物：`data/gold_symbols.jsonl`（每任务一条）、`data/experiment.jsonl`（每任务一行，含覆盖率四分类与 text/graph 两条 recall@k）。

## 数据

**主用**：SWE-bench Lite，`data/swebench_lite.jsonl` + `data/repos/*.tar.gz`，已就位（300 / 297，2.5 GB）。
网络要点：`huggingface.co` 直连超时，**`hf-mirror.com` 可用**；`codeload.github.com` 可用。

**备用/加分**：比赛官方的 22.42 GB 资产（129 任务 + `graphs/` + `embeddings/`），需要在**主赛道**页面 Join + 接受 Rules 才能下。

两条路（任选）：

**A. 浏览器**：比赛 **Data** 页 → Download All → 解压到本项目 `data/`。

**B. 命令行**
```powershell
& "D:\pyenv\cpython-3.12.13-windows-x86_64-none\python.exe" -m pip install kaggle
# 然后把 Kaggle → Settings → Create New Token 下载的 kaggle.json 放到 %USERPROFILE%\.kaggle\
& "D:\pyenv\cpython-3.12.13-windows-x86_64-none\python.exe" -m kaggle competitions download -c gemma-4-developer-agent -p data
```

落地后应是：`data/tasks.jsonl`、`data/snapshots/<instance_id>.tgz`、`data/graphs/`、`data/embeddings/`。
`data/` 已在 `.gitignore` 里，不会进仓库。

## 发布给评审的内容（Project Link）

仓库对外时，下面这些是**必须入库**的（其余数据太大，靠脚本重新拉取）：

| 路径 | 大小 | 作用 |
| --- | --- | --- |
| `data/gold_symbols.jsonl` | 0.14 MB | **354 个黄金符号**，300 任务，答案纸本身 |
| `data/swebench_lite.jsonl` | 3.0 MB | 300 条任务元数据（issue、patch、base_commit） |
| `data/ablation.jsonl` | 0.18 MB | 种子数 / 跳数 / 池大小的消融 |
| `data/experiment_v3.jsonl` | 6.6 MB | 八臂主实验，含每臂前 50 名与每个符号的名次 |
| `data/experiment_ff.jsonl` | 5.7 MB | file-first 分层臂与 `file_oracle` |
| `data/experiment_fr2.jsonl` | 10.4 MB | 文件级投票、5/5 混合与消融 |
| `data/features_full.jsonl` | 90.7 MB | 全量 2,232 任务的候选池 + 16 特征 + 标签（表 6/7 与 stack 的输入） |
| `data/combo_ltr.jsonl` / `data/combo_ltr_full.jsonl` | 0.2 / 0.2 MB | 学习排序每折的分数（Lite / 全量） |
| `data/combo_ltr_orders_full.jsonl` | 7.6 MB | 全量每任务、每 arm 的完整排名（任意 k 可复算） |
| `data/rerank_full_1024.jsonl` | 5.9 MB | bge-reranker-v2-m3 在 2,232 任务上的分数（“模型当特征”那一列） |
| `data/gold_fixed.jsonl` | 0.16 MB | 答案纸审计：原版 / 修复版 / 独立实现三套金标（`docs/gold-audit.md`） |
| `data/gold_impact.json` | 0.5 KB | 换金标重算的 recall 变化 |

复算全部数字：

```powershell
$py = 'D:\pyenv\cpython-3.12.13-windows-x86_64-none\python.exe'
& $py tools/audit_numbers.py      # 210 条断言，0 failure
& $py tools/analyse_v3.py         # 表 1–3
& $py tools/analyse_full.py       # 表 7（2,232 任务）
& $py tools/gold_fix.py --limit 300   # 答案纸审计（需 data/repos 快照）
& $py tools/gold_impact.py        # 换金标后的 recall 变化
& $py tools/decompose.py          # 预算乘积分解
& $py tools/analyse_filerank.py   # 正结果与消融
```

不含入仓库的：`data/repos/*.tar.gz`（18.45 GB，`tools/fetch_repos.py` 按 commit 重拉）、`models/`（2.12 GB 权重，`tools/fetch_model.py`）、`docs/papers/*.pdf`（版权）。

## 复原环境（uv，仓库里没有任何二进制）

没有提交 `.whl`、没有模型权重、没有快照。Python 侧由 `uv.lock` 决定（71 个包；torch 钉在 `2.11.0+cu128` 与 cu128 索引上，属于可选 `model` extra），重数据由 fetch 脚本拉：

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\setup.ps1          # 依赖 + 2.12 GB 重排器权重
powershell -ExecutionPolicy Bypass -File .\tools\setup.ps1 -Data    # 再加 SWE-bench 元数据与 18 GB 快照，最后跑审计
```

手动等价：

```powershell
uv venv --python 3.12 .venv
uv sync --frozen --all-extras         # 完全还原（含 torch/transformers 的 model extra）
uv run python tools/fetch_model.py    # 默认走 hf-mirror；直连可用时加 --endpoint
uv run python tools/audit_numbers.py  # 只跑论文数字的话，到这一步就够
```

- **只跑论文里的数字**（审计、表 1–3、表 7、换金标重算）不需要 torch、模型和快照：`uv sync --frozen` 装核心依赖即可，`uv run python tools/audit_numbers.py` 直接跑完。
- **cu128 索引慢的时候**：`tools/fetch_wheel.ps1` 从 SJTU 镜像用 8 段并行拉同一个 wheel（断点续传、校验总大小），拼好后 `uv pip install .\torch-2.11.0+cu128-cp312-cp312-win_amd64.whl`。
- **本机别急着 `uv sync`**：这台机器的 torch 是用本地拼装的 wheel 装的，`uv sync` 会把同一版本从 cu128 索引重下 2.6 GB；`setup.ps1` 检测到已装好就跳过同步。
- **`uv.lock` 是唯一的环境事实**：改依赖请改 `pyproject.toml` 再 `uv lock`，不要手改 lock。
- Windows 默认 `Restricted` 执行策略会拒绝 `.\tools\setup.ps1`，所以上面用 `powershell -ExecutionPolicy Bypass -File`。

## 环境备注

- 本机 `pwsh` 实际是 **Windows PowerShell 5.1**，脚本不要用 7 才有的语法（`??`、三元、`-Parallel`）。
- 代码默认在 **Kaggle Notebook** 上跑（Linux、数据可直接挂载），本地只写代码。
- 2026-10-30 之前 `4f48dc7` 误把 2.6 GB 的 CUDA wheel 和 8 个分片提交进了历史，已从全部 47 个 commit 里清除（`.git` 5.2 GB → 19 MB）；`.gitignore` 现在挡 `*.whl` 与 `tools/tmp_wheel/`。
