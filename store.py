"""Persistence and evidence rules for Sổ căn cứ (standard library only).

This module checks provenance/consistency, not the truth of an academic claim.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import html
import io
import json
import math
import re
import sqlite3
import tempfile
import threading
import unicodedata
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "2.0.0"
SCHEMA_VERSION = 1
TECHNICAL_NOTE = "Kết quả kiểm tra tính nhất quán của dẫn nguồn; không xác nhận tính đúng của luận điểm hoặc hiệu lực pháp lý của văn bản."


class AppError(Exception):
    def __init__(self, code, message, status=422, details=None):
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details

    def as_dict(self):
        value = {"code": self.code, "message": self.message}
        if self.details is not None:
            value["details"] = self.details
        return {"error": value}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    if not isinstance(value, bytes):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def ident(prefix):
    return prefix + "-" + uuid.uuid4().hex[:20]


def normalized_quote(value):
    return " ".join(unicodedata.normalize("NFC", value).split())


def fold(value):
    value = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
    return "".join(c for c in value if not unicodedata.combining(c))


def tokens(value):
    return re.findall(r"[a-z0-9]+", fold(value))


STOP = set("va la cua cho nhung cac mot duoc voi trong tai theo khi neu de co ve tu den nhu hay nay do da dang se can thi ma nen vao ra tren duoi bang boi nao gi nhu the nao la gi tai sao".split())
META_FIELDS = ("title", "issuer", "document_number", "published_date", "url", "kind", "text_kind")


def required_string(data, key, minimum=0, maximum=1000, default=None):
    value = data.get(key, default)
    if not isinstance(value, str):
        raise AppError("INVALID_FIELD", f"Trường {key} phải là chuỗi ký tự.")
    value = unicodedata.normalize("NFC", value).strip()
    if len(value) < minimum or len(value) > maximum:
        raise AppError("INVALID_LENGTH", f"Trường {key} cần từ {minimum} đến {maximum} ký tự.")
    if any(ord(c) < 32 and c not in "\n\t\r" for c in value):
        raise AppError("INVALID_TEXT", f"Trường {key} chứa ký tự điều khiển không hợp lệ.")
    return value


def ensure_object(data):
    if not isinstance(data, dict):
        raise AppError("INVALID_JSON", "Nội dung yêu cầu phải là một đối tượng JSON.", 400)


def validate_metadata(data):
    ensure_object(data)
    out = {
        "title": required_string(data, "title", 3, 300),
        "issuer": required_string(data, "issuer", 2, 200),
        "document_number": required_string(data, "document_number", 0, 100, ""),
        "published_date": required_string(data, "published_date", 0, 10, ""),
        "url": required_string(data, "url", 0, 2000, ""),
        "kind": required_string(data, "kind", 1, 30, "learning_note"),
        "text_kind": required_string(data, "text_kind", 1, 30, "summary"),
    }
    if out["kind"] not in ("law", "learning_note") or out["text_kind"] not in ("summary", "original"):
        raise AppError("INVALID_ENUM", "Loại nguồn hoặc loại nội dung không hợp lệ.")
    if out["published_date"]:
        try:
            if dt.date.fromisoformat(out["published_date"]).isoformat() != out["published_date"]:
                raise ValueError()
        except ValueError:
            raise AppError("INVALID_DATE", "Ngày công bố phải có dạng YYYY-MM-DD và là ngày hợp lệ.")
    if out["url"]:
        try:
            u = urlsplit(out["url"])
            valid = u.scheme == "https" and bool(u.hostname) and not u.username and not u.password and not any(c.isspace() for c in out["url"])
            _ = u.port
        except ValueError:
            valid = False
        if not valid:
            raise AppError("INVALID_URL", "Đường dẫn nguồn phải là HTTPS, có tên miền và không chứa thông tin đăng nhập.")
    if out["kind"] == "law" and not (out["url"] and out["document_number"] and out["published_date"]):
        raise AppError("INCOMPLETE_METADATA", "Nguồn văn bản pháp luật cần số hiệu, ngày công bố và đường dẫn HTTPS.")
    return out


def validate_segments(value, preserve_ids=False):
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise AppError("INVALID_SEGMENTS", "Mỗi phiên bản cần từ 1 đến 100 đoạn học liệu.")
    out, locators, ids = [], set(), set()
    for i, item in enumerate(value, 1):
        ensure_object(item)
        title = required_string(item, "title", 1, 250, f"Đoạn {i}")
        locator = required_string(item, "locator", 1, 250, f"Đoạn {i}")
        text = required_string(item, "text", 20, 12000)
        if normalized_quote(locator).casefold() in locators:
            raise AppError("DUPLICATE_LOCATOR", "Vị trí đoạn không được trùng trong cùng một phiên bản.")
        locators.add(normalized_quote(locator).casefold())
        sid = item.get("id") if preserve_ids else None
        sid = sid or ident("seg")
        if not isinstance(sid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", sid) or sid in ids:
            raise AppError("INVALID_ID", "Mã đoạn không hợp lệ hoặc bị trùng.")
        ids.add(sid)
        out.append({"id": sid, "title": title, "locator": locator, "text": text})
    if sum(len(x["text"]) for x in out) > 180000:
        raise AppError("SOURCE_TOO_LARGE", "Tổng nội dung một phiên bản vượt 180000 ký tự.")
    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sources(
 id TEXT PRIMARY KEY,title TEXT NOT NULL,issuer TEXT NOT NULL,document_number TEXT NOT NULL,
 published_date TEXT NOT NULL,url TEXT NOT NULL,kind TEXT NOT NULL CHECK(kind IN ('law','learning_note')),
 text_kind TEXT NOT NULL CHECK(text_kind IN ('summary','original')),status TEXT NOT NULL CHECK(status IN ('draft','reviewed')),
 current_version INTEGER NOT NULL,review_note TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_versions(
 source_id TEXT NOT NULL REFERENCES sources(id),version INTEGER NOT NULL,sha256 TEXT NOT NULL,
 metadata_json TEXT NOT NULL,segments_json TEXT NOT NULL,change_note TEXT NOT NULL,created_at TEXT NOT NULL,
 status TEXT NOT NULL,review_note TEXT NOT NULL,PRIMARY KEY(source_id,version));
CREATE TABLE IF NOT EXISTS segments(
 id TEXT PRIMARY KEY,source_id TEXT NOT NULL,source_version INTEGER NOT NULL,title TEXT NOT NULL,
 locator TEXT NOT NULL,text TEXT NOT NULL,sha256 TEXT NOT NULL,
 FOREIGN KEY(source_id,source_version) REFERENCES source_versions(source_id,version));
CREATE INDEX IF NOT EXISTS segments_source ON segments(source_id,source_version);
CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,description TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),text TEXT NOT NULL,
 claim_type TEXT NOT NULL CHECK(claim_type IN ('factual','analysis','proposal')),created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS claims_project ON claims(project_id);
CREATE TABLE IF NOT EXISTS evidence(
 id TEXT PRIMARY KEY,claim_id TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
 segment_id TEXT NOT NULL REFERENCES segments(id),source_id TEXT NOT NULL REFERENCES sources(id),source_version INTEGER NOT NULL,
 source_sha256 TEXT NOT NULL,segment_sha256 TEXT NOT NULL,quote TEXT NOT NULL,note TEXT NOT NULL,
 snapshot_json TEXT NOT NULL,snapshot_hash TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(claim_id,segment_id,quote));
CREATE INDEX IF NOT EXISTS evidence_claim ON evidence(claim_id);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT NOT NULL,action TEXT NOT NULL,
 entity_id TEXT NOT NULL,details_json TEXT NOT NULL,previous_hash TEXT NOT NULL,event_hash TEXT NOT NULL);
"""


