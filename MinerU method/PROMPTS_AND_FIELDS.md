# MinerU Method：提示词与字段对照（可编辑稿）

> 用途：集中审阅和修改当前 `MinerU method` 在论文抽取、CONSORT 图像抽取和 LLM 质量评价中使用的全部提示词。
>
> 状态：四段式提示词已同步到 `mineru_method/prompts.py`、`mineru_method/llm.py`、`mineru_method/pipeline.py` 和 `evaluate_2015_01.py`，并于 2026-08-25 在 2015-01 上完成测试。Pydantic 字段结构仍以 `mineru_method/schemas.py` 为准。

## 1. 实际调用结构

每个文本抽取请求由三部分组成：

1. 通用 System Prompt；
2. 模块专用 `instruction`；
3. 程序动态加入的 Pydantic JSON Schema、章节上下文和校验失败反馈。

当前程序的 User Prompt 结构如下：

```json
{
  "module": "{{module_name}}",
  "instruction": "{{模块专用提示词}}",
  "schema": "{{Pydantic model_json_schema() 动态生成}}",
  "validation_feedback": "{{上一次 Pydantic 校验错误；首次为空}}",
  "context": "{{章节路由后的 Markdown 文本}}"
}
```

建议同步到程序的统一四段式结构如下：

```json
{
  "role_definition": "你是一名医学 RCT 论文信息提取专家……",
  "task_description": "{{本模块任务、证据规则和禁止事项}}",
  "field_definitions": "{{字段含义、类型、枚举及字段间边界}}",
  "json_template": "{{完整输出 JSON 骨架}}",
  "validation_feedback": "{{上一次校验错误；首次为空}}",
  "source_context": "{{章节路由后的 Markdown 或图像}}"
}
```

可替换变量：

| 变量 | 含义 | 来源 |
|---|---|---|
| `{{module_name}}` | `metadata`、`acupuncture`、`risk_of_bias` 或 `outcomes` | 程序 |
| `{{模块专用提示词}}` | 第 3～6 节中的 instruction | 可修改 |
| `{{Pydantic schema}}` | 字段、类型、必填规则、枚举和 `extra=forbid` | `schemas.py` |
| `{{validation_feedback}}` | 上一次响应的 Pydantic 错误或传输错误 | 程序 |
| `{{context}}` | 路由到该模块的论文内容 | `routing.py` |

---

## 2. 通用文本抽取 System Prompt

对应模块：元数据、针灸参数、偏倚风险、统计结局。

当前原文：

```text
You extract data from randomized clinical trial articles.
Use only the supplied context. Never infer an unreported value. Use exact enum codes from the JSON schema.
Every non-NR substantive value must be supported by a short verbatim quote in evidence.
Keep outcomes separated by instrument, timepoint, arm and estimand. Return one JSON object only.
```

优化后的角色定义：

```text
你是一名医学 RCT 论文信息提取专家，熟悉临床试验方法学、CONSORT、STRICTA、
偏倚风险评价、医学统计学和循证医学数据编码。

你必须严格依据提供的论文上下文进行结构化提取：
1. 不使用外部知识补全文中未报告的信息；
2. 不把推测、常规做法或人工金标准当作论文证据；
3. 严格区分原文值、标准化值和推导值；
4. 严格使用字段界定与枚举编码；
5. 每个非 NR/null 的实质性结果必须提供可逐字核验的短证据；
6. 仅输出符合指定模板的一个 JSON 对象，不输出解释性正文。
```

修改位置：`MinerU method/mineru_method/llm.py` 中的 `SYSTEM`。

### 2.1 推导与猜测的边界

允许推导，但不允许猜测。运行时统一采用以下判定：

```text
只有同时满足以下条件才允许填写推导值：
1. 推导所需的全部输入都在论文上下文中有直接证据；
2. 使用的公式、单位换算或字段映射是预先定义的；
3. 从输入到输出只有一个合理结果；
4. 结果可以由审阅者复算；
5. evidence.support_type="derived"，并在 evidence.derivation 中记录公式或映射。

以下情况属于猜测，必须返回 null/NR：
- 缺少任一输入；
- 存在两种或以上合理解释；
- 依赖临床常识、行业惯例或“通常如此”；
- 依据人工金标准反推论文值；
- 根据文章没有提及某事而反推其发生或未发生。
```

示例：

| 情形 | 判定 | 理由 |
|---|---|---|
| Methods 明确 `T1=10 weeks`，表格写 `T0–T1` | 允许推导为10周 | 跨章节映射唯一，可记录 `T1 → 10 weeks` |
| 表头明确 ITT 为 `Acupuncture n=80, Sham n=82` | 允许填80/82 | 分析集和组别均明确 |
| 82人分组，明确治疗前退出2人 | 允许推导 received=80 | `82-2=80`，前提完整且唯一 |
| 9次、每周1次 → 总疗程9周 | 仅在项目预先规定 `sessions/frequency` 归一化公式后允许 | 否则“首末次间隔8周”与“9个治疗周”口径不唯一 |
| 单次治疗20分钟 → 留针20分钟 | 禁止 | session duration 不等于 needle retention |
| 假针组未画治疗前退出 → received=82 | 禁止仅凭缺失推断 | 需要正文明确值或预先定义的流程图完备性规则 |

---

## 3. 元数据 / 基本特征提示词

### 3.1 输入范围

路由内容：标题、Abstract、Introduction 及未被明确分入其他章节的文章开头信息。

### 3.2 当前 instruction

```text
Extract Sheet1 bibliographic/basic characteristics.
```

### 3.3 优化后的四段式提示词（已同步运行代码）

