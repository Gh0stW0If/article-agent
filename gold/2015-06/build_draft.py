"""Reproduce the independently PDF-reviewed FROZEN Gold; never reads predictions.

Annotation values below were transcribed from the seven-page primary article.
This is a document-specific authoring file, not an extraction pipeline.
The historical filename is retained for compatibility.
"""
import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys
from article_agent.domain import models as dm
from article_agent.evaluation import GoldStandardV2

ROOT = Path(__file__).resolve().parents[2]
PDF = ROOT / "datas/articles/2015/-2015-06.pdf"
WORKBOOK = ROOT / "datas/label/2015-6篇.xlsx"
SID = "2015-06-S1"
ARMS = [SID + f"-A{i:02}" for i in (1, 2, 3)]
SOURCE = "2015-06-article"
LABELS = ["CIC treatment", "EA combined with CIC treatment", "sham acupuncture combined with CIC treatment"]
ROWS = [
    ("bladder-balance", 1, None, ["21 (60.0)", "29 (85.29)", "23 (60.5)"], ["0.019", "0.963", "0.019"]),
    ("cic-frequency", 2, None, ["1.7±0.14", "0.35±0.07", "1.35±0.21"], ["<0.001", "<0.01", "<0.001"]),
    ("residual-1-month", 3, 1, ["301.0±8.48", "213.0±9.19", "295.0±9.89"], ["<0.001", "0.018", "<0.001"]),
    ("voided-1-month", 4, 1, ["271.5±12.06", "375.5±10.06", "276.5±9.09"], ["<0.001", "0.107", "<0.001"]),
    ("residual-3-months", 3, 3, ["193.5±10.6", "113.5±12.02", "176.5±9.19"], ["<0.001", "<0.001", "<0.001"]),
    ("voided-3-months", 4, 3, ["360.0±14.14", "471.0±10.4", "382.5±10.2"], ["<0.001", "<0.001", "<0.001"]),
]
ROW_NAMES = [
    "The number of bladder balance patients (n, %)*", "CIC frequency (times/day)",
    "Residual urine volume (ml) in the 1st month", "Voided volume (ml) in the 1st month",
    "Residual urine volume (ml) in the 3rd month", "Voided volume (ml) in the 3rd month",
]
BASELINE = ["566.0±8.9", "591.0±9.4", "575.0±10.5"]
PAIRS = [(0, 1), (0, 2), (1, 2)]


