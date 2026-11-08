# 引用核实笔记（10 篇 PDF）

> 核实时间：2026-10-25。方法：`pypdf` 抽全文 → 定位到具体行 → 抄原句。
> 状态标记：✅ 已核实原文 ｜ ⚠️ 原文有歧义或不支持我们的说法 ｜ ⬜ 未读/仅摘要
> 规则：论文正文里每个带数字的引用必须能指回这里的一行。

---

## 1. PyCG（ICSE 2021）✅

**做什么**：用静态分析给 Python 建调用图，目标是"实用精度"。

**我们引的那句**：
> "rates of precision∼99.2%, and adequate **recall∼69.9%**"（摘要）
> 表里 Average 行：`99.2 74.4 98.7 69.9 20.6 14.4`

**我们的边界**：PyCG 量的是**边**的召回率（建图质量）；我们量的是**任务相关符号**能不能被图/检索碰到（使用价值）。69.9% 是我们论证"静态图天生缺三成"的锚点，两者不冲突但不是一个量。

**状态**：✅ 数字与表述均核实。

---

## 2. ARISE（2026）✅ + ⚠️

**做什么**：仓库级图表示 + 工具集，给 agent 做故障定位与修复。节点＝Module/Class/Function/Method，边＝Contains / Imports / Inherits / Calls。

**我们引的那句（这是论文动机的核心）**：
> "Spurious call edges lead agents down incorrect paths and are **more harmful than missing edges** [32,33], so we resolve only unambiguous direct and qualified `module.function()` calls and **drop dynamic dispatch through attribute access**."

**为什么这句值钱**：他们**主动**选择放弃动态分派，理由写得很清楚——错的边比缺的边更害人。这正好支撑我们"图的天花板是覆盖率而非算法"的论点，而且是他们自己说的，不是我们推测。

**结果数字（核实）**：`ARISE-Full` 在 SWE-bench Lite 上 **Pass@1 = 22.0%（66/300）**，相对 host 的 17.3% 提升 4.7 个点；Function R@1 0.43→0.60，Line R@1 0.26→0.41。

**⚠️ 一处必须改正**：我之前写"ARISE 不报任何覆盖率指标"——**这是错的**。原文有 `Coverage@budget`，定义是"8000 token 预算下，build_context_bundle 输出里黄金**行**的占比"。
**它量的是"上下文预算够不够装下答案"，不是"图的节点/边覆盖率"。** 两者不同，但我不该说人家"没有覆盖率指标"。正文已改为：ARISE 报告的是 *上下文预算内的黄金行覆盖*，而非图的覆盖率。

---

## 3. LocAgent（2025）✅ / ⚠️

**做什么**：把代码库转成有向异构图，用 LLM agent 在图上多跳搜索来定位。

**我们引的那句**：
> "reaching up to **92.7% accuracy on file-level localization**"（摘要）

**⚠️ 表格有歧义**：Table 4 每行 7 个数，caption 说"accuracy at file, module, and function levels"。以 `Qwen2.5-32B(ft) 75.91 90.51 92.70 85.77 87.23 71.90 77.01` 为例，92.70 与摘要的 file-level 92.7% 对得上，说明前三列顺序是 **function, module, file**（与 caption 的书写顺序相反）。按这个读法，**LocAgent 的函数级是 75.91%**。
**处理方式**：正文只引摘要明确写出的"92.7% file-level"，**不引函数级数字**，避免因列序歧义出错。

**我们的边界**：他们报的是"模型能不能定位到"，我们是"不考虑模型，检索层能给出什么"。他们的 92.7% 含模型能力；我们的 27.5% 是纯 BM25。

---

## 4. SWE-bench（ICLR 2024）✅

**做什么**：从真实 GitHub issue + 已合并的修复 PR 构建基准。

**我们引的那句**：
> "instances without at least one test where its status changes from **fail to pass** (henceforth referred to as fail-to-pass test)"

**我们的用法**：说明 `patch`（人写的修复）和 fail-to-pass 测试是**基准自带的标签**，我们用前者造答案纸。

**⚠️ 注意**：`FAIL_TO_PASS` / `test_patch` 这些**字段名**来自数据集 schema，不是论文正文——引用时不要说"论文定义了字段 X"。

---

## 5. SWE-agent（NeurIPS 2024）✅

**做什么**：给模型设计 Agent-Computer Interface（ACI），证明**接口设计**比模型本身更能决定成败。

**我们引的那句**：摘要 "SWE-agent's custom **agent-computer interface**"。

**我们的边界**：他们固定接口、让模型自由行动；我们固定行动、只换检索。两边正交。

---