```text
【角色定义】
你是一名医学 RCT 论文信息提取专家，熟悉临床试验论文的书目信息、研究对象、
干预措施和对照措施编码。你只能依据输入的标题、摘要、引言和文章首页信息作答。

【任务描述】
从输入上下文中提取论文的基础信息和试验基本特征。
- 分别提取题目、发表年份、语言、期刊、第一作者、作者联系方式、疾病、国家、干预和对照。
- 发表年份和期刊必须来自明确的文章首页、页眉、页脚或引文信息；没有直接证据时使用 null/NR。
- country 指受试者招募地或试验中心所在国家，不得仅根据作者单位推断。
- intervention 和 control 应描述随机分组后各组实际接受的完整方案，包括共同干预。
- 不得在本模块中把干预名称转换为假针对照枚举。
- 每个非 NR/null 字段必须在 evidence 中给出直接支持该值的短引文。

【字段界定】
- title：论文正式标题。
- publication_year：明确出版年份；整数或 null。
- language：论文正文语言；无证据填 NR。
- journal：期刊正式名称；无证据填 NR。
- first_author：作者列表中的第一作者。
- author_contact：优先通讯作者邮箱，其次第一作者邮箱；无证据填 NR。
- disease_name：标题、目的或纳入标准中明确的目标疾病。
- country：受试者招募或试验实施所在国家。
- intervention：试验组完整干预描述。
- control：对照组完整干预描述。
- evidence：字段级逐字证据；field_id 必须与被支持字段完全相同。

【JSON 模板】
{
  "title": "NR",
  "publication_year": null,
  "language": "NR",
  "journal": "NR",
  "first_author": "NR",
  "author_contact": "NR",
  "disease_name": "NR",
  "country": "NR",
  "intervention": "NR",
  "control": "NR",
  "evidence": [
    {
      "field_id": "title",
      "quote": "输入上下文中的逐字短引文",
      "page": null,
      "source": "markdown"
    }
  ]
}
```

### 3.4 对应字段

| Pydantic 字段 | Excel | 类型/默认值 | 含义 |
|---|---|---|---|
| `title` | Sheet1 G 题目 | `str`, `NR` | 论文标题 |
| `publication_year` | Sheet1 H 发表年份 | `int \| null` | 明确出版年份 |
| `language` | Sheet1 I 文献语言 | `str`, `NR` | 论文语言 |
| `journal` | Sheet1 J 期刊名称 | `str`, `NR` | 期刊全名 |
| `first_author` | Sheet1 M 第一作者姓名 | `str`, `NR` | 第一作者 |
| `author_contact` | Sheet1 N 作者联系方式 | `str`, `NR` | 优先通讯作者邮箱，其次第一作者 |
| `disease_name` | Sheet1 R 疾病名称 | `str`, `NR` | 标题或纳入标准中的疾病 |
| `country` | Sheet1 U 国家 | `str`, `NR` | 招募中心所在国家 |
| `intervention` | Sheet1 X 干预方法名称 | `str`, `NR` | 试验组完整干预 |
| `control` | Sheet1 Y 对照组名称 | `str`, `NR` | 对照组完整干预 |
| `evidence[]` | 不直接写 Excel | `EvidenceQuote[]` | 各字段的原文证据 |

修改位置：`MinerU method/mineru_method/pipeline.py` 的 `metadata` 调用。

---

## 4. STRICTA 针灸 / 干预提示词

### 4.1 输入范围

路由内容：Methods 及其子标题，例如 Interventions、Treatment、Acupuncture protocol。

### 4.2 当前 instruction

```text
Extract STRICTA treatment and sham-control fields. Frequency and duration must not be swapped.
```

### 4.3 优化后的四段式提示词（已同步运行代码）

```text
【角色定义】
你是一名医学 RCT 论文信息提取专家，熟悉 STRICTA 报告规范、针灸临床试验、
假针设计、选穴方案、针刺操作和疗程编码。你只能依据输入的 Methods 上下文作答。

【任务描述】
提取试验组针灸方案和对照组假针/非假针方案，并将原文描述映射到指定字段和枚举。
- 严格区分治疗频次、治疗总次数、总疗程、单次治疗时长和留针时间。
- treatment_frequency_* 表示多久治疗一次；例如 one session per week。
- total_sessions 表示治疗访问/治疗次数总数。
- treatment_duration_* 表示从疗程开始到结束的总时长，不是单次分钟数或治疗次数。
- retention_time_* 仅表示针具留置体内的时间；“20-minute session”不能自动等同留针20分钟。
- 假针类型按对照组实际接受的机制编码，同时在证据中保留 usual care 等共同干预。
- 明确区分固定选穴、加减选穴和个体化选穴。
- 只有原文明示 elicited/achieved deqi 或明确“得气”时，deqi 才能编码为1。
- 未报告或证据不足的字段使用 null/NR/未报告枚举，不得根据针灸常规推断。
- 每个非 NR/null 字段必须提供直接证据。

【字段界定】
- control_type_transformed：1=穿刺假针，2=非穿刺假针，3=非针具假干预，
  4=高强度非假针对照，5=常规治疗非假针对照，6=低强度非假针对照。
- acupuncture_type：1=中医针刺，2=日本医学针刺，3=韩国韩医针刺，4=西医针刺，
  5=五行针刺，6=头针，7=耳针，8=干针，9=未报告。
- stimulation_type：1=手针，2=电针，3=激光针，4=TEAS，5=穴位按压。
- point_selection_scheme：1=固定，2=加减，3=个体化，4=未报告。
- treatment_frequency_raw/value/unit：频次原文、数值、单位；单位1=天、2=周、3=小时。
- treatment_duration_raw/value/unit：总疗程原文、数值、单位；单位1=天、2=周。
- total_sessions：治疗总次数。
- deqi：1=是，2=否，3=未报告，4=不适用。
- needle_depth_raw：进针深度原文。
- retention_time_raw/value：留针时间原文和分钟数。
- practitioner_experience_years：操作者针灸实践年数；不等同于培训小时数。
- evidence：字段级逐字证据。

【JSON 模板】
{
  "control_type_transformed": null,
  "acupuncture_type": null,
  "stimulation_type": null,
  "point_selection_scheme": null,
  "treatment_frequency_raw": "NR",
  "treatment_frequency_value": null,
  "treatment_frequency_unit": null,
  "treatment_duration_raw": "NR",
  "treatment_duration_value": null,
  "treatment_duration_unit": null,
  "total_sessions": null,
  "deqi": 3,
  "needle_depth_raw": "NR",
  "retention_time_raw": "NR",
  "retention_time_value": null,
  "practitioner_experience_years": null,
  "evidence": [
    {
      "field_id": "treatment_frequency_raw",
      "quote": "输入上下文中的逐字短引文",
      "page": null,
      "source": "markdown"
    }
  ]
}
```

### 4.4 对应字段

