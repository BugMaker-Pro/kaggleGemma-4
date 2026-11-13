# 未见任务集上的 label-free 结构复现检验（2026-11-09，协议 v1 冻结）

## 冻结状态

本协议在**查看 62 个留出任务的任何结构量之前**写入冻结。冻结前只做了数据可得性核查：文件行数、仓库前缀分布、快照文件名与 `base_commit` 匹配、`features.py` 的跳过条件、`graph_controls.py` 的函数签名。未对这 62 个任务运行过建池、建图、重连或 `promote`，未见过它们任何一个 `top10` 或 `D` 值。

主集合（2,232 任务）的四个结构量**已在上一轮 `intervention-sensitivity-confirmation.md` §"结构性核查"中公开**：`D=0` 共 537 个，其中 530 个 `real.top10 ∈ rewired 短名单集合`、362 个 `real == base`；`D>0` 共 1,695 个，其中 341 个 `real ∈ rewired`、34 个 `real == base`；`D` 均值 0.2496、非零比例 75.9%。本轮把这些**已知数字当作固定基准与方向来源**，不参与任何阈值选择，也不在新集合上挑判据。

## 为什么做这个（外部确认路径的核查结论）

上一轮与 v0 都写明"确认必须在新仓库或外部基准上完成"。核查结果：

| 路径 | 结论 |
| --- | --- |
| 新仓库快照 | **不可得**。本地 `data/repos` 2,174 个快照全部属于原来 12 个仓库 |
| 主赛道 119 确认任务（fastapi / rich / httpx） | **本地不可得**，只在 Kaggle 云端 `tasks.jsonl`，且按比赛规则冻结；也无符号级金标 |
| `swebench_full.jsonl` 中未用的 62 个任务 | **可得**：62/62 有本地快照、patch、FAIL_TO_PASS，分布 11 个仓库，从未进入 `features_full.jsonl` 或任何既有实验 |

但 62 个任务被排除的原因正是 `tools/features.py:117` 的 `if not gold and not KEEP_EMPTY_GOLD: skipped` —— 从参考补丁提不出符号级金标。因此：

- **做不了**需要 `Δ` 的敏感度假设确认（无金标；且按主集合 88.4% 零效应推算，62 个任务里仅约 7 个非零 `Δ`，功效严重不足）。
- **做得了**完全不需要金标的**结构量复现检验**：候选池是 `bm25.search(issue, 200)`、AST 图与约束重连都不读 patch，上一轮最关键的结构关联（`D=0 ↔ real 短名单落在随机图族内`）本身就与金标无关。

因此本轮把确认问题从"敏感度机制"换成可回答的、更基础的问题：**上一轮在同批任务上看到的那两个 label-free 结构关联，在一批从未被任何实验看过的任务上是否仍成立？**

这**不满足**"新仓库或外部基准"的严格条件（62 个任务仍属原 12 个仓库），只能称为**未见任务集上的复现检验**。不得写成外部验证、独立复制或样本外预测。

## 输入（哈希冻结）

| 文件 | SHA256 | 用途 |
| --- | --- | --- |
| `data/swebench_full.jsonl` | `6c7bf5df9130e1f0acfd1654b267b9d79e8d86c9c1c1bd7c5a83bdf828198d9b` | 62 个留出任务的 `instance_id` / `repo` / `base_commit` / `problem_statement` |
| `data/features_full.jsonl` | `1bdb47063949bd67ca68e651a05bc989e282bf6fbac54b1f3a74ea20d782b2b4` | 仅用于取 2,232 个已用任务 ID 做差集 |
| `data/graph_controls.jsonl` | `b89bb12bcab3c5f381ba271c8b2b876d491434bb85ae4f5c5681a9c2fa0560df` | 仅用于描述性基准 P1 |

脚本启动重算三个哈希，不一致即拒绝运行。

**字段白名单（写死）**：`swebench_full.jsonl` 每行只读取 `instance_id`、`repo`、`base_commit`、`problem_statement`；**禁止读取** `patch`、`test_patch`、`FAIL_TO_PASS`、`PASS_TO_PASS`。脚本不得打开 `data/gold_symbols.jsonl`、`data/features_full.jsonl` 的 `labels`/`gold_*` 字段之外的任何内容、`data/intervention_effect_bench*.json*`、或 `paper/` 下任何文件。审计会以"破坏所有金标字段后结果逐位不变"验证。

## 总体构造（完全 label-free）

留出集 `H = {task ∈ swebench_full : instance_id ∉ features_full}`，写死由两个文件的 ID 差集决定，不按任何结果过滤、不补样本、不删失败任务（若某任务建池或建图失败，整轮判为未完成而不是静默减少 N）。

对 `H` 中每个任务，只用源码快照与 issue 文本：

