#!/usr/bin/env python3
"""Write UTF-8 two-column Quizlet imports from verified learning items."""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path

from study_data import (
    OPPOSITION_RELATIONS, RELATION_LABELS, StudyData, answer, atomic_text,
    node_type, object_properties, path_label, study_edges,
)

DECK_RELATIONS = {
    "derivations": {"DERIVED_FROM"},
    "inflections": {"INFLECTION_OF"},
    "prefixes": {"HAS_PREFIX"},
    "suffixes": {"HAS_SUFFIX"},
    "roots": {"HAS_ROOT", "HAS_ETYMOLOGICAL_ROOT"},
    "cognates": {"COGNATE_WITH"},
    "synonyms": {"SYNONYM_OF"},
    "near_synonyms": {"NEAR_SYNONYM_OF"},
    "antonyms": OPPOSITION_RELATIONS,
    "collocations": {"PARTICIPATES_IN_COLLOCATION"},
    "colligations": {"HAS_COLLIGATION"},
    "idioms": {"PARTICIPATES_IN_IDIOM"},
    "phrasal_verbs": {"PARTICIPATES_IN_PHRASAL_VERB"},
    "verb_patterns": {"HAS_VERB_PATTERN"},
    "themes": {"BELONGS_TO_THEME"},
}
EXPRESSION_DECKS = frozenset({"collocations", "colligations", "idioms", "phrasal_verbs", "verb_patterns"})
EXPRESSION_NODE_TYPES = frozenset({
    "COLLOCATION", "COLLIGATION", "IDIOM", "PHRASAL_VERB", "GRAMMATICAL_PATTERN",
})
LANGUAGE_LABELS = {
    "bilingual": "검증된 한국어 뜻 또는 교차 검증된 영어 정의",
    "english_definitions": "교차 검증된 영어 정의",
}


def sense_prompt(data, sense):
    word = data.words[sense["word_id"]]
    headword = path_label(word["headword"])
    part_of_speech = path_label(sense["part_of_speech"])
    siblings = [
        other for other in data.word_senses[word["word_id"]]
        if other["part_of_speech"] == sense["part_of_speech"]
    ]
    prompt = f"{headword} ({part_of_speech})" if part_of_speech else headword
    if len(siblings) > 1:
        prompt += f" · 의미 {siblings.index(sense) + 1}"
    if len(data.homonyms[word["normalized"]]) > 1:
        prompt += f" · {word['homonym_key'] or word['word_id']}"
    return prompt


def expression_node(data, edge):
    identifiers = (edge["to_node_id"], edge["from_node_id"])
    for identifier in identifiers:
        if node_type(data, identifier) in EXPRESSION_NODE_TYPES:
            return data.nodes[identifier]
    return None


def reference_meaning(data, node):
    if node["node_type"] == "WORD":
        senses = data.word_senses.get(node.get("word_id"), ())
        if len(senses) == 1:
            return data.meaning(senses[0]["sense_id"])
        return {}
    return data.node_meaning(node)


def learning_label(data, node_id):
    node = data.nodes[node_id]
    if node["node_type"] == "SENSE" and node.get("sense_id") in data.senses:
        return sense_prompt(data, data.senses[node["sense_id"]])
    return data.node_label(node_id)


def edge_card(data, deck, edge, english_only):
    relation = edge["relation_type"]
    source_id = edge["from_node_id"]
    target_id = edge["to_node_id"]
    source = learning_label(data, source_id)
    target = learning_label(data, target_id)
    if deck in EXPRESSION_DECKS:
        expression = expression_node(data, edge)
        if expression:
            meaning = answer(reference_meaning(data, expression), english_only=english_only)
            if meaning:
                return expression["label"], meaning
        return None
    if deck == "themes":
        if not english_only:
            return f"{source} · 확인된 테마", target
    if deck == "inflections":
        if english_only:
            return None
        features = object_properties(edge).get("features")
        if isinstance(features, list):
            features = " · ".join(map(str, features))
        elif isinstance(features, dict):
            features = " · ".join(f"{name} {value}" for name, value in sorted(features.items()))
        features = path_label(features)
        return f"{target} · 굴절형" + (f" · {features}" if features else ""), source
    label = RELATION_LABELS[relation]
    meaning = answer(reference_meaning(data, data.nodes[target_id]), english_only=english_only)
    if meaning:
        return f"{source} · {label}", f"{target} · {meaning}"
    return None


def render_cards(data, *, english_only):
    decks = defaultdict(set)
    for sense in data.senses.values():
        if data.role(sense["word_id"]) != "core":
            continue
        meaning = answer(data.meaning(sense["sense_id"]), english_only=english_only)
        if meaning:
            decks["core_words"].add((sense_prompt(data, sense), meaning))
    deck_by_relation = {
        relation: deck for deck, relations in DECK_RELATIONS.items() for relation in relations
    }
    for edge in study_edges(data):
        related_words = [
            data.node_word(identifier)
            for identifier in (edge["from_node_id"], edge["to_node_id"])
        ]
        if all(word is None or data.role(word) == "extension" for word in related_words):
            continue
        deck = deck_by_relation.get(edge["relation_type"])
        if edge["relation_type"] == "HAS_ETYMOLOGICAL_AFFIX":
            target = data.nodes[edge["to_node_id"]]
            affix_type = object_properties(target).get("affix_type") or object_properties(edge).get("affix_type")
            if target["node_type"] == "PREFIX" or affix_type == "prefix":
                deck = "prefixes"
            elif target["node_type"] == "SUFFIX" or affix_type == "suffix":
                deck = "suffixes"
        if deck:
            card = edge_card(data, deck, edge, english_only)
            if card:
                front, back = map(path_label, card)
                if front and back:
                    decks[deck].add((front, back))
    return decks


def write_decks(data, output):
    summary = ["# Quizlet 가져오기", "", "UTF-8 TSV에서 탭을 앞면과 뒷면 구분자로 사용합니다.", ""]
    counts = {}
    for language in LANGUAGE_LABELS:
        cards = render_cards(data, english_only=language == "english_definitions")
        summary += [f"## {LANGUAGE_LABELS[language]}", ""]
        counts[language] = {}
        for deck in ("core_words", *DECK_RELATIONS):
            target = output / language / f"{deck}.tsv"
            with atomic_text(target, newline="") as stream:
                answers_by_front = defaultdict(list)
                for front, back in sorted(cards[deck], key=lambda pair: (pair[0].casefold(), pair[0], pair[1])):
                    answers_by_front[front].append(back)
                for front, backs in answers_by_front.items():
                    for number, back in enumerate(backs, start=1):
                        prompt = front if len(backs) == 1 else f"{front} · {number}/{len(backs)}"
                        stream.write(f"{prompt}\t{back}\n")
            count = len(cards[deck])
            counts[language][deck] = count
            summary.append(f"- {deck} {count}장 [TSV]({language}/{deck}.tsv)")
        summary.append("")
    if not any(count for decks in counts.values() for count in decks.values()):
        summary += ["현재 조건을 충족한 카드가 없습니다."]
    with atomic_text(output / "README.md") as stream:
        stream.write("\n".join(summary) + "\n")
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=Path("data/processed/toeic.db"))
    parser.add_argument("--output", type=Path, default=Path("exports/quizlet"))
    args = parser.parse_args()
    counts = write_decks(StudyData(args.db), args.output)
    for language, decks in counts.items():
        print(f"{language}: {sum(decks.values())} cards")


if __name__ == "__main__":
    main()
