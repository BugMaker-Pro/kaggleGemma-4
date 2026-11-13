# 干预敏感度假设的确认性协议（2026-11-09，协议 v1 冻结）

## 冻结状态与诚实定位

本协议在**查看本轮任何信号—结果关联之前**写入冻结。冻结前只做了四类检查：文件存在性与行数、arm 名称与 `top10` 字段类型/长度、按下面公式计算的 `D` 的**边际分布与非零比例**、仓库计数。未计算 `D` 与 `Δ`/`upside`/`downside`/`harm` 的任何相关、未做任何分组比较、未看 `null_calibrated_graph.jsonl` 的任何 `symbol` 数值、未挑 `q` 或表示。

**必须写明的来源限制**：本假设来自 `docs/experiments/intervention-effect-bench.md` §"方向反转"的 **post-hoc 发现**（同一批 2,232 任务、同一金标、同一 12 仓库）。因此本轮**不是独立复制**，也不满足上一轮写下的"外部基准或新仓库"确认条件。本轮能做的、且只声称能做的，是两件事：

1. **排除一个具体混杂**：上一轮的主信号 `null_spread = std(5 个 rewired 种子的 symbol)` 含 `labels`；本轮主信号改为**完全不含金标**的随机图 top-10 集合分歧度，彻底排除"信号与被预测量共享 recall 分数"这一类质疑。
2. **把方向变成事前固定**：上一轮的方向 reversal 是事后翻的；本轮把"高分歧 → upside 与 downside 同时上升"写成可证伪的事前预测，并写死失效判读、校正与禁止措辞。

即使三条主检验全部成立，结论也只能写"**同一批任务上的内部确认**"，不得写 confirmed mechanism / independent replication / external validation。外部确认仍需新仓库或外部基准，本轮不提供。

本工作**不改动**已提交的 Kaggle Writeup 与 `paper/` 任何文件；结果不入投稿结论。

## 研究问题与假设

`docs/experiments/intervention-effect-bench.md` 事后提出的解释是：反事实对照的离散度测量的不是"这个任务安不安全"，而是"这个任务对图干预有多敏感"，因而会**同时**放大正收益与负收益；用它做选择性干预得到的是"高收益、高风险"前沿，而不是更安全的子集。

两个互斥的事前预测（在同一批数据上可区分）：

| | 高离散度子集的 `upside` | 高离散度子集的 `downside` / `harm_rate` |
| --- | --- | --- |
| 安全性解释（v0 预注册时的方向） | 低 | **低** |
| **敏感度假设（本轮主假设）** | **高** | **高** |

区分点就是 `downside` 与 `harm_rate` 的符号；上一轮"高离散度组 harm% 0.083 vs 基线 0.040"是 post-hoc 观察到的，本轮把它当作待确认的预测重新检验。

## 输入（哈希冻结）

| 文件 | SHA256 | 用途 |
| --- | --- | --- |
| `data/graph_controls.jsonl` | `b89bb12bcab3c5f381ba271c8b2b876d491434bb85ae4f5c5681a9c2fa0560df` | 主信号 + 主结果变量 |
| `data/null_calibrated_graph.jsonl` | `9c523214103a2270758c3d30e7e822217d86780d424c1910531fa07f3bcdec27` | 次要跨干预族确认 C4 |
| `data/graph_controls_context.jsonl` | `f6f16512c104bfe412d1198d939a4bcb9fa3ea54f6e13524f69c43e1822b7c20` | 仅溯源，脚本不读取 |

脚本启动重算前两个哈希，不一致即拒绝运行。

### 主信号不含金标的依据（冻结前已核验）

`experiments/graph_controls.py` 文件头明确："All rankings and randomization operate on candidate indices, files, and graph edges; they never accept gold labels"。`evaluate()` 中 `ranked` 的每个 `top10` 由 `order` 与图邻接经 `promote()` 产生；`labels` 只传给 `metrics()` 用于计算 `symbol`/`gained`/`lost`。`data/graph_controls_context.jsonl` 的三个 `orders` 分别是原始候选序、body-BM25 序、冻结的 dense 序，均不含标签。

