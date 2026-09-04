from __future__ import annotations


ROLE_DEFINITION = """你是一名医学 RCT 论文信息提取专家，熟悉临床试验方法学、CONSORT、STRICTA、偏倚风险评价、医学统计学和循证医学数据编码。
你必须严格依据提供的论文上下文进行结构化提取。允许推导，但不允许猜测：只有当全部输入均有直接原文证据、转换规则唯一且结果可复算时，才能填写推导值；必须在 evidence 中标记 support_type=derived，并在 derivation 中写明公式或映射。若缺少前提、存在多种合理解释、依赖常识/惯例/人工金标准或根据“未提及”反推，必须返回 null/NR。直接摘录使用 support_type=direct。严格使用字段界定与枚举编码；每个非 NR/null 的实质性结果必须提供可逐字核验的短证据；仅输出符合指定模板的一个 JSON 对象。"""


PROMPT_SPECS: dict[str, dict] = {
    "metadata": {
        "task_description": """从标题、摘要、引言和文章首页上下文中提取论文基础信息和试验基本特征。发表年份和期刊必须来自明确的文章首页、页眉、页脚或引文；country 指受试者招募地或试验中心所在国家，不得仅根据作者单位推断；intervention 和 control 描述随机组实际接受的完整方案及共同干预。证据不足时使用 null/NR。""",
        "field_boundaries": {
            "title": "论文正式标题",
            "publication_year": "明确出版年份；整数或 null",
            "language": "论文正文语言；无证据为 NR",
            "journal": "期刊正式名称；无证据为 NR",
            "first_author": "作者列表中的第一作者",
            "author_contact": "优先通讯作者邮箱，其次第一作者邮箱",
            "disease_name": "标题、目的或纳入标准中的目标疾病",
            "country": "受试者招募或试验实施所在国家",
            "intervention": "试验组完整干预描述",
            "control": "对照组完整干预描述",
            "evidence": "字段级逐字证据，field_id 与字段完全相同",
        },
        "json_template": {
            "title": "NR", "publication_year": None, "language": "NR", "journal": "NR",
            "first_author": "NR", "author_contact": "NR", "disease_name": "NR", "country": "NR",
            "intervention": "NR", "control": "NR", "evidence": [],
        },
    },
    "acupuncture": {
        "task_description": """从 Methods 上下文提取 STRICTA 针灸方案及假针/非假针对照。严格区分治疗频次、治疗总次数、总疗程、单次治疗时长和留针时间；20-minute session 不能自动等同留针20分钟。若总次数和每周频次均有直接证据，按预定义公式 course_weeks=total_sessions/sessions_per_week 推导总疗程，并记录derived证据。按对照组实际接受的机制编码假针类型；存在假针+usual care等复合对照时，control_type_transformed保存主要假针机制，control_type_components保存全部机制。只有原文明示 elicited/achieved deqi 或明确“得气”时 deqi 才为1。不得根据针灸常规推断。""",
        "field_boundaries": {
            "control_type_transformed": "1穿刺假针；2非穿刺假针；3非针具假干预；4高强度非假针；5常规治疗；6低强度非假针",
            "control_type_components": "复合对照的全部机制代码，如非穿刺假针+常规治疗=[2,5]",
            "acupuncture_type": "1中医；2日本；3韩国；4西医；5五行；6头针；7耳针；8干针；9未报告",
            "stimulation_type": "1手针；2电针；3激光针；4 TEAS；5穴位按压",
            "point_selection_scheme": "1固定；2加减；3个体化；4未报告",
            "treatment_frequency_raw/value/unit": "治疗频次；单位1天、2周、3小时",
            "treatment_duration_raw/value/unit": "总疗程，不是单次分钟数或次数；单位1天、2周",
            "total_sessions": "治疗总次数",
            "deqi": "1是；2否；3未报告；4不适用",
            "needle_depth_raw": "进针深度原文",
            "retention_time_raw/value": "明确留针时间及分钟数",
            "practitioner_experience_years": "针灸实践年数，不等同培训小时",
            "practitioner_experience_raw/comparator": "经验原文与比较符，over 3 years保存raw、value=3、comparator=>",
            "evidence": "字段级逐字证据",
        },
        "json_template": {
            "control_type_transformed": None, "control_type_components": [], "acupuncture_type": None, "stimulation_type": None,
            "point_selection_scheme": None, "treatment_frequency_raw": "NR",
            "treatment_frequency_value": None, "treatment_frequency_unit": None,
            "treatment_duration_raw": "NR", "treatment_duration_value": None,
            "treatment_duration_unit": None, "total_sessions": None, "deqi": 3,
            "needle_depth_raw": "NR", "retention_time_raw": "NR", "retention_time_value": None,
            "practitioner_experience_years": None, "practitioner_experience_raw": "NR",
            "practitioner_experience_comparator": "NR", "evidence": [],
        },
    },
    "risk_of_bias": {
        "task_description": """从试验方法学上下文提取随机序列、分配隐藏、盲法、随机样本量、主要分析人群和缺失数据处理。random_sequence_method保存论文对序列生成的任何直接叙述，即使具体算法未报告；random_sequence_class只按明确算法分类。中央电话/网站系统不能自动证明计算机生成序列。participant_blinding必须由participants/patients明确表述支持。随机样本量是治疗前randomized/allocated人数。同时报告ITT和PP时按证据层级判定主要分析：显式primary/main > 摘要主结局分析 > 主文主表相对于补充材料；使用后两级时标记derived并记录依据。简单线性回归填补缺失值编码为5。""",
        "field_boundaries": {
            "random_sequence_method/class": "生成方法；分类1随机数字表、2计算机、3抽签、4骰子、5硬币、6洗牌/信封、7最小化、8未报告、9其他",
            "allocation_concealment/class": "隐藏方法；分类1中心电话/网站、2不透光密封信封、3密封信封、4不透光信封、5未报告、6其他",
            "participant_blinding": "1是、2否、3未报告；只评价受试者",
            "outcome_assessor_blinding": "1是、2否、3未报告；只评价结局评价者",
            "randomized_sample_intervention_raw/control_raw": "两组随机/分配人数",
            "total_randomized": "随机总人数，必须与两组之和一致",
            "primary_analysis": "1 ITT/mITT；2 available case；3 per protocol；4未明确",
            "missing_data_method": "1 complete case；2 all available；3 mean；4 LOCF；5 regression；6 multiple imputation；7 ML；8 weighting；9 combination；10 mixed-effect；11 other；12 no missing；13 NR",
            "evidence": "字段级逐字证据",
        },
        "json_template": {
            "random_sequence_method": "NR", "random_sequence_class": 8,
            "allocation_concealment": "NR", "allocation_concealment_class": 5,
            "participant_blinding": 3, "outcome_assessor_blinding": 3,
            "randomized_sample_intervention_raw": None, "randomized_sample_control_raw": None,
            "total_randomized": None, "primary_analysis": 4, "missing_data_method": 13,
            "evidence": [],
        },
    },
    "outcomes": {
        "task_description": """输入按表格分块提供，逐张表、逐行提取 Results 中的临床结局。表格已经过确定性分类，必须先遵守 TABLE_CATEGORY、TABLE_COLUMN_MAP 和 TARGET_SELECTION_REASON，再处理被选中的目标行。不得设置全篇条数上限或抽样；每个输入行必须在 row_decisions 中明确标记为 outcome 或 non_outcome，所有 outcome 行生成记录。非临床结局的基线人口学、随机分配/流程和纯行政行可标记为 non_outcome，但不能静默漏掉。一条记录只能表示一个结局工具、一个时间点/对比、一个 analysis_population 和一个 estimand；同一表格同时含 PP 与 ITT、多个时间点或多个独立比较时必须拆成独立记录。必须逐字保留 TABLE_ID 和 ROW_ID，明确填写 arm、comparison、analysis_set 和 record_role；不能把多个臂压缩成匿名 intervention/control。由模型判断结局名称、时间点、分析人群、组别比较和 P 值对应关系，但数值只能来自当前行和 TABLE_COLUMN_MAP 对应单元格。时间点可使用 Methods 时间字典唯一映射并标记 derived。分别保存所有研究臂的估计值、CI、n、组间效应、P值及比较符和效应量；不得跨时间点、分析行或表格补值。只允许证据唯一支持的可复算推导，禁止猜测、常识补全或依据 Gold 修改。""",
        "field_boundaries": {
            "table_id": "输入 TABLE_ID 的稳定来源表ID；逐字复制并去除 #part 后缀",
            "row_id": "输入行末 ROW_ID 的稳定行ID；逐字复制，不能用数组序号替代",
            "arm": "该行实际出现的全部研究臂；每臂保留arm_id、arm_label、role和明确的n/估计值",
            "comparison": "该记录实际比较关系；明确 intervention_vs_control、arm_vs_arm、multi_arm、within_arm、overall 或 NR",
            "row_decisions": "对输入的每个 ROW_ID 给出 outcome/non_outcome 和基于当前行的简短理由；不得遗漏任何输入行",
            "analysis_set": "原文分析集/模型标签，如 ITT、FAS、PPS、LOCF、MMRM；无证据为NR",
            "record_role": "primary、secondary、safety、subgroup、sensitivity、baseline、administrative、other或NR",
            "outcome_name/instrument": "临床结局及量表；必须对应当前表格的一行",
            "timepoint_raw/value/unit": "时间原文及明确日历值；单位1天、2月、3年、4周、5小时",
            "statistic_type": "continuous、binary、ordinal 或 other",
            "analysis_population": "ITT、mITT、PP、available_case、other或NR",
            "intervention_*": "同一分析行试验组估计值、CI和n",
            "control_*": "同一分析行对照组估计值、CI和n",
            "between_group_measure": "MD、SMD、OR、RR、RD、HR、percent_change、other、NR",
            "outcome_between_group_*": "组间效应及区间",
            "outcome_p_value": "该结局/时间点的P值",
            "outcome_p_value_comparator": "=、<、<=、>、>=或NR",
        "effect_size_name": "效应量正式名称，如 Cohen's d",
        "source_evidence": "当前表/行的一段连续逐字证据；不跨行拼接",
        "derived": "仅在当前行证据唯一支持并完成可复算推导时为true，否则false",
        "derivation": "derived=true时给出可复算公式和输入单元格；否则为null",
        "conflict_group_id": "重复/冲突记录的稳定组标识；抽取阶段不得依据Gold生成或删除记录",
        "evidence": "字段级表格或正文逐字证据",
        },
        "json_template": {
            "outcomes": [{
                "table_id": "table-2", "row_id": "table-2:r004",
                "arm": [{"arm_id": "A", "arm_label": "Group A", "role": "intervention", "n": None, "estimate": None, "lower": None, "upper": None, "event_count": None}],
                "comparison": {"relation": "intervention_vs_control", "intervention_arm_id": "A", "control_arm_id": "C", "comparator_arm_ids": ["C"], "contrast": "Group A vs Group C"},
                "analysis_set": "FAS", "record_role": "primary",
                "outcome_name": "", "measurement_instrument": "NR",
                "outcome_observation_timepoint_raw": "", "outcome_observation_timepoint_value": None,
                "outcome_observation_timepoint_unit": None, "statistic_type": "continuous", "analysis_population": "NR",
                "intervention_estimate": None, "intervention_variance_lower": None,
                "intervention_variance_upper": None, "intervention_n": None,
                "control_estimate": None, "control_variance_lower": None,
                "control_variance_upper": None, "control_n": None,
                "between_group_measure": "NR", "outcome_between_group_estimate": None,
                "outcome_between_group_lower": None, "outcome_between_group_upper": None,
            "outcome_p_value": None, "outcome_p_value_comparator": "NR", "effect_size_name": "NR", "quote": "", "evidence": [],
            }],
            "row_decisions": [{"row_id": "table-2:r004", "status": "outcome", "reason": "该行报告临床结局统计"}],
        },
    },
}


