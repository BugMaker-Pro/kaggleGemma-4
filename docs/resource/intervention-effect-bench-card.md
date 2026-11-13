# InterventionEffect Bench v1 — Resource Card

版本 v1 · 2026-11-09 · 许可 **MIT**（仓库根 `LICENSE`）· 校验清单 `data/bench_resource_manifest.json`

## 一句话定位

逐任务的、**由约束随机图对照派生的代码定位干预效应真值表**：不是又一个检索方法，而是让"某个图干预在这条任务上到底有没有用、代价是什么"第一次可以逐任务查表、跨策略复算。附带 62 条完全 label-free 的未见任务结构量，以及三轮预注册的结果文件。

标签是**从参考补丁自动派生的静态定位目标**（独立复核 279/300），不需要运行 agent、执行测试、修复成功或人工标注。注意：这是"无 agent 运行"，**不是"无金标"**。

## 交付文件

| 文件 | 内容 | 行数 / 规模 |
| --- | --- | --- |
| `data/intervention_effect_bench.jsonl` | 主宽表：逐任务 × 3 表示 × 13 臂的效应与位移 | 2,232 行 · 12 仓库 |
| `data/heldout_structure_rows.jsonl` | 62 个未见任务的 label-free 结构量 | 62 行 · 11 仓库 |
| `data/intervention_effect_bench_results.json` | 七策略 × 六覆盖点 × 三表示全曲线 | 主检验 + 全曲线 |
| `data/intervention_predictability.json` | 干预净收益可预测性的样本外结果 | 三表示、Holm |
| `data/intervention_sensitivity_confirmation.json` | label-free 敏感度假设确认性检验 | 三条主检验 + C1–C6 |
| `data/external_structure_check.json` | 未见任务集的结构复现检验 | 两条 Fisher + P1/P4/P5 |
| `data/bench_resource_manifest.json` | 全部文件的 SHA256 与 13 项完整性校验 | 由校验脚本生成 |

所有 SHA256 见 `data/bench_resource_manifest.json`；不含仓库快照、模型权重或官方比赛数据。

## 主宽表 schema（每行一个任务）

| 字段 | 内容 |
| --- | --- |
| `instance_id`, `repo` | 任务标识与仓库 |
| `gold_total`, `pool_size`, `pool_gold` | 金标符号总数、候选池大小、池内命中数 |
| `pre_intervention` | 6 个**干预前**特征：`margin_10_11`, `top5_mass`, `seed_file_spread`, `seed_degree`, `evidence_top10`, `score_decay`（只读 `features_full` 的 `rows`/`files`，不读标签） |
| `char_budget` | 仅 290 个 Lite 任务：16,000 字符下 definition / file 两种呈现的 recall 曲线 |
| `representations.{metadata,body,dense}` | 三个基础排序表示各自的 `base`、`real`、`same_file`、`rewired`(5)、`rewired_pair`(5) 与 `derived` |

每个臂含 `symbol`, `file`, `gained`, `lost`；`derived` 含 `delta`, `churn`, `efficiency`, `harm`, `null_spread`, `null_mean`, `pair_spread`。

```
delta       = real.symbol − base.symbol        == (real.gained − real.lost)/gold_total
churn       = (real.gained + real.lost)/gold_total
efficiency  = delta/churn                      (churn=0 记 0)
harm        = max(−delta, 0)
null_spread = std(5 个 rewired 种子的 symbol)
null_mean   = mean(5 个 rewired 种子的 symbol)
pair_spread = std(5 个 rewired_pair 种子的 symbol)
```

`rewired` 是度/文件匹配的双边交换随机图；`rewired_pair` 额外保持逐文件对度数，是更严格的敏感性对照。两者的排序与随机化都**不接受金标**（`experiments/graph_controls.py` 文件头）。

## 指标与协议

策略在覆盖率 `q` 下选中 `q` 比例任务实施干预，未选中收益为 0。网格 `q ∈ {0.1,0.2,0.3,0.5,0.8,1.0}`，主覆盖 `q=0.2`。

| 指标 | 定义 | 方向 |
| --- | --- | --- |
| `gain@q` | `mean(delta \| selected)`（条件量） | 高 |
| `risk@q` / `harm_rate@q` | `mean(harm \| selected)` / `P(delta<0 \| selected)` | 低 |
| **`utility@q`** | `coverage × gain@q`，即**全任务**上的净收益 | 高 |
| `overall_risk@q` | 全任务上的平均 harm | 低 |
| `AURC` / `AUGC` | `risk@q` / `gain@q` 对 `q` 的梯形积分 | 低 / 高 |

`gain@q` 是条件量，在 88.4% 的 `delta` 为零的数据上会放大小 `q` 的噪声，`utility@q` 是后来补的**整体量**，两者必须一起读。七个策略（`never`/`always`/`random`/`null_spread`/`margin_low`/`evidence_high`/`oracle`）与三个表示全部报告，不设结果门控。

统计约定：12 仓库按名称交替分 6/6 两折，每折内取 `top ⌈q·n⌉`；按仓库 cluster bootstrap 10,000 次、种子 20261109；多比较 Holm 校正。分折在这里的作用是让阈值不在全样本上一次性挑定，**不构成样本外预测**（基准曾用于探索性方法开发）。

## 伴随结论（每个都标好状态）

