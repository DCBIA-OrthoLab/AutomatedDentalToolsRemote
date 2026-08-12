"""The client half of a streamed run, against a REAL server on a real socket.

Not mocked, for the same reason `test_transfer.py` is not: what this exercises
is a body that arrives in pieces over time, plus files fetched from a second
endpoint *while* that body is still open. A mocked `requests` response hands
back the whole thing at once and would pass against a client that waited for
the last byte before doing anything — which is exactly the bug this feature
exists to remove.

The fake server speaks the real protocol (`POST /run/{tool}` answering
`application/x-ndjson`, `GET /results/{id}`, `DELETE /results/{id}`) and is
deliberately unhelpful where a real one can be: it interleaves items and
artifacts, it fails part-way, and it sends a `relative_dir` that tries to
escape the output folder.

Usage:
    python3 -m unittest test_streaming
"""

import io
import json
import os
import shutil
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_HERE = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, "..", "..")))

from ServerToolsCoreLib.client import ToolServerClient
from ServerToolsCoreLib.errors import ServerToolError

TOKEN = "test-token"

# One tool, streaming, so `run()` opts in. The client reads this off the
# schema rather than being told by the module.
SCHEMA = {
    "name": "probe",
    "output_kind": "files",
    "streaming": True,
    "arguments": {"count": {"type": "int", "types": ["int"], "required": False}},
}


def _zip_bytes(members: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class _Handler(BaseHTTPRequestHandler):
    """Serves whatever `script` the test set: a list of events, plus the blobs
    each artifact refers to."""

    script = []
    blobs = {}
    fetched = []
    deleted = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.headers.get("X-Result-Delivery") != "stream":
            # The blocking contract: one real archive, which the client
            # integrity-checks before accepting.
            payload = _zip_bytes({"whole_run.txt": "everything at once"})
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Content-Disposition", 'attachment; filename="probe_output.zip"'
            )
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for event in type(self).script:
            self.wfile.write((json.dumps(event) + "\n").encode())
            # Flushed per line: the client must be able to act on event N
            # before event N+1 exists, which is the entire contract.
            self.wfile.flush()

    def do_GET(self):
        result_id = self.path.rsplit("/", 1)[-1]
        blob = type(self).blobs.get(result_id)
        if blob is None:
            self.send_response(404)
            self.end_headers()
            return
        type(self).fetched.append(result_id)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        self.wfile.write(blob)

    def do_DELETE(self):
        type(self).deleted.append(self.path.rsplit("/", 1)[-1])
        self.send_response(204)
        self.end_headers()