| Pydantic 字段 | Excel | 类型/编码 | 含义 |
|---|---|---|---|
| `control_type_transformed` | Sheet1 AA | `ShamType \| null` | 假针/非假针对照类型 |
| `control_type_components` | 内部扩展字段 | `list[ShamType]` | 复合对照的全部机制，如 `[2,5]` |
| `acupuncture_type` | Sheet1 AO | `int \| null` | 针刺治疗类型 |
| `stimulation_type` | Sheet1 AP | `int \| null` | 手针、电针等 |
| `point_selection_scheme` | Sheet1 AQ | `int \| null` | 固定、加减、个体化或未报告 |
| `treatment_frequency_raw` | Sheet1 AT | `str`, `NR` | 频次原文 |
| `treatment_frequency_value` | Sheet1 AU | `float \| null` | 标准化频次数值 |
| `treatment_frequency_unit` | Sheet1 AV | `1=天, 2=周, 3=小时` | 频次单位 |
| `treatment_duration_raw` | Sheet1 AX | `str`, `NR` | 总疗程原文，不是单次时长 |
| `treatment_duration_value` | Sheet1 AY | `float \| null` | 总疗程数值 |
| `treatment_duration_unit` | Sheet1 AZ | `1=天, 2=周` | 总疗程单位 |
| `total_sessions` | Sheet1 BA | `int \| null` | 治疗总次数 |
| `deqi` | Sheet1 BD | `DeqiType` | 是否得气 |
| `needle_depth_raw` | Sheet1 BE | `str`, `NR` | 进针深度原文 |
| `retention_time_raw` | Sheet1 BH | `str`, `NR` | 留针时间原文 |
| `retention_time_value` | Sheet1 BI | `float \| null` | 留针分钟数 |
| `practitioner_experience_years` | Sheet1 AL | `float \| null` | 操作者针灸实践年数 |
| `practitioner_experience_raw` | 内部扩展字段 | `str` | 经验年限原文，如 `over 3 years` |
| `practitioner_experience_comparator` | 内部扩展字段 | `=,<,<=,>,>=,NR` | 年限比较符 |
| `evidence[]` | 不直接写 Excel | `EvidenceQuote[]` | 字段级原文证据 |

### 4.5 针灸相关枚举

`ShamType`：

| 代码 | 含义 |
|---:|---|
| 1 | Penetrating needle sham，穿刺性假针 |
| 2 | Non-penetrating needle sham，非穿刺假针 |
| 3 | Non-needle sham，非针具假干预 |
| 4 | High-intensity control，无假针对照 |
| 5 | Usual care control，无假针对照 |
| 6 | Low-intensity control，无假针对照 |

`acupuncture_type`：1=中医针刺，2=日本医学针刺，3=韩国韩医针刺，4=西医针刺，5=五行针刺，6=头针，7=耳针，8=干针，9=未报告。

`stimulation_type`：1=手针，2=电针，3=激光针，4=TEAS，5=穴位按压。

`point_selection_scheme`：1=固定方案，2=加减方案，3=个体化方案，4=未报告。

`DeqiType`：1=是，2=否，3=未报告，4=不适用（如 TEAS、激光针）。

修改位置：`MinerU method/mineru_method/pipeline.py` 的 `acupuncture` 调用。

---

## 5. 试验质量 / 偏倚风险提示词

### 5.1 输入范围

路由内容：Methods 及其子标题，包括 Randomisation、Blinding、Statistical analysis、Missing data。

> 当前严格 Methods 路由可能漏掉 Abstract 中的盲法概述。若希望允许 Abstract 作为补充证据，需要同时修改章节路由，而不只是提示词。

### 5.2 当前 instruction

```text
Extract randomization, concealment, blinding, analysis population and missing-data handling. Regression imputation is code 5. If both per-protocol and ITT are reported, code the article's primary/main analysis, not the first phrase encountered.
```

### 5.3 优化后的四段式提示词（已同步运行代码）

```text
【角色定义】
你是一名医学 RCT 论文信息提取专家，熟悉随机序列生成、分配隐藏、盲法、
ITT/PP 分析、缺失数据处理和 Cochrane 偏倚风险概念。你只能依据提供的试验方法学上下文作答。

【任务描述】
提取随机序列、分配隐藏、盲法、随机样本量、主要分析人群和缺失数据处理方法。
- 随机序列生成回答“序列如何产生”；分配隐藏回答“下一次分组如何对招募人员隐藏”。
- 中央电话/网站随机系统属于分配隐藏证据，除非原文明示计算机产生序列，否则不得编码为计算机随机。
- participant_blinding 必须由 participants/patients 的明确表述支持；不能用医护人员、针灸师、评价者或统计人员盲法替代。
- outcome_assessor_blinding 必须指向结局测量、访视评价或结局判定人员。
- 随机样本量指治疗前 randomized/allocated 人数，不是 received、followed-up 或 analyzed 人数。
- 同时报告 ITT 和 PP 时，提取论文声明的主要/主分析，而不是上下文中最先出现的分析。
- 用简单线性回归填补缺失值时 missing_data_method=5。
- 不得根据常规试验做法推断；证据不足时使用 NR 枚举。
- 每个非 NR/null 字段必须提供直接证据。

【字段界定】
- random_sequence_method：序列生成方法原文。
- random_sequence_class：1=随机数字表，2=计算机随机，3=抽签，4=掷骰子，
  5=抛硬币，6=洗牌/信封，7=最小化，8=未报告，9=其他。
- allocation_concealment：分配隐藏方法原文。
- allocation_concealment_class：1=中心电话/网站，2=不透光密封信封，3=密封信封，
  4=不透光信封，5=未报告，6=其他。
- participant_blinding：1=是，2=否，3=未报告。
- outcome_assessor_blinding：1=是，2=否，3=未报告。
- randomized_sample_intervention_raw：试验组随机/分配人数。
- randomized_sample_control_raw：对照组随机/分配人数。
- total_randomized：随机总人数；两组都有值时必须等于两组之和。
- primary_analysis：1=ITT/mITT，2=available case，3=per protocol，4=未明确报告。
- missing_data_method：1=complete case，2=all available，3=mean imputation，4=LOCF，
  5=regression，6=multiple imputation，7=maximum likelihood，8=weighting，
  9=combination，10=mixed-effect model，11=other，12=no missing data，13=not reported。
- evidence：字段级逐字证据。

【JSON 模板】
{
  "random_sequence_method": "NR",
  "random_sequence_class": 8,
  "allocation_concealment": "NR",
  "allocation_concealment_class": 5,
  "participant_blinding": 3,
  "outcome_assessor_blinding": 3,
  "randomized_sample_intervention_raw": null,
  "randomized_sample_control_raw": null,
  "total_randomized": null,
  "primary_analysis": 4,
  "missing_data_method": 13,
  "evidence": [
    {
      "field_id": "allocation_concealment",
      "quote": "输入上下文中的逐字短引文",
      "page": null,
      "source": "markdown"
    }
  ]
}
```

### 5.4 对应字段

