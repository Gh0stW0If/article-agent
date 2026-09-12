# 2015-06：为什么运行成功，HARD exact 仍只有 2.21%？

这是第一次成功完成的 PR5D-1 生产提取，使用用户授权的全 gpt-5.6-sol + Responses 配置。以下为冻结 prediction 后的只读分析，不是新 matching 规则，不修改 prediction、Gold 或 evaluator。

## 两分钟结论

三臂及两处样本量来源冲突识别成功，但“认识了哪个结局/比较”没有满足冻结 evaluator 的身份条件。4 个 Gold Outcome 和 3 个 Gold Comparison 均未匹配，导致下游结果不能进入正常数值比较。

- HARD exact：6/271，2.21%。
- Production coverage：6/165，3.64%。
- Supported value accuracy：6/6，100%。这个分母只有 6，不能解释为结局数值全对。
- 548 个字段是未匹配实体的级联损失，不是 548 个独立的数值提取错误。
- 3 个 Arm 均匹配；A02/A03 randomized_n 均保留 {34, 38}，冲突检测和候选集合都为 2/2。

## 1. Outcome identity：首先阻断结果匹配

| 预测 Outcome | 名称 | instrument | Gold 对应临床项目的 instrument |
| --- | --- | --- | --- |
| O01 | Bladder balance patients | UNRESOLVED | NOT_APPLICABLE |
| O02 | CIC frequency | UNRESOLVED | NOT_APPLICABLE |
| O03 | Residual urine volume | UNRESOLVED | NOT_REPORTED |
| O04 | Voided volume | UNRESOLVED | NOT_REPORTED |
| O05 | Rate of bladder balance patients | UNRESOLVED | NOT_APPLICABLE |

PR5B 的 `entity_matcher.field_key()` 将字段状态纳入 identity。Outcome 匹配先要求 instrument key 一致，再核对名称/已有 Gold alias。因此即使 CIC frequency 等名称完全相同，UNRESOLVED 也不能与 Gold 的明确缺失状态匹配。

表格的 “Bladder balance patients” 与正文的 “Rate of bladder balance patients” 生成了两个实体。它们是同一临床主题下计数/比例表达的疑似拆分；正式 evaluator 仍记录 MISSING/EXTRA，而非 SPLIT，因为 instrument 阶段没有产生候选边。这里不自动合并，也不追认新 Gold alias。

Residual urine volume 和 Voided volume 各自跨 1/3 月仍共享同一预测 Outcome，没有因为随访时间创建新实体。基线 residual urine 不在结果中：Table 1 被生产路由整体判为 baseline 并跳过，而 Gold 的已接受政策包含 3 个基线 ArmResult。

## 2. Comparison identity：参与组正确不等于完整身份正确

预测确实包含以下三个 source-explicit participant mappings：

| Comparison | arm_ids | relation | contrast |
| --- | --- | --- | --- |
| C01 | A01, A02 | UNRESOLVED | SOURCE_CONFLICT |
| C02 | A01, A03 | UNRESOLVED | PRESENT “Group 1 vs Group 3” |
| C03 | A02, A03 | UNRESOLVED | SOURCE_CONFLICT |

Gold 的 relation 均为 PRESENT “between-group”。C01/C03 的 contrast candidate 分别是 `Group 1 vs Group 2` 与 `group 1 vs. group 2`、`Group 2 vs Group 3` 与 `group 2 vs. group 3`。大小写/句点形式不同被现有字段合并逻辑保留为冲突，没有被人工消解。

PR5B Comparison identity 同时要求有序参与组、relation 和 contrast 的 key 一致；所以 3 个 Comparison 均未匹配。12 个 prediction ComparisonResult 随之出现 COMPARATOR_SCOPE_UNRESOLVED。这不等同于 12 次独立的组别推断错误。

数量为 3 本身不能证明 C(3,2) 自动展开。source records 已包含明确 `Group 1 vs Group 2` 等关系，组装调用的是已有 PR4 canonicalizer，没有新增 all-pairs 逻辑。未根据 Gold 回填缺失的 P1/P2/P3 语义。

## 3. Intervention 名称形式造成两项未匹配

I01 为 `clean intermittent catheterization (CIC)`，I02 为 `electroacupuncture (EA)`；Gold 的规范名未带括号缩写。现有严格名称/alias matching 没有匹配这两项；I03 sham acupuncture 匹配成功。

结构层面仍为 3 个 Intervention，CIC 实体由 3 个 Arm 共享，未创建独立 behavioral intervention。未匹配不是“完全没抽到治疗”。