class StreamedRunTest(unittest.TestCase):
    def setUp(self):
        _Handler.script = []
        _Handler.blobs = {}
        _Handler.fetched = []
        _Handler.deleted = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)

        host, port = self.server.server_address[:2]
        self.client = ToolServerClient(f"http://{host}:{port}", TOKEN, verify_tls=False)
        self.client._tools_cache = {"probe": SCHEMA}

        self.output = tempfile.mkdtemp(prefix="stream_out_")
        self.addCleanup(shutil.rmtree, self.output, True)

    def _artifact(self, result_id: str, filename: str, payload: bytes, relative_dir="."):
        _Handler.blobs[result_id] = payload
        return {
            "event": "artifact",
            "name": filename,
            "relative_dir": relative_dir,
            "result_ref": {
                "result_id": result_id,
                "filename": filename,
                "media_type": "application/octet-stream",
                "size": len(payload),
            },
        }

    def _run(self):
        events = []
        result = self.client.run(
            "probe", args={}, output_dir=self.output, event_cb=events.append
        )
        return result, events

    def test_every_event_reaches_the_callback_in_order(self):
        _Handler.script = [
            {"event": "start", "tool": "probe"},
            {"event": "item", "index": 1, "total": 2, "name": "p1", "status": "running"},
            {"event": "item", "index": 1, "total": 2, "name": "p1", "status": "ok"},
            {"event": "item", "index": 2, "total": 2, "name": "p2", "status": "ok"},
            {"event": "done"},
        ]
        _result, events = self._run()
        self.assertEqual(
            [(e["event"], e.get("status")) for e in events],
            [("start", None), ("item", "running"), ("item", "ok"), ("item", "ok"), ("done", None)],
        )

    def test_each_artifact_lands_in_the_output_folder(self):
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "p1.nii.gz", b"first patient"),
            self._artifact("r2", "p2.nii.gz", b"second patient"),
            {"event": "done"},
        ]
        result, _events = self._run()
        self.assertEqual(result.kind, "stream")
        self.assertEqual(result.path, self.output)
        self.assertEqual(
            sorted(os.listdir(self.output)), ["p1.nii.gz", "p2.nii.gz"]
        )
        with open(os.path.join(self.output, "p1.nii.gz"), "rb") as handle:
            self.assertEqual(handle.read(), b"first patient")

    def test_a_zipped_item_is_unpacked_where_it_belongs(self):
        """One artifact per item, holding that item's files, placed under the
        directory the event names -- so two patients whose scans share a file
        name do not collide on the client either."""
        _Handler.script = [
            {"event": "start"},
            self._artifact(
                "r1", "case.zip",
                _zip_bytes({"scan_Seg.nii.gz": "A"}), relative_dir="subjectA",
            ),
            self._artifact(
                "r2", "case.zip",
                _zip_bytes({"scan_Seg.nii.gz": "B"}), relative_dir="subjectB",
            ),
            {"event": "done"},
        ]
        self._run()
        self.assertEqual(sorted(os.listdir(self.output)), ["subjectA", "subjectB"])
        for subject, expected in (("subjectA", "A"), ("subjectB", "B")):
            path = os.path.join(self.output, subject, "scan_Seg.nii.gz")
            self.assertTrue(os.path.isfile(path))
            with open(path) as handle:
                self.assertEqual(handle.read(), expected)
        # The archive itself is not left behind next to what it held.
        self.assertNotIn("case.zip", os.listdir(os.path.join(self.output, "subjectA")))

    def test_the_files_survive_a_run_that_fails_afterwards(self):
        """The whole reason for the feature: 26 patients segmented and the 27th
        fatal used to return nothing at all."""
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "p1.nii.gz", b"kept"),
            {"event": "item", "index": 2, "total": 2, "name": "p2", "status": "failed",
             "error": "could not be read"},
            {"event": "error", "detail": "RuntimeError", "delivered": 1},
        ]
        with self.assertRaises(ServerToolError) as raised:
            self._run()
        # The message says what was saved, because "it failed" and "it failed
        # after writing 1 of your 2 patients" call for different next steps.
        self.assertIn("1 result", str(raised.exception))
        self.assertEqual(os.listdir(self.output), ["p1.nii.gz"])

    def test_a_directory_that_escapes_the_output_folder_is_refused(self):
        """`relative_dir` is the server's and is joined onto a local path. A
        `..` in it would write a patient's files somewhere the user never
        picked, so it is dropped rather than obeyed."""
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "escaped.txt", b"nope", relative_dir="../../elsewhere"),
            {"event": "done"},
        ]
        self._run()
        self.assertEqual(os.listdir(self.output), ["escaped.txt"])
        self.assertFalse(os.path.exists(os.path.join(self.output, "..", "..", "elsewhere")))

    def test_a_zip_member_that_escapes_is_refused(self):
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "evil.zip", _zip_bytes({"../escaped.txt": "nope"})),
            {"event": "done"},
        ]
        # A result that could not be brought back is a real failure and is
        # raised as one, at the END so everything else is saved first. Silently
        # continuing would leave a hole in the results with only a log line.
        with self.assertRaises(ServerToolError) as raised:
            self._run()
        self.assertIn("could not be downloaded", str(raised.exception))
        self.assertFalse(
            os.path.exists(os.path.join(os.path.dirname(self.output), "escaped.txt"))
        )

    def test_the_reader_never_waits_for_a_download(self):
        """The fix for "the server seems to wait for the client": fetching runs
        on its own thread, so a slow download cannot stop the event loop from
        reading -- which is what used to freeze the panel mid-run and make a
        server that was still working look stalled."""
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "p1.nii.gz", b"x" * 4096),
            {"event": "item", "index": 2, "total": 2, "name": "p2", "status": "running"},
            {"event": "item", "index": 2, "total": 2, "name": "p2", "status": "ok"},
            {"event": "done"},
        ]
        seen = []
        self.client.run("probe", args={}, output_dir=self.output,
                        event_cb=lambda e: seen.append(e["event"]))
        # Every event was forwarded, and the artifact still landed. The
        # trailing "item" is the client reporting what that artifact cost,
        # which arrives once the fetcher thread has finished with it.
        self.assertEqual(seen[:5], ["start", "artifact", "item", "item", "done"])
        self.assertEqual(os.listdir(self.output), ["p1.nii.gz"])

    def test_a_malformed_line_does_not_abandon_the_run(self):
        """A file already on disk must not be lost to an event the client
        cannot parse."""
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "p1.nii.gz", b"kept"),
            "NOT JSON",
            {"event": "done"},
        ]
        # The handler json.dumps everything, so a raw string arrives quoted but
        # parses to a str rather than a dict; the client must survive both.
        _result, events = self._run()
        self.assertEqual(os.listdir(self.output), ["p1.nii.gz"])
        # `done` is the server's last word; the client may still report what
        # collecting each artifact cost after it (see the "saved" events).
        self.assertIn("done", [e["event"] for e in events])

    def test_each_artifact_reports_what_it_cost(self):
        """Where a run's time went has to be visible in the PANEL, not only in
        a log line whose level the host application decides. Diagnosing a slow
        run by asking someone to raise a logger's level is how you get no
        answer -- which is exactly what happened before this existed."""
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "p1.nii.gz", b"x" * 8192),
            {"event": "done"},
        ]
        events = []
        self.client.run("probe", args={}, output_dir=self.output, event_cb=events.append)

        saved = [e for e in events if e.get("status") == "saved"]
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["name"], "p1.nii.gz")
        # The three numbers that tell a slow transfer from a slow unpack from a
        # client that never got round to it.
        self.assertIn("down", saved[0]["error"])
        self.assertIn("unpack", saved[0]["error"])

    def test_each_collected_result_is_released(self):
        """A reference the server keeps until someone says otherwise; not
        releasing it would leave patient data on the server until the reaper."""
        _Handler.script = [
            {"event": "start"},
            self._artifact("r1", "p1.nii.gz", b"x"),
            {"event": "done"},
        ]
        self._run()
        self.assertEqual(_Handler.fetched, ["r1"])
        self.assertEqual(_Handler.deleted, ["r1"])

    def test_a_tool_that_does_not_stream_is_never_asked_to(self):
        """The header is sent only when the SCHEMA says the tool can stream, so
        a module never keeps a list of which of its tools do."""
        self.client._tools_cache = {"probe": dict(SCHEMA, streaming=False)}
        result = self.client.run(
            "probe", args={}, output_dir=self.output, event_cb=lambda event: None
        )
        # The fake server answers the non-streaming branch for that request.
        self.assertNotEqual(result.kind, "stream")

    def test_no_event_callback_means_no_streaming(self):
        """A caller that does not want events gets the blocking contract, even
        for a tool that can stream."""
        result = self.client.run("probe", args={}, output_dir=self.output)
        self.assertNotEqual(result.kind, "stream")


if __name__ == "__main__":
    unittest.main()