| Pydantic 字段 | Excel | 类型/编码 | 含义 |
|---|---|---|---|
| `random_sequence_method` | Sheet1 AC | `str`, `NR` | 随机序列生成原文 |
| `random_sequence_class` | Sheet1 AD | `int 1..9` | 随机序列分类 |
| `allocation_concealment` | Sheet1 AE | `str`, `NR` | 分配隐藏原文 |
| `allocation_concealment_class` | Sheet1 AF | `int 1..6` | 分配隐藏分类 |
| `participant_blinding` | Sheet1 AH | `YesNoNR` | 研究对象是否盲法 |
| `outcome_assessor_blinding` | Sheet1 AI | `YesNoNR` | 结局评价者是否盲法 |
| `randomized_sample_intervention_raw` | Sheet1 CB | `int \| null` | 试验组随机例数 |
| `randomized_sample_control_raw` | Sheet1 CC | `int \| null` | 对照组随机例数 |
| `total_randomized` | Sheet1 CD | `int \| null` | 随机总例数；若两组均有值，必须等于两组之和 |
| `primary_analysis` | Sheet1 CL | `PrimaryAnalysis` | 主要分析人群 |
| `missing_data_method` | Sheet1 CM | `MissingDataMethod` | 主要分析的缺失数据处理 |
| `evidence[]` | 不直接写 Excel | `EvidenceQuote[]` | 字段级原文证据 |

### 5.5 偏倚风险枚举

`random_sequence_class`：1=随机数字表，2=计算机随机，3=抽签，4=掷骰子，5=抛硬币，6=洗牌/信封，7=最小化，8=未报告，9=其他。

`allocation_concealment_class`：1=中心隐藏（电话/网站），2=不透光密封信封，3=密封信封，4=不透光信封，5=未报告，6=其他。

`YesNoNR`：1=是，2=否，3=未报告。

`PrimaryAnalysis`：1=ITT/mITT，2=available case，3=per protocol，4=未明确报告。

`MissingDataMethod`：

| 代码 | 含义 |
|---:|---|
| 1 | Complete case |
| 2 | All available |
| 3 | Mean imputation |
| 4 | LOCF |
| 5 | Regression |
| 6 | Multiple imputation |
| 7 | Maximum likelihood |
| 8 | Weighting |
| 9 | Combination |
| 10 | Mixed-effect model |
| 11 | Other |
| 12 | No missing data |
| 13 | Not reported |

修改位置：`MinerU method/mineru_method/pipeline.py` 的 `risk_of_bias` 调用。

---

## 6. 统计结局提示词

### 6.1 输入范围

路由内容：Results、结果子标题，以及全文中收集到的 HTML/Markdown 表格。

### 6.2 当前 instruction

```text
Extract every relevant clinical outcome row from one supplied Results table. The pipeline sends tables one by one and preserves every relevant row; do not sample rows or apply a document-wide limit. Keep percent change, confidence interval and Cohen's d in distinct semantic fields.
```

### 6.3 优化后的四段式提示词（已同步运行代码）

```text
【角色定义】
你是一名医学 RCT 论文信息提取专家，熟悉连续型、二分类和有序结局，
ITT/PP 分析、组内变化、组间效应、置信区间、P 值和标准化效应量。
你只能依据输入的 Results 正文和表格作答。

【任务描述】
输入按表格分块提供；表格已先完成确定性分类、表头解析和目标行选择，再逐行提取临床相关结局，不设置全篇条数上限，也不得因表格较长而抽样。
- 必须保留 `table_id`、`row_id`，并显式填写 `arm`、`comparison`、`analysis_set`、`record_role`；多臂试验不能压缩成匿名的 intervention/control。
- 一条记录只能表示一个结局工具、一个时间点/时间对比、一个分析集和一个 estimand；同一行含多个独立时间点或分析集时拆分。
- 由模型判断结局名称、测量工具、时间点、分析人群、组别比较和 P 值对应关系；基线人口学、随机分配/流程和纯行政行可跳过。
- 不得把 ITT 估计值与 PP 样本量组合在同一条记录中。
- 如果上下文只给出 T0–T1 而没有明确日历时长，保留 T0–T1，时间数值和单位填 null。
- 分别保存试验组估计值/CI/n、对照组估计值/CI/n、组间效应、P值、百分比变化和标准化效应量。
- 只有表格明确将 Cohen's d 作为效应量时，才能填写 between_group_measure="SMD"、
  outcome_between_group_estimate 和 effect_size_name="Cohen's d"。
- 组内百分比变化不能自动作为组间 percent_change。
- 原样保留负号和小数，并核对适用时 lower <= estimate <= upper。
- 不得从另一时间点、另一分析行或另一张表补齐当前行缺失值。
- 每个非 null 值必须提供同一行或直接相邻说明中的证据。

【字段界定】
- table_id：来源表稳定 ID，由输入逐字复制。
- row_id：来源行稳定 ID，由输入逐字复制，不能用数组序号替代。
- arm：该行实际出现的全部研究臂及标签、角色、n/组内值。
- comparison：该记录实际表示的组间或组内比较及参与比较的臂。
- analysis_set：原文 FAS、PPS、LOCF、MMRM 等分析集/模型标签；无证据为 NR。
- record_role：primary、secondary、safety、subgroup、sensitivity、baseline、administrative、other 或 NR。
- outcome_name：临床结局名称。
- measurement_instrument：测量工具或量表。
- outcome_observation_timepoint_raw：时间点/时间对比原文。
- outcome_observation_timepoint_value/unit：明确的日历时间数值和单位；单位1=天、2=月、3=年、4=周、5=小时。
- statistic_type：continuous、binary、ordinal 或 other。
- intervention_estimate/lower/upper/n：同一分析行的试验组统计量。
- control_estimate/lower/upper/n：同一分析行的对照组统计量。
- between_group_measure：MD、SMD、OR、RR、RD、HR、percent_change、other 或 NR。
- outcome_between_group_estimate/lower/upper：组间效应及区间。
- outcome_p_value：该结局/时间点对应的 P 值。
- effect_size_name：效应量正式名称，如 Cohen's d。
- evidence：字段级表格或正文逐字证据，source 使用 table 或 markdown。
- source_values：当前表/行中所有原始单元格的逐字值，保持列顺序，不进行首尾裁剪。
- source_evidence：当前表/行的一段连续逐字证据；不能用跨行摘要替代。
- derived：仅在当前证据可唯一复算时为 true；否则为 false。
- derivation：derived=true 时写出公式和输入单元格，否则为 null。
- conflict_group_id：重复/冲突记录的稳定标识；抽取阶段不依据金标准生成或删除。

【JSON 模板】
{
  "outcomes": [
    {
      "table_id": "table-2",
      "row_id": "table-2:r004",
      "arm": [{"arm_id": "A", "arm_label": "Group A", "role": "intervention", "n": null, "estimate": null, "lower": null, "upper": null, "event_count": null}],
      "comparison": {"relation": "intervention_vs_control", "intervention_arm_id": "A", "control_arm_id": "C", "comparator_arm_ids": ["C"], "contrast": "Group A vs Group C"},
      "analysis_set": "FAS",
      "record_role": "primary",
      "outcome_name": "",
      "measurement_instrument": "NR",
      "outcome_observation_timepoint_raw": "",
      "outcome_observation_timepoint_value": null,
      "outcome_observation_timepoint_unit": null,
      "statistic_type": "continuous",
      "analysis_population": "NR",
      "intervention_estimate": null,
      "intervention_variance_lower": null,
      "intervention_variance_upper": null,
      "intervention_n": null,
      "control_estimate": null,
      "control_variance_lower": null,
      "control_variance_upper": null,
      "control_n": null,
      "between_group_measure": "NR",
      "outcome_between_group_estimate": null,
      "outcome_between_group_lower": null,
      "outcome_between_group_upper": null,
      "outcome_p_value": null,
      "outcome_p_value_comparator": "NR",
      "effect_size_name": "NR",
      "source_values": [],
      "source_evidence": "",
      "derived": false,
      "derivation": null,
      "conflict_group_id": null,
      "evidence": [
        {
          "field_id": "outcome_name",
          "quote": "输入表格或正文中的逐字短引文",
          "page": null,
          "source": "table"
        }
      ]
    }
  ]
}
```