```
files   = read_snapshot(SnapshotIndex(repos).path_for(task))
graph   = build_graph(files)
docs    = {node_id: document_text(node) for node_id in graph.nodes}
pool    = [node_id for node_id, _ in BM25(docs).search(problem_statement, 200)]
cand_files = [graph.nodes[i].get('file','') for i in pool]
edges   = projection(graph.edges, pool)          # 投影到候选池索引
order   = list(range(len(pool)))                  # metadata 表示，唯一表示
base    = order[:10]
real    = promote(order, reachable(order, adjacency(edges)))
rew_s   = promote(order, reachable(order, adjacency(rewire(edges, cand_files,
                                     instance_id, s, False)[0])))
          for s ∈ {11,23,37,51,71}
```

与 `run_graph_controls.py` 完全同一套函数、同一种子、同一 `ATTEMPTS_PER_EDGE`；差别只是**不传 labels、不生成 body/dense 表示**（dense 嵌入在这 62 个任务上不存在，且本轮不需要）。

定义（全部只依赖候选索引集合）：

```
D        = (1/10) Σ_{a<b} [1 − |T_a ∩ T_b| / |T_a ∪ T_b|]     T_s = set(rew_s)
in_null  = 1[ tuple(real) ∈ { tuple(rew_s) : s ∈ seeds } ]     （有序短名单落在随机图族内）
unchanged= 1[ real == base ]
churn    = |set(real) − set(base)|                              （短名单位移量，label-free）
```

`in_null` 沿用上一轮结构性核查的口径（比较有序 `top10` 元组）。

## 主检验（两条，方向事先固定，Holm 校正）

在 `H` 上各构造一个 2×2 表，行 = `D==0` vs `D>0`，列 = 目标结构量 = 1 vs 0：

| 编号 | 列 | 预期方向（来自已公开的主集合数字） | 检验 |
| --- | --- | --- | --- |
| **R1** | `in_null` | `D=0` 组比例更高（主集合 530/537=98.70% vs 341/1695=20.12%） | Fisher 精确检验，单侧 `greater` |
| **R2** | `unchanged` | `D=0` 组比例更高（主集合 362/537=67.41% vs 34/1695=2.01%） | Fisher 精确检验，单侧 `greater` |

两个原始 p 做 Holm 校正；同时报优势比（Haldane 校正，任一格为 0 时加 0.5）。

**判据（写死）**：两条 Holm 后 `p < 0.05` **且** 两条优势比均 `> 1` → **复现成立**。否则 → **未复现**。不使用 `D` 的分布差异、不换方向、不换列定义、不用别的表示或别的随机图族来救结论。

## 描述性报告（不参与主判定，不推断、不挑）

| 编号 | 内容 |
| --- | --- |
| P1 | `D` 的均值 / 中位数 / 非零比例 / `D=0` 比例，与主集合基准 `0.2496 / 0.2576 / 0.7594 / 0.2406` 的差值；按仓库 cluster bootstrap **10,000 次、种子 20261109** 给 90% / 95% 区间。区间跨 0 只写"未观察到漂移"，**不写"证明等价"** |
| P4 | `in_null`、`unchanged` 的全样本比例；`churn` 的均值与分布；`ρ_spearman(D, churn)`（只在 `H` 上，探索性） |
| P5 | 11 个仓库的逐仓库 `D=0` 比例与 `in_null` 比例，用于查看是否被单个仓库主导 |

P1/P4/P5 全部报告，不设结果门控；**不**为它们计算 p 值、**不**用其中任一项支持主结论。

## 失效判读（写死）

| 结果 | 结论怎么写 |
| --- | --- |
| R1、R2 均 Holm 后成立且 OR > 1 | "在 62 个从未进入既有实验的留出任务上，两个 label-free 结构关联方向复现；这是**同仓库新任务集上的复现检验**，不是外部验证，且**与任何金标/干预收益结论无关**"。必须同时报 62 个任务的建池/建图完成数、P1/P4/P5、Fisher 表、区间 |
| 其余任何情况 | "结构关联在未见任务集上**未复现**"；只报四个格子的计数与区间，不给机制解释、不改列定义、不换随机种子或表示重跑 |
| 任一任务建池/建图失败 | 整轮判 **未完成**，报告失败 ID，不基于剩余任务下结论 |

## 限制与禁止措辞

