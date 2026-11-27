"""Deterministic four-module analysis of rebuilt source items against open lexical data.

Rules are versioned (RULES) and evaluated on the 100-item reviewed sample before they are
applied to every item. A grade-B English definition needs one Wiktionary sense and one
WordNet sense with the same part of speech that the rules align to the same meaning;
GCIDE only supports (it never supplies the sole or a second definition, because its
Webster 1913 text is often dated and its WordNet senses are not independent).
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rebuild_evidence import Lexicon, korean_terms, normalize  # noqa: E402

RULES = "v3.1"
MIN_SIM = float(__import__("os").environ.get("REBUILD_MIN_SIM", "0.34"))
MIN_MARGIN = float(__import__("os").environ.get("REBUILD_MIN_MARGIN", "0.0"))
STOP = set("""a an the of to or and in on for with by as at from into that which who whom whose
be is are was were been being one ones something someone somebody anything thing things its it
their his her your our not no any some such very more most other especially usually often
person people act state quality being way manner""".split())
PRODUCTIVE = {
    "-ment", "-ion", "-tion", "-ation", "-er", "-or", "-ly", "-ness", "-ity", "-able", "-ible", "-al",
    "-ic", "-ive", "-ful", "-less", "-ize", "-ise", "-ify", "-ing", "-ed", "-en", "-ent", "-ant",
    "-ance", "-ence", "-ship", "-hood", "-free", "-wise", "-ward", "-y", "-ous", "-ary", "-ery",
    "-ist", "-ee", "-age", "-ure", "-ism", "-ish", "-like",
    "un-", "in-", "im-", "il-", "ir-", "dis-", "mis-", "re-", "pre-", "over-", "under-", "inter-",
    "down-", "up-", "out-", "co-", "non-", "sub-", "super-", "trans-", "anti-", "self-", "multi-",
}
COMBINING = {"para-", "chron-", "-lysis", "-logy", "-graph", "tele-", "micro-", "bio-", "auto-"}
FAMILY = {"la": "Latinate", "fro": "Latinate", "frm": "Latinate", "fr": "Latinate", "xno": "Latinate",
          "it": "Latinate", "es": "Latinate", "ca": "Latinate", "pt": "Latinate", "ML.": "Latinate",
          "grc": "Greek", "ang": "Germanic", "gem-pro": "Germanic", "gmw-pro": "Germanic",
          "non": "Germanic", "dum": "Germanic", "nl": "Germanic", "de": "Germanic", "gml": "Germanic",
          "en": "English formation", "enm": "English formation"}
CHAIN = {"inh", "der", "bor", "bor+", "lbor", "uder", "lbor+", "slbor", "obor"}
FORMATION = {"af", "affix", "suffix", "prefix", "compound", "surf", "suf", "pre", "confix"}


GERMANIC = {"frk", "gmq", "osx", "odt", "goh", "got", "gem", "gsw", "gml", "non", "dum", "nl", "de", "fy",
            "ang", "nds", "da", "sv", "is", "no", "nb", "lng", "gmh", "ofs", "wlm"}
LATINATE = {"fro", "frm", "fr", "xno", "it", "es", "ca", "pt", "pro", "oc", "itc-ola", "fro-nor", "ro", "LL.", "ML."}
CELTIC = {"cel", "cel-gau", "ga", "kw", "cy", "gd", "sga", "br"}


def family(lang):
    if not lang:
        return None
    if lang.startswith("la") or lang in LATINATE:
        return "Latinate"
    if lang in ("en", "enm"):
        return "English formation"
    if lang in ("grc", "gkm", "el") or lang.endswith("-grc"):
        return "Greek"
    if lang in GERMANIC or lang.startswith("ang"):
        return "Germanic"
    if lang in CELTIC:
        return "Celtic"
    return "Other"


# Part of speech --------------------------------------------------------------------------

def korean_pos(group):
    """Infer one part of speech from a Korean gloss group; the deck has no POS field."""
    text = re.sub(r"\([^)]*\)", "", group).strip(" ~")
    last = re.split(r"[,;]", text)[-1].strip()
    if re.search(r"(하다|되다|시키다|받다|주다|내다|지다|하게 하다|[가-힣]다)$", last):
        return "verb"
    if re.search(r"(게|히|로|으로|이)$", last) and not re.search(r"(의|한|은|는|인|운|던)$", last):
        if re.search(r"(게|히|으로|로)$", last) or last in {"약간", "주로", "대부분", "결국", "마침내", "매주", "거꾸로"}:
            return "adverb"
    if re.search(r"(의|적인|있는|없는|않은|같은|스러운|로운|던|운)$", last) or (
            re.search(r"(한|은|는|인|된)$", last) and len(last) >= 3):
        return "adjective"
    if last in {"약간", "주로", "대부분", "결국", "마침내", "매주", "거꾸로", "반대로", "다시"}:
        return "adverb"
    return "noun"


KO_POS = {"noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb", "name": None}


class KoreanEntries:
    """Wiktionary Korean entries: term -> [(English POS, English gloss words)]."""

    def __init__(self, path=Path("data/rebuild/kaikki_korean.jsonl")):
        self.entries = defaultdict(list)
        if path.exists():
            for line in path.open(encoding="utf-8"):
                row = json.loads(line)
                pos = KO_POS.get(row["pos"], row["pos"])
                words = {w for sense in row["senses"] for w in re.findall(r"[a-z]+", sense["gloss"].casefold())}
                self.entries[row["word"]].append((pos, words, row["record_id"]))

    def lookup(self, term):
        from extract_korean_entries import variants
        found = []
        for form in [term] + sorted(variants(term) - {term}):
            if form in self.entries:
                found += self.entries[form]
                break
        return found


KOREAN = None
MODEL_REVIEW = {}


def load_model_review(path):
    if path and path.exists():
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            MODEL_REVIEW[row["item_id"]] = row["accepted_pairs"]


def korean_index():
    global KOREAN
    if KOREAN is None:
        KOREAN = KoreanEntries()
    return KOREAN


def group_pos(group):
    """Prefer the POS of the Wiktionary Korean entry for the gloss; fall back to ending rules."""
    terms = korean_terms(group)
    if not terms:
        return korean_pos(group)
    last = terms[-1]
    entries = [pos for pos, _, _ in korean_index().entries.get(last, []) if pos]
    if len(set(entries)) == 1:
        return entries[0]
    return korean_pos(group)


def item_pos(item):
    if " " in item["normalized"]:
        return {"phrase"}
    found = set()
    for group in item["korean_groups"]:
        for part in re.split(r";", group):
            if part.strip():
                found.add(group_pos(part))
    return found or {"noun"}


# Korean anchoring -------------------------------------------------------------------------

def korean_forms(term):
    """Spelling variants that differ only in ending: 편안한/편안하다, 정확히/정확하게, 면세의/면세."""
    term = re.sub(r"^(~[을를이가에게의와과으로로]+|~)\s*", "", term).strip()
    forms = {term}
    for pattern, repl in ((r"한$", "하다"), (r"하다$", "한"), (r"히$", "하게"), (r"하게$", "히"), (r"의$", "")):
        if re.search(pattern, term):
            forms.add(re.sub(pattern, repl, term))
    return {f for f in forms if f}


def anchored(item, kk):
    """Wiktionary senses whose Korean translation equals a textbook Korean term."""
    wanted = set()
    for group in item["korean_groups"]:
        for term in korean_terms(group):
            wanted |= korean_forms(term)
    senses = [s for s in kk if s.get("kind") != "translation"]
    hits = {}
    for sense in senses:
        if any(k in wanted for k in sense.get("ko", [])):
            hits[sense["id"]] = sorted(set(sense["ko"]) & wanted)
    for row in kk:
        if row.get("kind") != "translation" or row["ko_word"] not in wanted or not row.get("table_sense"):
            continue
        label = content(row["table_sense"])
        best = None
        for sense in senses:
            if sense["record_id"] != row["record_id"] or not label:
                continue
            overlap = len(label & content(sense["gloss"])) / len(label)
            if overlap >= 0.6 and (best is None or overlap > best[0]):
                best = (overlap, sense["id"])
        if best:
            hits.setdefault(best[1], []).append(row["ko_word"])
    return hits


# English sense alignment ------------------------------------------------------------------

def content(text):
    words = re.findall(r"[a-z]+", (text or "").casefold())
    return {w[:6] for w in words if w not in STOP and len(w) > 2}


def similarity(kk_sense, wn_sense, headword=""):
    own = {w[:6] for w in re.findall(r"[a-z]+", headword.casefold())} | {w[:4] for w in re.findall(r"[a-z]+", headword.casefold())}
    def clean(words):
        return {w for w in words if w not in own and w[:4] not in own}
    a = clean(content(kk_sense["gloss"]) | {s[:6] for s in kk_sense.get("synonyms", []) if s})
    b = clean(content(wn_sense["definition"]) | {s.casefold()[:6] for s in wn_sense["synonyms"]})
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def wordnet_anchor(item, wn_p):
    """WordNet senses whose synonyms or definition share a word with the English glosses of
    the Wiktionary Korean entry for a textbook term (the headword itself excluded)."""
    own = set(re.findall(r"[a-z]+", item["headword"].casefold()))
    best = {}
    for group in item["korean_groups"]:
        for term in korean_terms(group):
            for pos, words, _ in korean_index().lookup(term):
                english = {w for w in words if w not in STOP and w not in own and len(w) > 2}
                if not english:
                    continue
                for i, sense in wn_p:
                    syn = {t for s in sense["synonyms"] for t in s.casefold().split()} - own
                    score = len(english & syn) * 2 + len(english & {w for w in re.findall(r"[a-z]+", sense["definition"].casefold())})
                    if score:
                        best[i] = max(best.get(i, 0), score)
    if not best:
        return []
    top = max(best.values())
    return [i for i, score in best.items() if score == top]


def usable_kk(senses):
    return [s for s in senses if s.get("kind") != "translation" and not s["old"] and s["pos"] != "proper"
            and not s["form_of"]]


def candidates(lex, item):
    word = item["headword"]
    kk = lex.kk_senses(word)
    lemma_note = None
    if not usable_kk(kk):
        lemmas = {f for s in kk if s.get("kind") != "translation" for f in s["form_of"] if f}
        if len(lemmas) == 1:
            lemma_note = next(iter(lemmas))
            kk = lex.kk_senses(lemma_note)
    return lex.wn_senses(word), kk, lemma_note


def align(item, lex, pos):
    wn, kk_all, lemma = candidates(lex, item)
    kk = usable_kk(kk_all)
    phrase = "phrase" in pos
    pos_ok = (lambda p: True) if phrase else (lambda p: p in pos)
    wn_p = [(i, s) for i, s in enumerate(wn) if pos_ok(s["pos"])]
    kk_p = [s for s in kk if pos_ok(s["pos"])]
    hits = anchored(item, kk_all)
    anchor = [s for s in kk_p if s["id"] in hits]
    word = item["headword"]
    wn_hits = wordnet_anchor(item, wn_p)
    pairs, method, margins = [], None, []
    if anchor:
        method = "korean_anchor"
        for sense in anchor:
            scored = sorted(((similarity(sense, w, word) + (0.2 if i in wn_hits else 0), i) for i, w in wn_p
                             if w["pos"] == sense["pos"]), reverse=True)
            runner = scored[1][0] if len(scored) > 1 else 0.0
            if scored and scored[0][0] >= MIN_SIM and scored[0][0] - runner >= MIN_MARGIN:
                pairs.append((sense["id"], scored[0][1], round(scored[0][0], 2)))
                margins.append(round(scored[0][0] - runner, 2))
    if not pairs and wn_hits:
        method = "korean_entry_anchor"
        for i in wn_hits:
            scored = sorted(((similarity(s, wn[i], word), s["id"]) for s in kk_p if s["pos"] == wn[i]["pos"]), reverse=True)
            runner = scored[1][0] if len(scored) > 1 else 0.0
            if scored and scored[0][0] >= MIN_SIM and scored[0][0] - runner >= MIN_MARGIN:
                pairs.append((scored[0][1], i, round(scored[0][0], 2)))
                margins.append(round(scored[0][0] - runner, 2))
    if not pairs and wn_p and kk_p:
        by_pos = defaultdict(lambda: ([], []))
        for i, w in wn_p:
            by_pos[w["pos"]][0].append(i)
        for s in kk_p:
            by_pos[s["pos"]][1].append(s["id"])
        mono = [(k[0], w[0]) for p, (w, k) in by_pos.items() if len(w) == 1 and len(k) == 1]
        if mono and not phrase:
            method = "monosemous_pair"
            pairs = [(k, w, None) for k, w in mono]
    # v3: only pairs anchored on both sides by the textbook Korean meaning, or monosemous in both
    # sources, become grade B. One-sided pairs stay as proposals for semantic review.
    proposed = []
    review = MODEL_REVIEW.get(item["item_id"])
    if method != "monosemous_pair":
        strong = [(k, w, sc) for k, w, sc in pairs if k in hits and w in wn_hits]
        proposed = [(k, w, sc) for k, w, sc in pairs if (k, w, sc) not in strong]
        pairs = strong
        if pairs:
            method = "double_korean_anchor"
    if not pairs and review and proposed:
        # A reviewed decision only accepts pairs the rules proposed; it never adds new evidence.
        pairs = [proposed[i] for i in review if i < len(proposed)]
        proposed = [p for i, p in enumerate(proposed) if i not in review]
        if pairs:
            method = "model_reviewed_pair"
    if pairs:
        grade = "B"
    elif len(anchor) == 1 or (len(kk_p) == 1 and not wn_p) or (len(wn_p) == 1 and not kk_p):
        grade, method = "C", "single_source_korean_anchor" if len(anchor) == 1 else "single_source_only_sense"
        if len(anchor) == 1:
            pairs = [(anchor[0]["id"], None, None)]
        elif kk_p:
            pairs = [(kk_p[0]["id"], None, None)]
        else:
            pairs = [(None, wn_p[0][0], None)]
    elif wn_p or kk_p:
        grade, method = "D", "proposed_pair_needs_review" if proposed else "candidates_unaligned"
    else:
        grade, method = "E", "no_sense_record"
    korean = sorted({k for ids in hits.values() for k in ids if ids}) if any(p[0] in hits for p in pairs) else []
    return {"grade": grade, "method": method, "pairs": pairs, "kk_lemma": lemma, "margins": margins,
            "proposed": proposed,
            "korean_matches": korean, "wn": wn, "kk": kk}


# Morphology and etymology -----------------------------------------------------------------

def _pieces(name, args):
    values = [str(args[k]) for k in sorted((k for k in args if k.isdigit()), key=int)]
    if name == "ety":
        if len(values) < 2 or not values[1].startswith(":af"):
            return None
        values = [values[0]] + values[2:]
    if not values or values[0] != "en":
        return None
    parts = [re.sub(r"<.*?>", "", v).strip() for v in values[1:] if v.strip()]
    if name in ("suf", "suffix") and len(parts) == 2 and not parts[1].startswith("-"):
        parts[1] = "-" + parts[1]
    if name in ("pre", "prefix") and len(parts) == 2 and not parts[0].endswith("-"):
        parts[0] += "-"
    return parts if len(parts) >= 2 else None


def ordered_entries(lex, word, records=()):
    entries = lex.etymology(word)
    keyed = [e for e in entries if e["record_id"] in records]
    return keyed + [e for e in entries if e not in keyed]


def morphology(lex, word, pos, records=()):
    for entry in ordered_entries(lex, word, records):
        for name, args in entry["templates"]:
            if name not in FORMATION | {"ety"}:
                continue
            parts = _pieces(name, args)
            if not parts:
                continue
            affixes = [p for p in parts if p.startswith("-") or p.endswith("-")]
            free = [p for p in parts if p not in affixes]
            if name == "compound" or (not affixes and len(free) >= 2):
                return {"segments": parts, "type": "compound", "source": entry["record_id"]}
            if affixes and all(a in PRODUCTIVE for a in affixes) and free:
                return {"segments": parts, "type": "derivation", "source": entry["record_id"]}
            if affixes and all(a in PRODUCTIVE | COMBINING for a in affixes):
                return {"segments": parts, "type": "combining_forms", "source": entry["record_id"]}
    if " " in word:
        return {"segments": word.split(), "type": "multiword", "source": "headword"}
    return None


def etymology(lex, word, records=()):
    for entry in ordered_entries(lex, word, records):
        chain = [(name, str(args.get("2", "")), str(args.get("3", ""))) for name, args in entry["templates"]
                 if name in CHAIN and str(args.get("1")) == "en" and not str(args.get("2", "")).endswith("-pro")
                 and str(args.get("2", "")) not in ("ine", "")]
        roots = [str(args.get("3")) for name, args in entry["templates"] if name == "root" and args.get("3")]
        formation = any(name in FORMATION or (name == "ety" and str(args.get("2", "")).startswith(":af"))
                        for name, args in entry["templates"])
        sources = [(lang, form) for name, lang, form in chain if lang not in ("en", "enm")]
        if sources:
            lang, form = sources[-1]
            kind = "borrowed" if any(n.startswith(("bor", "lbor")) for n, _, _ in chain) else "derived"
            if all(n == "inh" for n, l, _ in chain if l not in ("en", "enm")):
                kind = "inherited"
            return {"language": lang, "family": family(lang), "etymon": form, "type": kind,
                    "root": roots[0] if roots else None, "source": entry["record_id"]}
        if formation:
            return {"language": "en", "family": "English formation", "etymon": None, "type": "formation",
                    "root": roots[0] if roots else None, "source": entry["record_id"]}
    return None


# Semantics and usage ----------------------------------------------------------------------

def semantics(result):
    fields, synonyms, antonyms = [], set(), set()
    for kk_id, wn_index, _ in result["pairs"]:
        if wn_index is None:
            continue
        sense = result["wn"][wn_index]
        fields.append(sense["lexfile"])
        synonyms.update(sense["synonyms"])
        antonyms.update(t for k, t in sense["relations"] if k == "antonym")
    return {"fields": sorted(set(fields)), "synonyms": sorted(synonyms)[:8], "antonyms": sorted(antonyms)}


def load_usage(path):
    usage = defaultdict(list)
    for line in path.open(encoding="utf-8"):
        row = json.loads(line)
        usage[normalize(row["headword"])].append(row)
    return usage


DEGREE = {"more", "most", "less", "least", "very", "much", "such", "other", "many", "few", "own", "same", "so", "too"}


def _collocation_ok(row, headword):
    """Drop corpus artefacts: acronyms, proper names, single-document repeats, degree words."""
    details = row.get("details", {})
    attest = details.get("attestations") or []
    target = set(normalize(headword).split())
    other = [w for w in row["expression"].split() if w not in target]
    if not attest or not other or any(w in DEGREE for w in other):
        return False
    if len({a.get("document") for a in attest}) == 1 and len(attest) > 1:
        return False
    surfaces = [" ".join(a.get("surface", "").split()) for a in attest]
    words = [s.split() for s in surfaces if s]
    def collocate_tokens(tokens):
        return [t for t in tokens if normalize(t)[:4] not in {w[:4] for w in target}]
    tokens = [collocate_tokens(t) for t in words]
    if tokens and all(t and all(x.isupper() and len(x) > 1 for x in t) for t in tokens):
        return False
    target_lower = any(any(t.islower() for t in ws if normalize(t)[:4] in {w[:4] for w in target}) for ws in words)
    if tokens and target_lower and all(t and all(x[:1].isupper() for x in t) for t in tokens):
        return False
    if words and all(all(x[:1].isupper() for x in ws) for ws in words):
        return False  # title-cased in every attestation: a name or heading, not a collocation
    if any(normalize(x) != w and normalize(x).startswith(w) and w in target for ws in words for x in ws for w in [normalize(x)[:len(w)] for w in target]):
        pass
    return True


def lexical_usage(rows, headword=""):
    collocations, seen = [], set()
    frequency = 0
    for row in rows:
        details = row.get("details", {})
        if row["usage_type"] == "FREQUENCY":
            frequency += details.get("frequency", 0)
        elif row["usage_type"] in ("COLLOCATION", "COLLIGATION"):
            metrics = details.get("metrics", {})
            if not (details.get("frequency", 0) >= 5 and metrics.get("logdice", 0) >= 7
                    and metrics.get("log_likelihood", 0) >= 10.83 and _collocation_ok(row, headword)):
                continue
            surfaces = [" ".join(a.get("surface", "").split()).casefold() for a in details.get("attestations", [])]
            shown = max(set(surfaces), key=surfaces.count) if surfaces else row["expression"]
            if shown in seen:
                continue
            seen.add(shown)
            collocations.append({"expression": shown, "lemma": row["expression"], "type": row["usage_type"].lower(),
                                 "combination": details.get("combination"), "frequency": details["frequency"],
                                 "logdice": metrics["logdice"], "record": row["source_record_id"]})
        elif row["usage_type"] == "PHRASE_ATTESTATION":
            frequency += details.get("frequency", 0)
    collocations.sort(key=lambda c: (-c["logdice"], -c["frequency"]))
    return {"oanc_frequency": frequency, "collocations": collocations[:6]}


def analyze(item, lex, usage):
    pos = item_pos(item)
    result = align(item, lex, pos)
    english = []
    records = {kk_id.rsplit(":", 1)[0] for kk_id, _, _ in result["pairs"] if kk_id}
    for kk_id, wn_index, score in result["pairs"]:
        kk = next((s for s in result["kk"] if s["id"] == kk_id), None)
        wn = result["wn"][wn_index] if wn_index is not None else None
        english.append({"kk_sense": kk_id, "kk_gloss": kk["gloss"] if kk else None,
                        "wn_sense": wn["sense_id"] if wn else None, "wn_index": wn_index,
                        "wn_definition": wn["definition"] if wn else None, "pos": (wn or kk)["pos"],
                        "similarity": score})
    return {
        "item_id": item["item_id"], "headword": item["headword"], "deck": item["deck"], "day": item["day"],
        "core": item["core"], "korean": item["korean_groups"], "pos": sorted(pos), "rules": RULES,
        "english_grade": result["grade"], "method": result["method"], "english": english,
        "alignment_margins": result["margins"],
        "proposed_pairs": [{"kk_sense": k, "wn_sense": result["wn"][w]["sense_id"], "score": sc} for k, w, sc in result["proposed"]],
        "kk_lemma": result["kk_lemma"],
        "korean_status": "verified" if result["korean_matches"] else "unverified",
        "korean_evidence": result["korean_matches"],
        "morphology": morphology(lex, item["headword"], pos, records),
        "etymology": etymology(lex, item["headword"], records),
        "semantics": semantics(result),
        "usage": lexical_usage(usage.get(item["normalized"], []), item["headword"]),
        "textbook_relations": item["textbook_relations"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=Path("data/rebuild/source_items.jsonl"))
    parser.add_argument("--usage", type=Path, default=Path("data/rebuild/oanc_usage.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-review", type=Path, help="reviewed acceptances of proposed pairs (JSONL)")
    args = parser.parse_args()
    load_model_review(args.model_review)
    lex, usage = Lexicon(), load_usage(args.usage)
    rows = [json.loads(line) for line in args.items.open(encoding="utf-8")]
    out = [analyze(row, lex, usage) for row in rows if not row.get("duplicate_of")]
    with args.output.open("w", encoding="utf-8") as handle:
        for row in out:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(args.output, len(out), dict(Counter(r["english_grade"] for r in out)))


if __name__ == "__main__":
    main()