### 6.4 对应字段

每个 `OutcomeStatistic` 对应一个“结局 × 时间点 × 分析集/estimand”记录。

| Pydantic 字段 | Excel/用途 | 类型 | 含义 |
|---|---|---|---|
| `outcome_name` | Sheet3 J | `str` | 结局名称 |
| `measurement_instrument` | Sheet3 K | `str`, `NR` | 量表或测量工具 |
| `outcome_observation_timepoint_raw` | Sheet3 DC | `str` | 时间点/对比原文，如 T0–T1 |
| `outcome_observation_timepoint_value` | Sheet3 DD | `float \| null` | 明确或允许推导的时间数值 |
| `outcome_observation_timepoint_unit` | Sheet3 DE | `1=天,2=月,3=年,4=周,5=小时` | 时间单位 |
| `statistic_type` | 内部结构字段 | `continuous/binary/ordinal/other` | 结局统计类型 |
| `analysis_population` | 内部结构字段 | `ITT/mITT/PP/available_case/other/NR` | 与该行数值和样本量一致的分析集 |
| `intervention_estimate` | Sheet3 对应试验组统计区 | `float \| null` | 试验组估计值 |
| `intervention_variance_lower` | Sheet3 对应试验组 CI | `float \| null` | 试验组区间下限 |
| `intervention_variance_upper` | Sheet3 对应试验组 CI | `float \| null` | 试验组区间上限 |
| `intervention_n` | Sheet3 对应试验组样本量 | `int \| null` | 同一行、同一分析集试验组 n |
| `control_estimate` | Sheet3 对应对照组统计区 | `float \| null` | 对照组估计值 |
| `control_variance_lower` | Sheet3 对应对照组 CI | `float \| null` | 对照组区间下限 |
| `control_variance_upper` | Sheet3 对应对照组 CI | `float \| null` | 对照组区间上限 |
| `control_n` | Sheet3 对应对照组样本量 | `int \| null` | 同一行、同一分析集对照组 n |
| `between_group_measure` | 决定 Sheet3 MD/SMD/OR/RR/RD/HR 区域 | 枚举字符串 | 组间效应类型 |
| `outcome_between_group_estimate` | Sheet3 AC/AJ/AM/AP/AS 等 | `float \| null` | 组间效应估计值 |
| `outcome_between_group_lower` | Sheet3 对应 CI 下限 | `float \| null` | 组间区间下限 |
| `outcome_between_group_upper` | Sheet3 对应 CI 上限 | `float \| null` | 组间区间上限 |
| `outcome_p_value` | Sheet3 I | `float \| null` | P 值 |
| `outcome_p_value_comparator` | 内部结构字段 | `=,<,<=,>,>=,NR` | 保留 `<0.001` 等比较符 |
| `effect_size_name` | 内部语义字段 | `str`, `NR` | 如 Cohen's d |
| `evidence[]` | 不直接写 Excel | `EvidenceQuote[]` | 表格/正文原文证据 |

`between_group_measure` 允许值：`MD`、`SMD`、`OR`、`RR`、`RD`、`HR`、`percent_change`、`other`、`NR`。

### 6.5 表格逐张调用与合并

`pipeline.py` 先从完整 Results 上下文中提取 HTML/Markdown 表格，确定性拆出多级表头并生成逐列 `column_map`；随后由独立的表格分类 LLM（`ARTICLE_AGENT_TABLE_CLASSIFIER_MODEL`，当前配置为 `gpt-5.6-luna`）读取整张表和相邻结果叙述，判断 `outcome/safety/subgroup/sensitivity/baseline/flow/other/unknown`。生产路径不再用固定关键词决定表型。分类完成后用确定性规则排除表头、空行和重复表头，选择目标数据行；结局请求先发送完整表格，若响应失败、不完整或 `row_id` 覆盖不全，自动按行重试，所有请求均写入 `request_manifest.jsonl`。当前分片串行发送（1 个请求在途），每次实际请求前等待 10ms；不再使用字符、首尾行或“最多 6 条”截断。分类响应、整表响应、行级 fallback 和覆盖状态均写入 manifest，原始重复记录不删除。

若其他基础字段匹配或语义路由步骤造成准确率下降，可将 `ARTICLE_AGENT_BASIC_MATCH_MODEL` 设为 `gpt-5.6-luna`；它是通用回退，专用表格分类变量优先级更高。该变量只替换语义判断，不替换需要可复核的确定性表头、组别、样本量和统计列解析。

失败分片的恢复请求继续使用 `gpt-5.6-sol`，表格分类单独使用 `gpt-5.6-luna`；成功缓存、失败原因、输入哈希和覆盖行 ID 均保留。

`ARTICLE_AGENT_TABLE_CLASSIFIER_MAX_CHARS` 不再用于裁剪分类输入。若网关无法接受整表，请求规划器改为结构化分片并逐行覆盖，不生成首尾摘要，也不静默丢失行。

