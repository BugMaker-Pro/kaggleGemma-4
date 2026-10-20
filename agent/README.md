# agent/ — 主赛道提交包

这个目录的内容最终会被打成 `submission.zip` 提交（解压后 < 3 GiB）。它**不是**一个普通的 Python 项目：Kaggle 不会执行任意入口脚本，只接受**声明式 agent 配置**，由官方 harness 编译成 agent 再运行。

## 你实际设计的只有四件事

循环、工具实现、沙箱、补丁提取、验证——**全部由官方 harness 提供**，你写不了，也不需要写。能改的只有：

| 旋钮 | 内容 | 影响什么 |
| --- | --- | --- |
| **prompt** | 系统提示词：工作流、纪律、输出格式 | 模型怎么想、何时停、改多大 |
| **工具** | 启用哪些已注册工具、怎么引导使用 | 观察质量（搜索粒度、读窗口） |
| **委派** | 单 agent 还是 subagent 分工 | 探索广度 vs 上下文消耗 |
| **限额** | 轮数、超时、输出 token | 预算分配，单任务 vs 全局 |
| （可选）adapter | LoRA 权重 | 模型行为，需自带权重 |

没有 `while True:` 可以写。你想「加一个门控」「改一下循环」——在提交包里都做不到，只能在 prompt 里表达，或者用 sandboxed skill（⚠️ 待核实是否允许）。

> 这也决定了论文的边界：如果 harness 固定了循环，那么可研究/可改进的空间就是上面四行，不是「设计一个更聪明的 agent 架构」。

## 已确认的规则

| 项 | 值 |
| --- | --- |
| 提交文件 | `submission.zip` |
| 解压后大小 | < 3 GiB |
| 模型 | 固定 `gemma-4-31b-it-qat-w4a16-ct`，不可换 |
| agent 类型 | ADK `LlmAgent` 等受支持类型 |
| 提示词 | 外部文件（样例路径 `agent/prompts/system.md`） |
| 工具 | 必须来自 harness 已注册的工具集，不能自定义 host 侧 Python |
| adapter | 可选 LoRA，需自带权重 |
| 运行环境 | 离线；仓库沙箱 4 GiB RAM / 2 vCPU |

## 目录

```
agent/
├── README.md            # 本文件
├── prompts/
│   └── system.md        # 系统提示词（已写第一版）
├── config.yaml          # ⚠️ 待按 sample_submission 对齐，尚未创建
└── tools/               # ⚠️ 工具声明，取决于 harness schema
```

## ⚠️ 必须先用 `sample_submission/` 校准的部分

我目前**没有拿到**提交包的精确 schema（官方 `HARNESS_README.md`、`sample_submission/` 和 Kaggle Getting Started notebook 都是 JS 渲染页面，抓取工具读不到正文）。以下字段名只能等真包确认，不要凭想象写：

- [ ] 顶层配置文件名（`config.yaml` / `agent.yaml` / `submission.yaml`？）
- [ ] agent 的类型声明字段（`type: LlmAgent`？`agent_class`？）
- [ ] prompt 路径怎么写（相对包根？带 `agent/` 前缀？）
- [ ] 工具注册的写法（列名字？带参数 schema？）
- [ ] 模型引用的写法（别名？checkpoint 全名？）
- [ ] adapter 声明字段（不写 adapter 时该字段是省略还是置空）
- [ ] 限额字段（最大轮数、单任务超时、最大输出 token）在哪一层配置
- [ ] 是否有 `requirements.txt` 式的依赖声明，还是只能用 wheelhouse

**校准方法**：解压 `sample_submission/`，把目录树和每个 YAML/MD 文件原样贴进本文件下方「样例原文」小节，再逐个字段改写。

## 工具清单（按官方文档描述推断，名称以实际注册为准）

| 用途 | 典型工具 | 备注 |
| --- | --- | --- |
| 搜索 | `search_file` / 文本搜索 | 先搜后读 |
| 读文件 | `read_file(filepath, start_line, end_line)` | 上限 150 行 / 10,000 字符 |
| 编辑 | `edit_file` / 字符串替换 | 必须精确匹配 |
| 执行 | `run_command` | 输出截断 5,000 字符，沙箱无网络 |
| 提交 | `submit_patch()` | 内部执行 `git add -N . && git diff --binary` |
| 代码图 | `get_code_neighbors` / `get_code_subgraph` | 公开数据里 129 个图为空 |
| 相似代码 | `search_similar_code` | 查询的是**已索引符号**，不是自然语言 issue |

后两个工具的坑见 [../docs/competition.md](../docs/competition.md) §4.1。

## 打包检查清单

提交前逐项确认：

- [ ] 解压后总大小 < 3 GiB（`du -sh` 或资源管理器看解压后体积）
- [ ] 没有把 base model 权重打进去
- [ ] 没有把 `snapshots/`、`wheels/`、数据文件打进去
- [ ] 没有 `.git`、`__pycache__`、`.venv`、日志
- [ ] prompt 文件路径与实际引用一致
- [ ] 配置里没有引用不存在的 adapter
- [ ] 在本地用同一个 zip 跑通过至少 1 个任务

## 样例原文

<!-- 解压 sample_submission/ 后，把目录树和每个文件的原文贴在这里 -->

```
（待填）
```
