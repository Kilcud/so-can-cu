"""Executable invariants and adverse scenarios for evidence provenance."""
import copy
import io
import json
import sqlite3
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from store import AppError, Store, digest, normalized_quote
from tools.verify_backup import verify


def source_payload():
    return {
        "title": "Học liệu thực hành kiểm tra nguồn",
        "issuer": "Nhóm thực hành mô phỏng",
        "document_number": "DEMO-TEST-01",
        "published_date": "2026-10-26",
        "url": "",
        "kind": "learning_note",
        "text_kind": "original",
        "segments": [
            {"title": "Trích dẫn có phiên bản", "locator": "Mục 1", "text": "Khi học liệu thay đổi phiên bản, người viết phải kiểm tra lại đoạn trích và ghi nhận nguồn đã sử dụng."},
            {"title": "Sao lưu hồ sơ", "locator": "Mục 2", "text": "Bản sao lưu phải được kiểm tra trên thư mục tách biệt trước khi phục hồi dữ liệu vào môi trường sử dụng."},
        ],
    }


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name, seed_demo=False)
        self.source = self.store.create_source(source_payload())["source"]
        self.sid = self.source["id"]
        self.project = self.store.create_project({"title": "Hồ sơ kiểm thử độc lập", "description": "Dữ liệu mô phỏng"})["project"]
        self.pid = self.project["id"]
        self.claim = self.store.create_claim(self.pid, {"text": "Dẫn chứng cần giữ phiên bản để người đọc có thể đối chiếu lại.", "claim_type": "factual"})["claim"]
        self.cid = self.claim["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def reviewed(self):
        self.store.review_source(self.sid, {"review_note": "Đã đối chiếu nội dung do bộ kiểm thử tạo."})
        return self.store.get_source(self.sid)["segments"][0]

    def attached(self):
        g = self.reviewed()
        return self.store.attach_evidence(self.cid, {"segment_id": g["id"], "quote": g["text"], "note": "Phù hợp với ví dụ thực hành."})["evidence"]

    def assert_app_error(self, code, fn, *args):
        with self.assertRaises(AppError) as caught:
            fn(*args)
        self.assertEqual(code, caught.exception.code)

    def test_new_source_is_draft(self):
        self.assertEqual("draft", self.source["status"])
        self.assertEqual(1, self.source["version"])

    def test_cannot_self_assign_reviewed_on_creation(self):
        data = source_payload()
        data["status"] = "reviewed"
        self.assert_app_error("REVIEW_REQUIRED", self.store.create_source, data)

    def test_invalid_date_rejected(self):
        data = source_payload()
        data["published_date"] = "2026-02-30"
        self.assert_app_error("INVALID_DATE", self.store.create_source, data)

    def test_url_schemes_and_userinfo_rejected(self):
        for url in ("javascript:alert(1)", "http://example.org/", "https://user:pass@example.org/", "https://example.org:broken/"):
            data = source_payload()
            data["url"] = url
            self.assert_app_error("INVALID_URL", self.store.create_source, data)

    def test_law_metadata_required(self):
        data = source_payload()
        data["kind"] = "law"
        self.assert_app_error("INCOMPLETE_METADATA", self.store.create_source, data)

    def test_duplicate_locators_rejected(self):
        data = source_payload()
        data["segments"][1]["locator"] = "Mục 1"
        self.assert_app_error("DUPLICATE_LOCATOR", self.store.create_source, data)

    def test_empty_or_short_segments_rejected(self):
        for segments in ([], [{"title": "Đoạn", "locator": "1", "text": "ngắn"}]):
            data = source_payload()
            data["segments"] = segments
            with self.assertRaises(AppError):
                self.store.create_source(data)

    def test_search_hides_drafts_by_default(self):
        self.assertEqual([], self.store.search("trích dẫn phiên bản")["results"])
        self.assertTrue(self.store.search("trích dẫn phiên bản", reviewed_only=False)["results"])

    def test_search_vietnamese_accent_equivalence(self):
        self.reviewed()
        a = [r["id"] for r in self.store.search("trích dẫn phiên bản")["results"]]
        b = [r["id"] for r in self.store.search("trich dan phien ban")["results"]]
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_search_original_text_retains_accents(self):
        self.reviewed()
        result = self.store.search("hoc lieu phien ban")["results"][0]
        self.assertIn("học liệu", result["text"])

    def test_search_empty_stopwords_and_out_of_scope(self):
        self.reviewed()
        for query in ("", "và của là", "amoxicillin trẻ sơ sinh", "zzzxxyy987654"):
            self.assertEqual([], self.store.search(query)["results"])

    def test_search_source_filter(self):
        self.reviewed()
        self.assertTrue(self.store.search("học liệu phiên bản", source_id=self.sid)["results"])
        self.assertEqual([], self.store.search("học liệu phiên bản", source_id="missing")["results"])

    def test_search_limits_are_bounded(self):
        self.assert_app_error("INVALID_QUERY", self.store.search, "a" * 201)
        self.assert_app_error("INVALID_LIMIT", self.store.search, "học liệu", "", True, 51)

    def test_review_note_required(self):
        self.assert_app_error("INVALID_LENGTH", self.store.review_source, self.sid, {"review_note": "ok"})

    def test_draft_cannot_be_attached(self):
        g = self.store.get_source(self.sid)["segments"][0]
        self.assert_app_error("SOURCE_UNREVIEWED", self.store.attach_evidence, self.cid, {"segment_id": g["id"], "quote": g["text"]})

    def test_exact_quote_required(self):
        g = self.reviewed()
        self.assert_app_error("QUOTE_MISMATCH", self.store.attach_evidence, self.cid, {"segment_id": g["id"], "quote": "Một câu hoàn toàn không xuất hiện trong nguồn."})

    def test_whitespace_normalized_quote_accepted(self):
        g = self.reviewed()
        quote = "Khi   học liệu\n thay đổi phiên bản,"
        e = self.store.attach_evidence(self.cid, {"segment_id": g["id"], "quote": quote})["evidence"]
        self.assertEqual("Khi học liệu thay đổi phiên bản,", e["quote"])

    def test_empty_quote_uses_entire_segment(self):
        g = self.reviewed()
        e = self.store.attach_evidence(self.cid, {"segment_id": g["id"], "quote": ""})["evidence"]
        self.assertEqual(normalized_quote(g["text"]), e["quote"])

    def test_duplicate_evidence_rejected(self):
        e = self.attached()
        self.assert_app_error("DUPLICATE_EVIDENCE", self.store.attach_evidence, self.cid, {"segment_id": e["segment_id"], "quote": e["quote"]})

    def test_missing_evidence_severity_depends_on_claim_type(self):
        self.assertEqual("error", self.store.check_project(self.pid)["checks"][0]["status"])
        self.store.update_claim(self.cid, {"claim_type": "analysis"})
        self.assertEqual("warning", self.store.check_project(self.pid)["checks"][0]["status"])
        self.store.update_claim(self.cid, {"claim_type": "proposal"})
        self.assertEqual("pass", self.store.check_project(self.pid)["checks"][0]["status"])

    def test_valid_evidence_has_no_technical_errors(self):
        self.attached()
        result = self.store.check_project(self.pid)
        self.assertEqual(1, result["summary"]["pass"])
        self.assertEqual([], result["issues"])
        self.assertIn("không xác nhận", result["note"])

    def test_revision_preserves_old_evidence_and_marks_stale(self):
        e = self.attached()
        new = self.store.revise_source(self.sid, {"segments": source_payload()["segments"], "change_note": "Tạo phiên bản mới để kiểm tra tính kế thừa."})
        self.assertEqual(2, new["source"]["version"])
        self.assertEqual("draft", new["source"]["status"])
        saved = self.store.get_project(self.pid)["claims"][0]["evidence"][0]
        self.assertEqual(e["quote"], saved["quote"])
        self.assertEqual(1, saved["source_version"])
        codes = {x["code"] for x in self.store.check_project(self.pid)["issues"]}
        self.assertEqual({"SOURCE_CHANGED", "SOURCE_UNREVIEWED"}, codes)

    def test_review_new_version_does_not_silently_refresh_evidence(self):
        e = self.attached()
        self.store.revise_source(self.sid, {"segments": source_payload()["segments"], "change_note": "Đối chiếu lại với nguồn theo phiên bản mới."})
        self.store.review_source(self.sid, {"review_note": "Đã kiểm tra đầy đủ bản học liệu mới."})
        self.assertEqual(["SOURCE_CHANGED"], [x["code"] for x in self.store.check_project(self.pid)["issues"]])
        self.assert_app_error("SOURCE_CHANGED", self.store.attach_evidence, self.cid, {"segment_id": e["segment_id"]})

    def test_relink_new_version_resolves_staleness(self):
        old = self.attached()
        result = self.store.revise_source(self.sid, {"segments": source_payload()["segments"], "change_note": "Bổ sung phiên bản để kiểm thử liên kết lại."})
        self.store.review_source(self.sid, {"review_note": "Đã đối chiếu bản mới cho phép thực hành."})
        self.store.delete_evidence(old["id"])
        self.store.attach_evidence(self.cid, {"segment_id": result["segments"][0]["id"]})
        self.assertEqual([], self.store.check_project(self.pid)["issues"])

    def test_direct_segment_corruption_is_detected(self):
        e = self.attached()
        with self.store.write() as c:
            c.execute("UPDATE segments SET text='Nội dung đã bị thay đổi ngoài luồng ứng dụng.' WHERE id=?", (e["segment_id"],))
        codes = {x["code"] for x in self.store.check_project(self.pid)["issues"]}
        self.assertIn("SNAPSHOT_HASH_MISMATCH", codes)
        self.assert_app_error("SOURCE_INTEGRITY_ERROR", self.store.review_source, self.sid, {"review_note": "Thử đối chiếu trong tình trạng nguồn đã bị sửa."})

    def test_direct_metadata_corruption_is_detected(self):
        self.attached()
        with self.store.write() as c:
            c.execute("UPDATE sources SET issuer='Chủ thể bị thay ngoài ứng dụng' WHERE id=?", (self.sid,))
        self.assertIn("SNAPSHOT_HASH_MISMATCH", {x["code"] for x in self.store.check_project(self.pid)["issues"]})

    def test_evidence_quote_corruption_is_detected(self):
        e = self.attached()
        with self.store.write() as c:
            c.execute("UPDATE evidence SET quote='Nội dung giả không tồn tại trong nguồn đã lưu.' WHERE id=?", (e["id"],))
        codes = {x["code"] for x in self.store.check_project(self.pid)["issues"]}
        self.assertIn("SNAPSHOT_HASH_MISMATCH", codes)
        self.assertIn("QUOTE_MISMATCH", codes)

    def test_update_claim_preserves_evidence(self):
        self.attached()
        changed = self.store.update_claim(self.cid, {"text": "Luận điểm đã điều chỉnh cần được tác giả xem xét lại với dẫn chứng đang có."})["claim"]
        self.assertEqual(1, len(changed["evidence"]))

    def test_delete_claim_cascades_evidence(self):
        self.attached()
        self.store.delete_claim(self.cid)
        self.assertEqual([], self.store.get_project(self.pid)["claims"])
        with self.store.read() as c:
            self.assertEqual(0, c.execute("SELECT COUNT(*) FROM evidence").fetchone()[0])

    def test_failed_transaction_rolls_back_content_and_audit(self):
        before = self.store.audit()["verification"]["checked"]
        count = len(self.store.list_projects())
        with patch.object(self.store, "_audit", side_effect=RuntimeError("simulated storage failure")):
            with self.assertRaises(RuntimeError):
                self.store.create_project({"title": "Không được lưu khi nhật ký lỗi"})
        self.assertEqual(count, len(self.store.list_projects()))
        self.assertEqual(before, self.store.audit()["verification"]["checked"])

    def test_audit_detects_modified_event(self):
        self.assertTrue(self.store.audit()["verification"]["valid"])
        with self.store.write() as c:
            c.execute("UPDATE audit SET action='changed' WHERE id=1")
        result = self.store.audit()["verification"]
        self.assertFalse(result["valid"])
        self.assertEqual(1, result["first_invalid_id"])

    def test_parallel_writes_preserve_audit_chain(self):
        errors = []
        def create(i):
            try:
                self.store.create_project({"title": "Hồ sơ song song " + str(i)})
            except Exception as exc:
                errors.append(exc)
        threads = [threading.Thread(target=create, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], errors)
        self.assertEqual(13, len(self.store.list_projects()))
        self.assertTrue(self.store.audit()["verification"]["valid"])

    def test_read_transaction_keeps_one_snapshot_during_other_write(self):
        with self.store.read() as c:
            before = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            thread = threading.Thread(target=lambda: self.store.create_project({"title": "Hồ sơ tạo trong khi luồng khác đang đọc"}))
            thread.start()
            thread.join(timeout=5)
            self.assertFalse(thread.is_alive())
            inside = c.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
            self.assertEqual(before, inside)
        self.assertEqual(before + 1, len(self.store.list_projects()))

    def test_export_escapes_html_and_preserves_citation_metadata(self):
        self.attached()
        self.store.update_claim(self.cid, {"text": "Ví dụ nhập chuỗi <script>alert('x')</script> để kiểm tra an toàn hiển thị."})
        payload, mime, name = self.store.export_project(self.pid, "html")
        value = payload.decode()
        self.assertNotIn("<script>", value)
        self.assertIn("&lt;script&gt;", value)
        self.assertIn("Tài liệu tham khảo", value)
        self.assertIn("DEMO-TEST-01", value)
        self.assertIn("SHA-256", value)

    def test_json_and_markdown_exports_include_warnings(self):
        data = json.loads(self.store.export_project(self.pid, "json")[0])
        self.assertEqual("MISSING_EVIDENCE", data["validation"]["issues"][0]["code"])
        md = self.store.export_project(self.pid, "markdown")[0].decode()
        self.assertIn("MISSING_EVIDENCE", md)
        self.assertIn("không xác nhận", md)

    def test_empty_project_warning_survives_each_export_format(self):
        self.store.delete_claim(self.cid)
        data = json.loads(self.store.export_project(self.pid, "json")[0])
        self.assertEqual("EMPTY_PROJECT", data["validation"]["issues"][0]["code"])
        md = self.store.export_project(self.pid, "markdown")[0].decode()
        self.assertIn("EMPTY_PROJECT", md)
        self.assertIn("Hồ sơ chưa có luận điểm", md)
        html_export = self.store.export_project(self.pid, "html")[0].decode()
        self.assertIn("Hồ sơ chưa có luận điểm", html_export)

    def test_unsupported_export_format_rejected(self):
        self.assert_app_error("INVALID_FORMAT", self.store.export_project, self.pid, "exe")

    def test_backup_is_valid_and_can_open_as_separate_store(self):
        self.attached()
        payload, mime, name = self.store.backup()
        path = Path(self.tmp.name) / "backup.zip"
        path.write_bytes(payload)
        self.assertTrue(verify(path)["valid"])
        restore = Path(self.tmp.name) / "separate_restore"
        restore.mkdir()
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            (restore / "so_can_cu.sqlite3").write_bytes(z.read("so_can_cu.sqlite3"))
        reopened = Store(restore, seed_demo=False)
        self.assertEqual(self.store.get_project(self.pid), reopened.get_project(self.pid))
        self.assertEqual([], reopened.check_project(self.pid)["issues"])

    def test_backup_verifier_rejects_changed_database(self):
        payload, _, _ = self.store.backup()
        path = Path(self.tmp.name) / "bad.zip"
        with zipfile.ZipFile(io.BytesIO(payload)) as old, zipfile.ZipFile(path, "w") as new:
            for name in old.namelist():
                content = old.read(name)
                if name == "so_can_cu.sqlite3":
                    content += b"changed"
                new.writestr(name, content)
        with self.assertRaises(ValueError):
            verify(path)

    def test_seed_is_idempotent_across_restart(self):
        with tempfile.TemporaryDirectory() as t:
            first = Store(t)
            a = first.bootstrap()["stats"]
            second = Store(t)
            self.assertEqual(a, second.bootstrap()["stats"])
            self.assertEqual(5, a["sources"])

    def test_source_history_contains_all_versions(self):
        self.reviewed()
        self.store.revise_source(self.sid, {"segments": source_payload()["segments"], "change_note": "Bản thứ hai để kiểm tra lịch sử nguồn."})
        self.assertEqual([2, 1], [x["version"] for x in self.store.get_source(self.sid)["versions"]])

    def test_sql_control_characters_are_data(self):
        title = "Hồ sơ '); DROP TABLE sources; --"
        p = self.store.create_project({"title": title})["project"]
        self.assertEqual(title, p["title"])
        self.assertEqual(1, len(self.store.list_sources()))

    def test_unknown_entities_return_not_found(self):
        for fn in (self.store.get_source, self.store.get_project, self.store.delete_claim, self.store.delete_evidence):
            self.assert_app_error("NOT_FOUND", fn, "missing-id")


if __name__ == "__main__":
    unittest.main(verbosity=2)