当前 juapi 网关配置 `ARTICLE_AGENT_COMPACT_API_PROMPTS=0`：分类、结局抽取、后处理和评分均使用完整四段式提示词。请求过大时只允许在表/行边界拆分，不允许字符截断。

评分模型由 `ARTICLE_AGENT_EVAL_MODEL` 控制（未设置时沿用 `ARTICLE_AGENT_MODEL`）。结局评分按 `source_index` 逐行发送完整原始记录、证据和 Gold，再综合全部行审计；规范化冲突不得覆盖原始候选。

### 6.6 非 LLM 表格兜底

当 outcomes LLM 请求失败时，`table_parser.py` 会用确定性规则解析主要 PainVAS 行。该规则没有提示词；如果要修改其行为，需要改正则表达式和字段赋值逻辑，而不是修改本 Markdown。

修改位置：

- LLM instruction：`MinerU method/mineru_method/llm.py` 的 `extract_outcomes_by_table()` 调用；
- 表格结构/表头/行选择：`MinerU method/mineru_method/table_parser.py`；表格语义分类：`MinerU method/mineru_method/llm.py` 的 `classify_outcome_tables_with_llm()`。

### 6.7 提取后结局处理与金标准冲突标记

结局逐表、逐行抽取完成后，流水线会再调用一次 LLM 做独立的后处理。该阶段不回写或修正原始 `OutcomeStatistic`，只增加规范化字段、重复组和与 Sheet3 金标准的比较标记；因此任何冲突值都会同时保留原值并标记为 `conflict`，便于人工复核。随后程序只依据论文来源行和无损规范化注释生成 `outcomes.canonical.json`：重复/冲突来源进入 `conflict_groups`，canonical 代表行通过 `source_indices` 回指所有原始记录，且 `gold_used=false`。

#### 后处理四段式提示词

```json
{
  "role_definition": "医学 RCT 论文统计结局后处理专家和数据质量审计者",
  "task_description": "逐条处理全部候选结局，不设条数上限；不得删除、合并或改写原始数值、n、置信区间、P 值和证据。只能新增规范化字段、重复组和金标准比较标记。金标准只用于比较，不能填补候选缺失值。允许从该候选行及证据做唯一可复算的规范化；依赖常识、跨行补值或多种解释时使用 NR/unresolved，禁止猜测。",
  "field_boundaries": {
    "source_index": "候选 outcomes 数组中的零基索引，必须复制输入索引",
    "normalized_outcome_name": "依据候选行和证据整理结局名称",
    "normalized_measurement_instrument": "依据证据整理量表/测量工具；无证据为 NR",
    "normalized_timepoint": "只使用该候选行自己的时间点",
    "comparison_relation": "干预/对照/第三臂及组间比较关系；无法判断为 NR",
    "duplicate_group": "重复来源行使用稳定字符串标识，否则为 null",
    "gold_row_ids": "必须逐字复制输入 gold_reference_rows 的 gold_row_id；不确定为空数组",
    "conflict_status": "none、conflict、unresolved 或无金标准时 not_checked",
    "conflict_fields": "outcome_name、instrument、timepoint、arm、n、effect、p_value 等",
    "conflict_reason": "简短可核查说明，不提出未经证据支持的修正值"
  },
  "gold_reference_legend": {
    "column_1": "文章/结局 legacy 行标识；不是稳定的 gold_row_id",
    "STUDYID": "研究内部编号",
    "OUTCOM": "金标准结局名称",
    "INSTRU": "金标准测量工具",
    "FOLTIM/FOLTIMN/FOLTIMU": "观察时间点原文、数值和单位编码",
    "PVALNUM/PVALRAG": "P 值数值及范围编码",
    "B* / E* / F*": "基线、主要结束时点和随访时点的组内统计区；I/C 为干预/对照，DEST 及 L/U 为组间效应和区间",
    "BOR/BRR/BRD/BHR 及 EOR/ERR/ERD/EHR": "对应时点的 OR/RR/RD/HR 组间效应及区间"
  },
  "json_template": {
    "records": [{
      "source_index": 0,
      "normalized_outcome_name": "NR",
      "normalized_measurement_instrument": "NR",
      "normalized_timepoint": "NR",
      "comparison_relation": "NR",
      "duplicate_group": null,
      "gold_row_ids": [],
      "conflict_status": "unresolved",
      "annotation_status": "unresolved",
      "conflict_fields": [],
      "conflict_reason": ""
    }],
    "notes": []
  }
}
```

#### 后处理输出字段

后处理结果写入每篇文章目录的 `outcomes.postprocessed.json`，原始候选结果仍在 `extraction.json` 的 `outcomes` 中：

| 字段 | 类型 | 规则 |
|---|---|---|
| `source_index` | `int` | 指向原始 outcomes 数组，保证可回溯 |
| `source_outcome` | `OutcomeStatistic` | 原始抽取值的完整副本，不得修改 |
| `normalized_outcome_name` | `str` | LLM 规范化结局名称 |
| `normalized_measurement_instrument` | `str` | LLM 规范化工具 |
| `normalized_timepoint` | `str` | LLM 规范化时间点 |
| `comparison_relation` | `str` | LLM 判断的组间比较关系 |
| `duplicate_group` | `str \| null` | 重复记录分组 |
| `conflict_group_id` | `str \| null` | 独立 canonical 归组生成的冲突组 ID |
| `gold_row_ids` | `list[str]` | 对应 Sheet3 金标准行 ID |
| `conflict_status` | `none \| conflict \| unresolved \| not_checked` | 与金标准的比较状态 |
| `annotation_status` | `none \| conflict \| unresolved \| not_checked` | 规范化注释状态；不覆盖 source_outcome |
| `conflict_fields` | `list[str]` | 冲突字段 |
| `conflict_reason` | `str` | 可核查原因 |
| `value_preserved` | `bool` | 始终为 `true`；冲突不覆盖原值 |

`outcomes.canonical.json` 另含 `records[]`（canonical 代表行、来源索引和选择状态）以及
`conflict_groups[]`（所有重复/数值冲突来源）。该文件只用于证据审阅和后续 Excel 投影，
不会把代表行当作已确认正确值，也不会使用金标准反向修正原始抽取。

若某个金标准行没有任何候选记录匹配，会在 `gold_conflicts[]` 中保留该行并标记 `record_missing`；这表示需要人工回查，不代表自动推断候选值。

