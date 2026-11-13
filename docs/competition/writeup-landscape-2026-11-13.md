# 论文赛道同类 Writeup 对标（2026-11-13）

截止时间（北京时间 2026-11-13 07:59）已过，本文用于三件事：

1. 记录同场提交在做什么、强在哪，供评委视角自查；
2. 给出我们论文（`paper/submission.md`）相对同行的真实位置；
3. 列出可执行的改进项，供 arXiv 版、NeurIPS 展示版和主赛道复用时使用。

> 说明：Kaggle 的 Writeup 页面是客户端渲染，匿名抓取只能拿到标题；本文重点分析的 4 篇中，3 篇读到了完整正文（Kaggle 渲染正文、作者仓库 Markdown），FGL 只读到 arXiv 摘要。凡未读到正文的，只记录标题与副标题，不做内容断言。

## 0. 一句话结论

我们的**证据设计**（固定候选池 + 度数/同文件匹配随机图 + 三种表示 + 粒度分解 + 独立金标审计）仍是同场最扎实的一档；但**选题叙事**已经落后半步——同场至少三份提交独立得出"图对静态检索/智能体没有稳定增益"，再用"图没用"当卖点会显得不新。真正还能拉开差距的是：把结论升级为"**图负责扩大可达集，模型负责选择，静态提升规则最后**"，并补一个 Gemma 4 在环实验与外部时间戳协议。

## 1. 竞争格局（约 300 份提交的可见面）

| 簇 | 代表提交 | 核心主张 | 对我们意味着什么 |
| --- | --- | --- | --- |
| A. 定位与代码图（最大簇） | Graph Tools Fail, Gemma Reranking Holds；Born After the Cutoff；我们；aghasalim、CosmicMagnetar、rabiul9137、lottolove5131 等仓库 | 图/嵌入/BM25 在函数级定位上的真实收益；候选池与重排 | 直接竞争。必须靠"对照设计"而不是"图 null"区分 |
| B. 智能体与训练 | Let the Fixer Decide（FGL）；Tools Unused, Tests Fooled；What Actually Limits a Small-Model SWE Agent；Structure over Scale；MOEPA；GRPO 记录 | 用 fixer 似然训练 localizer；工具消融；上下文/预算机制；轨迹数据 | 他们把"定位"接到"解决率"，这是我们缺的下游证据 |
| C. 评测有效性 | Tools Unused, Tests Fooled；Hollow Pass；Rare failures need many runs；Valid Agent Trajectories Teach the Wrong Behavior；Where a fixed small model's score comes from | 129 题里只有 68 题可区分；测试会接受 14.7% 的坏补丁；单次运行不足以比较 | 这是今年最稀缺、评委最买账的角度；我们的金标审计天然属于这一簇，但只做了标签、没做测试 |

评委画像（Perozzi、Galkin、Rózemberczki 等偏图 ML）会天然重视 A 簇，但 A 簇已经拥挤；B/C 簇稀缺。我们的最佳落点是"**A 的严格对照 + C 的审计气质**"，而不是再交一篇"A 里说图没用"。

## 2. 四篇重点分析

### 2.1 Graph Tools Fail, Gemma Reranking Holds（T Wood / twood8）

- **规模**：129 道公开题 + 667（Lite∪Verified−requests）+ 1,518 道"fresh"（全量测试减去 Lite/Verified/requests）。
- **主结果**：官方图一跳扩展对 BM25 为 −2.6 Hit@5 [−9.5, +4.3]；自建图 PageRank 样本内 +6.7，冻结测试 −1.2；**Gemma 4 E4B 对 BM25 前 20 做 3-pick 重排，Hit@5 47.2→60.9（+13.7 [+11.8,+15.6]，McNemar 233 vs 25），Hit@1 24.8→42.0**，单次调用约 2.7k tokens。
- **方法学**：三份冻结协议，C1/C2 上传 Kaggle dataset 取得**服务器时间戳**；预注册主终点 + Holm 次终点；开发→测试收缩（+15.1→+13.7）与图方法（+6.7→−1.2）并列报告；逐仓库 bootstrap；失败方向也写。
- **资源**：`gold_symbols.jsonl`、`locate_code` skill（stdlib）、逐结论 notebook、C2 复跑脚本。
- **写作**：标题即结论；§6 五条可执行建议；§7 六条限制（含预训练暴露、顺序敏感性）。
- **可借鉴**：(i) 服务器时间戳预注册；(ii) "模型只提升、不检索"的分解（金的 top-20 上限 65.7%）；(iii) 成本表（token/延迟）；(iv) 建议清单单独成节。

### 2.2 Tools Unused, Tests Fooled（Manohar Papasani / TechNaom）

