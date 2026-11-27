# 영어 정의 검증

영어 정의는 같은 의미를 명시적으로 확인한 두 독립 학습자 사전의 근거를 갖춘 경우 교차 검증으로 등록한다. 상용 사전의 뜻풀이는 개별 열람 후 재구성하고 정의 출처를 남긴다. 기계 판독 자료에서 추출한 독립 후보는 검토 대상 의미로 유지한다. [검토 형식](../analysis/README.md)

의미를 실제로 등록한 범위의 검증 비율과 원천 전반의 의미 정렬 범위는 [SQLite 측정 결과](database.generated.md)에서 확인한다.

## 전수 검증에 필요한 접근

현재 연결에는 전수 비교와 로컬 저장에 이용할 수 있는 지정 영영사전 데이터가 없다. Cambridge는 사전 데이터 이용을 별도 라이선스로 안내한다. Collins의 공개 API 조건에는 쿼리를 대체하기 위한 로컬·온라인 보관 제한이 있다. Oxford Languages의 API는 데이터 제품과 오프라인 이용 범위를 계약별로 구분한다. 전수 검증 기준에는 독립 사전 두 곳에서 의미를 비교하고 SQLite에 근거를 유지할 수 있는 권한이 필요하다. [Cambridge 라이선스](https://dictionary.cambridge.org/license.html) · [Collins API 이용약관](https://blog.collinsdictionary.com/terms-conditions-collins-api/) · [Oxford API FAQ](https://developer.oxforddictionaries.com/faq)

각 출현의 영·한 검토 건수와 공개 후보는 로컬 `data/processed/semantic_coverage.csv`에서 확인할 수 있다. Wiktextract의 한국어 번역 후보는 원자료가 기록한 영어 의미 라벨과 함께 보존한다. 개별 교재 뜻과 대조되기 전에는 한국어 확인 건수에서 제외한다.
