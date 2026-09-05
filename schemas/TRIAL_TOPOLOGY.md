# PR2: trial topology

`article_agent.trial_topology_agent` identifies randomized study arms before
intervention protocol, sample flow and outcomes. Its Pydantic output is:

```json
{
  "number_of_arms": 3,
  "arms": [{
    "source_label": "Group A",
    "name": "complete arm name including shared treatment",
    "role": null,
    "aliases": [],
    "evidence": [{"source_id": "article", "quote": "verbatim allocation passage", "arm_text": "arm-specific phrase"}]
  }]
}
```

The example shows one arm's shape; a valid response must contain all three arms
when `number_of_arms` is 3. There is no upper arm-count limit. Disease strata,
timepoints, analysis sets, treatment components and other cited trials are not
arms. Role is optional, and multiple arms can have the same role. No LLM ID fields
are accepted. The four prompt sections live in `TOPOLOGY_PROMPT`.

The complete Markdown is sent without character slicing. Each quote and arm
anchor must exist in the supplied source (only whitespace variation is allowed).
The returned list is sorted by input source order and the arm anchor's position
in the source. The resulting persisted topology order is authoritative. IDs are
generated in Python as `<article_id>-S1-A01`, `A02`, etc. Renaming a display label
does not change IDs; discovering a genuinely new earlier arm can change later
IDs, so topology should be frozen before downstream extraction.

`topology_to_canonical()` returns one Article, one Study and all topology Arms.
The labels/available roles have reciprocal EvidenceTargets. Counts remain
UNRESOLVED and protocol links/results/comparisons are empty. No C(n,2) expansion
is performed. A failure is explicit; it never silently defaults to two arms.

## Integration and compatibility

MinerU `run_experiment()` calls topology immediately after creating the API
client, before metadata/protocol/outcome extraction. It writes:

- `trial_topology/trial_topology.json`
- `trial_topology/trial_topology.canonical.json` (topology-only graph)
- `trial_topology/topology.manifest.json` and complete request/response attempts

The original `extraction.json` is unchanged. A full outcome/result migration is
not published automatically by this topology-only stage.

`legacy_bundle_to_canonical(bundle, topology=topology)` uses these exact Arms.
This remains an explicit compatibility projection, not the default pipeline
output, because existing outcome aliases may need later semantic reconciliation.
Existing source labels/aliases must match unambiguously; roles and row ordering
do not establish identity. Unknown/ambiguous legacy labels are preserved in raw
outcome projections and adapter warnings; they are not fabricated into new arms
or converted to results with dangling IDs. Arm protocol links and counts remain
deferred. Existing explicitly reported comparison records may be projected;
topology itself does not discover comparisons or generate pairs.

The one-argument adapter remains a legacy compatibility entry point and cannot
claim authoritative topology from incomplete pair-oriented metadata. It now
generates ordinal, rather than name-derived, Arm IDs. Use the topology argument
or topology CLI for the new semantics. The old MVP `article-agent run` path is a
separate legacy workflow; this PR integrates the MinerU workflow and a dedicated
Markdown topology CLI, not a migration of every historical runner.

Remaining two-slot constructs are explicitly outside PR2: the legacy
metadata/risk spreadsheet fields, `_reconcile_risk_with_flow` in MinerU pipeline,
the two-slot cross-check in `mineru_method/flow.py`, and legacy result/comparison
projections. They are compatibility boundaries, not topology identity rules.
Arm-to-intervention components and sample flow remain future work.

## Run only topology on saved Markdown

```powershell
D:\Application\Anaconda\envs\Agent\python.exe -m article_agent.trial_topology_agent --article-id 2015-06 --markdown outputs/mineru_method_lossless_sol_luna_v5/2015-06/article.md --output-dir outputs/pr2_trial_topology/2015-06
```

This makes API calls with the configured credentials and URL failover. The
topology model defaults to `gpt-5.6-luna` and can be set with
`ARTICLE_AGENT_TOPOLOGY_MODEL` or the standalone `--model` option. Requests are
serial with 10 ms spacing. Invalid responses retry with validation feedback;
quota/authentication failures do not produce a fallback topology. No Gold is an
input. Runtime artifacts and source papers remain ignored by Git.

Offline tests use synthetic allocation passages. Private-source verification
must be reported separately from online model extraction. The source-checked
2015 batch has counts 2, 2, 2, 3, 3, 3: 2015-04 and 2015-05 are also explicitly
three-arm studies. Do not enforce a two-arm expectation on those documents.