- **规模**：129 道公开题，用官方 harness 跑 `gemma-4-31b-it-qat-w4a16-ct`；11 种配置。
- **主结果**：129 题里**只有 68 题（53%）能区分智能体**（金补丁过、空补丁不过）；给不给图工具：50% vs 47%（McNemar p=0.69），提示使用后 44%；**163 个植入 bug 中 24 个（14.7%）被测试当作正确修复接受**（原始 21%，人工剔除等价变异后 14.7%）。
- **机制**：默认 16,384 输出 token 导致 26 次上下文溢出；减半后解决数 29→34/80（+6.2pp，CI [−1.3,+13.8]）。
- **方法学**：金/空双跑筛题；工具**使用率**与工具**可用性**分开报告；轨迹全量发布 + CPU 重验工具；承认 10 题 pilot 高估 30 点。
- **可借鉴**：(i) 先审计评测再测方法；(ii) 报告 adoption 而不只是 availability；(iii) 把"解决率是上界"讲清楚。我们的金标审计只覆盖"改哪"，没覆盖"改对没有"，这是可补的一句话。

### 2.3 Born After the Cutoff（AliceMessi / alanone）

- **资源**：4,097 条 issue→fix 实例，26 个宽松许可的 Python agent/LLM 框架仓库；按 Gemma 4 预训练截止（2025-01）与发布（2026-04）分三档；**1,790 条来自截止后才创建的 6 个仓库**（born-after 控制）。
- **主结果**：预注册 519 条评测集上，G1（BM25/嵌入种子一跳扩到 ≤40 单元，Gemma 4 E4B 单次重排）file Hit@1 0.80、function Hit@10 0.80（E4B），BM25 为 0.56/0.71；12B 0.83/0.81；Agentless 式提示 +0.23 function Hit@10（Holm p=0.0002）；12 步图智能体 G2 只有 0.365–0.465，token 却是 10 倍。
- **负结果**：H1 记忆假设不支持；"born-after 上图增益更大"的预测也不支持；探索性分析才看到 codebase-familiarity 效应。
- **方法学**：预注册 + 偏差日志；60 条金标由 LLM 审计（95%，并声明非独立）；数据集/图/回放 notebook/清单哈希；37 个单测。
- **可借鉴**：(i) 污染控制可以用"日期分档 + 新仓库"做得便宜；(ii) 图的价值在"扩池"，选择交给模型；(iii) 资源型论文的交付清单可以直接照抄格式。

### 2.4 Let the Fixer Decide（FGL，arXiv:2611.12164，2026-11-09）

- **主张**：localizer 不该只拟合"参考补丁改了哪些文件"，而应拟合"fixer 需要读哪些代码"。用冻结 fixer 给多个定位打分，再用加权 SFT 训练 localizer；不需要跑测试、不需要 RL。
- **规模**：Gemma 4 E4B，1,629 条 Kimi K3 验证轨迹；开发集 53 vs 46 到达补丁、8 vs 6 解决；单 agent 最高 11/78（基线 8）。
- **对我们的意义**：这是"定位目标函数"层面的创新，比再换一个检索器更根本。我们的 gold-symbol 指标同样假设"参考补丁=目标"，FGL 正好点出这个假设的边界；在 Related Work / Limitations 里引一句，会显得我们理解定位任务的本质。

## 3. 五维对比（我们的估计，不是评委打分）

| 维度 | 我们 | Graph Tools Fail | Tools Unused | Born After | FGL |
| --- | --- | --- | --- | --- | --- |
| Novelty | 3.5：匹配零模型 + 粒度分解是新的；"图 null"本身已被三家独立复现 | 4：首个"官方图审计 + 预注册重排"组合；重排本身不新 | 4.5：把"评测是否有效"变成主贡献 | 5：新数据集 + 污染分档 + born-after 控制 | 4.5：定位目标函数换成 fixer 似然 |
| Quality | 4：协议可迁移，2,232 题、三表示、Holm；但 Python-only、无下游 | 3.5：1,518 题很稳，但单模型/单提示、无稠密基线 | 4：发现可能普适，但 68 题、两仓库、单模型 | 4.5：4,097 实例、三档、多模型、预注册 | 4：一条完整训练管线，单模型 |
| Relevance | 3：定位是智能体第一步，但没有 Gemma、没有解决率 | 4.5：直接用比赛模型与题，建议可落地 | 5：直接改变榜单的读法 | 4.5：定位资源，格式兼容比赛 | 4.5：训练小模型智能体的通用方法 |
| Verifiability | 4.5：数据/排序/审计全开源，独立金标 279/300；但协议只有本地"pre-specified" | 5：服务器时间戳协议 + 每数一个 notebook | 4：轨迹 + 重验工具，但无外部时间戳 | 4.5：数据集 + 回放 + 清单哈希 + 偏差日志 | 3.5：代码/适配器公开，预注册不明 |
| Clarity | 4：信息密度高、诚实；但 2,916 词塞满数字，缺"建议清单"和资源卡 | 4.5：标题即结论，结构干净 | 4.5：三问三答，可读性强 | 4.5：资源论文的标准写法 | 4：信息完整，略长 |

