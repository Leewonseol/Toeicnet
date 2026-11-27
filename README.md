# Toeicnet 학습 자료 바로가기

rebuild-v2 결과(규칙 v3.1, Anki 덱 항목 5,071개 · 본 단어 1,241). 표는 GitHub에서 표로 보이도록 교재 DAY별로 나눴다. 한 DAY 폴더에 그 DAY의 모든 덱(빈출·기초·800·900) 항목이 들어 있다. `korean_textbook` 열은 해커스 교재의 한국어 뜻으로, 비공개 저장소에 개인 학습용으로 둔 것이다. 정확도와 한계는 [재구축 보고서](reports/rebuild_v2_report.md), 출처·라이선스와 DAY별 행 수는 [vocabulary/README.md](vocabulary/README.md).

**DAY:** [01](vocabulary/days/DAY01) · [02](vocabulary/days/DAY02) · [03](vocabulary/days/DAY03) · [04](vocabulary/days/DAY04) · [05](vocabulary/days/DAY05) · [06](vocabulary/days/DAY06) · [07](vocabulary/days/DAY07) · [08](vocabulary/days/DAY08) · [09](vocabulary/days/DAY09) · [10](vocabulary/days/DAY10) · [11](vocabulary/days/DAY11) · [12](vocabulary/days/DAY12) · [13](vocabulary/days/DAY13) · [14](vocabulary/days/DAY14) · [15](vocabulary/days/DAY15) · [16](vocabulary/days/DAY16) · [17](vocabulary/days/DAY17) · [18](vocabulary/days/DAY18) · [19](vocabulary/days/DAY19) · [20](vocabulary/days/DAY20) · [21](vocabulary/days/DAY21) · [22](vocabulary/days/DAY22) · [23](vocabulary/days/DAY23) · [24](vocabulary/days/DAY24) · [25](vocabulary/days/DAY25) · [26](vocabulary/days/DAY26) · [27](vocabulary/days/DAY27) · [28](vocabulary/days/DAY28) · [29](vocabulary/days/DAY29) · [30](vocabulary/days/DAY30)

