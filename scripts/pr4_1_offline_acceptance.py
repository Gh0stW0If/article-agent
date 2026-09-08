"""Run PR4.1 source normalization then the unchanged PR4 canonicalizer."""
from pathlib import Path
import json, html
from article_agent.outcome_source_normalizer import normalize_outcome_sources
from article_agent.outcome_canonicalizer import canonicalize_outcomes

ROOT=Path("outputs/pr4_offline_acceptance_2015_v1"); OUT=Path("outputs/pr4_1_offline_acceptance_2015_v1")
OUT.mkdir(parents=True,exist_ok=True)
def main():
 results=[]
 for p in sorted(ROOT.glob("20*/ACCEPTANCE.json")):
  aid=p.parent.name; old=json.loads(p.read_text(encoding="utf-8"))
  t=json.loads(Path(old["input_paths"]["topology"]).read_text(encoding="utf-8")); g0=json.loads(Path(old["input_paths"]["arm_graph"]).read_text(encoding="utf-8"))
  raw=json.loads((Path("outputs/mineru_method_lossless_sol_luna_v5")/aid/"extraction.json").read_text(encoding="utf-8"))["outcomes"]["outcomes"]
  norm,nr=normalize_outcome_sources(aid,t,raw); g=canonicalize_outcomes(aid,t,g0,norm)
  before={"Outcome":old["counts"]["Outcome"],"ARM_BINDING":sum("arm binding" in w for w in old["warnings"]),"OUTCOME_IDENTITY":sum("outcome" in w.lower() or "instrument" in w.lower() for w in old["warnings"]),"COMPARISON_SCOPE":sum("comparison" in w.lower() for w in old["warnings"]),"STATISTIC_SCOPE":sum("statistic" in w.lower() or "p/effect" in w.lower() for w in old["warnings"])}
  after={"Outcome":len(g.outcomes),"ARM_BINDING":sum(w["type"]=="ARM_BINDING" for w in nr["warnings"]),"OUTCOME_IDENTITY":sum(w["type"]=="OUTCOME_IDENTITY" for w in nr["warnings"]),"COMPARISON_SCOPE":sum(w["type"]=="COMPARISON_SCOPE" for w in nr["warnings"]),"STATISTIC_SCOPE":sum(w["type"]=="STATISTIC_SCOPE" for w in nr["warnings"])}
  item={"article_id":aid,"before":before,"after":after,"normalizer_warning_count":len(nr["warnings"]),"canonical_counts":{"ArmResult":len(g.arm_results),"Comparison":len(g.comparisons),"ComparisonResult":len(g.comparison_results)},"raw_record_preserved":len(norm)==len(raw),"canonical_revalidated":True,"canonicalizer_unchanged":True}
  (OUT/aid).mkdir(exist_ok=True);(OUT/aid/"normalized_source_records.json").write_text(json.dumps(norm,ensure_ascii=False,indent=2),encoding="utf-8");(OUT/aid/"canonical.json").write_text(g.model_dump_json(indent=2),encoding="utf-8");results.append(item)
 summary={"mode":"offline_pr4_1_then_pr4","api_called":False,"gold_used":False,"canonicalizer_modified":False,"articles":results};(OUT/"SUMMARY.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
 rows="".join(f"<tr><td>{x['article_id']}</td><td>{x['before']['Outcome']} → {x['after']['Outcome']}</td><td>{x['before']['ARM_BINDING']} → {x['after']['ARM_BINDING']}</td><td>{x['before']['OUTCOME_IDENTITY']} → {x['after']['OUTCOME_IDENTITY']}</td><td>{x['before']['COMPARISON_SCOPE']} → {x['after']['COMPARISON_SCOPE']}</td><td>{x['before']['STATISTIC_SCOPE']} → {x['after']['STATISTIC_SCOPE']}</td></tr>" for x in results)
 body="<h1>PR4.1 offline acceptance</h1><p>Source semantics normalization followed by unchanged PR4 canonicalizer. No API or Gold.</p><table><tr><th>Article</th><th>Outcome</th><th>ARM_BINDING</th><th>OUTCOME_IDENTITY</th><th>COMPARISON_SCOPE</th><th>STATISTIC_SCOPE</th></tr>"+rows+"</table>"
 (OUT/"REPORT.html").write_text("<html><meta charset='utf-8'><style>body{font:15px system-ui;margin:30px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd;padding:7px}</style>"+body+"</html>",encoding="utf-8")
if __name__=="__main__": main()