## 4. 我们强在哪、弱在哪

**强项（应继续强调）**

1. **对照设计最严**：固定候选池、度数+同文件匹配随机图、三种表示、Holm 校正、仓库聚类区间——同场没有第二份做到这个粒度。
2. **指标分解最细**：文件/符号/行三种粒度 + 索引内容（body）+ token 计价（定义 vs 整文件 16.1×）。这是"看得见成本"的定位研究。
3. **金标可信**：独立实现 279/300 一致，换金标 recall 变化 ≤0.7 点；这是很多同场工作没有的。
4. **学习融合有正结果**：0.447/0.727，图特征 +1.66 点（CI 0.66–2.42），并且做了"去掉拓扑特征重训"的严格消融。

**弱项（相对同场）**

1. **没有比赛模型在环**：同场头部都在用 Gemma 4 E4B/31B；我们只有 bge-small 稠密 + LightGBM。评委容易归类为"通用 IR 实验"。
2. **没有下游解决率**：连 FGL 都有 8 vs 6 的小规模解决率；我们只有检索。Limitations 已承认，但观感上弱一档。
3. **预注册是"本地声明"**：对手用 Kaggle dataset 服务器时间戳；我们的 protocol 无第三方时间戳，容易被质疑"看结果后改协议"。
4. **"图 null"不再稀缺**：Graph Tools Fail（−2.6 Hit@5）、Born After（RM 图基线低于 BM25）、我们的 Lite 八臂（无显著增益）三处独立趋同。再把它当头条会显得不新。
5. **绝对数字看起来低**：我们用"覆盖全部金标符号"的 recall（0.275/0.447），对手多用 any-gold Hit@k（0.47–0.80）。不解释口径，评委会误判。
6. **相关工作缺关键邻居**：RepoGraph、CoSIL、SweRank、Agentless、SWE-bench Verified、SWE-bench Illusion/污染研究、变异测试都没引；而对手的 Related Work 已经覆盖。

## 5. 提升清单

### P0：只改稿，1–2 天（arXiv 版立刻可做）

| # | 动作 | 落点 | 影响的维度 |
| --- | --- | --- | --- |
| 1 | 把"图没用"升级为"**图负责 reach，模型负责 selection，静态提升规则最后**"，并用我们已有的 2-hop 可达 35.7% / oracle 0.630 支撑 | §6 Discussion 第 1–2 段 | Novelty、Relevance |
| 2 | 指标口径一句话 + 用现有 ranking 补一个 any-gold Hit@10 | §3 或 §5 开头，Table 3 附近 | Clarity、Quality |
| 3 | 补 6 篇引用并压缩 §3 金标细节腾字数 | §2 Related Work；§3 | Novelty、Quality |
| 4 | 诚实标注"本地预注册、无外部时间戳"，并说明下一版将时间戳化 | §7 Limitations | Verifiability |
| 5 | 加 AI-use disclosure 与 resource card 两句 | 文末 | Verifiability、Clarity |

### P1：小实验，3–7 天

| # | 动作 | 成本 | 收益 |
| --- | --- | --- | --- |
| 6 | **Gemma 4 E4B 重排臂**：在现有 200 候选池、融合排序前 20 上做 3-pick 重排，量 symbol/file recall@10（290 Lite + 500 全量） | 约 800 次调用、1–2 张 T4、1 天 | 直接把论文接回比赛模型；无论正负都增强 Relevance |
| 7 | **日期分档**：把现有 2,232 结果按 issue 日期相对 Gemma 截止切三档，报告 BM25/融合 recall | 纯离线，半天 | 污染控制，Quality/Verifiability |
| 8 | **协议时间戳**：把 `graph-control-protocol.md`、分析计划上传 Zenodo/OSF/Kaggle dataset，引用 DOI/hash | 1 小时 | Verifiability 从 4.5 到 5 |

### P2：大工程，谨慎

| # | 动作 | 判断 |
| --- | --- | --- |
| 9 | 20–30 题下游解决率 | 2026-11-08 的 10 题 pilot 已经输给基线；除非重新设计预算与编辑时机，否则不进论文 |
| 10 | Lite 变异测试/测试充分性 | 成本高；引用 SWE-bench Verified 与 "Are Solved Issues Really Solved" 即可 |

## 6. 可直接用的英文改稿片段

**A. Related Work 增补（约 85 词）**

