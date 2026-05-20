from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from cctv_query.engine import CCTVQueryEngine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CSV = PROJECT_ROOT / "cctv_vehicle_log_routed.csv"
STATIC_DIR = PROJECT_ROOT / "web_static"


def handle_query_payload(engine: CCTVQueryEngine, payload: dict) -> dict:
    question = str(payload.get("question", "")).strip()
    if not question:
        raise ValueError("Question is required.")
    return engine.ask(question).to_dict()


class CCTVWebServer(ThreadingHTTPServer):
    def __init__(self, server_address, handler_class, csv_path: Path):
        super().__init__(server_address, handler_class)
        self.csv_path = csv_path
        self.engine = CCTVQueryEngine.from_csv(csv_path)


class CCTVRequestHandler(BaseHTTPRequestHandler):
    server: CCTVWebServer
    server_version = "CCTVQueryWeb/0.1"

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_file(STATIC_DIR / "index.html")
            return
        if path == "/api/health":
            self._send_json({"ok": True, "csv": str(self.server.csv_path)})
            return
        if path.startswith("/static/"):
            self._send_static(path.removeprefix("/static/"))
            return
        self._send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/query":
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return

        try:
            payload = self._read_json_body()
            response = handle_query_payload(self.server.engine, payload)
        except ValueError as exc:
            self._send_error(HTTPStatus.BAD_REQUEST, str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self._send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return

        self._send_json(response)

    def log_message(self, format: str, *args) -> None:
        return

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("JSON body is required.")
        raw = self.rfile.read(length).decode("utf-8")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid JSON body.") from exc
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object.")
        return payload

    def _send_static(self, relative_path: str) -> None:
        target = (STATIC_DIR / relative_path).resolve()
        static_root = STATIC_DIR.resolve()
        if static_root not in target.parents:
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        self._send_file(target)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", _content_type(path))
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_error(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)


def _content_type(path: Path) -> str:
    suffix = path.suffix.casefold()
    if suffix == ".html":
        return "text/html; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript; charset=utf-8"
    return "application/octet-stream"


def run(host: str, port: int, csv_path: Path) -> None:
    server = CCTVWebServer((host, port), CCTVRequestHandler, csv_path)
    print(f"Serving CCTV query web app at http://{host}:{port}")
    print(f"CSV: {csv_path}")
    server.serve_forever()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the CCTV query local web app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--csv", default=str(DEFAULT_CSV))
    args = parser.parse_args(argv)

    run(args.host, args.port, Path(args.csv))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
