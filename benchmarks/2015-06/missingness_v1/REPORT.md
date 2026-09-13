# PR5G-1 — Missingness Resolution

范围：仅缺失状态投影；无新增提取、无 API、无 identity 修复。Gold 仅用于事后评分。

## 状态含义

- NOT_APPLICABLE：当前结果语义不适用该字段。mean/SD 的样本量用 n；event_count/denominator 是事件语义。
- NOT_REPORTED：字段适用，已有完整且可核验的来源覆盖证明，逐来源审查无阳性/冲突/未决信息。
- UNRESOLVED：证据不足，不等于文章没有报告。不能把模型未抽到视为 NR。

## Before → after

| 指标 | Before | After |
|---|---:|---:|
| hybrid_hard_acceptable | 73/271 | 97/271 |
| hybrid_status_accuracy | 99/595 | 123/595 |
| hybrid_production_coverage | 74/165 | 74/165 |
| hybrid_supported_value_accuracy | 73/74 | 73/74 |
| HARD NOT_REPORTED unresolved | 34 | 34 |
| HARD NOT_APPLICABLE unresolved | 24 | 0 |
| HARD missingness total | 58 | 34 |
| ArmResult | 12/21 | 12/21 |
| ComparisonResult | 10/18 | 10/18 |
| Outcome | 3/4 | 3/4 |

## 决策与来源

NA 状态变化 24；NR 状态变化 0。
24 个 NA 依据已保存的 mean/SD 字段及 reciprocal evidence；没有按 Gold 或文章 ID 选择对象。
34 个 HARD NR 候选保留 UNRESOLVED：冻结生产产物未提供绑定这些字段的完整 scope certificate + field review。
现有表格片段、成功 extraction 或 surface context 均不等于全文/字段范围的完整覆盖。
COVERAGE_PROOFS.json 同时记录失败的覆盖检查；coverage_sufficient=false 不授权 NR。
生产 resolver 按字段家族遍历 source graph，而不是接收 58 个 Gold targets。未匹配 source 也记录判定，但不创建匹配关系、不计入这 58 项的分母；all_source_unresolved_decisions 与 HARD backlog 不同口径。
原始字段保存在独立投影的 legacy_fields.missingness.raw_fields；原始 evidence 和所有 PRESENT 值不变。
既有 SOURCE_CONFLICT 保留候选及 evidence；resolver 的未决结论不抹掉原始冲突。

## 审计与交接

RUN_MANIFEST.json 保存受保护输入哈希；语义 cache、Gold、Registry、prompt、identity links 全部原样复用。
PR5G2_EXTRACTION_INPUT.json 只含 34 个已匹配、Gold=PRESENT、缺少结构化值的 HARD 字段，不含 NR/NA、未匹配实体、timepoint PARTIAL。它是事后评估诊断，不进入本 PR 生产 resolver。
105 个 identity-unresolved HARD 与 1 个 timepoint PARTIAL 不变。
完整 CLI 在禁止网络的上下文中复现基线、运行两次、逐字节对比全部 9 个输出文件。

## 尚未解决

- 34 HARD NR candidates lack bound complete field-scope coverage/review receipts.
- 105 identity-unresolved HARD, 34 PRESENT-field misses and one timepoint PARTIAL remain out of scope.

本 PR 的性能变化来自 missingness-state reasoning 的改善，即正确区分 NOT_REPORTED、NOT_APPLICABLE 和 UNRESOLVED；不代表提取到了新的 PDF 内容，也不代表 numerical extraction 能力提高。