class Store:
    def __init__(self, data_dir, seed_path=None, seed_demo=True):
        self.data_dir = Path(data_dir).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "so_can_cu.sqlite3"
        self._lock = threading.RLock()
        with self.connect() as c:
            c.execute("PRAGMA journal_mode=WAL")
            c.executescript(SCHEMA)
            previous = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if previous and int(previous[0]) != SCHEMA_VERSION:
                raise RuntimeError("Phiên bản cơ sở dữ liệu không tương thích; không tự ghi đè.")
            c.execute("INSERT OR IGNORE INTO meta VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        if seed_demo:
            self.initialize_seed(seed_path)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=10)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA busy_timeout=10000")
        return c

    @contextlib.contextmanager
    def read(self):
        c = self.connect()
        try:
            c.execute("BEGIN")
            yield c
        finally:
            c.rollback()
            c.close()

    @contextlib.contextmanager
    def write(self):
        with self._lock:
            c = self.connect()
            try:
                c.execute("BEGIN IMMEDIATE")
                yield c
                c.commit()
            except Exception:
                c.rollback()
                raise
            finally:
                c.close()

    def _audit(self, c, action, entity_id, details):
        last = c.execute("SELECT event_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        previous = last[0] if last else "0" * 64
        event = {"created_at": now(), "action": action, "entity_id": entity_id, "details": details, "previous_hash": previous}
        event_hash = digest(canonical(event))
        c.execute("INSERT INTO audit(created_at,action,entity_id,details_json,previous_hash,event_hash) VALUES(?,?,?,?,?,?)", (event["created_at"], action, entity_id, canonical(details), previous, event_hash))

    def _source(self, c, sid):
        r = c.execute("SELECT s.*,v.sha256,(SELECT COUNT(*) FROM segments g WHERE g.source_id=s.id AND g.source_version=s.current_version) AS segment_count FROM sources s JOIN source_versions v ON s.id=v.source_id AND s.current_version=v.version WHERE s.id=?", (sid,)).fetchone()
        if not r:
            raise AppError("NOT_FOUND", "Không tìm thấy nguồn học liệu.", 404)
        d = dict(r)
        d["version"] = d.pop("current_version")
        return d

    def _insert_source(self, c, meta, segments, sid, status="draft", review_note="", change_note="Khởi tạo nguồn"):
        timestamp = now()
        values = [meta[k] for k in META_FIELDS]
        c.execute("INSERT INTO sources VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", [sid] + values + [status, 1, review_note, timestamp, timestamp])
        self._insert_version(c, sid, 1, meta, segments, status, review_note, change_note, timestamp)
        self._audit(c, "source.create", sid, {"version": 1, "status": status, "segments": len(segments)})

    def _insert_version(self, c, sid, version, meta, segments, status, review_note, change_note, timestamp):
        sha = digest(canonical({"metadata": meta, "segments": segments}))
        c.execute("INSERT INTO source_versions VALUES(?,?,?,?,?,?,?,?,?)", (sid, version, sha, canonical(meta), canonical(segments), change_note, timestamp, status, review_note))
        for g in segments:
            c.execute("INSERT INTO segments VALUES(?,?,?,?,?,?,?)", (g["id"], sid, version, g["title"], g["locator"], g["text"], digest(g["text"])))

    def initialize_seed(self, seed_path):
        with self.read() as c:
            if c.execute("SELECT 1 FROM meta WHERE key='seed_initialized'").fetchone():
                return
        seed_path = Path(seed_path) if seed_path else Path(__file__).parent / "data" / "source_seed.json"
        if seed_path.exists():
            seed = json.loads(seed_path.read_text(encoding="utf-8"))
        else:
            seed = {"schema_version": 1, "corpus_note": "Dữ liệu thực hành mô phỏng, không phải dữ liệu của Học viện.", "sources": [{"id": "src-demo", "title": "Quy trình thực hành kiểm tra nguồn", "issuer": "Tài liệu thực hành của sản phẩm mẫu", "document_number": "DEMO-01", "published_date": "", "url": "", "kind": "learning_note", "text_kind": "original", "status": "reviewed", "review_note": "Tài liệu mô phỏng do sản phẩm mẫu xây dựng.", "segments": [{"id": "seg-demo-01", "title": "Kiểm tra trích dẫn", "locator": "Mục 1", "text": "Mỗi luận điểm thực chứng cần gắn với đoạn nguồn có thể kiểm tra. Khi nguồn thay đổi phiên bản, người viết phải đọc lại đoạn dẫn trước khi sử dụng."}]}]}
        if seed.get("schema_version") != 1 or not isinstance(seed.get("sources"), list):
            raise RuntimeError("Tệp dữ liệu mẫu không đúng định dạng phiên bản 1.")
        with self.write() as c:
            if c.execute("SELECT 1 FROM meta WHERE key='seed_initialized'").fetchone():
                return
            for raw in seed["sources"]:
                meta = validate_metadata(raw)
                segs = validate_segments(raw["segments"], preserve_ids=True)
                sid = raw.get("id", ident("src"))
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", sid):
                    raise RuntimeError("Mã nguồn mẫu không hợp lệ.")
                status = raw.get("status", "draft")
                if status not in ("draft", "reviewed"):
                    raise RuntimeError("Trạng thái nguồn mẫu không hợp lệ.")
                review = raw.get("review_note", "")
                if status == "reviewed" and len(review.strip()) < 10:
                    raise RuntimeError("Nguồn mẫu đã đối chiếu phải có ghi chú kiểm tra.")
                self._insert_source(c, meta, segs, sid, status, review)
            c.execute("INSERT INTO meta VALUES('corpus_note',?)", (str(seed.get("corpus_note", "Dữ liệu thực hành mô phỏng.")),))
            timestamp = now()
            c.execute("INSERT INTO projects VALUES(?,?,?,?,?)", ("prj-demo", "Hồ sơ thực hành kiểm tra căn cứ", "Hồ sơ mô phỏng để thực hành thao tác. Các luận điểm minh họa chưa phải đề xuất hoặc kết quả triển khai tại Học viện.", timestamp, timestamp))
            examples = [
                ("clm-demo-01", "Mỗi đoạn dẫn trong hồ sơ cần giữ được thông tin nguồn và vị trí để người đọc có thể kiểm tra.", "analysis"),
                ("clm-demo-02", "Ví dụ để kiểm tra lỗi thiếu căn cứ: sản phẩm đã làm giảm một nửa thời gian tra cứu của người học trong thực tế.", "factual"),
                ("clm-demo-03", "Đề xuất tổ chức một buổi thực hành để người học nhận diện nguồn, thêm dẫn chứng và xem cảnh báo thay đổi phiên bản.", "proposal"),
            ]
            for cid, text, ctype in examples:
                c.execute("INSERT INTO claims VALUES(?,?,?,?,?,?)", (cid, "prj-demo", text, ctype, timestamp, timestamp))
            self._audit(c, "demo.initialize", "prj-demo", {"claims": len(examples), "note": "Luận điểm thực chứng cố ý thiếu căn cứ để trình diễn cảnh báo."})
            c.execute("INSERT INTO meta VALUES('seed_initialized',?)", (timestamp,))

    def corpus_note(self):
        with self.read() as c:
            r = c.execute("SELECT value FROM meta WHERE key='corpus_note'").fetchone()
            return r[0] if r else "Dữ liệu do người sử dụng nhập và tự đối chiếu."

    def list_sources(self):
        with self.read() as c:
            return [self._source(c, x[0]) for x in c.execute("SELECT id FROM sources ORDER BY created_at,id")]

    def get_source(self, sid):
        with self.read() as c:
            source = self._source(c, sid)
            segments = [dict(r) for r in c.execute("SELECT * FROM segments WHERE source_id=? AND source_version=? ORDER BY rowid", (sid, source["version"]))]
            versions = [dict(r) for r in c.execute("SELECT version,sha256,change_note,created_at,status,review_note FROM source_versions WHERE source_id=? ORDER BY version DESC", (sid,))]
            return {"source": source, "segments": segments, "versions": versions}

    def create_source(self, data):
        ensure_object(data)
        if data.get("status", "draft") != "draft":
            raise AppError("REVIEW_REQUIRED", "Nguồn mới phải bắt đầu ở trạng thái bản nháp.")
        meta, segs, sid = validate_metadata(data), validate_segments(data.get("segments")), ident("src")
        with self.write() as c:
            self._insert_source(c, meta, segs, sid)
        out = self.get_source(sid)
        return {"source": out["source"], "segments": out["segments"]}

    def review_source(self, sid, data):
        ensure_object(data)
        note = required_string(data, "review_note", 10, 2000)
        with self.write() as c:
            s = self._source(c, sid)
            validate_metadata(s)
            self._validate_version(c, sid, s["version"], raise_error=True)
            c.execute("UPDATE sources SET status='reviewed',review_note=?,updated_at=? WHERE id=?", (note, now(), sid))
            c.execute("UPDATE source_versions SET status='reviewed',review_note=? WHERE source_id=? AND version=?", (note, sid, s["version"]))
            self._audit(c, "source.review", sid, {"version": s["version"], "review_note": note})
            return {"source": self._source(c, sid)}

    def revise_source(self, sid, data):
        ensure_object(data)
        segs = validate_segments(data.get("segments"))
        note = required_string(data, "change_note", 10, 2000)
        with self.write() as c:
            old = self._source(c, sid)
            self._validate_version(c, sid, old["version"], raise_error=True)
            meta = {k: old[k] for k in META_FIELDS}
            version, timestamp = old["version"] + 1, now()
            self._insert_version(c, sid, version, meta, segs, "draft", "", note, timestamp)
            c.execute("UPDATE sources SET current_version=?,status='draft',review_note='',updated_at=? WHERE id=?", (version, timestamp, sid))
            self._audit(c, "source.revise", sid, {"from_version": old["version"], "to_version": version, "change_note": note, "segments": len(segs)})
        out = self.get_source(sid)
        return {"source": out["source"], "segments": out["segments"]}

    def search(self, query, source_id="", reviewed_only=True, limit=20):
        if not isinstance(query, str) or len(query) > 200:
            raise AppError("INVALID_QUERY", "Nội dung tìm kiếm không được vượt 200 ký tự.")
        if not isinstance(limit, int) or not 1 <= limit <= 50:
            raise AppError("INVALID_LIMIT", "Số kết quả cần nằm trong khoảng 1 đến 50.")
        query = normalized_quote(query)
        qtokens = list(dict.fromkeys(t for t in tokens(query) if t not in STOP))
        if not qtokens:
            return {"query": query, "results": [], "count": 0}
        with self.read() as c:
            sql = "SELECT g.*,s.title AS source_title,s.document_number,s.issuer,s.url AS source_url,s.status AS source_status,s.text_kind,v.sha256 AS source_sha256 FROM segments g JOIN sources s ON g.source_id=s.id AND g.source_version=s.current_version JOIN source_versions v ON v.source_id=g.source_id AND v.version=g.source_version WHERE 1=1"
            params = []
            if reviewed_only:
                sql += " AND s.status='reviewed'"
            if source_id:
                sql += " AND s.id=?"
                params.append(source_id)
            rows = [dict(r) for r in c.execute(sql, params)]
        results = []
        # Coverage is weighted by rarity across this filtered corpus. An unknown
        # distinctive word must not be outweighed by generic words such as
        # "dùng", "liệu" or "sơ" in an unrelated query.
        document_words = [set(tokens(r["title"] + " " + r["locator"] + " " + r["source_title"] + " " + r["document_number"] + " " + r["text"])) for r in rows]
        rarity = {t: 1 + math.log((len(rows) + 1) / (1 + sum(t in words for words in document_words))) for t in qtokens}
        total_query_weight = sum(rarity.values())
        numeric = [t for t in qtokens if t.isdigit()]
        for r in rows:
            title_words = set(tokens(r["title"] + " " + r["locator"]))
            source_words = set(tokens(r["source_title"] + " " + r["document_number"]))
            body_words = tokens(r["text"])
            body_set = set(body_words)
            allwords = title_words | source_words | body_set
            if numeric and not all(t in allwords for t in numeric):
                continue
            matched = [t for t in qtokens if t in allwords]
            coverage = sum(rarity[t] for t in matched) / total_query_weight
            if not matched or coverage < 0.5:
                continue
            # A positive match in the segment content/title avoids returning every
            # segment only because a generic source title matches the query.
            if not any(t in title_words | body_set for t in matched):
                continue
            score = sum(rarity[t] * ((4 if t in title_words else 0) + (1.5 if t in source_words else 0) + (1 + min(body_words.count(t), 4) * .2 if t in body_set else 0)) for t in matched)
            score *= coverage
            if fold(query) in fold(r["title"] + " " + r["text"]):
                score += 5
            r["score"] = round(score, 3)
            results.append(r)
        results.sort(key=lambda r: (-r["score"], r["source_id"], r["id"]))
        return {"query": query, "results": results[:limit], "count": len(results)}

    def _project(self, c, pid):
        r = c.execute("SELECT p.*,(SELECT COUNT(*) FROM claims WHERE project_id=p.id) AS claim_count FROM projects p WHERE id=?", (pid,)).fetchone()
        if not r:
            raise AppError("NOT_FOUND", "Không tìm thấy hồ sơ.", 404)
        return dict(r)

    def list_projects(self):
        with self.read() as c:
            return [self._project(c, x[0]) for x in c.execute("SELECT id FROM projects ORDER BY created_at,id")]

    def create_project(self, data):
        ensure_object(data)
        title = required_string(data, "title", 3, 250)
        description = required_string(data, "description", 0, 4000, "")
        pid, timestamp = ident("prj"), now()
        with self.write() as c:
            c.execute("INSERT INTO projects VALUES(?,?,?,?,?)", (pid, title, description, timestamp, timestamp))
            self._audit(c, "project.create", pid, {"title": title})
            return {"project": self._project(c, pid)}

    def update_project(self, pid, data):
        ensure_object(data)
        with self.write() as c:
            old = self._project(c, pid)
            title = required_string(data, "title", 3, 250, old["title"])
            description = required_string(data, "description", 0, 4000, old["description"])
            c.execute("UPDATE projects SET title=?,description=?,updated_at=? WHERE id=?", (title, description, now(), pid))
            self._audit(c, "project.update", pid, {"title": title})
            return {"project": self._project(c, pid)}

    def _evidence(self, r):
        d = dict(r)
        snap = json.loads(d.pop("snapshot_json"))
        d.pop("snapshot_hash", None)
        d.update(snap["display"])
        return d

    def _claim(self, c, cid):
        r = c.execute("SELECT * FROM claims WHERE id=?", (cid,)).fetchone()
        if not r:
            raise AppError("NOT_FOUND", "Không tìm thấy luận điểm.", 404)
        d = dict(r)
        d["evidence"] = [self._evidence(x) for x in c.execute("SELECT * FROM evidence WHERE claim_id=? ORDER BY created_at,id", (cid,))]
        return d

    def get_project(self, pid):
        with self.read() as c:
            project = self._project(c, pid)
            claims = [self._claim(c, x[0]) for x in c.execute("SELECT id FROM claims WHERE project_id=? ORDER BY created_at,id", (pid,))]
            return {"project": project, "claims": claims}

    def _validate_claim(self, data, old=None):
        ensure_object(data)
        old = old or {}
        text = required_string(data, "text", 20, 4000, old.get("text"))
        ctype = required_string(data, "claim_type", 1, 20, old.get("claim_type", "factual"))
        if ctype not in ("factual", "analysis", "proposal"):
            raise AppError("INVALID_ENUM", "Loại luận điểm phải là factual, analysis hoặc proposal.")
        return text, ctype

    def create_claim(self, pid, data):
        text, ctype = self._validate_claim(data)
        cid, timestamp = ident("clm"), now()
        with self.write() as c:
            self._project(c, pid)
            c.execute("INSERT INTO claims VALUES(?,?,?,?,?,?)", (cid, pid, text, ctype, timestamp, timestamp))
            c.execute("UPDATE projects SET updated_at=? WHERE id=?", (timestamp, pid))
            self._audit(c, "claim.create", cid, {"project_id": pid, "claim_type": ctype})
            return {"claim": self._claim(c, cid)}

    def update_claim(self, cid, data):
        with self.write() as c:
            old = self._claim(c, cid)
            text, ctype = self._validate_claim(data, old)
            timestamp = now()
            c.execute("UPDATE claims SET text=?,claim_type=?,updated_at=? WHERE id=?", (text, ctype, timestamp, cid))
            c.execute("UPDATE projects SET updated_at=? WHERE id=?", (timestamp, old["project_id"]))
            self._audit(c, "claim.update", cid, {"project_id": old["project_id"], "claim_type": ctype, "note": "Dẫn chứng được giữ lại; người viết phải tự xem xét quan hệ với luận điểm đã sửa."})
            return {"claim": self._claim(c, cid)}

    def delete_claim(self, cid):
        with self.write() as c:
            old = self._claim(c, cid)
            c.execute("DELETE FROM claims WHERE id=?", (cid,))
            c.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), old["project_id"]))
            self._audit(c, "claim.delete", cid, {"project_id": old["project_id"], "evidence_removed": len(old["evidence"])})
            return {"deleted": True}

    def attach_evidence(self, cid, data):
        ensure_object(data)
        gid = required_string(data, "segment_id", 1, 80)
        note = required_string(data, "note", 0, 2000, "")
        quote = required_string(data, "quote", 0, 12000, "")
        with self.write() as c:
            claim = self._claim(c, cid)
            g = c.execute("SELECT * FROM segments WHERE id=?", (gid,)).fetchone()
            if not g:
                raise AppError("NOT_FOUND", "Không tìm thấy đoạn nguồn.", 404)
            g = dict(g)
            source = self._source(c, g["source_id"])
            if source["version"] != g["source_version"]:
                raise AppError("SOURCE_CHANGED", "Đoạn này thuộc phiên bản cũ. Hãy tra cứu lại nguồn hiện hành.", 409)
            if source["status"] != "reviewed":
                raise AppError("SOURCE_UNREVIEWED", "Nguồn chưa được đối chiếu; chưa thể gắn làm dẫn chứng.")
            self._validate_version(c, source["id"], source["version"], raise_error=True)
            quote = normalized_quote(quote or g["text"])
            if not quote or quote not in normalized_quote(g["text"]):
                raise AppError("QUOTE_MISMATCH", "Đoạn trích không khớp nguyên văn nội dung học liệu đã chọn.")
            if c.execute("SELECT 1 FROM evidence WHERE claim_id=? AND segment_id=? AND quote=?", (cid, gid, quote)).fetchone():
                raise AppError("DUPLICATE_EVIDENCE", "Dẫn chứng này đã có trong luận điểm.", 409)
            display = {"source_title": source["title"], "source_url": source["url"], "locator": g["locator"], "issuer": source["issuer"], "document_number": source["document_number"], "published_date": source["published_date"], "text_kind": source["text_kind"]}
            snap = {"display": display, "segment_text": g["text"], "segment_title": g["title"], "source_id": source["id"], "source_version": source["version"], "source_sha256": source["sha256"], "segment_sha256": g["sha256"], "quote": quote}
            eid, timestamp = ident("evd"), now()
            c.execute("INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (eid, cid, gid, source["id"], source["version"], source["sha256"], g["sha256"], quote, note, canonical(snap), digest(canonical(snap)), timestamp))
            c.execute("UPDATE projects SET updated_at=? WHERE id=?", (timestamp, claim["project_id"]))
            self._audit(c, "evidence.attach", eid, {"claim_id": cid, "source_id": source["id"], "source_version": source["version"], "segment_id": gid, "quote_sha256": digest(quote)})
            return {"evidence": self._evidence(c.execute("SELECT * FROM evidence WHERE id=?", (eid,)).fetchone())}

    def delete_evidence(self, eid):
        with self.write() as c:
            old = c.execute("SELECT e.*,cl.project_id FROM evidence e JOIN claims cl ON e.claim_id=cl.id WHERE e.id=?", (eid,)).fetchone()
            if not old:
                raise AppError("NOT_FOUND", "Không tìm thấy dẫn chứng.", 404)
            c.execute("DELETE FROM evidence WHERE id=?", (eid,))
            c.execute("UPDATE projects SET updated_at=? WHERE id=?", (now(), old["project_id"]))
            self._audit(c, "evidence.delete", eid, {"claim_id": old["claim_id"], "project_id": old["project_id"]})
            return {"deleted": True}

    def _validate_version(self, c, sid, version, raise_error=False):
        r = c.execute("SELECT * FROM source_versions WHERE source_id=? AND version=?", (sid, version)).fetchone()
        valid = False
        if r:
            try:
                meta, segs = json.loads(r["metadata_json"]), json.loads(r["segments_json"])
                actual = [dict(x) for x in c.execute("SELECT id,title,locator,text,sha256 FROM segments WHERE source_id=? AND source_version=? ORDER BY rowid", (sid, version))]
                rows_match = len(actual) == len(segs) and all({k: a[k] for k in ("id", "title", "locator", "text")} == b and digest(a["text"]) == a["sha256"] for a, b in zip(actual, segs))
                valid = digest(canonical({"metadata": meta, "segments": segs})) == r["sha256"] and rows_match
                current = c.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
                if current and current["current_version"] == version:
                    valid = valid and {k: current[k] for k in META_FIELDS} == meta
            except (ValueError, TypeError, KeyError):
                valid = False
        if not valid and raise_error:
            raise AppError("SOURCE_INTEGRITY_ERROR", "Bản lưu nguồn không nhất quán với mã kiểm tra. Dừng thao tác và kiểm tra bản sao lưu.", 409)
        return valid

    def check_project(self, pid):
        with self.read() as c:
            self._project(c, pid)
            claims = c.execute("SELECT * FROM claims WHERE project_id=? ORDER BY created_at,id", (pid,)).fetchall()
            summary = {"claims": len(claims), "pass": 0, "warning": 0, "error": 0}
            issues, checks = [], []
            if not claims:
                issues.append({"claim_id": None, "code": "EMPTY_PROJECT", "severity": "warning", "message": "Hồ sơ chưa có luận điểm để kiểm tra."})
            validated_versions = {}
            for claim in claims:
                local = []
                def add(code, severity, message, eid=None):
                    item = {"claim_id": claim["id"], "code": code, "severity": severity, "message": message}
                    if eid:
                        item["evidence_id"] = eid
                    local.append(item)
                evidence = c.execute("SELECT * FROM evidence WHERE claim_id=? ORDER BY created_at,id", (claim["id"],)).fetchall()
                if not evidence and claim["claim_type"] != "proposal":
                    add("MISSING_EVIDENCE", "error" if claim["claim_type"] == "factual" else "warning", "Luận điểm chưa có dẫn chứng; cần bổ sung căn cứ hoặc điều chỉnh cách trình bày.")
                for e in evidence:
                    source = self._source(c, e["source_id"])
                    if source["status"] != "reviewed":
                        add("SOURCE_UNREVIEWED", "error", "Phiên bản hiện tại của nguồn chưa được đối chiếu.", e["id"])
                    if source["version"] != e["source_version"]:
                        add("SOURCE_CHANGED", "error", f"Dẫn chứng giữ phiên bản {e['source_version']}, nguồn hiện tại đã là phiên bản {source['version']}; cần đọc lại và gắn dẫn chứng mới.", e["id"])
                    key = (e["source_id"], e["source_version"])
                    if key not in validated_versions:
                        validated_versions[key] = self._validate_version(c, *key)
                    try:
                        snap = json.loads(e["snapshot_json"])
                        matching = digest(canonical(snap)) == e["snapshot_hash"] and snap["source_sha256"] == e["source_sha256"] and snap["segment_sha256"] == e["segment_sha256"] and snap["source_id"] == e["source_id"] and snap["source_version"] == e["source_version"] and snap["quote"] == e["quote"] and digest(snap["segment_text"]) == e["segment_sha256"]
                        pinned = c.execute("SELECT sha256 FROM source_versions WHERE source_id=? AND version=?", key).fetchone()
                        matching = matching and pinned and pinned[0] == e["source_sha256"] and validated_versions[key]
                        if not matching:
                            add("SNAPSHOT_HASH_MISMATCH", "error", "Bản lưu dẫn chứng hoặc nguồn không khớp mã kiểm tra đã lưu.", e["id"])
                        if normalized_quote(e["quote"]) not in normalized_quote(snap["segment_text"]):
                            add("QUOTE_MISMATCH", "error", "Đoạn trích không còn khớp nội dung của bản lưu dẫn chứng.", e["id"])
                    except (ValueError, TypeError, KeyError):
                        add("SNAPSHOT_HASH_MISMATCH", "error", "Bản lưu dẫn chứng không đọc được hoặc thiếu trường kiểm tra.", e["id"])
                state = "error" if any(i["severity"] == "error" for i in local) else "warning" if local else "pass"
                summary[state] += 1
                checks.append({"claim_id": claim["id"], "status": state, "issues": local})
                issues.extend(local)
            return {"summary": summary, "checks": checks, "issues": issues, "note": TECHNICAL_NOTE, "checked_at": now()}

    def audit(self):
        with self.read() as c:
            rows = c.execute("SELECT * FROM audit ORDER BY id").fetchall()
        events, previous, invalid = [], "0" * 64, None
        for row in rows:
            e = dict(row)
            try:
                e["details"] = json.loads(e.pop("details_json"))
                data = {k: e[k] for k in ("created_at", "action", "entity_id", "details", "previous_hash")}
                valid = e["previous_hash"] == previous and digest(canonical(data)) == e["event_hash"]
            except (ValueError, KeyError, TypeError):
                e["details"] = {"error": "Không đọc được nội dung nhật ký"}
                valid = False
            if not valid and invalid is None:
                invalid = e["id"]
            previous = e["event_hash"]
            events.append(e)
        verification = {"valid": invalid is None, "checked": len(rows), "last_hash": previous, "note": "Chuỗi băm giúp phát hiện bất nhất; người có quyền sửa toàn bộ cơ sở dữ liệu có thể tính lại chuỗi."}
        if invalid is not None:
            verification["first_invalid_id"] = invalid
        return {"events": list(reversed(events[-200:])), "verification": verification}

    def bootstrap(self):
        sources, projects = self.list_sources(), self.list_projects()
        issues = sum(len(self.check_project(p["id"])["issues"]) for p in projects)
        with self.read() as c:
            count = c.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        return {"app": {"name": "Sổ căn cứ", "version": VERSION, "mode": "single_user_local", "corpus_note": self.corpus_note()}, "stats": {"sources": len(sources), "reviewed_sources": sum(s["status"] == "reviewed" for s in sources), "projects": len(projects), "claims": count, "issues": issues}, "projects": projects, "sources": sources}

    def export_project(self, pid, format="html"):
        # Keep the dossier and its validation report in one application state
        # while another browser tab may be submitting a write.
        with self._lock:
            return self._export_project_locked(pid, format)

    def _export_project_locked(self, pid, format="html"):
        if format not in ("html", "markdown", "json"):
            raise AppError("INVALID_FORMAT", "Định dạng xuất phải là html, markdown hoặc json.")
        project = self.get_project(pid)
        checks = self.check_project(pid)
        bibliography, numbers = [], {}
        for claim in project["claims"]:
            for e in claim["evidence"]:
                key = (e["source_id"], e["source_version"])
                if key not in numbers:
                    number = len(numbers) + 1
                    numbers[key] = number
                    year = e["published_date"][:4] or "không ghi năm"
                    ref = f"{e['issuer']} ({year}), {e['source_title']}"
                    if e["document_number"]:
                        ref += f", {e['document_number']}"
                    if e["published_date"]:
                        ref += f", ngày {e['published_date']}"
                    ref += f". Bản học liệu lưu phiên bản {e['source_version']}."
                    if e["text_kind"] == "summary":
                        ref += " Nội dung học liệu là bản tóm lược; đối chiếu văn bản gốc khi sử dụng."
                    if e["source_url"]:
                        ref += " " + e["source_url"]
                    bibliography.append({"number": number, "text": ref, "source_id": e["source_id"], "source_version": e["source_version"], "sha256": e["source_sha256"]})
                e["citation_number"] = numbers[key]
        out = {"application_version": VERSION, "exported_at": now(), "technical_note": TECHNICAL_NOTE, **project, "validation": checks, "bibliography": bibliography}
        basename = "so_can_cu_" + pid
        if format == "json":
            return json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8"), "application/json; charset=utf-8", basename + ".json"
        issue_by_claim = {x["claim_id"]: x["issues"] for x in checks["checks"]}
        labels = {"factual": "Nhận định thực chứng", "analysis": "Phân tích", "proposal": "Kiến nghị"}
        if format == "markdown":
            def esc(s):
                s = html.escape(str(s), quote=False)
                return re.sub(r"([\\`*_\[\]])", r"\\\1", s)
            lines = ["# " + esc(project["project"]["title"]), "", esc(project["project"]["description"]), "", TECHNICAL_NOTE, "", "Thời điểm xuất: " + out["exported_at"], ""]
            for issue in checks["issues"]:
                if issue["claim_id"] is None:
                    lines.extend(["CẢNH BÁO " + issue["code"] + ": " + esc(issue["message"]), ""])
            for n, claim in enumerate(project["claims"], 1):
                lines.extend([f"## {n}. {labels[claim['claim_type']]}", "", esc(claim["text"]), ""])
                for e in claim["evidence"]:
                    lines.extend(["> " + esc(e["quote"]).replace("\n", "\n> "), "", f"[{e['citation_number']}] {esc(e['locator'])}; phiên bản {e['source_version']}.", ""])
                    if e["note"]:
                        lines.extend(["Ghi chú: " + esc(e["note"]), ""])
                for issue in issue_by_claim.get(claim["id"], []):
                    lines.extend(["CẢNH BÁO " + issue["code"] + ": " + esc(issue["message"]), ""])
            lines.extend(["## Tài liệu tham khảo", ""] + [f"[{r['number']}] {esc(r['text'])}" for r in bibliography])
            return "\n".join(lines).encode("utf-8"), "text/markdown; charset=utf-8", basename + ".md"
        e = html.escape
        parts = ["<!doctype html><html lang='vi'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>" + e(project["project"]["title"]) + "</title><style>body{max-width:900px;margin:40px auto;padding:0 24px;font:17px/1.65 Georgia,'Times New Roman',serif;color:#172331}h1,h2{line-height:1.3}h1{font-size:30px}h2{font-size:21px;margin-top:30px}blockquote{border-left:3px solid #ccd3da;margin:16px 0;padding:4px 18px}.notice,.warning{padding:12px;border:1px solid #b6bec7}.warning{background:#fff5e6}li{margin-bottom:12px}small{color:#425466}@media print{body{margin:0;padding:0;max-width:none}.claim{break-inside:avoid}a{color:inherit}}</style><body>", "<h1>" + e(project["project"]["title"]) + "</h1>", "<p>" + e(project["project"]["description"]) + "</p>", "<p class='notice'>" + TECHNICAL_NOTE + "</p>", "<p><small>Thời điểm xuất " + e(out["exported_at"]) + "; phần mềm " + VERSION + ". Số luận điểm " + str(checks["summary"]["claims"]) + "; lỗi " + str(checks["summary"]["error"]) + "; cảnh báo " + str(checks["summary"]["warning"]) + ".</small></p>"]
        for n, claim in enumerate(project["claims"], 1):
            parts.extend(["<section class='claim'><h2>" + str(n) + ". " + labels[claim["claim_type"]] + "</h2><p>" + e(claim["text"]).replace("\n", "<br>") + "</p>"])
            for ev in claim["evidence"]:
                parts.append("<blockquote>" + e(ev["quote"]) + "</blockquote><p><small>[" + str(ev["citation_number"]) + "] " + e(ev["locator"]) + "; phiên bản " + str(ev["source_version"]) + "; " + ("bản tóm lược học liệu" if ev["text_kind"] == "summary" else "nội dung lưu nguyên văn") + ".</small></p>")
                if ev["note"]:
                    parts.append("<p>Ghi chú " + e(ev["note"]) + "</p>")
            for issue in issue_by_claim.get(claim["id"], []):
                parts.append("<p class='warning'><strong>" + e(issue["code"]) + "</strong> " + e(issue["message"]) + "</p>")
            parts.append("</section>")
        if not project["claims"]:
            parts.append("<p class='warning'>Hồ sơ chưa có luận điểm để kiểm tra.</p>")
        parts.append("<h2>Tài liệu tham khảo</h2><ol>")
        parts.extend("<li>" + e(r["text"]) + "<br><small>SHA-256 " + e(r["sha256"]) + "</small></li>" for r in bibliography)
        parts.append("</ol></body></html>")
        return "".join(parts).encode("utf-8"), "text/html; charset=utf-8", basename + ".html"

    def backup(self):
        with tempfile.TemporaryDirectory(prefix="so_can_cu_backup_") as tmp:
            target = Path(tmp) / "so_can_cu.sqlite3"
            with self.read() as src:
                dst = sqlite3.connect(target)
                try:
                    src.backup(dst)
                    quick = dst.execute("PRAGMA quick_check").fetchone()[0]
                    foreign = dst.execute("PRAGMA foreign_key_check").fetchall()
                    last = dst.execute("SELECT event_hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
                    audit_count = dst.execute("SELECT COUNT(*) FROM audit").fetchone()[0]
                finally:
                    dst.close()
            if quick != "ok" or foreign:
                raise AppError("BACKUP_INTEGRITY_ERROR", "Bản sao dữ liệu không vượt qua kiểm tra nhất quán.", 409)
            payload = target.read_bytes()
        readme = ("SỔ CĂN CỨ — BẢN SAO LƯU\n\nTệp so_can_cu.sqlite3 là bản sao nhất quán tạo bằng SQLite backup API.\nChạy python tools/verify_backup.py <tep.zip> trước khi dùng. Dừng ứng dụng trước khi phục hồi thủ công vào thư mục dữ liệu mới. Giữ bản gốc cho đến khi kiểm tra xong. Không có chức năng tự ghi đè dữ liệu đang sử dụng.\nMã SHA-256 phát hiện thay đổi so với bản kê, không phải chữ ký số hay chứng nhận nguồn gốc.\n").encode("utf-8")
        manifest = {"schema_version": 1, "application_version": VERSION, "created_at": now(), "files": {"so_can_cu.sqlite3": {"sha256": digest(payload), "size": len(payload)}, "README.txt": {"sha256": digest(readme), "size": len(readme)}}, "audit_checkpoint": {"events": audit_count, "last_hash": last[0] if last else "0" * 64}, "note": "Bản kê không có chữ ký; lưu mốc kiểm tra độc lập nếu cần phát hiện việc thay cả dữ liệu và bản kê."}
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("so_can_cu.sqlite3", payload)
            z.writestr("README.txt", readme)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return buf.getvalue(), "application/zip", "so_can_cu_backup_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S") + ".zip"
