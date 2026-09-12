# PR5G-1 — Missingness Resolution

只改变独立 canonical projection 的缺失状态，不做 extraction、identity matching
或 evaluator 修改。生产接口：

```python
resolve_missingness(prediction, coverage=None)
# -> MissingnessProjection(prediction, decisions, coverage_proofs)
```

## 决策顺序

保护现有 PRESENT / SOURCE_CONFLICT 和未解释的原始来源之后：

1. 字段语义是否不适用？有来源支持的 mean/SD 结果使用 `n` 作为样本量；
   `event_count` 和 `denominator` 是事件计数/事件分母，不是均值样本量。
2. 字段适用时，是否具有完整、非 targeted 的 field-scope coverage authority，
   并逐一完成来源审查，且无阳性、冲突或未决来源？
3. 无法证明上述条件则保持 UNRESOLVED。

当前只涉及 Arm 的 received/analyzed/dropout，Outcome.role，
ArmResult 的 event_count/denominator/n，ComparisonResult.estimate。
字段家族固定，实体 ID/文章 ID/Gold expected statuses 不进入规则。
不填补值，不修复 Result identity，也不扩大到其他字段。

`n` 永远不因为结果是 mean 而变 NA。count/proportion/percentage/rate/other、
无 reciprocal evidence 的 mean、不完整 mean/SD 和混合事件来源均不授权 mean 规则。
原始 SOURCE_CONFLICT 仍保留；resolver 的 `resolution_status=UNRESOLVED`
不表示把冲突 candidates 删掉或改写成普通缺失。

## 复用 Absence Authority，而非另建 Harness

`coverage.py` 是既有 `ABSENCE_COVERAGE_CERTIFICATE/1.1.0` 的只读、保守
Python consumer，沿用这些本地机制的规则：

- `ts-agent/src/harness/absence/field-scope-source-universe.ts`
- `ts-agent/src/harness/absence/field-scope-completeness.ts`
- `harness/architecture/a2a/nr-authority-binding-contract.json`

这些本地 TS/Harness 文件不是 PR5G-1 新依赖，不需要纳入本 PR。
没有新 scope derivation、证书生成器、source retrieval、模型判断或 authority 版本。

`CoverageContext` 接收已经由可信 source pipeline 产生的 document-map binding、
certificate、source universe、owning scope policy，以及逐 source unit 的
`ABSENT|POSITIVE|CONFLICT|UNRESOLVED` review。receipt 自身的 COMPLETE 标签不足以
授权：还要检查内容哈希、document/field/skill/scope 绑定、所有 modality 的完整
unit 集合和 coverage diff、无 parser/budget/external gap、非 targeted 和
Gold-independent provenance、完整 field review。

哈希用于完整性核验，不是签名或对审查真实性的证明；调用者仍需可信 source
producer 的证据。不能根据 model miss、Gold、partial table context 自制 authority。
包含 exclusions 或外部来源但缺少可绑定审查的 receipt 会保守拒绝；
不实现另一套 exclusion/外部文档判定机制。

现有 authority policy 主要覆盖旧字段体系，本 PR **不新增或重映射** field scope
registry。canonical 字段没有精确的 owning policy/receipt 时默认 UNRESOLVED。
单元测试里的完整 receipt 为合成 source 场景，不是本篇文章的覆盖证明。
缺少线上 receipt 的本批次会得到 **0 NR promotions**，这是正确的 fail-closed 行为。

每个 NR proof 保存原 receipt、逐来源审查、哈希和最终状态。
NR coverage proof 是 authority/provenance，不伪装为阳性 Evidence。
NA 使用已有 canonical derived Evidence，链接原有统计类型/数值证据。
原始 source 字段和所有既有 evidence 均保留。

## 离线验收

```powershell
D:\Application\Anaconda\envs\Agent\python.exe scripts/pr5g1_missingness_acceptance.py
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q tests/test_missingness_resolution.py tests/test_missingness_acceptance.py
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q
```

CLI 先逐字节复现 PR5F-2，随后在禁用网络的上下文内进行两次完整 replay。
全部 9 个文件必须 byte-identical，才允许 `--snapshot` 保存新版本。
不覆盖不同内容的旧快照。

生产输入仅冻结 PR5F-2 prediction；**没有覆盖凭据**。
输出投影之后才读取 Gold 事后评分；复用原有 evaluator、identity links、
历史 semantic cache。保护文件哈希必须不变。

本次：HARD 73/271 → 97/271，status 99/595 → 123/595；
24 个 NA unresolved → 0；34 个 NR unresolved → 34。
Coverage 74/165、supported value accuracy 73/74、ArmResult 12/21、
ComparisonResult 10/18、Outcome 3/4、identity-unresolved HARD 105 均不变。

`MISSINGNESS_UNRESOLVED.json` 的 34 项按当前 HARD 口径；
`MISSINGNESS_DECISIONS.json` 按 source field families 记录全部生产判定，
包含未匹配且不计分的 source entities。二者不是同一分母。

PR5G2 handoff 仅包含已匹配且 Gold=PRESENT 但缺少结构化值的 34 个 HARD
字段；不混入 NR/NA、identity-unresolved 或 PARTIAL。这是事后诊断，绝不
作为本 PR resolver 的输入。

## 本 PR 验证记录

- 新增 Missingness tests：41 passed（38 generic + 3 real acceptance）。
- 含 PR5F-2、PR5F-1 identity、hybrid/evaluator/domain 的 focused suite：
  **365 passed in 13.38 s**。
- Agent 环境完整 pytest：**691 passed in 34.97 s**，无 skips/xfails/warnings。
- 全部 9 个离线输出在两次独立 replay 中逐字节一致。
- 受保护的 Gold、Registry、raw prediction、extraction/semantic prompts、
  semantic cache、source surface、identity mappings 哈希不变。
- 真实 conflict detection/candidate set 仍为 2/2；模型 API calls = 0。
