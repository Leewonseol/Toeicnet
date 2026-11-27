"""Typed validation of evidence-backed links in the four analysis modules."""

import argparse
from collections import defaultdict
from pathlib import Path

from review_common import (
    STATUSES, at_location, checked_evidence, date_field, enum_field, jsonl_records,
    load_catalog, normalized_lemma, object_field, reviewed_pos, text_field, write_jsonl,
)


LEXEME = {"WORD", "SENSE"}
WORD = {"WORD"}
SENSE = {"SENSE"}
MORPHOLOGY_TARGETS = {
    "HAS_MORPHEME": "MORPHEME",
    "HAS_ROOT": "ROOT",
    "HAS_BASE": "BASE",
    "HAS_STEM": "STEM",
    "HAS_PREFIX": "PREFIX",
    "HAS_SUFFIX": "SUFFIX",
    "HAS_INFLECTIONAL_ENDING": "INFLECTIONAL_ENDING",
}
SENSE_RELATIONS = {
    "SYNONYM_OF", "NEAR_SYNONYM_OF", "ANTONYM_OF", "COMPLEMENTARY_TO",
    "GRADABLE_OPPOSITE_OF", "CONVERSE_OF", "REVERSIVE_OF", "CONTEXTUAL_OPPOSITE_OF",
}
TAXONOMIC_RELATIONS = {"HYPERNYM_OF", "HYPONYM_OF", "MERONYM_OF"}
USAGE_TARGETS = {
    "PARTICIPATES_IN_COLLOCATION": {"COLLOCATION"},
    "HAS_COLLIGATION": {"COLLIGATION"},
    "PARTICIPATES_IN_IDIOM": {"IDIOM"},
    "PARTICIPATES_IN_PHRASAL_VERB": {"PHRASAL_VERB"},
    "HAS_VERB_PATTERN": {"GRAMMATICAL_PATTERN"},
    "HAS_ARGUMENT_STRUCTURE": {"GRAMMATICAL_PATTERN", "ARGUMENT_STRUCTURE"},
    "HAS_COUNTABILITY": {"GRAMMATICAL_PATTERN", "COUNTABILITY"},
    "HAS_TRANSITIVITY": {"GRAMMATICAL_PATTERN", "TRANSITIVITY"},
    "HAS_REGISTER": {"GRAMMATICAL_PATTERN", "REGISTER"},
}
RELATIONS = {
    "morphology": {
        **{name: (WORD, {target}) for name, target in MORPHOLOGY_TARGETS.items()},
        "DERIVED_FROM": (WORD, WORD),
        "INFLECTION_OF": (WORD, WORD),
        "COMPOUND_COMPONENT_OF": (WORD | {"BASE", "ROOT"}, WORD),
    },
    "etymology": {
        "ETYMOLOGICALLY_DERIVED_FROM": (WORD | {"HISTORICAL_FORM"}, WORD | {"HISTORICAL_FORM"}),
        "HAS_ETYMOLOGICAL_ROOT": (WORD | {"HISTORICAL_FORM"}, {"ETYMOLOGICAL_ROOT"}),
        "HAS_HISTORICAL_FORM": (WORD, {"HISTORICAL_FORM"}),
        "HAS_ETYMOLOGICAL_AFFIX": (WORD | {"HISTORICAL_FORM"}, {"ETYMOLOGICAL_AFFIX", "PREFIX", "SUFFIX"}),
        "HAS_ORIGIN_LANGUAGE": (WORD | {"HISTORICAL_FORM", "ETYMOLOGICAL_ROOT"}, {"ORIGIN_LANGUAGE"}),
        "VARIANT_OF": (
            {"HISTORICAL_FORM", "ETYMOLOGICAL_ROOT", "ETYMOLOGICAL_AFFIX"},
            {"HISTORICAL_FORM", "ETYMOLOGICAL_ROOT", "ETYMOLOGICAL_AFFIX"},
        ),
        "COGNATE_WITH": (WORD | {"HISTORICAL_FORM"}, WORD | {"HISTORICAL_FORM"}),
        "BORROWED_FROM": (WORD | {"HISTORICAL_FORM"}, {"HISTORICAL_FORM"}),
        "HAS_SEMANTIC_CHANGE": (LEXEME, {"SENSE", "HISTORICAL_FORM", "SEMANTIC_CHANGE"}),
    },
    "lexical_semantics": {
        **{name: (SENSE, SENSE) for name in SENSE_RELATIONS},
        **{name: (SENSE | {"SYNSET"}, SENSE | {"SYNSET"}) for name in TAXONOMIC_RELATIONS},
        "BELONGS_TO_SYNSET": (SENSE, {"SYNSET"}),
        "BELONGS_TO_SEMANTIC_FIELD": (SENSE, {"SEMANTIC_FIELD"}),
        "BELONGS_TO_THEME": (LEXEME, {"THEME"}),
    },
    "lexical_usage": {
        **{name: (SENSE, targets) for name, targets in USAGE_TARGETS.items()},
        "COLLOCATES_WITH": (SENSE, SENSE),
    },
}
SYMMETRIC = SENSE_RELATIONS | {"COGNATE_WITH", "COLLOCATES_WITH"}
REQUIRED_ATTRIBUTES = {
    "DERIVED_FROM": {"affixes", "source_pos", "target_pos", "meaning_change", "form_change"},
    "INFLECTION_OF": {"features"},
    "HAS_ETYMOLOGICAL_ROOT": {"origin_language", "historical_form", "earlier_meaning"},
    "HAS_HISTORICAL_FORM": {"origin_language", "earlier_meaning"},
    "BORROWED_FROM": {"origin_language"},
    "COGNATE_WITH": {"shared_origin", "cognate_type"},
    "HAS_SEMANTIC_CHANGE": {"change_type", "earlier_meaning", "later_meaning"},
    "HYPERNYM_OF": {"study_rationale"},
    "HYPONYM_OF": {"study_rationale"},
    "MERONYM_OF": {"study_rationale"},
    "PARTICIPATES_IN_COLLOCATION": {"combination_type"},
    "HAS_COLLIGATION": {"construction"},
    "PARTICIPATES_IN_IDIOM": {"idiom_category"},
    "PARTICIPATES_IN_PHRASAL_VERB": {
        "base_verb", "particle", "transitivity", "separability", "pronoun_position",
    },
    "HAS_VERB_PATTERN": {"construction"},
    "HAS_ARGUMENT_STRUCTURE": {"arguments"},
    "HAS_COUNTABILITY": {"value"},
    "HAS_TRANSITIVITY": {"value"},
    "HAS_REGISTER": {"value"},
}
ATTESTED_STATUSES = {"source_attested", "cross_verified", "corpus_attested"}


