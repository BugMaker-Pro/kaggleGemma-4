# 完整排序器接入

源目录 `agent/ranker/` 保存技能说明与推理脚本；权重由构建器生成到打包目录，不直接堆在源代码目录。

## 已实现

`issue + 当前仓库源码 → AST 图 → metadata BM25 前 200 候选 → 16 项特征 → BGE dense 分数 → 三个训练种子的排序树平均 → 前十符号与行号`。

- `localization_features.py` 为无标签特征计算，仅接受 issue、源码与图，不读取 patch/test_patch。
- `tree_predict.py` 直接执行 LightGBM 导出的数值树，免除沙箱内的 LightGBM 安装。实际模型输出与原库差异约 3.6e-15。
- `dense_encoder.py` 支持原始 FP32 CPU 检查点和按行 INT8 压缩权重。整数 position_ids 缓冲区保持原值，其余未量化偏置和 scale 使用 FP32。
- `localize.py` 在当前修复前源码上重建候选，排除依赖目录、符号链接和 `.adk_exec_*` 运行文件，不修改仓库。full 模式失败会明确返回错误，不暗中回退为词法排名。

## 与论文的区别

部署模型使用 2,189 条历史任务训练，排除了比赛涉及的 fastapi、httpx、requests、rich 全部仓库。论文是 2,232 任务的两折仓库评估；部署训练策略不能直接继承论文 44.7% 成绩。

原始 BGE 权重约 127 MiB，超过单 skill 50 MiB 限制。部署采用 INT8 权重压缩及无损压缩树文件；完整 skill 41,346,203 字节（约 39.4 MiB），ZIP 约 31.5 MiB。ADK 加载器仅加载文本资源，因此编码权重保存在文本载体中，运行时还原；没有绕过 50 MiB 校验。

一个历史 Requests 快照核对了 3,200 项特征值。原始 FP32 与压缩编码器的前十排序在该样本上完全一致，平均 dense 分数差约 0.00119，最大差 0.0037；这不代表全数据量化无损。历史并列候选存在顺序差异，独立列出而非宣称逐字复现原离线排名。

## 已完成的官方通道验证

私有 Kaggle 离线 CPU Notebook 已通过官方 `RunSkillScriptTool` 和 `AdkSandboxCodeExecutor` 执行完整技能：requests_7433 的 200 个候选完成评分，首位为 src.requests.models.PreparedRequest.prepare_body；工具成功且仓库没有改变。耗时约 80.6 秒，计入 agent 总时间时是显著开销。

该结果只证明官方技能接口在本地 subprocess 后端可运行。技能需要 numpy、torch、transformers、tokenizers；官方竞赛 Docker 是否具备这些依赖仍未验证，正式参赛包不能仅凭这个本地结果宣称运行环境兼容。额外编码器是否适用于最终提交还需以官方最终技术规则为准。

## 构建与验证

```powershell
.venv/Scripts/python.exe tools/build_ranker_skill.py --out .cache/main-track/ranker-package-new
.venv/Scripts/python.exe tools/verify_ranker_local.py --package .cache/main-track/ranker-package-new
.venv/Scripts/python.exe tools/package_ranker_agent.py --staged --package .cache/main-track/ranker-package-new --out artifacts/ranker-agent-new
.venv/Scripts/python.exe -m unittest tests.test_ranker_skill -v
```

打包要求输入目录含 local-integration.json，先完成原编码器/压缩编码器与原特征的对照后再打包；现有固定构建的记录已保留。`tools/build_ranker_probe.py` 构建官方技能通道 CPU 测试，`tools/build_ranker_agent_probe.py` 构建相同预算下证据基线与真实 ranker 调用的 agent 对照。

当前 ZIP 与私有数据集回执在 `artifacts/ranker-agent-v1/`。第一轮 GPU 试跑已经完成：两组修复均通过，但 ranker 组没有调用技能，因此接入审计为 false，不能把修复成功归因于排序器。完整结果保留在 `experiments/runs/main-track-ranker-agent-20261108-v1/`。

修正版通过 `tools/build_ranker_agent_probe.py --staged --ranker-only` 构建：SequentialAgent 先执行仅有技能工具的定位阶段，再由相同 Gemma 模型读取定位报告并修复。两个阶段共享同一总预算；原始权重与推理脚本不变。新一轮必须通过实际工具调用、完整原始问题、full 输出和补丁验证的独立核对，不能仅凭工作流配置宣称接入完成。

第二轮真实接入现已通过：`run_skill_script` 成功执行 full 排序，200 个候选中 prepare_body 排名第一；修复阶段随后提交只含源码的补丁，337 个测试通过。原始问题仅发生 CRLF/LF 与一个末尾换行差异，字节级不相同的事实保留在审计中。固定结果在 `experiments/runs/main-track-ranker-agent-20261108-v2/`，对应分阶段包在 `artifacts/ranker-agent-v2/`。该单任务不证明效果提升，冻结的 10 任务开发评测正在另行执行。
