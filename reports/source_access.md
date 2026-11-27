# 사전 접근성 점검

점검 시각(UTC): 2026-11-27T11:33:56+00:00 – 2026-11-27T11:35:16+00:00. 표제어: apply, requirement, acquire, contingent, employment. 응답 본문은 정의 표지 계수 후 폐기했고 저장하지 않았다.

| 출처 | 접근 상태 | 근거 | robots.txt | 확인 표제어 | 이용 권한 | 자동 수집 | 별도 출처로 계산 · 계보 |
| --- | --- | --- | ---: | --- | --- | --- | --- |
| collins | `forbidden` | HTTP 403 with a browser or CAPTCHA challenge | 200 | apply:forbidden | `license_required` | 중단 | 예 · collins |
| merriam_webster | `available` | definition marker present for 5/5 headwords | 200 | apply:available, requirement:available, acquire:available, contingent:available, employment:available | `license_required` | 중단 | 예 · merriam_webster |
| merriam_webster_api | `authentication_required` | service requires an API key | 200 | apply:authentication_required | `license_required` | 중단 | 아니요 · merriam_webster |
| etymonline | `robots_denied` | robots.txt disallows ClaudeBot | 200 | apply:robots_denied | `license_required` | 중단 | 예 · etymonline |
| cambridge | `available` | definition marker present for 5/5 headwords | 200 | apply:available, requirement:available, acquire:available, contingent:available, employment:available | `license_required` | 중단 | 예 · cambridge |
| oxford | `robots_denied` | robots.txt disallows Claude-Web, anthropic-ai | 200 | apply:robots_denied | `license_required` | 중단 | 예 · oxford |
| longman | `available` | definition marker present for 5/5 headwords | 200 | apply:available, requirement:available, acquire:available, contingent:available, employment:available | `license_required` | 중단 | 예 · longman |
| britannica | `forbidden` | HTTP 403 with a browser or CAPTCHA challenge | 200 | apply:forbidden | `license_required` | 중단 | 아니요 · merriam_webster |
| naver_dict | `robots_denied` | robots.txt disallows ToeicnetSourceProbe, Claude-User, ClaudeBot, Claude-SearchBot, Claude-Web, anthropic-ai | 200 | apply:robots_denied | `license_required` | 중단 | 아니요 · naver_dict |

이용 권한은 접근 상태와 별도로 판단했다. collins: Site terms; Collins API requires registration and separate terms. merriam_webster: Site terms; Dictionary API (dictionaryapi.com) requires a key and its own terms. merriam_webster_api: API key required; usage terms at dictionaryapi.com/info/terms-of-service. etymonline: No public dump or API confirmed; bulk storage rights unconfirmed. cambridge: Commercial; data licensing via dictionary.cambridge.org/license.html. oxford: Commercial; Oxford Languages API is a separate licence. longman: Commercial; no public API or dump confirmed. britannica: Shares the Merriam-Webster learner data lineage; not an independent source. naver_dict: Platform that redistributes other publishers' dictionaries; count the named provider, not Naver.
