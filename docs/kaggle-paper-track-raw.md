# 官方原文摘录（2026-10-20 抓取，已核实）

> 来源：<https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/overview>
> 抓取方式：Edge 无头模式 `--dump-dom` 渲染后取正文（页面是 JS 渲染，普通抓取只能拿到 `<title>`）。
> 下列英文为原文；方括号内是中文注。**引用官方规则时以本文为准，不要用二手转述。**

---

## 1. Description

> **Note:** there are two active competitions for the Gemma 4 Developer Agent Competition: the featured competition, and this paper track, where you can submit novel, unpublished research or document your approach to the prediction competition. Winning papers will be highlighted at a Google hosted event (such as a NeurIPS expo workshop) and awarded prizes.

> Today's most capable coding agents rely on internet-connected models running on powerful commercial infrastructure. That puts advanced software engineering out of reach for many developers.
>
> Small local models have made rapid progress, but they still struggle with complex, multi-turn software engineering. Large codebases are hard to navigate, making reliable bug fixes and feature additions tough for models that fit on a single accelerator.
>
> While The Gemma 4 Developer Agent Competition leaderboard ranks participants by bugs fixed, the Paper Track invites you to contribute research to advance the state-of-the-art in agentic software engineering. You will submit a Kaggle Writeup that describes your methods, experiments, and other details. Participation in the main competition isn't required to submit to the Paper Track, though we encourage participants to join both. **Submissions can include any related research, as long as it is unpublished.**
>
> Your solution could help put powerful coding assistants in the hands of millions more developers. Sharing how you did it makes advanced coding tools accessible to everyone.

## 2. Timeline

> - September 22, 2026 - Start Date.
> - November 12, 2026 - Final Submission Deadline.
>
> All deadlines are at 11:59 PM UTC on the corresponding day unless otherwise noted.

[北京时间 2026-11-13 07:59]

## 3. Evaluation（评分口径，最关键）

> To be eligible to win the The Gemma 4 Developer Agent Paper Track Prize, you must join this competition and submit a Writeup that documents your research to advance the state-of-the-art for agentic software engineering.
>
> Submissions for Paper Awards are evaluated equally across the following five criteria. Each criterion is scored on a scale from 0 (lowest) to 5 (highest), with the final score calculated as the average of all five.

| Category | Description |
| --- | --- |
| **Novelty** | Does the work provide new insights, deepen understanding, or highlight important properties of existing methods? |
| **Quality** | How general and universal is the Submission approach beyond the competition? Does your submission translate to other similar problems? How well does your method generalize? |
| **Relevance** | Is there significance and/or potential impact of the research on the field of software engineering and agentic learning? |
| **Verifiability** | Does the paper include sufficient information to understand how an innovation works; to understand how data was obtained, analyzed, and interpreted? |
| **Clarity** | Is the paper clearly presented and written? |

> The Paper Award will be awarded to three Submissions with the most points. Your Paper rubric evaluation will not be shared with you. In the event of a tie, the Paper that was entered first to the Competition will be the winner.

[五项等权取平均；**Quality 一维明确要求「跨出本比赛仍可迁移」**，这是选题的硬约束。]

## 4. Submission Requirements

> A valid submission must contain the following:
>
> - The Kaggle Writeup serves as your research paper project report. It should include:
>   - Title and subtitle
>   - Abstract
>   - Introduction
>   - Description of the research, including methods and experiments
>   - Related works and citations
>
> (Optional) Public Notebook: If you choose to submit code, your code should be submitted as a public notebook in the Project Links field. Your notebook should be publicly accessible and not require a login or paywall. If you use a private Kaggle Notebook, it will automatically be made public after the deadline.
>
> (Optional) Public Project Link: Optionally, instead of writing your paper in the Kaggle Writeup, you can also upload an arXiv-ready (LaTeX/Word) PDF version of your paper using the Public Project Link feature. It should be publicly accessible and not require a login or paywall.

### Submission Details

> - **Scope: 3,000 words maximum**, reporting original, unpublished research.
> - **Non-Archival:** Submission to this competition does not prevent submission to other conferences or venues.
> - Additional Assets: The below assets are optional.

[**3000 词**，不是页数。Non-Archival 意味着交完可以再投别处/发 arXiv，但**提交时必须未发表**。]

### Submission Topics（推荐方向，非穷举）

> - **Tuning & Optimization**: Parameter-efficient fine-tuning and Reinforcement Learning (RL) approaches tailored to improve SWE agent capabilities.
> - **Code Comprehension**: Novel techniques for code-graph generation, parsing, and embedding to enhance deep comprehension of complex repositories.
> - **Tasks & Benchmarks**: Development of new tasks, evaluation datasets, or resources targeting code structure, graphs, and structured code generation.
> - **Graph Reasoning**: Methods and architectures for improving Large Language Model (LLM) reasoning over large-scale graphs.

[四条里三条围绕 code graph；第二条几乎就是本方案的题目描述。]

> Share your writeup by November 12, 2026 at 11:59pm UTC. **Your final Submission must be made prior to the deadline. Any un-submitted or draft Writeups by the competition deadline will not be considered by the Judges.**

## 5. Tracks and Awards

> Total Prizes Available · $35,000

| 奖项 | 金额 | 原文说明 |
| --- | ---: | --- |
| **Overall Best Paper** | $15,000 | highest score calculated as the average of all five criteria |
| **Best New Resource (Dataset, library, etc)** | $10,000 | "A resource introduces a new dataset, tool, or software... a new 'dataset' could leverage the provided embeddings or other sources to create a dataset that can be used for either evaluation of Gemma 4 or for fine-tuning it. A new 'tool' could be a library which uses Gemma and some other algorithm to cluster code based on underlying behavior. New 'software' could be a dashboard to explore Github repos that are similar in structure to a target repo." |
| **Best New Application** | $10,000 | "A novel application is a new use-case (e.g. using code-graphs for writing TPU kernels). Show your creative uses of code-graphs and/or the provided embeddings... It could also involve application to existing benchmarks that differ from the provided ones." |

> Top submissions will be highlighted at a Google hosted expo during NeurIPS 2026.

[**三个奖，其中一个（Best New Resource）与「最佳论文」无关**——造工具/数据集也能拿 $10k。]

## 6. Judges / Citation

> Judges: **Elan Markowitz**, Machine Learning Engineer, Google
>
> Citation: Elan Markowitz, Bryan Perozzi, Benedek Rózemberczki, Glenn Cameron, Hadi Hemmati, Yuchen Li, Michael Galkin, Majid Farhadi, Ryan Holbrook, and Ashley Oldacre. *Google - The Gemma 4 Developer Agent Paper Track*. 2026. Kaggle.

[Perozzi = node2vec 一作；Galkin / Rózemberczki 均为图 ML。评委画像明确偏向 code graph 与图推理。]

## 7. 规模（抓取时）

> 5,292 Entrants · 294 Participants · 285 Teams · 302 Submissions · Does not award Points or Medals

---

## 8. 阅读结论（给选题用）

1. **字数 3000**，五节强制结构（标题/摘要/引言/方法实验/相关工作与引用）。超字数、缺小节都是硬伤。
2. **五项等权**，其中 Quality 要求「跨比赛可迁移」→ 只对一个榜单成立的结论拿不到高分。
3. **三个奖**，两个不是最佳论文 → 交付「资源」有独立赛道。
4. **题目清单与评委都偏 code graph** → 选题贴图，命中率最高。
5. **不要求开源**，但 Public Notebook 是可选的加分项；本方案最后一天要放一个能跑的 notebook 进去。
