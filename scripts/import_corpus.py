"""Measure POS-aware lexical candidates in the OANC GrAF archive."""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
import math
from pathlib import Path
import tarfile
from typing import Iterator
import xml.etree.ElementTree as ET

from external_records import normalize_headword, targets, write_jsonl

OANC_URL = "https://anc.org/data/oanc/download/"
GRAF = "{http://www.xces.org/ns/GrAF/1.0/}"
XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
LEXICAL_PAIRS = {
    ("verb", "noun"): "verb+noun",
    ("adjective", "noun"): "adjective+noun",
    ("noun", "noun"): "noun+noun",
    ("verb", "adverb"): "verb+adverb",
    ("adverb", "adjective"): "adverb+adjective",
}
WORD_PREPOSITIONS = {"IN", "TO", "RP"}
PENN_EXACT = {"IN": "preposition", "RP": "particle", "TO": "to", "DT": "determiner"}
TokenKey = tuple[str, str]
PairKey = tuple[TokenKey, TokenKey]


@dataclass(frozen=True, slots=True)
class Token:
    start: int
    end: int
    lemma: str
    pos: str
    tag: str
    id: str


def penn_pos(tag: str) -> str:
    for prefix, pos in (("NN", "noun"), ("VB", "verb"), ("JJ", "adjective"), ("RB", "adverb"),
                        ("PRP", "pronoun")):
        if tag.startswith(prefix):
            return pos
    return PENN_EXACT.get(tag, "other")


def annotation_spans(xml: bytes, label: str) -> Iterator[tuple[int, int, str, dict]]:
    root = ET.fromstring(xml)
    link_tag, feature_set_tag, feature_tag = GRAF + "link", GRAF + "fs", GRAF + "f"
    regions = {
        region.attrib[XML_ID]: tuple(map(int, region.attrib["anchors"].split()))
        for region in root.iterfind(GRAF + "region")
    }
    nodes = {
        node.attrib[XML_ID]: link.attrib["targets"]
        for node in root.iterfind(GRAF + "node")
        if (link := node.find(link_tag)) is not None
    }
    for annotation in root.iterfind(GRAF + "a"):
        if annotation.get("label") != label:
            continue
        node_id = annotation.get("ref")
        bounds = regions.get(nodes.get(node_id))
        if bounds is None or len(bounds) != 2:
            continue
        feature_map = annotation.find(feature_set_tag)
        features = {} if feature_map is None else {
            feature.attrib["name"]: feature.get("value")
            for feature in feature_map
            if feature.tag == feature_tag
        }
        yield *bounds, node_id, features


def archive_documents(path: Path, max_documents: int | None = None) -> Iterator[tuple[str, str, bytes, bytes]]:
    suffixes = (".txt", "-s.xml", "-hepple.xml")
    pending: dict[str, dict[str, bytes]] = defaultdict(dict)
    yielded = 0
    with tarfile.open(path, "r|*") as archive:
        for member in archive:
            filename = Path(member.name)
            if not member.isfile() or filename.name.startswith("._") or "/data/" not in member.name:
                continue
            suffix = next((suffix for suffix in suffixes if member.name.endswith(suffix)), None)
            if suffix is None:
                continue
            key = member.name[:-len(suffix)]
            with archive.extractfile(member) as file:
                pending[key][suffix] = file.read()
            if len(pending[key]) == len(suffixes):
                parts = pending.pop(key)
                yield key, parts[".txt"].decode("utf-8-sig"), parts["-hepple.xml"], parts["-s.xml"]
                yielded += 1
                if max_documents is not None and yielded >= max_documents:
                    return


def sentence_tokens(text: str, hepple: bytes, sentences: bytes) -> Iterator[tuple[int, int, list[Token]]]:
    spans = sorted((start, end) for start, end, _, _ in annotation_spans(sentences, "s"))
    starts = [start for start, _ in spans]
    groups: dict[int, list[Token]] = defaultdict(list)
    for start, end, token_id, info in annotation_spans(hepple, "tok"):
        index = bisect_right(starts, start) - 1
        if index < 0 or end > spans[index][1] or end > len(text):
            continue
        tag = info.get("msd") or ""
        lemma = normalize_headword(info.get("base") or text[start:end])
        groups[index].append(Token(start, end, lemma, penn_pos(tag), tag, token_id))
    for index, tokens in groups.items():
        yield *spans[index], sorted(tokens, key=lambda token: token.start)


