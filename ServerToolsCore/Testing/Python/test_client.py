"""Unit tests for ServerToolsCoreLib.client — run outside Slicer, requests mocked.

Usage:
    python3 -m unittest ServerToolsCore/Testing/Python/test_client.py
"""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import requests

from ServerToolsCoreLib.client import (
    ToolResult,
    ToolServerClient,
    _HEALTH_CHECK_TIMEOUT,
    _TOOLS_FETCH_TIMEOUT,
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
    if json_data is not None:
        response.json.return_value = json_data
    else:
        response.json.side_effect = ValueError("no json body")
    return response


class ToolServerClientTest(unittest.TestCase):
    def setUp(self):
        self.client = ToolServerClient("https://example.org/", "secret-token")

    def test_server_url_is_normalized(self):
        self.assertEqual(self.client._server_url, "https://example.org")

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

    # -- multi-file tools (e.g. real surg_mov_pred: "model" + "input") ------

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_rejects_when_only_one_of_two_required_files_given(self, mock_get):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "surg_mov_pred",
                    "arguments": {
                        "model": {"type": "zip_file", "required": True},
                        "input": {"type": "zip_file", "required": True},
                    },
                    "output_kind": "file",
                }
            ]
        )

        with self.assertRaises(ServerToolError) as ctx:
            self.client.run("surg_mov_pred", args={}, files={"input": __file__}, output_dir="/tmp")

        self.assertIn("model", str(ctx.exception))

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_run_sends_each_file_under_its_own_argument_name(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "surg_mov_pred",
                    "arguments": {
                        "model": {"type": "zip_file", "required": True},
                        "input": {"type": "zip_file", "required": True},
                    },
                    "output_kind": "file",
                }
            ]
        )
        mock_post.return_value = _response(
            content=b"zip-bytes", headers={"Content-Type": "application/zip"}
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            self.client.run(
                "surg_mov_pred", args={}, files={"model": __file__, "input": __file__}, output_dir=out_dir
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
            json_data=[{"name": "surg_mov_pred", "arguments": {}, "output_kind": "file"}]
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
            result = self.client.run("surg_mov_pred", args={}, output_dir=out_dir)

        self.assertEqual(os.path.basename(result.path), "predictions_outputs.xlsx")
        self.assertFalse(result.path.lower().endswith(".zip"))

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_result_filename_falls_back_to_mimetype_extension_without_content_disposition(self, mock_get, mock_post):
        # No Content-Disposition this time: the extension must still come from
        # a real MIME lookup (mirroring the server's own mimetypes.guess_type),
        # not the generic .bin/.gz guess.
        mock_get.return_value = _response(
            json_data=[{"name": "surg_mov_pred", "arguments": {}, "output_kind": "file"}]
        )
        mock_post.return_value = _response(
            content=b"csv,data",
            headers={"Content-Type": "text/csv"},
        )

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            result = self.client.run("surg_mov_pred", args={}, output_dir=out_dir)

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

    @mock.patch("ServerToolsCoreLib.client.requests.post")
    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_surg_mov_pred_zip_file_arguments_both_required(self, mock_get, mock_post):
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "surg_mov_pred",
                    "arguments": {
                        "model": {"type": "zip_file", "required": True},
                        "input": {"type": "zip_file", "required": True},
                    },
                    "output_kind": "file",
                }
            ]
        )
        mock_post.return_value = _response(content=b"zip", headers={"Content-Type": "application/zip"})

        import tempfile

        with tempfile.TemporaryDirectory() as out_dir:
            # Both files provided: must pass validation and reach requests.post.
            self.client.run(
                "surg_mov_pred", args={}, files={"model": __file__, "input": __file__}, output_dir=out_dir
            )
        self.assertTrue(mock_post.called)

    @mock.patch("ServerToolsCoreLib.client.requests.get")
    def test_surg_mov_pred_does_not_leak_into_scalar_args(self, mock_get):
        # Before is_file_type(), "model"/"input" (type "zip_file") were
        # wrongly treated as required *scalar* arguments, since they don't
        # equal the literal string "file" — this must no longer happen.
        mock_get.return_value = _response(
            json_data=[
                {
                    "name": "surg_mov_pred",
                    "arguments": {
                        "model": {"type": "zip_file", "required": True},
                        "input": {"type": "zip_file", "required": True},
                    },
                    "output_kind": "file",
                }
            ]
        )
        schema = self.client.get_tool_schema("surg_mov_pred")

        # Supplying both as files (not as scalar args) must satisfy validation.
        try:
            self.client._validate_against_schema(schema, {}, {"model": __file__, "input": __file__})
        except ServerToolError as exc:
            self.fail(f"zip_file arguments must be satisfied via `files`, not `args`: {exc}")


if __name__ == "__main__":
    unittest.main()