- 62 个任务**仍属原 12 个仓库**，不是新仓库；不构成外部基准验证、独立复制或样本外预测。
- 这 62 个任务是"参考补丁提不出符号级金标"而被排除的，与主集合存在**系统性分布差异**（patch 形态不同）。这既限制了可推广性，也使它成为一个分布外的稳健性检查；两种含义必须同时写明。
- **无符号级金标** → 本轮不产生、也不得推断任何与 `Δ`、`upside`、`downside`、recall、修复率有关的结论。
- 单个表示（metadata）、62 个任务、11 个仓库；Fisher 在小格子上功效有限，`D=0` 子集预计仅约 15 个任务。
- `unchanged` 与 `D=0` 的关联部分是构造性的（都源于图扰动幅度），**不得**称为机制、定律或因果发现。
- 禁用：external validation、independent replication、新仓库、样本外验证、confirmed mechanism、law、proven、提升修复率、优于 SOTA、首创/first、证明不可能。
- 不得把 `D` 称为"无金标方法"而忽略整个候选池与图仍来自参考补丁对应的 base_commit 快照（只是不使用 patch 内容）。

## 入稿状态与复现

`paper/` 与线上已提交 Writeup **不改动**；本结果 `eligible_for_submission = false`，留作 InterventionEffect Bench 资源的稳健性附注。

```bash
.venv/Scripts/python.exe tools/external_structure_check.py            # 全量
.venv/Scripts/python.exe tools/external_structure_check.py --smoke 1  # 只验代码路径，不打印结构量
```

产出 `data/external_structure_check.json`（全量）与 `data/heldout_structure_rows.jsonl`（62 行逐任务 label-free 结构量，可随资源一起发布）。

---

## 结果（2026-11-09，协议冻结后执行）

`.venv/Scripts/python.exe tools/external_structure_check.py`。输入哈希一致；留出集 **62 个任务**（全量 2,294 − 已用 2,232），11 个仓库；**62/62 建池与建图成功，0 失败**，故整轮有效。所有任务的 `pool_size = 200`，平均投影边数 42.9。

**主集合基准（由 `graph_controls.jsonl` 独立复算，与上一轮公开数字一致）**：`D` 均值 0.2496、中位数 0.2576、非零比例 0.7594、`D=0` 比例 0.2406；全样本 `in_null 0.3902`、`unchanged 0.1774`；`D=0` 子集（537）的 `in_null 530/537 = 0.9870`、`unchanged 362/537 = 0.6741`；`D>0` 子集（1,695）分别为 0.2012 / 0.0201。

### 主检验（两条单侧 Fisher，Holm 校正）

| 编号 | 2×2 表（`D=0` / `D>0` × 目标=1 / 0） | `D=0` 组 | `D>0` 组 | OR（Haldane） | p 原始 | p Holm | 通过 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| **R1 `in_null`** | `[[12, 0], [6, 44]]` | 12/12 = 1.000 | 6/50 = 0.120 | 171.15 | **8.594e-09** | **1.303e-08** | **是** |
| **R2 `unchanged`** | `[[10, 2], [1, 49]]` | 10/12 = 0.833 | 1/50 = 0.020 | 245.00 | **6.516e-09** | **1.303e-08** | **是** |

R1 的 Fisher 原生 OR 因零格无定义，改用 Haldane 加 0.5 修正并如实标注；R2 两者一致。按冻结判据，两条 Holm 后均 `p < 0.05` 且 OR `> 1` → **`verdict = REPLICATED_ON_UNSEEN_TASKS`**。

### P1 分布（按仓库 cluster bootstrap 10,000 次，种子 20261109）

| 量 | 留出集 | 主集合 | 差值 | 95% CI | 跨 0 |
| --- | ---: | ---: | ---: | --- | --- |
| `D` 均值 | 0.2759 | 0.2496 | +0.0263 | [−0.0995, 0.0733] | 是 |
| `D` 中位数 | 0.3211 | 0.2576 | +0.0635 | [−0.2212, 0.1174] | 是 |
| `D` 非零比例 | 0.8065 | 0.7594 | +0.0470 | [−0.2594, 0.1546] | 是 |
| `D=0` 比例 | 0.1935 | 0.2406 | −0.0470 | [−0.1546, 0.2594] | 是 |

四个区间全部跨 0 → **未观察到分布漂移**。按协议，这**不等于**证明等价：62 个任务的区间很宽（例如 `D=0` 比例为 ±15–26 个百分点），只能说没有检出差异。

### P4 / P5（描述性，不推断）

留出集全样本 `in_null 0.2903`、`unchanged 0.1774`；`churn` 均值 2.242、零值比例 0.1935；`ρ_spearman(D, churn) = 0.7184`（用 `scipy.stats.spearmanr` 正确处理并列）。

P5 逐仓库显示 62 个任务高度集中：django 26、sympy 17（合计 69%），且 django 的 `D=0` 仅 1/26 = 0.038，多个小仓库只有 1–2 个任务。因此做了下面的稳健性诊断。

### 结果产生后的稳健性诊断（post-hoc，明确不参与主判定）

**留一仓库**：逐个移除 11 个仓库之一后重算两个 2×2 表，单侧 Fisher 全部仍 `p < 0.05` 且 OR `> 1`：

