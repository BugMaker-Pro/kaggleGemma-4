# InterventionEffect Bench v0：预注册协议（2026-11-09）

## 冻结状态

本协议在**查看任何评测结果之前**写入冻结。此前只核对了文件存在性、字段结构、行数、输入哈希，以及上一轮已记录的 `Δ` 稀疏度与六个干预前特征的分布。未查看任何策略的 risk–coverage 曲线、未比较任何策略与基线。

写入时间：2026-11-09 22:2x（北京时间）。本工作**不改动**已提交的 Kaggle Writeup 与 `paper/` 任何文件。

## 定位（查新后的裁决）

2026 年公开工作已覆盖：选择性检索与任务级弃权（Repoformer、CodeRefuser）、级联/恢复的风险校准（BalanceRAG、CodeRescue、RSCB-MC、HG-CRC、ToolChain-CRC）、反事实校准缺口（Agent Retrieval Bench）、等预算呈现（CQ2-CARE）、文件级结构呈现（RepoNav）。因此本协议**不提出新的选择性/校准算法**，也不声称首创反事实对照评测。

本协议交付的是别人没有的一件东西：**逐任务的、由约束随机图对照派生的检索干预效应真值**，以及用它做跨策略审计的一套指标。标签是**从参考补丁自动派生的静态定位目标**（已独立复核 279/300），**不需要运行 agent、执行测试、修复成功或人工标注**；注意这不是"无金标"，金标仍来自参考补丁，且只代表一种修复的目标位置（沿用稿件 §7 的限制）。

与 Agent Retrieval Bench（427 样本、25 仓库、文件级、错误仓库对照）的差异仅在：**符号级、2,232 任务、度/文件匹配的随机重连对照、独立金标审计与逐任务可复算**。

## 输入（哈希冻结）

| 文件 | SHA256 |
| --- | --- |
| `data/graph_controls.jsonl` | `b89bb12bcab3c5f381ba271c8b2b876d491434bb85ae4f5c5681a9c2fa0560df` |
| `data/features_full.jsonl` | `1bdb47063949bd67ca68e651a05bc989e282bf6fbac54b1f3a74ea20d782b2b4` |
| `data/cost_budget.jsonl` | `2ee7e122485a59d60929659dd39af9fc5b21c53a9d3a7f4f149b8c266787103a` |
| `data/gold_symbols.jsonl` | `2fa161dc437993153e2d0b1834a88a89553270c3ca1978bcd3db08e65eba25ad` |

脚本启动重算哈希，不一致即拒绝运行。

## 资源：`data/intervention_effect_bench.jsonl`（宽表，每行一个任务）

| 字段 | 内容 |
| --- | --- |
| `instance_id`, `repo`, `gold_total`, `pool_size`, `pool_gold` | 任务标识与金标规模 |
| `pre_intervention` | 六个干预前特征（`margin_10_11`, `top5_mass`, `seed_file_spread`, `seed_degree`, `evidence_top10`, `score_decay`），只读 `features_full` 的 `rows`/`files` |
| `char_budget` | 仅 Lite 任务：16,000 字符下 definition / file 两种呈现的 recall，来自 `cost_budget.jsonl` |
| `representations.{metadata,body,dense}` | `base`、`real`、`file` 三种对照，以及 `rewired`（5 个匹配随机图种子）与 `rewired_pair`（5 个严格随机图种子）的逐任务 `symbol`/`file`/`gained`/`lost` |
| `representations.*.derived` | `delta`、`churn`、`efficiency`、`harm`、`null_spread`、`null_mean` |

许可：仓库根 `LICENSE`（MIT）。不含仓库快照、模型权重或官方比赛数据。

## 新指标（现在写死）

对任务 `i`、表示 `r`：

```
delta_i   = real.symbol - base.symbol            (已核对 == (real.gained-real.lost)/gold_total)
churn_i   = (real.gained + real.lost)/gold_total  (总位移)
efficiency_i = delta_i/churn_i  (churn_i=0 时记 0)
harm_i    = max(-delta_i, 0)
```

策略在覆盖率 `q` 下选中 `q` 比例的任务实施干预，未选中任务不干预（收益 0）。报告**选中子集上的条件量**（不与 `q` 相乘，因为覆盖本身是横轴）：

| 指标 | 定义 | 方向 |
| --- | --- | --- |
| `gain@q` | `mean(delta \| selected)` | 越高越好 |
| `risk@q` | `mean(harm \| selected)` | 越低越好 |
| `harm_rate@q` | `P(delta<0 \| selected)` | 越低越好 |
| `saving@q` | `1 - q` | 干预节省率 |
| `AURC` | `risk@q` 对 `q` 的梯形积分（网格见下） | 越低越好 |
| `AUGC` | `gain@q` 对 `q` 的梯形积分 | 越高越好 |