| 实验 | 结果 | 状态 |
| --- | --- | --- |
| 干预净收益可预测性 | 主表示 `ρ=0.020`，CI 跨 0，Holm p=0.731 → **未观察到** | 预注册，可作资源附注 |
| Bench v0 主检验 | `null_spread` 显著选出更差子集（Holm p=0.0025）；`evidence_high` 显著升高风险；三个数据驱动策略均未同时改善 gain 与 risk → **未观察到** | 预注册，**基准本身与指标是主要交付** |
| 敏感度假设确认 | 换成完全 label-free 的集合分歧度后，`ρ(D_main, null_spread)=0.2681 < 0.30` 触发预先写死的适用性门槛；且 `Δupside` 显著、`Δdownside`/`Δharm` 不显著 → **未确认** | 预注册，post-hoc 机制假设维持"不得入稿" |
| 未见任务集结构复现 | 62 个从未进入既有实验的任务上，两条 label-free 结构关联方向复现（Holm p≈1.3e-08，留一仓库 11/11 通过）→ **复现成立** | 预注册，**正结果，但只作稳健性附注** |

三个"未观察到 / 未确认"与一个"复现成立"必须一起给出，不能只报最后一个。

## 62 行 held-out 结构量

`data/heldout_structure_rows.jsonl` 的 9 个字段全部 label-free：`instance_id`, `repo`, `D`, `D_zero`, `in_null`, `unchanged`, `churn`, `pool_size`, `edges`。`D` 是 5 个 rewired 短名单集合的平均成对 `1−Jaccard`；`in_null` 指真实图短名单落在随机图族内；`unchanged` 指干预未改变短名单。

这 62 个任务来自 `swebench_full.jsonl` 减去 `features_full.jsonl`（2,294 − 2,232），**从未进入任何既有实验**；被排除的原因是参考补丁提不出符号级金标。它们与主集合 ID 零重叠，但**仍属原 12 个仓库，不是新仓库**。

## 复现

```bash
.venv/Scripts/python.exe tools/intervention_effect_bench.py
.venv/Scripts/python.exe tools/predict_intervention_value.py
.venv/Scripts/python.exe tools/confirm_intervention_sensitivity.py
.venv/Scripts/python.exe tools/external_structure_check.py
.venv/Scripts/python.exe tools/verify_bench_resource.py     # 13 项完整性校验
.venv/Scripts/python.exe -m unittest discover -s tests -q  # 211 项既有测试
```

四个生成脚本启动即重算输入哈希，不一致拒绝运行；结果均已验证逐字段确定性。`verify_bench_resource.py` 只读资源、输出不含时间戳，重跑逐字节一致。

协议原文：`docs/experiments/intervention-predictability.md`、`intervention-effect-bench.md`、`intervention-sensitivity-confirmation.md`、`heldout-structure-replication.md`。

## 已知限制（不要省略）

- **金标来自参考补丁**，只代表一种修复的目标位置，不是修复成功、不是 agent 下游效果；沿用稿件 §7 的限制。不得把本资源结论外推到生成式查询、LLM 反馈、其他语言、其他基准或修复率。
- **不是无金标方法**：`delta` 等结果量含金标；只有 `D` 这类结构信号是 label-free。候选池与图仍来自参考补丁对应的 `base_commit` 快照。
- **不声称首创**反事实对照评测；与 Agent Retrieval Bench 的差异仅在符号级、2,232 任务、度/文件匹配的重连对照、独立金标审计与逐任务可复算。不与 CORE-Bench 比规模。
- **恒等式陷阱已排除但需警惕**：`topology_surplus = real.symbol − mean(rewired.symbol)` 与 `delta` 共享 `real.symbol`，明确不用作策略分数；`D=0` 子集的"零效应"主要是结构性可推出的，不是预测发现。
- **post-hoc 内容全部标注**：`null_spread` 方向反转、`utility@q` 补指标、机制假设、留一仓库诊断均为结果产生后补充，不参与各自的主检验，不得调阈值或挑表示。
- **88.4% 的 `delta` 为零**，风险侧事件稀疏、区间偏宽；折大小 692/1540 不平衡；按仓库 bootstrap 只部分反映任务间相关性。
- 62 行 held-out 仍属原 12 仓库，**不构成外部验证、独立复制或样本外预测**；`D=0` 子集仅 12 个任务，R1 关联接近结构性必然。
- 所有结果 `eligible_for_submission = false`；`paper/` 与已提交 Kaggle Writeup **全程未改动**。

## 入稿状态与还差什么

v1 是一份**完整、可复算、可发布**的资源，适合作为 Non-Archival 下一版资源论文的核心材料或当前稿件的资源附注，但**单独不足以支撑一条新的方法学主张**。要推到可发表强度，还缺：

1. **真正的外部仓库验证**：本地只有原 12 仓库快照。官方主赛道数据含 fastapi/rich/httpx/requests 共 129 条新仓库任务（`.cache/main-track/official/tasks.jsonl`），但只有 patch/issue/base_commit；源码快照是比赛沙箱内的 `.tgz`（`HARNESS_README.md:267`），本地没有，且确认集按规则冻结。取得独立仓库快照后另开预注册是唯一干净的补强路径。
2. **下游验证**：把逐任务干预效应接上 agent 修复结果，才能谈"对修复率的含义"；目前完全没有这一层。
3. **跨语言 / 跨基准**：当前全是 Python + SWE-bench 系列。

**对已提交 Writeup 的建议：不动。** 四轮实验的结论都不足以替换现有主线，且重交需整套重交并确认最终状态为 `submitted`；本资源留作下一版。