# Table routing is an independent LLM step.  It receives the complete table
# block (caption, parsed headers and every source row), so the outcome model is
# never asked to infer whether a baseline table is an outcome table.  The
# classifier must make a semantic decision from the table as a whole rather
# than applying a single-word trigger.
TABLE_CLASSIFICATION_PROMPT_SPEC = {
    "role_definition": (
        "你是一名医学 RCT 论文表格分类专家。你熟悉临床试验基线特征、临床结局、"
        "安全性、亚组、敏感性分析和 CONSORT 流程表。你只负责判断整张表的语义类型，"
        "不抽取任何结局数值。"
    ),
    "task_description": (
        "阅读完整的表题、确定性解析的表头、各研究臂/样本量和全部数据行，给整张表分配一个"
        "table_category。必须综合表题、列结构、行的统计语义和相邻结果叙述，不要根据单个关键词、"
        "表号或第一行做机械匹配。outcome 表示临床结局测量及其组间/组内统计；safety 表示不良事件、"
        "耐受性或安全性；baseline 表示随机化前人口学/疾病特征；flow 表示筛选、随机、分配、随访或"
        "脱落流程；subgroup 和 sensitivity 只在表格明确呈现相应分析时使用；other 表示明确非上述类型的"
        "表；只有证据确实不足时才用 unknown。只输出指定 JSON。"
    ),
    "field_boundaries": {
        "table_category": (
            "outcome|safety|subgroup|sensitivity|baseline|flow|other|unknown；整张表的语义类别，"
            "不能因为表号或单个词出现而决定"
        ),
        "confidence": "0到1之间的小数；表示对整张表分类的信心，不是结局正确率",
        "rationale": "一句话说明使用了哪些表题、列结构、行语义或相邻叙述证据；不得提出未在输入中出现的新事实",
    },
    "json_template": {
        "table_category": "outcome",
        "confidence": 0.9,
        "rationale": "表格包含临床结局测量、多个随机组统计列和组间P值。",
    },
}