`always`（全干预）在所有 `q` 上是水平线：`gain = mean(delta)`、`risk = mean(harm)`；`never` 是退化点 `q=0`。**这是唯一公平的基线**：选择性策略用覆盖换安全，不能用总体净收益与全干预直接比大小。

覆盖网格预先固定：`q ∈ {0.1, 0.2, 0.3, 0.5, 0.8, 1.0}`，主覆盖 **`q = 0.2`**。

## 策略清单（预先固定，7 个）

| 策略 | 分数 | 性质 |
| --- | --- | --- |
| `never` | — | 基线，不干预 |
| `always` | — | 基线，全干预 |
| `random` | 固定种子 20261109 的随机排序 | null 对照 |
| **`null_spread`** | `−std(5 个 rewired 种子的 symbol)`，**分歧小优先** | **主检验**：只用随机图对照派生的不确定性，不含 `real.symbol` |
| `margin_low` | `−margin_10_11` | 次要；方向来自 2026-11-09 探索性探针，**明确标注 exploratory**，只作样本外验证 |
| `evidence_high` | `evidence_top10` | 次要，探针中高收益但高风险 |
| `oracle` | `delta` 本身 | 上界，不可部署 |

**排除恒等式陷阱的设计决定**：不使用 `topology_surplus = real.symbol − mean(rewired.symbol)` 作为策略分数。它与被预测量 `delta` 共享 `real.symbol`（`delta = real.symbol − base.symbol`），会造成机械相关，属于上一轮讨论已否决的同义反复。`null_spread` 只读取随机图对照的离散度，不读真实图结果。

## 分折、推断与校正

- 12 个仓库按名称排序交替分成 6/6 两折；两次互换，每个任务恰好在一个测试折被评估一次。每个折内按分数取 `top ⌈q·n⌉`，合并两折的选中集合后计算指标。
- 主表示预先固定为 `metadata`；`body`、`dense` 只报点估计，不作推断。
- 主检验：`q=0.2` 时 `null_spread` 相对 `always` 的 `Δgain = gain@0.2 − mean(delta)` 与 `Δrisk = risk@0.2 − mean(harm)`。按仓库 cluster bootstrap **10,000 次、种子 20261109** 给 95% 区间与双侧 p（bootstrap 内 `always` 基线在同一重采样子集上重算）。
- 多重比较：三个数据驱动策略（`null_spread`/`margin_low`/`evidence_high`）的 `Δgain` 双侧 p 做 Holm 校正。`Δrisk` 为次要指标，只报区间不参与主判定。

## 失败判读（现在写死）

| 结果 | 结论怎么写 |
| --- | --- |
| 主策略 `Δgain` 的 cluster 区间下界 > 0 **且** `Δrisk` 上界 < 0 **且** Holm 后成立 | 可写"反事实对照派生的离散度能识别更安全的干预子集"；必须同时报三表示、全曲线、区间，不得外推 |
| 否则 | 写"在符号级、留出仓库上**未观察到**反事实校准信号的稳定收益，与 Agent Retrieval Bench 报告的文件级校准缺口方向一致"；明确这不是证明不可行，并把**基准本身与新指标**作为主要交付 |
| 结果混杂 | 只报数字与区间，不给机制解释，不挑最好看的策略或表示当结论 |

无论哪种结果，**七个策略、六个覆盖点、三个表示全部报告**，不设结果门控；`oracle` 与 `random` 必须同表给出，以便读出上界与 null。

## 禁止措辞与外推边界

禁用：首创/first、law、mechanism、predicts all interventions、证明不可预测、提升修复率、优于 SOTA。不得声称本基准优于 CORE-Bench（180K queries / 106K 标签）的规模；卖点只是"干预效应"这一维度。不得把结论外推到生成查询、LLM 反馈、其他语言、其他基准或 agent 下游修复。

## 复现

```bash
.venv/Scripts/python.exe tools/intervention_effect_bench.py
```

产出 `data/intervention_effect_bench.jsonl` 与 `data/intervention_effect_bench_results.json`。

---

## 结果（2026-11-09，协议冻结后执行）

`.venv/Scripts/python.exe tools/intervention_effect_bench.py`。输入哈希一致；资源 2,232 行、12 仓库、290 个 Lite 任务带字符预算；重跑逐字段一致；既有 211 项单元测试全过。`oracle` 在 `q=0.2` 的 `utility = 0.04225`，与 2026-11-09 独立复算的 `mean(max(Δ,0)) = 0.04225` **完全一致**（跨脚本核对通过）。

全样本（metadata）：`meanΔ = +0.0219`、`meanHarm = 0.0203`、**88.4% 任务 Δ 为零**；body `−0.0001`、dense `+0.0064`。

### metadata @ q = 0.2（七策略，全部报告）

