# 从拓扑对照到算法：反事实图干预实验（2026-11-07）

## 目标

原论文已经区分“真实拓扑包含信息”和“固定邻居提升有净收益”。本轮进一步问：约束随机图能否从统计对照变成算法监督信号，在不读取修复金标的情况下减少有害图干预？

所有方法复用 2,232 个任务的固定候选池、真实投影图、五个约束重连图和 metadata/body/dense 顺序。算法构造阶段不读取 gold；涉及 repair label 的路由器使用仓库外评估，强排序器版本采用嵌套仓库交叉拟合。

## 方法

### 1. Null-calibrated promotion

对每个候选计算真实图一跳可达与五个保持节点文件内/跨文件度数的随机图可达概率。只提升 `real reach - null reach > 0` 的候选；另测按拓扑剩余值排序的版本。

### 2. Topology-surplus features

将真实可达、随机图可达概率及二者差值作为候选特征，加入论文的 16 特征＋dense LambdaMART。比较只加真实可达与加入完整反事实特征。

### 3. Counterfactual intervention routing

任务级模型预测是否应当在当前排序上启用固定图干预。普通版本只看图规模、种子度数、候选文件分布与排序不确定性；反事实版本再看随机图可达、真实/随机重合和重连可移动性。强排序器版本使用嵌套仓库交叉拟合，避免路由器训练目标来自训练内排序结果。

### 4. Contrastive topology denoising

这是本轮最独立的新算法。对每个训练仓库：

- 正例：真实图中被约束重连替换掉的边；
- 负例：约束重连图中新产生、真实图中不存在的边；
- 特征：端点文件/符号词法相似度、限定名前缀、三种检索表示中的端点名次与名次差；
- 测试：在未见仓库上给真实种子边评分，只提升高置信边连接的候选，或按边真实性分数排列图邻居。

边分类监督来自真实拓扑与随机拓扑的对比，不使用 reference patch、gold symbol 或 retrieval outcome。

## 全量结果

### 无训练或候选级方法

| 底座 | base | fixed real graph | null calibrated | surplus feature | contrastive denoising | contrastive scored |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| metadata | 0.2479 | **0.2698** | 0.2637 | — | 0.2523 | 0.2662 |
| body | 0.3171 | 0.3170 | 0.3115 | — | **0.3195** | 0.3144 |
| dense | 0.3659 | **0.3723** | 0.3678 | — | 0.3645 | 0.3700 |
| 16 features＋dense | 0.4470 | — | — | **0.4484** | — | — |

`dual_surplus` 的 0.4484 相对 0.4470 为 +0.14 点，任务及仓库区间均跨零。Contrastive denoising 在 body 上为 +0.24 点，仓库区间同样跨零；dense 上文件 recall 从 0.6931 增至 0.6971，但符号 recall 下降 0.14 点。不能把这些写成确认性提升。

### 路由方法

| 设置 | base | fixed graph | counterfactual route | oracle route |
| --- | ---: | ---: | ---: | ---: |
| metadata | 0.2479 | 0.2698 | 0.2704 | 0.2901 |
| body | 0.3171 | 0.3170 | 0.3189 | 0.3426 |
| dense | 0.3659 | 0.3723 | 0.3725 | 0.3970 |
| 16 features＋dense，嵌套评估 | 0.4470 | 0.4325 | 0.4442 | 0.4628 |

弱底座上的任务路由与 fixed graph 接近，未可靠超过它。强底座上固定图干预损失 1.45 点；反事实路由器避免 110/139 个有害任务，追回约 80.7% 的总体损失，但也只保留 23/81 个获益任务，最终仍比不干预低 0.28 点。

两专家路由也没有成功。强排序器与 frozen dense 的任务 oracle 为 0.4708，但嵌套跨仓库路由最高只有 0.4346，说明“专家互补存在”不等于可从当前任务统计中稳定识别。

## 科学结论

1. 约束随机图可以作为算法监督，而不只是显著性对照；这形成了 repair-label-free 的 contrastive topology denoising 方法。
2. 当前端点词法/名次特征不足以稳定识别有用真实边。随机图监督带来少量方向性变化，但没有超过最优固定图规则或 44.7% 强排序器。
3. 图干预选择存在可观 oracle 空间，但跨仓库可预测性弱。强检索器上的主要问题不是“图没有信号”，而是收益稀疏、损失异质且难以从任务级汇总统计预测。
4. 这组负结果提高了论文的新颖性和机制完整性，但不应替换原主结果，也不应称为新 SOTA。

## 投稿使用建议

正文最多加入一个明确标为 exploratory 的短段，强调“将 null 变为监督信号”的方法贡献，并同时报告未获得稳健净收益。不要新增一张大表，不要把 0.3195 或 0.4484 加粗成胜出结果。

若继续确认，下一步必须换外部基准、图构建器或新的仓库集合；不应继续在当前 2,232 个任务上搜索阈值。优先加入边类型、调用方向、定义/调用上下文和类型信息，再冻结后到外部任务评估。

## 复现

```bash
uv run python tools/run_null_calibrated_graph.py
uv run python tools/rank_with_topology_surplus.py
uv run python tools/select_graph_intervention.py
uv run python tools/run_counterfactual_router.py
uv run python tools/run_expert_router.py
uv run python tools/run_contrastive_topology.py
uv run python tools/audit_counterfactual_topology.py
uv run python -m unittest discover -s tests
```
