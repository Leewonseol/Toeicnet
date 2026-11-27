# 검토 데이터 입력 형식

작업 중인 JSONL은 Git에서 제외되는 `data/intermediate/`에 저장한다. 원천 위치 정보는 `normalize.py`가 출력한 항목의 `source_id`와 `source_record_id`로 참조한다.

## 의미 정렬 및 검증

`align_senses.py`는 표제어와 품사가 일치하는 항목을 검토 목록으로 만든다. 동형이의어와 품사가 불명확한 항목에는 별도 상태를 표시한다. 후보 레코드와 원천 항목을 대조하여 개별 의미가 확인되면 아래 레코드를 작성한다. 한 출현 위치에 여러 의미가 함께 기록되어 있으면 같은 위치를 별도의 의미들에 연결할 수 있다.

| 필드 | 입력 내용 |
| --- | --- |
| `kind` | `sense` |
| `headword`, `part_of_speech`, `sense_key` | 표제어, 품사, 해당 표제어 안에서 안정적으로 사용할 의미 식별 키 |
| `homonym_key` | 역사적 기원 등 근거로 분리된 경우 원천 레코드와 같은 식별 키 |
| `occurrences` | 이 의미와 일치하는 출현 위치 목록. 각 위치에 `source_id`와 `source_record_id`를 입력한다. |
| `english_definition`, `status`, `definition_origin` | 정의, 검증 상태, 정의 작성 방식. 상용 사전을 참조한 정의는 직접 재구성하고 `paraphrase`를 사용한다. 적법하게 가공 가능한 공개 정의는 `open_source`를 사용할 수 있다. |
| `definition_evidence` | 영영 정의 검토의 근거 목록 |
| `alignment_evidence` | 외부 어휘 DB의 개별 의미를 정렬한 경우 그 근거 목록. `external_sense_id`를 추가한다. |
| `verified_korean_meaning`, `korean_status`, `korean_evidence` | 검증된 한국어 뜻, 한국어 검증 상태, 한국어 뜻 검토의 별도 근거 목록 |
| `translation_uncertainty_reason` | 의미 범위, 문맥 의존성, 대응어 부재 등 확인된 이유 |
| `verification_date` | 검토 날짜. `YYYY-MM-DD` 형식. |

근거 항목에는 `source_id`, `source_record_id`, `url`, `extraction_method`, `verification_date`, `note`를 입력하고 버전을 확인할 수 있으면 `version`을 추가한다. 공개 URL이 없는 PDF는 파일명과 페이지·항목 위치를 `source_record_id`에 기록할 수 있다. 의미 근거는 `matched_sense_key`를 같은 의미의 `sense_key`로 지정하고 `sense_match`에 `matched`, `uncertain`, `disagrees` 중 하나를 기록한다. `note`에 품사, 의미 범위, 문법 및 사용역 등 근거가 되는 차이를 기록한다.

영영 정의의 `cross_verified`는 설정에 등록된 독립 영영사전 그룹 두 곳 이상의 `matched` 근거를 요구한다. WordNet과 Wiktextract는 의미 정렬 및 단일 출처 확인에 사용할 수 있다. `disputed`에는 독립적인 출처와 불일치 근거를 남긴다. 한국어 뜻을 평가한 근거에는 `assessment_kind`를 추가한다. 지원 값은 `bilingual_dictionary`, `korean_usage`, `bilingual_semantic_review`다. 한국어 상태가 `verified`인 경우에만 `verified_korean_meaning`을 기록한다. 원천 뜻은 출현 위치에 보존한다.

`verify_english_definitions.py`와 `verify_korean_translations.py`는 구조와 각 상태에 필요한 근거를 검사한다. 실제 사전 간 개별 의미 비교와 한국어 용례 분석은 근거를 작성할 때 수행한다.

```sh
python scripts/align_senses.py data/intermediate/normalized.jsonl \
  --candidates data/intermediate/oewn.jsonl data/intermediate/kaikki.jsonl \
  --output data/intermediate/alignment.jsonl
python scripts/verify_english_definitions.py data/intermediate/review_input.jsonl \
  --output data/intermediate/review_english.jsonl
python scripts/verify_korean_translations.py data/intermediate/review_english.jsonl \
  --output data/intermediate/reviewed_senses.jsonl
```

## 분석 모듈 관계

검토한 관계는 `kind=relation`으로 기록한다. `module`은 `morphology`, `etymology`, `lexical_semantics`, `lexical_usage` 중 하나다. `relation_type`, `from`, `to`, `attributes`, `status`, `evidence`, `verification_date`를 추가한다. 출발점과 도착점에 `node_type`을 지정한다. `WORD`에 `headword`와 해당 시 `homonym_key`를, `SENSE`에는 여기에 `part_of_speech`와 `sense_key`를 추가한다. 그 외 노드에는 안정적인 `key`와 표시용 `label`을 입력한다.

- 형태론의 `DERIVED_FROM`은 파생어에서 어기로 연결한다. `affixes`, `source_pos`, `target_pos`, `meaning_change`, `form_change`를 입력한다. `INFLECTION_OF`는 굴절형에서 어휘로 연결하고 `features`에 문법적 특성을 기록한다. `COMPOUND_COMPONENT_OF`는 합성 요소에서 합성어로 연결한다.
- 어원론의 어근 관계에 기원 언어 `origin_language`, 역사 형식 `historical_form`, 과거 의미 `earlier_meaning`을 기록한다. 동계어에는 `shared_origin`과 `cognate_type`을 기록한다. 현대 접사와 역사적 접사의 노드 식별 키에는 각 분석 범위를 반영한다.
- 의미론의 동의·유의·반의 관계는 두 개별 의미를 연결한다. 상하위어나 부분·전체 관계에는 TOEIC 학습에 도움이 되는 이유를 `study_rationale`로 남긴다. 공통 Synset 소속은 동의어 후보 선정에 활용한다. 문맥상 대체 가능성은 각각을 검토하여 기록한다.
- 용법의 연어와 문형은 해당 의미를 사용한다. 숙어 분류 `idiom_category`는 `preposition`, `adverb`, `verb`, `noun`으로 기록한다. 구동사에는 `base_verb`, `particle`, `transitivity`, `separability`, `pronoun_position`을 기록한다.

관계 근거의 `relation_match`와 `note`에 관계를 확인한 이유를 기록한다. `corpus_attested`는 용법 관계와 일치하는 말뭉치 자료를 요구한다. TOEIC 공식 공개 문항에서 확인한 용법은 `attributes.toeic_official`에 표시하고 해당 근거에 `item_locator`를 기록한다. 각 분석 스크립트는 `--include-candidates`로 외부 후보를 검토 대기 목록에 함께 포함할 수 있다.

```sh
python scripts/analyze_morphology.py data/intermediate/relations_input.jsonl \
  --output data/intermediate/morphology.jsonl
python scripts/analyze_etymology.py data/intermediate/relations_input.jsonl \
  --output data/intermediate/etymology.jsonl
python scripts/analyze_lexical_semantics.py data/intermediate/relations_input.jsonl \
  --output data/intermediate/lexical_semantics.jsonl
python scripts/analyze_lexical_usage.py data/intermediate/relations_input.jsonl \
  --output data/intermediate/lexical_usage.jsonl
```
