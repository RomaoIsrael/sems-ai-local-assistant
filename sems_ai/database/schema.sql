-- Esquema SQLite de SEMS AI — versión 1
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    builtin INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    doc_code TEXT,
    category_id INTEGER REFERENCES categories(id),
    area TEXT,
    doc_type TEXT,
    issuer TEXT,
    revision TEXT,
    issue_date TEXT,
    effective_date TEXT,          -- solo si está acreditada
    added_at TEXT NOT NULL,
    last_verified_at TEXT,
    status TEXT NOT NULL DEFAULT 'Pendiente de verificación',
    source TEXT,
    verifier TEXT,
    notes TEXT,
    current_version_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_documents_code ON documents(doc_code);

CREATE TABLE IF NOT EXISTS document_versions (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE RESTRICT,
    version_no INTEGER NOT NULL,
    revision TEXT,
    original_filename TEXT NOT NULL,
    original_path TEXT,
    stored_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    extension TEXT,
    imported_at TEXT NOT NULL,
    imported_by TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'pendiente',
    extraction_message TEXT,
    page_count INTEGER,
    security_flags TEXT,
    UNIQUE(document_id, version_no)
);
CREATE INDEX IF NOT EXISTS ix_versions_sha ON document_versions(sha256);

CREATE TABLE IF NOT EXISTS document_relations (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    related_document_id INTEGER NOT NULL REFERENCES documents(id),
    relation TEXT NOT NULL,
    notes TEXT,
    UNIQUE(document_id, related_document_id, relation)
);

