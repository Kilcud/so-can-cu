#!/usr/bin/env python3
"""Start Sổ căn cứ on a loopback-only HTTP server. No external packages."""
from __future__ import annotations

import argparse
from intake_v2 import decode_upload, create_imported, fetch_public
from ai_v2 import SearchEngine
import hmac
import json
import re
import secrets
import sqlite3
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from store import AppError, Store, VERSION

ROOT = Path(__file__).resolve().parent
BODY_LIMIT = 256 * 1024
IMPORT_BODY_LIMIT = 12 * 1024 * 1024
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/index.html": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"), "/ui_v2.js": ("ui_v2.js", "text/javascript; charset=utf-8"), "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
STATIC["/fonts/nunito.ttf"] = ("fonts/nunito.ttf", "font/ttf")
ID = r"([A-Za-z0-9_-]{1,80})"


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, port=8765, data_dir=None, seed_path=None, seed_demo=True, quiet=False):
        self.store = Store(data_dir or ROOT / "local_data", seed_path=seed_path, seed_demo=seed_demo)
        self.csrf_token = secrets.token_urlsafe(32)
        self.search_engine = SearchEngine(self.store)
        self.quiet = quiet
        super().__init__(("127.0.0.1", port), Handler)
        actual_port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{actual_port}", f"localhost:{actual_port}"}
        self.allowed_origins = {"http://" + host for host in self.allowed_hosts}


