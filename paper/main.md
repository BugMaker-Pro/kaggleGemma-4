# 论文骨架（v3：代码图覆盖率）

> 目标：**3,000 词**，Kaggle Writeup 提交，截止 2026-11-13 07:59（北京时间）。
> 强制小节（官方要求，缺一不可）：Title + Subtitle、Abstract、Introduction、Research description（methods & experiments）、Related works & citations。
> 用法：先把每节「要证明什么」定死，再去填实验。**不要先做实验再找故事。**

选题与实验协议见 [docs/paper-topic.md](../docs/paper-topic.md)，官方原文见 [docs/kaggle-paper-track-raw.md](../docs/kaggle-paper-track-raw.md)。

---

## 题目

**What the Graph Misses: Measuring and Repairing Code-Graph Coverage for Repository-Level Agents**

副标题（Writeup 要求）：
*An audit of 129 released task graphs, a rebuilt alternative, and what it buys a local coding agent*

---

## 摘要（最后写，180 词）

模板：

> Code graphs are now shipped as first-class assets to coding agents, but their coverage is rarely measured.
> We audit the graphs and symbol embeddings released with \<benchmark> across N tasks, and find **X%** of gold-fix symbols are absent.
> We trace the gap to \<三个来源及占比>, then rebuild the graph from the same snapshots with a language-agnostic extractor, raising coverage to **Y%**.
> On a controlled retrieval benchmark, the rebuilt graph improves recall@5 from **A** to **B** at **no additional context cost**.
> We release the extractor, the coverage audit toolkit, and a gold-symbol benchmark, and argue that **coverage, not graph sophistication, is the binding constraint** for small local agents.

**规则**：摘要里每个数字必须能在 §5 找到对应行。写不出来的数字，删掉。

---

## 1. Introduction（350 词）

要回答：

- 为什么定位（localization）是本地小模型做 agent 的第一瓶颈？（算力小 → 不能把仓库塞进上下文 → 必须检索）
- 代码图被当作解法，但没人量过「图里到底有多少代码」
- 我们量了，发现缺口是系统性的，而且补上之后收益可测

**必须有一个具体例子**：一条 issue（例如 `limit=0` 被当成默认值），说明要跨 3 个文件才能定位——用 [docs/task-walkthrough.md](../docs/task-walkthrough.md) §5 的链路。

- [ ] 例子写完
- [ ] 三条贡献，每条对应后面一节

## 2. Related Work（280 词）

| 线索 | 代表工作 | 与我们的差异 |
| --- | --- | --- |
| 仓库级修复基准 | SWE-bench | 他们报 resolved；我们量「检索层能不能找到」 |
| agent 与代码库的接口 | SWE-agent | 我们固定循环，只动检索 |
| 代码图 / 程序图 | CodexGraph 类工作、tree-sitter 系解析 | 他们假设图是完整的；我们测完整性 |
| 检索增强定位 | BM25 / 稀疏检索基线 | 作为 T0 对照 |
| 图神经网络 | node2vec 系（评委背景） | 不作为基线；我们论证覆盖率优先于表示学习 |

- [ ] 每条 2–3 句：他们做了什么 / 我们不同在哪
- [ ] 不写成综述，≤ 280 词

## 3. Setup: the released assets（350 词）

这是可信度的地基。

- 任务构成：FastAPI 67 / Rich 48 / Requests 13 / HTTPX 1，共 129
- 每个任务的资产：`snapshots/<id>.tgz`、`graphs/`、`embeddings/`、`tasks.jsonl` 的 `patch`
- 图的格式与字段（以实际读到的为准，不要凭猜）
- 已知现状：129 个 0 字节文件、async 符号缺失
- 评测口径：resolved 的定义、验证流程（为后文 §6 的推论埋伏笔）

- [ ] 每个数字都注明「实测」还是「文档声称」
- [ ] 有一次 `ls -l` 级别的证据（文件大小分布）

## 4. Method（550 词）

四小节，对应 E0–E3：

1. **黄金符号定义**：从 `patch` 变更行反推符号；歧义规则写清楚；抽检 20 个报一致率
2. **覆盖率度量**：分子/分母定义；按仓库与符号类型分解
3. **重建图**：节点/边类型、解析优先级（同文件 → 同包 → 全仓库唯一名）、`unresolved` 如何标记
4. **检索对照**：T0/T1/T2 三个条件，BM25 参数固定，**同 token 预算**

- [ ] 有一段伪代码或流程图（建图 + 检索）
- [ ] 说清楚「同预算」怎么保证

## 5. Results（750 词，四表两图）

### 表 1 覆盖率

| 仓库 | 任务数 | 官方覆盖 | 重建覆盖 | 提升 |
| --- | ---: | ---: | ---: | ---: |

### 表 2 缺口归因

| 来源 | 计数 | 占比 | 例 |
| --- | ---: | ---: | --- |

### 表 3 检索（主表）

| 条件 | recall@1 | recall@5 | recall@10 | 平均 token |
| --- | ---: | ---: | ---: | ---: |
| T0 文本 | | | | |
| T1 官方图 | | | | |
| T2 重建图 | | | | |

### 表 4 解析成功率（重建器的质量自证）

| 仓库 | 边数 | 已解析 | unresolved |
| --- | ---: | ---: | ---: |

**图 1（主图）**：左 覆盖率条形（官方 vs 重建，按仓库），右 recall@k 三线。
**图 2**：缺口归因堆叠柱。

- [ ] 每个数字有原始文件（`results/*.csv`）
- [ ] 主图在缩到 50% 时仍可读

## 6. Discussion（300 词）

- 对评测方的建议：发布图资产时同时发布覆盖率指标
- 对小模型场景的推论：**覆盖率优先于图算法**；预算应该先花在把图补全
- 对 agent 设计者的建议：先测一下手上的图有没有 0 字节文件

- [ ] 不外推到「所有 benchmark」，只写条件句

## 7. Limitations（150 词）

- 只覆盖 129 个公开任务，且 89% 集中在两个仓库
- 建图器先把 Python 做对，多语言未验证
- 「黄金符号」由 patch 反推，本身有噪声（给出抽检一致率）
- 未评估官方 embedding 的质量（文件为空，无法评估）
- 检索指标是 resolved 率的代理，二者不等价

## 8. Conclusion（90 词）

三句话，不引入新内容。

---

## 主张 → 证据 对照表

写正文前填满。**任何一行没有证据的主张，要么删掉，要么补实验。**

| # | 主张 | 证据 | 状态 |
| --- | --- | --- | --- |
| 1 | 官方图存在系统性覆盖缺口 | 表 1 官方列 + §3 的文件大小证据 | ☐ |
| 2 | 缺口主要来自文件级缺失 | 表 2 | ☐ |
| 3 | 重建可行且覆盖率高 | 表 1 重建列 + 表 4 | ☐ |
| 4 | 覆盖率转化为定位收益 | 表 3 | ☐ |
| 5 | 收益不是靠多塞上下文 | 表 3 的 token 列 | ☐ |

---

## 投稿前检查

- [ ] **≤ 3,000 词**（用工具数，不靠目测）
- [ ] 五个强制小节齐全：Title+Subtitle / Abstract / Introduction / Methods & Experiments / Related Works & Citations
- [ ] 未发表（无 arXiv、无公开博文；Non-Archival 只允许**提交后**再投）
- [ ] 所有数字可追溯到 `results/`
- [ ] 图在深色/浅色下都可读
- [ ] Public Notebook（可选加分项）已公开、不需登录
- [ ] 提交状态确认（截止前 24 小时提交，别卡最后一小时）