| 策略 | gain@.2 | risk@.2 | harm% | **utility@.2** | AURC | AUGC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| never | 0 | 0 | 0 | 0 | — | — |
| **always（基线）** | 0.0219 | 0.0203 | 0.040 | **0.0219** | 0.0183 | 0.0197 |
| random | 0.0354 | 0.0223 | 0.051 | 0.0071 | 0.0185 | 0.0265 |
| **null_spread（主）** | 0.0033 | 0.0163 | 0.025 | 0.0007 | 0.0151 | 0.0037 |
| margin_low | 0.0302 | 0.0176 | 0.031 | 0.0060 | 0.0164 | 0.0234 |
| evidence_high | 0.0395 | 0.0430 | 0.065 | 0.0079 | 0.0287 | 0.0253 |
| oracle（上界） | 0.2110 | 0.0000 | 0.000 | 0.0422 | 0.0020 | 0.0998 |

### 主检验（cluster bootstrap 10,000 次，Holm）

| 策略 | Δgain [95% CI] | p | Holm | Δrisk [95% CI] |
| --- | --- | ---: | ---: | --- |
| **null_spread** | **−0.0188 [−0.0259, −0.0088]** | 0.0008 | **0.0025** | −0.0038 [−0.0102, 0.0033] |
| margin_low | +0.0077 [−0.0071, 0.0231] | 0.2626 | 0.3248 | −0.0023 [−0.0116, 0.0097] |
| evidence_high | +0.0175 [−0.0076, 0.0449] | 0.1624 | 0.3248 | **+0.0227 [0.0150, 0.0321]** |

**按冻结的判读表：未观察到**（主策略区间不跨零但在错误方向，Δrisk 区间跨 0）。三个数据驱动策略在留出仓库上都没有同时改善 gain 与 risk；`evidence_high` 显著**升高**风险（issue 里明写线索的任务，图干预反而更易有害），`null_spread` 显著选出**更差**子集。

**结果产出后补充的描述性指标（不参与主检验）**：`gain@q` 是条件量，在 88% Δ 为零的数据上会放大小 `q` 的抽样噪声——`random` 看起来 0.0354 > 0.0219，但总体 `utility@0.2` 只有 0.0071。因此补 `utility@q = coverage × gain@q` 与 `overall_risk@q`，并与独立复算的 oracle 上界核对一致。这是指标修正，不改变主检验与判读。

### 主检验之外：方向反转（**post-hoc，明确标注，不得写进投稿结论**）

独立审计发现预注册把 `null_spread` 的方向写反了。反事实离散度与 Δ 在三个表示、两组独立随机图构造上**一致正相关**：

| 表示 | ρ(null_spread, Δ) | ρ(pair_spread, Δ) |
| ---: | ---: | ---: |
| metadata | 0.2563 | 0.2506 |
| body | 0.1008 | 0.1362 |
| dense | 0.1530 | 0.1899 |

`rewired_pair` 是另一组更严格的随机图族（5 个不同种子），方向一致提供了弱独立性证据，但**仍属同一批任务与同一金标，不是独立复制**。

探索性地把方向反过来（同样留出折、`q=0.2`，**事后**计算）：metadata 上 `null_spread_HIGH` 的 `gain = 0.0987`（约 4.5× 基线），但 `risk = 0.0376`、`harm% = 0.083`（约 2× 基线），`utility = 0.0198` 仍略低于全干预的 0.0219；`pair_spread_HIGH` 同向（0.0761 / 0.0314 / 0.067）。

**由此生成、尚未确认的机制假设**：反事实对照的离散度测量的不是"这个任务安不安全"，而是"**这个任务对图干预有多敏感**"——它同时放大正收益与负收益，因此用它校准出的阈值给出的是"高收益、高风险"的前沿，而不是更安全的子集。这可以解释 Agent Retrieval Bench 报告的"反事实校准阈值在自然无 gold 案例上失效"：校准信号测的是敏感度，不是安全性。

该假设由本 v0 数据产生，属事后假设生成，**不得进入已提交 Writeup、不得称为确认性结果、不得据此调阈值或挑表示**。确认必须在**新的预注册 + 外部基准或新仓库**上完成，并预先固定方向、主指标与失效判读。

### 交付与边界

新资源 `data/intervention_effect_bench.jsonl`（逐任务 × 3 表示 × 13 臂的效应与位移，含 6 个干预前特征、290 条字符预算曲线、MIT 许可）、新指标定义、七策略全曲线、两个稳定的样本外失效条件（显式证据臂升风险、低敏感度臂降收益）。不声称首创反事实对照评测，不与 CORE-Bench 比规模，不外推到 agent 修复率或其他语言。

**入稿状态**：`paper/` 与线上已提交 Writeup **均未改动**；本结果留作 Non-Archival 下一版资源论文的核心材料。
