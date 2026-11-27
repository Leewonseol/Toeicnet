# TOEIC 어휘 Batch RAG 실행 결과

기준 커밋은 `546902f9ebeb042d2e2041f556195e84844f3c84`입니다. 기존 Anki 1,241건과 PDF 3,837건을 합친 원천 출현 5,078건에 배치를 적용했습니다. 기존 SQLite의 원천 출현, 165개 의미, 518,012개 외부 후보, 5,357개 노드와 4,145개 에지는 유지했습니다. 배치 결과는 같은 DB의 `batch_rag_current`에서 조회할 수 있습니다. 전체 실행 ID는 `762908bcc99d8180e1d99e0a`입니다.

## 검증 전후

| 지표 | 실행 전 | 실행 후 |
| --- | ---: | ---: |
| A · 지정 영영사전 교차 검증 | 154/5,078 (3.03%) | 154/5,078 (3.03%) |
| B · 독립 공개 어휘 자료 교차 검증 | 별도 미집계 | 96/5,078 (1.89%) |
| A+B · 두 출처 기준 충족 | 154/5,078 (3.03%) | 250/5,078 (4.92%) |
| C · 단일 출처 확인 | 별도 미집계 | 66/5,078 (1.30%) |
| D · 개별 의미 또는 근거 검토 대기 | 별도 미집계 | 3,882 |
| E · 적용 가능한 사전 의미 미확보 | 별도 미집계 | 880 |
| 한국어 뜻 검증 연결 | 128/5,078 (2.52%) | 151/5,078 (2.97%) |

| 원천 | 출현 | A | B | C | D | E |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Anki 본 단어 | 1,241 | 73 | 34 | 12 | 1,120 | 2 |
| PDF 뒷단어 | 3,837 | 81 | 62 | 54 | 2,762 | 878 |

기존 공개 사전 후보가 있던 4,064건을 우선 처리했습니다. 정확 일치 후보가 없었던 860건에서는 형태·표기 변이까지 조사했습니다. 원본 WordNet과 Kaikki 아카이브를 909개 표기로 재검색해 기존 DB에 없던 변이 후보 18건을 원천 출현 4건에서 찾았으며, 새 정확 일치는 0건이었습니다. 새 후보는 의미·표기 검토 상태로 남겼습니다.

## 100개 표본 평가

별도 Codex 검토자가 배치 판정을 보기 전에 100건의 근거를 읽고 기준 표본을 만들었습니다. 76건에서 정답으로 확인한 공개 사전 후보는 217개였습니다. 대조군은 표제어·품사 필터를 적용한 SQLite 정확 일치 순서입니다.

| 측정 | 기준 | 배치 |
| --- | ---: | ---: |
| Recall@5 · 사전 의미 후보 단위 | 124/217 (57.1%) | 134/217 (61.8%) |
| 상위 5개에서 정답을 하나 이상 찾은 어휘 | 71/76 (93.4%) | 73/76 (96.1%) |
| 근거 링크 정밀도 · 첫 판정 |  | 84/85 (98.8%) |
| 근거 링크 정밀도 · 오류 수정 후 같은 표본 |  | 84/84 (100%) |
| B등급 판정 정밀도 · 기준 판정이 있는 승인 사례 |  | 36/36 (100%) |
| 등급 일치율 · 등급 기준이 있는 표본 |  | 62/77 (80.5%) |
| 잘못 승인한 개별 의미 링크 |  | 첫 판정 1건, 수정 후 0건 |

첫 판정은 `belongings`의 특정 의미에 더 넓은 사전 의미를 연결했습니다. 이를 검토 대기로 돌렸습니다. 수정 후 수치는 같은 표본의 재평가입니다. 독립 표본 판정은 Codex가 수행했고 인간 검수는 아직 수행하지 않았습니다.

## 처리 시간, 비용, 분석

