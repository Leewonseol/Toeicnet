# 해커스 TOEIC VOCA × 보카바이블 B 실행 보고서

2026-11-27 사용자 제공 Anki 대체 입력과 해커스 뒷단어 PDF를 사용해 통합 SQLite, 연결망, PART 1–3 학습 노트와 Quizlet 가져오기 파일을 생성했다. 원천 출현, 외부 후보, 검토된 의미와 관계는 각각의 근거 및 검증 상태를 갖는다.

## 원천과 OCR

- Quizlet 세트 324678752 화면에서 1,224장을 확인했다. 전체 내보내기를 확보하지 못해 해당 원천의 등록은 0건이다.
- 사용자 제공 Anki 덱의 5,101개 노트 중 `01.빈출단어`의 1,241개를 DAY 01–30의 대체 핵심 자료로 가져왔다. 전체 Quizlet 데이터와 항목별로 비교하는 작업은 대기 중이다.
- 해커스 뒷단어 PDF 3종의 120쪽을 한영 OCR로 처리했다. 자동 추출 후보는 2,486건이다. DAY 01–06, 11–12, 16, 30의 총 40쪽을 이미지와 대조해 1,279개 출현을 등록했다. 80쪽은 아직 이미지 대조가 필요하다.
- 대조한 40쪽에서 자동 추출과 이미지의 철자가 일치한 출현은 670건이었다. OCR 후보와 검토된 출현은 각각의 파일과 상태로 보존한다. [OCR 검증](ocr_validation.md)
- 검토한 이미지의 1,279개 출현 중 1,264개가 Anki의 뒷단어 범주에서 동일 DAY·표제어·세부 구간으로 확인됐다. 다른 원천 출현과 차이를 보존했다. [입력과 출처](source_coverage.md)

## 데이터베이스와 학습 자료

- [SQLite](../data/processed/toeic.db)
- [검증 상태와 분류별 수량](../reports/database.generated.md)
- [GraphML](../data/processed/vocabulary.graphml)
- [PART 1–3 학습 노트](../notes/README.md) 및 [자체 60일 학습표](../notes/schedule.md)
- [Quizlet UTF-8 TSV 목록](../exports/quizlet/README.md)

교차 검증 비율의 분모는 등록된 개별 의미다. 전체 원천 대비 검증 진척은 검토된 의미와 직접 연결된 원천 출현의 비율로 별도 집계한다. Open English WordNet, Wiktextract, OANC에서 추출된 관계와 용법은 후속 검토에 사용한다. ETS 공개 샘플의 근거는 실제 샘플 문항 위치로 기록했다. [원천의 버전·라이선스](../SOURCES.md)

## 검증과 GitHub

최종 실행 수치, 검증 결과와 로컬 커밋 해시는 [실행 결과](final_execution.generated.md)에 기록했다. 연결된 GitHub 계정의 저장소 생성 요청은 GitHub에서 HTTP 403으로 거절됐다. 브라우저에서 새 저장소 페이지를 열었을 때 로그인 화면이 표시됐다. 비공개 원격 저장소 생성 및 push는 완료되지 않았다. PDF, Anki, 원천 어휘와 근거 내용을 포함하는 데이터는 로컬에 보존했다.
