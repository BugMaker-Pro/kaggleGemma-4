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

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/paper-topic.md](docs/paper-topic.md) | **主线**：选题定稿 v4、三个天花板（黄金符号 / 候选池 / 图扩散）、E0–E3 协议与实测结果、3000 词预算、19 天排期 |
| [docs/kaggle-paper-track-raw.md](docs/kaggle-paper-track-raw.md) | **官方规则原文**（2026-10-20 核实）：3000 词、五维评分、三个奖、题目清单、评委 |
| [docs/data-assets.md](docs/data-assets.md) | **官方数据资产清单**（主赛道 Data 页原文）：22.42 GB / 524 文件、graph 与 embedding 的 schema、策展流程 |
| [docs/competition.md](docs/competition.md) | 两个赛道的完整机制：任务形态、约束、数据构成、评分方式 |
| [docs/task-walkthrough.md](docs/task-walkthrough.md) | 主赛道单任务流程：任务包字段、两阶段评测、六步循环、七个吃分的坑 |
| [paper/main.md](paper/main.md) | 论文骨架：3000 词逐节分配、主表/主图占位、主张→证据对照、投稿检查 |
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
- [x] 数据落地：SWE-bench Lite 300 任务元数据 + 297 个 base_commit 源码快照（2.7 GB，`data/`）
- [x] 全量跑 E0/E2/E3：295/300 任务落地 `data/experiment.jsonl`（0 报错，348 个黄金符号）
- [ ] **修 open arm**（graph 臂允许池外邻居补位）后重跑 → 正式主图
- [ ] 消融（种子数 / 跳数 / 池大小）+ 边解析率归因
- [ ] 官方 129 任务那一路（可选：需在主赛道 Join + 接受 Rules）
- [ ] 3000 词初稿 → 11/12 提交
- [ ] 主赛道首次提交（11/14 之后）

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

**主用**：SWE-bench Lite，`data/swebench_lite.jsonl` + `data/repos/*.tar.gz`，已就位（300 / 297，2.7 GB）。
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

## 环境备注

- **`pwsh` 默认模式必崩**（`0xC0000142` = `STATUS_DLL_INIT_FAILED`）。已定位：不是 Windows 或 PowerShell 损坏，是 DSH 沙箱层给子进程装配受限令牌失败；同一条命令在完全权限下正常。**解法：本会话切「完全权限」。**
- 本机 `pwsh` 实际是 **Windows PowerShell 5.1**，脚本不要用 7 才有的语法（`??`、三元、`-Parallel`）。
- 代码默认在 **Kaggle Notebook** 上跑（Linux、数据可直接挂载），本地只写代码。
