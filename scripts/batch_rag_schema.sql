CREATE TABLE IF NOT EXISTS batch_rag_runs (
    run_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL CHECK(mode IN ('pilot','full')),
    input_fingerprint TEXT NOT NULL,
    settings_json TEXT NOT NULL CHECK(json_valid(settings_json)),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    metrics_json TEXT CHECK(metrics_json IS NULL OR json_valid(metrics_json))
) STRICT;

CREATE TABLE IF NOT EXISTS batch_rag_cases (
    run_id TEXT NOT NULL REFERENCES batch_rag_runs,
    case_key TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    english_json TEXT NOT NULL CHECK(json_valid(english_json)),
    korean_json TEXT NOT NULL CHECK(json_valid(korean_json)),
    PRIMARY KEY(run_id,case_key)
) STRICT;
CREATE INDEX IF NOT EXISTS batch_rag_case_cache ON batch_rag_cases(cache_key);

CREATE TABLE IF NOT EXISTS batch_rag_occurrences (
    run_id TEXT NOT NULL REFERENCES batch_rag_runs,
    occurrence_id TEXT NOT NULL REFERENCES occurrences,
    case_key TEXT NOT NULL,
    priority INTEGER NOT NULL CHECK(priority BETWEEN 0 AND 2),
    modules_json TEXT NOT NULL CHECK(json_valid(modules_json)),
    candidate_refs_json TEXT NOT NULL CHECK(json_valid(candidate_refs_json)),
    retrieval_ms REAL NOT NULL CHECK(retrieval_ms >= 0),
    cache_hit INTEGER NOT NULL CHECK(cache_hit IN (0,1)),
    PRIMARY KEY(run_id, occurrence_id),
    FOREIGN KEY(run_id,case_key) REFERENCES batch_rag_cases(run_id,case_key)
) STRICT;

CREATE VIEW IF NOT EXISTS batch_rag_assessments AS
SELECT result.run_id,result.occurrence_id,result.case_key,result.priority,
       json_extract(review.english_json,'$.grade') AS english_grade,
       json_extract(review.english_json,'$.definition') AS english_definition,
       json_extract(review.korean_json,'$.status') AS korean_status,
       json_extract(review.korean_json,'$.meaning') AS verified_korean_meaning,
       review.english_json,review.korean_json,
       result.modules_json,result.candidate_refs_json
FROM batch_rag_occurrences result JOIN batch_rag_cases review USING(run_id,case_key);

CREATE VIEW IF NOT EXISTS batch_rag_current AS
SELECT * FROM batch_rag_assessments
WHERE run_id=(
    SELECT run_id FROM batch_rag_runs WHERE mode='full' AND finished_at IS NOT NULL
    ORDER BY finished_at DESC,run_id DESC LIMIT 1
);
