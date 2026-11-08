# 代码反馈实验记录

合并流程准备、首轮 API 试跑和不重叠任务扩样。原始回执、异常、成本及数据仍在 experiments/runs/。

- [feedback-pilot](#feedback-pilot)
- [deepseek-feedback-results](#deepseek-feedback-results)
- [flash-replication](#flash-replication)

<a id="feedback-pilot"></a>
## 单轮代码反馈实验：输入协议与 API 执行记录

日期：2026-11-02。

更新：已通过独立 DeepSeek Flash API 适配器完成真实试跑，见[结果、费用和异常披露](feedback.md#deepseek-feedback-results)。下文保留输入包及本地模型方案的准备记录；本地模型仍未配置，真实结果来自 API。

已经实现配对输入、模型版本冻结、本地查询生成、共同检索以及独立金标评分流程。12 条任务的 24 份真实输入已经保存；尚未运行真实生成模型，尚无反馈策略的效果结果。当前 manifest 明确标为 paired_inputs_awaiting_generator，model 为 null，formal_run_frozen 为 false。

本轮继续使用此前 12 条历史开发任务，不新增按失败筛选的样本。问题只限于：读取原查询结果中的代码，是否比只看 issue 的预规划查询改善定位？显式证据状态的贡献不在本轮范围内。

## 两组共同设置

| 项目 | 预规划组 | 代码反馈组 |
| --- | --- | --- |
| 模型可见 issue | 同一原文，最多 6,000 字符 | 同一原文，最多 6,000 字符 |
| 首轮结果可见性 | 不提供候选名、路径或代码 | 原查询前五个候选的代码窗口 |
| 模型调用 | 一次、独立请求 | 一次、独立请求 |
| 生成输出 | 严格 JSON，两条不同的查询 | 同一格式 |
| 查询长度 | 每条最多 1,000 字符 | 同一上限 |
| 检索调用 | 原查询 + 两条生成查询 | 同一上限 |
| 最终候选与排序 | RRF 常数 60，200 候选，前十诊断 | 同一规则 |

两组使用同一份提示指令，差异在输入 JSON 中是否包含首轮代码。反馈组每个候选最多 60 行、1,200 字符，总计最多 6,000 字符，保存文件、行号、字符区间和文本 hash。允许模块节点，与父实验候选范围一致。不会根据金标或已知成功案例选择展示窗口。

实际输入检查：24 份请求顺序和 hash 校验通过；12 个 issue 均未达到字符截断上限；预规划组代码暴露量为 0，反馈组总计 62,309 字符，单任务最多 6,000。准备输入时读取整个修复前快照并与父实验内容 hash 比对，完整源码读取量与预处理耗时另外记账，不把模型看到的字符数当作全部 IO。

## 预算与失败处理

每组拟定输入 token 上限 8,192，输出上限 256，合计上限 8,448。绑定具体 tokenizer 后逐条计数，在模型运行前冻结实际输入长度。超限时拒绝开始本轮，不在运行中悄悄截断代码。

模型 greedy 生成，不采样、不重试。JSON 格式错误、查询重复、查询超长或模型运行错误时，保留失败原因，回退到原查询排名。失败任务进入同一评分分母；不只报告成功生成的任务。运行错误导致无法取得输出 token 数时保留 null，并单独计数，不能当作零开销。

两组共享资源上限，但输入长度与实际成本不同；记录各组输入输出 token、调用次数和代码暴露量，不声称实际等成本。查询评分文档次数上限 300,000；每条查询最多返回 200。最终使用相同 RRF，未接入最强学习融合排序器。

没有硬墙钟超时；耗时仅记录。源码读取上限在读入后检查，不能称为硬 IO 限制。父数据或快照不一致、索引无法复现、文件损坏等完整性问题会中止本次执行，不删除失败任务后输出完整成绩；需要修复后使用新目录重跑。

## 流程与来源隔离

1. prepare-inputs：仅使用清洗后的四字段任务输入、父检索轨迹与修复前快照，生成两组请求。
2. freeze：校验本地生成模型和 tokenizer，保存模型所有相关文件的 SHA256、依赖版本、生成配置及实际输入 token 数，创建独立运行目录。
3. generate：只读取冻结的配对请求，用本地模型产生两条查询；不读取金标。
4. retrieve：按同一索引执行生成查询，核对原查询排名可精确复现，保存生成查询的返回及共同融合结果。
5. evaluate：核对响应与请求的对应、预算、执行查询、候选去重和融合，再独立读取 gold 评分。

在线阶段拒绝包含补丁、测试答案或 gold 的任务字段。推理不运行 issue 或代码中的命令，仅生成检索字符串。各阶段产物以独占创建方式写入，拒绝覆盖历史结果。

## 评估规则

主要比较是反馈组减去预规划组的任务宏平均 symbol recall@10；候选覆盖为次要指标。目标不在索引时仍计入分母，缺失金标和无符号任务单独记录。按仓库重采样，输出描述性 95% 区间（2,000 次，种子 20261102）。继续投入参考效应为 +2 个百分点；不自动扩样，也不根据新结果回改阈值。

小样本、历史开发使用以及前两轮结果均需披露。即使反馈组取得收益，也只支持普通反馈价值，不能证明显式证据状态有效。模型尚未确定，因此本输入包不能被称为完整冻结的模型实验。

## 已完成验证

- 新增 11 项针对性测试，全部测试合计 136 项通过。
- 测试覆盖预规划组不见代码、代码窗口字符定位、输入上限、严格 JSON、响应来源、token 预算、原查询回退以及合成检索评分链路。
- 使用离线随机初始化的微型 CPU 模型，验证本地权重加载、chat template、生成与 token 记账接口通过。该模型仅供接口检查，已清理临时权重；未用于真实任务，不产生研究成绩。
- 输入包与父实验源码、输入和轨迹的 fingerprint 校验通过。

## 当前模型缺口

工作区已有 bge-reranker-v2-m3、bge-small-en-v1.5 和 jina-code，配置显示分别为序列分类、编码器和 masked language model；本 runner 会拒绝将它们作为因果生成模型。当前没有配置可用于本轮的本地生成模型。

现有 runner 支持本地 Hugging Face 因果语言模型目录，要求包含权重、tokenizer 和 chat template；使用 local_files_only 与 trust_remote_code=False，不自动下载权重或执行模型仓库自定义代码。若改用远程推理服务，需要另行实现与冻结服务适配器及模型版本，不能把外部生成文本直接填进当前真实实验产物。

## 文件与运行入口

- [实验模块](../../experiments/feedback_pilot.py)、[分阶段 CLI](../../tools/run_feedback_pilot.py)、[针对性测试](../../tests/test_feedback_pilot.py)、[随机模型接口检查](../../tools/smoke_feedback_model.py)。
- [输入 manifest](../../experiments/runs/feedback-inputs-20261102-v1/manifest.json)、[24 份请求](../../experiments/runs/feedback-inputs-20261102-v1/requests.jsonl)、[代码来源窗口](../../experiments/runs/feedback-inputs-20261102-v1/contexts.jsonl)。

已执行的输入准备：

    .venv/Scripts/python.exe tools/run_feedback_pilot.py prepare-inputs --out experiments/runs/feedback-inputs-20261102-v1

指定真实本地模型后执行（下面的模型目录仅为占位符，尚未执行）：

    .venv/Scripts/python.exe tools/run_feedback_pilot.py freeze --bundle experiments/runs/feedback-inputs-20261102-v1 --model-dir PATH_TO_LOCAL_CHAT_MODEL --out experiments/runs/feedback-model-20261102-v1
    .venv/Scripts/python.exe tools/run_feedback_pilot.py generate --bundle experiments/runs/feedback-inputs-20261102-v1 --model-dir PATH_TO_LOCAL_CHAT_MODEL --run-dir experiments/runs/feedback-model-20261102-v1
    .venv/Scripts/python.exe tools/run_feedback_pilot.py retrieve --bundle experiments/runs/feedback-inputs-20261102-v1 --run-dir experiments/runs/feedback-model-20261102-v1
    .venv/Scripts/python.exe tools/run_feedback_pilot.py evaluate --bundle experiments/runs/feedback-inputs-20261102-v1 --run-dir experiments/runs/feedback-model-20261102-v1

测试命令：

    .venv/Scripts/python.exe -m unittest discover -s tests
    .venv/Scripts/python.exe tools/smoke_feedback_model.py

---

<a id="deepseek-feedback-results"></a>
## DeepSeek Flash 单轮反馈探测结果（2026-11-02）

已完成 24 次请求：23 次正常返回，1 次网络或响应解析异常，未重发。两组使用 deepseek-flash、关闭思考、temperature=0、JSON 输出、每次最多 256 输出 token。服务端返回模型名为 deepseek-flash，23 条响应的 system_fingerprint 一致：bc19ba97cbe016479903222bb1578db6。该 API 别名不是不可变 checkpoint，不能声称完整冻结了服务端权重。

结论：存在值得进一步核验的正向信号，但只有一条完整配对任务的前十召回改善。不能把含异常回退的总增益都解释为模型利用代码的收益，也不据此确认显式证据状态有效。

## 主要结果与异常敏感性

| 分析范围 | 只看 issue：候选覆盖 / recall@10 | 看 issue 和首轮代码：候选覆盖 / recall@10 |
| --- | --- | --- |
| 全部 12 条，含一次原查询回退 | 91.67% / 37.50% | 100.00% / 54.17% |
| 剔除异常任务后的 11 个完整配对 | 90.91% / 40.91% | 100.00% / 50.00% |

全部任务的主要差值为 +16.67 个百分点，仓库 bootstrap 描述性区间 [0.00, 41.67] 点。完整配对的差值为 +9.09 点，描述性区间 [0.00, 27.27] 点。两者区间均包含零，且跨过 +2 点继续投入参考门槛；小样本和历史开发使用的限制仍存在。

完整配对中只有 django__django-15996 的 recall@10 从 0 提高到 1，其余十条均不变，没有完整配对任务退步。反馈查询提到了 django db migrations serializer EnumSerializer IntFlag 等实现线索，但预规划查询也已经包含 EnumSerializer；不能仅据查询措辞断言模型发现了此前完全未知的符号。

反馈组还补齐 pytest-dev__pytest-5413 和 sympy__sympy-14024 的候选目标覆盖，两条任务的 recall@10 仍为 0。这些是候选生成层面的收益，不是最终前十定位收益。也没有下游修复成功率测量。

## 异常与协议偏差

第 12 次调用（psf__requests-2148 的反馈组）发生 transport/JSON error。客户端没有得到可解析响应，服务端是否完成、是否计费未知，输入输出 token 保留 null，不能用零代替。没有重发这次请求。

原 API 协议规定此类错误停止。停止后追加独立 continuation.json：异常请求使用原查询回退，只继续尚未发送的 12 次请求，总预算仍为 5 元。该续跑决定在查看检索成绩之前作出，属于需要披露的运行偏差。续跑适配器曾在处理 null 费用时出现两次本地汇总错误，均已修正并保留 continuation-v1.json、continuation-v2.json；第一次未发出新增请求，第二次在所有请求和检索完成后，仅影响费用汇总，没有重发或修改查询。

异常任务恰好原查询 recall@10 为 1，预规划查询融合后为 0，因此回退人为贡献了全体结果中的 +8.33 点。主结果保留它，另报完整配对敏感性，不把该部分计为反馈模型改善。完整配对分析属于事后敏感性，不替代原全任务分析。

## 费用与用量

23 个正常响应已知输入 37,470 token，输出 887 token。按本轮记录的空闲时段人民币单价并考虑 API 返回的缓存命中，估算为 **¥0.03399336，约 3.4 分钱**。这是由 usage 推算的费用，不是账户账单核验。

异常请求账单未知。已知请求按高峰价格计算，加异常请求的保守规划预留，共 ¥0.09184872，约 9.2 分钱；该数是预算预留估计，不是精确最终费用。初始整轮规划预留为 ¥0.380344，预算上限 ¥5。

| 已知用量 | 预规划组 | 反馈组 |
| --- | --- | --- |
| 输入 token | 8,078 | 29,392，另有一次未知 |
| 输出 token | 445 | 442，另有一次未知 |
| 模型请求 | 12 | 12，其中一次结果未知 |
| 检索调用（各臂计入原查询） | 36 | 34，异常任务只用原查询 |
| 提供给模型的代码字符 | 0 | 62,309 |

两组具有相同资源上限，但反馈组消耗更多实际输入 token，不声称实际等成本。缓存会影响账单，本轮未随机化两组发送顺序。每任务均先预规划后反馈，且服务端别名可能更新，这些也限制了精确复现主张。

由于未使用服务端一致的本地 tokenizer，API 输入 token 只能由 provider usage 事后核验；全部收到响应的请求均在原 8,192 输入上限内。发送前费用守卫使用 UTF-8 字节数加消息开销作保守规划估计，不将其称为准确 token 计数或绝对硬费用保证。此差异已在运行前 API manifest 中记录。

## 产物与验证

- [API 原冻结配置](../../experiments/runs/deepseek-flash-feedback-20261102-v1/manifest.json)、[续跑配置](../../experiments/runs/deepseek-flash-feedback-20261102-v1/continuation.json)。
- [生成响应与用量](../../experiments/runs/deepseek-flash-feedback-20261102-v1/responses.jsonl)、[检索结果](../../experiments/runs/deepseek-flash-feedback-20261102-v1/retrieval.jsonl)、[逐任务分数](../../experiments/runs/deepseek-flash-feedback-20261102-v1/scores.jsonl)。
- [全任务汇总](../../experiments/runs/deepseek-flash-feedback-20261102-v1/summary.json)、[完整配对敏感性与审计](../../experiments/runs/deepseek-flash-feedback-20261102-v1/sensitivity.json)。
- [API 适配器](../../tools/run_deepseek_feedback.py)、[续跑适配器](../../tools/continue_deepseek_feedback.py)、[独立审计脚本](../../tools/audit_deepseek_feedback.py)。

旧输入包、固定菜单和轮转实验源码 hash 保持一致。检索时重建同一修复前快照索引并验证原查询排名，独立评分核验执行查询、候选预算与融合。全部 146 项测试通过。密钥只从本机 .env 读取；.env/.ENV 已被 Git 忽略且未跟踪，运行产物扫描确认不含密钥。没有把认证头写入日志。

不要直接重新运行 generate 来重复购买请求；已有完整响应文件会拒绝再次调用。该目录中的 receipts 保存原始 provider 响应、调用开始标记和安全错误记录，没有认证信息。后续方法或参数变更需要新的配置及目录。

## 后续判断

这轮支持继续研究“普通代码反馈”，但不足以直接训练或宣称显式证据状态控制器有效。下一次优先设计更大、仓库分层且与这 12 条不重叠的探索样本，并在结果前冻结样本、预算和比较；旧 Lite 仍有历史开发使用，不称为独立确认集。应先稳定传输与失败处理，再扩样，避免回退策略混入模型效果。

### 后续扩样更新

[35 条不重叠任务的独立分层扩样](feedback.md#flash-replication)已完成：70 次请求全部正常，反馈 recall@10 相对预规划为 −1.43 点，2 条改善、2 条退步。首轮正向差值没有在扩样中重复出现；当前不进入多轮反馈或显式证据状态控制器训练。首轮记录与异常敏感性保持原样。

---

<a id="flash-replication"></a>
## Flash 分层扩样：冻结协议与结果（2026-11-02）

这是[首轮 Flash 探测](feedback.md#deepseek-feedback-results)之后的独立运行，样本与首轮 12 条不重叠。任务仍来自已用于历史开发的 SWE-bench Lite，不是全新确认集。样本选择、失败规则、API 配置、主要比较和继续投入门槛在本轮生成查询与评分前冻结。

## 样本与问题

每仓库最多选 3 条，排除首轮全部任务 ID，再按 SHA256(seed, instance_id) 排序取前几条；种子为 2026110202。共 35 条：11 个仓库各 3 条，Flask 剩余只有 2 条，全部纳入。抽样不使用补丁、gold、历史命中或本轮得分。公开基准可能出现在服务端模型训练材料中，本轮无法排除训练污染。

核心问题仍是：相同资源上限下，给模型看首轮代码，是否比只看 issue 生成查询改善前十符号召回？本轮不测试显式证据状态控制器，不训练模型，不测修复成功率。

两组使用同一模型别名 deepseek-flash、关闭思考、temperature=0、JSON 输出、每次最多 256 输出 token。每任务 2 次调用，共最多 70 次；各组一次生成两条查询。反馈组读取原查询前五个候选的代码窗口，最多 6,000 字符，预规划组不读取代码或候选信息。issue、窗口、最终 200 候选与 RRF 规则沿用首轮。

## 预先修订的失败处理

首轮一次单边回退制造了额外的表面收益。本轮采用配对回退：同一任务只要任一组未成功生成合规查询，两组都使用原查询排名。保留两组真实响应与用量，明确区分生成结果与用于检索的有效查询。这会让基础设施失败任务的两组差值为零，而不是单边得到原查询的偶然优势。

完整主分析保留可评分的全部选中任务；另按预先规定报告两组均成功的完整配对敏感性。两组中只有一组生成失败的原始输出仍保存，不能假称两次生成均失败。

请求顺序在任务内部由固定哈希决定，允许任一组先发，避免始终预规划先发。顺序是确定可复现的，不强求各组先发次数完全相等；缓存优惠单独影响费用，不能当作能力差异。

每请求仅发送一次、60 秒网络超时；网络/JSON 解析异常记为未知完成和未知计费，不重试，只继续未发送请求。连续三次异常停止；HTTP 错误停止。发现已有开始标记却既无响应也无错误记录时，拒绝自动重发。模型返回格式不合规也不修补、不追加调用。

快照、源码、请求、候选或评分完整性错误会停止，不能删除问题任务后发布完整样本结果。输入与检索按任务检查点保存，可恢复纯本地计算；最终汇总文件拒绝覆盖。

## 费用与预算

首轮按高峰价格加未知请求预留共 0.09184872 元，本轮从合计 5 元预算中扣除此预留，剩余上限为 4.90815128 元。所有输入准备完后还需在任何 API 请求之前封存请求 hash、执行顺序与整轮费用规划预留；预留超限则不发送。

费用规划使用消息 UTF-8 字节数加固定开销，并按高峰、未命中缓存单价估计，是保守规划量，不是精确 tokenizer 保证。收到响应后按 provider usage 检查输入 8,192 token、输出 256 token 和总计 8,448 token 上限。未知用量保留 null，不当成零。服务端模型别名与指纹逐次记录，别名不等于不可变权重版本。

输入已封存：70 份请求，整轮规划预留 1.117374 元，与首轮相加为 1.20922272 元。35 个 issue 均未触发字符截断，反馈组共暴露 189,907 字符代码；预规划先发 18 条任务，反馈先发 17 条。

## 分析规则

主要指标：所有可评分任务的宏平均 symbol recall@10，反馈组减预规划组，采用配对回退。主要效应的描述性 95% 区间按仓库进行 5,000 次 bootstrap（种子 2026110202），抽中仓库后保留该仓库全部任务。多个任务来自同一仓库，不能当作完全独立样本。

继续投入参考门槛为 +2 个百分点：区间下界达到门槛才支持继续进入下一阶段探索；上界低于门槛则当前协议未显示值得投入的收益；其余记为不确定。不自动扩样、不事后更换主要比较。该门槛是资源投入规则，不是预期提升或显著性门槛。

次要结果包括候选覆盖、原查询基线、完整配对敏感性、分仓库结果，以及正确目标的新增与丢失。未索引目标仍计入金标分母，缺失金标与无可评分符号的任务单列。不用文件级命中替代符号命中，也不把候选覆盖提高称为前十定位改善。

## 实施与审计

[扩样 runner](../../tools/run_flash_replication.py)复用已测试的纯输入、检索、API 计费与评分组件；旧实验源码及产物保持原样。新文件包含独立的抽样、请求顺序、成对回退和仓库聚类统计。新增[9 项测试](../../tests/test_flash_replication.py)，全部测试合计 155 项通过；含合成快照的全流程检查：金标文件在生成与检索时不存在，制造一次网络失败后确认两组对称回退，响应不会重试，密钥和补丁不会进入输出。

产物目录：[冻结 manifest](../../experiments/runs/flash-replication-20261102-v1/manifest.json)、[四字段任务输入](../../experiments/runs/flash-replication-20261102-v1/tasks.jsonl)。输入封存、响应、检索和评分结果在对应阶段完成后追加，尚未生成的文件不视为结果。

复现入口（新运行需使用不存在的目录；已完成 API 请求拒绝重复购买）：

    .venv/Scripts/python.exe tools/run_flash_replication.py prepare --run-dir experiments/runs/flash-replication-20261102-v1
    .venv/Scripts/python.exe tools/run_flash_replication.py inputs --run-dir experiments/runs/flash-replication-20261102-v1
    .venv/Scripts/python.exe tools/run_flash_replication.py generate --run-dir experiments/runs/flash-replication-20261102-v1
    .venv/Scripts/python.exe tools/run_flash_replication.py retrieve --run-dir experiments/runs/flash-replication-20261102-v1
    .venv/Scripts/python.exe tools/run_flash_replication.py evaluate --run-dir experiments/runs/flash-replication-20261102-v1

## 运行结果

35 条全部完成且可评分；70 次 API 请求全部正常返回，零重试、零格式失败、零配对回退。正常响应指纹均为 bc19ba97cbe016479903222bb1578db6，与首轮记录一致。API 请求实际发生于北京时间 2026-11-02 23:53:17 至 23:54:28；目录日期是这份冻结协议的版本标识。

| 策略 | 候选目标覆盖 | Symbol recall@10 |
| --- | --- | --- |
| 原始 issue 查询 | 83.33% | 36.67% |
| 只看 issue，预规划两条查询 | 95.71% | 56.67% |
| 看 issue 与首轮代码，生成两条查询 | 94.29% | 55.24% |

主要差值为 **−1.43 个百分点**；仓库聚类 bootstrap 描述性 95% 区间为 **[−12.12, +8.33] 点**。区间跨过零和事先的 +2 点门槛，按冻结规则判断为 **不确定**。没有复现首轮的总体正向差值，但也不能证明代码反馈普遍无效。两组均成功，所以完整配对敏感性与主分析完全相同，本轮的差异不来自异常回退。

### 改善与退步来自哪里

35 条中 2 条前十召回改善、2 条退步、31 条不变：

| 任务 | 预规划 recall@10 | 反馈 recall@10 | 对应目标最终名次 |
| --- | --- | --- | --- |
| astropy-7746 | 0.00 | 0.50 | _return_list_of_arrays：11 → 7；另一目标仍未入前十 |
| requests-2674 | 0.00 | 1.00 | HTTPAdapter.send：12 → 8 |
| matplotlib-18869 | 1.00 | 0.00 | matplotlib.__getattr__：10 → 18 |
| flask-5063 | 1.00 | 0.00 | routes_command：3 → 32 |

改善量为 +0.5、+1，退步量为 −1、−1，净和 −0.5，除以 35 即 −1.43 点。不能只按“2 胜 2 负”认为完全抵消，也不能只选改善的任务展示。

候选覆盖另有两条变化：django-10924 从 1.0 降为 0.0，pytest-5103 从 0.5 升为 1.0；二者前十召回均不变。Django 的反馈查询偏向 deconstruct、makemigrations，目标 FilePathField.formfield 则从预规划的第 21 名变为不在最终 200 候选。Flask 的反馈查询引入 create_url_adapter 等首轮代码内容，目标 CLI 函数退到第 32 名。这些案例提示初始结果可能把搜索带到相关但非目标的路径，是诊断线索，不是已识别的因果机制；本轮不据此改写提示再追分。

两组生成查询在全部 35 个任务中都不完全相同。反馈查询有 27 条任务包含“代码中出现而 issue 中未出现”的词法 token；只看 issue 的预规划查询也有 16 条满足同一条件。词法重合不能证明确实利用了代码，更不能替代检索效果。该统计只作描述性诊断。

### 实际用量与费用

| 项目 | 预规划组 | 反馈组 |
| --- | --- | --- |
| 输入 token | 22,135 | 94,848 |
| 输出 token | 1,246 | 1,396 |
| 模型调用 | 35 | 35 |
| 检索调用（含各组的原查询） | 105 | 105 |
| 代码暴露字符 | 0 | 189,907 |

总输入 116,983 token、输出 2,642 token。按响应中缓存用量及冻结单价估算，空闲时段费用 **¥0.10597532，约 0.11 元**；高峰价格估算为 ¥0.21195064。两轮已知请求的空闲费用合计约 ¥0.13996868，首轮另一次异常请求账单未知。把首轮未知请求预留与两轮已知请求都按高峰计，合计 ¥0.30379936，低于 5 元预算；这些均为用量推算或预留，不是账户账单核验。

反馈组消耗的实际输入 token 约为预规划的 4.28 倍，本轮没有对应的总体定位收益。相同上限没有带来实际等成本，资源记录不能省略。

### 审计与后续取舍

独立[审计脚本](../../tools/audit_flash_replication.py)重算了 140 个分臂指标，验证全部任务与首轮不重叠、原始响应与执行查询一致、候选融合和预算正确、主分析与仓库区间一致；运行产物未发现 API 密钥。全部 **155 项测试通过**。

审计材料：[输入封存](../../experiments/runs/flash-replication-20261102-v1/inputs.seal.json)、[生成响应](../../experiments/runs/flash-replication-20261102-v1/responses.jsonl)、[逐任务评分](../../experiments/runs/flash-replication-20261102-v1/scores.jsonl)、[汇总及分仓库结果](../../experiments/runs/flash-replication-20261102-v1/summary.json)、[独立审计](../../experiments/runs/flash-replication-20261102-v1/audit.json)。逐任务检索和 provider 收据保存在同目录 retrieval_tasks/、receipts/ 下。

**本轮不进入多轮反馈或显式证据状态控制器训练。**首轮少量任务的正向差值在这批不重叠任务上没有重复出现，不能把首轮当作稳定收益。当前更适合保留只看 issue 的查询生成作为简化的探索性基线；两种生成方案相对原始查询的提升属于本轮描述性观察，尚未验证最强学习融合排序器上的增量。

没有自动新增样本、调参或再次购买调用。后续如果继续研究，先另立协议检验初始代码相关性与强排序底座，而不是从这四个胜负案例中定向挑规则；不能把本轮“不确定”写成显著有效、等价或普遍无效。


### 强排序器后续诊断

2026-11-03 已复用本轮只看 issue 的生成查询完成[最强融合排序器增量验证](query-generation.md#strong-query)。相对原正文池前十召回增加 9.52 点，4 条改善、零条退步；区间下界为零，且三条改善的目标已存在于 metadata 池，尚未排除普通候选融合解释。这是新协议下的探索性诊断，不修改上述反馈组与预规划组的比较；没有新 API 调用。