- 전체 배치의 SQLite 검색·판정·체크포인트 처리 측정은 27.7초였습니다. 그중 사전 후보 검색은 평균 2.68ms/출현이었고, 표본에서 만든 판정 캐시를 100건에서 재사용했습니다. 이 시간에는 앞서 수행한 Codex 자료 검토와 별도로 실행한 전체 아카이브 검색이 포함되지 않습니다.
- 모델을 사용한 영어 판정 193건과 네 분석 모듈의 근거 판정 16건을 반영했습니다. 외부 API 호출은 0건, 추가 API 비용은 0달러입니다. 이전 순차 웹 조사에는 항목별 시간과 비용 기록이 없어 배속이나 비용 절감률을 산출하지 않았습니다.
- 형태론·어원론·의미론·용법에서 개별 근거를 각각 4건씩 검토했습니다. 모듈마다 3건은 해당 출처 기록 범위에서 확인했고 1건은 근거 부족으로 남겼습니다. 전체 원천에는 네 모듈의 후보와 검토 상태를 연결했습니다. OANC 용례와 TOEIC 공식 샘플은 용법 근거로 집계했습니다.
- 영한 후보 재순위화용 `intfloat/multilingual-e5-small`을 검토했습니다. 이 환경의 모델 파일과 추론 런타임을 확보하지 못해 실제 배치에서는 구조화 검색과 출처 기반 재순위화를 사용했습니다.
- 테스트 50개, SQLite 무결성 및 외래 키 검사, 원천 범위 검사, Anki TSV 열과 카드 고유성 검사를 통과했습니다.

## 산출물과 남은 작업

등급별 학습 노트를 재생성하고 Anki 카드 **322장**을 내보냈습니다. A 160장, B 96장, C 66장입니다. 기존 A의 원천 출현 하나에 둘 이상의 검토 의미가 연결될 수 있어 카드 수와 원천 출현 수가 다릅니다. 별도로 검증된 한국어 뜻을 표시하고, 번역이 미확인인 카드에는 해당 등급의 영어 정의와 출처를 제공합니다.

영어 D·E 4,762건의 의미 대조, C 66건의 두 번째 근거 확인, 한국어 뜻 4,927건의 검토가 남아 있습니다. 네 분석 모듈에도 미검토 관계가 있어 항목마다 작업별 대기 사유를 저장했습니다. 대기열, 항목별 근거가 담긴 실행 결과, 학습 노트와 Anki TSV는 로컬에 있습니다. 이 보고서에는 실행 집계와 방법을 수록했습니다.

## 클라우드 세션 점검 (2026-11-27 UTC)

기준은 `834686e`입니다. 이 세션의 컨테이너에는 `data/`(SQLite DB, OCR 검토 CSV, Anki 덱, 공개 데이터 아카이브)가 없습니다. 이 디렉터리는 `.gitignore`와 작업 규칙에 따라 로컬에만 있습니다. Google Drive에서는 뒷단어 PDF 3종만 확인했고, Anki 덱·검토된 OCR·DB는 찾지 못했습니다. 그래서 위 실행 결과의 수치(A 154, B 96, C 66, D 3,882, E 880, 한국어 151)를 이 세션에서 다시 확인하거나 갱신하지 않았습니다. 원천 항목의 대량 처리, 100개 표본 재평가, 학습 노트와 Anki TSV 재생성도 수행하지 않았습니다.

이 세션에서 실행·변경한 것:

