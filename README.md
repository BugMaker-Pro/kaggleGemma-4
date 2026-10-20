# kaggleGemma-4

参加 **Google – The Gemma 4 Developer Agent** 系列赛：**主攻论文赛道**，主赛道 11/14 之后再用同一套东西去交一版。

论文选题：**代码图覆盖率审计 + 重建**——官方发的 `graphs/` 与 `embeddings/` 里到底有多少代码？补全它，对小模型 agent 值多少？
（完整协议见 [docs/paper-topic.md](docs/paper-topic.md)）

## 关键日期（北京时间，UTC+8）

| 事件 | UTC | 北京时间 |
| --- | --- | --- |
| **论文赛道提交截止** | 2026-11-12 23:59 | **2026-11-13 07:59** |
| 主赛道组队合并截止 | 2026-11-25 23:59 | 2026-11-26 07:59 |
| 主赛道提交截止 | 2026-12-02 23:59 | 2026-12-03 07:59 |

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/paper-topic.md](docs/paper-topic.md) | **主线**：选题定稿 v3、RQ/H1–H3、E0–E4 实验协议、3000 词预算、23 天排期与止损线 |
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
- [x] 选题 v3 定稿：代码图覆盖率 + 重建（去 GPU 依赖）
- [x] 论文骨架（3000 词预算）
- [x] shell 转完全权限；Python 3.12 在 `D:\pyenv\cpython-3.12.13-windows-x86_64-none\python.exe`
- [x] **E0 代码**：diff 解析 + 符号解析 + 不落盘直接读 tar 快照（15 个测试通过）
- [x] **E1 代码**：graph 读取 + 符号级覆盖率四分类（exact/suffix/module_only/miss，14 个测试通过）
- [ ] **数据落地 22.42 GB**（阻塞：需在**主赛道**页面 Join + Accept Rules，见下）
- [ ] 用 129 个任务跑 E0，产出 `data/gold_symbols.jsonl`
- [ ] 官方图覆盖率审计（E1）
- [ ] 重建图 + 检索对照（E2/E3）→ **主图**
- [ ] 3000 词初稿 → 11/12 提交
- [ ] 主赛道首次提交（11/14 之后）

## 数据（当前唯一阻塞项）

22.4 GB，前提：Kaggle 账号已 **Join** 比赛并接受 Rules。

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
