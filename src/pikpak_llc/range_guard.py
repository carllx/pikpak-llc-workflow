"""Localhost-only HTTP Range forwarding with a hard upstream byte budget."""

import re
import threading
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests


REQUEST_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$", re.IGNORECASE)
CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+)$", re.IGNORECASE)


class RangeGuardError(RuntimeError):
    """Raised when an upstream response violates a Range Guard invariant."""


class TransferBudgetExceeded(RangeGuardError):
    """Raised before an upstream body can exceed the configured budget."""


@dataclass(frozen=True)
class RangeEvent:
    range: str
    status: int
    content_range: str | None
    bytes_transferred: int
    outcome: str


class TransferLedger:
    """Reserve and count upstream bytes across probes and guarded FFmpeg reads."""

    def __init__(self, max_bytes):
        if max_bytes <= 0:
            raise ValueError("max_origin_bytes must be positive")
        self.max_bytes = int(max_bytes)
        self.total_upstream_bytes = 0
        self._reserved_bytes = 0
        self._events = []
        self._lock = threading.Lock()

    def reserve(self, byte_count, allow_partial=False):
        with self._lock:
            available = self.max_bytes - self.total_upstream_bytes - self._reserved_bytes
            reservation = min(byte_count, available) if allow_partial else byte_count
            if reservation <= 0 or reservation > available:
                raise TransferBudgetExceeded(
                    f"Origin transfer budget cannot reserve {byte_count} bytes"
                )
            self._reserved_bytes += reservation
            return reservation

    def consume(self, byte_count):
        with self._lock:
            if byte_count > self._reserved_bytes:
                raise RangeGuardError("Upstream body exceeded its validated Content-Range")
            self._reserved_bytes -= byte_count
            self.total_upstream_bytes += byte_count

    def release(self, byte_count):
        with self._lock:
            self._reserved_bytes -= byte_count
            if self._reserved_bytes < 0:
                raise RangeGuardError("Transfer reservation accounting underflow")

    def record(self, event):
        with self._lock:
            self._events.append(event)

    def increase_max_bytes(self, max_bytes):
        """Increase a sequential workflow's hard fuse without resetting evidence."""
        with self._lock:
            new_max = int(max_bytes)
            if new_max < self.max_bytes or new_max < (
                self.total_upstream_bytes + self._reserved_bytes
            ):
                raise ValueError("Transfer budget can only be increased")
            self.max_bytes = new_max

    @property
    def events(self):
        with self._lock:
            return [asdict(event) for event in self._events]


def parse_request_range(value):
    match = REQUEST_RANGE_RE.fullmatch((value or "").strip())
    if not match:
        raise RangeGuardError("A single explicit HTTP byte Range is required")
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else None
    if end is not None and end < start:
        raise RangeGuardError("Range end precedes Range start")
    return start, end


def validate_content_range(request_range, value):
    requested_start, requested_end = parse_request_range(request_range)
    match = CONTENT_RANGE_RE.fullmatch((value or "").strip())
    if not match:
        raise RangeGuardError("Missing or malformed upstream Content-Range")
    start, end, total = map(int, match.groups())
    if start != requested_start:
        raise RangeGuardError("Upstream Content-Range start does not match request")
    if requested_end is not None and end != requested_end:
        raise RangeGuardError("Upstream Content-Range end does not match request")
    if end < start or end >= total:
        raise RangeGuardError("Upstream Content-Range bounds are invalid")
    return start, end, total


