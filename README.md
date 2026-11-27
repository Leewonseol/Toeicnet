# 해커스 TOEIC VOCA × 보카바이블 B

해커스 DAY 01–30의 원천 항목, 의미별 사전 근거, 형태·어원·의미·용법 관계를 SQLite에서 연결합니다. 같은 어휘의 출현 위치는 모두 보존하고, 동형이의어는 검토된 식별자로 분리합니다. WordNet, Wiktextract, OANC에서 추출한 후보는 사람이나 검토 담당 에이전트가 의미를 대조한 뒤 학습 자료에 반영합니다.

현재 진행 수치와 제약은 [실행 보고서](reports/final_report.md)를 참조하세요. 외부 자료의 버전, 체크섬과 열람 범위는 [자료 목록](SOURCES.md), [이용 조건](LICENSES.md), [다운로드 기록](sources/manifest.json)에 있습니다.

## 실행 환경

Python 3.11+, SQLite 3.37+, Poppler(`pdfinfo`, `pdftoppm`), Tesseract 5와 `eng`, `kor` 모델을 사용합니다. 설치된 Tesseract 모델 경로는 `--tessdata-dir`로 지정할 수 있습니다.

```sh
python -m pip install -r requirements.txt
python scripts/download_datasets.py oewn kaikki oanc
python -m unittest discover -s tests
```

## 원천 수집과 검토

허가받은 Quizlet 세트 `324678752`의 UTF-8 TSV·CSV·TXT를 `sources/quizlet/`에 둡니다. 원본 형식이 헤더가 없는 경우 표제어와 뜻 두 열을, 헤더가 있는 경우 DAY·품사·항목 구분이 확인된 열을 가져옵니다. 세트 화면에서 확인한 항목 수와 가져온 행 수가 일치해야 합니다.

```sh
python scripts/import_quizlet.py sources/quizlet/324678752.tsv \
  --expected-count 1224 --count-evidence 'Quizlet 세트 324678752 화면, 2026-11-27'
OMP_THREAD_LIMIT=1 python scripts/extract_ocr.py --tessdata-dir data/external/tessdata --jobs 2
```

이용 권한이 확인된 Anki 덱도 별도 원천으로 읽을 수 있습니다. 먼저 `python scripts/import_anki.py <.apkg 또는 .zip> --inspect`로 실제 노트 수와 카드 수, 덱·필드 식별자를 확인합니다. 암호화 ZIP은 대화형 `--ask-password`를 지원합니다. 가져오기 때 본 단어에 해당하는 덱과 노트 필드를 명시합니다. Anki 출현에는 별도 출처 ID가 부여됩니다. 이번에 확보한 덱의 원천 범위와 PDF 대조 결과는 [자료 목록](SOURCES.md#anki-대체-입력-출처-대조)을 참조하세요. 이 실행의 대체 덱은 다음과 같이 가져왔습니다.

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
python scripts/normalize.py
```

## 후보 추출과 의미 검토

```sh
python scripts/import_wordnet.py --input data/external/english-wordnet-2025.xml.gz \
  --targets data/intermediate/normalized.jsonl --output data/intermediate/wordnet.jsonl
python scripts/import_wiktextract.py --input data/external/raw-wiktextract-data.jsonl.gz \
  --version enwiktionary-2026-10-01 --targets data/intermediate/normalized.jsonl \
  --output data/intermediate/wiktextract.jsonl --schema-report data/intermediate/wiktextract-schema.json
python scripts/import_corpus.py --input data/external/OANC_GrAF.tgz \
  --targets data/intermediate/normalized.jsonl --output data/intermediate/oanc.jsonl
python scripts/align_senses.py data/intermediate/normalized.jsonl \
  --candidates data/intermediate/wordnet.jsonl data/intermediate/wiktextract.jsonl \
  --output data/intermediate/alignment.jsonl
```

[검토 입력 형식](analysis/README.md)에 따라 개별 의미 검토 기록을 작성합니다. 영영사전의 비교는 같은 품사와 의미에서 확인된 독립 출처별로 기록합니다. 한국어 뜻은 별도 근거로 판단하며 원천 뜻풀이는 출현 기록에 보존합니다. 사용 통계에서 선별한 후보에는 문맥과 출처 좌표를 남깁니다. 공식 TOEIC 공개 문항에서 확인한 용례에는 공식 문항 위치를 요구합니다.

## SQLite와 학습 자료

```sh
python scripts/build_database.py --manifest sources/manifest.json \
  --intake-manifest data/intermediate/normalized-manifest.json \
  --intake data/intermediate/normalized.jsonl --candidates data/intermediate/wordnet.jsonl \
  --candidates data/intermediate/wiktextract.jsonl --candidates data/intermediate/oanc.jsonl \
  --review data/intermediate/verified-senses.jsonl --review data/intermediate/reviewed-relations.jsonl
python scripts/build_network.py
python scripts/generate_study_notes.py
python scripts/export_quizlet.py
python scripts/validate_database.py --quizlet-output exports/quizlet
python scripts/report_database.py
```

Anki 대체 입력을 병합할 때는 `--intake data/intermediate/anki-core.jsonl --anki-manifest data/intermediate/anki-core-manifest.json`을 추가합니다. 독립적으로 검토된 PDF 주제 연결은 `assign_hackers_themes.py`로 생성할 수 있습니다. `--confirmed-days`에는 OCR 이미지에서 표제 및 DAY를 대조한 단원만 지정합니다.

SQLite DB에는 원천 출현, 의미, 독립적인 영·한 검증 결과, 후보, 노드·에지, 근거를 정규화하여 저장합니다. 분석별 SQL 뷰는 동일한 노드·에지에서 형태와 관계를 조회합니다. CSV·JSONL과 GraphML은 `data/processed/`, 학습 노트는 `notes/`, 이중언어·영어 정의 Quizlet TSV는 `exports/quizlet/`에 생성합니다. PART 2의 40일과 PART 3의 20일 일정은 프로젝트에서 정한 일정입니다. 자료가 부족한 날은 학습 분량을 비워 두고 근거 공백을 표시합니다.

원본, OCR, 사전 후보와 원천 정보를 포함하는 생성물은 로컬에서 관리합니다. Git은 코드, 문서, 공개 자료의 체크섬과 이용 근거를 추적합니다.