# The Results pipeline uses this smaller wire contract for each table/row
# batch.  It is intentionally separate from the Excel-facing OutcomeStatistic
# template so a long table can be returned efficiently while normalization
# still fills the complete Pydantic model.
TABLE_OUTCOME_PROMPT_SPEC = {
    "task_description": (
        "当前输入只包含一张已经分类的表及其逐行标记。先读取 TABLE_CATEGORY、TABLE_ID、TABLE_COLUMN_MAP 和 TARGET_SELECTION_REASON，再逐行检查所有输入 ROW_ID。"
        "逐行提取每一条临床结局数据行，不能因为表格较长而抽样或设置条数上限。必须在 row_decisions 中为每一个输入 ROW_ID 返回 outcome 或 non_outcome；不得静默漏行。"
        "排除基线人口学、随机分配/流程和纯行政行时，只能给该行标记 non_outcome 并说明原因。"
        "每条记录只对应一个结局工具、一个时间点/对比和一个分析人群；同一行含多个独立时间点、分析集或比较时拆分。"
        "逐字复制行末 ROW_ID 和 TABLE_ID；由模型判断结局名称、测量工具、时间点、分析人群、研究臂、比较关系、分析集、记录角色和P值对应关系。"
        "数值只能复制 TABLE_COLUMN_MAP 对应单元格；允许基于同一行完整数值作唯一计算，但必须标记 derived 并写出公式，不允许猜测、常识补全或跨行借值；无证据字段填null/NR。"
        "quote必须是输入中对应行的一段连续逐字短引文（每条记录只保留一条即可），evidence只列出支持关键字段的必要引用，不要复述整行或添加解释；只输出一个 JSON 对象。"
    ),
    "field_boundaries": {
        "table_id": "输入 SOURCE_TABLE_ID/TABLE_ID；必须保留来源表身份",
        "row_id": "输入行末 ROW_ID；必须逐字复制，不能跨行组合",
        "arm": "该行出现的所有研究臂；role只能是intervention/control/comparator/other/NR",
        "comparison": "relation=intervention_vs_control|arm_vs_arm|multi_arm|within_arm|overall|not_applicable|NR；写明臂ID和contrast",
        "analysis_set": "原文标签，如 ITT、FAS、PPS、LOCF、MMRM；无证据NR",
        "record_role": "primary|secondary|safety|subgroup|sensitivity|baseline|administrative|other|NR",
        "timepoint_unit": "1=day,2=month,3=year,4=week,5=hour,null=not reported",
        "statistic_type": "continuous|binary|ordinal|other",
        "analysis_population": "ITT|mITT|PP|available_case|other|NR",
        "between_group_measure": "MD|SMD|OR|RR|RD|HR|percent_change|other|NR",
        "p_comparator": "=|<|<=|>|>=|NR",
        "row_mapping": "quote must identify the source table row; never combine values across rows",
        "coverage": "row_decisions 必须逐字覆盖输入中的每一个 ROW_ID；缺失任何 ID 的响应视为不完整并会被重试",
        "source_first": "TABLE_COLUMN_MAP 和当前行是数值唯一来源；Gold、其他表和常识不能覆盖或补写当前行",
    },
    "json_template": {
        "outcomes": [{
            "table_id": "table-2", "row_id": "table-2:r004",
            "arm": [{"arm_id": "A", "arm_label": "Group A", "role": "intervention", "n": None, "estimate": None, "lower": None, "upper": None, "event_count": None}],
            "comparison": {"relation": "intervention_vs_control", "intervention_arm_id": "A", "control_arm_id": "C", "comparator_arm_ids": ["C"], "contrast": "Group A vs Group C"},
            "analysis_set": "FAS", "record_role": "secondary",
            "outcome_name": "", "measurement_instrument": "NR", "outcome_observation_timepoint_raw": "",
            "outcome_observation_timepoint_value": None, "outcome_observation_timepoint_unit": None,
            "statistic_type": "continuous", "analysis_population": "NR",
            "intervention_estimate": None, "intervention_variance_lower": None,
            "intervention_variance_upper": None, "intervention_n": None,
            "control_estimate": None, "control_variance_lower": None,
            "control_variance_upper": None, "control_n": None,
            "between_group_measure": "NR", "between_group_estimate": None,
            "between_group_lower": None, "between_group_upper": None,
            "outcome_p_value": None, "outcome_p_value_comparator": "NR", "effect_size_name": "NR", "quote": "",
            "source_evidence": "", "source_cells": [], "p_value_cells": [],
            "derived": False, "derivation": None, "conflict_group_id": None,
            "evidence": [],
        }],
        "row_decisions": [{"row_id": "table-2:r004", "status": "outcome", "reason": "该行报告临床结局统计"}],
    },
}

