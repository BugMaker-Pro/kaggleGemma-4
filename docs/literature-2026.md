# 2026 年这半年，和我们撞题的论文

收集日期 2026-10-30 至 2026-10-31。每条只记**核实过原文**的内容（链接在标题上），后面写"这对我们意味着什么"。第二轮补了三篇顶会/预印本：FuseSearch（ACL 2026 Findings）、CoQuIR（ACL 2026）、SWE-Bench Pro Verified，以及一个方法论预印本 falsify-eval。

## 0. 撞车地图（先看这个）

| 我们的想法 | 谁先到了 | 严重程度 |
| --- | --- | --- |
| 文件级指标掩盖了函数级问题 | CORE-Bench（EMNLP 26）、RepoNav（EMNLP 26）、FuseSearch（ACL 26 Findings，报告的是文件级 F1） | **红**：必须引用并说明分工 |
| 代码图对定位不值钱 | 小模型 agent 研究（arXiv 2610.33958）；FuseSearch 直接把"不需要知识图谱"写进设计 | **橙**：结论被独立复现，我们要把"定价"作为差异 |
| 检索结论需要声明统计功效 | falsify-eval（个人站预印本，非顶会） | **橙**：方法学近邻，必须引用 |
| 金标/任务质量要审计 | SWE-Bench Pro Verified（arXiv 2609.08149）、SWE-Bench Illusion | 绿：支持我们，不是抢 |
| 索引文本组成决定差距大小 | 没找到同类 | **绿**：可当自己的结果 |
| 两尺度经验功效曲线（真 benchmark、配对差值、n 到 2,232） | 没找到同类 | **绿**：最可能站住的一节 |


## 1. CORE-Bench: A Comprehensive Benchmark for Code Retrieval in the Era of Agentic Coding