| 자료 | DAY 폴더 안의 파일 | 전체 묶음 |
| --- | --- | --- |
| 핵심 표제어·한국어 뜻·영어 정의 | `headwords.csv` | [Drive csv/headwords.csv](https://drive.google.com/file/d/1v9uW0fkMxckI2e6cEzhikxUuKdtTks-0/view) |
| 형태론 | `derivations.csv` | [접두사](vocabulary/morphology/prefixes.csv) · [접미사](vocabulary/morphology/suffixes.csv) · [어기](vocabulary/morphology/roots.csv) |
| 어원론 | `historical_roots.csv` | [공통 PIE 어근 집단](vocabulary/etymology/shared_origins.csv) |
| 어휘 의미론 | `synonyms.csv` · `antonyms.csv` · `themes.csv` | – |
| 어휘 결합 및 용법 | `collocations.csv` · `colligations.csv`(OANC 미검토 후보) · `idioms.csv` | – |
| 보카바이블 PART 1–3 | – | Drive [PART 1](https://drive.google.com/file/d/1IJY-y1h0BRzh3sIjRk4XAylEzhj7Gk2-/view) · [PART 2](https://drive.google.com/file/d/1VJm2o5uSFRlNuQHBRdayYTmfC6Mxnazv/view) · [PART 3](https://drive.google.com/file/d/1uekB3q0khuUJgq4XEPNkEUPLuPZOULpR/view) |
| Anki 다운로드 | – | Drive [APKG 1,776장](https://drive.google.com/file/d/1Zt33cPMJ3XDEyUwkNlfomW9VeViwQ_aa/view) · [덱별 TSV](https://drive.google.com/drive/folders/1Musi9p4IWJYA6yJqMf538BeHDey46zza) |
| 전체 데이터베이스 | – | Drive [SQLite·전체 JSONL(분할)](https://drive.google.com/drive/folders/1EC0-NvM6nIwTJq06T21VHE_aDwZZ9sub) · [합치는 방법](https://drive.google.com/file/d/1nrQIeCG5OXU0ue1MKbFfu2bm-keYHtt_/view) |
| 검토 대기열 | `pending.csv` | [모델 검토 판정](vocabulary/review/model_review.jsonl) · [기준 판정](vocabulary/review/gold_sample_and_holdout.jsonl) |

PDF 뒷단어 3종(120쪽)은 OCR과 페이지 이미지 확인으로 Anki 뒷단어와 대조했다. `headwords.csv`의 `pdf_status`·`pdf_page`·`pdf_pos` 열과 [pdf_crosscheck.csv](vocabulary/review/pdf_crosscheck.csv)에 결과가 있다. Anki 뒷단어 3,830개 중 3,828개를 PDF에서 확인했고(4개는 손으로 지운 줄), PDF에만 있는 9개를 각 DAY 표에 `pdf_only_not_in_anki`로 넣었다. 다음 배치 작업은 각 DAY의 `pending.csv`부터 시작한다. 배치가 끝날 때마다 `python scripts/rebuild_export.py`로 `vocabulary/`를 다시 만들어 커밋하고 `exports/rebuild-v2/`를 Drive에 올린다.

# 해커스 TOEIC VOCA × 보카바이블 B

해커스 DAY 01–30의 원천 항목, 의미별 사전 근거, 형태·어원·의미·용법 관계를 SQLite에서 연결합니다. 같은 어휘의 출현 위치는 모두 보존하고, 동형이의어는 검토된 식별자로 분리합니다. WordNet, Wiktextract, OANC에서 추출한 후보는 사람이나 검토 담당 에이전트가 의미를 대조한 뒤 학습 자료에 반영합니다.

현재 진행 수치와 제약은 [실행 보고서](reports/final_report.md)를 참조하세요. 외부 자료의 버전, 체크섬과 열람 범위는 [자료 목록](SOURCES.md), [이용 조건](LICENSES.md), [다운로드 기록](sources/manifest.json)에 있습니다.

## 실행 환경

Python 3.11+, SQLite 3.37+, Poppler(`pdfinfo`, `pdftoppm`), Tesseract 5와 `eng`, `kor` 모델을 사용합니다. 설치된 Tesseract 모델 경로는 `--tessdata-dir`로 지정할 수 있습니다.

```sh
python -m pip install -r requirements.txt
python scripts/download_datasets.py oewn kaikki gcide oanc
python -m unittest discover -s tests
```

## 원천 수집과 검토

현재 원천은 사용자가 제공한 Anki 본 단어와 뒷단어 PDF입니다. Anki 덱은 `python scripts/import_anki.py <.apkg 또는 .zip> --inspect`로 노트 수, 덱 및 필드 식별자를 확인합니다. 암호화 ZIP은 대화형 `--ask-password`를 지원합니다. 이번에 확보한 덱의 범위와 PDF 대조 결과는 [자료 목록](SOURCES.md#anki와-pdf-출처-대조)에 있습니다.

```sh
python scripts/import_anki.py sources/quizlet/노랭이.apkg \
  --model-id 1769220488003 --headword-field 예문 --meaning-field 뜻 \
  --deck-prefix '노랭이::01.빈출단어' --expected-count 1241 --require-all-days \
  --output data/intermediate/anki-core.jsonl --manifest data/intermediate/anki-core-manifest.json
```

PDF 3종은 `sources/hackers/`에 둡니다. 스크립트는 최초 요청 파일명과 아래 Drive 파일명을 모두 인식하며, 기록에는 실제 입력 파일명을 사용합니다.

| 파일 | 범위 | PDF 페이지 |
| --- | --- | ---: |
| `해커스토익 뒷단어 데이 1-10(2).pdf` | DAY 01–10 | 40 |
| `해커스 뒷단어 데이 11–15(1).pdf` | DAY 11–15 | 20 |
| `해커스 뒷단어 16-30(1).pdf` | DAY 16–30 | 60 |

이번 실행의 전 페이지 OCR에는 PDFium 회색조 185 DPI와 PSM 11을 사용했습니다. `pypdfium2`와 `Pillow`를 설치하고 `--renderer pdfium --dpi 185 --psm 11 --output-dir data/intermediate/ocr_fast`를 추가하면 같은 설정을 사용할 수 있습니다.

OCR은 페이지 이미지, TXT, 좌표가 있는 TSV를 체크포인트에 보존합니다. `data/intermediate/ocr/`의 `candidates.pages.csv`와 `candidates.entries.csv`를 `reviewed.pages.csv`와 `reviewed.entries.csv`로 옮겨 페이지별 글자·누락·중복·줄바꿈을 이미지와 대조합니다. 페이지 번호, DAY, 검토 완료 표시, 검토한 항목 수를 채웁니다. 인쇄 페이지가 잘려 있으면 판독 불가 사유를 남깁니다. 품사나 구분이 불확실한 경우 교재 표기와 검토 메모를 보존합니다.

```sh
python scripts/normalize.py --only ocr --ocr-dir data/intermediate/ocr_fast \
  --reviewed-pages data/intermediate/ocr_fast/reviewed.pages.csv \
  --reviewed-entries data/intermediate/ocr_fast/reviewed.entries.csv
```

페이지별 검토를 분담했다면 `merge_ocr_reviews.py`로 기준 검토 CSV와 검토 배치 JSONL을 합칩니다. 같은 원본 페이지를 중복으로 가져오면 중단합니다.

## 후보 추출과 의미 검토

```sh
python scripts/import_wordnet.py --input data/external/english-wordnet-2025.xml.gz \
  --targets data/intermediate/normalized.jsonl --targets data/intermediate/anki-core.jsonl \
  --output data/intermediate/wordnet.jsonl
python scripts/import_wiktextract.py --input data/external/raw-wiktextract-data.jsonl.gz \
  --version enwiktionary-2026-10-01 --targets data/intermediate/normalized.jsonl \
  --targets data/intermediate/anki-core.jsonl \
  --output data/intermediate/wiktextract.jsonl --schema-report data/intermediate/wiktextract-schema.json
python scripts/import_gcide.py --input data/external/gcide-0.54.tar.xz --version 0.54 \
  --targets data/intermediate/normalized.jsonl --targets data/intermediate/anki-core.jsonl \
  --output data/intermediate/gcide.jsonl
python scripts/import_corpus.py --input data/external/OANC_GrAF.tgz \
  --targets data/intermediate/normalized.jsonl --targets data/intermediate/anki-core.jsonl \
  --output data/intermediate/oanc.jsonl
python scripts/align_senses.py data/intermediate/normalized.jsonl data/intermediate/anki-core.jsonl \
  --candidates data/intermediate/wordnet.jsonl data/intermediate/wiktextract.jsonl \
  --output data/intermediate/alignment.jsonl
```

[검토 입력 형식](analysis/README.md)에 따라 개별 의미 검토 기록을 작성합니다. 영영사전의 비교는 같은 품사와 의미에서 확인된 독립 출처별로 기록합니다. 한국어 뜻은 별도 근거로 판단하며 원천 뜻풀이는 출현 기록에 보존합니다. 사용 통계에서 선별한 후보에는 문맥과 출처 좌표를 남깁니다. 공식 TOEIC 공개 문항에서 확인한 용례에는 공식 문항 위치를 요구합니다.

## SQLite와 학습 자료

```sh
python scripts/build_database.py --manifest sources/manifest.json \
  --intake-manifest data/intermediate/normalized-manifest.json \
  --anki-manifest data/intermediate/anki-core-manifest.json \
  --intake data/intermediate/normalized.jsonl --intake data/intermediate/anki-core.jsonl \
  --candidates data/intermediate/wordnet.jsonl \
  --candidates data/intermediate/wiktextract.jsonl --candidates data/intermediate/gcide.jsonl \
  --candidates data/intermediate/oanc.jsonl \
  --review data/intermediate/verified-senses.jsonl --review data/intermediate/reviewed-relations.jsonl
python scripts/build_network.py
python scripts/export_wordnet_relations.py --db data/processed/toeic.db --output-dir data/processed/wordnet
python scripts/generate_study_notes.py
python scripts/export_semantic_coverage.py
python scripts/validate_database.py --core-source anki --require-coverage
python scripts/report_database.py
```

독립적으로 검토된 PDF 주제 연결은 `assign_hackers_themes.py`로 생성할 수 있습니다. `--confirmed-days`에는 OCR 이미지에서 표제 및 DAY를 대조한 단원만 지정합니다.

SQLite DB에는 원천 출현, 의미, 독립적인 영·한 검증 결과, 후보, 노드·에지와 근거를 정규화하여 저장합니다. CSV·JSONL과 GraphML은 `data/processed/`, 학습 노트와 60일 일정은 `notes/`에 생성합니다. `semantic_coverage.csv`와 `semantic_coverage_summary.json`은 각 출현에 의미 검증이 연결됐는지와 후보만 있는지를 보여 줍니다.

`external_lexical_evidence`는 원천 어휘 표기와 일치하는 공개 사전·말뭉치 기록을 어휘 ID에 연결합니다. 원천 레코드, 버전과 교재 의미의 정렬 상태를 확인할 수 있습니다. 핵심 노트의 공개 사전 정의, OANC 용례 위치와 공식 샘플 문항 위치도 이 보기에서 가져옵니다. `data/processed/wordnet/`에는 릴리스의 의미와 Synset 식별자, 원천 관계와 라이선스가 있습니다.

`derive_wiktextract_inflections.py`는 두 표제어가 원천에 있고 품사 조건을 만족할 때 같은 릴리스의 굴절형 목록과 `form-of` 항목을 대조합니다. 문법 자질이 양쪽에서 일치한 굴절 관계와 근거를 만들어 분석 입력에 추가할 수 있습니다.

원본, OCR, 사전 후보와 원천 정보를 포함하는 생성물은 로컬에서 관리합니다. Git은 코드, 문서, 공개 자료의 체크섬과 이용 근거를 추적합니다.

## Batch RAG 검증

`scripts/batch_rag.py`는 기존 SQLite에 저장된 Anki·PDF 출현, 검증된 의미, 공개 사전과 말뭉치를 사용합니다. 표제어·품사 일치부터 검색하고 사전에 기록된 활용형과 변이형을 추가합니다. 각 사전 의미에 원천 ID와 버전을 유지합니다. 한국어 표기 일치, 사전 내 관계와 말뭉치 용례는 후보를 정렬하고 검토할 때 사용합니다.

| 등급 | 영어 정의 근거 |
| --- | --- |
| A | 지정된 독립 영영사전 두 곳 이상에서 확인 (선택 사항. 분석과 학습 자료 생성의 전제 조건이 아님) |
| B | 독립 공개 어휘 자료 두 곳 이상(WordNet, Wiktionary, GCIDE의 Webster 1913 계보)에서 같은 품사·개별 의미를 확인 |
| C | 단일 사전 출처에서 확인 |
| D | 후보가 있으며 의미 또는 출처 독립성 검토 필요 |
| E | 적용 가능한 사전 의미 근거 미확보 |

상용 사전 웹사이트의 직접 수집은 필수 과정에서 제외했습니다. 공개 데이터의 출처 계보는 의미 단위로 판정합니다. GCIDE의 `WordNet 1.5/1.6` 정의는 `globalwordnet` 계보이므로 WordNet과 함께 B등급 근거가 되지 않습니다. 문구가 같거나 거의 같은 정의(예: Webster 1913을 옮긴 Wiktionary 뜻풀이)도 한 출처로 셉니다.

영어 정의와 한국어 뜻은 각각 검증합니다. 말뭉치와 공식 TOEIC 샘플은 용법의 근거입니다. 공개 사전 B등급은 기존 지정 사전 교차 검증 통계와 분리합니다. SQLite의 `batch_rag_current`에서 마지막 전체 실행의 등급·근거·별도 한국어 상태를 확인할 수 있습니다.

```bash
python scripts/batch_rag.py prepare --top-k 12
python scripts/batch_rag.py pilot --top-k 12 \
  --gold data/intermediate/batch_rag/pilot_gold.jsonl \
  --model-decisions data/intermediate/batch_rag/decisions_pilot.jsonl
python scripts/batch_rag_archive_probe.py --source oewn
python scripts/batch_rag_archive_probe.py --source kaikki
python scripts/batch_rag.py full --top-k 12 \
  --model-decisions data/intermediate/batch_rag/all_decisions.jsonl \
  --module-reviews data/intermediate/batch_rag/module_model_judgments.jsonl \
  --archive-observations data/intermediate/batch_rag/archive/oewn.archive_candidates.jsonl \
  --archive-observations data/intermediate/batch_rag/archive/kaikki.archive_candidates.jsonl
python scripts/batch_rag_study.py \
  --assessments data/intermediate/batch_rag/full/assessments.jsonl
```

사전 접근성 기록은 `python scripts/source_access_probe.py --from-json --db data/processed/toeic.db`로 요청 없이 DB에 옮깁니다. 기본 실행은 상용 사전 웹페이지와 이미 차단이 기록된 출처에 요청하지 않으며, 각각 `--allow-commercial-web`, `--recheck-blocked`를 명시해야 다시 요청합니다. HTTP 상태, robots.txt(프로젝트 UA와 Anthropic 에이전트 토큰), 확인 페이지, 정의 표지 유무를 출처별로 기록하고 이용 권한은 따로 둡니다. 403, robots 차단, 인증 요구에서는 해당 출처의 요청을 중단하고, 429·5xx만 지수 백오프로 두 번까지 재시도합니다. 응답 본문은 저장하지 않습니다. [최근 점검 결과](reports/source_access.md)

`prepare`는 고정 100개 표본의 검색 결과와 모델 입력을 생성합니다. 독립 검토로 만든 기준 JSONL과 실제 판정 JSONL의 형식은 각각 `batch_rag_benchmark.py`와 `batch_rag_verify.py`에서 확인할 수 있습니다. `pilot`에서 기준 표본과 대조한 결과가 통과하면 같은 DB와 설정으로 `full`을 실행합니다. 같은 입력과 설정으로 명령을 반복하면 SQLite 체크포인트에서 재개합니다. 다음 배치용 입력은 `prepare --review-queue data/intermediate/batch_rag/full/review_queue.jsonl --review-limit 100 --top-k 12`로 생성할 수 있습니다.

선택 사항인 `batch_rag_model.py`는 이용 권한과 호출 한도를 확인한 로컬 모델 명령에 검색 자료를 배치로 전달합니다. 학습 노트와 Anki TSV, 항목별 검토 대기열은 원천이나 사전의 개별 기록이 포함되므로 로컬에 보관합니다. [실행 및 평가 결과](reports/batch_rag_report.md)

## rebuild-v2 재구축

기존 OCR·DB·분석 결과를 전제로 하지 않고 Anki 원천과 공개 데이터에서 다시 만든 경로입니다. 결과와 정확도는 [재구축 보고서](reports/rebuild_v2_report.md)에 있습니다.

```sh
python scripts/download_datasets.py gcide oewn oanc kaikki
# 덱별 추출: import_anki.py --deck-prefix '노랭이::01.빈출단어' 등 4개 덱 → data/intermediate/anki-{core,basic,800,900}.jsonl
python scripts/rebuild_sources.py                 # 원천 항목표, 중복·관계 주석 감사
python scripts/extract_lexicon.py                 # WordNet·Wiktextract·GCIDE 대상 레코드
python scripts/extract_korean_entries.py          # Wiktionary 한국어 항목(의미 선택·한국어 검토용)
python scripts/import_corpus.py --input data/external/OANC_GrAF.tgz \
  --targets data/rebuild/corpus_targets.jsonl --output data/rebuild/oanc_usage.jsonl
python scripts/rebuild_sample.py                  # 고정 100개 표본
python scripts/rebuild_analyze.py --items data/rebuild/sample100.jsonl --output data/rebuild/sample.jsonl
python scripts/rebuild_evaluate.py --predictions data/rebuild/sample.jsonl --output data/rebuild/sample_eval.json
python scripts/rebuild_analyze.py --output data/rebuild/full.jsonl \
  --model-review data/rebuild/gold/core_model_review.jsonl
python scripts/rebuild_outputs.py --analysis data/rebuild/full.jsonl
```

B등급은 WordNet 의미와 Wiktionary 의미가 같은 품사·의미로 정렬되고 교재 한국어 뜻에 해당할 때만 줍니다. 규칙 판정과 모델 검토 판정은 등급 표시와 카드 덱에서 구분합니다. GCIDE는 근거 계보 확인에만 쓰고 B의 근거로 쓰지 않습니다. 카드·노트·항목별 결과에는 교재 한국어 뜻이 들어 있으므로 로컬에만 둡니다.
