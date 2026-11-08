# Sổ căn cứ API contract 1.0

Product: an offline, single-user local Python/SQLite application to retrieve learning sources, attach verbatim local excerpts to claims, detect missing/unreviewed/stale technical citations, and export an evidence dossier. It does not determine whether a claim is true or give a legal decision. Curated learning summaries are explicitly labelled summaries, never official verbatim law.

Runtime: Python >=3.10 standard library only. HTTP binds 127.0.0.1, default port8765. SQLite data path selectable with --data-dir. No backend URL fetching, no network dependency or external model. All source URLs open in user's browser with noopener. Data IDs are URL-safe strings (seed IDs retained, generated IDs UUID prefixes).

## Common response

JSON UTF-8. Successful lists use named array. Error status400/404/409/422 with {error:{code,message,details?}}. Every mutation has X-CSRF-Token returned by bootstrap. Host validation including port, Origin validation for mutation, request body limit256KiB, JSON Content-Type. Static files explicitly whitelisted. Parameterized SQL. All output escaped, no user HTML. Record mutation and audit in the same transaction.

## Bootstrap and search

- GET /api/bootstrap -> {csrf_token,app:{name,version,mode,corpus_note},stats:{sources,reviewed_sources,projects,claims,issues},projects:[...],sources:[...]}.
- GET /api/search?q=...&source_id=...&reviewed_only=true&limit=20 -> {query,results:[{id,source_id,source_title,document_number,issuer,source_url,source_version,source_status,locator,title,text,text_kind,score,source_sha256}],count}.
Search accent-insensitive (đ->d, NFD marks removed), token matching with title/locator weighting. Preserve original text. Query max200chars, limit1–50. No-match returns empty, no generated answer. Phrase/numeric tokens supported, avoid a single common stopword returning the entire corpus. reviewed_only defaults true.

## Sources

Metadata: {id,title,issuer,document_number,published_date,url,kind,text_kind,status,version,sha256,review_note,created_at,updated_at,segment_count}.
Segments: {id,source_id,source_version,title,locator,text,sha256}.
kind=law|learning_note; text_kind=summary|original. status=draft|reviewed. Date ISO or empty for internal notes. HTTPS URL required for law; empty URL allowed for learning_note.

- GET /api/sources -> {sources:[metadata]}.
- GET /api/sources/{id} -> {source:metadata,segments:[...],versions:[{version,sha256,change_note,created_at,status}]}.
- POST /api/sources body {title,issuer,document_number,published_date,url,kind,text_kind,segments:[{title,locator,text}]} ->201 {source,segments}. Always draft; supplied status ignored/rejected. Each segment 20–12000chars,1–100segments,total<=180000chars. Reject duplicate segment locator in same version. Metadata required for review.
- POST /api/sources/{id}/review body {review_note} ->{source}; require note>=10chars and appropriate metadata. This records self-review, not third-party approval.
- POST /api/sources/{id}/revise body {segments:[{title,locator,text}],change_note} ->{source,segments}; version+1, status=draft, preserve old immutable source snapshots and old evidence. Change note>=10chars. Old citations will be stale. New IDs for new segments.

## Projects and claims

- GET /api/projects ->{projects:[{id,title,description,created_at,updated_at,claim_count}]}.
- POST /api/projects {title,description} ->201 {project}.
- GET /api/projects/{id} ->{project,claims:[{id,project_id,text,claim_type,created_at,updated_at,evidence:[{id,claim_id,segment_id,source_id,source_version,source_sha256,segment_sha256,quote,note,source_title,source_url,locator,issuer,document_number,published_date,text_kind,created_at}]}]}.
- PATCH /api/projects/{id} {title,description} ->{project}.
- POST /api/projects/{id}/claims {text,claim_type} ->201 {claim}. Text20–4000chars. claim_type=factual|analysis|proposal.
- PATCH /api/claims/{id} {text,claim_type} ->{claim}.
- DELETE /api/claims/{id} ->{deleted:true}. UI confirm.
- POST /api/claims/{id}/evidence {segment_id,quote,note} ->201 {evidence}. Quote must be an exact normalized-whitespace substring of the selected stored segment and source must currently be reviewed. Empty quote uses entire segment. Store full immutable metadata snapshot and hashes. Reject duplicates perclaim+segment+quote and quote mismatch. Evidence supports traceability only, not semantic entailment.
- DELETE /api/evidence/{id} ->{deleted:true}. UI confirm.

## Checks and exports

- GET /api/projects/{id}/check ->{summary:{claims,pass,warning,error},checks:[{claim_id,status,issues:[...]}],issues:[{claim_id,code,severity,message,evidence_id?}]}.
Checks: factual claim without evidence error MISSING_EVIDENCE; analysis without evidence warning MISSING_EVIDENCE; proposal without evidence permitted. Existing evidence: SOURCE_UNREVIEWED, SOURCE_CHANGED, QUOTE_MISMATCH, SNAPSHOT_HASH_MISMATCH as appropriate; never silently refresh old evidence. Empty project warning EMPTY_PROJECT. Results must say technical check only. Check both pinned source snapshot and current status. Source revision causes stale regardless of same words. Source revision requires explicit evidence relinking by user.
- GET /api/projects/{id}/export?format=html|markdown|json ->attachment. Include project content, numbered citations, conventional bibliography, perclaim issues and verification date/version. HTML printable. Always show issues if present; no pretend certification. Export endpoints read-only.
- GET /api/audit ->{events:[{id,created_at,action,entity_id,details,previous_hash,event_hash}],verification:{valid,checked,first_invalid_id?}}. Limit last200 events in UI; verification covers whole log. Hash chain detects inconsistencies under trusted checkpoint, not tamper proof against an administrator.
- GET /api/health ->{ok:true,version:'1.0.0'}.
- GET /api/backup ->application/zip attachment, SQLite consistent backup +manifest checksum +README. No server-side restore endpoint.

## Seed and fixtures

data/source_seed.json: {schema_version:1,corpus_note,sources:[{id,title,issuer,document_number,published_date,url,kind,text_kind,status,review_note,segments:[{id,title,locator,text}]}]}.
Seed on fresh DB only. Put demonstration project in service initialization with factual/analysis/proposal examples and at least one missing-evidence warning, all labelled simulated. No imaginary Academy data. Do not add fake statistics.
data/search_fixtures.json: {queries:[{id,query,expected_segment_ids:[],category,note}]}.

## UI structure and integration

Six navigation views: Tổng quan; Tra cứu; Hồ sơ lập luận; Nguồn học liệu; Nhật ký; Hướng dẫn. All labels Vietnamese. Single page index.html, app.js, styles.css; no remote fonts/CDN/assets. Bootstrap token in memory. Search-result detail drawer with metadata and attach-to-claim controls. Project editor, checks, exports. Source create/review/revise with explicit status. Audit verifier and backup download. Responsive; accessible labels, keyboard focus; errors visible; loading/empty states. Keep summary/original and single-user nature clear without clutter. A seed corpus note must be visible in help/source detail.

## Deliverable quality

Meaningful automated service/HTTP tests, Vietnamese accent search, quotes/stale transitions, exports, persistence, bodylimit, CSRF/Origin/Host, escaping, transaction audit consistency, backups. Root handles browser tests, screenshots, actual benchmark, report integration and packaging. Never write invented pass counts or performance improvements. Backend and frontend owners write technical/manual documentation after integration for150–200page final formal report, driven by actual implementation.
