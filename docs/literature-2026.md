# 2026 年这半年，和我们撞题的论文

收集日期 2026-10-30。每条只记**核实过摘要原文**的内容（链接在标题上），后面写"这对我们意味着什么"。

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

## 落到行动上的四件事（按性价比排序）

| | 做什么 | 成本 | 收益 |
| --- | --- | --- | --- |
| A | **引用 CORE-Bench / RepoNav / 小模型图工具 / 仓库记忆**，§2 加一段"谁做了什么、我们不重复什么" | 1 小时，约 +40 词（当前余 99） | 直接挡掉"你们不知道已有工作"的质疑，是 Novelty 与 Quality 两维 |
| B | **同文件兄弟符号分析**：在"文件已进 top-10 但符号没进"的任务里，数这 10 个槽位有多少来自金标文件的其他符号 | 半小时，纯离线 | 把 RepoNav 的前提在我们的数据上量化，给"剩余 33.5% 丢在哪"一个具体答案 |
| C | **hop 深度分层**（照 2610.33958 的做法）：按 issue→金标的图距离分层，看图臂是否只在 ≤1 跳有增益 | 半天 | 把我们的负结果和他们的正结果接上：不是图无用，是两跳以上没人能兑现 |
| D | **置换查询地板** | 1 小时（重跑 BM25） | 给 27.5% 一个随机基线，防"就是蒙的"质疑 |

我的建议：先 A（保护新颖性，必须做），再 B（便宜且让结论可操作）。C 如果时间允许，是唯一能"加新结果"的；D 优先级最低。
