"""HTTP boundary and complete-workflow checks against the real local server."""
import http.client
import io
import json
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import LocalServer, BODY_LIMIT


class HttpContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="socancu_http_")
        cls.server = LocalServer(0, Path(cls.temp.name), quiet=True)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.token = cls.server.csrf_token

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.temp.cleanup()

    def call(self, method, path, value=None, headers=None, raw=None, token=True):
        h = {}
        if token:
            h["X-CSRF-Token"] = self.token
        body = raw
        if value is not None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            h["Content-Type"] = "application/json"
        h.update(headers or {})
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        c.request(method, path, body=body, headers=h)
        r = c.getresponse()
        out = r.read()
        content_type = r.getheader("Content-Type", "")
        status, response_headers = r.status, dict(r.getheaders())
        c.close()
        data = json.loads(out) if content_type.startswith("application/json") else out
        return status, data, response_headers

    def error(self, method, path, status, code, **kw):
        actual, data, _ = self.call(method, path, **kw)
        self.assertEqual(actual, status, data)
        self.assertEqual(data["error"]["code"], code)

    def test_H01_health_and_bootstrap(self):
        """Đọc phiên làm việc và kiểm tra số liệu xuất phát từ dữ liệu thật."""
        status, d, h = self.call("GET", "/api/health")
        self.assertEqual((status, d["ok"], d["version"]), (200, True, "2.0.0"))
        status, d, _ = self.call("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertEqual(d["csrf_token"], self.token)
        self.assertEqual(d["stats"]["sources"], len(d["sources"]))
        self.assertEqual(h["Cache-Control"], "no-store")

    def test_H02_localhost_host_is_allowed(self):
        """Địa chỉ localhost đúng cổng vẫn truy cập được máy chủ cục bộ."""
        self.assertEqual(self.call("GET", "/api/health", headers={"Host": f"localhost:{self.port}"})[0], 200)

    def test_H03_foreign_host_is_rejected(self):
        """Từ chối Host bên ngoài ngay cả khi kết nối tới loopback."""
        self.error("GET", "/api/bootstrap", 403, "INVALID_HOST", headers={"Host": "attacker.invalid"})

    def test_H04_wrong_local_port_is_rejected(self):
        """Host dùng sai cổng không được xem là địa chỉ tin cậy."""
        self.error("GET", "/api/health", 403, "INVALID_HOST", headers={"Host": "127.0.0.1:1"})

    def test_H05_foreign_origin_read_is_rejected(self):
        """Không cấp dữ liệu phiên cho yêu cầu có Origin bên ngoài."""
        self.error("GET", "/api/bootstrap", 403, "INVALID_ORIGIN", headers={"Origin": "https://attacker.invalid"})

    def test_H06_cross_site_metadata_is_rejected(self):
        """Dấu hiệu truy cập từ trang khác bị từ chối trước xử lý dữ liệu."""
        self.error("GET", "/api/sources", 403, "CROSS_SITE_REQUEST", headers={"Sec-Fetch-Site": "cross-site"})

    def test_H07_missing_csrf_token_is_rejected(self):
        """Yêu cầu ghi thiếu mã phiên không tạo hồ sơ."""
        self.error("POST", "/api/projects", 403, "CSRF_REJECTED", value={"title": "Hồ sơ không được tạo"}, token=False)

    def test_H08_wrong_csrf_token_is_rejected(self):
        """Yêu cầu ghi có mã phiên sai không được chấp nhận."""
        self.error("POST", "/api/projects", 403, "CSRF_REJECTED", value={"title": "Hồ sơ không được tạo"}, headers={"X-CSRF-Token": "invalid"})

    def test_H09_foreign_origin_mutation_is_rejected(self):
        """Origin sai vẫn bị chặn khi biết mã phiên thử nghiệm."""
        self.error("POST", "/api/projects", 403, "INVALID_ORIGIN", value={"title": "Hồ sơ không được tạo"}, headers={"Origin": "https://attacker.invalid"})

    def test_H10_json_content_type_required(self):
        """Không diễn giải một biểu mẫu hoặc văn bản thường thành lệnh ghi JSON."""
        self.error("POST", "/api/projects", 415, "UNSUPPORTED_CONTENT_TYPE", raw=b'{"title":"test"}', headers={"Content-Type": "text/plain"})

    def test_H11_invalid_json_rejected(self):
        """JSON sai cú pháp trả lỗi rõ ràng thay vì lỗi máy chủ."""
        self.error("POST", "/api/projects", 400, "INVALID_JSON", raw=b'{broken', headers={"Content-Type": "application/json"})

    def test_H12_invalid_utf8_rejected(self):
        """Byte không phải UTF-8 không được lưu thành văn bản bị hỏng."""
        self.error("POST", "/api/projects", 400, "INVALID_JSON", raw=b'{"title":"\xff"}', headers={"Content-Type": "application/json"})

    def test_H13_json_array_rejected(self):
        """Hình dạng dữ liệu đầu vào phải là một đối tượng có trường xác định."""
        self.error("POST", "/api/projects", 400, "INVALID_JSON", raw=b'[]', headers={"Content-Type": "application/json"})

    def test_H14_request_size_is_bounded(self):
        """Giới hạn kích thước được kiểm tra trước khi đọc toàn bộ nội dung."""
        self.error("POST", "/api/projects", 413, "BODY_TOO_LARGE", raw=b"x" * (BODY_LIMIT + 1), headers={"Content-Type": "application/json"})

    def test_H15_static_whitelist_blocks_traversal_and_database(self):
        """Chỉ tài sản giao diện được công bố; đường dẫn dữ liệu không được phục vụ."""
        for path in ("/../store.py", "/%2e%2e/store.py", "/local_data/socancu.sqlite3", "/data/source_seed.json"):
            with self.subTest(path=path):
                self.error("GET", path, 404, "NOT_FOUND")

    def test_H16_static_security_headers(self):
        """Tệp giao diện có chính sách nguồn và loại nội dung phù hợp."""
        for path in ("/", "/app.js", "/styles.css"):
            with self.subTest(path=path):
                status, body, headers = self.call("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
                self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
                self.assertEqual(headers["X-Frame-Options"], "DENY")

    def test_H17_cross_origin_preflight_is_not_enabled(self):
        """Ứng dụng không bật CORS cho trang bên ngoài gửi lệnh."""
        status, data, headers = self.call("OPTIONS", "/api/projects", headers={"Origin": "https://attacker.invalid"})
        self.assertEqual(status, 405)
        self.assertNotIn("Access-Control-Allow-Origin", headers)

    def test_H18_invalid_search_parameters(self):
        """Giới hạn và bộ lọc tìm kiếm sai được báo tại giao diện API."""
        self.error("GET", "/api/search?q=test&limit=abc", 400, "INVALID_LIMIT")
        self.error("GET", "/api/search?q=test&reviewed_only=maybe", 400, "INVALID_FILTER")

    def test_H19_complete_dossier_workflow(self):
        """Tạo hồ sơ, gắn nguồn, đổi phiên bản và đọc lại căn cứ cũ qua HTTP."""
        status, p, _ = self.call("POST", "/api/projects", value={"title": "Thử nghiệm toàn bộ quy trình HTTP", "description": "Dữ liệu mô phỏng của ca H19."})
        self.assertEqual(status, 201, p)
        pid = p["project"]["id"]
        status, c, _ = self.call("POST", f"/api/projects/{pid}/claims", value={"text": "Hồ sơ cần ghi rõ vị trí đoạn được dẫn để có thể kiểm tra lại.", "claim_type": "factual"})
        self.assertEqual(status, 201, c)
        cid = c["claim"]["id"]
        status, check, _ = self.call("GET", f"/api/projects/{pid}/check")
        self.assertTrue(any(x["code"] == "MISSING_EVIDENCE" for x in check["issues"]))
        source = {"title": "Học liệu HTTP H19", "issuer": "Tổ kiểm thử mô phỏng", "document_number": "TEST-H19", "published_date": "2026-10-26", "url": "", "kind": "learning_note", "text_kind": "original", "segments": [{"title": "Vị trí đoạn dẫn", "locator": "Mục 1", "text": "Hồ sơ cần ghi rõ vị trí đoạn được dẫn để người đọc có thể mở đúng phần tài liệu và kiểm tra lại nội dung."}]}
        status, s, _ = self.call("POST", "/api/sources", value=source)
        self.assertEqual(status, 201, s)
        sid, segid = s["source"]["id"], s["segments"][0]["id"]
        self.assertEqual(s["source"]["status"], "draft")
        status, _, _ = self.call("POST", f"/api/sources/{sid}/review", value={"review_note": "Đã kiểm tra học liệu mô phỏng trong ca H19."})
        self.assertEqual(status, 200)
        status, e, _ = self.call("POST", f"/api/claims/{cid}/evidence", value={"segment_id": segid, "quote": "", "note": "Dùng để kiểm tra luồng giao tiếp HTTP."})
        self.assertEqual(status, 201, e)
        pinned = e["evidence"]["source_version"]
        _, check, _ = self.call("GET", f"/api/projects/{pid}/check")
        self.assertEqual(check["summary"]["error"], 0)
        changed = [{"title": "Vị trí đoạn dẫn", "locator": "Mục 1", "text": source["segments"][0]["text"] + " Phiên bản mới bổ sung yêu cầu ghi ngày đối chiếu."}]
        status, s2, _ = self.call("POST", f"/api/sources/{sid}/revise", value={"segments": changed, "change_note": "Bổ sung yêu cầu ngày đối chiếu trong ca H19."})
        self.assertEqual(status, 200, s2)
        _, check, _ = self.call("GET", f"/api/projects/{pid}/check")
        self.assertTrue(any(x["code"] == "SOURCE_CHANGED" for x in check["issues"]))
        _, dossier, _ = self.call("GET", f"/api/projects/{pid}")
        self.assertEqual(dossier["claims"][0]["evidence"][0]["source_version"], pinned)
        for fmt in ("html", "markdown", "json"):
            status, exported, headers = self.call("GET", f"/api/projects/{pid}/export?format={fmt}")
            self.assertEqual(status, 200)
            self.assertIn("attachment", headers["Content-Disposition"])
            text = json.dumps(exported, ensure_ascii=False) if isinstance(exported, dict) else exported.decode("utf-8")
            self.assertIn("SOURCE_CHANGED", text)

    def test_H20_backup_download_and_audit(self):
        """Tải bản sao ZIP có thể mở và nhật ký còn nhất quán sau giao dịch."""
        status, payload, headers = self.call("GET", "/api/backup")
        self.assertEqual(status, 200)
        self.assertIn("application/zip", headers["Content-Type"])
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            self.assertIsNone(z.testzip())
            self.assertTrue(any(x.endswith(".json") for x in z.namelist()))
            self.assertTrue(any(x.endswith((".db", ".sqlite3", ".sqlite")) for x in z.namelist()))
        status, d, _ = self.call("GET", "/api/audit")
        self.assertEqual(status, 200)
        self.assertTrue(d["verification"]["valid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
