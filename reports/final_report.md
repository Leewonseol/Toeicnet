# 해커스 TOEIC VOCA × 보카바이블 B 실행 보고서

사용자 제공 Anki 본 단어와 해커스 뒷단어 PDF를 통합했다. Anki DAY 01–30의 빈출단어 **1,241건**과 뒷단어 PDF **120쪽**에서 원본 이미지로 대조한 **3,837건**을 출처별로 보존했다. 원천 출현은 총 **5,078건**이며 고유 표기는 두 출처에 공통으로 있는 두 항목을 합쳐 **5,076개**다. [OCR 검증](ocr_validation.md) · [원천 자료](source_coverage.md)

PDF 출현 **3,777건**의 DAY·정규화 표제어·교재 구간을 Anki 보조 덱과 대조했다. 인쇄 페이지 숫자는 스캔에서 확인할 수 있는 경우 기록하고, 잘린 27쪽은 사유와 PDF 페이지를 보존했다. [출처 목록](../SOURCES.md#anki와-pdf-출처-대조)

## 산출물과 의미 검증 진척

- [SQLite](../data/processed/toeic.db) 및 [어휘 CSV](../data/processed/vocabulary.csv)
- [어휘 연결망](../data/processed/vocabulary.graphml)
- [PART 1–3 학습 노트](../notes/README.md) 및 [자체 60일 일정](../notes/schedule.md)
- [원천 출현별 의미 검토 상태](../data/processed/semantic_coverage.csv)
- [실행 결과와 현재 커밋](final_execution.generated.md) 및 [분류별 집계](database.generated.md)

영영사전 두 곳의 근거를 확인한 의미만 교차 검증으로 표시한다. 한국어 뜻은 독립적으로 판단하고 문맥 의존, 부분 대응과 미검증을 구분한다. 검증된 개별 의미의 수와 그 의미가 연결된 원천 출현 수는 각각 계산한다. WordNet, Wiktextract 및 OANC의 전체 원천 대상 분석 후보는 검토 상태를 유지한다. [정의 검증 기준](definition_validation.md)

## 저장소

재현 코드, 처리 방법과 공개 자료의 출처 기록을 비공개 `main`에 반영한다. 원본 PDF, Anki 덱, 어휘 출현과 사전 후보를 포함하는 생성물은 로컬에 보관한다. [GitHub 저장소](https://github.com/Leewonseol/Toeicnet)