## 4. 数值已经出现，但来源语义仍有缺口

- 原始结局 source records：14 条，表格 8 条 + Results 正文 6 条；全部保存在 prediction 的 production_source_bundle 中。
- Table 2 的 7 个已选 row_id、正文的 6 个已选 row_id 均有覆盖记录。但这只表示已处理/已确认，不表示所有临床结果都正确提取。
- Table 2 的 column_map 为空。CIC frequency source[1] 的三个 arm_label 为 `NR (arm column 1/2/3)`；均值/SD 已出现，但无法唯一绑定冻结 Arm，因此没有生成对应 3 个 ArmResult。不能根据列顺序猜回去。
- 预测为 15 ArmResult，Gold 为 21。生产中未形成基线 residual urine 的 3 个 ArmResult，也未形成 CIC frequency 的 3 个 ArmResult；正式 evaluator 则因上游 Outcome 未匹配，将全部 Gold ArmResult 归为 missing。
- Bladder balance source[0] 将 21/29/23 放在 `arm.n`，value/event_count 尚空；denominator 也未据 Gold 补入。这是字段语义投影问题，不能用行覆盖率证明正确。
- source[2] 同时含多个明确比较和一串行级 P 值。PR4 对未安全分配的行级统计保留 warning，不将同一 P 自动复制给所有比较。
- 预测时间点仍出现 `1st month`、`3rd month`、`3d month`，analysis_set 常为 UNRESOLVED。即使上游身份得到解决，这些也可能构成后续匹配条件差异；本次不做“假如修改后”的重新计分。

## 5. 匹配实体上的字段问题

正式计数：32 NOT_EXTRACTED、4 VALUE_WRONG；4 个 VALUE_WRONG 都是 SOFT 字段。

| 字段 | 本次观测 | 解读 |
| --- | --- | --- |
| Article.authors | 只保留 first_author Xu-Dong Gu，Gold 有 11 位作者 | 作者列表覆盖不足 |
| Study.condition | Spinal cord injury-induced urinary retention / urinary retention after spinal cord injury | 冻结字符串比较不接受此表述差异，不据此单独断言临床含义错误 |
| I03.kind | sham acupuncture / non-penetrating sham acupuncture | 规范描述细节不同 |
| I03.description | 两段不同描述 | 严格字符串比较判错；不是独立医学语义审查 |

DOI、journal、country、若干随机化/盲法/缺失处理字段未提取；不少字段是 Gold NOT_REPORTED、prediction UNRESOLVED。不能将未抽到的 NR 事后改为 NOT_REPORTED。

## 运行与评分边界

- 解析后端：mineru:pipeline，7 页原文；parser auto 保持不变。
- Topology：2 次请求，首个标签/alias 证据校验失败，第二次通过；ArmDetails 首次通过。
- 结局阶段 manifest：12 个记录操作，10 success、2 failed（整表/正文整块超时）；随后 9 个行级 fallback 覆盖所选行。原失败文件保留。
- 后处理：14/14 条记录处理成功，两个分片；VLM 结果已生成。
- 缺乏完整 wire-level tracing，不能从这些文件声称全流程 HTTP 请求精确总数；各阶段实际可观测计数在 PRODUCTION_AUDIT.json。
- 请求行 manifest 的 run_id 原样为 NR，文章 manifest 标识 retry06。此 provenance 缺口记录在审计中，未倒填修改原文件。
- 90 个 source/dependency 文件与隔离副本哈希一致；提取 forbidden_read_attempts=[]，Gold/标签未进入生产输入。
- Evidence grounding 17/17 仅为已评价字段的结构引用闭环，不是 PDF 语义复核。
- Gold 中 centre_count、participant_blinding 的 REVIEW_REQUIRED 不进入 ordinary HARD denominator。
- prediction 在任何 evaluator 调用前冻结；重复离线 evaluate 输出 byte-identical。

## Top 5 瓶颈（只识别，不实施优化）

1. Outcome identity 的 instrument 状态与名称语义。
2. Comparison identity 的 relation 缺失及 contrast 文字形式冲突。
3. Intervention 规范名称与 source 名称的身份对接。
4. ArmResult 来源覆盖/Arm 绑定；区分原始缺失与上游匹配级联损失。
5. ComparisonResult 的统计归属和上游 Comparison/Outcome 依赖。

正式 field/entity failure taxonomy 不变。无明确证据要求修改 Gold；Possible Gold Issues: None。
