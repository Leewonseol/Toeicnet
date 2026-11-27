PRAGMA foreign_keys=ON;
CREATE TABLE sources (
    source_id TEXT PRIMARY KEY, title TEXT NOT NULL, url TEXT, independence_group TEXT,
    license TEXT, version TEXT, metadata_json TEXT NOT NULL DEFAULT '{}'
) STRICT;
CREATE TABLE words (
    word_id TEXT PRIMARY KEY, headword TEXT NOT NULL, normalized TEXT NOT NULL, homonym_key TEXT NOT NULL,
    UNIQUE(normalized, homonym_key)
) STRICT;
CREATE TABLE occurrences (
    occurrence_id TEXT PRIMARY KEY, word_id TEXT NOT NULL REFERENCES words,
    source_id TEXT NOT NULL REFERENCES sources, source_record_id TEXT NOT NULL,
    day INTEGER CHECK(day BETWEEN 1 AND 30), category TEXT, original_korean_meaning TEXT,
    part_of_speech TEXT, entry_type TEXT, filename TEXT, pdf_page INTEGER CHECK(pdf_page>0),
    printed_page TEXT, verification_status TEXT NOT NULL, properties_json TEXT NOT NULL,
    UNIQUE(source_id, source_record_id)
) STRICT;
CREATE INDEX occurrence_word ON occurrences(word_id);
CREATE TABLE senses (
    sense_id TEXT PRIMARY KEY, word_id TEXT NOT NULL REFERENCES words,
    part_of_speech TEXT NOT NULL, sense_key TEXT NOT NULL, preferred_display_language TEXT NOT NULL,
    UNIQUE(word_id,part_of_speech,sense_key)
) STRICT;
CREATE TABLE english_definitions (
    sense_id TEXT PRIMARY KEY REFERENCES senses, english_definition TEXT, status TEXT NOT NULL,
    verification_date TEXT, definition_origin TEXT
) STRICT;
CREATE TABLE korean_translations (
    sense_id TEXT PRIMARY KEY REFERENCES senses, verified_korean_meaning TEXT, status TEXT NOT NULL,
    translation_uncertainty_reason TEXT, verification_date TEXT
) STRICT;
CREATE TABLE sense_occurrences (
    sense_id TEXT REFERENCES senses, occurrence_id TEXT REFERENCES occurrences,
    PRIMARY KEY(sense_id,occurrence_id)
) STRICT;
CREATE TABLE nodes (
    node_id TEXT PRIMARY KEY, node_type TEXT NOT NULL, label TEXT NOT NULL,
    sense_id TEXT REFERENCES senses, word_id TEXT REFERENCES words,
    status TEXT NOT NULL, properties_json TEXT NOT NULL
) STRICT;
CREATE TABLE edges (
    edge_id TEXT PRIMARY KEY, from_node_id TEXT NOT NULL REFERENCES nodes,
    to_node_id TEXT NOT NULL REFERENCES nodes, relation_type TEXT NOT NULL,
    sense_id TEXT REFERENCES senses, status TEXT NOT NULL, properties_json TEXT NOT NULL
) STRICT;
CREATE INDEX edge_from ON edges(from_node_id);
CREATE INDEX edge_to ON edges(to_node_id);
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY, object_type TEXT NOT NULL, object_id TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources, url TEXT, source_record_id TEXT,
    version TEXT, extraction_method TEXT NOT NULL, verification_date TEXT, note TEXT,
    properties_json TEXT NOT NULL
) STRICT;
CREATE INDEX evidence_object ON evidence(object_type,object_id);
CREATE TABLE external_candidates (
    candidate_id TEXT PRIMARY KEY, kind TEXT NOT NULL, headword TEXT NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources, source_record_id TEXT NOT NULL, payload_json TEXT NOT NULL
) STRICT;
CREATE TABLE run_input (
    input_kind TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL, row_count INTEGER NOT NULL,
    PRIMARY KEY(input_kind,sha256)
) STRICT;
CREATE TABLE pipeline_state (
    stage TEXT PRIMARY KEY, payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
) STRICT;
CREATE VIEW translation_verification AS SELECT * FROM korean_translations;
CREATE VIEW verification_results AS
    SELECT 'english_definition' AS object_type,sense_id AS object_id,status,verification_date FROM english_definitions
    UNION ALL SELECT 'korean_translation',sense_id,status,verification_date FROM korean_translations
    UNION ALL SELECT 'occurrence',occurrence_id,verification_status,NULL FROM occurrences
    UNION ALL SELECT 'edge',edge_id,status,json_extract(properties_json,'$.verification_date') FROM edges;
