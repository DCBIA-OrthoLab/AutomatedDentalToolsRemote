"""Unit tests for ServerToolsCoreLib.client — run outside Slicer, requests mocked.

Usage:
    python3 -m unittest ServerToolsCore/Testing/Python/test_client.py
"""

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import requests

from ServerToolsCoreLib.client import (
    ToolResult,
    ToolServerClient,
    _HEALTH_CHECK_TIMEOUT,
    _TOOLS_FETCH_TIMEOUT,
    accepts_folder,
    argument_types,
    download_file,
    file_extensions_for,
    is_file_type,
)
from ServerToolsCoreLib.errors import ServerToolError

TOOLS_RESPONSE = [
    {
        "name": "example_tool",
        "arguments": {
            "label": {"type": "str", "required": True},
            "file": {"type": "file", "required": True},
        },
        "output_kind": "text",
    },
]


def _response(status_code=200, json_data=None, content=b"", headers=None, text=""):
    response = mock.Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.headers = headers or {"Content-Type": "application/json"}
    response.content = content
    response.text = text
    # The client downloads file results via iter_content (stream=True), never
    # via .content; a mock without it would hand the writer a Mock object.
    response.iter_content = lambda chunk_size: iter([content] if content else [])
    if json_data is not None:
        response.json.return_value = json_data
    else:
        response.json.side_effect = ValueError("no json body")
    return response