**与上一轮被否决的恒等式陷阱的区别**：`topology_surplus = real.symbol − mean(rewired.symbol)` 与被预测量 `Δ = real.symbol − base.symbol` 共享 `real.symbol`，属机械相关。本轮信号不读 `real` 臂、不读 `base` 臂、不读任何 `*symbol`/`gained`/`lost`/`gold_*`。二者共享的只是**所有臂共用的输入**（候选池顺序与图构造机制），不是被预测量的分子或分母：`D` 是集合分歧度，`Δ` 是命中数差；`D=0` 时 `Δ` 可任意，`D` 高时 `Δ` 也可为 0。这不构成恒等式。

## 主信号（写死，无自由参数）

对任务 `i`、表示 `r`、随机图族 `f`、种子 `s ∈ {11,23,37,51,71}`，令 `T(i,r,f,s)` 为对应 arm 的 `top10` **候选索引集合**（10 个整数）。定义平均成对 Jaccard 距离：

```
D(i, r, f) = (1/10) · Σ_{a<b} [ 1 − |T_a ∩ T_b| / |T_a ∪ T_b| ]
```

其中 `a<b` 遍历 5 个种子的 `C(5,2)=10` 个无序对，取值域 `[0, 1)`。

| 记号 | 定义 | 地位 |
| --- | --- | --- |
| `D_main` | `D(i, metadata, rewired)` | **主信号** |
| `D_pair` | `D(i, metadata, rewired_pair)` | 次要确认 C1，`rewired_pair` 是保持逐文件对度数的更严格随机图族 |
| `D_body` / `D_dense` | `D(i, body|dense, rewired)` | 次要确认 C2 |

冻结前的边际检查（只看信号，不看结果）：`rewired` 族三表示的非零比例 75.2%–76.9%，均值 0.248–0.261，q90 ≈ 0.50；`rewired_pair` 族非零比例 44.3%–50.3%，中位数在 body/dense 为 0。信号非退化，但 `pair` 族有大量并列 → 并列处理必须写死（见下）。

**确定性并列处理**：排序键为 `(−D, tie)`，其中 `tie = int.from_bytes(sha256(instance_id.encode()).digest()[:8], 'big')` 升序。不用行序、不用随机数、不依赖结果变量。

## 结果变量（含金标，明确与主信号区分）

对任务 `i`、表示 `r`，`Δ(i,r) = arms.real.symbol − arms.base.symbol`：

```
upside_i   = max( Δ_i, 0)
downside_i = max(−Δ_i, 0)
harm_i     = 1[Δ_i < 0]
```

`upside + downside = |Δ|`，`upside − downside = Δ`。`Δ` 与 `(real.gained − real.lost)/gold_total` 的一致性在 v0 已核对，本脚本再次逐行断言。

跨干预族 C4 用 `data/null_calibrated_graph.jsonl` 的 `calibrated` 臂：`Δ_cal = arms.calibrated.symbol − arms.base.symbol`，同样定义三个量。该文件的排序也是 label-free（脚本文件头："Ranking is label-free; gold is read only after each shortlist is constructed"），但**干预机制不同**（只提升超过随机图 reach 均值的真实邻居），因此作为"敏感度是否跨干预类型成立"的次要检验。

## 选集、分折与阈值

- 覆盖 `q = 0.2` 为**主覆盖**，写死；`q = 0.3` 仅作次要方向一致性 C3。
- 12 个仓库按名称排序交替分成 6/6 两折（与 v0、可预测性实验完全相同）。每个折内按 `(−D, tie)` 取 `top ⌈q·n_fold⌉`，合并两折选中集 `S`。
- **分折的定位要说清楚**：`D` 是 label-free 且无训练、无拟合参数，分折在这里**不防过拟合**；它的唯一作用是让 top-q 阈值不在全样本上一次性挑定，保持与前两轮实验的可比性。不得把本结果称为"out-of-fold 预测"或"样本外验证"。
- `D` 的构造不使用任何结果变量，因此**不存在标签泄漏**；但同一批任务与金标仍使所有估计相关，cluster bootstrap 按仓库重采样以部分反映该相关性。

## 主检验（三条，事先固定，Holm 校正）

全部在 `D_main` + `metadata` + `real` 干预 + `q = 0.2` 上。对选中集 `S`，基线在**全部任务**上计算：

```
Δupside   = mean(upside   | S) − mean(upside   | all)
Δdownside = mean(downside | S) − mean(downside | all)
Δharm     = mean(harm     | S) − mean(harm     | all)
```

