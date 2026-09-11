# 2015-06 Gold DRAFT — 人工审阅包

状态：DRAFT。尚未批准为 FROZEN，不运行真实 Agent benchmark。

## 来源与审阅范围

主来源为本地 `-2015-06.pdf`，逐页审阅 1–7 页，并视觉核对第 4 页 Table 1/2。Excel `2015-6篇.xlsx` 仅用于交叉核对。SHA256 见 gold.json source_lineage；不提交二进制。

## REVIEW_REQUIRED 队列

所有条目当前 value=null；不会纳入普通 HARD 分母。

### Study 2015-06-S1.centre_count

Methods gives one recruiting hospital; Acknowledgements names two hospitals where the study was finished. Centre definition requires review; no explicit contradictory centre counts.
- E0011: PDF p.5: We thank Second Hospital Affiliated Jiaxing University and Sir Runrun Hospital of Zhejiang University where the study was finished.
- E0012: PDF p.2: which was performed in the Department of Rehabilitation Medicine, Affiliated Second Hospital of Jiaxing University

### Study 2015-06-S1.participant_blinding

Source says single blind and describes a mock device to facilitate blinding, but does not explicitly identify the blinded party.
- E0015: PDF p.3: To facilitate blinding, a mock EA therapeutic instrument, emitted a sound and a blinking light, was attached to the needles

### Study 2015-06-S1.practitioner_blinding

Source says single blind and describes a mock device to facilitate blinding, but does not explicitly identify the blinded party.
- E0016: PDF p.3: To facilitate blinding, a mock EA therapeutic instrument, emitted a sound and a blinking light, was attached to the needles

### Study 2015-06-S1.outcome_assessor_blinding

Source says single blind and describes a mock device to facilitate blinding, but does not explicitly identify the blinded party.
- E0017: PDF p.3: To facilitate blinding, a mock EA therapeutic instrument, emitted a sound and a blinking light, was attached to the needles

### Study 2015-06-S1.statistician_blinding

Source says single blind and describes a mock device to facilitate blinding, but does not explicitly identify the blinded party.
- E0018: PDF p.3: To facilitate blinding, a mock EA therapeutic instrument, emitted a sound and a blinking light, was attached to the needles

### Intervention 2015-06-S1-I02.total_sessions

Legacy workbook gives 90 from once/day × 3 months; months have variable length and no explicit 90 sessions are printed.
- E0058: PDF p.2: These treatments lasted for 3 months.

### Intervention 2015-06-S1-I03.total_sessions

Sham total treatment count is not reported; do not inherit 90 from EA/legacy workbook.
- E0069: PDF p.2: These treatments lasted for 3 months.

### ArmResult 2015-06-S1-AR01.timepoint

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0088: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR01.timepoint_value

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0089: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR01.timepoint_unit

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0090: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR01.denominator

Percentages imply 35/34/38 but explicit outcome denominators are not given; Methods allocation conflicts with Table 1. No denominator inferred from percentages.
- E0093: PDF p.4: 21 (60.0)

### ArmResult 2015-06-S1-AR02.timepoint

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0095: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR02.timepoint_value

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0096: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR02.timepoint_unit

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0097: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR02.denominator

Percentages imply 35/34/38 but explicit outcome denominators are not given; Methods allocation conflicts with Table 1. No denominator inferred from percentages.
- E0100: PDF p.4: 29 (85.29)

### ArmResult 2015-06-S1-AR03.timepoint

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0102: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR03.timepoint_value

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0103: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR03.timepoint_unit

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0104: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ArmResult 2015-06-S1-AR03.denominator

Percentages imply 35/34/38 but explicit outcome denominators are not given; Methods allocation conflicts with Table 1. No denominator inferred from percentages.
- E0107: PDF p.4: 23 (60.5)

### ComparisonResult 2015-06-S1-CR01.timepoint

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0111: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR01.timepoint_value

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0112: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR01.timepoint_unit

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0113: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR02.timepoint

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0117: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR02.timepoint_value

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0118: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR02.timepoint_unit

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0119: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR03.timepoint

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0123: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR03.timepoint_value

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0124: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

### ComparisonResult 2015-06-S1-CR03.timepoint_unit

Table 2 gives no timepoint; Results mentions the 1st month in a sentence also naming voided volume. Scope of the time qualifier is ambiguous; no inheritance from adjacent rows.
- E0125: PDF p.4: there were no significant differences between group 1 and 3 in number of bladder balance patients and voided volume (ml) at the 1st month

## 额外人工审阅项目

- 已保留 Table 1 的 3 个 baseline residual urine ArmResults；不新建 Outcome。请确认 baseline inclusion policy。
- Bladder balance 定义见 Outcome O01.legacy_fields.definition：低压充分排尿、残余尿约100 ml或以下、无感染。
- A02/A03 randomized_n 各保留 Methods/Table 1 两候选，不依据百分比裁决。
- Sham frequency 未明确单独报告，不复制 EA once/day。CIC 固定频次不适用，不能与 CIC frequency 结局混淆。
- P-only ComparisonResults 的 effect_measure、estimate、CI 统一 NOT_REPORTED；不计算 effect size。统计检验放 legacy_fields。
- 随机序列 code=2 是标准化编码、非原文数字；allocation concealment 的 NR code 不当作 PRESENT 数字。

## Legacy workbook reconciliation

| Workbook item | Gold interpretation | Reason |
|---|---|---|
| Sheet1 rows 10–11 的两条比较记录 | 一个 Article、三臂、三项明确比较 | 不是两篇文章；编号不进入 Gold truth |
| total_sessions=90 | REVIEW_REQUIRED | once/day × 3 months 不等于原文报告90次 |
| centre_count=1 | REVIEW_REQUIRED | Acknowledgements另提第二家医院 |
| Group2/3 n=34/38 | SOURCE_CONFLICT | Methods写38/34，Table1写34/38 |
| analyzed n 复制随机人数、dropout=0 | NOT_REPORTED | 原文未明确对应 flow counts |
| Bladder balance 主要/患者重要结局 | role NOT_REPORTED | 不等于试验声明 primary outcome |
| 通讯邮箱、年份、电脑随机、once/day、3 months | PDF核对后保留 | workbook不是独立事实证据 |
| journal全称 | 保留PDF缩写 Int J Clin Exp Med | 未用外部检索扩写 |

## 解释限制

NOT_REPORTED coverage_complete 仅指已审阅提供的完整论文及合理章节，不代表检索过所有外部注册/补充文件。
Self-consistency PASS 只证明与冻结 schema/evaluator 结构兼容，不证明人工标注正确。