- **사전 접근성 점검**: `scripts/source_access_probe.py`로 9개 출처를 5개 표제어로 점검했습니다. 결과는 [source_access.md](source_access.md)에 있습니다. 응답 본문은 정의 표지를 센 뒤 버렸습니다. robots.txt는 프로젝트 UA와 Anthropic 에이전트 토큰을 모두 평가했으며, 한 토큰이라도 차단되면 요청하지 않았습니다.
  - `available`: Merriam-Webster 웹, Cambridge, Longman (각 5/5)
  - `forbidden`: Collins, Britannica (HTTP 403, 브라우저 확인 페이지). 재시도하지 않았습니다.
  - `robots_denied`: Etymonline(`ClaudeBot`), Oxford(`anthropic-ai`, `Claude-Web`), 네이버 영어사전(모든 토큰)
  - `authentication_required`: Merriam-Webster Dictionary API (키 필요)
  - 접근 가능 여부와 별개로 9개 출처 모두 `license_required`이며 자동 수집은 중단 상태입니다.
  - 관찰 범위: 이 결과는 이 클라우드 환경의 송신 IP에서 관찰한 것입니다. Collins·Britannica의 403이 IP 기반 차단인지는 확인하지 않았습니다(추론: 다른 네트워크에서는 결과가 다를 수 있음).
- **Merriam-Webster를 지정 영영사전에 추가**: `config/sources.yaml`에 `merriam_webster`를 추가하고 `LEARNER_SOURCES`에 넣었습니다. Britannica와 같은 `merriam_webster` 계보이므로 두 출처는 A등급의 독립 출처 두 곳으로 계산되지 않습니다. 네이버는 `independence_group`이 없는 플랫폼으로 등록했습니다.
- **의미 대조 7종 판정**: `equivalent`, `partially_equivalent`, `broader`, `narrower`, `context_dependent`, `different_sense`, `insufficient_evidence`를 판정 JSONL에서 받습니다. `equivalent`만 일치로 처리합니다. 기존 `match`, `partial`, `uncertain`, `no_match` 기록은 각각 `equivalent`, `partially_equivalent`, `insufficient_evidence`, `different_sense`로 읽으며 등급 결과는 바뀌지 않습니다. 결과에는 `alignment_result`를 기록합니다.
- **출처 조합 필드**: 모든 판정에 `source_combination`(`learner×2`, `open×2`, `learner×1+open×1` 등)을 기록합니다. 독립된 학습자 사전 하나와 공개 자료 하나가 같은 의미를 지지하면, 기존에는 D였고 이제 C(`source_attested`)입니다. A·B의 정의는 바꾸지 않았습니다. 이 C 배정은 "단일 신뢰 출처 확인" 기준을 충족한다는 판단에 근거한 선택입니다.
- 테스트 59개 통과(1개는 `zstd` 부재로 건너뜀). 기존 50개에 사전 점검 5개와 판정 4개를 추가했습니다.

로컬 DB에서 이어서 실행할 순서:

1. `python scripts/source_access_probe.py --db data/processed/toeic.db`: 점검 결과를 `source_access_checks` 표와 `source_access_current` 보기에 기록합니다. 사용하는 네트워크에서 결과가 다를 수 있으므로 로컬에서 다시 점검합니다.
2. `batch_rag_verify.py`가 바뀌어 규칙 지문이 달라졌습니다. 기존 `pilot` 요약으로는 `full`이 거부됩니다. 같은 기준 표본과 판정 JSONL로 `pilot`을 다시 실행해 관문을 확인한 뒤 `full`을 실행합니다. 기존 판정 파일을 그대로 쓰므로 모델을 다시 호출하지 않습니다.
3. 남은 D 3,882건의 의미 대조에는 판정 JSONL이 필요합니다. 상용 사전의 근거를 쓰려면 이용 권한이 먼저 확보되어야 합니다. 예: Merriam-Webster API 키와 약관 확인, Collins API 계약.

## 공개 데이터 중심 전략 전환 (2026-11-27 UTC)

상용 사전 웹사이트(Collins, Cambridge, Oxford, Longman, Britannica, 네이버)의 직접 수집을 필수 과정에서 제외했습니다. 이 출처들은 이번 전환 이후 요청하지 않았습니다. `source_access_probe.py`는 기본 실행에서 상용 웹페이지와 차단이 기록된 출처를 건너뜁니다. 이 저장소용 클라우드 환경의 허용 호스트에서도 상용 사전 7곳을 제거했습니다.