实现位置：`MinerU method/mineru_method/llm.py` 的 `postprocess_outcomes_with_llm()`；提示词常量为 `OUTCOME_POSTPROCESS_PROMPT_SPEC`；金标准只由 `gold.py` 在抽取完成后读取。

---

## 7. CONSORT 流程图 VLM 提示词

### 7.1 输入

输入为自动定位并渲染的 Figure 1 所在 PDF 页面图像，而不是 Markdown 文本。

### 7.2 当前完整提示词模板

```json
{
  "task": "Extract the CONSORT participant flow from Figure 1. Keep branches distinct. Do not infer obscured numbers.",
  "response_format_instruction": "Return one JSON object only.",
  "article_id": "{{article_id}}",
  "required": [
    "screened_n",
    "randomized_n",
    "arms: arm_name/randomized_n/received_n/analyzed_n/dropout_n/dropout_reasons/follow_up_completed_n/other_missing_data",
    "evidence"
  ],
  "evidence_rule": "Evidence quotes must be visible text and use source=figure.",
  "json_schema": "{{ConsortFlowExtraction.model_json_schema()}}"
}
```

### 7.3 优化后的四段式 VLM 提示词（已同步运行代码）

```text
【角色定义】
你是一名医学 RCT 论文信息提取专家，熟悉 CONSORT 受试者流程图、随机分组、
分配、接受干预、随访、脱落和分析人群。你具备医学图像文字理解能力，
只能依据输入图像中清晰可见的信息作答。

【任务描述】
从给定的 CONSORT 流程图图像中提取受试者流转数据，保持每个随机组及分支独立。
- 不推断模糊、裁切、遮挡或不可辨认的数字。
- 区分 assessed/screened、excluded、randomized、allocated、received treatment、
  followed up、analyzed 和 dropout。
- received_n 不能写入 randomized_n；随访完成数不能写入 analyzed_n。
- 使用图中原始时间点标签记录 follow_up_completed_n。
- 将每个脱落/缺失原因关联到正确的组别和阶段。
- 图中未报告 analyzed 人数时，analyzed_n 填 null。
- evidence 必须是图中可见文字，source 固定为 figure。

【字段界定】
- screened_n：进入筛选或最终资格评估的人数。
- randomized_n：全试验随机总人数。
- arms：随机组列表。
- arms[].arm_name：图中组名。
- arms[].randomized_n：分配到该组的人数。
- arms[].received_n：实际接受该组干预的人数。
- arms[].analyzed_n：明确纳入统计分析的人数。
- arms[].dropout_n：明确标注的脱落人数。
- arms[].dropout_reasons：脱落阶段、人数和原因。
- arms[].follow_up_completed_n：原始时间点标签到完成随访人数的映射。
- arms[].other_missing_data：非脱落的其他缺失事件。
- evidence：图中文字证据及页码。

【JSON 模板】
{
  "screened_n": null,
  "randomized_n": null,
  "arms": [
    {
      "arm_name": "",
      "randomized_n": null,
      "received_n": null,
      "analyzed_n": null,
      "dropout_n": null,
      "dropout_reasons": [
        {"stage": "", "n": null, "reason": ""}
      ],
      "follow_up_completed_n": {},
      "other_missing_data": [
        {"stage": "", "n": null, "reason": ""}
      ]
    }
  ],
  "evidence": [
    {
      "quote": "图中可见的逐字短引文",
      "page": null,
      "source": "figure"
    }
  ]
}
```

### 7.4 对应字段

| 层级 | 字段 | 类型 | 含义 |
|---|---|---|---|
| 试验 | `screened_n` | `int \| null` | 筛选/最终资格评估人数 |
| 试验 | `randomized_n` | `int \| null` | 随机总人数 |
| 试验 | `arms[]` | `FlowArm[]` | 各随机组 |
| 组 | `arm_name` | `str` | 组名 |
| 组 | `randomized_n` | `int \| null` | 分配至该组人数 |
| 组 | `received_n` | `int \| null` | 实际接受干预人数 |
| 组 | `analyzed_n` | `int \| null` | 纳入分析人数 |
| 组 | `dropout_n` | `int \| null` | 脱落人数 |
| 组 | `dropout_reasons[]` | `FlowEvent[]` | 脱落阶段、人数、原因 |
| 组 | `follow_up_completed_n` | `dict[str,int]` | 时间点到访/完成随访人数 |
| 组 | `other_missing_data[]` | `FlowEvent[]` | 其他缺失数据事件 |
| 事件 | `stage` | `str` | 事件阶段/时间点 |
| 事件 | `n` | `int \| null` | 人数 |
| 事件 | `reason` | `str` | 原因 |
| 证据 | `evidence[].quote` | `str` | 图中可见原文 |
| 证据 | `evidence[].page` | `int \| null` | 页码；注意 PDF 页序与印刷页码语义 |
| 证据 | `evidence[].source` | 固定 `figure` | 证据来源 |

修改位置：`MinerU method/mineru_method/llm.py` 的 `extract_flow()`。

---

## 8. Pydantic 校验重试提示

第一次响应未通过 Pydantic 校验时，程序会把完整校验错误放回下一次请求：

```json
{
  "validation_feedback": "{{Pydantic ValidationError}}"
}
```

传输失败时使用：

```text
Transport error on prior attempt; retry the same extraction: {{error}}
```

当前最多请求 3 次，即首次加 2 次重试。模型必须修复结构，不应因为校验失败而改写已有正确证据。

修改位置：`MinerU method/mineru_method/llm.py` 的 `ValidatedExtractor`。

---

## 9. LLM 分模块质量评价提示词

该提示词只评价抽取效果，不参与生成正式抽取结果。

### 9.1 角色定义 / System Prompt

```text
你是一名医学 RCT 论文信息提取专家，在本任务中担任独立的信息提取质量审计者。
你熟悉临床试验方法学、STRICTA、CONSORT、医学统计和字段编码。
你必须以论文原文/图像证据为最高依据，严格评价候选抽取，同时识别人工金标准本身的错误或歧义。
只输出一个符合指定 JSON 模板的对象，不输出额外正文。
```

### 9.2 四段式 User Prompt 模板

