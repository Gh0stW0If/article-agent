# 2015-06 Gold DRAFT — 人工审阅包

状态：DRAFT。尚未批准为 FROZEN，不运行真实 Agent benchmark。

## 来源与审阅范围

主来源为本地 `-2015-06.pdf`，逐页审阅 1–7 页，并视觉核对第 4 页 Table 1/2。Excel `2015-6篇.xlsx` 仅用于交叉核对。SHA256 见 gold.json source_lineage；不提交二进制。

## REVIEW_REQUIRED 队列

所有条目当前 value=null；不会纳入普通 HARD 分母。

### Study 2015-06-S1.centre_count

Methods gives one recruiting hospital; Acknowledgements names two hospitals where the study was finished. Centre definition requires review; no explicit contradictory centre counts.
- E0012: PDF p.5: We thank Second Hospital Affiliated Jiaxing University and Sir Runrun Hospital of Zhejiang University where the study was finished.
- E0013: PDF p.2: which was performed in the Department of Rehabilitation Medicine, Affiliated Second Hospital of Jiaxing University

### Study 2015-06-S1.participant_blinding

Source says single blind and describes a mock device to facilitate blinding, but does not explicitly identify the blinded party.
- E0016: PDF p.3: To facilitate blinding, a mock EA therapeutic instrument, emitted a sound and a blinking light, was attached to the needles

## 已接受的人工审核决策

- Baseline inclusion：accepted policy。保留 Table 1 的 3 个 baseline residual urine ArmResults，并关联已有 Outcome；不再作为待裁决项。
- participant_blinding 保持 REVIEW_REQUIRED；practitioner / outcome assessor / statistician blinding 改为 NOT_REPORTED，各自建立完整 MissingnessAssessment，不从 single blind 推断角色。
- I02/I03.total_sessions 改为 NOT_REPORTED；不由频次和月数计算 Gold 总次数。Workbook 数值仅留在下方 reconciliation note。
- Bladder balance 的 3 个 ArmResult 和 3 个 ComparisonResult，其 timepoint / timepoint_value / timepoint_unit 共 18 个字段均为 NOT_REPORTED，逐字段建立 MissingnessAssessment；不从 Results 句子推断 1 month。
- Study.countries 保留 Chinese patients 来源，并补充 PDF 第 5 页通讯地址 Second Hospital, Jiaxing University, Jiaxing 314000, China 的直接证据。

## Denominator 最终人工裁决与 derivation policy

- 已接受 deterministic derived：三个 bladder balance ArmResult.denominator 均为 PRESENT，并从待审队列移除。
- A01：21 / 0.600 = 35；raw_value 保留 "21 (60.0)"。
- A02：29 / 0.8529 ≈ 34；raw_value 保留 "29 (85.29)"。
- A03：23 / 0.605 ≈ 38；raw_value 保留 "23 (60.5)"。
- 仅使用当前 Table 2 单元格的事件数和百分比：相除后取最近整数，并核对该整数计算出的百分比在原表精度下与印刷值一致。百分比已舍入，因此 A02/A03 使用近似符号。每个字段链接独立的 support_type=derived evidence，保存完整推导、页码、表格、行及组别单元格坐标。
- derived outcome denominator does not adjudicate randomized_n SOURCE_CONFLICT. 不按人数求和、Methods/Table 1 或组别角色消解 A02/A03 randomized_n 的来源冲突。

## 待人工决定

- 最终 REVIEW_REQUIRED 仅剩 2 项：centre_count 和 participant_blinding；value=null。Gold 暂仍保持 DRAFT。

## 保留的解释与限制

- Bladder balance 定义见 Outcome O01.legacy_fields.definition：低压充分排尿、残余尿约100 ml或以下、无感染。
- A02/A03 randomized_n 各保留 Methods/Table 1 两候选，不依据百分比裁决。
- Sham frequency 未明确单独报告，不复制 EA once/day。CIC 固定频次不适用，不能与 CIC frequency 结局混淆。
- P-only ComparisonResults 的 effect_measure、estimate、CI 统一 NOT_REPORTED；不计算 effect size。统计检验放 legacy_fields。
- 随机序列 code=2 是标准化编码、非原文数字；allocation concealment 的 NR code 不当作 PRESENT 数字。

## Legacy workbook reconciliation

| Workbook item | Gold interpretation | Reason |
|---|---|---|
| Sheet1 rows 10–11 的两条比较记录 | 一个 Article、三臂、三项明确比较 | 不是两篇文章；编号不进入 Gold truth |
| total_sessions=90 | I02/I03 NOT_REPORTED，value=null | Workbook 90 仅留在本 reconciliation note；once/day × 3 months 不等于原文报告总次数，不进入 Gold value |
| centre_count=1 | REVIEW_REQUIRED | Acknowledgements另提第二家医院 |
| Group2/3 n=34/38 | SOURCE_CONFLICT | Methods写38/34，Table1写34/38 |
| analyzed n 复制随机人数、dropout=0 | NOT_REPORTED | 原文未明确对应 flow counts |
| Bladder balance 主要/患者重要结局 | role NOT_REPORTED | 不等于试验声明 primary outcome |
| 通讯邮箱、年份、电脑随机、once/day、3 months | PDF核对后保留 | workbook不是独立事实证据 |
| journal全称 | 保留PDF缩写 Int J Clin Exp Med | 未用外部检索扩写 |

## 解释限制

NOT_REPORTED coverage_complete 仅指已审阅提供的完整论文及合理章节，不代表检索过所有外部注册/补充文件。
Self-consistency PASS 只证明与冻结 schema/evaluator 结构兼容，不证明人工标注正确。