- **A등급은 선택 사항입니다.** 검토 대기열, 네 분석 모듈, 학습 카드 생성은 원래 A를 전제로 하지 않았습니다. B·C는 그대로 정식 등급입니다. 바뀐 것은 B의 근거로 GCIDE를 추가한 점입니다.
- **GCIDE 0.54 추가**: GNU 공식 tarball을 받아 서명을 확인했습니다. `import_gcide.py`는 정의마다 품사, 의미 번호, `[Obs.]`·`[R.]` 등 표시, 어원 문자열, `<source>` 계보를 보존합니다. 전체 릴리스에서 정의 179,656건을 6초 안에 추출했습니다.
- **중복 계산 차단**: GCIDE의 WordNet 유래 정의(9,335건)는 `derived_from`에 `globalwordnet`을 기록하여, Open English WordNet과 함께 인용하면 B가 되지 않습니다. 정의 문구가 같거나 거의 같으면(문자열 유사도 0.8 이상 또는 단어 집합 Jaccard 0.75 이상) 독립 근거로 세지 않습니다. 이 기준은 Webster 1913 문구를 옮긴 Wiktionary 뜻풀이를 겨냥한 것이며, 임계값은 이번에 정한 값입니다. 로컬 100개 표본 재평가에서 정밀도를 확인해야 합니다.
- **공식 API 약관 확인**: Merriam-Webster Dictionary API 약관 5조 (a)는 서면 승인 없는 자동·기록 질의를, (i)는 제3자 제품과의 비교를 금지합니다. 따라서 승인 없이 배치 검증에 사용하지 않습니다. 한국어기초사전 저작권 페이지는 두 번 모두 연결이 재설정되어 다시 확인하지 못했습니다. 기존 기록(텍스트 CC BY-SA 2.0, API 인증키 필요)을 유지합니다. Etymonline은 robots.txt가 `ClaudeBot`을 차단하므로 자동 요청하지 않으며, 어원 근거는 Wiktextract의 어원 템플릿과 GCIDE 어원 문자열을 사용합니다.
- **연결하지 않은 것**: GCIDE의 어원 문자열은 후보 레코드에 저장했습니다. 하지만 어원 분석 모듈(`batch_rag_modules.py`)은 아직 Wiktextract 어원 관계만 읽습니다.
- **처리 수치는 바뀌지 않았습니다.** 이 컨테이너에 DB가 없어 4,064건 처리, 등급 갱신, 학습 자료 재생성은 수행하지 않았습니다.

로컬 실행 순서:

```sh
python scripts/download_datasets.py gcide
python scripts/import_gcide.py --input data/external/gcide-0.54.tar.xz --version 0.54 \
  --targets data/intermediate/normalized.jsonl --targets data/intermediate/anki-core.jsonl \
  --output data/intermediate/gcide.jsonl
# build_database.py에 --candidates data/intermediate/gcide.jsonl을 추가해 재구축
python scripts/batch_rag.py prepare --top-k 12   # GCIDE 후보가 포함된 새 판정 입력
python scripts/batch_rag.py pilot --top-k 12 --gold data/intermediate/batch_rag/pilot_gold.jsonl \
  --model-decisions data/intermediate/batch_rag/decisions_pilot.jsonl
python scripts/batch_rag.py full --top-k 12 --model-decisions data/intermediate/batch_rag/all_decisions.jsonl ...
python scripts/batch_rag_study.py --assessments data/intermediate/batch_rag/full/assessments.jsonl
```

GCIDE 후보가 추가되면 판정 입력의 근거 집합과 캐시 키가 바뀝니다. 그래서 기존 판정 JSONL은 GCIDE를 보지 않은 판정으로 그대로 재사용되고, GCIDE를 인용한 B 판정은 새 판정이 있어야 생깁니다.