class ValidatedRangeResponse:
    """A validated upstream 206 response with reserved transfer budget."""

    def __init__(self, response, request_range, ledger):
        self.response = response
        self.request_range = request_range
        self.ledger = ledger
        self.status = response.status_code
        self.content_range = response.headers.get("Content-Range")
        self.expected_bytes = 0
        self.transferred_bytes = 0
        self.total_size = None
        self._reserved_remaining = 0
        self._outcome = "FAIL"

        if self.status != 206:
            self._record_and_close("HTTP_200_ABORT" if self.status == 200 else "STATUS_REJECTED")
            raise RangeGuardError(f"Upstream media response must be HTTP 206, got {self.status}")

        try:
            start, end, self.total_size = validate_content_range(
                request_range, self.content_range
            )
            self.expected_bytes = end - start + 1
            content_length = response.headers.get("Content-Length")
            if content_length is not None and int(content_length) != self.expected_bytes:
                raise RangeGuardError("Content-Length does not match Content-Range")
            _, requested_end = parse_request_range(request_range)
            self._open_ended = requested_end is None
            if not self._open_ended:
                self._reserved_remaining = ledger.reserve(self.expected_bytes)
        except Exception:
            self._record_and_close("VALIDATION_REJECTED")
            raise

    def iter_content(self, chunk_size=65536):
        while self.transferred_bytes < self.expected_bytes:
            requested = min(
                chunk_size, self.expected_bytes - self.transferred_bytes
            )
            if self._open_ended:
                reserved = self.ledger.reserve(requested, allow_partial=True)
            else:
                reserved = min(requested, self._reserved_remaining)
                if reserved <= 0:
                    raise TransferBudgetExceeded("Origin transfer budget reached")
            try:
                chunk = self.response.raw.read(reserved)
            except Exception:
                if self._open_ended:
                    self.ledger.release(reserved)
                raise
            if not chunk:
                if self._open_ended:
                    self.ledger.release(reserved)
                break
            self.ledger.consume(len(chunk))
            if self._open_ended:
                if len(chunk) < reserved:
                    self.ledger.release(reserved - len(chunk))
            else:
                self._reserved_remaining -= len(chunk)
            self.transferred_bytes += len(chunk)
            yield chunk
        if self.transferred_bytes != self.expected_bytes:
            raise RangeGuardError(
                f"Incomplete upstream body: {self.transferred_bytes}/{self.expected_bytes} bytes"
            )
        self._outcome = "PASS"

    def read(self):
        try:
            return b"".join(self.iter_content())
        finally:
            self.close()

    def close(self):
        if self.response is None:
            return
        if self._reserved_remaining:
            self.ledger.release(self._reserved_remaining)
            self._reserved_remaining = 0
        self._record_and_close(self._outcome)

    def abort(self, outcome):
        self._outcome = outcome
        self.close()

    def _record_and_close(self, outcome):
        if self.response is None:
            return
        self.response.close()
        self.ledger.record(
            RangeEvent(
                range=self.request_range,
                status=self.status,
                content_range=self.content_range,
                bytes_transferred=self.transferred_bytes,
                outcome=outcome,
            )
        )
        self.response = None


def open_upstream_range(
    origin_url,
    request_range,
    ledger,
    session=None,
):
    """Open one upstream request without exposing its signed URL in telemetry."""
    parse_request_range(request_range)
    client = session or requests
    try:
        response = client.get(
            origin_url,
            headers={"Range": request_range},
            stream=True,
            allow_redirects=True,
            timeout=(15, 60),
        )
    except requests.RequestException as error:
        raise RangeGuardError(
            f"Upstream Range request failed: {type(error).__name__}"
        ) from error
    return ValidatedRangeResponse(
        response,
        request_range,
        ledger,
    )


def fetch_exact_range(origin_url, request_range, ledger, session=None):
    upstream = open_upstream_range(origin_url, request_range, ledger, session=session)
    return upstream.read(), upstream.total_size


class RangeGuard:
    """Forward FFmpeg media GETs through a localhost-only guarded seam."""

    def __init__(self, origin_url, ledger, session=None):
        self._origin_url = origin_url
        self._ledger = ledger
        self._session = session
        self._failure = None
        self._server = None
        self._thread = None

    def __enter__(self):
        guard = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/media":
                    self.send_error(404)
                    return
                request_range = self.headers.get("Range")
                if not request_range:
                    self.send_error(400, "Range required")
                    return
                upstream = None
                headers_sent = False
                try:
                    upstream = open_upstream_range(
                        guard._origin_url,
                        request_range,
                        guard._ledger,
                        session=guard._session,
                    )
                    self.send_response(206)
                    self.send_header("Content-Range", upstream.content_range)
                    self.send_header("Content-Length", str(upstream.expected_bytes))
                    self.send_header("Accept-Ranges", "bytes")
                    content_type = upstream.response.headers.get("Content-Type")
                    if content_type:
                        self.send_header("Content-Type", content_type)
                    self.end_headers()
                    headers_sent = True
                    for chunk in upstream.iter_content():
                        try:
                            self.wfile.write(chunk)
                        except (
                            BrokenPipeError,
                            ConnectionResetError,
                            ConnectionAbortedError,
                        ):
                            upstream.abort("CLIENT_CLOSED")
                            return
                except Exception as error:
                    guard._failure = error
                    if not headers_sent:
                        self.send_error(502, "Range Guard rejected upstream response")
                finally:
                    if upstream is not None:
                        upstream.close()

            def do_HEAD(self):
                self.send_error(405, "Range GET required")

            def log_message(self, format, *args):
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    @property
    def url(self):
        if self._server is None:
            raise RuntimeError("Range Guard has not started")
        return f"http://127.0.0.1:{self._server.server_port}/media"

    def raise_if_failed(self):
        if self._failure is not None:
            raise RangeGuardError(
                f"Range Guard failed: {type(self._failure).__name__}"
            ) from self._failure

    def __exit__(self, exc_type, exc, traceback):
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
        self._origin_url = None
