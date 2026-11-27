# 출처와 확보 현황

확인일은 2026-11-27 UTC다. 공개 다운로드 자료의 파일명과 SHA-256은 `config/sources.yaml`과 `sources/manifest.json`에 기록했다. 사용자 제공 원천의 개별 파일과 가져오기 기록은 로컬에 있다.

## 해커스 원천 자료

| 자료 | 확보 상태 | 확인 내용 |
| --- | --- | --- |
| 본 단어 Quizlet 세트 `324678752` | 항목 수 1,224장 확인 · 사용자 요청에 따라 범위 제외 | 브라우저의 일반 공개 카드 보기에서 세트 제목과 등록 카드 수를 확인했다. 최종 입력 범위는 사용자 제공 Anki와 PDF다. [지정 세트](https://quizlet.com/kr/324678752/%ED%95%B4%EC%BB%A4%EC%8A%A4-%ED%86%A0%EC%9D%B5-%EB%B3%B4%EC%B9%B4-1-30%EC%A0%84%EB%A9%B4%EA%B0%9C%EC%A0%95%ED%8C%90-flash-cards/), [공식 내보내기 안내](https://help.quizlet.com/hc/en-us/articles/360034345672-Exporting-your-sets) |
| 사용자 제공 Anki 자료 | DAY 01–30의 카드·노트 5,101건 읽음 | 자료 안의 덱 분류에 따라 빈출 1,241건, 토익 기초 837건, 800점 2,033건, 900점 990건으로 집계했다. 가져오기 출처는 `hackers_anki_user`다. |
| 뒷단어 스캔 PDF 3종 | 120페이지 한영 OCR · 120페이지 원본 대조 | PDF별 실제 페이지 수는 40·20·60이다. 원본 대조를 마친 3,837건은 OCR 보고서에 반영했다. |
| 해커스 DAY 주제 | 공개 강의 목차 확인 | 공식 신토익 강의에 DAY 01–30의 주제가 표시된다. 기존판의 일부 DAY 순서가 다르다. `config/sources.yaml`의 `hackers_toc.day_topics`에 신토익 강의 주제를 저장했으며 원천 판본과 DAY 출현 위치를 확인한 뒤 연결에 사용한다. [공식 강의 목차](https://champ.hackers.com/?c=lecture%2Flec_toeic&lec_id=7353&pcmode=Y&r=champstudy&sub=detail), [공식 기존판 목록](https://www.hackers.co.kr/s_toeic/voca_game/voca_new/voca_old) |

### Anki와 PDF 출처 대조

Anki의 DAY 01–30 빈출단어 덱 1,241건을 본 단어로 등록했다. Anki의 나머지 덱 3,860건은 PDF 이미지 대조를 보조하는 별도 입력이다.

PDF 120쪽의 출현 3,837건을 Anki 기초·800점·900점 덱과 비교했다. 같은 DAY와 정규화 표제어가 일치한 PDF 출현은 3,777건(98.44%)이며, 모두 세부 구간도 일치했다. 원래 표기까지 일치한 출현은 3,737건이었다. PDF에만 있는 DAY·표제어는 60건, Anki 뒷단어에만 있는 것은 53건이었다. 표제어와 구간에서 확인한 출처 대조 결과이며, 각 원뜻과 품사의 적합성은 별도 근거로 검증한다. DAY별 수량과 입력 체크섬은 로컬 대조 기록에 있다. [OCR 검증](reports/ocr_validation.md)

## 다운로드와 참조 자료

| 자료 | 이번 작업에서 확보한 내용 | 버전 또는 자료 식별 정보 |
| --- | --- | --- |
| Open English WordNet | WN-LMF 압축 파일 다운로드 | 2025 본판, `english-wordnet-2025.xml.gz`, 2025-12-31 공개. [공식 다운로드](https://en-word.net/downloads), [공식 저장소](https://github.com/globalwordnet/english-wordnet) |
| Wiktionary via Kaikki / Wiktextract | 원시 JSONL 압축 파일 3,082,476,978바이트 다운로드 | `raw-wiktextract-data.jsonl.gz`, enwiktionary 2026-10-01 덤프, 2026-10-30 추출. English 레코드는 `lang_code == 'en'`으로 선별한다. [원시 다운로드와 추출 버전](https://kaikki.org/dictionary/rawdata.html), [추출 스키마](https://github.com/tatuylonen/wiktextract#format-of-the-extracted-word-entries) |
| GCIDE | 0.54 tarball 14,803,080바이트 다운로드, GNU 키링 서명 확인 | 2024-12-31 릴리스. 정의 179,656건을 추출했으며 `<source>` 기준으로 Webster 1913 계보 161,702건, WordNet 유래 9,335건, GCIDE 편집자 추가 5,533건, 기타 3,086건이다. [소개](https://gcide.gnu.org.ua/about), [배포](https://ftp.gnu.org/gnu/gcide/) |
| Open American National Corpus | GrAF 아카이브 660,388,635바이트 다운로드 | `OANC_GrAF.tgz`, 공식 배포 저장소 `datasets-2026-09-25` 릴리스. [공식 다운로드](https://anc.org/data/oanc/download/), [배포 릴리스](https://github.com/nancyide/anc-website/releases/tag/datasets-2026-09-25) |
| ETS TOEIC Listening and Reading | 공개 샘플 34페이지를 로컬 참고용으로 다운로드 | Paper-delivered testing, 2,461,549바이트. [자료 안내](https://www.ets.org/toeic/test-takers/prepare.html), [샘플 PDF](https://www.ets.org/pdfs/toeic/toeic-listening-reading-sample-test.pdf) |
| 한국 TOEIC 공식 사이트 | RC 공개 샘플과 실제기출 공개 페이지 확인 | 공개 샘플과 공식적으로 공개된 기출의 근거 유형을 달리 기록한다. [RC 샘플](https://exam.toeic.co.kr/content/TOE/sampleRc1.php), [실제기출 공개 페이지](https://m.exam.toeic.co.kr/content/common/realQuestion.php) |
| OCR 언어 모델 | 영어와 한국어 Tesseract 모델 다운로드 | `tessdata_fast` 4.1.0. 로컬의 `data/external/tessdata/`. [공식 릴리스](https://github.com/tesseract-ocr/tessdata_fast/tree/4.1.0) |

### 실제 Wiktextract 레코드의 필드 확인

압축 파일에서 처음 만난 영어 레코드 10,000개를 스트리밍으로 검사했다. 이 표본은 파일 구조를 확인하는 데 쓰였으며 해커스 본 단어 또는 뒷단어를 선정하는 데 사용하지 않았다.

| 범위 | 확인한 주요 필드 |
| --- | --- |
| 어휘 항목 | `word`, `pos`, `lang_code`, `senses`, `forms`, `head_templates`, `etymology_number`, `etymology_text`, `etymology_links`, `etymology_templates`, `derived`, `related`, `synonyms`, `antonyms`, `hyponyms`, `hypernyms` |
| 개별 의미 | `glosses`, `raw_glosses`, `tags`, `examples`, `attestations`, `senseid`, `alt_of`, `form_of`, `synonyms`, `antonyms`, `hypernyms`, `meronyms` |
| 역사 자료 | `etymology_text`는 서술문이다. `etymology_templates`의 `name`과 인수는 구조적 단서다. `cog`, `root`, `bor`, `inh`, `der`, `af`, `suffix`, `compound`, `prefix` 등을 확인했다. |

표본에 범용 `morphemes` 필드는 없었다. 어원 템플릿에서 현대 형태 분석으로 전환할 때에는 구성요소와 현대 영어의 결합 관계를 따로 판단해야 한다. `senseid`가 들어 있는 의미는 일부여서 외부 레코드의 의미 위치도 근거에 보존한다. [Wiktextract 기술 문서](https://github.com/tatuylonen/wiktextract#format-of-the-extracted-word-entries)

## 학습자용 사전 및 어원사전

| 출처 | 이번 작업에서 확인한 접근 및 활용 범위 |
| --- | --- |
| Cambridge Dictionary | 제공자 라이선스와 공식 API 안내를 확인했다. 계약 없는 상태에서 공개 표제어를 개별 참조할 수 있는 경우 의미·품사·용례를 대조한다. [사전](https://dictionary.cambridge.org/), [라이선스](https://dictionary.cambridge.org/license.html), [API](https://dictionary.cambridge.org/develop) |
| Oxford Learner’s Dictionaries | 학습자용 사이트의 법적 고지와 Oxford Languages의 별도 API를 확인했다. 학습자용 데이터나 Collocations 제품이 자동으로 포함된다고 가정하지 않는다. [법적 고지](https://www.oxfordlearnersdictionaries.com/legal-notice.html), [Oxford Languages API](https://languages.oup.com/products/api/) |
| Longman Dictionary of Contemporary English | 이전 열람에서는 HTTP 502·503이었다. 2026-11-27 클라우드 점검에서는 5개 시험 표제어 모두 정의 표지를 확인했다. 공식 덤프와 저장 권한은 미확인이다. [사전](https://www.ldoceonline.com/), [접근 점검](reports/source_access.md) |
| Collins Dictionary | 공개 사이트 약관과 별도 이용 조건이 있는 API를 확인했다. [사전](https://www.collinsdictionary.com/), [사이트 약관](https://www.collinsdictionary.com/terms-and-conditions), [API](https://www.collinsdictionary.com/us/collins-api/) |
| Merriam-Webster | 2026-11-27 클라우드 점검에서 웹 표제어 5/5의 정의 표지를 확인했다. 공식 Dictionary API는 키 없이 `Key is required`를 반환했다. API 약관은 비상업 이용, 참조 사전별 1일 1,000건, 최대 2종을 조건으로 한다. 5조 (a)는 서면 승인 없는 자동·기록 질의를, (i)는 제3자 제품과의 비교를 금지하므로 배치 검증에는 서면 승인이 필요하다. Britannica와 같은 `merriam_webster` 계보로 센다. [사전](https://www.merriam-webster.com/), [API](https://dictionaryapi.com/), [API 약관](https://dictionaryapi.com/info/terms-of-service) |
| 네이버 영어사전 | 다른 출판사의 사전 데이터를 제공하는 플랫폼이다. 독립 출처로 세지 않고, 화면에 표시된 원천 사전의 계보로 기록한다. 2026-11-27 점검 시 robots.txt가 모든 AI 에이전트 토큰을 차단해 본문을 요청하지 않았다. [사전](https://en.dict.naver.com/) |
| Britannica Dictionary | 공개 표제어의 일반 웹 열람에서 overdue, portfolio, premium의 해당 의미를 확인했다. Merriam-Webster Learners Dictionary API는 별도로 확인했다. 같은 계열 학습자용 데이터를 중복 집계하지 않는다. [Britannica Dictionary](https://www.britannica.com/dictionary), [Learners Dictionary API](https://dictionaryapi.com/products/api-learners-dictionary), [사전 이용 연구](https://elibrary.narr.digital/xibrary/10.24053-AAA-2024-0004) |
| 국립국어원 한국어기초사전 | 한국어 뜻과 한국어 용례를 독립적으로 검토하는 데 사용한다. 공식 API와 전체 내려받기 안내를 확인했다. [사전](https://krdict.korean.go.kr/), [개발 지원](https://krdict.korean.go.kr/kor/openApi/openApiInfo) |
| Online Etymology Dictionary | 개별 공개 항목에서 remit 계열, dividend, itinerary, collateral 등의 역사적 경로와 접사를 확인했다. 공식 덤프·API 및 대량 저장 권한은 미확인이다. [Etymonline](https://www.etymonline.com/), [약관](https://www.etymonline.com/legal/terms) |

영어 정의 교차 검증에서 사전 이름이 달라도 원자료의 제작자가 같은 경우 한 출처로 센다. 자료 확보와 개별 해커스 의미 검증은 별도의 상태로 기록한다.

## 공식 TOEIC 샘플 위치 확인

한국 TOEIC 공식 RC 샘플 1의 Part 5 이미지에서 본문과 선택지의 어휘를 직접 확인했다. SQLite 기록에는 13건의 관찰 표기 및 문항 위치가 있다. 문형을 검토한 두 동사의 근거는 분석에 연결했다. 실제 공식 샘플 위치만 인용했다. [한국 TOEIC 공식 RC 샘플](https://exam.toeic.co.kr/content/TOE/sampleRc1.php)

## 보카바이블 B권 학습 구성 확인

허민의 『보카바이블 4.0』은 스텝업에서 2018년에 출간했다. 예스24에 실린 목차와 출판사 소개에서 B권 Part 2의 40일 구성과 Part 3의 20일 구성을 확인했다. Part 2의 DAY 01–09는 의미나 공간 관계별 접두어, DAY 10은 품사 형성 접미어, DAY 11–40은 기본동사·명사로 설명하는 어근을 다룬다. 초반에 전치사·부사 표현을, 어근 학습에서는 기본동사·명사 표현을 함께 배치한다. 대표 주제로는 이동 방향의 접두어, 전달·이동을 나타내는 동사 어근, 신체·시간에 관련된 명사 어근이 있다. [보카바이블 4.0 목차·출판사 소개](https://www.yes24.com/Product/Goods/61307273)

Part 3의 공개 목차에서 인간의 능력·감각, 직장, 법, 경제, 환경과 같은 테마 범주를 확인했다. 공식 목차는 개별 동의어 집단과 수록 숙어의 전체 목록까지 제공하지 않는다. 출판사 소개가 안내한 교재지원 공식 카페에 접속했으나 응답 시간을 초과했으며 B권 전체 강의 목록과 원문 색인은 확보하지 못했다. [목차와 색인 안내](https://www.yes24.com/Product/Goods/61307273), [교재지원 사이트](https://www.vocabible.com/)

프로젝트 일정은 사용자가 지정한 DAY 01–10 접두어, DAY 11–40 어근, 20일 유의어·테마 학습을 따른다. 접미사는 보조 색인에 둔다. 각 집단의 실제 구성은 해커스 원천 출현과 개별 어휘 근거에서 생성한다.
