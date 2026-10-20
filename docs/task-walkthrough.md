# 一次 bug 修复任务，具体要你做什么

> 对象：主赛道（Developer Agent）。论文赛道不要求你跑这个流程，但论文里的实验就是跑它。
> 来源：官方 harness 的第三方逐条核对（[Pilkwang Kim 长文](https://pilkwangkim.github.io/posts/Gemma-4-Developer-Agent-From-Issue-to-Verified-Patch/)，2026-09-25），以及 Kaggle 竞赛元数据。原文抓不到的段落（提交包精确 schema）标 ⚠️。

---

## 0. 一句话

**你要交的不是补丁，是一台「会产补丁的机器」。**

比赛不会给你 issue 让你手工修。它给你一个 `submission.zip`——里面是 agent 的配置、提示词、可选的小 adapter——然后把这台机器放到一批你从没见过的 issue 上跑，看它自己能不能修好。

所以「怎么做」分两层：

1. **一次性**：设计并打包这台机器（prompt、工具、循环、限额）。
2. **每个任务**：机器自己在沙箱里读代码、改代码、验证、交 diff。

---

## 1. 每个任务长什么样

数据集里一行就是一个任务：

| 字段 | 内容 | 你能不能用 |
| --- | --- | --- |
| `instance_id` | 任务 ID | 能 |
| `repo` + `base_commit` | 哪个仓库、哪个提交之前的版本 | 能（快照就是按这个还原的） |
| `problem_statement` | issue 正文：现象、期望、有时带 stack trace | 能，这是唯一的任务描述 |
| `hints_text` | 额外线索 | 公开数据里**全是空的**，别依赖 |
| `patch` | 官方参考修复 | **只在开发集有**，隐藏任务没有 |
| `test_patch` | 官方验证测试 | **只在开发集有**，隐藏任务没有 |
| `created_at` | 时间戳 | 能（可用来切分训练/开发/留出） |

隐藏任务上，你只有 `problem_statement` + 一个仓库快照。**参考修复和验证测试都在评测方手里，agent 碰不到。**

沙箱里的仓库：

- 路径 `/workspace`
- 有 git 历史，但**参考修复之后的 commit 已被移除**——翻 git log 找不到答案
- **没有网络**，装依赖只能靠官方 wheelhouse
- 4 GiB RAM / 2 vCPU（跑 pytest 的那个环境，不是跑模型的 GPU）

---

## 2. 评测时到底发生什么

两个**隔离**的环境，先生产，后检验：

```
[agent 配置 + 可选 adapter] ──┐
[issue 描述] ─────────────────┼──> harness 循环 <──> Gemma 模型服务
                              │         ↕ 工具调用 / 观察
                              └──> 沙箱 A：可写的 /workspace
                                        │
                                  提取 git diff
                                        ↓
                              沙箱 B：全新副本
                              + 你的 diff
                              + 还原被改过的测试文件
                              + 官方 test_patch
                                        ↓
                                 resolved / unresolved
```

### 阶段 A：生成（agent 干活）

agent 循环：读代码 → 形成假设 → 改 → 跑一个局部检查 → 根据结果决定下一步。

结束时调用 `submit_patch()`，它做的是：

```bash
git add -N .                              # 让新建的未跟踪文件也出现在 diff 里
git diff --binary _swegemma_baseline      # 相对准备好的基线取 diff
# 基线不可用时回退：
git diff --binary HEAD
```

注意第一行：`git add -N` 只是登记意图，不产生 commit，作用是**让临时新建的文件也进入 diff**。这意味着你在仓库里随手丢的 `repro.py`、`debug.log`，会**一起被打包提交**。

### 阶段 B：验证（跟你无关，但决定你的分）

harness 在一个**全新副本**上：

1. 应用你的 diff
2. 尝试还原受保护的测试文件和 runner 配置（防止你改测试来「通过」）
3. 应用官方的 `test_patch`
4. 从 `test_patch` 推导出要跑的 pytest 目标，运行
5. 检查测试运行**产生了有效的非空结果**

第 5 条很重要：**进程正常退出（exit 0）不算通过**。如果一个测试被跳过、没收集到用例、或者输出为空，即使没有报错也不给分。

---

## 3. 怎么算分

```
Score = (1/N) · Σ r_i     r_i = 1 当且仅当第 i 个任务的验证通过
```

- 隐藏任务约 **120 个**，Public / Private 各占一半；最终名次用 Private 那一半。
- 没有「解释得好」「中间步骤漂亮」「大部分测试通过」的分数。**要么 resolved，要么 0。**
- 举例（原文的算术示例）：60 个任务里修好 9 个 → 0.15。多修好 1 个，分数涨约 0.0167。

### 三个必须分开看的「成功」

| 你观察到的 | 它说明什么 | 是不是得分 |
| --- | --- | --- |
| agent session 结束 | 循环停了（可能超时） | ❌ |
| 提取到非空 patch | 有东西可以送验证 | ❌ |
| 验证通过 | 这个任务 resolved | ✅ |

**只有第三个是目标。** 前两个是「在哪一步把分丢掉的」诊断信息。超时后也可能仍然留下了可验证的 patch，所以运行状态和 resolved 状态要分别记录。

---

## 4. 你的 agent 必须做对的六件事

这是官方建议的 baseline 循环，也是论文里要论证的「方法」：

1. **把 issue 翻译成可验证的行为描述**——「应该发生什么」而不是「看起来哪里不对」。
2. **定位**——找到实现 + 相关测试。搜索 `search_file` / 读文件 / 代码图三选一或组合。
3. **复现**——能跑的话，写一个聚焦的检查让 bug 现形（`normalize_limit(0)` 现在返回 10）。
4. **最小改动**——只改证据支持的那一处。
5. **回归检查**——改完后验证原行为没坏（`None` 仍返回默认值、正常值仍然正常）。
6. **审 diff、清临时文件、提交**。

第 6 步不是形式主义：临时脚本会被 `git add -N` 带进 patch。

---

## 5. 一个具体例子（把整条链路走一遍）

**issue**：「把 limit 显式设为 0 却返回了 10 条；省略 limit 时才该用默认值。」

**初始代码**（`query/limits.py`）：

```python
def normalize_limit(value, default=10):
    return value or default          # 0 和 None 都被当成假值
```

**agent 的轨迹**（示意，不是真实运行记录）：

| 步骤 | 动作 | 观察 |
| --- | --- | --- |
| 1 | `search_file("limit")` | 命中 30 多处，排除文档和测试 |
| 2 | `read_file("query/options.py")` | `return normalize_limit(raw_limit)` |
| 3 | `read_file("query/limits.py")` | 看到 `return value or default` |
| 4 | 跑聚焦检查 | `normalize_limit(0)` → 10，**复现成功** |
| 5 | 编辑 | `return default if value is None else value` |
| 6 | 再跑三个用例 | `0→0`、`None→10`、`5→5` 全过 |
| 7 | 审 diff | 只有一个文件的一行改动 |
| 8 | `submit_patch()` | 提取到非空 diff，交给验证方 |

**验证方**（你看不到）：打上 diff、还原测试文件、应用官方 `test_patch`、跑测试 → resolved。

注意：参考修复可能和你的写法不一样（比如用 `if value is None: return default`），**只要行为对就能过**——这是行为测试，不是逐字比对。

---

## 6. 七个会直接吃掉分数的坑

1. **临时脚本污染 patch**：`git add -N .` 会把仓库里所有新文件都带上。收尾必须清理，否则验证环境里多出一个可能报错的文件。
2. **改测试没用**：验证前会尝试还原受保护的测试文件。而且实测 `swegemma 0.2.7` 的还原逻辑用的是 `git checkout HEAD -- <一长串路径>`，路径里有不存在的文件时整条命令失败且错误被吞掉（Git 2.54 下已改的测试会留在原地）——**别依赖这个 bug**，它不是设计意图，也不代表隐藏评分器的行为。
3. **exit 0 ≠ 通过**：必须产生非空测试结果。写一个「什么都不测」的测试等于 0。
4. **自己验证通过 ≠ 得分**：你的检查是决策依据，不是评分标准。隐藏测试你只能猜它的语义。
5. **改对症状、改错层次**：把特判写进 `routes.py` 能修好 Web 入口，但命令行入口仍然坏（它们共用 `limits.py`）。共享 helper 的改动要看所有调用方。
6. **单个任务吃掉全部时间**：任务顺序执行、总预算 12 小时。一个卡死的任务会挤掉后面所有任务的分。
7. **多采样 + 用参考测试挑最优**：本地实验可以这么干，但比赛里的 agent 没有 oracle，也不在预算内。论文里不能把这种「本地挑出来最好的一版」当成 agent 的期望通过率。

---

## 7. 提交包里有什么

已确认的部分：

- `submission.zip`，解压后 **< 3 GiB**
- **ADK 声明式配置**（`LlmAgent` 类型），不是任意 Python 入口
- 系统提示词文件（示例路径 `agent/prompts/system.md`）
- **注册的工具**（read / search / edit / run / submit_patch 这一类）
- 可选 **LoRA adapter**（不是必须；样例里有多 LoRA 路由的演示，别照抄没有权重的声明）

⚠️ **精确 schema 我没拿到**——官方 `HARNESS_README.md`、`sample_submission/` 和 Kaggle 上的 [Getting Started notebook](https://www.kaggle.com/code/ryanholbrook/getting-started-gemma-4-developer-agent) 是唯一权威来源，而这些页面都是 JS 渲染，抓不到正文。等你 shell 恢复后，第一件事就是解压 `sample_submission/`，把目录树和 `agent/*.yaml` 贴进 `docs/`。

---

## 8. 如果你要参赛，最小路径是这样

按「先便宜、后昂贵」排序，别一上来就开 GPU：

1. **不开模型**：拿 1 个 dev 任务，自己当 agent 手工做一遍。写清楚「现在发生什么 / 应该发生什么 / 用什么观察能区分」。
2. **不开模型**：解压 `snapshots/<id>.tgz`，确认能装依赖、能跑测试。跑一次**不加修改**的仓库 + `test_patch`，确认它是**失败**的（负对照）；再打上参考 `patch`，确认**通过**（正对照）。这两步任一失败，说明环境不对，别怪模型。
3. **开模型**：用官方样例包跑 1 个任务，只回答三个问题——工具调得通吗？diff 能提取吗？各阶段耗时多少？
4. **8–12 个任务**：记录「轮数 / token / 是否非空 diff / 是否 resolved / 耗时」。这是 baseline 表。
5. **只改一个变量**（比如定位工具），在同样任务上重跑——这才是论文里那张对比表。

---

## 9. 这套流程和论文赛道的关系

论文要回答的其实就三个问题，而它们的证据全部来自上面的流程：

| 论文里的章节 | 证据从哪来 |
| --- | --- |
| 方法：我改了什么 | prompt / 工具 / 循环 / adapter 的具体差异 |
| 实验：有没有用 | §8 第 4、5 步的对比表（resolved 率、token、耗时） |
| 分析：为什么有用 | 失败轨迹的分类（定位错 / 编辑错 / 验证错 / 超时） |

也就是说：**主赛道的工程练习不是额外负担，它就是论文的实验部分。** 反过来说，如果你只写论文不碰这条链路，评审很容易看出实验是编的。