| 编号 | 预测（敏感度假设） | 双侧 p 的判据 |
| --- | --- | --- |
| S1 | `Δupside > 0` | bootstrap CI 下界 > 0 且 Holm p < 0.05 |
| S2 | `Δdownside > 0` | 同上 |
| S3 | `Δharm > 0` | 同上 |

cluster bootstrap **10,000 次、种子 20261109**，按 12 个仓库有放回重采样；**每次重采样后重新按折选 `top ⌈q·n_f⌉`、重新算 `all` 基线、重新算三个差值**（不是固定 `S` 后只重算基线）。95% 区间取 2.5/97.5 分位，双侧 `p = 2·min(P(stat≤0), P(stat≥0))` clip 到 1。三个主 p 做 Holm 校正。

**适用性前置检查（写死，不可事后放宽）**：计算 `ρ_spearman(D_main, null_spread)`，其中 `null_spread = std(5 个 rewired 种子的 symbol)` 来自 `graph_controls.jsonl`。它是**描述性等价诊断，不是主信号**，只在事后用来判断本轮检验的是不是上一轮 post-hoc 看到的那个量。

- 若 `ρ < 0.30`：无论 S1–S3 结果如何，主判定强制为"**未确认**"，结论写"label-free 结构分歧度与上一轮 post-hoc 使用的离散度不等价，本轮检验了另一个量，不构成对该假设的确认"。
- 若 `ρ ≥ 0.30`：按 S1–S3 判定。

## 失效判读（写死）

| 结果 | 结论怎么写 |
| --- | --- |
| `ρ ≥ 0.30` **且** S1/S2/S3 三条 Holm 后全部成立 | "在同一批 2,232 任务上，用完全不含金标的结构分歧度信号，去除共享 recall 混杂后，**内部确认**了高离散度子集的 upside 与 downside 同时上升；与'离散度=安全性'不相容"。必须同时报三表示、两信号族、两覆盖点、全曲线与区间；**必须附**"非独立复制、非外部验证、非投稿结论" |
| 其余任何情况 | "敏感度假设在本轮**未获内部确认**"；只报数字与区间，不给机制解释、不换方向重跑、不挑表示或 `q` 当结论 |
| 结果混杂 | 同上，只报数字，不解释 |

**不得**因为 S1 成立而 S2/S3 不成立就改写为"仍有收益"；那属于事后改判读。

## 次要确认清单（事先固定，只报方向与点估计，不推断、不参与主判定、不得用于救结论）

| 编号 | 内容 |
| --- | --- |
| C1 | `D_pair` 在 metadata 上的 `Δupside/Δdownside/Δharm` 方向 |
| C2 | `D_body`、`D_dense` 在各自表示上的三条差值方向 |
| C3 | `q = 0.3` 上主信号的三条差值方向 |
| C4 | 跨干预族：`calibrated` 臂在 metadata 上、用同一个 `D_main` 的三条差值方向；同时报 `Δ_cal` 的零值比例与 `base.symbol` 与 `graph_controls` 的一致性 |
| C5 | 五分位桶（`D_main` 全样本等分，metadata）上 `mean(upside)`、`mean(downside)`、`mean(Δ)` 序列 |
| C6 | 低离散度组（bottom `q=0.2`）的三条差值，作为对称预测的描述性对照 |

C1–C6 全部报告，不设结果门控；**不**为它们计算 p 值、**不**做 Holm、**不**用其中任一项支持主结论。

## 禁止措辞与外推边界

禁用：confirmed mechanism、proven、law、universal、independent replication、external validation、out-of-fold prediction、样本外验证、提升修复率、优于 SOTA、首创/first、证明不可能、安全性校准、optimal。

不得把本结果外推到：生成式查询、LLM 反馈、其他语言、其他基准、agent 下游修复、其他干预类型（C4 只是同批任务的一个方向对照）。不得声称 12 仓库的 cluster bootstrap 消除了金标相关性。不得把 `D` 称为"无金标方法"而忽略 `Δ` 仍来自参考补丁派生的静态定位目标（沿用稿件 §7 限制）。

## 复现

```bash
.venv/Scripts/python.exe tools/confirm_intervention_sensitivity.py
```

产出 `data/intervention_sensitivity_confirmation.json`：输入哈希、`ρ` 适用性检查、三条主检验的点估计/区间/原始 p/Holm p、主判定、C1–C6 全部描述量、`verdict` 字符串。脚本不得读取 `data/intervention_effect_bench*.json*` 或 `paper/` 下任何文件。

