PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS course (
  id            INTEGER PRIMARY KEY,
  name          TEXT,
  school        TEXT,
  image_url     TEXT,
  updated_at    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS test (
  id            INTEGER PRIMARY KEY,
  course_id     INTEGER REFERENCES course(id),
  name          TEXT,
  objective     INTEGER,
  release_time  TEXT,
  deadline      TEXT,
  chapter_id    INTEGER,
  chapter_name  TEXT,
  total_pages   INTEGER,
  updated_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_test_course ON test(course_id);

CREATE TABLE IF NOT EXISTS question (
  id            INTEGER PRIMARY KEY,
  test_id       INTEGER REFERENCES test(id) ON DELETE CASCADE,
  seq           INTEGER,
  type          TEXT,
  title         TEXT,          -- 去 HTML 纯文本
  title_html    TEXT,          -- 原始 HTML（保留 img）
  std_answer    TEXT,          -- 填空题原始答案
  answer        TEXT,          -- 归一化答案(JSON/文本)
  UNIQUE(test_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_q_test ON question(test_id);
CREATE INDEX IF NOT EXISTS idx_q_type ON question(type);

CREATE TABLE IF NOT EXISTS option (
  id            INTEGER NOT NULL,
  question_id   INTEGER REFERENCES question(id) ON DELETE CASCADE,
  seq           INTEGER,
  content       TEXT,
  content_html  TEXT,
  is_answer     INTEGER DEFAULT 0,
  PRIMARY KEY (question_id, id)
);
CREATE INDEX IF NOT EXISTS idx_opt_q ON option(question_id);

-- 原始 POST /mooc/test/{tid} 响应，便于回放/对账
CREATE TABLE IF NOT EXISTS raw_answer (
  test_id       INTEGER PRIMARY KEY REFERENCES test(id) ON DELETE CASCADE,
  payload       TEXT
);

CREATE TABLE IF NOT EXISTS notice (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  kind     TEXT,     -- announcement / website / extension
  content  TEXT,
  fetched_at TEXT
);