[arXiv:2606.11864](https://arxiv.org/abs/2606.11864) · EMNLP 2026 Main

> "Existing code retrieval benchmarks mainly evaluate docstring-to-function or snippet-level matching, thereby missing this requirement-driven repository search problem... CORE-Bench evaluates code retrieval ability at three levels: code understanding, issue-to-edit localization, and broader context retrieval. Built from curated code-search tasks and SWE-bench-series instances, CORE-Bench contains over 180K queries... Experiments with representative embedding models show a sharp drop from traditional code search to code retrieval in agentic coding settings. Simple supervised fine-tuning of existing embedding models significantly improves performance."

**意味着**：他们独立发现了同一条裂口——"传统 code search 指标好看，agentic 场景掉得厉害"。这是我们 §1 的立论，现在有了同期证据，**必须引用**，否则评委可能认为我们不知道已有 benchmark。区别要写清：他们**造 benchmark + 训 embedding**，我们**测同一个 ranking 在两种粒度上的差**，并给图的边际价值与尺度不变性。他们量的是"检索模型够不够好"，我们量的是"结构到底值多少分"。

## 2. RepoNav: From Snippet Retrieval to File-Centered Repository Navigation for Code Agents

[arXiv:2609.08355](https://arxiv.org/abs/2609.08355) · EMNLP 2026

> "current retrieval tools typically return flat lists of isolated code snippets: such lists can surface relevant files, but provide insufficient structure for agents to distinguish the target function from semantically similar alternatives in the same file... Across diverse models on LocBench, RepoNav improves function-level localization and narrows the file-to-function gap. Controlled ablations demonstrate that these gains come from structured evidence organization rather than simply exposing additional file structure."

**意味着**：这篇是**正面结果**，但和我们不矛盾——他们改的是**检索之后的呈现**（把扁平列表变成以文件为骨架的导航），不是排序本身。我们的 recall@10 量的是排序；他们说"文件找对了、符号分不清"，正好是我们 §5 的 66.5% 上限所对应的剩余 33.5%。**引用并明确分工**：我们量"槽位里有没有"，他们改善"槽位里的东西怎么摆"。也提醒我们别把结论写成"结构无用"——正确的说法是"进入候选池的排序层面，图不值钱；出了池子之后的呈现，另有空间"。

## 3. How Do Small Coding Agents Use Code Graphs and Embeddings?

[arXiv:2610.33958](https://arxiv.org/abs/2610.33958) · 2026-10-25（预印本）

> "Coding agents are given embedding search and code-graph tools on the premise that a repository's structure is something the model lacks and the tool supplies. We test that premise on SWE-bench Verified with small open-weight models... Structured tools double grep-only accuracy for Qwen3-8B and Gemma 4 E4B; their gain peaks at 17-21 points at 1.7-4B and falls to 4-5 points at 32B... Each extra hop multiplies the odds of correct localization by 0.50-0.67 at every size, and no tool set flattens that gradient: traces show the graph tools' gain is name lookup at hop 0 and one expansion at hop 1, and agents chain expansions in only 12-14% of episodes... linear probes find direct call edges decodable... below a lexical baseline (0.99)".

**意味着**：这是**对我们最有力的外部旁证**——换了一个完全不同的测量面（agent 的工具使用、小模型、hop 深度分层），结论同向：图工具的价值≈名字查找 + 一跳；两跳以上没人用；结构化表示在权重里也不比词法强。他们还有一个我们没用过的分析维度：**用 hop 深度分层**，每多一跳，定位正确率乘 0.5–0.67。我们可以照做：把任务按"issue 提到的代码到金标之间的图距离"分层，看我们的图臂是否只在 hop=1 上有增益。数据是现成的（`near_seed`、图距离），半天能出。

## 4. Improving Code Localization with Repository Memory

[arXiv:2510.01003](https://arxiv.org/abs/2510.01003) · ICLR 2026

> "each instance is typically handled from scratch assuming no prior repository knowledge... we augment language agents with such memory by leveraging a repository's commit history... We demonstrate that augmenting such a memory can significantly improve LocAgent... on both SWE-bench-verified and the more recent SWE-bench-live."

**意味着**：这正是我们做过的"历史先验"实验，但我们是**一次性检索**且做了分解：`sim` 只 +0.009（p=0.12），`freq` +0.019（p<1e-4），相似性在**最不相似**的任务上反而贡献最多 → 那更像"文件流行度"而不是"案例记忆"。他们得到正结果，是因为记忆是**agent 多轮可查的工具**，不是一次性特征。**引用作对照**，并把这句写进 Limitations：我们的负结果限定在单轮排序，不否定工具化记忆。

## 5. Finding the File: Localisation on SWE-bench Verified, Measured Against a Permuted-Query Floor

[HF blog](https://huggingface.co/blog/RiverRider/finding-the-file-localisation-on-swe-bench-verifie)（只核到标题与摘要片段，正文未取到）

方法学想法：把 issue 打乱（permute）当作**随机地板**，报告"真实查询比地板高多少"，以剥离"文件名字符串碰巧出现在 issue 里"的成分。

**意味着**：我们的 62.4% 文件 recall 里，有多少来自路径/类名与 issue 的字面重合？我们的证据特征已经把这一点显式化（`named_file`、`frame_file`、`path_in_issue`），但一个**置换地板**会让"27.5% 不是运气"这句话有量化锚点。成本：用另一个任务的 issue 重跑 BM25（300 任务，约 1 小时）。

## 6. 顺带记一笔风险文献

[The SWE-Bench Illusion: When State-of-the-Art LLMs Remember Instead of Reason](https://openreview.net/pdf?id=ZJCyrBpgnW) —— 讨论 SWE-bench 上的记忆/污染。和我们"图不如读 issue"的结论互补：如果模型记得住，那"读 issue"的收益也可能被高估。可在 Limitations 里一句带过（我们测的是检索，不涉及模型是否记住）。

## 7. FuseSearch: Learning Adaptive Parallel Execution for Efficient Code Localization

ACL 2026 Findings（蚂蚁集团）· [项目页](https://github.com/sxthunder/FuseSearch) · [中文报道](https://hub-assets-cache.baai.ac.cn/view/55532)

报道里的关键句：代码定位吃掉 agent 超过 **50%** 的计算；固定并行 8 个工具会产生 **34.9% 冗余调用**；他们的工具箱只有 `glob`/`grep`/`read_file` 三把，**"不需要代码知识图谱，不需要语法解析器，零依赖"**；4B 模型在 SWE-bench Verified（386 实例）上 **84.7% 文件级 F1**，比基线快 93.6%、省 68.9% token；RL 让模型学会"该搜多少"，奖励 = 0.8×定位准确率 + 0.2×(准确率×工具效率)。

**意味着**：这是最直接的竞争者，而且立场和我们一致——**别建图，聪明地搜就够**。两点要写进 Related Work：
1. 他们报告的是**文件级 F1**，正是我们论文说会高估的那个粒度；可以说"最强的 agentic 定位器仍在文件级汇报"；
2. 他们用 386 个实例做评测——我们的功效表说明这个量级只能分辨 5 点以上的效应（他们效应大，不受影响，但这句话对我们有利）。

差异：他们做**多轮 agent 策略**（学并行度），我们做**单轮排序的定价**（8 臂受控、同池同预算、两尺度）。

## 8. CoQuIR: A Comprehensive Benchmark for Code Quality-Aware Information Retrieval

[ACL 2026 Long](https://aclanthology.org/2026.acl-long.512/)（Geng et al.）

> "current benchmarks primarily emphasize functional relevance while neglecting code quality... 42,725 queries and 134,907 code snippets in 11 languages... Evaluating 23 retrievers... even state-of-the-art models often fail to separate buggy or insecure code from robust counterparts."

**意味着**：又一篇"现有 code retrieval benchmark 缺了 X"的顶会论文，但 X 是**质量**（正确/效率/安全/可维护），不是**粒度**。可以在 §2 一句带过：这类工作补的是检索目标的维度，我们补的是同一排序的评分粒度——两者正交。

## 9. Calibrated Falsification Harnesses for Retrieval Evaluation（预印本，非顶会）

[PREPRINT](https://spalsh-spec.github.io/falsify-eval/PREPRINT.md) · Sparsh Sharma · v7-10K · 2026-05

> "Retrieval and ranking system claims are routinely reported as bare aggregate metrics, without (a) a calibrated null-distribution comparison..., (c) explicit per-feature statistical significance with declared sample-size power..."

他们给了"bench-size calibration curve at N ∈ {21,40,80,120,141}"并把结果**投影**到 N=10,000。

**意味着**：这是我们功效那一节最近的近邻，**必须引用**，否则"样本量功效"会显得是我们在重新发明。差异很清楚：他们是**小语料 + 投影**（N 最大 141，10k 是外推），我们是**真 benchmark 上直接量到 2,232**、用配对差值重采样、并且给出每臂的检出概率曲线。一句话："prior work argues the point on a niche corpus; we measure it on the benchmark the field actually uses."

## 10. SWE-Bench Pro Verified: A Reliable Benchmark for Software Engineering Agents

[arXiv:2609.08149](https://arxiv.org/abs/2609.08149)

> "its evaluation is undermined by two sources of unreliability: reward hacking, enabled by leakage of gold solutions or hidden evaluation information, and task quality issues, including misleading problem statements and improperly scoped tests."

**意味着**：他们修的是**任务与评测**的可信度，我们修的是**答案纸**（金标）的可信度，两条线可以互相引用：都说明"benchmark 的数字需要先验一遍再比"。也支持我们 §3 的"misleading problem statement"式的分析（issue 文本是仪器）。


## 落到行动上的五件事（按性价比排序，2026-10-31 更新）

| | 做什么 | 成本 | 收益 |
| --- | --- | --- | --- |
| A | **引用 CORE-Bench / RepoNav / FuseSearch / CoQuIR / falsify-eval**，§2 加一段"谁做了什么、我们不重复什么" | 1 小时，+50 词左右（当前全文余 16，需先砍 40） | 挡掉"不知道已有工作"，Novelty 与 Quality 两维 |
| B | **body ablation 全量 + noise 控制**：把 2.3×→1.9× 的结论钉在 2,232 上 | 机器时间（已在跑 / 待补） | 把"你的差距是模板造成的"这个最大漏洞变成结果 |
| C | **同文件兄弟符号分析**：文件进 top-10 但符号没进时，数槽位里有多少兄弟符号 | 半小时，纯离线 | 量化 RepoNav 的前提，给"剩余 33.5%"一个答案 |
| D | **hop 深度分层**（照 2610.33958）：按 issue→金标的图距离分层看图臂增益 | 半天 | 把我们的负结果和他们的正结果接上 |
| E | **置换查询地板** | 1 小时 | 给 27.5% 一个随机基线 |

现状：功效分析（§5 新节 + Table 7）已完成并进论文——这是和 falsify-eval 唯一正面对上的地方，且我们是真 benchmark 直接量到 2,232。剩下的优先级：B（在跑）→ A（引用定位）→ C。
