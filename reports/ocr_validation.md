# 해커스 뒷단어 OCR 검증

2026-11-27 사용자가 연결한 Google Drive에서 실제 스캔 PDF 3종을 확보했다. Poppler `pdfinfo`로 총 120페이지를 확인했다. 파일명 마지막의 `(2)`가 프로젝트 요청에 적힌 이름과 달라 OCR 원장과 어휘 출현 기록에 Drive의 실제 원본 파일명을 보존했다.

| `sources/hackers/`의 실제 원본 파일명 | DAY | OCR 완료 / PDF 페이지 | 자동 후보 |
|---|---:|---:|---:|
| 해커스토익 뒷단어 데이 1-10(2).pdf | 01–10 | 40 / 40 | 850 |
| 해커스 뒷단어 데이 11–15(1).pdf | 11–15 | 20 / 20 | 384 |
| 해커스 뒷단어 16-30(1).pdf | 16–30 | 60 / 60 | 1,252 |
| 합계 | 01–30 | 120 / 120 | 2,486 |

Tesseract 5.5.0과 공식 `tessdata_fast` 4.1.0 영어·한국어 모델을 사용했다. 초기 검토에 Poppler 26.05.0으로 만든 300 dpi 이미지를 사용했고 전 페이지 OCR은 PDFium 회색조 185 dpi 및 Tesseract PSM 11 설정으로 실행했다. 같은 원본과 설정으로 재시도하면 페이지 체크포인트가 재사용된다. [tessdata_fast 4.1.0](https://github.com/tesseract-ocr/tessdata_fast/tree/4.1.0)

첫 PDF 1페이지의 이미지에서 28개 표제어를 확인했다. 빠른 OCR의 고유 표제어 후보 21개 중 대소문자를 무시한 철자가 일치한 것은 18개였다. 자동 후보에는 체크박스 및 배경 인쇄 흔적, 단어 사이 공백 소실, 잘못 분리된 영어·한국어 열과 한국어 뜻 일부 누락이 확인됐다. 이 표본만으로 전 페이지의 정확도를 산정할 수 없다. 자동 후보는 이미지 대조 전까지 검토 파일에 남긴다. OCR 실행 쪽수는 `data/intermediate/ocr_fast/manifest.json`에서, 이미지 대조 쪽수 및 정규화된 원천 행은 `data/intermediate/normalized-manifest.json`에서 확인한다.

## 120쪽 이미지 대조 결과

DAY 01–30의 전체 120쪽을 원본 이미지와 대조해 출현 3,837건을 기록했다. 같은 PDF 페이지에서 유니코드·공백·아포스트로피·대소문자를 정규화한 표제어 출현을 비교했다. 반복 출현도 각각 셌다.

| 원본 범위 | 대조 페이지 | 이미지 대조 출현 | 자동 후보 | 철자 일치 |
|---|---:|---:|---:|---:|
| DAY 01–10 | 40 | 1,280 | 850 | 705 |
| DAY 11–15 | 20 | 640 | 384 | 313 |
| DAY 16–30 | 60 | 1,917 | 1,252 | 1,076 |
| 합계 | 120 | 3,837 | 2,486 | 2,094 |

자동 후보에서 철자가 일치하지 않거나 누락된 출현은 1,743건이었다. 같은 쪽에서 일치하는 출현을 찾지 못한 후보는 392건이었다. 이 수치는 표제어 철자 비교에 한정한다. 인쇄 쪽수 영역이 잘려 숫자를 읽을 수 없는 27쪽은 빈값과 검토 메모를 남겼으며 PDF 쪽수는 전 페이지에서 보존했다.

Anki는 이미지 대조에 보조 자료로 사용했다. 전수 대조 완료 전 사용했던 후보 목록은 로컬 기록으로 보존한다. [Anki와 PDF 출처 대조](../SOURCES.md#anki와-pdf-출처-대조)

## 검토 절차

1. 실제 PDF를 배치하고 `python scripts/extract_ocr.py --tessdata-dir data/external/tessdata`를 실행한다. PDF 쪽수는 1부터 센다. 출력 폴더 `data/intermediate/ocr/`에 SHA-256과 렌더링 설정으로 구분한 페이지 이미지, 텍스트, TSV 좌표 및 신뢰도와 후보 CSV를 보관한다. 빠른 옵션은 선택 의존성 설치 후 `--renderer pdfium --dpi 185 --psm 11 --output-dir data/intermediate/ocr_fast`로 실행한다. 선택 의존성은 `pypdfium2`와 `Pillow`다.
2. `candidates.pages.csv`와 `candidates.entries.csv`를 각각 `reviewed.pages.csv`와 `reviewed.entries.csv`로 복사한다. 각 PDF 페이지의 이미지를 기준으로 DAY, 인쇄 페이지, 표제어, 한국어 뜻, 품사, 교재 분류를 확인한다. 필요한 줄 합치기와 철자 수정, 빠진 항목 추가, 잘못 분리된 항목 삭제를 수행한다. 원본에 실제로 반복 출현하는 항목은 유지하고 같은 페이지에서 고유한 `entry_index`를 지정한다.
3. 페이지별 `reviewed_entries`에 실제 출현 건수를 기록하고 `review_status`에 `image_reviewed`를 입력한다. 인쇄 페이지 식별이 불가능하거나 어휘가 없는 페이지는 `review_note`에 이유를 남긴다. 각 항목의 유형은 `word`, `compound`, `phrase`, `idiom`, `phrasal_verb` 중에서 선택한다. OCR에서 누락된 항목을 추가할 때 OCR 좌표와 confidence는 비워 둔다.
4. `python scripts/normalize.py`를 실행한다. 검토되지 않은 페이지나 건수가 맞지 않는 페이지, 중복된 출현 식별자가 있는 경우 정규화를 중단한다. OCR만 독립적으로 처리한 경우 `--only ocr`를 사용한다. 진행 중인 OCR 캐시에서 이미 대조한 쪽만 가져오려면 같은 OCR 옵션으로 `--cached-only`를 실행하고 정규화에서 `--ocr-snapshot --allow-partial-ocr-review`를 지정한다. 정규화 매니페스트에 전체/검토 쪽수와 부분 입력 상태를 기록한다.