CREATE TABLE IF NOT EXISTS chunks (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES document_versions(id),
    document_id INTEGER NOT NULL REFERENCES documents(id),
    seq INTEGER NOT NULL,
    page INTEGER,
    section TEXT,
    location TEXT,
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_chunks_version ON chunks(version_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, section, content='chunks', content_rowid='id',
    tokenize = 'unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, section) VALUES (new.id, new.text, new.section);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, section) VALUES ('delete', old.id, old.text, old.section);
END;

CREATE TABLE IF NOT EXISTS embeddings (
    chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id),
    model TEXT NOT NULL,
    dim INTEGER NOT NULL,
    vector BLOB NOT NULL
);

CREATE TABLE IF NOT EXISTS query_history (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    username TEXT,
    query TEXT NOT NULL,
    answer TEXT,
    mode TEXT,
    model TEXT,
    sources_json TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    username TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id TEXT,
    details TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    iterations INTEGER NOT NULL,
    role TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- ---------------- Cumplimiento ----------------
CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    version_id INTEGER NOT NULL REFERENCES document_versions(id),
    req_code TEXT NOT NULL,
    numeral TEXT,
    page INTEGER,
    text TEXT NOT NULL,
    obligation_type TEXT NOT NULL,
    keyword TEXT,
    chunk_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_req_version ON requirements(version_id);

CREATE TABLE IF NOT EXISTS compliance_analyses (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT,
    title TEXT,
    reference_version_id INTEGER NOT NULL REFERENCES document_versions(id),
    evaluated_version_id INTEGER NOT NULL REFERENCES document_versions(id),
    method TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS compliance_items (
    id INTEGER PRIMARY KEY,
    analysis_id INTEGER NOT NULL REFERENCES compliance_analyses(id) ON DELETE CASCADE,
    requirement_id INTEGER REFERENCES requirements(id),
    ident TEXT NOT NULL,
    source TEXT,
    numeral TEXT,
    req_page INTEGER,
    req_text TEXT,
    obligation_type TEXT,
    local_document TEXT,
    local_section TEXT,
    local_page INTEGER,
    local_chunk_id INTEGER,
    evidence TEXT,
    result TEXT,
    gap TEXT,
    recommendation TEXT,
    justification TEXT,
    proposed_action TEXT,
    confidence TEXT,
    score REAL,
    review_status TEXT NOT NULL DEFAULT 'Pendiente de revisión',
    reviewer TEXT,
    reviewed_at TEXT,
    reviewer_notes TEXT
);

-- ---------------- Revisión Word ----------------
CREATE TABLE IF NOT EXISTS word_reviews (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    created_by TEXT,
    source_version_id INTEGER REFERENCES document_versions(id),
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    analysis_id INTEGER REFERENCES compliance_analyses(id),
    output_path TEXT,
    output_sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'borrador'
);

CREATE TABLE IF NOT EXISTS word_review_changes (
    id INTEGER PRIMARY KEY,
    review_id INTEGER NOT NULL REFERENCES word_reviews(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    action TEXT NOT NULL,               -- insert_after | append_to
    paragraph_index INTEGER NOT NULL,
    anchor_text TEXT,
    new_text TEXT NOT NULL,
    reason TEXT,
    requirement TEXT,
    source_document TEXT,
    numeral TEXT,
    justification TEXT,
    classification TEXT NOT NULL,       -- Requisito | Recomendación | Validación pendiente
    compliance_item_id INTEGER,
    decision TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | aceptada | rechazada
    decided_by TEXT,
    decided_at TEXT
);

-- ---------------- Auditorías ----------------
CREATE TABLE IF NOT EXISTS audits (
    id INTEGER PRIMARY KEY,
    code TEXT,
    title TEXT NOT NULL,
    standard TEXT,
    sop TEXT,
    asset TEXT,
    scope TEXT,
    start_date TEXT,
    end_date TEXT,
    lead_auditor TEXT,
    auditors TEXT,
    auditees TEXT,
    methodology_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Planificada',
    created_at TEXT NOT NULL,
    created_by TEXT
);

CREATE TABLE IF NOT EXISTS audit_questions (
    id INTEGER PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    qid TEXT NOT NULL,
    origin TEXT NOT NULL,           -- oficial | complementaria
    origin_reference TEXT,          -- checklist oficial identificado o requisito de origen
    source TEXT,
    numeral TEXT,
    question TEXT NOT NULL,
    translation TEXT,
    auditor_guide TEXT,
    required_evidence TEXT,
    result TEXT,
    evidence_found TEXT,
    observations TEXT,
    finding TEXT,
    responsible TEXT,
    close_date TEXT,
    effectiveness TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS audit_evidence (
    id INTEGER PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    question_id INTEGER REFERENCES audit_questions(id),
    document_id INTEGER REFERENCES documents(id),
    reference TEXT,
    description TEXT,
    sha256 TEXT,
    added_at TEXT NOT NULL,
    added_by TEXT
);

CREATE TABLE IF NOT EXISTS audit_findings (
    id INTEGER PRIMARY KEY,
    audit_id INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
    question_id INTEGER REFERENCES audit_questions(id),
    ref TEXT NOT NULL,
    finding_type TEXT,            -- según metodología
    description TEXT NOT NULL,
    requirement TEXT,
    evidence TEXT,
    responsible TEXT,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'Abierto',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corrective_actions (
    id INTEGER PRIMARY KEY,
    finding_id INTEGER NOT NULL REFERENCES audit_findings(id) ON DELETE CASCADE,
    root_cause TEXT,
    action TEXT NOT NULL,
    responsible TEXT,
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'Abierta',
    closed_date TEXT,
    effectiveness_check TEXT,
    effectiveness_date TEXT,
    created_at TEXT NOT NULL
);

-- ---------------- Legislación ----------------
CREATE TABLE IF NOT EXISTS legal_instruments (
    id INTEGER PRIMARY KEY,
    document_id INTEGER REFERENCES documents(id),
    official_id TEXT NOT NULL,
    title TEXT NOT NULL,
    instrument_type TEXT,
    issuer TEXT,
    publication_date TEXT,
    official_source TEXT,
    effective_date TEXT,
    validity_status TEXT NOT NULL DEFAULT 'No verificado',
    verified_at TEXT,
    verified_by TEXT,
    verification_basis TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS legal_relations (
    id INTEGER PRIMARY KEY,
    from_instrument_id INTEGER NOT NULL REFERENCES legal_instruments(id) ON DELETE CASCADE,
    to_instrument_id INTEGER NOT NULL REFERENCES legal_instruments(id) ON DELETE CASCADE,
    relation TEXT NOT NULL,     -- reforma | deroga | sustituye | complementa | posible_contradiccion
    articles TEXT,
    notes TEXT,
    UNIQUE(from_instrument_id, to_instrument_id, relation)
);

CREATE TABLE IF NOT EXISTS legal_obligations (
    id INTEGER PRIMARY KEY,
    instrument_id INTEGER NOT NULL REFERENCES legal_instruments(id) ON DELETE CASCADE,
    article TEXT,
    obligation TEXT NOT NULL,
    applicability TEXT,
    frequency TEXT,
    responsible TEXT,
    evidence_required TEXT,
    evidence_found TEXT,
    compliance_status TEXT NOT NULL DEFAULT 'No evaluado',
    verified_by TEXT,
    verified_at TEXT,
    notes TEXT
);

-- ---------------- Gestión de desechos ----------------
CREATE TABLE IF NOT EXISTS waste_streams (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    classification TEXT,
    hazardous TEXT NOT NULL DEFAULT 'Por determinar',  -- Sí | No | Por determinar
    hazard_characteristics TEXT,
    classification_basis TEXT,
    generation_point TEXT,
    unit TEXT NOT NULL DEFAULT 'kg',
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS waste_movements (
    id INTEGER PRIMARY KEY,
    stream_id INTEGER NOT NULL REFERENCES waste_streams(id),
    date TEXT NOT NULL,
    stage TEXT NOT NULL,   -- Generación | Almacenamiento temporal | Transporte | Tratamiento | Disposición final
    quantity REAL,
    unit TEXT,
    location TEXT,
    manager TEXT,
    manifest_no TEXT,
    transfer_note TEXT,
    document_ref TEXT,
    responsible TEXT,
    notes TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS form_templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    module TEXT NOT NULL,
    fields_json TEXT NOT NULL,
    is_official INTEGER NOT NULL DEFAULT 0,
    official_source TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS form_records (
    id INTEGER PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES form_templates(id),
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_by TEXT
);