## 6. Jarvis（2023）✅ / ⚠️

**做什么**：更精确的 Python 调用图构建。

**核实到的数字**：
> "In terms of recall, JARVIS achieves a recall of **0.82** and **0.66**"（两个基准/设置）

**用法**：支撑"召回率可以往上推，但代价是精度与工程复杂度"。
**⚠️**：我只核到这两个数字的句子，**没有核对它们分别对应哪个基准**。正文若要写"在 PyCG 的基准上"，必须先补这一步；否则只写"JARVIS 报告 0.82/0.66 的召回率"。

---

## 7. CodexGraph（NAACL 2025）✅ / ⬜

**做什么**：把代码库建成图数据库，让 LLM 用图查询语言检索。

**核实**：出处、页码（142–160）、标题均确认。
**⬜ 未核实**：我之前判断"CodexGraph 不报节点数/覆盖率"——**没有在正文里找到证据**。处理方式：Related Work 里**不写这句判断**，只写它做了什么。

---

## 8. RepoAtlas（2026）⬜

**做什么**：给 coding agent 提供"演化中的多模态仓库视图"，包含静态图与任务相关的动态视图。
**核实**：有 comparison table，含 DynamicGTR 等系统；提到 "structural coverage becomes inadequate"。
**⬜ 未细读**。处理方式：正文只作一句背景引用，不写具体数字。

---

## 9–10. ReAct / PagedAttention ⬜ 背景

只用于 Intro/Limitations 的一句话背景（agent 循环范式 / 长上下文的分页管理），**不引任何数字**。

---

## 汇总：正文里允许出现的引用数字

| 数字 | 出处 | 状态 |
| --- | --- | --- |
| PyCG precision 99.2% / recall 69.9% | PyCG 摘要 + 表 | ✅ |
| LocAgent 92.7% file-level | LocAgent 摘要 | ✅ |
| ARISE Pass@1 22.0%（66/300）、Function R@1 0.43→0.60 | ARISE 表 2 + 正文 | ✅ |
| ARISE "drop dynamic dispatch … more harmful than missing edges" | ARISE §图构建 | ✅ |
| Jarvis recall 0.82 / 0.66 | Jarvis 正文 | ✅（基准归属待补） |
| 我们自己：354 符号 / 62.4% 文件 @10 / 27.5% 符号 @10 / 一跳可达 11.9% / 二跳 35.7% / 边解析 46% | `data/*.jsonl` + `tools/analyse*.py` | ✅ 可复现 |

## 待办

- [ ] Jarvis 的 0.82 / 0.66 分别对应哪个基准
- [ ] CodexGraph 是否报告图规模（想写才查，不写就不用查）
- [ ] RepoAtlas 是否值得一句更具体的引用


## 11. Bellam: How Do Small Coding Agents Use Code Graphs and Embeddings? (2026)

核实日期：2026-11-01。官方摘要 https://arxiv.org/abs/2610.33958 与全文 https://arxiv.org/html/2610.33958v1。作者 Saurav Bellam，v1 提交日期 2026-10-25，均从 arXiv citation metadata 核对。

直接相关：grep、embedding、graph 工具组合的消融，按图距离分层，多种小模型（包括 Gemma 4），以及固定修复模型的下游验证。正文讨论图工具收益来自名称查找和短程扩展。这与本稿图的边际价值和字面证据明显重叠，不能忽略或声称首次。

本稿引用用于定位研究范围：该文研究多轮 agent 工具使用；本稿研究固定槽位静态排序中的候选覆盖、金标替换及索引正文干预。两者不是可直接比较的性能基线。详细新颖性评估和待做实验见 `docs/novelty-review.md`。

---

# 历史文献检索记录

以下保留各次检索当时的判断，不代表当前结论；论文定位以新颖性评审和当前稿件为准。

<a id="literature"></a>
## 文献地图（选题用）

> 用法：每个方向 **地基 → 前沿**。地基决定你能不能判断前沿是不是在胡说；前沿决定你的 Related Work 站在哪。
> 纪律：**3 天读完，每天 2 小时**。每篇只读摘要 + 方法节 + 实验表的表头，写三行笔记：*它假设了什么 / 它没做什么 / 我们能接什么*。
> ⭐ = 必读（8 篇）。⚠️ = 我只看到标题或摘要片段，**引用前必须打开原文核对**。
> 最后更新：2026-10-20。

---

## 1. 代码图与程序分析（地基）

> 这一族决定了我们论文的**上半句**：图天生不全，而且这是已知的。

