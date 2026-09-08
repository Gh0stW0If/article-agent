"""Run PR4.1 source normalization then the unchanged PR4 canonicalizer."""
from pathlib import Path
import json, html
from article_agent.outcome_source_normalizer import normalize_outcome_sources
from article_agent.outcome_canonicalizer import canonicalize_outcomes
from article_agent.domain import ArticleExtraction

def warning_counts(warnings):
 counts=dict.fromkeys(("ARM_BINDING","OUTCOME_IDENTITY","COMPARISON_SCOPE","STATISTIC_SCOPE"),0)
 for warning in warnings:
  w=warning.lower()
  if "arm binding" in w or "arm observation" in w: category="ARM_BINDING"
  elif "comparison participants" in w or "comparison source" in w: category="COMPARISON_SCOPE"
  elif "statistic" in w or "p/effect" in w: category="STATISTIC_SCOPE"
  elif "evidence" in w or "deriv" in w or "invalid" in w: continue
  elif "outcome" in w or "instrument" in w or "identity" in w: category="OUTCOME_IDENTITY"
  else: continue
  counts[category]+=1
 return counts

ROOT=Path("outputs/pr4_offline_acceptance_2015_v1"); OUT=Path("outputs/pr4_1_offline_acceptance_2015_v1")
OUT.mkdir(parents=True,exist_ok=True)
def main():
 results=[]
 for p in sorted(ROOT.glob("20*/ACCEPTANCE.json")):
  aid=p.parent.name; old=json.loads(p.read_text(encoding="utf-8"))
  t=json.loads(Path(old["input_paths"]["topology"]).read_text(encoding="utf-8")); g0=json.loads(Path(old["input_paths"]["arm_graph"]).read_text(encoding="utf-8"))
  raw=json.loads((Path("outputs/mineru_method_lossless_sol_luna_v5")/aid/"extraction.json").read_text(encoding="utf-8"))["outcomes"]["outcomes"]
  norm,nr=normalize_outcome_sources(aid,t,raw); g=canonicalize_outcomes(aid,t,g0,norm)
  baseline=canonicalize_outcomes(aid,t,g0,raw)
  assert ArticleExtraction.model_validate_json(g.model_dump_json())==g
  assert [n["_pr41_original"] for n in norm]==raw
  assert g.arms==baseline.arms and g.interventions==baseline.interventions
  before={"Outcome":len(baseline.outcomes),**warning_counts(baseline.adapter_warnings)}
  after={"Outcome":len(g.outcomes),**warning_counts(g.adapter_warnings)}
  item={"article_id":aid,"before":before,"after":after,"delta":{k:after[k]-before[k] for k in before},"normalization_counters":nr["counters"],"normalizer_warning_count":len(nr["warnings"]),"canonical_counts":{"ArmResult":len(g.arm_results),"Comparison":len(g.comparisons),"ComparisonResult":len(g.comparison_results)},"raw_record_preserved":True,"canonical_revalidated":True,"canonicalizer_unchanged":True}
  (OUT/aid).mkdir(exist_ok=True);(OUT/aid/"normalized_source_records.json").write_text(json.dumps(norm,ensure_ascii=False,indent=2),encoding="utf-8");(OUT/aid/"canonical.json").write_text(g.model_dump_json(indent=2),encoding="utf-8");results.append(item)
 summary={"mode":"offline_pr4_1_then_pr4","warning_metric":"both sides use PR4 canonicalizer warnings with identical exclusive classification; normalizer warnings are separate","api_called":False,"gold_used":False,"canonicalizer_modified":False,"articles":results};(OUT/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
 rows="".join(f"<tr><td>{x['article_id']}</td><td>{x['before']['ARM_BINDING']} → {x['after']['ARM_BINDING']} ({x['delta']['ARM_BINDING']:+d})</td><td>{x['before']['OUTCOME_IDENTITY']} → {x['after']['OUTCOME_IDENTITY']} ({x['delta']['OUTCOME_IDENTITY']:+d})</td><td>{x['before']['COMPARISON_SCOPE']} → {x['after']['COMPARISON_SCOPE']} ({x['delta']['COMPARISON_SCOPE']:+d})</td><td>{x['before']['STATISTIC_SCOPE']} → {x['after']['STATISTIC_SCOPE']} ({x['delta']['STATISTIC_SCOPE']:+d})</td><td>{x['normalization_counters']}</td></tr>" for x in results)
 body="<h1>PR4.1 offline acceptance</h1><p>Source semantics normalization followed by unchanged PR4 canonicalizer. No API or Gold.</p><table><tr><th>Article</th><th>ARM_BINDING before→after Δ</th><th>OUTCOME_IDENTITY before→after Δ</th><th>COMPARISON_SCOPE before→after Δ</th><th>STATISTIC_SCOPE before→after Δ</th><th>Normalization counters</th></tr>"+rows+"</table>"
 (OUT/"REPORT.html").write_text("<html><meta charset='utf-8'><style>body{font:15px system-ui;margin:30px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd;padding:7px}</style>"+body+"</html>",encoding="utf-8")
if __name__=="__main__": main()