def endpoint(value, name, allowed):
    item = dict(object_field(value, name))
    node_type = enum_field(item, "node_type", allowed)
    if node_type in LEXEME:
        item["headword"] = text_field(item, "headword")
        item["homonym_key"] = text_field(item, "homonym_key", optional=True)
        if node_type == "SENSE":
            item["sense_key"] = text_field(item, "sense_key")
            item["part_of_speech"] = reviewed_pos(item)
    else:
        item["key"] = text_field(item, "key")
        item["label"] = text_field(item, "label")
    return item


def endpoint_key(item):
    node_type = item["node_type"]
    if node_type in LEXEME:
        return (
            node_type, normalized_lemma(item["headword"]), item.get("homonym_key") or "",
            item.get("part_of_speech", "") if node_type == "SENSE" else "",
            item.get("sense_key", "") if node_type == "SENSE" else "",
        )
    return node_type, item["key"]


def relation_key(item):
    first, second = endpoint_key(item["from"]), endpoint_key(item["to"])
    if item["relation_type"] in SYMMETRIC and first > second:
        first, second = second, first
    return item["relation_type"], first, second


def checked_relation(record, catalog):
    module = enum_field(record, "module", RELATIONS)
    relation_type = enum_field(record, "relation_type", RELATIONS[module])
    status = enum_field(record, "status", STATUSES)
    from_types, to_types = RELATIONS[module][relation_type]
    source = endpoint(record.get("from"), "from", from_types)
    target = endpoint(record.get("to"), "to", to_types)
    if endpoint_key(source) == endpoint_key(target):
        raise ValueError("relation endpoints must be distinct")
    if relation_type in TAXONOMIC_RELATIONS and source["node_type"] != target["node_type"]:
        raise ValueError("taxonomy links must connect two sense nodes or two synset nodes")
    attributes = object_field(record.get("attributes", {}), "attributes")
    evidence = checked_evidence(record, "evidence", catalog)
    if status in ATTESTED_STATUSES | {"disputed"}:
        supporting = [entry for entry in evidence if entry.get("relation_match") == "matched"]
        if status in ATTESTED_STATUSES and not supporting:
            raise ValueError(f"{status} requires explicitly matched relation evidence")
        for entry in evidence:
            enum_field(entry, "relation_match", {"matched", "disagrees", "uncertain"})
            text_field(entry, "note")
        if status == "cross_verified" and (
            len({entry["independence_group"] for entry in supporting}) < 2
            or any(entry["relation_match"] == "disagrees" for entry in evidence)
        ):
            raise ValueError("cross_verified requires two independent, agreeing relation sources")
        if status == "corpus_attested" and (
            module != "lexical_usage"
            or not any(catalog[entry["source_id"]]["source_type"] == "corpus" for entry in supporting)
        ):
            raise ValueError("corpus_attested requires matched corpus evidence for a usage relation")
        if status == "disputed" and (
            len({entry["independence_group"] for entry in evidence}) < 2
            or not any(entry["relation_match"] == "disagrees" for entry in evidence)
        ):
            raise ValueError("disputed requires independently sourced relation disagreement")
        if status in ATTESTED_STATUSES:
            missing = REQUIRED_ATTRIBUTES.get(relation_type, set()) - attributes.keys()
            if missing:
                raise ValueError(f"{relation_type} missing attributes {', '.join(sorted(missing))}")
            if relation_type == "PARTICIPATES_IN_IDIOM":
                enum_field(attributes, "idiom_category", {"preposition", "adverb", "verb", "noun"})
    if attributes.get("toeic_official") is True and (
        module != "lexical_usage" or not any(
            catalog[entry["source_id"]]["source_type"] == "official_test"
            and entry.get("relation_match") == "matched" and entry.get("item_locator")
            for entry in evidence
        )
    ):
        raise ValueError("toeic_official requires matched evidence with a public official item locator")
    return {
        "kind": "relation", "module": module, "relation_type": relation_type,
        "from": source, "to": target, "attributes": attributes,
        "status": status, "evidence": evidence, "verification_date": date_field(record),
    }