| 级别 | 工作 | 一句话 | 读它为了 |
| --- | --- | --- | --- |
| ⭐ 地基 | **PyCG**（ICSE 2021，[arXiv:2103.00587](https://arxiv.org/abs/2103.00587)） | Python 调用图：precision **99.2%**，recall **69.9%** | 拿到「图漏三成」这个数字的出处 |
| ⭐ 前沿 | **Jarvis**（[arXiv:2305.05949](https://arxiv.org/abs/2305.05949)） | 把 Python 调用图的 recall 往上推 | 看「补全」这件事的理论天花板在哪 |
| 工具 | **tree-sitter**（增量解析器，非论文） | 我们 E2 建图要用的底座 | 决定我们能抽到哪些边 |
| 选读 | 程序切片（slicing）⚠️ | ARISE 的引用基础 | 不理解也能写，理解加分 |

**读完要回答**：为什么图天生不全？哪几类边最容易漏——动态派发、装饰器、`import as`、`getattr`、`__getattr__`？我们的 4 个仓库里哪一类最多？

---

## 2. Agent 与代码库的接口（核心方向）

> 这一族决定**下半句**：所有人都在用图，没人查图。

| 级别 | 工作 | 一句话 | 读它为了 |
| --- | --- | --- | --- |
| ⭐ 地基 | **SWE-agent**（[arXiv:2405.15793](https://arxiv.org/abs/2405.15793)） | 提出「agent–computer interface」：工具设计比模型能力更决定成败 | 我们的 T0/T1/T2 对照的实验范式来自这里 |
| ⭐ 前沿 | **CodexGraph**（NAACL 2025，[ACL](https://aclanthology.org/2025.naacl-long.7/)） | 把仓库抽成图数据库，让 agent 写 Cypher 查询 | 最典型的「图即接口」；看它的消融表里有没有覆盖率 |
| 前沿 | **LocAgent**（[arXiv:2503.09089](https://ar5iv.labs.arxiv.org/html/2503.09089)） | 图引导的定位 agent，把定位拆成图搜索 | 直接对标我们的定位任务 |
| 前沿 | **RepoGraph** / **CGM** ⚠️ | 图聚合 / 图进注意力（要改架构） | 分清「训练派」和「工具派」 |
| ⭐ 最新 | **RepoAtlas**（[arXiv:2609.16936](https://arxiv.org/abs/2609.16936)） | 多模态仓库视图，SWE-bench Verified +2.4 点 | 2026 年的 SOTA 参照；它的 Related Work 就是我们 §2 的骨架 |
| ✅ **已读** | **ARISE**（[arXiv:2605.03117](https://arxiv.org/abs/2605.03117)） | 多粒度程序图（语句级 + def-use），三层工具 API | **不撞车**：只报 Function Recall@1 +17.0 / Pass@1 22.0%，**没报任何覆盖率**；且原文自认「静默丢弃动态派发」。详见 [related-work.md](notes.md#related-work) §3.5 |

**读完要回答**：这五篇里，有几篇报告了自己图的节点数 / 边数 / 覆盖率？（我猜 0 篇——这就是我们的空隙。）

---

## 3. 检索与定位（方法层）

> 我们 E3 的三个对照（BM25 / 官方图 / 重建图）要靠这一族才站得住。

| 级别 | 工作 | 一句话 | 读它为了 |
| --- | --- | --- | --- |
| 地基 | **BM25 / 稀疏检索**（教科书级） | 我们 T0 的基线 | 别让评审说「你用了个弱基线」 |
| 地基 | dense retrieval（双塔） | 语义检索的基线 | 解释为什么官方用 256 维 embedding |
| 前沿 | **OrcaLoca**（ICML 2025） | LLM agent 做 issue localization 的框架 | 定位任务的 SOTA 指标 |
| 前沿 | **RepoBench** ⚠️（ICLR 2024） | 仓库级补全基准 | 检索评测的常用设定 |
| 前沿 | **CodeRAG-Bench** ⚠️ | 检索增强代码生成的基准 | 同上 |
| 最新 | **CLARC**（ICLR 2026）⚠️ | C/C++ 鲁棒代码搜索基准 | 看「鲁棒性」怎么被定义和度量 |

**读完要回答**：定位的 SOTA 是 file-level 还是 function-level？recall@k 的 k 通常取多少？我们报 recall@1/5/10 够不够？

---

## 4. 基准与效度（论文的落脚点）

> 我们最终是一篇「测量」论文，这一族是方法论上的靠山。

| 级别 | 工作 | 一句话 | 读它为了 |
| --- | --- | --- | --- |
| ⭐ 地基 | **SWE-bench**（[arXiv:2310.06770](https://arxiv.org/abs/2310.06770)） | 2294 个真实 GitHub issue + 隐藏测试 | 所有实验的数据来源 |
| 地基 | **SWE-bench Verified**（OpenAI） | 人工筛过的 500 条 | 我们最可能的实验集 |
| ⭐ 前沿 | **The SWE-Bench Illusion**（ACM，[DOI](https://dl.acm.org/doi/10.1145/3786583.3786882)） | 模型可能是在「回忆」而非推理 | 效度批判的标准写法 |
| 前沿 | **Dataset Quality for SE Tasks**（ACM）⚠️ | 数据集质量如何影响任务结论 | 我们的「打包事故」那一节的先例 |

**读完要回答**：效度类论文的**证据强度**长什么样？（是统计检验、还是逐任务枚举？）我们只有 30–129 个任务，够不够？

---

## 5. 小模型 / 预算受限（背景，不深读）

| 工作 | 一句话 |
| --- | --- |
| **ReAct**（[arXiv:2210.03629](https://arxiv.org/abs/2210.03629)） | 推理-行动交替的原始范式 |
| **mini-SWE-agent**（[mini-swe-agent.com](https://mini-swe-agent.com/latest/)） | 100 行实现的 agent，证明循环本身不重要 |
| **PagedAttention**（[arXiv:2309.06180](https://arxiv.org/abs/2309.06180)） | 32K 上下文的显存账 |

这一族**只写进 Introduction 和 Limitations**，不占正文。

---

## 6. 三天读法

| 天 | 读什么 | 产出 |
| --- | --- | --- |
| **D1** | PyCG → SWE-bench → SWE-agent | 搞清楚「图漏三成」和「ACI 决定成败」这两句话的出处 |
| **D2** | CodexGraph → LocAgent → **ARISE** | **撞车结论**：ARISE 到底报了什么粒度 |
| **D3** | RepoAtlas → The SWE-Bench Illusion | 写完 §2 Related Work 的 280 词草稿 |

---

## 7. 读完必须能回答的 5 个问题

1. **有没有人报过「agent 用的图覆盖了多少代码」？**（如果 ARISE 报过，我们的新意要退到「打包事故 + 代价换算」）
2. ARISE 报的是节点级、文件级、还是边级覆盖率？
3. 定位任务的 SOTA 数字是多少，用的是什么指标？
4. 用什么指标比较三个检索器才公平——recall@k 还是 resolved？两者差多少？
5. 用一句话说服自己：**为什么这篇论文现在写、由我们写？**

第 5 题答不上来，就不要动笔。

---

<a id="literature-2026"></a>
## 2026 年这半年，和我们撞题的论文

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

---

<a id="related-work"></a>
## 相关工作与定位（2026-10-20 初查）

> 方法：4 组关键词的网页检索 + 2 篇精读摘要（CodexGraph、RepoAtlas）。**未逐篇读全文**，标 ⚠️ 的引用待精读后再写进论文。
> 用途：确认「我们这句话有没有人说过」。结论：**没人说过，但旁边的位置已经站满了人。**

---

## 1. 五个簇

### A. 代码图 → 上下文的 agent（最拥挤）

| 工作 | 做了什么 | 默认假设 |
| --- | --- | --- |
| **CodexGraph**（NAACL 2025） | 把仓库抽成图数据库，让 agent 写图查询语言取上下文；在 CrossCodeEval / SWE-bench / EvoCodeBench 上评测 | 图是完整的 |
| **RepoGraph**（Ouyang et al. 2025）⚠️ | 在仓库级代码图上做多跳聚合 | 图是完整的 |
| **LocAgent**（Chen et al. 2025）⚠️ | 图引导的 LLM 定位 agent | 图是完整的 |
| **CGM**（Tao et al. 2025）⚠️ | 把图塞进模型注意力，需要改架构与训练 | 图是完整的 |
| **RepoAtlas**（2026） | 多模态仓库视图（选-投影-刷新），SWE-bench Verified 上 +2.4 点 | 图是完整的 |

**共同点**：都在比「谁的图用法更聪明」，没有一篇报告**这张图本身覆盖了多少代码**。

### B. 定位（localization）作为独立问题

- **OrcaLoca**、**Issue localization via iterative code graph searching**、**LARGER**、**ARISE**（2026）⚠️
- 关心的是「几轮命中」，不是「检索的底座是否漏了东西」。

### C. 静态分析的精度上限（PL 一侧，早就知道）

- **PyCG**（ICSE 2021，[arXiv:2103.00587](https://arxiv.org/abs/2103.00587)）：Python 调用图，**precision ≈ 99.2%，recall ≈ 69.9%**
- **Jarvis**（[arXiv:2305.05949](https://arxiv.org/abs/2305.05949)）：把 recall 往上推

**关键**：PL 社区十几年前就知道调用图召回率只有七成左右。而 A 簇的 agent 论文**一篇都没引用这个事实**。

### D. 代码检索 / RAG 基准

- RepoBench、CodeRAG-Bench 一类 ⚠️：测「检索器能不能找到」，不测「索引里有没有」。

### E. 评测效度（我们 v2 的方向）

- SWE-bench 的污染与效度批评已有多篇 ⚠️；但**针对 agent 的图资产**的效度研究没搜到。

---

## 2. 我们的位置

一句话：**A 簇假设图是完整的，C 簇证明图不完整，中间没有人做过桥。**

三条可写的贡献：

1. **桥**：把 PL 的「调用图 recall ≈ 70%」第一次落到一个**正在被 agent 使用的、已发布的图资产**上，给出符号级覆盖率。
2. **代价**：这个缺口换算成定位 recall@k 掉多少点——A 簇的消融表里没有这一行。
3. **打包缺陷**：129 任务 ↔ 127 commit 的硬链接断掉（社区报告的 0 字节文件）。这是**工程事故**，不是算法精度，PL 文献里没有，agent 文献里也没人检查。

---

## 3. 风险：最近的三篇

| 最像的工作 | 差在哪 | 一句话区分 |
| --- | --- | --- |
| RepoAtlas（2026） | 它改善**视图**，我们质疑**底座** | 「你优化的是怎么选，我量的是有没有」 |
| PyCG / Jarvis | 它们报 precision/recall，我们报**对 agent 任务的影响** | 「召回率 70% 对编译分析是常识，对 agent 是致命的」 |
| ARISE（2026） | **已精读，不撞车**（见 §3.5） | 它比谁的图更**深**，我们量图有**多全** |

## 3.5 ARISE 精读结论（2026-10-20，已排除撞车）

**它做了什么**：在 SWE-agent 上加「多粒度程序图」——结构边（Contains/Imports/Calls/Inherits）**再加语句级节点与过程内 def-use 边**，通过三层工具 API 暴露，核心是 `get_dataflow_slice`。
**数字**：SWE-bench Lite（300 题 / 11 个 Python 仓库），Qwen2.5-Coder-32B；Function Recall@1 **+17.0**、Line Recall@1 **+15.0**、Pass@1 **22.0%（66/300）**，比 SWE-agent **+4.7**。
**它没做什么**：**没有报任何图覆盖率指标**——只报端任务结果。

**为什么它反而帮我们**：原文自己写了建图时的取舍——

> "spurious edges (false positives) cause agents to follow incorrect paths, which can be more harmful than missing edges... We therefore restrict resolution to unambiguous cases... and **silently drop dynamic dispatch through attribute access**."

也就是说：**它明知会漏边，仍然选择静默丢弃，并且从不回报丢了多少。** 这正是我们的论文要量的东西。这句话可以直接引成我们 Introduction 的动机。

**顺带拿到的对标数字**（都来自 ARISE 的 Related Work，引用前仍需回原文核）：

| 系统 | 指标（SWE-bench Lite） |
| --- | --- |
| LocAgent | 92.7% **file-level** accuracy（微调 Qwen2.5-32B） |
| OrcaLoca | 65.33% **function** match |
| ARISE | Function Recall@1 +17.0 / Pass@1 22.0% |

**结论**：这个社区的量纲是 file-level accuracy / function recall@1 / resolved。我们的覆盖率可以直接挂在这个量纲上——「覆盖率 → function recall@1 → resolved」是一条评审一眼能看懂的因果链。

---

## 4. 对选题的影响

**坏消息**：A 簇太挤，如果论文写成「我们也用图做定位」，Novelty 大概 2 分。

**好消息**：正因为挤，**「你们的图到底全不全」这个问题才显得扎心**，而且没人问过。3000 词刚好够讲这一个问题。

**需要调整的一处**：原来说「覆盖率是新颖点」不准确——**PL 圈知道图不全**。真正的新颖点是：
> **在 agent 这条链路上，这个已知的精度损失从来没有被计入成本。**

这句话要写进 Introduction 第二段。

---

## 5. 待办

- [ ] 精读 ARISE（2026）——最可能撞车
- [ ] 精读 LocAgent 的消融表，确认它有没有报图规模/覆盖率
- [ ] 补 RepoGraph / CGM / OrcaLoca 的准确 arXiv 号
- [ ] 查「SWE-bench 定位 oracle」类工作：有没有人报过「知道文件位置能涨多少」
- [ ] 把本文档压缩成论文 §2 的 280 词

---
