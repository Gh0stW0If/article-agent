# PR5D-1 baseline_v1 验证记录

本文是冻结 baseline_v1 的验收补充，不修改已冻结 prediction、evaluation 或快照文件。

## 运行

- Article：2015-06。
- 工作分支：pr5d1-real-benchmark-2015-06。
- 基础 Git SHA：eefa90ff85935af980c2fedcc2917d4771a94e5e（PR #11 merge）。
- 用户明确授权的变更：Responses 通信适配；全部模型角色请求 gpt-5.6-sol。
- 通信层文件 SHA256：3adee63389441d527f4e558e61b633118ff9ca29e09cd8ff4576356ce7f726f4。
- 生产 source snapshot SHA256：e6f585225789f93bd33816b75c0dfedc27a31d2406fe47d93fee9e87bf5be676。
- 原生产提取算法、提示词、Gold、Registry、evaluator 未修改。tracked working tree 并非 clean；本次不是原始 main 字节完全不变的运行，此差异已写入 RUN_MANIFEST，不隐去。
- 前 5 次技术失败保留；第 6 次为第一次成功完成 production，未因评分低重新抽取。
- 90 个 source/dependency 文件与隔离副本哈希一致。
- PRODUCTION_ISOLATION 的 forbidden_read_attempts=[]；未向模型发送 Gold/标签。

## 冻结哈希

Prediction：
`ebe87d48a43c065f866b136854da65532d90dcf644e74fc2b33a68eb7cf53ffb`

Evaluation：
`4899ebde62cd0d4f4c42ecebdf2e387a82b518bf118f59293a5397f8bb64e73d`

prediction 在首次 evaluator 调用前固定。多次离线评分输出 byte-identical；没有覆盖不同的 evaluation。结果没有最低性能门槛。

## 测试

全部使用 `D:\Application\Anaconda\envs\Agent\python.exe`。

```powershell
python -m pytest tests/test_real_benchmark_2015_06.py tests/test_models.py -q
# 58 passed in 0.75s

python -m pytest -q
# 467 passed in 23.84s
```

新增真实快照测试涵盖：

- FROZEN Gold、ArticleExtraction/2.0、EvaluationReport/2.0.0 validation。
- prediction / evaluation / Gold / registry 与运行 manifest 的 SHA 一致。
- 快照所有已登记文件的 SHA 一致。
- 重新 evaluate 与冻结结果 byte-identical；模型调用入口禁用后仍可运行。
- 五项核心指标、实体指标、failure counts、conflict metrics 与 evaluator 完全一致。
- REVIEW_REQUIRED 两字段排除 ordinary HARD/value accuracy。
- 原始记录保存、Arm/Intervention/sample-flow 未被组装改写。
- 清楚披露 Responses transport exception、全 sol 配置及并非 clean main。
- 快照不含 API key、Authorization token、PDF、Excel 或日志。
- 发布器拒绝覆盖已存在的快照目录。

`git diff --check` 通过。测试未调用真实 API。

## 非阻断的运行诊断

production.stderr.log 保存了 MinerU 子进程输出读取线程的 UTF-8 UnicodeDecodeError。解析产物、Markdown、后续全部提取阶段均已完成，最终 exit_code=0，因此不是本次 production 的终止原因。该 stderr 不能据此当作完整的 parser 原始日志。

原始日志留在本地 `outputs/pr5d1_2015_06_benchmark_retry06/production.stderr.log`，不提交日志，不修解析器。

请求计数按已保存的操作记录报告；缺乏完整 wire-level tracing，未伪造全流程 HTTP 总次数。行 manifest 中原有 run_id=NR 的 provenance 缺口也保留并披露。

## 提交状态

baseline_v1 已生成于本地，可供 review；本次未 commit、push、merge 或启动优化。