def association(pair: int, left: int, right: int, windows: int) -> dict:
    pmi = math.log2(pair * windows / (left * right))
    logdice = 14 + math.log2(2 * pair / (left + right))
    table = [pair, left - pair, right - pair, windows - left - right + pair]
    expected = [left * right, left * (windows - right), (windows - left) * right,
                (windows - left) * (windows - right)]
    return {
        "pmi": round(pmi, 5),
        "logdice": round(logdice, 5),
        "log_likelihood": round(2 * sum(value * math.log(value * windows / expectation)
                                       for value, expectation in zip(table, expected, strict=True) if value), 5),
    }


def candidate_records(
    path: Path, wanted: set[str], version: str, min_count: int, max_documents: int | None, stats: dict,
) -> Iterator[dict]:
    document_count = 0
    token_count = 0
    windows = 0
    frequencies: Counter[TokenKey] = Counter()
    left_marginals: Counter[TokenKey] = Counter()
    right_marginals: Counter[TokenKey] = Counter()
    pairs: Counter[PairKey] = Counter()
    preps: Counter[tuple[TokenKey, str, str]] = Counter()
    exact_phrases: Counter[str] = Counter()
    examples: dict[tuple, list[dict]] = defaultdict(list)
    phrase_starts: dict[str, set[int]] = defaultdict(set)
    for word in wanted:
        parts = word.split()
        if len(parts) > 1:
            phrase_starts[parts[0]].add(len(parts))

    if not wanted:
        stats.update(documents=0, lexical_tokens=0, adjacent_lexical_windows=0, test_document_limit=max_documents)
        return

    for document, text, hepple, sentences in archive_documents(path, max_documents):
        document_count += 1
        def attest(key: tuple, first: Token, last: Token, sentence_start: int, sentence_end: int) -> None:
            sample = examples[key]
            if len(sample) < 3:
                # Keep a localizable excerpt instead of exporting the full sentence/document.
                context_start = max(sentence_start, first.start - 60)
                context_end = min(sentence_end, last.end + 60)
                sample.append({
                    "document": f"{document}.txt", "first_token_id": first.id, "last_token_id": last.id,
                    "start": first.start, "end": last.end, "surface": text[first.start:last.end],
                    "context_start": context_start, "context_end": context_end,
                    "context": text[context_start:context_end],
                })

        for sentence_start, sentence_end, tokens in sentence_tokens(text, hepple, sentences):
            for index, token in enumerate(tokens):
                if not token.lemma or not token.lemma[0].isalpha():
                    continue
                token_count += 1
                token_key = (token.lemma, token.pos)
                if token.lemma in wanted:
                    frequencies[token_key] += 1
                    attest(("frequency", token_key), token, token, sentence_start, sentence_end)
                phrase_lengths = (
                    phrase_starts.get(normalize_headword(text[token.start:token.end]), ())
                    if phrase_starts else ()
                )
                for length in phrase_lengths:
                    if index + length > len(tokens):
                        continue
                    last = tokens[index + length - 1]
                    phrase = normalize_headword(text[token.start:last.end])
                    if phrase in wanted:
                        exact_phrases[phrase] += 1
                        attest(("phrase", phrase), token, last, sentence_start, sentence_end)
                if index + 1 >= len(tokens):
                    continue
                right = tokens[index + 1]
                if not right.lemma or not right.lemma[0].isalpha():
                    continue
                right_key = (right.lemma, right.pos)
                windows += 1
                left_marginals[token_key] += 1
                right_marginals[right_key] += 1
                if (token.lemma in wanted or right.lemma in wanted) and (token.pos, right.pos) in LEXICAL_PAIRS:
                    pairs[token_key, right_key] += 1
                    attest(("pair", token_key, right_key), token, right, sentence_start, sentence_end)
                if token.lemma not in wanted or token.pos not in {"verb", "adjective", "noun"}:
                    continue
                pattern = None
                last = right
                if right.tag in WORD_PREPOSITIONS:
                    pattern = f"{token.pos}+{penn_pos(right.tag)}"
                    if (right.tag == "TO" and index + 2 < len(tokens)
                            and tokens[index + 2].pos == "verb" and token.pos in {"verb", "adjective"}):
                        pattern = f"{token.pos}+to-infinitive"
                        last = tokens[index + 2]
                elif right.tag == "VBG" and token.pos == "verb":
                    pattern = "verb+VBG"
                if pattern:
                    key = (token_key, right.lemma if right.tag in WORD_PREPOSITIONS else "VBG", pattern)
                    preps[key] += 1
                    attest(("pattern", *key), token, last, sentence_start, sentence_end)

    if document_count == 0:
        raise ValueError(f"{path}: no text with GrAF Hepple and sentence annotations found")

    def usage(kind: str, word: str, pos: str | None, expression: str, record_id: str,
              count: int, attestations: list[dict], **details) -> dict:
        return {
            "kind": "usage_candidate", "source_id": "oanc", "version": version, "url": OANC_URL,
            "source_record_id": f"{kind}:{record_id}", "extraction_method": "oanc_graf_hepple_sentence",
            "headword": word, "part_of_speech": pos, "usage_type": kind, "expression": expression,
            "verification_status": "corpus_attested",
            "details": {
                **details, "frequency": count, "attestations": attestations,
                "test_document_limit": max_documents, "analysis_scope": "OANC general English",
                "toeic_evidence": False, "sense_alignment": "unreviewed",
            },
        }

    for key, count in sorted(frequencies.items()):
        word, pos = key
        yield usage("FREQUENCY", word, pos, word, f"{word}:{pos}", count, examples["frequency", key],
                    lexical_tokens=token_count)
    for phrase, count in sorted(exact_phrases.items()):
        yield usage("PHRASE_ATTESTATION", phrase, None, phrase, phrase, count, examples["phrase", phrase])
    for (left_key, right_key), count in sorted(pairs.items()):
        if count < min_count:
            continue
        left, left_pos = left_key
        right, right_pos = right_key
        expression = f"{left} {right}"
        metrics = association(count, left_marginals[left_key], right_marginals[right_key], windows)
        for word, pos in sorted({left_key, right_key}):
            if word in wanted:
                yield usage("COLLOCATION", word, pos, expression, f"{word}:{left_key}:{right_key}", count,
                            examples["pair", left_key, right_key], combination=LEXICAL_PAIRS[left_pos, right_pos],
                            status="candidate_pending_dictionary_and_context_review", metrics=metrics,
                            left_frequency=left_marginals[left_key], right_frequency=right_marginals[right_key],
                            adjacent_lexical_windows=windows, minimum_count=min_count)
    for (key, connector, pattern), count in sorted(preps.items()):
        if count < min_count:
            continue
        word, pos = key
        expression = f"{word} {connector}"
        if pattern.endswith("to-infinitive"):
            expression += " + infinitive"
        yield usage("COLLIGATION", word, pos, expression, f"{word}:{connector}:{pattern}", count,
                    examples["pattern", key, connector, pattern], combination=pattern,
                    status="candidate_pending_grammar_review", minimum_count=min_count)

    stats.update(documents=document_count, lexical_tokens=token_count, adjacent_lexical_windows=windows,
                 test_document_limit=max_documents)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="OANC GrAF tar archive")
    parser.add_argument("--targets", action="append", required=True, type=Path, help="JSONL containing headword")
    parser.add_argument("--version", default="datasets-2026-09-25")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-count", default=5, type=int)
    parser.add_argument("--max-documents", type=int, help="Limit for adapter QA only")
    args = parser.parse_args()
    if args.min_count < 2 or (args.max_documents is not None and args.max_documents < 1):
        parser.error("--min-count must be >=2 and --max-documents must be >=1 if provided")
    stats: dict = {}
    count = write_jsonl(args.output, candidate_records(
        args.input, targets(args.targets), args.version, args.min_count, args.max_documents, stats
    ))
    print(f"OANC: {stats['documents']} annotated documents, {stats['lexical_tokens']} lexical tokens, "
          f"{count} candidate records")


if __name__ == "__main__":
    main()
