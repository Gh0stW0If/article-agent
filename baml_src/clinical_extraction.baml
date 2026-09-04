// Optional BAML contract for the clinical RCT extraction modules.
//
// The generated client is loaded only when ARTICLE_AGENT_BAML_CLIENT_MODULE is
// configured.  Pydantic remains the validation boundary so BAML and the
// existing OpenAI-compatible provider produce the same wire contract.

enum EvidenceSource {
  Markdown @alias("markdown")
  Table @alias("table")
  Figure @alias("figure")
  Crossref @alias("crossref")
}

enum EvidenceSupportType {
  Direct @alias("direct")
  Derived @alias("derived")
}

class EvidenceQuote {
  field_id string
  quote string
  page int?
  source EvidenceSource
  support_type EvidenceSupportType
  derivation string?
}

class Arm {
  arm_id string
  arm_label string
  role string
  n int?
  estimate float?
  lower float?
  upper float?
  event_count int?
}

class Comparison {
  relation string
  intervention_arm_id string
  control_arm_id string
  comparator_arm_ids string[]
  contrast string
}

class ClinicalOutcome {
  table_id string
  row_id string
  outcome_name string
  measurement_instrument string
  outcome_observation_timepoint_raw string
  outcome_observation_timepoint_value float?
  outcome_observation_timepoint_unit int?
  statistic_type string
  analysis_population string
  intervention_estimate float?
  intervention_variance_lower float?
  intervention_variance_upper float?
  intervention_n int?
  control_estimate float?
  control_variance_lower float?
  control_variance_upper float?
  control_n int?
  between_group_measure string
  outcome_between_group_estimate float?
  outcome_between_group_lower float?
  outcome_between_group_upper float?
  outcome_p_value float?
  outcome_p_value_comparator string
  effect_size_name string
  arm Arm[]
  comparison Comparison
  analysis_set string
  record_role string
  evidence EvidenceQuote[]
}

class OutcomeExtraction {
  outcomes ClinicalOutcome[]
}

class MetadataExtraction {
  title string
  publication_year int?
  language string
  journal string
  first_author string
  author_contact string
  disease_name string
  country string
  intervention string
  control string
  evidence EvidenceQuote[]
}

class AcupunctureProtocol {
  control_type_transformed int?
  control_type_components int[]
  acupuncture_type int?
  stimulation_type int?
  point_selection_scheme int?
  treatment_frequency_raw string
  treatment_frequency_value float?
  treatment_frequency_unit int?
  treatment_duration_raw string
  treatment_duration_value float?
  treatment_duration_unit int?
  total_sessions int?
  deqi int
  needle_depth_raw string
  retention_time_raw string
  retention_time_value float?
  practitioner_experience_years float?
  practitioner_experience_raw string
  practitioner_experience_comparator string
  evidence EvidenceQuote[]
}

class RiskOfBiasExtraction {
  random_sequence_method string
  random_sequence_class int
  allocation_concealment string
  allocation_concealment_class int
  participant_blinding int
  outcome_assessor_blinding int
  randomized_sample_intervention_raw int?
  randomized_sample_control_raw int?
  total_randomized int?
  primary_analysis int
  missing_data_method int
  evidence EvidenceQuote[]
}

function ExtractClinicalOutcomes(source_context: string) -> OutcomeExtraction {
  client GPT4o
  prompt #"
  You are a medical RCT clinical-outcome extraction expert. Extract every
  evidence-bearing row from the supplied table context. Preserve table_id and
  row_id, never guess missing values, and return the exact structured object
  below. An evidence-supported deterministic derivation is allowed, but a
  guess is forbidden. Keep separate arms, comparisons, analysis sets and
  record roles; do not collapse conflicting records.
  {{ source_context }}

  {{ ctx.output_format }}
  "#
}

function ExtractMetadata(source_context: string) -> MetadataExtraction {
  client GPT4o
  prompt #"
  You are a medical RCT metadata extraction expert. Use only the supplied
  title, abstract, introduction, DOI/citation and front-matter evidence.
  Return NR/null when a field is not reported. Do not infer country from an
  author's affiliation unless the study setting itself supports it. Return
  the exact structured object below.
  {{ source_context }}

  {{ ctx.output_format }}
  "#
}

function ExtractAcupuncture(source_context: string) -> AcupunctureProtocol {
  client GPT4o
  prompt #"
  You are a medical RCT acupuncture intervention extraction expert. Use only
  the supplied Methods evidence. Distinguish raw wording from coded values,
  permit only evidence-supported deterministic derivation, and never guess.
  Return the exact structured object below.
  {{ source_context }}

  {{ ctx.output_format }}
  "#
}

function ExtractRiskOfBias(source_context: string) -> RiskOfBiasExtraction {
  client GPT4o
  prompt #"
  You are a medical RCT risk-of-bias extraction expert. Use only the supplied
  Methods evidence. Separate random-sequence generation, allocation
  concealment, blinding, analysis population and missing-data handling. Do
  not treat an unreported method as negative evidence. Return the exact
  structured object below.
  {{ source_context }}

  {{ ctx.output_format }}
  "#
}