# The full field registry above remains the authoritative contract and is
# written to the audit prompts.  The API extraction pass uses this separate
# semantic-first contract so the model does not spend its response budget
# repeating the entire Pydantic schema for every row.  Numeric cells are still
# supplied losslessly in ``source_context`` and are enriched deterministically
# by the normalizer; this is a transport decomposition, not source clipping.
OUTCOME_SEMANTIC_PROMPT_SPEC = {
    "role_definition": (
        "You are a medical RCT outcome extraction expert familiar with CONSORT, STRICTA, "
        "clinical scales and statistical tables. Use only the supplied table/row evidence."
    ),
    "task_description": (
        "Read every supplied ROW_ID. For each clinically reportable outcome, create one compact "
        "record per outcome x timepoint x analysis_set x comparison. Preserve all study arms and "
        "exact source_values in their source order. Decide outcome_name, instrument, timepoint, "
        "comparison, analysis_set and record_role from the current row only. A row with no numeric "
        "clinical result may be acknowledged as non_outcome. Never guess, combine rows, use Gold, "
        "or impose a maximum outcome count. Return JSON only."
    ),
    "field_boundaries": (
        "row_id=copy exactly; outcome_name=endpoint; instrument=scale/test or NR; "
        "timepoint=exact time or change label; comparison=explicit contrast; "
        "analysis_set=ITT/FAS/PP/PPS/LOCF/MMRM or NR; record_role=primary|secondary|safety|subgroup|sensitivity|baseline|other|NR; "
        "arms=every named arm with explicit n/value/sd/change; p_value_cells=every P column with its header/raw comparator; "
        "source_values=all exact numeric/effect/P/CI strings; "
        "source_evidence=one short verbatim quote; row_decisions=one outcome/non_outcome decision for every input ROW_ID."
    ),
    "json_template": (
        "{outcomes:[{row_id,outcome_name,instrument,timepoint,comparison,analysis_set,record_role,"
        "arms:[{label,role,n,value,sd,change}],p_value_cells[],source_values[],p_value,p_value_comparator,effect_estimate,"
        "confidence_interval,source_evidence,derived,derivation}],row_decisions:[{row_id,status,reason}]}"
    ),
}