class Handler(BaseHTTPRequestHandler):
    server_version = "SoCanCu/" + VERSION
    sys_version = ""
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        if not self.server.quiet:
            # Only method/status/path are logged by the default HTTP log. Do not
            # log request bodies, CSRF tokens, source text or evidence quotations.
            super().log_message(format, *args)

    def _headers(self, status, ctype, size, filename=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(size))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
        self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if filename:
            self.send_header("Content-Disposition", 'attachment; filename="' + filename + '"')
        self.end_headers()

    def _send(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self._headers(status, "application/json; charset=utf-8", len(payload))
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _bytes(self, payload, ctype, filename=None):
        self._headers(200, ctype, len(payload), filename)
        if self.command != "HEAD":
            self.wfile.write(payload)

    def _guard(self, mutation=False):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0].strip().lower() not in self.server.allowed_hosts:
            raise AppError("INVALID_HOST", "Máy chủ chỉ chấp nhận truy cập bằng địa chỉ cục bộ đã cấu hình.", 403)
        origins = self.headers.get_all("Origin", [])
        if len(origins) > 1 or (origins and origins[0] not in self.server.allowed_origins):
            raise AppError("INVALID_ORIGIN", "Nguồn yêu cầu không được phép truy cập ứng dụng cục bộ.", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise AppError("CROSS_SITE_REQUEST", "Yêu cầu từ trang web khác đã bị chặn.", 403)
        if mutation:
            supplied = self.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(supplied, self.server.csrf_token):
                raise AppError("CSRF_REJECTED", "Phiên thao tác không hợp lệ. Hãy tải lại ứng dụng rồi thử lại.", 403)

    def _body(self):
        if self.headers.get("Transfer-Encoding"):
            raise AppError("UNSUPPORTED_ENCODING", "Không chấp nhận yêu cầu truyền theo khối.", 400)
        raw_lengths = self.headers.get_all("Content-Length", [])
        if len(raw_lengths) != 1 or not re.fullmatch(r"[0-9]{1,10}", raw_lengths[0]):
            raise AppError("INVALID_LENGTH", "Yêu cầu cần có Content-Length hợp lệ.", 411)
        length = int(raw_lengths[0])
        if length > (IMPORT_BODY_LIMIT if urlsplit(self.path).path == "/api/import/file" else BODY_LIMIT):
            raise AppError("BODY_TOO_LARGE", "Dữ liệu gửi lên vượt giới hạn cho thao tác này.", 413)
        ctype = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if ctype != "application/json":
            raise AppError("UNSUPPORTED_CONTENT_TYPE", "Yêu cầu phải sử dụng application/json.", 415)
        try:
            body = self.rfile.read(length)
            if len(body) != length:
                raise AppError("INCOMPLETE_BODY", "Nội dung yêu cầu chưa được nhận đầy đủ.", 400)
            value = json.loads(body.decode("utf-8"))
            if not isinstance(value, dict):
                raise AppError("INVALID_JSON", "Nội dung JSON phải là một đối tượng.", 400)
            return value
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AppError("INVALID_JSON", "Nội dung yêu cầu không phải JSON UTF-8 hợp lệ.", 400)

    def _handle(self, fn):
        try:
            fn()
        except AppError as exc:
            self._send(exc.as_dict(), exc.status)
        except sqlite3.OperationalError:
            self._send({"error": {"code": "DATABASE_UNAVAILABLE", "message": "Không thể truy cập dữ liệu lúc này. Kiểm tra quyền thư mục hoặc thử lại sau."}}, 503)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            return
        except Exception as exc:
            if not self.server.quiet:
                print(f"Internal request error: {type(exc).__name__}", file=sys.stderr)
            self._send({"error": {"code": "INTERNAL_ERROR", "message": "Thao tác không hoàn thành. Dữ liệu của giao dịch lỗi đã được hoàn tác."}}, 500)

    def do_GET(self):
        self._handle(self._get)

    def do_HEAD(self):
        self._handle(self._get)

    def do_POST(self):
        self._handle(self._mutate)

    def do_PATCH(self):
        self._handle(self._mutate)

    def do_DELETE(self):
        self._handle(self._mutate)

    def do_OPTIONS(self):
        self._handle(lambda: (_ for _ in ()).throw(AppError("METHOD_NOT_ALLOWED", "Không hỗ trợ truy cập chéo nguồn.", 405)))

    def _get(self):
        self._guard()
        parsed = urlsplit(self.path)
        path, query = parsed.path, parse_qs(parsed.query, keep_blank_values=True)
        store = self.server.store
        if path == "/ui-font.css":
            # Local font resolution only. The optional font is downloaded by an
            # explicit setup command, never while a document is being used.
            sources = 'local("Nunito"), local("Nunito Regular")'
            if (ROOT / "static/fonts/nunito.ttf").is_file():
                sources += ', url("/fonts/nunito.ttf") format("truetype")'
            font_css = ('@font-face{font-family:"SCC Nunito";font-style:normal;'
                        'font-weight:200 1000;font-display:swap;src:' + sources + ';}')
            return self._bytes(font_css.encode("utf-8"), "text/css; charset=utf-8")
        if path in STATIC:
            name, ctype = STATIC[path]
            file = ROOT / "static" / name
            if not file.is_file():
                raise AppError("NOT_FOUND", "Tệp giao diện chưa có trong bộ cài.", 404)
            return self._bytes(file.read_bytes(), ctype)
        if path == "/api/health":
            return self._send({"ok": True, "version": VERSION})
        if path == "/api/bootstrap":
            value = store.bootstrap()
            value["csrf_token"] = self.server.csrf_token
            return self._send(value)
        if path == "/api/sources":
            return self._send({"sources": store.list_sources()})
        if path == "/api/projects":
            return self._send({"projects": store.list_projects()})
        if path == "/api/ai/status":
            return self._send({"embedding_model":"nomic-embed-text","generation_model":"qwen2.5:3b","provider":"Ollama cục bộ; không tự gửi dữ liệu lên Internet", "note":"Các mô hình cần cài và khởi chạy riêng."})
        if path == "/api/search":
            try:
                limit = int(query.get("limit", ["20"])[0])
            except ValueError:
                raise AppError("INVALID_LIMIT", "Giới hạn kết quả phải là số nguyên.", 400)
            reviewed = query.get("reviewed_only", ["true"])[0]
            if reviewed not in ("true", "false"):
                raise AppError("INVALID_FILTER", "Bộ lọc reviewed_only phải là true hoặc false.", 400)
            return self._send(store.search(query.get("q", [""])[0], query.get("source_id", [""])[0], reviewed == "true", limit))
        match = re.fullmatch(r"/api/sources/" + ID, path)
        if match:
            return self._send(store.get_source(match[1]))
        match = re.fullmatch(r"/api/projects/" + ID + r"(/check|/export)?", path)
        if match:
            pid, suffix = match.groups()
            if suffix == "/check":
                return self._send(store.check_project(pid))
            if suffix == "/export":
                return self._bytes(*store.export_project(pid, query.get("format", ["html"])[0]))
            return self._send(store.get_project(pid))
        if path == "/api/audit":
            return self._send(store.audit())
        if path == "/api/backup":
            return self._bytes(*store.backup())
        raise AppError("NOT_FOUND", "Đường dẫn không tồn tại.", 404)

    def _mutate(self):
        self._guard(mutation=True)
        path = urlsplit(self.path).path
        store = self.server.store
        data = {} if self.command == "DELETE" else self._body()
        if self.command == "POST":
            if path == "/api/import/file":
                filename,suffix,raw = decode_upload(data)
                result = create_imported(store, str(data.get('title') or filename), str(data.get('issuer') or 'Người sử dụng'), '',raw,suffix,filename)
                return self._send(result,201)
            if path == "/api/import/public":
                url=data.get('url','')
                suffix,raw=fetch_public(url)
                result=create_imported(store,str(data.get('title') or 'Tài liệu công khai'),str(data.get('issuer') or 'Nguồn công khai'),url,raw,suffix,url)
                return self._send(result,201)
            if path == "/api/search/semantic":
                reviewed_only = data.get('reviewed_only',True)
                limit = data.get('limit',8)
                if not isinstance(reviewed_only,bool) or not isinstance(limit,int) or not 1<=limit<=20:
                    raise AppError('INVALID_FILTER','Bộ lọc tìm kiếm không hợp lệ.',422)
                return self._send(self.server.search_engine.semantic(data.get('q',''),reviewed_only, limit))
            if path == "/api/rag/ask":
                return self._send(self.server.search_engine.answer(data.get('question',''),data.get('mode','semantic')))
            if path == "/api/sources":
                return self._send(store.create_source(data), 201)
            if path == "/api/projects":
                return self._send(store.create_project(data), 201)
            match = re.fullmatch(r"/api/sources/" + ID + r"/(review|revise)", path)
            if match:
                fn = store.review_source if match[2] == "review" else store.revise_source
                return self._send(fn(match[1], data))
            match = re.fullmatch(r"/api/projects/" + ID + r"/claims", path)
            if match:
                return self._send(store.create_claim(match[1], data), 201)
            match = re.fullmatch(r"/api/claims/" + ID + r"/evidence", path)
            if match:
                return self._send(store.attach_evidence(match[1], data), 201)
        if self.command == "PATCH":
            match = re.fullmatch(r"/api/projects/" + ID, path)
            if match:
                return self._send(store.update_project(match[1], data))
            match = re.fullmatch(r"/api/claims/" + ID, path)
            if match:
                return self._send(store.update_claim(match[1], data))
        if self.command == "DELETE":
            match = re.fullmatch(r"/api/claims/" + ID, path)
            if match:
                return self._send(store.delete_claim(match[1]))
            match = re.fullmatch(r"/api/evidence/" + ID, path)
            if match:
                return self._send(store.delete_evidence(match[1]))
        raise AppError("NOT_FOUND", "Không tìm thấy thao tác tương ứng.", 404)


def main():
    parser = argparse.ArgumentParser(description="Sổ căn cứ — tra cứu học liệu và kiểm tra căn cứ trích dẫn")
    parser.add_argument("--port", type=int, default=8765, help="Cổng cục bộ (mặc định 8765)")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "local_data", help="Thư mục dữ liệu; mỗi thư mục là một bộ hồ sơ riêng")
    parser.add_argument("--no-demo", action="store_true", help="Khởi tạo dữ liệu trống, không nạp hồ sơ mẫu")
    parser.add_argument("--quiet", action="store_true", help="Ẩn nhật ký truy cập HTTP")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Cổng phải từ 1 đến 65535.")
    try:
        server = LocalServer(args.port, args.data_dir, seed_demo=not args.no_demo, quiet=args.quiet)
    except OSError as exc:
        print(f"Không thể khởi động máy chủ: {exc}. Thử cổng khác bằng --port.", file=sys.stderr)
        return 1
    print(f"Sổ căn cứ {VERSION}: http://127.0.0.1:{server.server_address[1]}")
    print(f"Dữ liệu: {server.store.path}")
    print("Một người dùng trên máy cục bộ. Nhấn Ctrl+C để dừng.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng ứng dụng.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