```json
{
  "role_definition": "医学 RCT 论文信息提取专家兼独立质量审计者",
  "task_description": {
    "task": "独立评价文章 {{article_id}} 的 {{module}} 模块抽取质量",
    "authority_order": [
      "论文逐字引文或图像可见证据是最高依据",
      "人工 Excel 金标准仅作参考，可能存在编码、年份、样本量或时间点错误",
      "候选字段非空不代表正确，必须由证据支持"
    ],
    "scoring_rule": "module_score 必须为0至100的整数",
    "response_limit": "不设置字段发现、记录数或词数上限；必须覆盖全部输入字段/记录。仅在请求过大时按完整表行或完整段落分片，不能截断语义内容。"
  },
  "field_definitions": {
    "module": "{{module}}",
    "fields_to_evaluate": "{{该模块 canonicalFieldId 列表}}",
    "status": ["correct", "acceptable", "incorrect", "missing", "gold_ambiguous"],
    "severity": ["critical", "major", "minor"],
    "candidate": "{{候选抽取字段}}",
    "human_gold_values": "{{人工 Excel 金标准}}",
    "source_context": "{{论文或图像证据}}"
  },
  "json_template": {
    "module_score": 0,
    "module_verdict": "string",
    "field_findings": [
      {
        "field": "string",
        "status": "correct|acceptable|incorrect|missing|gold_ambiguous",
        "severity": "critical|major|minor",
        "reason": "brief string"
      }
    ],
    "strengths": ["string"],
    "weaknesses": ["string"],
    "gold_quality_notes": ["string"]
  }
}
```

### 9.3 各评价模块对应字段

| 评价模块 | 与人工金标准直接比较的字段 |
|---|---|
| `metadata` | `title`, `publication_year`, `journal`, `first_author`, `country`, `intervention`, `control` |
| `acupuncture` | `control_type_transformed`, `treatment_frequency_raw`, `treatment_frequency_value`, `treatment_frequency_unit`, `treatment_duration_raw`, `treatment_duration_value`, `treatment_duration_unit`, `total_sessions`, `deqi` |
| `risk_of_bias` | `random_sequence_method`, `random_sequence_class`, `allocation_concealment`, `allocation_concealment_class`, `participant_blinding`, `outcome_assessor_blinding`, `primary_analysis`, `missing_data_method` |
| `outcomes` | Sheet3 中该文章所有非空人工标注字段，与 `OutcomeExtraction.outcomes[]` 比较 |
| `consort_flow` | `randomized_sample_intervention_raw`, `randomized_sample_control_raw`, `total_randomized`，并结合 VLM 图证据评价详细流程 |

### 9.4 评分尺度（已纳入任务描述）

当前模块评审提示没有明确规定 `module_score` 的量纲，2015-01 曾出现 `6`、`62`、`0.95` 等不一致尺度。建议加入：

```text
module_score 必须是0至100的整数：
- 90–100：接近完整且证据一致，仅有轻微问题；
- 75–89：大部分正确，存在少量实质性遗漏或编码问题；
- 60–74：质量混合，重要字段需要修正；
- 40–59：存在主要遗漏或语义错配；
- 0–39：不适合直接用于下游任务。
```

修改位置：`MinerU method/evaluate_2015_01.py` 的 `call_judge()`、`common` 和模块 `payload`。

---

## 10. LLM 综合评价提示词

### 10.1 优化后的四段式 User Prompt 模板

```json
{
  "role_definition": "医学 RCT 论文信息提取专家兼综合质量审计者",
  "task_description": {
    "task": "综合五个独立模块审计，生成最终抽取质量评价",
    "scoring_rules": [
      "所有 module_scores 和 overall_score 必须是0至100的整数",
      "输入模块分数不在0至100量纲时，必须根据字段发现重新计算",
      "结局和偏倚风险中的证据性错误权重高于文字表述差异",
      "必须区分候选抽取错误与人工金标准错误"
    ]
  },
  "field_definitions": {
    "module_audits": "{{metadata、acupuncture、risk_of_bias、outcomes、consort_flow 五个评价 JSON}}",
    "overall_score": "综合质量分，0至100整数",
    "module_scores": "五个模块的标准化0至100整数分",
    "critical_errors": "影响下游使用的主要候选抽取错误",
    "gold_quality_notes": "人工金标准的错误、歧义或内部不一致",
    "next_actions": "使用 canonicalFieldId 表示的可执行修改建议"
  },
  "json_template": {
    "overall_score": 0,
    "module_scores": {
      "metadata": 0,
      "acupuncture": 0,
      "risk_of_bias": 0,
      "outcomes": 0,
      "consort_flow": 0
    },
    "verdict": "string",
    "critical_errors": ["string"],
    "gold_quality_notes": ["string"],
    "next_actions": ["string"]
  }
}
```

此请求仍使用第 9.1 节的评审 System Prompt。

### 10.2 综合任务约束

所有约束已经放入上方 `task_description.scoring_rules`，不再额外拼接自由文本任务提示，
以避免评分尺度或证据优先级出现互相冲突的指令。

修改位置：`MinerU method/evaluate_2015_01.py` 中的 `synthesis`。

---

## 11. 通用证据字段

文本抽取的 `EvidenceQuote`：

| 字段 | 规则 |
|---|---|
| `field_id` | 必须是被证据支持的 canonicalFieldId |
| `quote` | 输入上下文中的逐字短引文，不应改写 |
| `page` | 1 起始页码；无法可靠确定时为 null |
| `source` | `markdown`、`table` 或 `figure` |
| `support_type` | `direct`=直接报告；`derived`=唯一可复算推导 |
| `derivation` | derived 时记录公式、单位换算或跨章节映射；direct 时为 null |

建议在所有模块提示中保留以下统一要求：

```text
对于每个非 NR/null 的实质性字段，必须添加一条简短的逐字 EvidenceQuote。
EvidenceQuote.field_id 必须与被支持的 canonicalFieldId 完全一致。
证据必须直接支持具体值或编码，不能仅与该主题相关。
```

---

## 12. 修改后同步检查清单

修改提示词时请同时检查：

- 是否改变了某字段的语义，而 Pydantic 字段名/类型仍未调整；
- 是否增加了新枚举值，但 `schemas.py` 和 Excel codebook 尚未同步；
- 是否要求使用 Abstract 证据，但路由仍只提供 Methods；
- 是否允许推导值，以及如何区分“原文值”和“推导值”；
- 是否把同一结局不同时间点、ITT/PP 分析或不同样本量混在一条记录；
- 是否要求 VLM 提取的字段确实存在于 `ConsortFlowExtraction`；
- 修改后运行：

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m pytest -q tests\test_mineru_method.py
```

当前代码来源：

- `MinerU method/mineru_method/llm.py`
- `MinerU method/mineru_method/pipeline.py`
- `MinerU method/mineru_method/schemas.py`
- `MinerU method/evaluate_2015_01.py`
- `registry/legacy-excel/sheet1-mapping.json`
- `registry/legacy-excel/sheet3-mapping.json`
