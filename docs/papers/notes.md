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