---

## 结果（2026-11-09，协议冻结后执行）

`.venv/Scripts/python.exe tools/confirm_intervention_sensitivity.py`。输入哈希一致；2,232 任务 / 12 仓库；`Δ` 与 `(gained−lost)/gold_total` 逐行断言通过；`null_calibrated_graph.jsonl` 的 `base.symbol` 与 `graph_controls.jsonl` **0 处不一致**。

**审计**：重跑逐字段 `deterministic rerun: True`；既有 **211 项单元测试全过**（`python -m unittest discover -s tests -q`）；把 `graph_controls.jsonl` 中所有 `symbol`/`file`/`gained`/`lost`/`gold_total`/`pool_gold`/`graph_edges` 全部替换为随机数后，六个 `D` 向量的最大绝对变化均为 **0.0**（`LEAKAGE CHECK: True`），即主信号确实完全不依赖金标派生量。`paper/` 与线上已提交 Writeup **未改动**。

折大小为 692 / 1540（django 824 个任务全部落在同一折），这是"12 仓库按名称交替"既定规则的结果，协议已说明分折**不防过拟合、只保持与前两轮可比**，因此不据此做样本外推断。

### 适用性前置检查（协议写死的门槛）

`ρ_spearman(D_main, null_spread) = 0.2681 < 0.30` → **门槛失败**。按冻结协议，主判定**强制**为 `NOT_CONFIRMED_SIGNAL_NOT_EQUIVALENT`：完全 label-free 的集合分歧度与上一轮 post-hoc 使用的"随机图命中数标准差"只有中等相关，**不是同一个量**，本轮不构成对原假设的确认。

### 主检验（metadata / `real` vs `base` / `D_main` / q=0.2 / 10,000 cluster bootstrap / Holm）

基线：`upside 0.042248`、`downside 0.020321`、`harm_rate 0.040323`、`meanΔ 0.021928`（88.4% 任务 Δ 为零）。选中组：`meanΔ 0.041414`、`harm_rate 0.060403`、`utility@0.2 = 0.008283`。

| 编号 | 点估计 | 95% CI | p 原始 | p Holm | 通过 |
| --- | ---: | --- | ---: | ---: | --- |
| S1 `Δupside` | **+0.031523** | **[0.013376, 0.049504]** | 0.0002 | **0.0006** | **是** |
| S2 `Δdownside` | +0.012037 | [−0.004530, 0.022054] | 0.1136 | 0.2272 | 否 |
| S3 `Δharm` | +0.020080 | [−0.006293, 0.038781] | 0.1330 | 0.2272 | 否 |

**即使忽略适用性门槛，S2/S3 也不成立**，即"三条全部通过"本身未满足。两条判据独立地指向同一结论：`verdict = NOT_CONFIRMED_SIGNAL_NOT_EQUIVALENT`。按冻结的失效判读表，只报数字与区间，不给机制解释，不换方向重跑，不挑表示或覆盖率当结论。

### 次要确认（C1–C6 全部报告，不推断、不参与主判定）

| 编号 | `Δupside` | `Δdownside` | `Δharm` | 选中 `meanΔ` | 选中 `harm%` | 方向与主检验一致 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| C1 `D_pair` | +0.036001 | +0.014723 | +0.031266 | 0.043207 | 0.071588 | 是 |
| C2 body | +0.010258 | +0.014728 | +0.028572 | **−0.004580** | 0.076063 | 否（净收益转负） |
| C2 dense | +0.028914 | +0.012806 | +0.026782 | 0.022496 | 0.073826 | 是 |
| C3 q=0.3 | +0.024750 | +0.011741 | +0.023857 | 0.034937 | 0.064179 | 是 |
| C4 `calibrated` 臂 | +0.035215 | +0.011093 | +0.020979 | 0.039991 | 0.058166 | 是 |
| C6 低离散度组 | −0.037774 | −0.020321 | −0.040323 | 0.004474 | **0.000000** | 对称对照 |

C4 的 `Δ_cal` 零值比例 89.96%，`base.symbol` 0 处不一致；跨干预族方向一致但**仍属同一批任务与同一金标**，不构成独立复制。

C5 五分位桶（`D_main` 从高到低）：

