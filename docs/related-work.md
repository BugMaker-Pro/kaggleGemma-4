# 相关工作与定位（2026-10-20 初查）

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
