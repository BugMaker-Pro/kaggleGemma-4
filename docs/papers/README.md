# 论文 PDF 索引（10 篇）

> 下载：2026-10-20，来源 arXiv / ACL Anthology。
> PDF 已在 `.gitignore` 里（不进仓库）。这份索引进仓库。
> 读法见 [../literature.md](../literature.md)：**每篇只读摘要 + 方法节 + 实验表头**，写三行笔记。

## 地基（先把这三篇读透）

| 文件 | 题目 | 出处 | 读的时候只盯 |
| --- | --- | --- | --- |
| `PyCG_callgraph_python.pdf` | PyCG: Practical Call Graph Generation in Python | ICSE 2021 | 表里的 precision **99.2** / recall **69.9**——我们整篇论文的地基数字 |
| `SWE-bench.pdf` | SWE-bench: Can Language Models Resolve Real-World GitHub Issues? | ICLR 2024 | 数据怎么造的、`patch` / `test_patch` / `FAIL_TO_PASS` 各是什么 |
| `SWE-agent_ACI.pdf` | SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering | NeurIPS 2024 | ACI 的定义；为什么工具设计比模型更决定成败 |

## 主战场（决定我们的 Related Work 怎么写）

| 文件 | 题目 | 出处 | 读的时候只盯 |
| --- | --- | --- | --- |
| `CodexGraph.pdf` | CodexGraph: Bridging LLMs and Code Repositories via Code Graph Databases | NAACL 2025 | 消融表里**有没有**报节点数 / 覆盖率（我判断没有） |
| `LocAgent.pdf` | LocAgent: Graph-Guided LLM Agents for Code Localization | 2025 | 92.7% file-level 是怎么算的、图有多少节点 |
| `ARISE.pdf` | ARISE: A Repository-level Graph Representation and Toolset for Agentic Fault Localization and Program Repair | 2026 | §3.2 建图取舍：原文自认「silently drop dynamic dispatch」——我们的动机句 |
| `RepoAtlas.pdf` | RepoAtlas: Guiding Coding Agents via Evolving Multimodal Repository Views | 2026 | 最新的视图路线；它的 Related Work 就是我们 §2 的骨架 |

## 方法参照（E3 的三个对照要用）

| 文件 | 题目 | 出处 | 读的时候只盯 |
| --- | --- | --- | --- |
| `Jarvis_callgraph_python.pdf` | Jarvis: Scalable and Precise Application-Centered Call Graph Construction for Python | 2023 | recall 能推到多高、代价是什么（这就是我们「重建图」的天花板） |

## 背景（只写进 Intro / Limitations，不占正文）

| 文件 | 题目 | 出处 | 读的时候只盯 |
| --- | --- | --- | --- |
| `ReAct.pdf` | ReAct: Synergizing Reasoning and Acting in Language Models | ICLR 2023 | 引用一句就够 |
| `PagedAttention.pdf` | Efficient Memory Management for LLMs with PagedAttention | SOSP 2023 | 32K 上下文的显存账 |

---

## 没下到的（要另找）

| 目标 | 状态 | 备注 |
| --- | --- | --- |
| **The SWE-Bench Illusion** | ✗ | ACM DOI `10.1145/3786583.3786882`，可能需要机构登录；先找 arXiv 版 |
| **RepoBench** | ✗ | 只有 PyPI 包，没定位到论文页 |
| **CodeRAG-Bench** | ✗ | 还没确认 arXiv 号 |
| **CLARC**（ICLR 2026） | ✗ | 只看到二手笔记 |
| **SWE-bench Verified** | ✗ | 是 OpenAI 的博客，不是论文；用的时候引 URL |

> ⚠️ 上面五个都**不要凭印象编引用**，找不到就换成能读到的替代品。