| 桶 | 平均 `D` | `mean(upside)` | `mean(downside)` | `mean(Δ)` | `harm%` |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1（最高） | 0.5058 | 0.074994 | 0.033383 | 0.041612 | 0.064877 |
| 2 | 0.3837 | 0.053736 | 0.032495 | 0.021241 | 0.067114 |
| 3 | 0.2492 | 0.050570 | 0.025081 | 0.025489 | 0.044843 |
| 4 | 0.1087 | 0.027358 | 0.007598 | 0.019760 | 0.020179 |
| 5（最低） | 0.0000 | 0.004484 | 0.002990 | 0.001495 | 0.004484 |

### 结构性核查（结果产生后的诊断，不改变主判定）

最低桶 `D=0` 共 537 个任务，其中 **530 个的 `real.top10` 与某个 rewired 随机图的 `top10` 完全相同且 `Δ=0`**；仅 7 个例外，且这 7 个的 `real.top10` 都不在随机图族的短名单内。另有 175 个 `D=0` 任务 `real.top10 ≠ base.top10`（排序变了但换进换出的候选都不命中金标）。

因此 C5 最低桶的"几乎零效应"**主要是结构性可推出的**：随机图扰动不改变短名单时，真实图干预也基本不改变短名单。这**不是**一个统计预测发现，不得包装成"识别出了安全的无干预子集"——与前面几轮已否决的恒等式陷阱同类。

这一点也解释了适用性门槛为何失败：`null_spread` 是随机图**命中数的离散度**，而 `D` 是随机图**短名单集合的分歧度**；在 `D>0` 的 1,695 个任务中，`real.top10` 有 1,354 个**不在**随机图族的短名单内，两种离散度可以脱钩。

### 描述性观察（**hypothesis-generating，明确不得入稿、不得改判读**）

- 五分位桶上 `upside` 从 0.004484 单调升到 0.074994，但 `downside` 在第 2 桶已达 0.032495、顶桶仅 0.033383 —— 风险侧在中高分位**趋于饱和**，正收益侧继续上升。也就是说，"对称地同时放大正负"这一假设在描述层面也不像成立。
- 同覆盖公平比较下，`utility@0.2 = 0.008283`，约为随机选择（≈ 0.004386）的 1.9 倍，但仍**远低于**全干预 `always` 的 0.021928。与 v0 一致：选择性干预在总体净收益上仍不划算。
- body 表示上选中组净收益转负、harm 上升，方向不一致；这是预先固定的次要对照，如实报告，不用于支持或推翻主结论。

以上三条**只能**作为下一轮新预注册的假设来源，本轮不据此提出新主张、不调阈值、不挑表示。

### 对 v0 post-hoc 发现的限定

`docs/experiments/intervention-effect-bench.md` §"方向反转"提出的"离散度 = 干预敏感度而非安全性"假设，其信号 `null_spread` **含 labels**。本轮换成完全 label-free 的结构分歧度后：两信号仅 `ρ = 0.2681`、正收益侧放大可复现、风险侧放大未达显著、且最低桶效应结构性可推出。因此该机制假设**仍未经确认**，并新增一条限定：它至少部分可能是金标派生量的产物，不能不加区分地移植到无金标信号上。该假设继续维持"post-hoc、不得入稿"的状态。

### 限制

同一批 2,232 任务、同一金标、12 仓库 → **非独立复制、非外部验证、非样本外预测**；88.4% 的 `Δ` 为零使风险侧事件稀疏、区间偏宽；折大小 692/1540 不平衡；按仓库的 cluster bootstrap 只部分反映任务间相关性。不得外推到生成式查询、LLM 反馈、其他语言、其他基准或其他干预类型，不得把 `D` 称为"无金标方法"而忽略 `Δ` 仍来自参考补丁派生的静态定位目标。

### 交付与下一步

新增 `docs/experiments/intervention-sensitivity-confirmation.md`（本文件）、`tools/confirm_intervention_sensitivity.py`、`data/intervention_sensitivity_confirmation.json`。协议、三条主检验、六组次要对照、结构性核查与审计全部落盘。

**入稿状态**：`paper/` 与线上已提交 Writeup 均未改动；本结果 `eligible_for_submission = false`。

真正满足 v0 写下的确认条件仍需**新仓库或外部基准**上重跑图对照（需要 `data/repos` 快照与独立任务集），这是数据可得性问题，应先核查再决定是否另开预注册；本轮不自动开启，也不把同一批任务上的任何重做标记为外部验证。