OUTCOME_POSTPROCESS_PROMPT_SPEC = {
    "role_definition": (
        "你是一名医学 RCT 论文统计结局后处理专家和数据质量审计者。"
        "你负责在原始逐行抽取完成后整理结局身份、时间点和比较关系，并把候选与人工金标准的差异标记出来。"
    ),
    "task_description": (
        "输入包含已完成的候选 outcomes 数组、每条记录的原文证据和 Sheet3 金标准参考行。"
        "逐条处理所有候选记录，不得设置条数上限，不得删除、合并或改写候选记录中的任何原始数值、n、置信区间、P值或证据。"
        "source_outcome 是唯一的原始事实层；规范化字段只能作为独立注释，不能替代 source_outcome。"
        "只能通过 source_index 指向原始记录，并新增 normalized_outcome_name、normalized_measurement_instrument、"
        "normalized_timepoint、comparison_relation、duplicate_group 和金标准比较标记。"
        "金标准仅用于比较和标记，绝不能用来填补候选缺失值或把候选值改成金标准值。"
        "如果候选与金标准在结局、工具、时间点、组别、样本量、效应量或P值上有冲突，必须 conflict_status=conflict，"
        "列出 conflict_fields 和可核查的简短原因；若证据不足以判断，使用 unresolved。"
        "若同一候选记录只是重复表格副本，给出相同 duplicate_group，但仍为每条原始记录输出一条决定。"
        "允许从该候选行及其证据做唯一可复算的名称、单位或时间规范化；若依赖常识、跨行补值或存在多种解释，必须使用 NR/unresolved，禁止猜测。"
        "所有 source_index 必须逐字覆盖输入候选；缺少任意索引的响应视为不完整并重试。"
        "只输出 JSON。"
    ),
    "field_boundaries": {
        "source_index": "候选 outcomes 数组中的零基索引；必须逐字复制输入索引",
        "normalized_outcome_name": "只根据候选行和原文证据整理结局名称，不加入工具、时间点或数值",
        "normalized_measurement_instrument": "只整理原文明确的量表、问卷、测试或测量工具；没有证据为NR",
        "normalized_timepoint": "只整理该记录自己的原文时间点，不跨行借用；没有证据为NR",
        "comparison_relation": "明确干预/对照/第三臂或组间比较；无法判断为NR",
        "duplicate_group": "同一来源行或完全相同数值的重复记录使用稳定字符串标识，否则为null",
        "gold_row_ids": "与候选最可能对应的金标准行ID；必须逐字复制输入 gold_reference_rows 中的 gold_row_id（不是 column_1/STUDYID）；不确定时为空数组",
        "conflict_status": "none=无可见冲突；conflict=与金标准有冲突；unresolved=证据不足；not_checked=无金标准",
        "conflict_fields": "发生冲突的字段名，例如 outcome_name、timepoint、arm、n、effect、p_value",
        "conflict_reason": "简短、可核查的冲突说明；不得提出未经证据支持的修正值",
        "annotation_status": "none|conflict|unresolved|not_checked；仅描述注释状态，不改变 source_outcome",
    },
    "gold_reference_legend": {
        "column_1": "Sheet3 文章/结局行的 legacy 行标识；不是稳定的 gold_row_id",
        "STUDYID": "研究内部编号",
        "OUTCOM": "金标准结局名称",
        "INSTRU": "金标准测量工具",
        "FOLTIM/FOLTIMN/FOLTIMU": "随访/观察时间点原文、数值和单位编码",
        "PVALNUM/PVALRAG": "P 值数值及其范围编码",
        "B* / E* / F*": "基线、主要结束时点和随访时点的组内统计区；I/C 分别对应干预/对照，DEST 及其 L/U 为组间效应和区间",
        "BOR/BRR/BRD/BHR 及 EOR/ERR/ERD/EHR": "对应时点的 OR/RR/RD/HR 组间效应及其区间",
    },
    "json_template": {
        "records": [{
            "source_index": 0,
            "normalized_outcome_name": "NR",
            "normalized_measurement_instrument": "NR",
            "normalized_timepoint": "NR",
            "comparison_relation": "NR",
            "duplicate_group": None,
            "gold_row_ids": [],
            "conflict_status": "unresolved",
            "annotation_status": "unresolved",
            "conflict_fields": [],
            "conflict_reason": "",
        }],
        "notes": [],
    },
}


