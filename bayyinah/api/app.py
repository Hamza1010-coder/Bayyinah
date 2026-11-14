"""HTTP API. Stdlib only, threaded, with auth, rate limiting and audit.

Routes
------
GET  /                              single-page app
GET  /api/health                    liveness + corpus summary
GET  /api/stats                     usage stats (requires key when configured)
GET  /api/documents                 ingested corpus documents
POST /api/ask                       {"question": "..."} -> cited answer
GET  /api/queries?limit=50          recent questions (audit trail)
POST /api/feedback                  {"target_type","target_id","useful","comment"}
POST /api/contracts                 {"text": "..."} or multipart file upload
GET  /api/contracts                 recent analyses
GET  /api/contracts/{id}            one analysis
GET  /api/contracts/{id}/report.html
GET  /api/contracts/{id}/report.docx
"""

from __future__ import annotations

import base64
import binascii
import datetime
import io
import json
import logging
import re
import uuid
import traceback
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..config import Settings, ensure_dirs
from ..contracts.analyzer import ContractAnalyzer
from ..contracts.report import to_docx, to_html
from ..db import Database
from ..generation.llm import get_default_llm
from ..generation.render import render_markdown
from ..ingest.loaders import LoaderError, load_bytes
from ..ingest.pipeline import ingest_directory, ingest_document
from ..retrieval.corpus import SqliteCorpus
from ..security import RateLimiter, is_authorized
from ..services import AnswerService, ContractService, stats

log = logging.getLogger("bayyinah.api")

STATIC_DIR = Path(__file__).resolve().parent / "static"
CONTRACT_PATH = re.compile(r"^/api/contracts/([0-9a-f\-]{8,})/report\.(html|docx)$")


class App:
    def __init__(self, settings: Settings, db: Database | None = None, corpus=None):
        self.settings = settings
        ensure_dirs(settings)
        self.db = db or Database(settings.db_path)
        self.corpus = corpus or SqliteCorpus(self.db)
        self.llm = get_default_llm()
        self.answer_service = AnswerService(self.corpus, settings, llm=self.llm, db=self.db)
        self.contract_service = ContractService(
            self.corpus, self.db, ContractAnalyzer(self.corpus, llm=self.llm)
        )
        self.limiter = RateLimiter(settings.rate_limit_per_min)
        self.started_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")

    def refresh_corpus(self) -> None:
        self.corpus.reload()
        self.answer_service.pipeline.store = self.corpus

    def ingest_upload(self, data: bytes, filename: str) -> dict:
        """Ingest an uploaded corpus file.

        Written under the app's own work directory (not the OS temp dir) so the
        file stays inside the deployment boundary and is deleted immediately.
        """
        suffix = Path(filename).suffix.lower() or ".txt"
        work = self.settings.db_path.parent / "uploads"
        work.mkdir(parents=True, exist_ok=True)
        tmp = work / f"upload-{uuid.uuid4().hex[:12]}{suffix}"
        tmp.write_bytes(data)
        try:
            result = ingest_document(
                self.db, tmp,
                title=Path(filename).stem,
                doc_id=Path(filename).stem.lower().replace(" ", "_"),
                actor="upload",
            )
            result.filename = filename
            self.refresh_corpus()
            return result.to_dict()
        finally:
            tmp.unlink(missing_ok=True)

    def ingest_path(self, path: str | Path) -> list[dict]:
        p = Path(path)
        results = (
            ingest_directory(self.db, p) if p.is_dir() else [ingest_document(self.db, p)]
        )
        self.refresh_corpus()
        return [r.to_dict() for r in results]


# --------------------------------------------------------------------------
# multipart parsing (minimal, correct enough for one file field)
# --------------------------------------------------------------------------
def parse_multipart(body: bytes, content_type: str) -> dict[str, dict]:
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    fields: dict[str, dict] = {}
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        fields[name] = {"filename": part.get_filename(), "data": payload}
    return fields


