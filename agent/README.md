# agent/ — 主赛道准备与评测

已取得官方运行说明、样例和 129 个公开任务。2026-11-08 用户确认已加入比赛；下载链路已修复并实际成功。完整计划见 [main-track-plan](../docs/competition/competition.md#main-track-plan)，执行状态见 [main-track-status](../docs/competition/competition.md#main-track-status)。

## 官方运行合约

来源：本地 `.cache/main-track/official/HARNESS_README.md` 和官方 `ryanholbrook/getting-started-gemma-4-developer-agent` v3。

- ZIP 根目录放 `agent.yaml`；可选 `eval_config.yaml`、提示词、子 agent、skill 与 adapter。
- 顶层只能使用声明式 agent 配置，不能放任意 Python agent 入口；允许沙箱中的 ADK skill 脚本。
- 每包统一使用一种获准模型：`gemma-4-31b-it-qat-w4a16-ct`、`gemma-4-12b-it-qat-w4a16-ct`、`gemma-4-e4b-it-qat-w4a16-ct` 或 `gemma-4-e2b-it-qat-w4a16-ct`。旧记录中“只能用 31B”已经过时。
- 包解压后小于 3 GiB；单 skill 目录上限 50 MiB；文件扩展名受限。32,768 是上下文上限，不能当作额外可用输入预算。
- `run_command`、`read_file`、`edit_file`、`write_file`、`get_status`、`submit_patch`、`get_code_neighbors`、`search_similar_code`、`get_code_subgraph` 是官方注册工具。
- `search_similar_code` 主要以已有符号查询向量邻居；多词输入存在词法回退，不能等同于实时 issue 编码器。
- 主赛道截止：北京时间 2026-12-03 07:59；每日最多提交 1 次。

## 当前三个包

运行 `tools/build_main_track.py` 生成三个根目录正确、配置匹配的包及私有 Kaggle 流程测试 Notebook。

| 包 | 定位指令 |
| --- | --- |
| baseline | 官方根提示词 |
| evidence | 替换官方定位段为显式证据优先和候选保留策略 |
| evidence_graph | evidence 加按需一跳图查询 |

所有包统一为 12B、无 adapter、单 agent，采样和预算相同（3 分钟、30 次工具调用、最多 50 轮、单命令 60 秒）。官方样例的 dummy LoRA 和 AgentTool 委派从全部实验臂中移除。因此 baseline 是 **匹配配置上的官方提示词基线**，并非未经修改的官方样例成绩。非定位流程保持一致。

`prompts/system.md` 是早期草稿，不作为这三个包的共用主提示词；构建器从下载的官方提示词生成。`prompts/localization/` 是两种实验策略的来源。

## 可重复命令

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/fetch_main_track.ps1 -IncludeSample
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/fetch_main_track.ps1 -Files tasks.jsonl
.venv/Scripts/python.exe tools/build_main_track.py --out .cache/main-track/build-v2 --run-suffix v2
.venv/Scripts/python.exe -m unittest tests.test_main_track -v
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/run_main_track_notebook.ps1 -Action Status -BuildDirectory .cache/main-track/build-v2
```

`Launch` 会创建私有 Notebook 并消耗 Kaggle GPU 配额，最多一小时；`Status`/`Logs` 只读取状态或日志。脚本拒绝覆盖同名 Notebook。比赛提交是独立步骤，这里没有自动提交榜单的代码。

## 当前验证边界

已完成任务划分、配置控制、Notebook 代码语法和 ZIP 根目录检查；官方 `validate_directory` 与真实修复在 Kaggle 运行时执行。首次云端运行因默认 Python 3.13 与官方 cp312 wheels 不匹配而在安装阶段失败。第二次使用官方固定镜像，状态见执行记录。一个开发任务的流程测试不能证明方法提升 resolved rate。

## ??????

- `tools/audit_main_track.py` ????????????????????????????????
- `--completion-guardrails` ??????????? `prompts/completion.md`?????????????????
- `--engineering-task-id` ????????????????????
- Notebook ????? `append_task_result` ??????????????????
- Requests ????????? src ?????????????????????????Rich ????????????????? Requests ???????????????????????????

`--max-output-tokens 8192` ???????????????????????????????????`--src-layout-repair` ????? subprocess ???????? ZIP?????????????

批量入口为 `tools/build_main_track_batch.py`，只允许冻结开发集 ID，默认并发 2。模型运行前要求每个任务在相同环境中满足参考补丁通过、空补丁失败；运行后用 `tools/audit_main_track.py --batch-dir <目录>` 验证完整任务×配置矩阵、实际包、补丁和评分输出。
