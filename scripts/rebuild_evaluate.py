"""Score rule output against the reviewed 100-item sample, module by module."""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rebuild_analyze import family  # noqa: E402


def seg(text):
    return re.sub(r"\s+", "", (text or "").replace("(compound)", "").replace("(phrasal verb)", "")).casefold()


def kid(value):
    return value.split(":", 2)[2] if value and value.startswith("kaikki:") else value


def ratio(hit, total):
    return {"correct": hit, "total": total, "rate": round(hit / total, 3) if total else None}


def evaluate(pred, gold):
    out, errors = {}, []
    pos_hit = sum(1 for p, g in zip(pred, gold) if set(p["pos"]) == set(g["pos"]) or
                  ("phrase" in p["pos"] and " " in p["headword"]))
    out["pos_exact"] = ratio(sum(1 for p, g in zip(pred, gold) if set(p["pos"]) == set(g["pos"])), len(gold))
    out["pos_single_word"] = ratio(sum(1 for p, g in zip(pred, gold) if " " not in p["headword"] and set(p["pos"]) == set(g["pos"])),
                                   sum(1 for p in pred if " " not in p["headword"]))
    b_total = b_ok = 0
    for p, g in zip(pred, gold):
        if p["english_grade"] != "B":
            continue
        b_total += 1
        good = all((e["wn_index"] in g["wn"]) and (kid(e["kk_sense"]) in g["kk"] or (g.get("kk_lemma") and p["kk_lemma"] == g["kk_lemma"]))
                   for e in p["english"])
        b_ok += good
        if not good:
            errors.append({"n": g["n"], "module": "english_B", "headword": p["headword"],
                           "predicted": [(e["kk_sense"], e["wn_index"]) for e in p["english"]], "gold": (g["kk"], g["wn"])})
    gold_both = sum(1 for g in gold if g["wn"] and (g["kk"] or g.get("kk_lemma")))
    out["english_B_precision"] = ratio(b_ok, b_total)
    out["english_B_recall_vs_gold_two_source_items"] = ratio(b_ok, gold_both)
    c_total = c_ok = 0
    for p, g in zip(pred, gold):
        if p["english_grade"] == "C":
            c_total += 1
            e = p["english"][0]
            good = ((kid(e["kk_sense"]) in g["kk"] or (g.get("kk_lemma") and p["kk_lemma"] == g["kk_lemma"]))
                    if e["kk_sense"] else (e["wn_index"] in g["wn"]))
            c_ok += bool(good)
            if not good:
                errors.append({"n": g["n"], "module": "english_C", "headword": p["headword"], "predicted": (e["kk_sense"], e["wn_index"]), "gold": (g["kk"], g["wn"])})
    out["english_C_precision"] = ratio(c_ok, c_total)
    out["grade_distribution"] = dict(Counter(p["english_grade"] for p in pred))
    kv = [(p, g) for p, g in zip(pred, gold) if p["korean_status"] == "verified"]
    out["korean_verified_precision"] = ratio(sum(1 for p, g in kv if g["ko_wikt"] and p["english_grade"] in "BC"
                                                 and all(kid(e["kk_sense"]) in g["kk"] for e in p["english"] if e["kk_sense"])), len(kv))
    out["korean_verified_recall"] = ratio(sum(1 for p, g in kv if g["ko_wikt"]), sum(1 for g in gold if g["ko_wikt"]))
    m_pred = [(p, g) for p, g in zip(pred, gold) if p["morphology"] and p["morphology"]["type"] != "multiword"]
    m_ok = sum(1 for p, g in m_pred if g["morph"] and seg(" + ".join(p["morphology"]["segments"])) == seg(g["morph"]))
    out["morphology_precision"] = ratio(m_ok, len(m_pred))
    out["morphology_recall"] = ratio(m_ok, sum(1 for g in gold if g["morph"] and "multiword" not in (g.get("morph_basis") or "")
                                              and "phrasal" not in g["morph"] and "compound)" not in g["morph"]))
    for p, g in m_pred:
        if not (g["morph"] and seg(" + ".join(p["morphology"]["segments"])) == seg(g["morph"])):
            errors.append({"n": g["n"], "module": "morphology", "headword": p["headword"], "predicted": p["morphology"]["segments"], "gold": g["morph"]})
    e_pred = [(p, g) for p, g in zip(pred, gold) if p["etymology"] and g["ety_lang"]]
    e_ok = sum(1 for p, g in e_pred if p["etymology"]["family"] == family(g["ety_lang"]))
    out["etymology_family_precision"] = ratio(e_ok, len(e_pred))
    out["etymology_family_recall"] = ratio(e_ok, sum(1 for g in gold if g["ety_lang"]))
    for p, g in e_pred:
        if p["etymology"]["family"] != family(g["ety_lang"]):
            errors.append({"n": g["n"], "module": "etymology", "headword": p["headword"], "predicted": p["etymology"]["family"] + ":" + p["etymology"]["language"], "gold": g["ety_lang"]})
    r_pred = [(p, g) for p, g in zip(pred, gold) if p["etymology"] and p["etymology"]["root"] and g.get("root")]
    out["root_agreement"] = ratio(sum(1 for p, g in r_pred if p["etymology"]["root"] == g["root"]), len(r_pred))
    f_pred = [(p, g) for p, g in zip(pred, gold) if p["semantics"]["fields"]]
    f_ok = sum(1 for p, g in f_pred if set(p["semantics"]["fields"]) <= set(g["field"]))
    out["semantic_field_precision"] = ratio(f_ok, len(f_pred))
    a_pred = [(p, g) for p, g in zip(pred, gold) if p["semantics"]["antonyms"]]
    out["antonym_precision"] = ratio(sum(1 for p, g in a_pred if set(p["semantics"]["antonyms"]) <= set(g["ant"])), len(a_pred))
    out["antonym_recall"] = ratio(sum(1 for p, g in a_pred if set(g["ant"]) & set(p["semantics"]["antonyms"])), sum(1 for g in gold if g["ant"]))
    return out, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--gold", type=Path, default=Path("data/rebuild/gold/sample_gold.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    gold = [json.loads(l) for l in args.gold.open(encoding="utf-8")]
    pred = [json.loads(l) for l in args.predictions.open(encoding="utf-8")]
    assert len(pred) == len(gold)
    scores, errors = evaluate(pred, gold)
    args.output.write_text(json.dumps({"scores": scores, "errors": errors}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for key, value in scores.items():
        print(key, value)


if __name__ == "__main__":
    main()