def build():
    evidence, notes, reasons = [], [], {}
    entities = []

    def entity(cls, id_value, **refs):
        idf = {"Article": "article_id", "Study": "study_id", "Arm": "arm_id",
               "Intervention": "intervention_id", "Outcome": "outcome_id",
               "ArmResult": "arm_result_id", "Comparison": "comparison_id",
               "ComparisonResult": "comparison_result_id"}[cls.__name__]
        item = cls(**{idf: id_value}, **refs).model_dump(mode="json")
        entities.append((cls.__name__, id_value, item))
        # Every default is explicitly adjudicated below; unresolved defaults fail build.
        return item

    def absence(item, field, reason, status="NOT_REPORTED"):
        item[field] = {"status": status, "value": None}
        reasons[(id(item), field)] = reason

    def na(item, fields, reason):
        for field in fields.split():
            absence(item, field, reason, "NOT_APPLICABLE")

    def review(item, field, reason, quote=None, page=4):
        absence(item, field, reason, "REVIEW_REQUIRED")
        if quote:
            item[field]["raw_value"] = quote
            item[field]["evidence_ids"] = [ev(item, field, quote, page)]

    def ev(item, field, quote, page, section=None, table=None, row=None, cell=None, derivation=None):
        kind, eid, _ = next(x for x in entities if x[2] is item)
        evidence_id = f"E{len(evidence)+1:04}"
        evidence.append({
            "evidence_id": evidence_id, "source_id": SOURCE, "source_type": "table" if table else "markdown",
            "page": page, "section": section or ("Tables" if table else "Article"),
            "table_id": table, "row_id": row, "cell_refs": [cell] if cell else [],
            "quote": quote, "targets": [{"entity_type": kind, "entity_id": eid, "field_id": field}],
            "support_type": "derived" if derivation else "direct", "derivation": derivation,
        })
        return evidence_id

    def put(item, field, value, quote, page, **location):
        item[field] = {"status": "PRESENT", "value": value, "raw_value": quote,
                       "evidence_ids": [ev(item, field, quote, page, **location)]}

    def nr(item, fields, reason):
        for field in fields.split():
            absence(item, field, reason)

    title = ("Effects of electroacupuncture combined with clean intermittent catheterization on urinary retention "
             "after spinal cord injury: a single blind randomized controlled clinical trial")
    article = entity(dm.Article, "2015-06")
    put(article, "title", title, title, 1)
    put(article, "publication_year", 2015, "Int J Clin Exp Med 2015;8(10):19757-19763", 1)
    put(article, "journal", "Int J Clin Exp Med", "Int J Clin Exp Med", 1)
    put(article, "language", "English", title, 1, derivation="Language identification from English title and full article; not an explicitly labelled language field.")
    authors = ["Xu-Dong Gu", "Jing Wang", "Peng Yu", "Jian-Hua Li", "Yun-Hai Yao", "Jian-Ming Fu",
               "Zhong-Li Wang", "Ming Zeng", "Liang Li", "Ming Shi", "Wen-Ping Pan"]
    put(article, "authors", authors,
        "Xu-Dong Gu1*, Jing Wang1,4*, Peng Yu2, Jian-Hua Li3, Yun-Hai Yao1, Jian-Ming Fu1, Zhong-Li Wang1, Ming Zeng1, Liang Li1, Ming Shi1, Wen-Ping Pan1",
        1, derivation="Remove affiliation superscripts and co-first-author markers; retain printed author order.")
    correspondence = ("Address correspondence to: Dr. Jing Wang, Department of Rehabilitation Medicine, Second Hospital, "
                      "Jiaxing University, Jiaxing 314000, China. Tel: +86-57382971932; Fax: +86-57382971932; E-mail: jingwangjw1@163.com")
    put(article, "correspondence", [correspondence], correspondence, 5)
    nr(article, "doi", "Reviewed title/metadata, all seven pages, footers and references: no DOI identifying this article is printed. IJCEM0013465 is a manuscript identifier, not a DOI.")
    study = entity(dm.Study, SID, article_id="2015-06", arm_ids=ARMS,
                   intervention_ids=[SID+f"-I{i:02}" for i in (1,2,3)], outcome_ids=[SID+f"-O{i:02}" for i in (1,2,3,4)])
    put(study, "design", "single blind, randomized, controlled clinical trial",
        "This study was a single blind, randomized, controlled clinical trial", 2, section="Methods")
    put(study, "condition", "urinary retention after spinal cord injury", "urinary retention (residual urine volume > 100 ml) after SCI", 2)
    put(study, "countries", ["China"], "A total of 107 Chinese patients", 2)
    study["countries"]["evidence_ids"].append(ev(study, "countries",
        "Second Hospital, Jiaxing University, Jiaxing 314000, China.", 5, section="Correspondence"))
    put(study, "randomized_n", 107, "A total of 107 patients with SCI induced urinary retention were randomly divided into 3 groups", 1)
    review(study, "centre_count", "Methods gives one recruiting hospital; Acknowledgements names two hospitals where the study was finished. Centre definition requires review; no explicit contradictory centre counts.",
           "We thank Second Hospital Affiliated Jiaxing University and Sir Runrun Hospital of Zhejiang University where the study was finished.", 5)
    study["centre_count"]["evidence_ids"].append(ev(study,"centre_count",
        "which was performed in the Department of Rehabilitation Medicine, Affiliated Second Hospital of Jiaxing University",2))
    put(study, "random_sequence_method", "computer-generated list", "based on the computer-generated list", 2)
    put(study, "random_sequence_code", 2, "based on the computer-generated list", 2,
        derivation="Existing coding contract (legacy workbook Sheet1 AD1: 2=计算机随机; canonical adapter random_sequence_class preserves code 2) maps computer-generated list to 2. Article does not print the code.")
    nr(study, "allocation_concealment allocation_concealment_code",
       "Full article including Methods randomization paragraph reports sequence generation only, no allocation concealment. Canonical legacy adapter excludes NR code 5 from present codes; retain NOT_REPORTED, not a numeric source observation.")
    review(study, "participant_blinding", "Source says single blind and describes a mock device to facilitate blinding, but does not explicitly identify the blinded party.",
           "To facilitate blinding, a mock EA therapeutic instrument, emitted a sound and a blinking light, was attached to the needles", 3)
    for field, party in (("practitioner_blinding", "treating practitioners"),
                         ("outcome_assessor_blinding", "outcome assessors"),
                         ("statistician_blinding", "statisticians")):
        nr(study, field, f"Human-reviewed NOT_REPORTED: full article, including Methods treatment/blinding paragraphs, outcome measurements and statistical analysis, does not explicitly report blinding of {party}. The single-blind label and mock-device description do not identify this party as blinded; no role inference is made.")
    nr(study, "primary_analysis_set missing_data_method",
       "Reviewed Methods/statistical analysis, Results, Discussion and all seven pages: no ITT, per-protocol, complete-case or imputation statement. ANOVA/Tukey/Bonferroni describe tests, not analysis set or missing-data handling.")
    arms = []
    for i, label in enumerate(LABELS):
        arm = entity(dm.Arm, ARMS[i], study_id=SID,
                     intervention_ids=[[SID+"-I01"],[SID+"-I02",SID+"-I01"],[SID+"-I03",SID+"-I01"]][i])
        arms.append(arm)
        arm["legacy_fields"]["source_label"] = f"Group {i+1}"
        put(arm, "label", label, f"group {i+1} ({label}", 2)
        put(arm, "role", ["active_control","experimental","sham_control"][i], f"group {i+1} ({label}", 2,
            derivation="Role annotation from explicitly described CIC, EA+CIC and sham+CIC treatment contrasts; does not establish blinding or identity.")
        if i == 0:
            put(arm, "randomized_n", 35, "group 1 (CIC treatment, n=35", 2)
            arm["randomized_n"]["evidence_ids"].append(ev(arm,"randomized_n","Group 1 (n=35)",4,table="Table 1",row="header",cell="Group 1"))
        else:
            candidates = []
            for n, page, quote, loc in [
                ([35,38,34][i],2,f"group {i+1} ({label}, n={[35,38,34][i]}",{"section":"Methods / Treatment methods"}),
                ([35,34,38][i],4,f"Group {i+1} (n={[35,34,38][i]})",{"table":"Table 1","row":"header","cell":f"Group {i+1}"})]:
                candidates.append({"value":n,"raw_value":quote,"evidence_ids":[ev(arm,"randomized_n",quote,page,**loc)]})
            arm["randomized_n"]={"status":"SOURCE_CONFLICT","value":None,"raw_value":"Methods versus Table 1",
                "evidence_ids":[e for c in candidates for e in c["evidence_ids"]],"conflict_candidates":candidates}
        nr(arm,"received_n analyzed_n dropout_n","Full article/Results/Tables/Figures reviewed: no explicit arm-specific received, analyzed or dropout counts. Table 1 n and Table 2 percentages are not flow counts; no zero-dropout assumption.")
    interventions = []
    names = ["Clean intermittent catheterization", "Electroacupuncture", "Sham acupuncture"]
    cic = ("Before catheter placement, behavioral interventions (such as fluid schedules and regular voiding attempts) were firstly performed to induce emiction.")
    ea = ("filiform needles (0.38 mm in diameter and 5 cm in length)")
    sham = ("the needle was just taping to the dermal surface of BL 31-34 by an adhesive tap without insertion")
    for i,name in enumerate(names):
        item = entity(dm.Intervention,SID+f"-I{i+1:02}",study_id=SID); interventions.append(item)
        put(item,"name",name,["Clean intermittent catheterization (CIC)","electroacupuncture (EA)","Sham acupuncture combined with CIC treatment"][i], [2,1,3][i])
        put(item,"kind",["catheterization","electroacupuncture","non-penetrating sham acupuncture"][i],[cic,ea,sham][i],[2,2,3][i],
            derivation="Treatment category normalized from the stated procedure; no additional intervention entity.")
        put(item,"duration_raw","3 months","These treatments lasted for 3 months.",2)
        put(item,"duration_value",3,"These treatments lasted for 3 months.",2,derivation="Split explicitly reported duration into numeric value and unit.")
        put(item,"duration_unit","months","These treatments lasted for 3 months.",2,derivation="Split explicitly reported duration into numeric value and unit.")
        if i==0:
            put(item,"description","CIC includes fluid schedules and regular voiding attempts, equipment preparation, cleaning, lubrication, gentle catheter insertion and advancement, drainage until empty, removal and urine-volume recording.",cic,2,
                derivation="Concise annotation of CIC treatment paragraph on page 2; procedural steps remain part of CIC.")
            item["description"]["evidence_ids"].append(ev(item,"description",
                "(1) Assembling all equipments, including catheter, lubricant, and drainage receptacle (container); (2) Cleaning the penis/vulva of patients, and then opening urethra; (3) Lubricating the catheter; (4) Inserting and advancing the catheter gently; (5) Continuing to advance the catheter for another 1 inch once the urine flow starts and holding it in place until the urine flow stops and the bladder is empty; (6) Removing the catheter gently to ensure the entire bladder is empty; (7) Recording the volume of urine.",2))
            put(item,"components",["fluid schedules","regular voiding attempts","catheterization"],cic,2,
                derivation="Within-protocol procedural components only; not independent treatment entities.")
            q="The exact frequency of CIC is dependent on fluid intake, bladder capacity and post-void residual urine of patients."
            put(item,"frequency_raw",q,q,2)
            na(item,"frequency_value frequency_unit","Adaptive CIC protocol has no fixed treatment frequency; this is not the CIC-frequency outcome.")
            nr(item,"total_sessions","No total catheterizations reported in Methods or full text; individualized frequency prevents a fixed total.")
        elif i==1:
            description="Bilateral BL31–BL34; 0.38 mm × 5 cm filiform needles, 3 cm depth, twirling/rotating, De-qi; BL31 and BL34 connected to SDZ-II, 20 min, 20 Hz; followed by CIC."
            put(item,"description",description,ea,2,derivation="Protocol summary from EA treatment paragraphs on pages 2–3.")
            for quote,page in [("for 3 cm after routine sterilization",2),("twirling and rotating. When the De-qi occurred",3),("and lasted for 20 min with pulse frequency of 20 Hz",3)]:
                item["description"]["evidence_ids"].append(ev(item,"description",quote,page))
            put(item,"components",["Bilateral BL31–BL34 needling","De-qi","20 Hz electrical stimulation for 20 min"],"and lasted for 20 min with pulse frequency of 20 Hz",3,
                derivation="Within-EA procedure summary; see linked full protocol description and pages 2–3.")
            for field in ("description","components"):
                item[field]["evidence_ids"].append(ev(item,field,
                    "the needles in the acupoints of BL 31 and BL 34 were connected with Electronic Acupuncture Treatment Instrument (SDZ-II, Hwato, China)",3))
                item[field]["evidence_ids"].append(ev(item,field,
                    "were punctured perpendicularly into Bilateral Baliao (BL) 31-34",2))
            item["components"]["evidence_ids"].append(ev(item,"components","When the De-qi occurred",3))
            put(item,"frequency_raw","once a day","EA was performed on patients in the morning once a day.",2)
            put(item,"frequency_value",1,"once a day",2,derivation="Explicit once/day parsed as value 1 and unit day.")
            put(item,"frequency_unit","day","once a day",2,derivation="Explicit once/day parsed as value 1 and unit day.")
            nr(item,"total_sessions","Human-reviewed NOT_REPORTED: Methods reports EA once/day and a three-month treatment course, but no total session count. Full article contains no explicit total; frequency and calendar months are not converted to sessions.")
        else:
            put(item,"description","Needle taped to BL31–BL34 dermal surface without insertion; mock EA device emits sound/blinking light; same CIC procedure.",sham,3,
                derivation="Summary of sham paragraph; no penetrating acupuncture.")
            item["description"]["evidence_ids"].append(ev(item,"description","a mock EA therapeutic instrument, emitted a sound and a blinking light",3))
            put(item,"components",["surface-taped needle without insertion","mock EA sound and blinking light"],sham,3,
                derivation="Within-sham components from the same paragraph, not separate interventions.")
            item["components"]["evidence_ids"].append(ev(item,"components",
                "a mock EA therapeutic instrument, emitted a sound and a blinking light",3))
            item["description"]["evidence_ids"].append(ev(item,"description",
                "The procedure of CIC was same as described above",3))
            nr(item,"frequency_raw frequency_value frequency_unit","Sham described as based on EA method, without an explicit sham frequency; do not silently copy once/day.")
            nr(item,"total_sessions","Human-reviewed NOT_REPORTED: Methods sham-treatment paragraph and full article report no total sham session count. Do not copy the EA schedule or calculate a count from treatment duration.")
    outcomes = []
    for i,name in enumerate(["Bladder balance","CIC frequency","Residual urine volume","Voided volume"]):
        o=entity(dm.Outcome,SID+f"-O{i+1:02}",study_id=SID); outcomes.append(o)
        put(o,"name",name,ROW_NAMES[[0,1,2,3][i]],4,table="Table 2",row=ROWS[[0,1,2,3][i]][0],cell="label")
        nr(o,"role","Full article describes outcome measurements but does not designate primary or secondary outcomes; legacy patient-important label is not a trial-defined hierarchy.")
        na(o,"scale_min scale_max","Not a bounded questionnaire scale; do not invent physiological ranges.")
        if i in (0,1):
            na(o,"instrument","Criteria-defined event/count frequency; no named measurement scale is applicable.")
        else:
            nr(o,"instrument","No named measuring instrument is specified; catheter collection is reported as procedure, not a named calibrated instrument.")
        if i==0:
            na(o,"unit","Event/state endpoint; counts and percent remain in result raw values.")
            q="The bladder was considered to be balanced when (1) adequate urine could be easily discharged at low pressure, (2) approximately 100 ml or less residual urine was left, (3) and no urinary tract infection occurred."
            o["legacy_fields"]["definition"]=q
            put(o,"direction","higher event proportion is better","promoting the balance of vesical function",1,
                derivation="Direction annotated from the stated beneficial conclusion, not a questionnaire code.")
        else:
            put(o,"unit","times/day" if i==1 else "ml",ROW_NAMES[[0,1,2,3][i]],4,table="Table 2",row=ROWS[[0,1,2,3][i]][0],cell="label")
            put(o,"direction","higher is better" if i==3 else "lower is better",
                "reducing residual urine volume and the frequency of CIC, increasing voided volume",1,
                derivation="Direction from the article's therapeutic conclusion.")
    comparisons=[]
    for i,(a,b) in enumerate(PAIRS):
        c=entity(dm.Comparison,SID+f"-C{i+1:02}",study_id=SID,arm_ids=[ARMS[a],ARMS[b]])
        comparisons.append(c)
        q=f"P{i+1}: group {a+1} vs. group {b+1}"
        put(c,"relation","between-group",q,4,table="Table 2",row="footnote",cell=f"P{i+1}",
            derivation="Explicit comparison footnote defines between-group relation and ordered participants.")
        put(c,"contrast",f"Group {a+1} vs Group {b+1}",q,4,table="Table 2",row="footnote",cell=f"P{i+1}")
    arm_results=[]; comparison_results=[]
    def time_fields(item,month,rowname,row):
        if month:
            put(item,"timepoint",f"{month} month" if month==1 else f"{month} months",rowname,4,table="Table 2",row=row,cell="label")
            put(item,"timepoint_value",month,rowname,4,table="Table 2",row=row,cell="label",derivation="Explicit row timepoint split into number and unit.")
            put(item,"timepoint_unit","months",rowname,4,table="Table 2",row=row,cell="label",derivation="Explicit row timepoint split into number and unit.")
        elif row=="bladder-balance":
            nr(item,"timepoint timepoint_value timepoint_unit","Human-reviewed NOT_REPORTED: Table 2 bladder-balance row, caption and footnote do not state a timepoint. Full Methods/Results review provides no uniquely assigned timepoint for these counts or their comparisons. The Results sentence also naming voided volume does not establish a bladder-balance timepoint; do not infer one month or borrow adjacent-row timepoints.")
        else:
            nr(item,"timepoint timepoint_value timepoint_unit","CIC-frequency row has no timepoint; full Results/Methods do not uniquely assign one. Do not assume 3 months.")
    for row_index,(row,oi,month,values,pvalues) in enumerate(ROWS):
        for ai,raw in enumerate(values):
            r=entity(dm.ArmResult,SID+f"-AR{len(arm_results)+1:02}",outcome_id=SID+f"-O{oi:02}",arm_id=ARMS[ai],source_table_id="Table 2",source_row_id=row)
            arm_results.append(r)
            loc=dict(table="Table 2",row=row,cell=f"Group {ai+1}")
            put(r,"raw_value",raw,raw,4,**loc)
            time_fields(r,month,ROW_NAMES[row_index],row)
            nr(r,"analysis_set n","Full article/Table 2 does not specify analysis population or analyzed n for this result. Table 1/Methods randomized counts are not copied into results.")
            if oi==1:
                put(r,"value_kind","event_count",ROW_NAMES[0],4,table="Table 2",row=row,cell="label",derivation="n,% row represents event counts plus percentages, not a continuous mean.")
                put(r,"event_count",int(raw.split()[0]),raw,4,**loc)
                na(r,"value standard_deviation change_from_baseline dispersion_lower dispersion_upper","Event count record: continuous mean/SD/change/dispersion fields do not apply.")
                # Human-approved, field-level derivation from this Table 2 cell only.
                count_text, percent_text = raw.rstrip(")").split(" (")
                count, percent = Decimal(count_text), Decimal(percent_text)
                proportion = percent / 100
                denominator = int((count / proportion).to_integral_value(rounding=ROUND_HALF_UP))
                assert (count * 100 / denominator).quantize(percent, rounding=ROUND_HALF_UP) == percent
                precision = -percent.as_tuple().exponent + 2
                relation = "=" if count / proportion == denominator else "≈"
                derivation = (
                    f"{count_text} / {proportion:.{precision}f} {relation} {denominator}. "
                    "Human-approved deterministic policy: divide the reported event count by its reported percentage/100, "
                    "round to the nearest integer, and verify that the resulting percentage rounds back to the printed precision. "
                    "Use only this Table 2 cell, not Methods/Table 1 allocation counts. "
                    "derived outcome denominator does not adjudicate randomized_n SOURCE_CONFLICT."
                )
                put(r,"denominator",denominator,raw,4,derivation=derivation,**loc)
                reasons[(id(r),"denominator")] = derivation
            else:
                put(r,"value_kind","mean","Quantitative data were expressed as mean ± standard deviation (SD).",3)
                mean,sd=map(float,raw.split("±"))
                put(r,"value",mean,raw,4,**loc); put(r,"standard_deviation",sd,raw,4,**loc)
                nr(r,"change_from_baseline dispersion_lower dispersion_upper","Table 2 reports timepoint means and SD only; no change score or dispersion limits. No calculation from baseline means.")
                na(r,"event_count denominator","Continuous mean record, not an event proportion.")
        for pi,raw in enumerate(pvalues):
            r=entity(dm.ComparisonResult,SID+f"-CR{len(comparison_results)+1:02}",comparison_id=SID+f"-C{pi+1:02}",outcome_id=SID+f"-O{oi:02}")
            comparison_results.append(r); r["legacy_fields"].update(source_table_id="Table 2",source_row_id=row,
                statistical_test="Chi-square; Bonferroni pairwise" if oi==1 else "ANOVA; Tukey pairwise")
            loc=dict(table="Table 2",row=row,cell=f"P{pi+1}")
            put(r,"raw_value",raw,raw,4,**loc)
            put(r,"p_value",float(raw.lstrip("<")),raw,4,**loc)
            put(r,"p_value_comparator","<" if raw.startswith("<") else "=",raw,4,**loc)
            time_fields(r,month,ROW_NAMES[row_index],row)
            nr(r,"analysis_set","No ITT/per-protocol/other analysis-set statement in full article.")
            nr(r,"effect_measure estimate confidence_interval_lower confidence_interval_upper",
               "Table 2 reports P values, not an effect measure, effect estimate or confidence interval; full Results provides no corresponding estimates. These could be reported but are absent. Statistical tests are not effect measures; no derived effect size.")
    for ai,raw in enumerate(BASELINE):
        r=entity(dm.ArmResult,SID+f"-AR{len(arm_results)+1:02}",outcome_id=SID+"-O03",arm_id=ARMS[ai],source_table_id="Table 1",source_row_id="residual-baseline")
        arm_results.append(r); loc=dict(table="Table 1",row="residual-baseline",cell=f"Group {ai+1}")
        put(r,"timepoint","baseline","Table 1. The clinical state of patients with spinal cord injury (SCI) induced urinary retention",4,
            derivation="Table 1 clinical characteristics before treatment outcomes in Table 2; retained as baseline observation under the accepted baseline inclusion policy.",**loc)
        na(r,"timepoint_value timepoint_unit","Baseline is a phase, not an elapsed numeric time.")
        put(r,"raw_value",raw,raw,4,**loc)
        put(r,"value_kind","mean","Quantitative data were expressed as mean ± standard deviation (SD).",3)
        mean,sd=map(float,raw.split("±"))
        put(r,"value",mean,raw,4,**loc); put(r,"standard_deviation",sd,raw,4,**loc)
        nr(r,"analysis_set n","No explicit analyzed sample size or analysis set for this baseline measure; Table 1 header n is not silently treated as result n.")
        na(r,"change_from_baseline event_count denominator","Baseline has no change-from-baseline; continuous mean is not an event count.")
        nr(r,"dispersion_lower dispersion_upper","Baseline table reports SD, not confidence/dispersion bounds.")
    assessments=[]
    review_queue=[]
    for kind,eid,item in entities:
        for field,value in item.items():
            if not isinstance(value,dict) or "status" not in value:
                continue
            if value["status"] in ("UNRESOLVED","INSUFFICIENT_CONTEXT"):
                raise ValueError(f"Unadjudicated {kind}.{field}")
            reason=reasons.get((id(item),field))
            if reason:
                item["legacy_fields"].setdefault("annotation_notes",{})[field]=reason
            if value["status"]=="NOT_REPORTED":
                assessments.append({"entity_type":kind,"entity_id":eid,"field_id":field,
                    "status":"NOT_REPORTED","coverage_complete":True,"covered_sources":[SOURCE],
                    "rationale":reason+" Review scope: primary PDF pages 1–7, including Methods, Results, tables, figure captions, correspondence and references. No supplement or separate protocol is indicated in the supplied article."})
            if value["status"]=="REVIEW_REQUIRED":
                review_queue.append((kind,eid,field,reason,value.get("evidence_ids",[])))
    truth=dict(article=article,studies=[study],arms=arms,interventions=interventions,outcomes=outcomes,
               arm_results=arm_results,comparisons=comparisons,comparison_results=comparison_results,evidence=evidence)
    gold=GoldStandardV2.model_validate({
        "gold_version":"GOLD_STANDARD/2.0.0","article_schema_version":"ARTICLE_EXTRACTION/2.0",
        "gold_id":"2015-06-gold-v1","article_id":"2015-06","state":"FROZEN",
        "source_lineage":{"documents":[
            {"source_id":SOURCE,"role":"PRIMARY_ARTICLE","sha256":hashlib.sha256(PDF.read_bytes()).hexdigest()},
            {"source_id":"2015-06-legacy-workbook","role":"LEGACY_ANNOTATION","sha256":hashlib.sha256(WORKBOOK.read_bytes()).hexdigest()}]},
        "truth":truth,"missingness_assessments":assessments,
        "review_notes":[
            "DRAFT independently annotated from all seven PDF pages; workbook only cross-checked. No prediction output or LLM/API was used.",
            "PDF journal abbreviation retained as normalized journal value; no external bibliographic lookup.",
            "NOT_REPORTED vs NOT_APPLICABLE decisions are per-field in legacy_fields.annotation_notes.",
            "Accepted policy: retain the three Table 1 baseline residual-urine ArmResults under the existing Outcome; baseline inclusion is not pending adjudication.",
            "Human-adjudicated policy: Table 2 bladder-balance denominators are deterministically derived as 35/34/38 from the event counts and printed percentages, with field-level derived evidence and original cells retained. derived outcome denominator does not adjudicate randomized_n SOURCE_CONFLICT. No derived effects.",
            "Source quote normalization joins PDF line wraps and removes discretionary hyphens only; author affiliation markers transcribed as text.",
            "No claim of annotation accuracy from self-evaluation; self-consistency only.",
        ]})
    return gold,review_queue


