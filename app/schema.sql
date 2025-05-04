-- 删除旧表 (如果存在)，方便重新初始化
DROP TABLE IF EXISTS meanings;
DROP TABLE IF EXISTS collocations;
DROP TABLE IF EXISTS concept_tags;
DROP TABLE IF EXISTS tags;
DROP TABLE IF EXISTS session_history; -- Added
DROP TABLE IF EXISTS concepts;

-- 核心概念表
CREATE TABLE concepts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    term TEXT NOT NULL UNIQUE COLLATE NOCASE, -- Ensure term is case-insensitive unique
    phonetic TEXT,
    etymology TEXT,
    synonyms TEXT,
    audio_url TEXT,
    error_count INTEGER DEFAULT 0 NOT NULL, -- Added NOT NULL
    srs_interval INTEGER DEFAULT 1 NOT NULL, -- Added NOT NULL
    srs_efactor REAL DEFAULT 2.5 NOT NULL, -- Added NOT NULL
    srs_due_date TEXT NOT NULL,
    last_reviewed_date TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP -- Consider adding a trigger to auto-update this
);

-- 含义表
CREATE TABLE meanings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id INTEGER NOT NULL,
    part_of_speech TEXT NOT NULL,
    definition TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE
);

-- 固定搭配/例句表
CREATE TABLE collocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    concept_id INTEGER NOT NULL,
    phrase TEXT NOT NULL,
    example TEXT,
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE
);

-- 标签表
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

-- 概念-标签关联表
CREATE TABLE concept_tags (
    concept_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    PRIMARY KEY (concept_id, tag_id),
    FOREIGN KEY (concept_id) REFERENCES concepts (id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id) REFERENCES tags (id) ON DELETE CASCADE
);

-- NEW: Session History table
CREATE TABLE session_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_type TEXT NOT NULL CHECK(session_type IN ('practice', 'test')), -- 'practice' or 'test'
    mode TEXT,                             -- e.g., 'due', 'hardest', 'mode1', 'mode2_phrase', 'mode3_blank_term'
    tag_filter_id INTEGER,                 -- ID of the tag used for filtering, NULL if none
    start_time TEXT NOT NULL,              -- ISO format UTC
    end_time TEXT NOT NULL,                -- ISO format UTC
    duration_seconds INTEGER NOT NULL,
    total_items INTEGER NOT NULL,
    correct_count INTEGER NOT NULL,
    incorrect_count INTEGER NOT NULL,
    skipped_count INTEGER DEFAULT 0,       -- Primarily for tests where items might be skipped due to errors
    accuracy REAL,                         -- Calculated accuracy percentage
    FOREIGN KEY (tag_filter_id) REFERENCES tags (id) ON DELETE SET NULL -- If tag deleted, keep history but lose link
);

-- --- 索引 ---
-- Concepts
CREATE INDEX idx_concepts_due_date ON concepts (srs_due_date);
CREATE INDEX idx_concepts_term ON concepts (term); -- UNIQUE constraint implies index, but explicit is fine
CREATE INDEX idx_concepts_error_count ON concepts (error_count);

-- Meanings/Collocations
CREATE INDEX idx_meanings_concept_id ON meanings (concept_id);
CREATE INDEX idx_collocations_concept_id ON collocations (concept_id);

-- Tags
CREATE INDEX idx_tags_name ON tags (name); -- UNIQUE constraint implies index
CREATE INDEX idx_concept_tags_tag_id ON concept_tags (tag_id);
CREATE INDEX idx_concept_tags_concept_id ON concept_tags (concept_id);

-- NEW: Session History
CREATE INDEX idx_history_session_type ON session_history (session_type);
CREATE INDEX idx_history_start_time ON session_history (start_time); -- For sorting
CREATE INDEX idx_history_tag_filter ON session_history (tag_filter_id);

-- Add Trigger to update 'updated_at' on concepts table (Optional but good practice)
-- DROP TRIGGER IF EXISTS update_concept_timestamp;
-- CREATE TRIGGER update_concept_timestamp
-- AFTER UPDATE ON concepts
-- FOR EACH ROW
-- BEGIN
--     UPDATE concepts SET updated_at = CURRENT_TIMESTAMP WHERE id = OLD.id;
-- END;
