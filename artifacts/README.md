# 本地历史产物

- `archive/legacy-workspace-20261108.zip`：85 个旧诊断文件、试跑输出、补丁草稿、日志和预览图。归档保留原相对路径，所有文件在移除散文件前均逐项核对 SHA256。
- 同名 `.manifest.json`：文件大小、SHA256、原修改时间，以及两份完全相同文件的对应关系。归档内部也有 `ARCHIVE_MANIFEST.json`。
- `releases/`：原根目录的项目 ZIP 和 Git bundle，内容不变。

查看旧文件时可将 ZIP 解压到独立目录，内部仍使用原来的 data/、tmp/、paper/ 等路径：

```powershell
.venv/Scripts/python.exe -m zipfile -e artifacts/archive/legacy-workspace-20261108.zip .cache/archive-preview
```

两份去重文件可从同内容文件恢复：

| 原路径 | 保留的同内容文件 |
| --- | --- |
| data/body_ablation_full.jsonl | data/body_ablation.jsonl |
| tmp/dense_scores_repro.jsonl | data/dense_scores.jsonl |

原 tmp/review/graph-controls-uncached 已移至 experiments/runs/graph-controls-uncached-20261101，三份原始文件完整保留。当前工作文件仍在各自目录中；artifacts 只收纳历史产物，不存放运行依赖。
