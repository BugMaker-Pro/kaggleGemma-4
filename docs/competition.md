# Gemma 4 Developer Agent 双赛道完整说明

> 整理时间：2026-10-19（北京时间），**2026-10-20 用无头渲染核实了论文赛道的全部规则**（见 [kaggle-paper-track-raw.md](kaggle-paper-track-raw.md)）。
> 核查方式：日期/奖金/提交限制等硬字段来自 Kaggle 内部接口 `competitions.CompetitionService/GetCompetition` 的原始返回（2026-10-19 抓取）；技术约束与环境细节来自主赛道官方 harness 的第三方逐条核对（[Pilkwang Kim 长文](https://pilkwangkim.github.io/posts/Gemma-4-Developer-Agent-From-Issue-to-Verified-Patch/)，核对日 2026-09-25）。凡是我无法直接读到原文的，都在文中标了 **⚠️ 待核实**，请不要当成官方规则使用。

---

## 0. 一页速览

| | 主赛道 Developer Agent | 论文赛道 Paper Track |
| --- | --- | --- |
| 全称 | Google – The Gemma 4 Developer Agent Competition | Google – The Gemma 4 Developer Agent Paper Track |
| 你要交的东西 | `submission.zip`（一个 agent 包，运行后为每个 issue 生成 patch） | 一篇 Kaggle Writeup（研究论文） |
| 截止（UTC） | 2026-12-02 23:59 | **2026-11-12 23:59** |
| 截止（北京时间） | 2026-12-03 07:59 | **2026-11-13 07:59** |
| 距整理日剩余 | ≈ 45 天 | **≈ 24 天** |
| 奖金 | $65,000（1st $37,000 / 2nd $18,000 / 3rd $10,000） | $35,000（Best Paper $15k / Best New Resource $10k / Best New Application $10k） |
| 名次数 | 3 | 3（三个独立奖项） |
| 队伍上限 | 5 人 | 5 人 |
| 当前规模 | 3,228 队 / 3,574 人 / 17,867 次提交 | 285 队 / 302 次提交 / 5,292 人已加入 |
| 每日提交 | 1 次（计分 2 次） | 5 次（计分 2 次） |
| 身份验证 | 必须 | 必须 |
| 关系 | —— | **不要求**参加主赛道，但官方鼓励两边都参加 |

一句话：**主赛道比「谁修的 bug 多」，论文赛道比「谁把这件事讲清楚、并给出可复现的研究贡献」。** 论文可以用主赛道的实验作为素材，但也可以完全独立。

---

## 1. 比赛要解决的是什么问题

这不是一个「给输入、预测数值」的比赛，而是一个 **repo-level software engineering agent** 比赛。

每个任务给你三样东西：

1. **一个 issue**：`problem_statement`，一段自然语言的 bug 报告或功能请求（可能带 stack trace，也可能只是模糊描述）。
2. **一个仓库快照**：某个开源仓库在 `base_commit`（参考修复之前的那个 commit）时刻的完整代码、测试、配置和 git 历史。
3. **一个沙箱**：在 `/workspace` 下，你可以读文件、跑测试、改代码，但**没有网络**。

你要产出的是 **一个 patch**（git diff）。评判标准是：把这个 patch 打到干净的仓库副本上，跑官方隐藏的验证测试，**通过 = resolved**。最终分数是 resolved 任务占全部任务的比例。

| | 普通 Kaggle 预测赛 | 本比赛 |
| --- | --- | --- |
| 评测时输入 | 未见过的数据行 | issue 描述 + 仓库快照 |
| 你要产出 | 一个预测文件 / 推理 notebook | 一个能**自动生成 patch** 的 agent 包 |
| 评分 | 与 label 比较的指标 | 隐藏测试通过率（resolved rate） |
| 提交的到底是什么 | 模型/权重/推理代码 | 一套「解题流程」：prompt、工具、循环、限额 |

关键含义：**你提交的不是针对公开 issue 的一组补丁，而是面对新 issue 的解法。** 参考补丁（`patch`）和验证补丁（`test_patch`）只存在于开发集里，隐藏任务上你看不到。

### 1.1 为什么这件事难

- **定位（localization）**：issue 说「limit 设成 0 却返回了 10」，你要先找到是哪一层把 0 变成了 10。可能是一行代码，但要跨越整个仓库才能确定那一行。
- **多轮**：一次搜索只能得到一个文件名，读文件才能看到函数，跑测试才能推翻假设。每一步依赖上一步的观察，所以是 agent 循环，不是单次推理。
- **验证**：改完之后要知道「改对了没有」。改动本身可能是错的，也可能是对的但改错了地方（比如改了调用方而不是共享 helper）。
- **预算**：上下文只有 32K，总时间只有 12 小时（详见 §6）。

---

## 2. 两条赛道

### 2.1 主赛道（Developer Agent）

- 固定 base model：`gemma-4-31b-it-qat-w4a16-ct`（`it` = instruction tuned，`qat` = quantization-aware training，`w4a16` = 4-bit 权重 / 16-bit 激活，`ct` = compressed-tensors 打包）。**所有 agent 和 subagent 必须用这一个模型**；harness 里存在别的模型别名，但那些不是参赛资格内的选择。
- 提交 `submission.zip`：ADK（Agent Development Kit）风格的声明式 agent 配置 + prompt + 可选 LoRA adapter + 沙箱内可用工具声明。**不是**任意 Python 入口。
- 运行方式：Kaggle 把你的包跑在一批隐藏 issue 上，**顺序执行**，累积计时；产出 patch 后由独立评分器验证。
- 排行榜按 resolved 比例排名，`leaderboardPercentage: 50`（公开/私榜各占一半）。

### 2.2 论文赛道（Paper Track）

- 提交形式：**Kaggle Writeup**，描述你的方法、实验和细节。
- 官方原话（经 givemechallenge 转载，与 Kaggle 简介一致）：
  > While The Gemma 4 Developer Agent Competition leaderboard ranks participants by bugs fixed, the Paper Track invites you to contribute research to advance the state-of-the-art in agentic software engineering. You will submit a Kaggle Writeup that describes your methods, experiments, and other details. Participation in the main competition isn't required to submit to the Paper Track, though we encourage participants to join both. **Submissions can include any related research, as long as it is unpublished.**
- 主题范围：任何与「让开放模型在本地/消费级硬件上做可靠的软件工程 agent」相关的研究——定位、上下文管理、工具设计、验证、训练/后训练、评测方法都可以。
- **「未发表」（unpublished）是硬条件**：已公开发表的论文不能再投。官方另有 **Non-Archival** 条款——参赛不阻止之后投别的会或发预印本。所以口径是「**提交那一刻**未发表」，交完再公开没问题。

### 2.3 对比

| 维度 | 主赛道 | 论文赛道 |
| --- | --- | --- |
| 评委 | 自动化测试 + 隐藏测试 | 人工评审，五维各 0–5 取平均（已核实） |
| 胜负手 | 修复率、时间预算控制 | 新颖性、严谨性、可复现性、对该领域的贡献 |
| 最低可交付 | 一个能跑通并产出非空 diff 的包 | 一篇能自圆其说、实验可复现的论文 |
| 是否需要 GPU | 需要（复现/调优时） | 取决于选题；纯分析类可以先用公开轨迹 |
| 与另一赛道 | —— | 可以把主赛道的 agent 与实验作为论文素材 |

---

## 3. 主赛道技术约束（直接决定论文实验怎么设计）

| 约束 | 数值 | 对设计的含义 |
| --- | --- | --- |
| 模型 | `gemma-4-31b-it-qat-w4a16-ct`，不可换 | 消融只能在 prompt / 工具 / 循环 / adapter 上做 |
| 推理硬件 | 4 × L4，合计 96 GB 显存 | 本地别的卡上的时延不能直接外推 |
| 上下文 | 32,768 tokens（Kaggle serving 合约，不是模型卡的 256K） | 指令 + issue + 观察 + 思考 + 输出全在里面 |
| 总生成时间 | **12 小时**（全部任务，含环境准备） | 平均分到每个任务可能只有 3–6 分钟 |
| 提交包体积 | 解压后 < 3 GiB | 不能塞 base model，只能放配置和小 adapter |
| 沙箱 | Docker，4 GiB RAM / 2 vCPU，**离线** | 依赖必须来自官方 wheelhouse |
| 工具输出 | 命令输出默认截断 5,000 字符；`read_file` 上限 150 行 / 10,000 字符 | 「把仓库打印出来」不可行 |
| 提交格式 | `submission.zip`，声明式配置 | 不能写任意 host 端 Python 入口 |
| 提交频率 | 每天 1 次，计分 2 次 | 改一版要等一天，必须本地先验证 |

### 3.1 两个独立的「内存」概念

- **GPU 显存**：跑模型用的，96 GB。
- **沙箱 RAM**：跑 `pytest`、`pip install` 用的，4 GiB。
两者不通用。给模型更多显存不会让一个吃 5 GiB 的测试进程跑起来。

### 3.2 两个时钟

- 本地 agent session 计时从任务环境准备好之后开始。
- 官方 12 小时**包含**环境准备。所以单任务超时只控制了一部分总时长。
- 官方已说明隐藏任务是**顺序**跑的；额度耗尽会导致提交失败（后续计划改成「未完成任务记 0 分」，⚠️ 是否已上线待核实）。

---

## 4. 公开数据长什么样

主赛道的公开开发集包含（`tasks.jsonl` + 一批伴随资源）：

| 资源 | 用途 |
| --- | --- |
| `tasks.jsonl` | 每行一个任务：`instance_id`、`repo`、`base_commit`、`problem_statement`、`hints_text`、`patch`（参考修复）、`test_patch`（验证测试）、`created_at` |
| `snapshots/<instance_id>.tgz` | 还原 `base_commit` 时刻的仓库 |
| `graphs/` | 代码符号关系图（`get_code_neighbors` / `get_code_subgraph`） |
| `embeddings/` | 符号向量（`search_similar_code`） |
| `wheels/` | 历史依赖 wheel，供离线安装 |
| `docker/`、`sandbox/` | 环境构建 |
| `sample_submission/` | 官方配置示例 |
| `HARNESS_README.md` | 执行与提交合约 |

### 4.1 已知的数据问题（写论文时要么绕开、要么当成贡献）

1. **`graphs/` 和 `embeddings/` 各有 129 个 0 字节文件**——原因是任务名/commit 名的 hard link 处理，社区在 [discussion/742911](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742911) 报告过，官方确认在查。另有参与者报告 async 函数缺失。
   → 含义：**你的 agent 必须在图查询失败时也能干活**，文本搜索 + 自己解析 AST 是必须的兜底。
2. **公开数据的 `hints_text` 全是空的**，尽管 schema 允许有值。→ baseline 不能依赖 hints。
3. **公开任务来自 4 个公开仓库，隐藏任务来自私有仓库**。→ 在公开仓库上「记住答案位置」的启发式不会迁移，论文里要论证你的方法是**可迁移的调试行为**而不是仓库先验。

---

## 5. 论文赛道：提交什么、评委看什么

### 5.1 已核实的事实

- 提交载体是 **Kaggle Writeup**（该比赛 `hackathon: true`，是 Kaggle 的 writeup 型比赛）。
- 奖金 $35,000，**分三个独立奖项**：Best Paper $15k、Best New Resource $10k、Best New Application $10k；队伍上限 5 人；需要身份验证。
- **3,000 词上限**（不是页数）；五个强制小节：Title+Subtitle / Abstract / Introduction / 方法与实验 / 相关工作与引用。
- 代码与 PDF 都是**可选**：代码走 Public Notebook，PDF 走 Public Project Link；都不是必交项。
- 不参加主赛道也可以投论文。
- 必须是**未发表**的研究；但有 **Non-Archival** 条款——参赛不阻止之后投别的会或发预印本。
- 全部原文见 [kaggle-paper-track-raw.md](kaggle-paper-track-raw.md)。

### 5.2 已核实（2026-10-20，Edge 无头渲染抓取，原文见 [kaggle-paper-track-raw.md](kaggle-paper-track-raw.md)）

| 问题 | 答案 |
| --- | --- |
| 篇幅 | **3,000 词上限**（按词不按页） |
| 格式 | 站内 Kaggle Writeup；PDF 可选（Public Project Link） |
| 评审 | 五维各 0–5 取平均：Novelty / **Quality** / Relevance / Verifiability / Clarity |
| 强条款 | Quality 明确要求「跨出本比赛仍可迁移」 |
| 开源 | 不强制；Public Notebook 可选，公开且不需登录 |
| 奖项 | 三个：$15k / $10k / $10k，其中两个不是「最佳论文」 |
| 评委 | Elan Markowitz（Google）+ 引用名单含 Perozzi / Galkin / Rózemberczki（图 ML） |
| 排行榜 | 页面注明不授予积分与奖牌；只统计提交数 |
| 未发表 | 提交时必须未发表；**Non-Archival**，之后可投别处 |
| 私榜成绩 | 页面未禁止，但论文里引用自己比赛成绩会削弱「跨比赛可迁移」这一维 |

> 结论：**篇幅紧（3000 词）、评分重可迁移性、奖项给资源留了位置**。这三点直接决定了 [paper-topic.md](paper-topic.md) 的选题。

---

## 6. 预算怎么算（论文里必须交代的部分）

### 6.1 时间

顺序执行的生成总时长：

```
T_gen = h + Σ (s_i + a_i) ≤ 720 分钟
```

- `h`：一次性开销（模型加载等）
- `s_i`：第 i 个任务的准备/清理开销
- `a_i`：第 i 个任务的 agent session 时间
- 验证时间**不计入**这个预算

若有 120 个任务：720 / 120 = **6 分钟/任务（含准备）**。这不是官方配额，只是一个规划用的平均数。3 分钟 agent 超时 → 约 360 分钟 agent 时间，剩 360 分钟给准备开销。

### 6.2 上下文

```
C_prompt + M_requested ≤ 32,768
```

如果你预留 8,192 tokens 给输出，输入最多 24,576 tokens。**即使最终回答很短，这个准入条件也成立**——不是「答得短就能多塞输入」。

工具观察预算（默认值）：命令输出 5,000 字符，`read_file` 150 行 / 10,000 字符。所以有效上下文管理 = 知道什么时候该停、该丢什么。

---

## 7. 时间线（倒排，北京时间）

| 时间 | 论文赛道 | 主赛道 |
| --- | --- | --- |
| 10/19 – 10/26 | 读完规则、定选题、搭本地评测 | 拉数据、跑通一个任务 |
| 10/27 – 11/05 | 主实验 + 消融（至少 8–12 个 dev 任务） | baseline 迭代 |
| 11/05 – 11/09 | 写作（**3,000 词**），出图 | —— |
| 11/11 – 11/12 | 内审、查格式、**提交** | —— |
| **11/13 07:59** | **截止** | —— |
| 11/13 – 11/25 | —— | 继续冲榜（团队合并截止 11/26 07:59） |
| 11/26 – 12/03 07:59 | —— | 最后冲刺，12/03 07:59 截止 |

**论文赛道的真实可用时间只有 3 周多一点**，其中还要留出写作时间。这意味着选题必须「小、可做、可复现」，不要选需要大规模训练的方向当主线。

> ⚠️ 这张表是 v1 视角，**当前权威排期见 [paper-topic.md](paper-topic.md) §7**（逐日到 11/12 提交）。

---

## 8. 参赛前置条件（现在就能做，不需要 shell）

- [ ] Kaggle 账号完成**身份验证**（手机号/证件）。这是硬门槛，且可能需要几小时到几天。
- [ ] 在比赛页点 **Join Competition** 并**接受 Rules**（`rulesRequired: true`，不接受看不到数据、不能提交）。
- [ ] 确认队伍（≤ 5 人）；论文赛道同样有 5 人上限。
- [ ] 记下每日提交次数（论文 5 次/天，主赛道 1 次/天），别把提交次数耗在格式错误上。
- [ ] 备好 GPU 环境（主赛道实验需要 4×L4 等价算力；论文若只做分析类实验可先不用）。

---

## 9. 我们可以做哪些选题

以下是四个可落地的方向，按「3 周内能否做完」排序。

### 9.1 定位策略：文本检索 vs 代码图 vs 混合

- **研究问题**：在 32K 上下文和 4 GiB 沙箱下，把 issue 映射到「该改的文件/符号」，哪种检索最有效？
- **实验**：同一 agent 骨架，只换定位工具（纯 grep / 官方 graph 工具 / 混合），在 8–12 个 dev 任务上比较「首次命中正确文件的轮数」「token 消耗」「resolved 率」。
- **素材**：公开 `graphs/`、`embeddings/`（注意 129 个空文件问题，正好是你的 ablation 条件）。
- **风险**：低。不需要训练，纯 prompt + 工具编排。
- **论文卖点**：图工具在数据损坏时的退化行为 + 文本兜底的收益曲线。

### 9.2 预算调度：时间与上下文怎么分配

- **研究问题**：给定 12 小时总预算和每任务未知难度，如何决定「继续投入还是收手」？
- **实验**：固定 agent，只改停止准则（固定步数 / 固定时间 / 基于「是否已复现失败」的自适应），画 resolved 数 vs 总耗时的曲线。
- **素材**：需要真实的 agent 运行轨迹（本地或 Kaggle 上跑）。
- **风险**：中。需要跑很多次，成本高；但论文的「预算感知」角度很新。
- **论文卖点**：把 `max Σ p_i(t_i)` 这个规划问题变成可测量的经验曲线。

### 9.3 验证驱动修复（self-verification）

- **研究问题**：让 agent 自己写回归测试再改代码，能不能显著提高 resolved 率？
- **实验**：A/B——直接改 vs 先复现失败再改 vs 改完跑自测再迭代。看「假修复」（测试通过但隐藏测试不过）的比例。
- **素材**：只要 dev 任务 + 公开 test_patch 做离线对照。
- **风险**：中低。是当前 agent 研究的热点，容易被评审认可。
- **论文卖点**：把「trajectory 中哪一步让修复失败」量化。

### 9.4 轨迹蒸馏 + LoRA（3 GiB 内）

- **研究问题**：用公开任务的参考轨迹做 agentic SFT，LoRA adapter 能不能在固定模型上带来稳定增益？
- **实验**：构造 `(observation, action)` 数据，训练 adapter，比较有无 adapter 的 resolved 率；控制推理预算一致。
- **素材**：`tasks.jsonl` 的 `patch` 可以生成「正确动作」；需要自己合成轨迹（无官方轨迹）。
- **风险**：高。需要 GPU、需要数据合成管线，3 周内很可能做不完。
- **论文卖点**：如果做出来，故事最完整；但建议作为「附加实验」而不是主线。

**已定（2026-10-20）**：以上四个方向都没选。主线改为 [paper-topic.md](paper-topic.md) 的「代码图覆盖率 + 重建」——9.1 的检索对照被吸收为 E3，9.3 的「验证驱动」降级为主赛道的工程纪律。原因是读到官方评分口径后，「跨比赛可迁移性」是硬约束，前四个方向都绑死在这一个榜上。

---

## 10. 已知坑与风险清单

1. **12 小时顺序执行**——一个任务卡死会拖垮整轮。必须有单任务超时。
2. **32K 上下文**——一次 `cat` 大文件就废掉半个上下文。读文件要分片。
3. **4 GiB 沙箱 RAM**——跑全量 pytest 很容易 OOM，只能跑相关测试。
4. **离线**——任何 `pip install` 都必须命中 wheelhouse。
5. **图/嵌入数据有 0 字节文件**——工具会静默返回空，agent 必须能识别并降级。
6. **每天 1 次主赛道提交**——本地验证不充分就提交，等于浪费一天。
7. **泛化**——公开 4 个仓库 vs 隐藏私有仓库，靠仓库记忆的 trick 无效。
8. **论文「未发表」**——提交前不要公开即可；官方 Non-Archival 条款允许提交后再投别处。
9. **身份验证**——没验证等于没参赛，且验证有延迟。
10. **截止时区**——论文赛道是 UTC 11-12 23:59，即北京时间 11-13 早上 7:59，不要按「12 号晚上」理解。

---

## 11. 参考链接

**官方**
- 论文赛道：[kaggle.com/competitions/gemma-4-developer-agent-paper](https://www.kaggle.com/competitions/gemma-4-developer-agent-paper/overview)
- 主赛道：[kaggle.com/competitions/gemma-4-developer-agent](https://www.kaggle.com/competitions/gemma-4-developer-agent/overview)
- 模型页：[google/gemma-4 · gemma-4-31b-it-qat-w4a16-ct](https://www.kaggle.com/models/google/gemma-4/other/gemma-4-31b-it-qat-w4a16-ct)
- 官方 wheelhouse 数据集：[gemma-4-developer-agent-wheelhouse](https://www.kaggle.com/datasets/metric/gemma-4-developer-agent-wheelhouse/data)
- 图/嵌入损坏报告：[discussion/742911](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/742911)
- 12 小时/顺序执行问答：[discussion/743063](https://www.kaggle.com/competitions/gemma-4-developer-agent/discussion/743063)

**背景阅读**
- 长文教程（本文件技术约束的主要来源）：[Gemma 4 Developer Agent: Learning to Fix a Codebase, One Verified Patch at a Time](https://pilkwangkim.github.io/posts/Gemma-4-Developer-Agent-From-Issue-to-Verified-Patch/)
- SWE-bench 论文：[arXiv:2310.06770](https://arxiv.org/abs/2310.06770)
- mini-SWE-agent：[mini-swe-agent.com](https://mini-swe-agent.com/latest/)
- ADK Agent Config：[adk.dev/agents/config](https://adk.dev/agents/config/)
- Gemma 4 发布公告：[blog.google](https://blog.google/innovation-and-ai/technology/developers-tools/gemma-4/)
- PagedAttention（为什么「权重装得下」不等于「上下文随便给」）：[arXiv:2309.06180](https://arxiv.org/abs/2309.06180)

---

## 12. 术语表

| 术语 | 含义 |
| --- | --- |
| issue | 一段描述「哪里不对/要加什么」的自然语言，可能含 stack trace |
| `base_commit` | 参考修复之前的那个 git commit，是你工作的起点 |
| patch | git diff 形式的代码改动 |
| resolved | patch 打上后，隐藏验证测试全部通过 |
| trajectory | 一次 agent 尝试的完整记录：消息、动作、观察 |
| harness | 官方负责装载 agent、准备环境、执行并评分的软件 |
| loclization | 把 issue 缩小到具体文件/符号的过程 |
| ADK | Google Agent Development Kit，本比赛用它的受限声明式配置 |
| QAT / w4a16 | 量化感知训练 / 4-bit 权重 + 16-bit 激活 |
| Writeup | Kaggle 站内的报告页面，论文赛道的提交载体 |
