#!/usr/bin/env python3
"""Run reproducible tests and corpus-scoped retrieval measurements.

This writes measured results. It does not estimate human time savings or
institutional deployment effectiveness.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import io
import json
import platform
from pathlib import Path
import statistics
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from store import Store


def case_map():
    mapping = {}
    tree = ast.parse((ROOT / "tests/test_store.py").read_text())
    names = [node.name for cl in tree.body if isinstance(cl, ast.ClassDef) for node in cl.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
    for i, name in enumerate(names, 1):
        mapping[name] = f"S{i:02}"
    return mapping


class EvidenceResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.records = []
        self.started = {}
        self.codes = case_map()

    def startTest(self, test):
        self.started[test.id()] = time.perf_counter()
        super().startTest(test)

    def record(self, test, status, detail=""):
        name = test.id().split(".")[-1]
        code = name.split("_")[1] if name.startswith("test_H") else self.codes.get(name, name)
        self.records.append({"id": code, "automated_test": name, "full_test_id": test.id(), "description": test.shortDescription() or name, "status": status, "duration_ms": round((time.perf_counter() - self.started[test.id()]) * 1000, 3), "detail": detail})

    def addSuccess(self, test):
        super().addSuccess(test)
        self.record(test, "passed")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        self.record(test, "error", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.record(test, "skipped", reason)


def fingerprint():
    files = [ROOT / "app.py", ROOT / "store.py"] + sorted((ROOT / "static").glob("*")) + sorted((ROOT / "tests").glob("test_*.py")) + sorted((ROOT / "data").glob("*.json"))
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()}


def retrieval(store, fixture):
    dataset = json.loads(fixture.read_text())
    records = []
    for q in dataset["queries"]:
        response = store.search(q["query"], limit=20)
        found = [r["id"] for r in response["results"]]
        expected = q["expected_segment_ids"]
        ranks = [found.index(e) + 1 for e in expected if e in found]
        best = min(ranks) if ranks else None
        records.append({**q, "returned_ids": found, "best_expected_rank": best, "hit_at_5": bool(best and best <= 5) if expected else None, "empty_when_expected": not found if not expected else None})
    positive = [r for r in records if r["expected_segment_ids"]]
    negative = [r for r in records if not r["expected_segment_ids"]]
    return {"file": str(fixture.relative_to(ROOT)), "records": records, "summary": {"queries": len(records), "positive_queries": len(positive), "hit_at_5_count": sum(r["hit_at_5"] for r in positive), "hit_at_5_rate": sum(r["hit_at_5"] for r in positive) / len(positive) if positive else None, "mrr_at_5": sum(1 / r["best_expected_rank"] if r["hit_at_5"] else 0 for r in positive) / len(positive) if positive else None, "no_match_queries": len(negative), "correct_empty_count": sum(r["empty_when_expected"] for r in negative)}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "evidence")
    parser.add_argument("--repeat", type=int, default=20)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
    runner = unittest.TextTestRunner(stream=log, verbosity=2, resultclass=EvidenceResult)
    start = time.perf_counter()
    result = runner.run(suite)
    elapsed = time.perf_counter() - start
    tests = {"measured_at_utc": datetime.now(timezone.utc).isoformat(), "environment": {"python": platform.python_version(), "platform": platform.system(), "machine": platform.machine()}, "total": result.testsRun, "passed": len([r for r in result.records if r["status"] == "passed"]), "failures": len(result.failures), "errors": len(result.errors), "skipped": len(result.skipped), "duration_seconds": round(elapsed, 4), "cases": result.records, "artifact_sha256": fingerprint()}
    (args.out / "test_results.json").write_text(json.dumps(tests, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "test_results.txt").write_text(log.getvalue(), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="socancu_measure_") as temporary:
        store = Store(Path(temporary), seed_demo=True)
        development = retrieval(store, ROOT / "data/search_fixtures.json")
        validation = retrieval(store, ROOT / "data/search_holdout.json")
        queries = json.loads((ROOT / "data/search_fixtures.json").read_text())["queries"]
        for q in queries:
            store.search(q["query"], limit=20)
        latencies = []
        for _ in range(args.repeat):
            for q in queries:
                tick = time.perf_counter()
                store.search(q["query"], limit=20)
                latencies.append((time.perf_counter() - tick) * 1000)
        ordered = sorted(latencies)
        performance = {"method": "Wall-clock Store.search with SQLite I/O, one warm-up pass, serial requests, fixed24segmentseed; excludes HTTP/browser/network/human work.", "samples": len(latencies), "repetitions_per_query": args.repeat, "median_ms": statistics.median(latencies), "p95_ms": ordered[max(0, int(.95 * len(ordered)) - 1)], "min_ms": min(latencies), "max_ms": max(latencies), "raw_ms": latencies}
    retrieval_report = {"measured_at_utc": tests["measured_at_utc"], "environment": tests["environment"], "development": development, "supplementary": validation, "performance": performance, "limits": ["Development queries were used to adjust retrieval; their result is a regression result.", "Supplementary queries were defined before this measurement and not used to tune the algorithm.", "A24segment corpus cannot establish general retrieval quality.", "No human usability experiment or Academy deployment was conducted."]}
    (args.out / "retrieval_results.json").write_text(json.dumps(retrieval_report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tests": {k: tests[k] for k in ("total", "passed", "failures", "errors", "duration_seconds")}, "development": development["summary"], "supplementary": validation["summary"], "performance": {k: v for k, v in performance.items() if k != "raw_ms"}}, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