> Repository graphs have been built for agents before: RepoGraph [16] and CoSIL [17] construct their own graphs, SweRank [18] trains function-level retrievers, and Agentless [19] shows that a fixed localize-then-repair pipeline is competitive. Recent work also shows that models can recall repositories seen in pre-training [20] and that benchmark tests can accept broken fixes [21]. Our static rankings do not depend on model memory, and our gold audit is separate from test adequacy.

**B. 指标口径（约 45 词，放在 §3 或 §5 开头）**

> Hit@k in concurrent localization work usually means that at least one gold location appears in the top k. Our recall instead averages the fraction of all gold symbols recovered, so absolute values are lower by construction; on the same Lite ranking, any-gold Hit@10 is X against 0.275 coverage.

（X 需用现有 ranking 计算；`experiment_v3.jsonl` 的每符号名次足够，不需要重跑检索。）

**C. Discussion 升级（约 100 词）**

> Two concurrent competition studies place these numbers. A function-level audit of the shipped competition graph finds one-hop expansion at −2.6 Hit@5 points and no gain from rewired edges, yet +13.7 points when Gemma 4 E4B reranks a 20-item shortlist [22]; a contamination-controlled benchmark reports 0.80 function Hit@10 from a one-hop pool of at most 40 units reranked by the same model, against 0.71 for BM25 [23]. Both agree with our accounting: expansion raises the ceiling — our two-hop pool reaches 35.7% of gold symbols — but a static promotion rule cannot convert reach without displacing existing hits. The practical order is graph for reach, a model for selection, a fixed promotion rule last.

**D. Limitations 增补（约 35 词）**

> Protocols were pre-specified locally before outcome inspection but not externally timestamped; concurrent work now uses server-timestamped protocols [22], and we adopt that practice for the next version.

**E. AI-use disclosure / resource card（按实情填）**

> AI-use disclosure. Code, analysis and drafting were assisted by an AI coding assistant; the authors reviewed every number and claim.
>
> Resource card. Data: patch-derived gold symbols, per-task rankings and audit outputs. Code: `tools/audit_numbers.py`, `tools/audit_counterfactual_topology.py`, protocols and reproduction commands. No GPU is required to recompute the reported metrics.

## 7. Gemma 4 rerank 实验草案（P1 第 6 项）

- **输入**：现有 200 候选池；取融合排序前 20；每题一次调用。
- **提示**：issue 前 1,200 字符；候选写成 `[i] module.qualname (path:line)` + 前 8 行；要求只输出 3 个编号。
- **模型**：`gemma-4-e4b-it` QAT，greedy，输出 ≤32 token；无金标进入提示。
- **指标**：coverage recall@10（我们的主指标）、any-gold Hit@10、file recall@10、首次命中位次、token 成本。
- **统计**：仓库聚类 bootstrap + 精确符号检验；与融合排序配对。
- **判读（先写死）**：
  - 若 coverage 显著上升 → 新主结果，论文标题可改为"reach + selection"；
  - 若 only any-gold/ Hit@1 上升 → 作为"选择层"证据，不改主结论；
  - 若都不升 → 说明在覆盖口径下瓶颈在池子/标签，不在选择；仍然是可发表负结果。
- **防污染**：Lite 多为旧题（Gemma 可能见过），同时跑 500 道截止后/新仓库子集作 replication；两处分开报告。

## 8. 引用与来源

- T Wood. *Graph Tools Fail, Gemma Reranking Holds: Pre-Registered Localisation Tests.* Kaggle Gemma 4 Developer Agent Paper Track, 2026. <https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/writeups/graph-tools-fail-gemma-reranking-holds-pre-regis>
- Manohar Papasani. *Tools Unused, Tests Fooled.* Kaggle Paper Track, 2026. <https://github.com/TechNaom/gemma4-agentic-swe>
- *Born After the Cutoff: A localization benchmark for small Gemma 4 coding agents.* Kaggle Paper Track, 2026. <https://github.com/AliceMessi/born-after-the-cutoff>
- Hennara et al. *Let the Fixer Decide: Training a Code Localizer from the Fixer's Likelihood.* arXiv:2611.12164, 2026. <https://arxiv.org/abs/2611.12164>
- *What Actually Limits a Small-Model SWE Agent?* <https://github.com/bsw0610/gemma4-swe-harness-audit>
- 其他同场可见提交（标题级）：*Where Do Small Gemma 4 Coding Agents Fail?*、*Fixing Is Easy, Knowing Isn't*、*Valid Agent Trajectories Teach the Wrong Behavior*、*Rare failures need many runs*、*Where a fixed small model's score comes from*、*Hollow Pass*、*Structure over Scale*、*MOEPA*、*DesignGrad*、*StateBridge × TwinAPI*。
- 我们的稿：`paper/submission.md`（2,916 词，6 页）、`paper/submission.pdf`、`paper/kaggle_body_img.md`。