FLOW_PROMPT_SPEC = {
    "role_definition": ROLE_DEFINITION + " 你具备医学图像文字理解能力，只能依据图像中清晰可见的信息作答。",
    "task_description": """从 CONSORT 流程图图像提取受试者流转数据，保持各随机组和分支独立。不得推断模糊或遮挡数字；区分 screened、excluded、randomized、allocated、received、followed up、analyzed 和 dropout。dropout_n 只记录图中明确写为 withdrew、lost from trial 或 dropout 的试验退出人数，绝不能把T1/T2/T3各阶段的missing follow-up人数累加为总dropout；这些阶段性缺失应写入other_missing_data。received_n不能写入randomized_n，随访完成数不能写入analyzed_n；保留图中原始时间点标签；把每个原因关联到正确组别和阶段。""",
    "field_boundaries": {
        "screened_n": "进入筛选或最终资格评估人数",
        "randomized_n": "全试验随机总人数",
        "arms[].randomized_n": "分配到该组的人数",
        "arms[].received_n": "实际接受该组干预的人数",
        "arms[].analyzed_n": "明确纳入统计分析的人数",
        "arms[].dropout_n/reasons": "脱落人数、阶段和原因",
        "arms[].follow_up_completed_n": "原始时间点标签到完成随访人数的映射",
        "arms[].other_missing_data": "其他缺失事件",
        "evidence": "图中可见逐字证据，source 固定为 figure",
    },
    "json_template": {"screened_n": None, "randomized_n": None, "arms": [], "evidence": []},
}