CANDIDATE_MODULES = defaultdict(set)
for analysis_module, relation_types in RELATIONS.items():
    for name in relation_types:
        CANDIDATE_MODULES[name].add(analysis_module)
for candidate_type, candidate_module in {
    "ETYMOLOGY_TEXT": "etymology",
    "ETYMOLOGY_NARRATIVE": "etymology",
    "ETYMOLOGY_TEMPLATE": "etymology",
    "ETYMOLOGY": "etymology",
    "HISTORICAL_FORM": "etymology",
    "INFLECTION": "morphology",
    "HAS_INFLECTION": "morphology",
    "HAS_VARIANT_FORM": "morphology",
    "HAS_DERIVED_TERM_CANDIDATE": "morphology",
    "MORPHOLOGICAL_TEMPLATE": "morphology",
    "DERIVATION": "morphology",
    "AFFIX": "morphology",
    "COMPOUND": "morphology",
    "MORPHOLOGY": "morphology",
    "WORD_FORM": "morphology",
    "HAS_MERONYM": "lexical_semantics",
    "RELATED_TO": "lexical_semantics",
    "COLLOCATION": "lexical_usage",
    "COLLIGATION": "lexical_usage",
    "FREQUENCY": "lexical_usage",
    "PHRASE_ATTESTATION": "lexical_usage",
    "IDIOM": "lexical_usage",
    "PHRASAL_VERB": "lexical_usage",
    "VERB_PATTERN": "lexical_usage",
    "ARGUMENT_STRUCTURE": "lexical_usage",
    "COUNTABILITY": "lexical_usage",
    "TRANSITIVITY": "lexical_usage",
    "REGISTER": "lexical_usage",
}.items():
    CANDIDATE_MODULES[candidate_type].add(candidate_module)


def analysis_records(paths, module, catalog, *, for_review):
    seen = set()
    for location, record in jsonl_records(paths):
        if record.get("kind") == "relation":
            if record.get("module") != module:
                if record.get("module") not in RELATIONS:
                    raise ValueError(f"{location}: unknown analysis module")
                continue
            checked = at_location(location, checked_relation, record, catalog)
            key = relation_key(checked)
            if key in seen:
                raise ValueError(f"{location}: duplicate reviewed {key[0]} relation")
            seen.add(key)
            yield checked
        elif for_review:
            relation_type = record.get("relation_type") or record.get("usage_type")
            if record.get("module") == module or module in CANDIDATE_MODULES.get(relation_type, set()):
                yield {**record, "module": module, "review_status": "pending"}


def analysis_cli(module, description):
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("input", type=Path, nargs="+")
    parser.add_argument("--catalog", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-candidates", action="store_true",
        help="Include external candidate records as pending review",
    )
    args = parser.parse_args()
    try:
        catalog = load_catalog(args.catalog)
        rows = analysis_records(args.input, module, catalog, for_review=args.include_candidates)
        count = write_jsonl(args.output, rows)
    except (ValueError, OSError) as error:
        parser.error(str(error))
    print(f"Wrote {count} {module} records to {args.output}")