def main():
    gold,queue=build()
    directory=Path(__file__).parent
    (directory/"gold.json").write_text(gold.model_dump_json(indent=2)+"\n",encoding="utf-8")
    lines=["# 2015-06 Gold FROZEN — 人工审阅记录","","状态：FROZEN。人工审核已完成；gold_id：2015-06-gold-v1。本次仅冻结状态与版本标识，不改变任何事实 annotation。不运行真实 Agent benchmark，等待 PR 最终 merge。",
        "","## 来源与审阅范围","","主来源为本地 `-2015-06.pdf`，逐页审阅 1–7 页，并视觉核对第 4 页 Table 1/2。Excel `2015-6篇.xlsx` 仅用于交叉核对。SHA256 见 gold.json source_lineage；不提交二进制。",
        "","## REVIEW_REQUIRED（已审核的不确定状态）","","centre_count 和 participant_blinding 保持 REVIEW_REQUIRED、value=null。这是人工审核完成后保留的不确定状态，不是未完成工作；不进入 ordinary scoring denominator（包括普通 HARD 分母）。"]
    by_id={e.evidence_id:e for e in gold.truth.evidence}
    for kind,eid,field,reason,ids in queue:
        lines += [f"\n### {kind} {eid}.{field}","",reason]
        lines += [f"- {e}: PDF p.{by_id[e].page}: {by_id[e].quote}" for e in ids]
    lines += ["","## 已接受的人工审核决策","",
        "- Baseline inclusion：accepted policy。保留 Table 1 的 3 个 baseline residual urine ArmResults，并关联已有 Outcome；不再作为待裁决项。",
        "- participant_blinding 保持 REVIEW_REQUIRED；practitioner / outcome assessor / statistician blinding 改为 NOT_REPORTED，各自建立完整 MissingnessAssessment，不从 single blind 推断角色。",
        "- I02/I03.total_sessions 改为 NOT_REPORTED；不由频次和月数计算 Gold 总次数。Workbook 数值仅留在下方 reconciliation note。",
        "- Bladder balance 的 3 个 ArmResult 和 3 个 ComparisonResult，其 timepoint / timepoint_value / timepoint_unit 共 18 个字段均为 NOT_REPORTED，逐字段建立 MissingnessAssessment；不从 Results 句子推断 1 month。",
        "- Study.countries 保留 Chinese patients 来源，并补充 PDF 第 5 页通讯地址 Second Hospital, Jiaxing University, Jiaxing 314000, China 的直接证据。",
        "","## Denominator 最终人工裁决与 derivation policy","",
        "- 已接受 deterministic derived：三个 bladder balance ArmResult.denominator 均为 PRESENT，并从待审队列移除。",
        "- A01：21 / 0.600 = 35；raw_value 保留 \"21 (60.0)\"。",
        "- A02：29 / 0.8529 ≈ 34；raw_value 保留 \"29 (85.29)\"。",
        "- A03：23 / 0.605 ≈ 38；raw_value 保留 \"23 (60.5)\"。",
        "- 仅使用当前 Table 2 单元格的事件数和百分比：相除后取最近整数，并核对该整数计算出的百分比在原表精度下与印刷值一致。百分比已舍入，因此 A02/A03 使用近似符号。每个字段链接独立的 support_type=derived evidence，保存完整推导、页码、表格、行及组别单元格坐标。",
        "- derived outcome denominator does not adjudicate randomized_n SOURCE_CONFLICT. 不按人数求和、Methods/Table 1 或组别角色消解 A02/A03 randomized_n 的来源冲突。",
        "","## 冻结结论","",
        "- 最终 REVIEW_REQUIRED 仅剩 2 项：centre_count 和 participant_blinding；value=null。人工审核已完成，Gold 状态为 FROZEN；两项语义与证据不变，不代表待完成工作，不进入 ordinary scoring denominator。",
        "","## 保留的解释与限制","",
        "- Bladder balance 定义见 Outcome O01.legacy_fields.definition：低压充分排尿、残余尿约100 ml或以下、无感染。",
        "- A02/A03 randomized_n 各保留 Methods/Table 1 两候选，不依据百分比裁决。",
        "- Sham frequency 未明确单独报告，不复制 EA once/day。CIC 固定频次不适用，不能与 CIC frequency 结局混淆。",
        "- P-only ComparisonResults 的 effect_measure、estimate、CI 统一 NOT_REPORTED；不计算 effect size。统计检验放 legacy_fields。",
        "- 随机序列 code=2 是标准化编码、非原文数字；allocation concealment 的 NR code 不当作 PRESENT 数字。",
        "","## Legacy workbook reconciliation","",
        "| Workbook item | Gold interpretation | Reason |","|---|---|---|",
        "| Sheet1 rows 10–11 的两条比较记录 | 一个 Article、三臂、三项明确比较 | 不是两篇文章；编号不进入 Gold truth |",
        "| total_sessions=90 | I02/I03 NOT_REPORTED，value=null | Workbook 90 仅留在本 reconciliation note；once/day × 3 months 不等于原文报告总次数，不进入 Gold value |",
        "| centre_count=1 | REVIEW_REQUIRED | Acknowledgements另提第二家医院 |",
        "| Group2/3 n=34/38 | SOURCE_CONFLICT | Methods写38/34，Table1写34/38 |",
        "| analyzed n 复制随机人数、dropout=0 | NOT_REPORTED | 原文未明确对应 flow counts |",
        "| Bladder balance 主要/患者重要结局 | role NOT_REPORTED | 不等于试验声明 primary outcome |",
        "| 通讯邮箱、年份、电脑随机、once/day、3 months | PDF核对后保留 | workbook不是独立事实证据 |",
        "| journal全称 | 保留PDF缩写 Int J Clin Exp Med | 未用外部检索扩写 |",
        "","## 解释限制","","NOT_REPORTED coverage_complete 仅指已审阅提供的完整论文及合理章节，不代表检索过所有外部注册/补充文件。",
        "Self-consistency PASS 只证明与冻结 schema/evaluator 结构兼容，不证明人工标注正确。"]
    (directory/"REVIEW.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(f"FROZEN written; reviewed uncertain fields={len(queue)}")


if __name__=="__main__":
    main()
