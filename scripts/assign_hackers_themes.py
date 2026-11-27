"""Link image-reviewed occurrences to confirmed Hackers DAY themes."""
import argparse
from collections import defaultdict
from pathlib import Path
import re

from analysis_review import checked_relation
from review_common import date_field, jsonl_records, load_catalog, normalized_lemma, write_jsonl


def confirmed_themes(rows, catalog, date, confirmed_days):
    topics = catalog["hackers_toc"]["day_topics"]
    groups = defaultdict(list)
    for _, record in rows:
        if (record.get("source_id") == "hackers_back" and record.get("review_status") == "image_reviewed"
                and record.get("day") in confirmed_days and record.get("source_sha256")):
            key = (normalized_lemma(record["headword"]), record.get("homonym_key") or "", record["day"])
            groups[key].append(record)
    for (_, homonym_key, day), occurrences in sorted(groups.items()):
        topic = topics.get(day) or topics.get(str(day))
        if not topic:
            raise ValueError(f"No catalog theme for DAY {day:02}")
        theme_key = re.sub(r"[^a-z]+", "-", topic.lower()).strip("-")
        label = "채용" if day == 1 else topic
        evidence = [
            {
                "source_id": item["source_id"], "url": None, "source_record_id": str(item["source_record_id"]),
                "extraction_method": "human_pdf_image_review",
                "verification_date": date, "relation_match": "matched", "sha256": item["source_sha256"],
                "note": f"원본 이미지에서 DAY {day:02} 출현을 확인. 연결은 교재의 학습 단원을 나타냄.",
            }
            for item in occurrences
        ]
        evidence.append({
            "source_id": "hackers_toc", "url": catalog["hackers_toc"]["url"],
            "source_record_id": f"DAY {day:02}", "extraction_method": "public_course_index_review",
            "verification_date": date, "relation_match": "matched", "note": f"공식 강의 목차 DAY {day:02} 주제 {topic}",
        })
        yield checked_relation({
            "kind": "relation", "module": "lexical_semantics", "relation_type": "BELONGS_TO_THEME",
            "status": "source_attested", "verification_date": date,
            "from": {"node_type": "WORD", "headword": occurrences[0]["headword"], "homonym_key": homonym_key or None},
            "to": {"node_type": "THEME", "key": f"hackers:day{day:02}:{theme_key}", "label": label},
            "attributes": {"book_day": day, "classification_basis": "reviewed_textbook_unit"},
            "evidence": evidence,
        }, catalog)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="+", type=Path)
    parser.add_argument("--catalog", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--verification-date", required=True)
    parser.add_argument("--confirmed-days", nargs="+", type=int, required=True,
                        help="DAYs whose actual PDF theme headers were cross-checked with the course index")
    args = parser.parse_args()
    if not all(1 <= day <= 30 for day in args.confirmed_days):
        parser.error("confirmed DAYs must be in 01–30")
    date = date_field({"verification_date": args.verification_date})
    count = write_jsonl(args.output, confirmed_themes(
        jsonl_records(args.input), load_catalog(args.catalog), date, set(args.confirmed_days),
    ))
    print(f"{count} reviewed textbook theme memberships")


if __name__ == "__main__":
    main()