def _zip_bytes(members=None) -> bytes:
    """A genuinely valid zip archive, for tests whose result filename ends in
    .zip: the client CRC-checks those before accepting them, so `b"zip-bytes"`
    placeholders no longer pass."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in (members or {"result.txt": "ok"}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


class ToolServerClientTest(unittest.TestCase):
    def setUp(self):
        self.client = ToolServerClient("https://example.org/", "secret-token")

    def test_server_url_is_normalized(self):
        self.assertEqual(self.client._server_url, "https://example.org")

    # -- configure() (live settings panel updates) -----------------------

    def test_configure_updates_fields(self):
        self.client.configure(server_url="http://other.org/", token="new-token", verify_tls=False, timeout=42)

        self.assertEqual(self.client.server_url, "http://other.org")
        self.assertEqual(self.client.token, "new-token")
        self.assertFalse(self.client.verify_tls)
        self.assertEqual(self.client.timeout, 42)

    def test_configure_partial_update_leaves_other_fields(self):
        self.client.configure(token="only-token-changes")

        self.assertEqual(self.client.server_url, "https://example.org")
        self.assertEqual(self.client.token, "only-token-changes")
        self.assertTrue(self.client.verify_tls)
        self.assertEqual(self.client.timeout, 600)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_configure_drops_cached_tools(self, mock_get):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)
        self.client.list_tools()
        self.assertEqual(mock_get.call_count, 1)

        self.client.configure(server_url="http://other.org")

        mock_get.return_value = _response(json_data=[])
        self.client.list_tools()
        self.assertEqual(mock_get.call_count, 2)  # re-fetched, not served from the old cache

    def test_properties_reflect_constructor_defaults(self):
        self.assertEqual(self.client.server_url, "https://example.org")
        self.assertEqual(self.client.token, "secret-token")
        self.assertTrue(self.client.verify_tls)
        self.assertEqual(self.client.timeout, 600)

    # -- list_tools / get_tool_schema ---------------------------------

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_list_tools_caches(self, mock_get):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)

        tools = self.client.list_tools()
        tools_again = self.client.list_tools()

        self.assertEqual(mock_get.call_count, 1)
        self.assertIn("example_tool", tools)
        self.assertIs(tools, tools_again)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_list_tools_force_refresh(self, mock_get):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)

        self.client.list_tools()
        self.client.list_tools(force_refresh=True)

        self.assertEqual(mock_get.call_count, 2)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_get_tool_schema_unknown_tool_lists_available(self, mock_get):
        mock_get.return_value = _response(
            json_data=[
                {"name": "beta_tool", "arguments": {}, "output_kind": "text"},
                {"name": "alpha_tool", "arguments": {}, "output_kind": "text"},
            ]
        )

        with self.assertRaises(ServerToolError) as ctx:
            self.client.get_tool_schema("does_not_exist")

        self.assertIn("does_not_exist", str(ctx.exception))
        self.assertIn("alpha_tool, beta_tool", str(ctx.exception))

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_get_tool_schema_can_bypass_the_cache(self, mock_get):
        # What a panel retrying after a failure needs: the cached list may be
        # the very reason the tool wasn't found.
        mock_get.return_value = _response(json_data=[])
        with self.assertRaises(ServerToolError):
            self.client.get_tool_schema("example_tool")

        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)

        self.assertIn("label", self.client.get_tool_schema("example_tool", force_refresh=True)["arguments"])
        self.assertEqual(mock_get.call_count, 2)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_get_tool_schema_uses_the_cache_by_default(self, mock_get):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)
        self.client.get_tool_schema("example_tool")
        self.client.get_tool_schema("example_tool")

        self.assertEqual(mock_get.call_count, 1)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_list_tools_uses_short_timeout(self, mock_get):
        # get_tool_schema() runs synchronously from a module's setup(); it must
        # not be able to freeze Slicer for up to self._timeout (600s).
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)
        self.client.list_tools()

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["timeout"], _TOOLS_FETCH_TIMEOUT)
        self.assertLess(_TOOLS_FETCH_TIMEOUT, self.client._timeout)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_fetch_tools_network_error_wrapped(self, mock_get):
        mock_get.side_effect = requests.RequestException("boom")
        with self.assertRaises(ServerToolError):
            self.client.list_tools()

    # -- list_tool_data (server-side models/testfiles) -----------------

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_list_tool_data_request_shape_and_result(self, mock_get):
        mock_get.return_value = _response(
            json_data={"models": ["stacking_v1.zip", "stacking_v2.zip"], "testfiles": ["demo.zip"]}
        )

        data = self.client.list_tool_data("SurgMovPred")

        self.assertEqual(data, {"models": ["stacking_v1.zip", "stacking_v2.zip"], "testfiles": ["demo.zip"]})
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://example.org/tools/SurgMovPred/data")
        # The endpoint is Bearer-protected, unlike /tools.
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")
        # Called synchronously from a module's setup(), like the schema fetch:
        # must use the short timeout, never the 600s tool-execution one.
        self.assertEqual(kwargs["timeout"], _TOOLS_FETCH_TIMEOUT)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_list_tool_data_tolerates_missing_keys(self, mock_get):
        mock_get.return_value = _response(json_data={})

        self.assertEqual(self.client.list_tool_data("SurgMovPred"), {"models": [], "testfiles": []})

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_list_tool_data_network_error_wrapped(self, mock_get):
        mock_get.side_effect = requests.RequestException("boom")
        with self.assertRaises(ServerToolError):
            self.client.list_tool_data("SurgMovPred")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_list_tool_data_maps_error_status(self, mock_get):
        mock_get.return_value = _response(status_code=401, json_data={})
        with self.assertRaises(ServerToolError) as ctx:
            self.client.list_tool_data("SurgMovPred")
        self.assertEqual(ctx.exception.status_code, 401)

    # -- local validation ----------------------------------------------

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_rejects_unexpected_argument_locally(self, mock_get):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)

        with self.assertRaises(ServerToolError):
            self.client.run("example_tool", args={"typo": "x"}, files={"file": __file__}, output_dir="/tmp")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_rejects_missing_required_argument_locally(self, mock_get):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)

        with self.assertRaises(ServerToolError):
            self.client.run("example_tool", args={}, files={"file": __file__}, output_dir="/tmp")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_rejects_missing_required_file_locally(self, mock_get):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)

        with self.assertRaises(ServerToolError):
            self.client.run("example_tool", args={"label": "x"}, files={}, output_dir="/tmp")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_allows_missing_optional_file_locally(self, mock_get):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "optional_file_tool",
                    "arguments": {"attachment": {"type": "file", "required": False}},
                    "output_kind": "text",
                }
            ]
        )

        # Should pass local validation (no file argument required); network call
        # itself isn't exercised here (no requests.post mock), so a failure would
        # surface as a real connection attempt/error, not a ServerToolError.
        try:
            self.client._validate_against_schema(
                self.client.get_tool_schema("optional_file_tool"), {}, {}
            )
        except ServerToolError as exc:
            self.fail(f"Optional file argument should not be required: {exc}")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_rejects_file_when_tool_has_no_file_argument_locally(self, mock_get):
        mock_get.return_value = _response(
            json_data=[{"name": "no_file_tool", "arguments": {}, "output_kind": "text"}]
        )

        with self.assertRaises(ServerToolError):
            self.client.run("no_file_tool", args={}, files={"file": __file__}, output_dir="/tmp")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_rejects_file_argument_name_not_declared_as_file_locally(self, mock_get):
        # "label" exists in the schema but is type "str", not "file".
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)

        with self.assertRaises(ServerToolError):
            self.client.run("example_tool", args={}, files={"label": __file__}, output_dir="/tmp")

    # -- multi-file tools (e.g. real SurgMovPred: "model" + "input") ------

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_rejects_when_only_one_of_two_required_files_given(self, mock_get):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "SurgMovPred",
                    "arguments": {
                        "model": {"type": "zip_file", "required": True},
                        "input": {"type": "zip_file", "required": True},
                    },
                    "output_kind": "file",
                }
            ]
        )

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("SurgMovPred", args={}, files={"input": __file__}, output_dir="/tmp")

        self.assertIn("model", str(ctx.exception))

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_sends_each_file_under_its_own_argument_name(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "SurgMovPred",
                    "arguments": {
                        "model": {"type": "zip_file", "required": True},
                        "input": {"type": "zip_file", "required": True},
                    },
                    "output_kind": "file",
                }
            ]
        )
        mock_post.return_value = _response(
            content=_zip_bytes(), headers={"Content-Type": "application/zip"}
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            self.client.run(
                "SurgMovPred", args={}, files={"model": __file__, "input": __file__}, output_dir=out_dir
            )

        _, kwargs = mock_post.call_args
        self.assertEqual(set(kwargs["files"].keys()), {"model", "input"})
        model_filename, model_handle = kwargs["files"]["model"]
        input_filename, input_handle = kwargs["files"]["input"]
        self.assertEqual(model_filename, os.path.basename(__file__))
        self.assertEqual(input_filename, os.path.basename(__file__))
        self.assertTrue(model_handle.closed)
        self.assertTrue(input_handle.closed)

    # -- request shape ----------------------------------------------------

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_sends_filename_with_upload(self, mock_get, mock_post):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)
        mock_post.return_value = _response(json_data={"result": "hello"})

        self.client.run("example_tool", args={"label": "x"}, files={"file": __file__}, output_dir="/tmp")

        _, kwargs = mock_post.call_args
        filename, file_handle = kwargs["files"]["file"]
        self.assertEqual(filename, os.path.basename(__file__))
        self.assertTrue(file_handle.closed)  # closed after the call

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_text_result_and_request_shape(self, mock_get, mock_post):
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)
        mock_post.return_value = _response(json_data={"result": "hello"})

        result = self.client.run(
            "example_tool", args={"label": "x"}, files={"file": __file__}, output_dir="/tmp"
        )

        self.assertIsInstance(result, ToolResult)
        self.assertEqual(result.kind, "text")
        self.assertEqual(result.text, "hello")

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer secret-token")
        self.assertEqual(kwargs["data"], {"label": "x"})

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_stringifies_bool(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "flag_tool",
                    "arguments": {"flag": {"type": "bool", "required": True}},
                    "output_kind": "text",
                }
            ]
        )
        mock_post.return_value = _response(json_data={"result": "ok"})

        self.client.run("flag_tool", args={"flag": True}, output_dir="/tmp")

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["data"], {"flag": "true"})

    # -- error mapping ----------------------------------------------------

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_maps_422_to_server_message(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "text"}]
        )
        mock_post.return_value = _response(
            status_code=422, json_data={"detail": "Missing required argument 'x'"}
        )

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("no_args_tool", args={}, output_dir="/tmp")

        self.assertIn("Missing required argument", str(ctx.exception))
        self.assertEqual(ctx.exception.status_code, 422)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_maps_401(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "text"}]
        )
        mock_post.return_value = _response(status_code=401, json_data={})

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("no_args_tool", args={}, output_dir="/tmp")

        self.assertEqual(ctx.exception.status_code, 401)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_error_message_falls_back_to_plain_text_body(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "text"}]
        )
        mock_post.return_value = _response(
            status_code=400, headers={"Content-Type": "text/plain"}, text="disallowed extension: .exe"
        )

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("no_args_tool", args={}, output_dir="/tmp")

        self.assertIn("disallowed extension", str(ctx.exception))

    # -- result filename / extension ---------------------------------------

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_segmentation_result_gets_nii_gz_extension(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[{"name": "seg_tool", "arguments": {}, "output_kind": "segmentation"}]
        )
        mock_post.return_value = _response(
            content=b"binary", headers={"Content-Type": "application/octet-stream"}
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("seg_tool", args={}, output_dir=out_dir)

        self.assertTrue(result.path.endswith(".nii.gz"), result.path)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_result_filename_prefers_content_disposition(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[{"name": "seg_tool", "arguments": {}, "output_kind": "segmentation"}]
        )
        mock_post.return_value = _response(
            content=b"binary",
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Disposition": 'attachment; filename="custom_name.nrrd"',
            },
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("seg_tool", args={}, output_dir=out_dir)

        self.assertEqual(os.path.basename(result.path), "custom_name.nrrd")

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_xlsx_result_keeps_its_own_extension_not_zip(self, mock_get, mock_post):
        # Regression: an .xlsx is a zip container internally (OOXML). The
        # resolved result filename must never end in .zip, or downstream code
        # deciding "should this be unpacked as an archive" purely from the
        # extension (see slicer_io.is_extractable_archive) would wrongly
        # extract a spreadsheet into raw XML parts instead of keeping it.
        mock_get.return_value = _response(
            json_data=[{"name": "SurgMovPred", "arguments": {}, "output_kind": "file"}]
        )
        mock_post.return_value = _response(
            content=b"PK\x03\x04fake-xlsx-bytes",
            headers={
                "Content-Type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "Content-Disposition": 'attachment; filename="predictions_outputs.xlsx"',
            },
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("SurgMovPred", args={}, output_dir=out_dir)

        self.assertEqual(os.path.basename(result.path), "predictions_outputs.xlsx")
        self.assertFalse(result.path.lower().endswith(".zip"))

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_result_filename_falls_back_to_mimetype_extension_without_content_disposition(self, mock_get, mock_post):
        # No Content-Disposition this time: the extension must still come from
        # a real MIME lookup (mirroring the server's own mimetypes.guess_type),
        # not the generic .bin/.gz guess.
        mock_get.return_value = _response(
            json_data=[{"name": "SurgMovPred", "arguments": {}, "output_kind": "file"}]
        )
        mock_post.return_value = _response(
            content=b"csv,data",
            headers={"Content-Type": "text/csv"},
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("SurgMovPred", args={}, output_dir=out_dir)

        self.assertTrue(result.path.endswith(".csv"), result.path)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_writes_binary_result_to_output_dir(self, mock_get, mock_post):
        import tempfile

        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "file"}]
        )
        mock_post.return_value = _response(
            content=b"binary-bytes", headers={"Content-Type": "application/gzip"}
        )

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("no_args_tool", args={}, output_dir=out_dir)

            self.assertEqual(result.kind, "file")
            self.assertTrue(result.path.endswith(".gz"))
            with open(result.path, "rb") as fh:
                self.assertEqual(fh.read(), b"binary-bytes")

    # -- download integrity ------------------------------------------------

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_streams_the_response(self, mock_get, mock_post):
        # stream=True is what keeps a multi-hundred-MB result archive out of
        # Slicer's RAM: the body must be consumed by iter_content, not
        # pre-buffered inside requests.post.
        mock_get.return_value = _response(json_data=TOOLS_RESPONSE)
        mock_post.return_value = _response(json_data={"result": "ok"})

        self.client.run("example_tool", args={"label": "x"}, files={"file": __file__}, output_dir="/tmp")

        _, kwargs = mock_post.call_args
        self.assertIs(kwargs["stream"], True)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_truncated_download_is_rejected_and_removed(self, mock_get, mock_post):
        import tempfile

        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "file"}]
        )
        mock_post.return_value = _response(
            content=b"only-half-the-bytes",
            headers={"Content-Type": "application/gzip", "Content-Length": "999999"},
        )

        with tempfile.TemporaryDirectory() as out_dir:
            with self.assertRaises(ServerToolError) as ctx:
                self.client.run("no_args_tool", args={}, output_dir=out_dir)
            self.assertIn("Truncated", str(ctx.exception))
            # The partial file must not survive: a later step (or the user)
            # finding it would mistake it for a real result.
            self.assertEqual(os.listdir(out_dir), [])

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_corrupt_zip_result_is_rejected_and_removed(self, mock_get, mock_post):
        import tempfile

        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "files"}]
        )
        # Looks like a zip (magic bytes, .zip filename) but has no readable
        # central directory -- exactly what a connection cut mid-body leaves.
        mock_post.return_value = _response(
            content=b"PK\x03\x04this-is-not-a-whole-archive",
            headers={
                "Content-Type": "application/zip",
                "Content-Disposition": 'attachment; filename="AMASSS_Pred.zip"',
            },
        )

        with tempfile.TemporaryDirectory() as out_dir:
            with self.assertRaises(ServerToolError) as ctx:
                self.client.run("no_args_tool", args={}, output_dir=out_dir)
            self.assertIn("unreadable", str(ctx.exception))
            self.assertEqual(os.listdir(out_dir), [])

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_intact_zip_result_passes_verification(self, mock_get, mock_post):
        import tempfile

        content = _zip_bytes({"scan_Pred_MAND.nii.gz": "seg", "scan_Pred_MAND.vtk": "surf"})
        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "files"}]
        )
        mock_post.return_value = _response(
            content=content,
            headers={
                "Content-Type": "application/zip",
                "Content-Length": str(len(content)),
                "Content-Disposition": 'attachment; filename="AMASSS_Pred.zip"',
            },
        )

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("no_args_tool", args={}, output_dir=out_dir)

            self.assertEqual(result.kind, "file")
            with open(result.path, "rb") as fh:
                self.assertEqual(fh.read(), content)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_length_check_skipped_when_body_travels_compressed(self, mock_get, mock_post):
        import tempfile

        # With Content-Encoding, Content-Length counts wire bytes while
        # iter_content yields the decompressed stream: a mismatch there is
        # normal and must not be reported as truncation.
        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "file"}]
        )
        mock_post.return_value = _response(
            content=b"decompressed-and-longer-than-the-wire-count",
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": "10",
                "Content-Encoding": "gzip",
                "Content-Disposition": 'attachment; filename="result.bin"',
            },
        )

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("no_args_tool", args={}, output_dir=out_dir)
            self.assertEqual(result.kind, "file")

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_download_reports_progress_with_a_total(self, mock_get, mock_post):
        # A silent multi-minute run is what made a user cancel a job that was
        # working; the download phase must report bytes as they land.
        import tempfile

        content = _zip_bytes({"a.nii.gz": "x" * 5_000_000})
        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "files"}]
        )
        mock_post.return_value = _response(
            content=content,
            headers={
                "Content-Type": "application/zip",
                "Content-Length": str(len(content)),
                "Content-Disposition": 'attachment; filename="out.zip"',
            },
        )

        messages = []
        with tempfile.TemporaryDirectory() as out_dir:
            self.client.run(
                "no_args_tool", args={}, output_dir=out_dir, progress_cb=messages.append
            )

        downloads = [m for m in messages if m.startswith("Downloading results")]
        self.assertTrue(downloads, messages)
        self.assertIn("MB", downloads[-1])
        self.assertIn("100%", downloads[-1])

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_download_progress_omits_the_total_when_unusable(self, mock_get, mock_post):
        # Content-Encoding makes Content-Length count wire bytes, so a
        # percentage computed from it would run past 100.
        import tempfile

        mock_get.return_value = _response(
            json_data=[{"name": "no_args_tool", "arguments": {}, "output_kind": "file"}]
        )
        mock_post.return_value = _response(
            content=b"z" * 2_000_000,
            headers={
                "Content-Type": "application/octet-stream",
                "Content-Length": "10",
                "Content-Encoding": "gzip",
                "Content-Disposition": 'attachment; filename="out.bin"',
            },
        )

        messages = []
        with tempfile.TemporaryDirectory() as out_dir:
            self.client.run(
                "no_args_tool", args={}, output_dir=out_dir, progress_cb=messages.append
            )

        downloads = [m for m in messages if m.startswith("Downloading results")]
        self.assertTrue(downloads, messages)
        self.assertNotIn("%", downloads[-1])

    # -- health --------------------------------------------------------

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_health_true(self, mock_get):
        mock_get.return_value = _response(json_data={"status": "ok"})
        self.assertTrue(self.client.health())

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_health_uses_short_timeout(self, mock_get):
        mock_get.return_value = _response(json_data={"status": "ok"})
        self.client.health()

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs["timeout"], _HEALTH_CHECK_TIMEOUT)
        self.assertLess(_HEALTH_CHECK_TIMEOUT, self.client._timeout)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_health_false_on_network_error(self, mock_get):
        mock_get.side_effect = requests.RequestException("boom")
        self.assertFalse(self.client.health())

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_health_does_not_swallow_unrelated_errors(self, mock_get):
        response = _response(json_data={"status": "ok"})
        response.json.side_effect = KeyError("programming error, not a network/parse issue")
        mock_get.return_value = response

        with self.assertRaises(KeyError):
            self.client.health()


class IsFileTypeTest(unittest.TestCase):
    def test_literal_file(self):
        self.assertTrue(is_file_type("file"))

    def test_suffixed_types(self):
        self.assertTrue(is_file_type("zip_file"))
        self.assertTrue(is_file_type("nifti_file"))
        self.assertTrue(is_file_type("csv_file"))  # not seen yet, but the convention must cover it

    def test_scalar_types_are_not_file_types(self):
        self.assertFalse(is_file_type("str"))
        self.assertFalse(is_file_type("int"))
        self.assertFalse(is_file_type("float"))
        self.assertFalse(is_file_type("bool"))

    def test_missing_type_is_not_a_file_type(self):
        self.assertFalse(is_file_type(""))


class PublishedExtensionsTest(unittest.TestCase):
    """The server publishes each file type's extensions next to `types`, so
    the client keeps no copy of its FILE_TYPES table."""

    def test_extensions_come_from_the_schema(self):
        spec = {
            "type": "csv_file",
            "types": ["csv_file", "folder"],
            "extensions": {"csv_file": [".csv"], "folder": [".zip"]},
        }

        # "folder"'s .zip is what a zipped folder uploads as, not something a
        # file picker should offer.
        self.assertEqual(file_extensions_for(spec), (".csv",))

    def test_a_multi_format_type_needs_no_client_side_table(self):
        # AMASSS's input. Nothing in the name says .nii/.nrrd/.gipl.
        spec = {
            "type": "volume_or_zip_file",
            "types": ["volume_or_zip_file"],
            "extensions": {"volume_or_zip_file": [".nii", ".nii.gz", ".nrrd", ".zip"]},
        }

        self.assertEqual(file_extensions_for(spec), (".nii", ".nii.gz", ".nrrd", ".zip"))

    def test_a_type_the_server_declines_to_restrict_is_unrestricted(self):
        spec = {"type": "file", "types": ["file"], "extensions": {"file": None}}

        self.assertEqual(file_extensions_for(spec), ())

    def test_the_schema_wins_over_the_fallback_table(self):
        # A server that changes an extension must not be second-guessed.
        spec = {
            "type": "nifti_file",
            "types": ["nifti_file"],
            "extensions": {"nifti_file": [".nii", ".nii.gz", ".nrrd"]},
        }

        self.assertEqual(file_extensions_for(spec), (".nii", ".nii.gz", ".nrrd"))

    def test_a_server_predating_the_field_still_works(self):
        # No "extensions" key at all: fall back to the local table.
        self.assertEqual(file_extensions_for({"types": ["nifti_file"]}), (".nii", ".nii.gz"))


class ArgumentTypesTest(unittest.TestCase):
    """An argument may accept several types (`types`), e.g. example_tool's
    `input`: a .csv file *or* a whole folder.

    These exercise the fallback path — a server that does not publish
    `extensions` (see PublishedExtensionsTest for the normal one).
    """

    _INPUT = {"type": "csv_file", "types": ["csv_file", "folder"]}

    def test_types_wins_over_the_single_type(self):
        self.assertEqual(argument_types(self._INPUT), ["csv_file", "folder"])

    def test_falls_back_to_the_single_type(self):
        # A schema predating the `types` field must still work.
        self.assertEqual(argument_types({"type": "zip_file"}), ["zip_file"])
        self.assertEqual(argument_types({}), [])

    def test_accepts_folder(self):
        self.assertTrue(accepts_folder(self._INPUT))
        self.assertFalse(accepts_folder({"type": "zip_file", "types": ["zip_file"]}))
        self.assertFalse(accepts_folder({"type": "str", "types": ["str"]}))

    def test_extensions_come_from_the_non_folder_types(self):
        self.assertEqual(file_extensions_for(self._INPUT), (".csv",))

    def test_extensions_of_a_multi_extension_type(self):
        self.assertEqual(file_extensions_for({"types": ["nifti_file"]}), (".nii", ".nii.gz"))

    def test_extensions_of_several_file_types(self):
        self.assertEqual(file_extensions_for({"types": ["csv_file", "zip_file"]}), (".csv", ".zip"))

    def test_generic_file_type_is_unrestricted(self):
        self.assertEqual(file_extensions_for({"types": ["file"]}), ())
        self.assertEqual(file_extensions_for({"types": ["csv_file", "file"]}), ())

    def test_folder_only_argument_has_no_extensions(self):
        self.assertEqual(file_extensions_for({"types": ["folder"]}), ())

    def test_unknown_file_type_derives_its_extension_from_its_name(self):
        # Same convention as is_file_type: a new "<x>_file" the server adds
        # needs no client-side change.
        self.assertEqual(file_extensions_for({"types": ["vtk_file"]}), (".vtk",))

    def test_a_multi_format_type_lists_every_extension(self):
        # The server's "volume_or_zip_file" (used by its AMASSS tool): a name
        # that spells out no extension at all. Its entry has to mirror the
        # server's FILE_TYPES table, which /tools does not publish.
        self.assertEqual(
            file_extensions_for({"types": ["volume_or_zip_file"]}),
            (".nii", ".nii.gz", ".nrrd", ".nrrd.gz", ".gipl", ".gipl.gz", ".zip"),
        )

    def test_an_unknown_compound_type_name_is_not_turned_into_a_filter(self):
        # Guessing ".scan_or_mesh" from "scan_or_mesh_file" would give a file
        # dialog matching nothing — strictly worse than not filtering. A
        # compound name we don't know degrades to an unrestricted picker.
        self.assertEqual(file_extensions_for({"types": ["scan_or_mesh_file"]}), ())


class RealServerSchemaTest(unittest.TestCase):
    """Regression coverage for the actual /tools payload returned by the dev
    server: file arguments are typed "nifti_file"/"zip_file", never the
    literal "file" — see ARCHITECTURE.md."""

    def setUp(self):
        self.client = ToolServerClient("http://localhost:8000", "dev-token")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_example_tool_nifti_file_argument_is_recognized(self, mock_get):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "example_tool",
                    "arguments": {
                        "label": {"type": "str", "required": True},
                        "file": {"type": "nifti_file", "required": True},
                        "threshold": {"type": "float", "required": True},
                        "iterations": {"type": "int", "required": False},
                    },
                    "output_kind": "text",
                }
            ]
        )

        with self.assertRaises(ServerToolError) as ctx:
            # Missing the required "file" upload and "threshold" argument.
            self.client.run("example_tool", args={"label": "x"}, output_dir="/tmp")

        # Whichever is checked first, it must be a *local* validation error
        # (schema-driven), not a generic/unrelated failure.
        self.assertIn("example_tool", str(ctx.exception))

    # The real surg_mov_pred schema since the model moved fully server-side:
    # "model" is a scalar str (the *name* of a server-hosted model, picked
    # from GET /tools/{tool}/data), only "input" is still uploaded.
    _SURG_MOV_PRED_SCHEMA = [
        {
            "name": "SurgMovPred",
            "arguments": {
                "model": {"type": "str", "required": True, "server_selectable": "model"},
                "input": {"type": "zip_file", "required": True, "server_selectable": "testfile"},
            },
            "output_kind": "file",
        }
    ]

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_surg_mov_pred_sends_model_name_as_form_value(self, mock_get, mock_post):
        mock_get.return_value = _response(json_data=self._SURG_MOV_PRED_SCHEMA)
        mock_post.return_value = _response(content=_zip_bytes(), headers={"Content-Type": "application/zip"})

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            self.client.run(
                "SurgMovPred",
                args={"model": "stacking_v2.zip"},
                files={"input": __file__},
                output_dir=out_dir,
            )

        _, kwargs = mock_post.call_args
        # The model travels as a plain form value (its server-side name)...
        self.assertEqual(kwargs["data"], {"model": "stacking_v2.zip"})
        # ...and only "input" is uploaded as a file.
        self.assertEqual(set(kwargs["files"].keys()), {"input"})

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_surg_mov_pred_missing_model_name_fails_locally(self, mock_get):
        mock_get.return_value = _response(json_data=self._SURG_MOV_PRED_SCHEMA)

        with self.assertRaises(ServerToolError) as ctx:
            self.client._validate_against_schema(
                self.client.get_tool_schema("SurgMovPred"), {}, {"input": __file__}
            )
        self.assertIn("model", str(ctx.exception))

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_surg_mov_pred_model_is_not_a_file_argument(self, mock_get):
        # Uploading a local model package is no longer supported: "model" is a
        # scalar, so passing it under `files` must be rejected before any
        # network round-trip.
        mock_get.return_value = _response(json_data=self._SURG_MOV_PRED_SCHEMA)

        with self.assertRaises(ServerToolError):
            self.client._validate_against_schema(
                self.client.get_tool_schema("SurgMovPred"),
                {},
                {"model": __file__, "input": __file__},
            )


class ExampleToolRequestTest(unittest.TestCase):
    """The full request/response round-trip for `example_tool` — the tool that
    exercises everything the client has to do: a choice, a multichoice, an
    input accepting a file or a folder, and a multi-file (.zip) result.

    The schema is the server's real GET /tools entry, verbatim.
    """

    EXAMPLE_TOOL = {
        "name": "example_tool",
        "output_kind": "files",
        "arguments": {
            "label": {
                "type": "str", "types": ["str"], "required": True,
                "description": "Free-text label for this run",
                "server_selectable": None, "choices": None,
            },
            "input": {
                "type": "csv_file", "types": ["csv_file", "folder"], "required": True,
                "description": "A single .csv file, or a folder of .csv/.xlsx/.ods files sent as a .zip archive",
                "server_selectable": None, "choices": None,
            },
            "threshold": {
                "type": "float", "types": ["float"], "required": True,
                "description": "Numeric threshold parameter",
                "server_selectable": None, "choices": None,
            },
            "iterations": {
                "type": "int", "types": ["int"], "required": False,
                "description": "Optional number of iterations",
                "server_selectable": None, "choices": None,
            },
            "outputs": {
                "type": "multichoice", "types": ["multichoice"], "required": False,
                "description": "Which result files to produce",
                "server_selectable": None,
                "choices": {"summary": True, "preview": True, "columns": False},
            },
            "preview_format": {
                "type": "choice", "types": ["choice"], "required": False,
                "description": "Format of the preview file",
                "server_selectable": None,
                "choices": {"csv": True, "json": False},
            },
        },
    }

    def setUp(self):
        self.client = ToolServerClient("http://localhost:8000", "dev-token")

    def _args(self, **overrides):
        args = {
            "label": "test",
            "threshold": 1.0,
            "preview_format": "json",
            "outputs": {"summary": True, "preview": True, "columns": False},
        }
        args.update(overrides)
        return args

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_form_fields_match_the_contract(self, mock_get, mock_post):
        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])
        mock_post.return_value = _response(
            content=_zip_bytes(), headers={"Content-Type": "application/zip"}
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            self.client.run("example_tool", args=self._args(), files={"input": __file__}, output_dir=out_dir)

        _, kwargs = mock_post.call_args
        data = kwargs["data"]
        # A "choice" travels as the option name, in clear.
        self.assertEqual(data["preview_format"], "json")
        # A "multichoice" travels as the complete dict, as JSON.
        self.assertEqual(json.loads(data["outputs"]), {"summary": True, "preview": True, "columns": False})
        self.assertEqual(data["label"], "test")
        # Only the file argument is uploaded.
        self.assertEqual(set(kwargs["files"]), {"input"})

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_a_zipped_folder_is_uploaded_under_the_same_argument_name(self, mock_get, mock_post):
        # The client zips a folder selection before sending; the server sees an
        # ordinary .zip under "input" and unpacks it.
        import tempfile

        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])
        mock_post.return_value = _response(content=_zip_bytes(), headers={"Content-Type": "application/zip"})

        with tempfile.TemporaryDirectory() as work_dir:
            archive = os.path.join(work_dir, "example_tool_input.zip")
            with open(archive, "wb") as fh:
                fh.write(b"PK\x03\x04")
            self.client.run("example_tool", args=self._args(), files={"input": archive}, output_dir=work_dir)

        _, kwargs = mock_post.call_args
        filename, _handle = kwargs["files"]["input"]
        self.assertEqual(filename, "example_tool_input.zip")

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_files_output_kind_is_saved_under_its_real_name(self, mock_get, mock_post):
        import tempfile

        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])
        mock_post.return_value = _response(
            content=_zip_bytes(),
            headers={
                "Content-Type": "application/zip",
                "Content-Disposition": 'attachment; filename="example_tool_results.zip"',
            },
        )

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run(
                "example_tool", args=self._args(), files={"input": __file__}, output_dir=out_dir
            )

        self.assertEqual(result.kind, "file")
        # A .zip of several results: base_widget's "save_as" handling unpacks
        # it into the output folder (see slicer_io.is_extractable_archive).
        self.assertEqual(os.path.basename(result.path), "example_tool_results.zip")

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_unknown_option_422_is_shown_verbatim(self, mock_get, mock_post):
        # No client-side fallback for an out-of-list value: the server's own
        # message names the offending option and lists the valid ones.
        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])
        detail = "Argument 'preview_format': unknown option 'xml'. Expected one of: csv, json"
        mock_post.return_value = _response(status_code=422, json_data={"detail": detail})

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run(
                "example_tool",
                args=self._args(preview_format="xml"),
                files={"input": __file__},
                output_dir="/tmp",
            )

        self.assertEqual(str(ctx.exception), detail)
        self.assertEqual(ctx.exception.status_code, 422)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_413_reports_the_server_s_actual_limit(self, mock_get, mock_post):
        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])
        mock_post.return_value = _response(
            status_code=413, json_data={"detail": "File exceeds the 500 MB limit."}
        )

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("example_tool", args=self._args(), files={"input": __file__}, output_dir="/tmp")

        self.assertEqual(str(ctx.exception), "File exceeds the 500 MB limit.")
        self.assertEqual(ctx.exception.status_code, 413)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_400_reports_the_allowed_extensions(self, mock_get, mock_post):
        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])
        detail = "Unsupported file extension for 'input'. Allowed: ('.csv', '.zip')"
        mock_post.return_value = _response(status_code=400, json_data={"detail": detail})

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("example_tool", args=self._args(), files={"input": __file__}, output_dir="/tmp")

        self.assertEqual(str(ctx.exception), detail)
        self.assertEqual(ctx.exception.status_code, 400)

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_401_reports_the_server_message(self, mock_get, mock_post):
        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])
        mock_post.return_value = _response(status_code=401, json_data={"detail": "Invalid token."})

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("example_tool", args=self._args(), files={"input": __file__}, output_dir="/tmp")

        self.assertEqual(str(ctx.exception), "Invalid token.")

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_missing_input_file_fails_locally(self, mock_get):
        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("example_tool", args=self._args(), files={}, output_dir="/tmp")

        self.assertIn("input", str(ctx.exception))

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_optional_choice_arguments_may_be_omitted(self, mock_get):
        # Omitting a multichoice entirely is what applies the server's declared
        # defaults — it must not be forced into the payload.
        mock_get.return_value = _response(json_data=[self.EXAMPLE_TOOL])

        self.client._validate_against_schema(
            self.client.get_tool_schema("example_tool"),
            {"label": "test", "threshold": 1.0},
            {"input": __file__},
        )


class DownloadFileTest(unittest.TestCase):
    """download_file: the GitHub test-data fetch base_widget drives. Not part
    of ToolServerClient on purpose (no server URL, no token) but tested here
    like the rest of the module, requests mocked."""

    URL = "https://github.com/example/releases/download/v1/MG_test_scan.nii.gz"

    def setUp(self):
        self.work = tempfile.mkdtemp(prefix="download_test_")
        self.addCleanup(shutil.rmtree, self.work, True)
        self.destination = os.path.join(self.work, "MG_test_scan.nii.gz")

    def _streaming_response(self, chunks, headers=None, status=200):
        response = mock.MagicMock()
        response.status_code = status
        response.headers = headers or {}
        response.iter_content = lambda chunk_size: iter(chunks)
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        if status >= 400:
            response.raise_for_status.side_effect = requests.HTTPError(f"{status} error")
        else:
            response.raise_for_status.return_value = None
        return response

    def test_streams_the_body_to_the_destination(self):
        response = self._streaming_response([b"abc", b"def"])

        with mock.patch.object(requests, "get", return_value=response) as get:
            result = download_file(self.URL, self.destination)

        self.assertEqual(result, self.destination)
        with open(self.destination, "rb") as handle:
            self.assertEqual(handle.read(), b"abcdef")
        # stream=True is what keeps a 100 MB scan out of Slicer's RAM.
        self.assertTrue(get.call_args.kwargs.get("stream"))
        self.assertEqual(get.call_args.args[0], self.URL)

    def test_progress_reports_percentages_from_content_length(self):
        response = self._streaming_response(
            [b"a" * 512, b"b" * 512], headers={"Content-Length": "1024"}
        )
        messages = []

        with mock.patch.object(requests, "get", return_value=response):
            download_file(self.URL, self.destination, progress_cb=messages.append)

        self.assertEqual(len(messages), 2)
        self.assertIn("(50%)", messages[0])
        self.assertIn("(100%)", messages[1])
        # The label is the file being fetched, not the tool-run wording.
        self.assertIn("MG_test_scan.nii.gz", messages[0])

    def test_an_http_error_raises_and_writes_nothing(self):
        response = self._streaming_response([], status=404)

        with mock.patch.object(requests, "get", return_value=response):
            with self.assertRaises(requests.HTTPError):
                download_file(self.URL, self.destination)

        self.assertFalse(os.path.exists(self.destination))


if __name__ == "__main__":
    unittest.main()
