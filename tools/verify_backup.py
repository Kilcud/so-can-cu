#!/usr/bin/env python3
"""Verify a Sổ căn cứ backup without extracting it into the working data dir."""
import argparse
import hashlib
import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path


def verify(path):
    with zipfile.ZipFile(path) as z:
        expected_names = {"manifest.json", "so_can_cu.sqlite3", "README.txt"}
        names = z.namelist()
        if len(names) != len(expected_names) or set(names) != expected_names:
            raise ValueError("Bản sao có thành phần không đúng định dạng hoặc tên bị trùng.")
        if sum(i.file_size for i in z.infolist()) > 100 * 1024 * 1024:
            raise ValueError("Kích thước giải nén vượt giới hạn kiểm tra 100 MiB.")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("schema_version") != 1:
            raise ValueError("Phiên bản bản kê không được hỗ trợ.")
        if set(manifest.get("files", {})) != {"so_can_cu.sqlite3", "README.txt"}:
            raise ValueError("Danh mục tệp trong bản kê không hợp lệ.")
        for name, info in manifest["files"].items():
            data = z.read(name)
            if len(data) != info["size"] or hashlib.sha256(data).hexdigest() != info["sha256"]:
                raise ValueError("Mã kiểm tra hoặc kích thước không khớp: " + name)
        database = z.read("so_can_cu.sqlite3")
    with tempfile.TemporaryDirectory(prefix="so_can_cu_verify_") as temp:
        target = Path(temp) / "snapshot.sqlite3"
        target.write_bytes(database)
        c = sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)
        try:
            if c.execute("PRAGMA quick_check").fetchone()[0] != "ok" or c.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Cơ sở dữ liệu không nhất quán.")
            schema = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if not schema or schema[0] != "1":
                raise ValueError("Phiên bản cơ sở dữ liệu không đúng.")
            audit = c.execute("SELECT created_at,action,entity_id,details_json,previous_hash,event_hash FROM audit ORDER BY id").fetchall()
            previous = "0" * 64
            for timestamp, action, entity, details, prior, actual in audit:
                value = {"created_at": timestamp, "action": action, "entity_id": entity, "details": json.loads(details), "previous_hash": prior}
                encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                if prior != previous or hashlib.sha256(encoded).hexdigest() != actual:
                    raise ValueError("Chuỗi nhật ký có bản ghi không nhất quán.")
                previous = actual
            cp = manifest.get("audit_checkpoint", {})
            if cp.get("events") != len(audit) or cp.get("last_hash") != previous:
                raise ValueError("Mốc nhật ký không khớp bản kê.")
        finally:
            c.close()
    return {"valid": True, "files_checked": 2, "audit_events": len(audit), "audit_last_hash": previous, "note": "Kết quả xác nhận tính nhất quán với bản kê; bản kê không có chữ ký số."}


def main():
    p = argparse.ArgumentParser(description="Kiểm tra bản sao lưu Sổ căn cứ")
    p.add_argument("backup", type=Path)
    args = p.parse_args()
    try:
        print(json.dumps(verify(args.backup), ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile, sqlite3.Error) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
