"""End-to-end API tests against a real HTTP server on an ephemeral port."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from tests.support import SAMPLE_CONTRACT, make_db
from bayyinah.api.app import App, BayyinahServer
from bayyinah.config import Settings
from bayyinah.retrieval.corpus import SqliteCorpus


def start_server(*, api_key=None, rate_limit=1000):
    tmp = Path(tempfile.mkdtemp())
    settings = Settings(db_path=tmp / "test.db", api_key=api_key, rate_limit_per_min=rate_limit)
    db = make_db()
    app = App(settings, db=db, corpus=SqliteCorpus(db))
    server = BayyinahServer(("127.0.0.1", 0), app)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def stop_server(server):
    server.shutdown()
    server.server_close()


def request(base, path, *, method="GET", body=None, headers=None, raw=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    hdrs = {"Content-Type": "application/json"} if body is not None else {}
    hdrs.update(headers or {})
    req = urllib.request.Request(base + path, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = resp.read()
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype:
                return resp.status, json.loads(payload.decode())
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        try:
            return exc.code, json.loads(payload.decode())
        except Exception:  # noqa: BLE001
            return exc.code, payload


class TestAnonymousServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = start_server()

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.server)

    def test_health(self):
        status, data = request(self.base, "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(data["chunks"], 8)
        self.assertTrue(data["synthetic_corpus"])
        self.assertFalse(data["auth_required"])

    def test_index_page(self):
        status, body = request(self.base, "/")
        self.assertEqual(status, 200)
        self.assertIn("dir=\"rtl\"", body.decode())

    def test_ask_returns_grounded_answer(self):
        status, data = request(self.base, "/api/ask", method="POST",
                               body={"question": "ما هي فترة التجربة القصوى؟"})
        self.assertEqual(status, 200)
        self.assertIn("53", {c["article_no"] for c in data["answer"]["citations"]})
        self.assertGreater(data["query_id"], 0)
        self.assertIn("markdown", data)

    def test_ask_rejects_short_question(self):
        status, data = request(self.base, "/api/ask", method="POST", body={"question": "hi"})
        self.assertEqual(status, 400)

    def test_ask_end_of_service_includes_calculation(self):
        status, data = request(
            self.base, "/api/ask", method="POST",
            body={"question": "كم مكافأة نهاية الخدمة إذا استقلت بعد 3 سنوات براتب 6000 ريال؟"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"]["calculations"][0]["result"], 3000.0)

    def test_contract_analysis(self):
        status, data = request(self.base, "/api/contracts", method="POST",
                               body={"text": SAMPLE_CONTRACT, "filename": "عقد.txt"})
        self.assertEqual(status, 200)
        self.assertEqual(data["report"]["counts"]["non_compliant"], 4)
        self.assertEqual(data["coverage"]["covered_by_rules"], 5)
        self.assertTrue(data["links"]["html"].startswith("/api/contracts/"))

    def test_contract_report_html(self):
        _, created = request(self.base, "/api/contracts", method="POST",
                             body={"text": SAMPLE_CONTRACT})
        status, body = request(self.base, created["links"]["html"])
        self.assertEqual(status, 200)
        self.assertIn("المادة 53", body.decode())

    def test_contract_upload_multipart(self):
        boundary = uuid.uuid4().hex
        payload = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="contract.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            f"{SAMPLE_CONTRACT}\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        status, data = request(
            self.base, "/api/contracts", method="POST", raw=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["filename"], "contract.txt")

    def test_contract_rejects_short_text(self):
        status, _ = request(self.base, "/api/contracts", method="POST", body={"text": "short"})
        self.assertEqual(status, 400)

    def test_feedback(self):
        _, created = request(self.base, "/api/ask", method="POST", body={"question": "كم يوم إجازة سنوية؟"})
        status, data = request(self.base, "/api/feedback", method="POST",
                               body={"target_type": "query", "target_id": created["query_id"], "useful": True})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])

    def test_queries_history(self):
        status, data = request(self.base, "/api/queries")
        self.assertEqual(status, 200)
        self.assertTrue(data["queries"])
        self.assertIn("question", data["queries"][0])

    def test_contracts_history(self):
        request(self.base, "/api/contracts", method="POST", body={"text": SAMPLE_CONTRACT})
        status, data = request(self.base, "/api/contracts")
        self.assertEqual(status, 200)
        self.assertTrue(data["contracts"])

    def test_stats(self):
        status, data = request(self.base, "/api/stats")
        self.assertEqual(status, 200)
        self.assertIn("chunks", data)
        self.assertIn("queries", data)

    def test_documents(self):
        status, data = request(self.base, "/api/documents")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["documents"]), 1)

    def test_unknown_route(self):
        status, _ = request(self.base, "/api/nope")
        self.assertEqual(status, 404)


class TestAuthenticatedServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server, cls.base = start_server(api_key="secret-key")

    @classmethod
    def tearDownClass(cls):
        stop_server(cls.server)

    def test_health_is_public(self):
        status, data = request(self.base, "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["auth_required"])

    def test_stats_requires_key(self):
        status, _ = request(self.base, "/api/stats")
        self.assertEqual(status, 401)

    def test_stats_with_key(self):
        status, data = request(self.base, "/api/stats", headers={"X-API-Key": "secret-key"})
        self.assertEqual(status, 200)
        self.assertIn("chunks", data)

    def test_ask_is_open_but_ingest_is_not(self):
        status, _ = request(self.base, "/api/ask", method="POST", body={"question": "كم يوم إجازة؟"})
        self.assertEqual(status, 200)
        status, _ = request(self.base, "/api/ingest", method="POST", body={"path": "corpora/raw"})
        self.assertEqual(status, 401)


class TestRateLimit(unittest.TestCase):
    def test_second_request_is_throttled(self):
        server, base = start_server(rate_limit=1)
        try:
            first, _ = request(base, "/api/ask", method="POST", body={"question": "كم يوم إجازة سنوية؟"})
            second, data = request(base, "/api/ask", method="POST", body={"question": "كم يوم إجازة سنوية؟"})
            self.assertEqual(first, 200)
            self.assertEqual(second, 429)
            self.assertIn("retry_after_s", data)
        finally:
            stop_server(server)


if __name__ == "__main__":
    unittest.main()