- R1 `in_null`：**11/11 通过**，最大 p `6.06e-07`（移除 django 时）
- R2 `unchanged`：**11/11 通过**，最大 p `5.45e-06`（移除 django 时）

结论不是由单个仓库驱动。但这是结果后诊断，**不**写进主判定、**不**做多重比较校正、**不**用于挑选。

### 这两条关联有多少是恒等式？（必须写明的限定）

| | 主集合 `D=0` | 主集合 `D>0` | 留出集 `D=0` | 留出集 `D>0` |
| --- | ---: | ---: | ---: | ---: |
| `in_null` | 530/537 = 0.9870 | 341/1695 = 0.2012 | 12/12 = 1.000 | 6/50 = 0.120 |
| `unchanged` | 362/537 = 0.6741 | 34/1695 = 0.0201 | 10/12 = 0.833 | 1/50 = 0.020 |

- **R1 接近结构性必然**：若五个约束随机图给出完全相同的短名单，真实图（同一扰动族的一个实例）几乎必然也给出该短名单。它不是严格恒等式（主集合 `D=0` 有 7 个反例、`D>0` 有 20% 正例），但**信息量有限**，其"复现"主要说明构造在新任务上稳定，而不是发现了一个新的经验规律。
- **R2 有更多经验内容**：`D=0` 时主集合仍有 175/537（32.6%）排序发生了改变，`D>0` 时也有 34/1695 排序未变，双向都有大量例外。但 `unchanged` 与 `D=0` 共享"图扰动幅度"这一来源，**按协议不得称为机制、定律或因果发现**。

因此本轮正结果的准确表述是：**两个 label-free 结构关联在一批从未进入既有实验、且分布与主集合系统性不同（补丁提不出符号）的任务上方向复现**；其中一条接近构造性，另一条是稳健的条件关联。**不**把它写成预测能力、机制解释或性能提升。

### 审计

- 修正了两处技术问题后重跑：Fisher 的真实 p 是 `8.59e-09` / `6.52e-09`（初次实现被 `round(...,6)` 写成 `0.0`，已改为完整浮点 + 科学计数法显示）；R1 零格导致的 `Infinity` OR 已改为 `null` 并注明 Haldane 修正；`ρ(D, churn)` 改用 `scipy.stats.spearmanr` 处理并列。以上均为**实现修正，不改变协议判据或结论方向**。
- 确定性重跑：结果 JSON 与 62 行 JSONL **逐字段一致**；输出为严格 JSON（无 `Infinity`/`NaN`）。
- 零金标读取：对 3 个留出任务注入伪造的 `patch`/`test_patch`/`FAIL_TO_PASS`/`PASS_TO_PASS` 后 `one_task()` 输出逐字段不变（`TASK-LEVEL LEAKAGE CHECK: True`）；把 `graph_controls.jsonl` 所有 `symbol`/`file`/`gained`/`lost`/`gold_total`/`pool_gold` 替换为随机数后主集合基准逐字段不变（`BASELINE LEAKAGE CHECK: True`）；62 行输出只含 `instance_id, repo, D, D_zero, in_null, unchanged, churn, pool_size, edges`，与主集合 ID **零重叠**。
- 既有 **211 项 unittest 全过**；`paper/` 与线上已提交 Writeup **未改动**。

### 限制

62 个任务**仍属原 12 个仓库**，不是新仓库，不构成外部基准验证、独立复制或样本外预测；它们是"参考补丁提不出符号级金标"而被排除的，与主集合存在系统性分布差异，既是限制也是一次分布外稳健性检查；**无符号级金标 → 本轮不产生也不得推断任何与 `Δ`、`upside`、`downside`、recall、修复率有关的结论**；只用 metadata 单表示；`D=0` 子集仅 12 个任务；Fisher 在零格上依赖 Haldane 修正；P1 区间宽，跨 0 只表示未检出差异。

### 交付与下一步

新增 `docs/experiments/heldout-structure-replication.md`（本文件）、`tools/external_structure_check.py`、`data/external_structure_check.json`、`data/heldout_structure_rows.jsonl`（62 行 label-free 结构量，可随 InterventionEffect Bench 资源一同发布，MIT）。

**入稿状态**：`eligible_for_submission = false`；本结果只作为资源的**稳健性附注**，不单独构成论文主张，不改动 `paper/` 与线上 Writeup。

严格意义上的外部确认仍缺**新仓库**：本地只有原 12 个仓库的快照，主赛道 119 个确认任务（fastapi / rich / httpx）只在 Kaggle 云端且按规则冻结。若要把这条线推到可发表强度，需要先取得独立仓库的源码快照与候选池构建能力，再另开预注册；本轮不自动开启，也不把同仓库新任务标成外部验证。