class Handler(BaseHTTPRequestHandler):
    server_version = "Bayyinah/1.0"
    protocol_version = "HTTP/1.1"

    # -- infrastructure ---------------------------------------------------
    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        log.info("%s - %s", self.address_string(), fmt % args)

    def handle_one_request(self) -> None:
        """Swallow connection resets.

        Browsers routinely drop keep-alive sockets on navigation. The stdlib
        logs a full traceback for that, which looks like a crash in a demo
        terminal and hides real errors.
        """
        try:
            super().handle_one_request()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            self.close_connection = True

    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200, extra: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, message: str, **extra) -> None:
        self._json({"error": message, **extra}, status)

    def _body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        if length > self.app.settings.max_upload_bytes:
            raise ValueError(f"payload too large (limit {self.app.settings.max_upload_bytes} bytes)")
        return self.rfile.read(length) if length else b""

    def _json_body(self) -> dict:
        raw = self._body()
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid JSON body") from exc

    def _authorized(self) -> bool:
        key = self.headers.get("X-API-Key") or self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        return is_authorized(key, self.app.settings.api_key)

    def _rate_ok(self) -> bool:
        actor = self.headers.get("X-API-Key") or self.client_address[0]
        allowed, retry = self.app.limiter.check(actor)
        if not allowed:
            self._error(429, "rate limit exceeded", retry_after_s=retry)
        return allowed

    def _require_auth(self) -> bool:
        if not self._authorized():
            self._error(401, "missing or invalid API key")
            return False
        return True

    # -- GET ---------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        try:
            if path in ("/", "/index.html"):
                return self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                return self._file(STATIC_DIR / path.removeprefix("/static/"))
            if path == "/api/health":
                return self._json(
                    {
                        "status": "ok",
                        "chunks": len(self.app.corpus),
                        "documents": len(self.app.db.documents()),
                        "synthetic_corpus": any(c.synthetic for c in self.app.corpus.chunks),
                        "auth_required": self.app.settings.auth_enabled,
                        "model": self.app.llm.name,
                        "started_at": self.app.started_at,
                    }
                )
            if path == "/api/documents":
                return self._json({"documents": [dict(r) for r in self.app.db.documents()]})
            if path == "/api/queries":
                return self._json({"queries": _queries_json(self.app, 50)})
            if path == "/api/stats":
                if not self._require_auth():
                    return
                return self._json(stats(self.app.db))
            if path == "/api/contracts":
                return self._json({"contracts": _contracts_json(self.app, 50)})

            match = CONTRACT_PATH.match(path)
            if match:
                return self._contract_report(match.group(1), match.group(2))

            return self._error(404, "not found")
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            log.error("GET %s failed: %s\n%s", path, exc, traceback.format_exc())
            return self._error(500, "internal error")

    def _contract_report(self, contract_id: str, fmt: str) -> None:
        payload = self.app.contract_service.get(contract_id)
        if payload is None:
            return self._error(404, "contract not found")
        report = _rebuild_report(payload["report"])
        if fmt == "html":
            return self._send(200, to_html(report).encode("utf-8"), "text/html; charset=utf-8")
        buffer = io.BytesIO()
        try:
            to_docx(report, buffer)
        except RuntimeError as exc:
            return self._error(501, str(exc))
        return self._send(
            200,
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            {"Content-Disposition": f'attachment; filename="bayyinah-{contract_id[:8]}.docx"'},
        )

    def _file(self, path: Path, content_type: str | None = None) -> None:
        if not path.is_file():
            return self._error(404, "not found")
        ctype = content_type or _guess_type(path)
        self._send(200, path.read_bytes(), ctype, {"Cache-Control": "no-cache"})

    # -- POST --------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0]
        if not self._rate_ok():
            return
        try:
            if path == "/api/ask":
                return self._ask()
            if path == "/api/contracts":
                return self._contract()
            if path == "/api/feedback":
                return self._feedback()
            if path == "/api/ingest":
                return self._ingest()
            return self._error(404, "not found")
        except ValueError as exc:
            return self._error(400, str(exc))
        except BrokenPipeError:
            return
        except Exception as exc:  # noqa: BLE001
            log.error("POST %s failed: %s\n%s", path, exc, traceback.format_exc())
            return self._error(500, "internal error")

    def _ask(self) -> None:
        payload = self._json_body()
        question = str(payload.get("question") or "").strip()
        if len(question) < 3:
            return self._error(400, "question is required (min 3 chars)")
        if len(question) > 1000:
            return self._error(400, "question too long (max 1000 chars)")
        result = self.app.answer_service.ask(question)
        return self._json(
            {
                **result.to_dict(),
                "markdown": render_markdown(result.answer),
                "synthetic_corpus": any(c.synthetic for c in self.app.corpus.chunks),
            }
        )

    def _contract(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        filename = "contract.txt"
        text = ""
        warnings: list[str] = []

        if content_type.startswith("multipart/form-data"):
            fields = parse_multipart(self._body(), content_type)
            file_field = fields.get("file")
            if file_field and file_field["filename"]:
                filename = file_field["filename"]
                try:
                    loaded = load_bytes(file_field["data"], filename)
                except LoaderError as exc:
                    return self._error(415, str(exc))
                text, warnings = loaded.text, list(loaded.warnings)
            elif "text" in fields:
                text = fields["text"]["data"].decode("utf-8", errors="replace")
            else:
                return self._error(400, "no file or text part in upload")
        else:
            payload = self._json_body()
            filename = str(payload.get("filename") or filename)
            text = str(payload.get("text") or "")
            if not text and payload.get("content_base64"):
                try:
                    raw = base64.b64decode(str(payload["content_base64"]), validate=True)
                except (binascii.Error, ValueError):
                    return self._error(400, "content_base64 is not valid base64")
                try:
                    loaded = load_bytes(raw, filename)
                except LoaderError as exc:
                    return self._error(415, str(exc))
                text, warnings = loaded.text, list(loaded.warnings)

        if len(text.strip()) < 40:
            return self._error(400, "contract text is required (min 40 chars)")

        contract_id, result = self.app.contract_service.analyze(text, filename=filename)
        if warnings:
            result.report.notes.extend(warnings)
        return self._json(
            {
                "contract_id": contract_id,
                "filename": filename,
                **result.to_dict(),
                "links": {
                    "html": f"/api/contracts/{contract_id}/report.html",
                    "docx": f"/api/contracts/{contract_id}/report.docx",
                },
            }
        )

    def _feedback(self) -> None:
        payload = self._json_body()
        target_type = str(payload.get("target_type") or "query")
        target_id = str(payload.get("target_id") or "")
        if not target_id:
            return self._error(400, "target_id is required")
        useful = bool(payload.get("useful"))
        self.app.db.add_feedback(target_type, target_id, useful, str(payload.get("comment") or ""))
        return self._json({"ok": True})

    def _ingest(self) -> None:
        if not self._require_auth():
            return
        payload = self._json_body()
        path = payload.get("path")
        if not path:
            return self._error(400, "path is required")
        results = self.app.ingest_path(path)
        return self._json({"results": results, "chunks": len(self.app.corpus)})


def _guess_type(path: Path) -> str:
    return {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }.get(path.suffix.lower(), "application/octet-stream")


def _queries_json(app: App, limit: int) -> list[dict]:
    out = []
    for row in app.db.recent_queries(limit):
        out.append(
            {
                "id": row["id"],
                "ts": row["ts"],
                "question": row["question"],
                "refusal_reason": row["refusal_reason"],
                "confidence": row["confidence"],
                "latency_ms": row["latency_ms"],
                "cost_usd": row["cost_usd"],
                "n_citations": row["n_citations"],
                "verification_ok": bool(row["verification_ok"]),
            }
        )
    return out


def _contracts_json(app: App, limit: int) -> list[dict]:
    return [
        {
            "id": row["id"],
            "ts": row["ts"],
            "filename": row["filename"],
            "counts": json.loads(row["counts_json"]),
        }
        for row in app.db.contracts(limit)
    ]


def _rebuild_report(data: dict):
    from ..schemas import Citation, Finding, XRayReport

    report = XRayReport(
        document_id=data.get("document_id", ""),
        filename=data.get("filename", ""),
        notes=list(data.get("notes") or []),
        redaction=dict(data.get("redaction") or {}),
    )
    for item in data.get("findings") or []:
        cit = item.get("citation")
        report.findings.append(
            Finding(
                clause_id=item.get("clause_id", ""),
                clause_text=item.get("clause_text", ""),
                verdict=item.get("verdict", "not_covered"),
                severity=item.get("severity", "low"),
                rationale=item.get("rationale", ""),
                suggested_redline=item.get("suggested_redline", ""),
                citation=Citation(**cit) if cit else None,
                confidence=float(item.get("confidence") or 0.0),
            )
        )
    return report


class BayyinahServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, app: App):
        super().__init__(address, Handler)
        self.app = app