CREATE VIEW definitions_with_context AS
SELECT s.sense_id,w.word_id,w.headword,s.part_of_speech,s.preferred_display_language,
       en.english_definition,en.status AS english_definition_status,
       ko.verified_korean_meaning,ko.status AS korean_translation_status,ko.translation_uncertainty_reason,
       en.verification_date AS english_verification_date,ko.verification_date AS korean_verification_date
FROM senses s JOIN words w USING(word_id)
JOIN english_definitions en USING(sense_id) JOIN korean_translations ko USING(sense_id);

-- Typed projections over the shared node/edge storage.
CREATE VIEW morphemes AS SELECT * FROM nodes WHERE node_type IN
    ('MORPHEME','ROOT','BASE','STEM','PREFIX','SUFFIX','INFLECTIONAL_ENDING');
CREATE VIEW morphological_analyses AS SELECT * FROM edges WHERE json_extract(properties_json,'$.module')='morphology';
CREATE VIEW word_morpheme_relations AS SELECT e.* FROM edges e JOIN morphemes m ON m.node_id=e.to_node_id;
CREATE VIEW derivations AS SELECT * FROM edges WHERE relation_type='DERIVED_FROM';
CREATE VIEW inflections AS SELECT * FROM edges WHERE relation_type='INFLECTION_OF';
CREATE VIEW compounds AS SELECT * FROM edges WHERE relation_type='COMPOUND_COMPONENT_OF';
CREATE VIEW etymological_relations AS SELECT * FROM edges WHERE json_extract(properties_json,'$.module')='etymology';
CREATE VIEW etymologies AS SELECT * FROM etymological_relations;
CREATE VIEW etymological_roots AS SELECT * FROM nodes WHERE node_type='ETYMOLOGICAL_ROOT';
CREATE VIEW historical_forms AS SELECT * FROM nodes WHERE node_type='HISTORICAL_FORM';
CREATE VIEW origin_languages AS SELECT DISTINCT json_extract(properties_json,'$.origin_language') AS language
    FROM etymological_relations WHERE json_type(properties_json,'$.origin_language')='text';
CREATE VIEW cognates AS SELECT * FROM edges WHERE relation_type='COGNATE_WITH';
CREATE VIEW semantic_changes AS SELECT * FROM edges WHERE relation_type='HAS_SEMANTIC_CHANGE';
CREATE VIEW synsets AS SELECT * FROM nodes WHERE node_type='SYNSET';
CREATE VIEW semantic_relations AS SELECT * FROM edges WHERE json_extract(properties_json,'$.module')='lexical_semantics';
CREATE VIEW synonyms AS SELECT * FROM edges WHERE relation_type='SYNONYM_OF';
CREATE VIEW near_synonyms AS SELECT * FROM edges WHERE relation_type='NEAR_SYNONYM_OF';
CREATE VIEW antonyms AS SELECT * FROM edges WHERE relation_type IN
    ('ANTONYM_OF','COMPLEMENTARY_TO','GRADABLE_OPPOSITE_OF','REVERSIVE_OF');
CREATE VIEW semantic_fields AS SELECT * FROM nodes WHERE node_type='SEMANTIC_FIELD';
CREATE VIEW themes AS SELECT * FROM nodes WHERE node_type='THEME';
CREATE VIEW word_theme_relations AS SELECT * FROM edges WHERE relation_type='BELONGS_TO_THEME';
CREATE VIEW collocations AS SELECT * FROM nodes WHERE node_type='COLLOCATION';
CREATE VIEW colligations AS SELECT * FROM nodes WHERE node_type='COLLIGATION';
CREATE VIEW idioms AS SELECT * FROM nodes WHERE node_type='IDIOM';
CREATE VIEW phrasal_verbs AS SELECT * FROM nodes WHERE node_type='PHRASAL_VERB';
CREATE VIEW verb_patterns AS SELECT * FROM edges WHERE relation_type='HAS_VERB_PATTERN';
CREATE VIEW argument_structures AS SELECT * FROM edges WHERE relation_type='HAS_ARGUMENT_STRUCTURE';
CREATE VIEW countability AS SELECT * FROM edges WHERE relation_type='HAS_COUNTABILITY';
CREATE VIEW transitivity AS SELECT * FROM edges WHERE relation_type='HAS_TRANSITIVITY';
CREATE VIEW registers AS SELECT * FROM edges WHERE relation_type='HAS_REGISTER';
CREATE VIEW corpus_attestations AS SELECT * FROM external_candidates
    WHERE json_extract(payload_json,'$.verification_status')='corpus_attested';
