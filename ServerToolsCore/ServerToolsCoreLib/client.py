"""The only class in the extension that speaks HTTP to the tool server.

Imports neither `slicer` nor `qt` — see ARCHITECTURE.md dependency rule. This
makes it testable in plain CI with `requests` mocked out (see
ServerToolsCore/Testing/Python/test_client.py).
"""

import logging
import mimetypes
import os
import re
from dataclasses import dataclass
from typing import Callable, Optional

import requests

from .errors import ServerToolError, error_for_status

logger = logging.getLogger("ServerToolsCore.client")

# A health check feeds the status banner on every enter(); it must never hang
# for as long as a real tool run (self._timeout, up to 600s).
_HEALTH_CHECK_TIMEOUT = 10

# get_tool_schema() is called synchronously from a module's setup() (building
# the GUI needs the schema before the first paint) — a slow/unreachable server
# must not be able to freeze Slicer for up to 600s just to open a module.
_TOOLS_FETCH_TIMEOUT = 15

_CONTENT_DISPOSITION_FILENAME_RE = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?')
_SERVER_MESSAGE_MAX_LEN = 500


def is_file_type(type_name: str) -> bool:
    """Whether a schema argument `type` denotes a file upload.

    The server is not limited to a generic "file" type — it can (and does,
    e.g. "nifti_file", "zip_file") use more specific type names to hint at
    what kind of file is expected. Treating any "..._file" type (plus the
    literal "file", for tools that don't bother being specific) as a file
    argument means a new file-ish type the server introduces later needs no
    client-side code change — the whole point of a schema-driven client.
    """
    return type_name == "file" or type_name.endswith("_file")


@dataclass
class ToolResult:
    """Uniform result regardless of output_kind."""

    kind: str  # "text" | "file"
    text: Optional[str] = None
    path: Optional[str] = None


class ToolServerClient:
    def __init__(self, server_url, token, verify_tls=True, timeout=600):
        self._server_url = server_url.rstrip("/")
        self._token = token
        self._verify_tls = verify_tls
        self._timeout = timeout
        self._tools_cache = None

    # ------------------------------------------------------------------
    # Live (re)configuration — e.g. from a user-facing settings panel
    # ------------------------------------------------------------------

    @property
    def server_url(self) -> str:
        return self._server_url

    @property
    def token(self) -> str:
        return self._token

    @property
    def verify_tls(self) -> bool:
        return self._verify_tls

    @property
    def timeout(self) -> int:
        return self._timeout

    def configure(self, server_url=None, token=None, verify_tls=None, timeout=None) -> None:
        """Update connection settings on the already-constructed singleton in
        place, so every module sharing get_client() sees the change without a
        Slicer restart. Drops the cached /tools schema unconditionally — it
        may belong to a different server entirely once any of these change.
        """
        if server_url is not None:
            self._server_url = server_url.rstrip("/")
        if token is not None:
            self._token = token
        if verify_tls is not None:
            self._verify_tls = verify_tls
        if timeout is not None:
            self._timeout = timeout
        self._tools_cache = None

    # ------------------------------------------------------------------
    # Schema discovery
    # ------------------------------------------------------------------

    def health(self) -> bool:
        try:
            response = requests.get(
                f"{self._server_url}/health", timeout=_HEALTH_CHECK_TIMEOUT, verify=self._verify_tls
            )
            return bool(response.ok and response.json().get("status") == "ok")
        except (requests.RequestException, ValueError) as exc:
            logger.debug("Health check failed: %s", exc)
            return False

    def list_tools(self, force_refresh: bool = False) -> dict:
        """Return {tool_name: schema}, cached after the first call."""
        if self._tools_cache is None or force_refresh:
            self._tools_cache = self._fetch_tools()
        return self._tools_cache

    def get_tool_schema(self, tool_name: str) -> dict:
        tools = self.list_tools()
        if tool_name not in tools:
            available = ", ".join(sorted(tools)) or "none"
            raise ServerToolError(f"Unknown tool '{tool_name}'. Available: {available}")
        return tools[tool_name]

    def list_tool_data(self, tool_name: str) -> dict:
        """Return {"models": [...], "testfiles": [...]} — the file names hosted
        on the server for this tool (GET /tools/{tool}/data, Bearer-protected).

        This is what lets a server_selectable argument (e.g. SurgMovPred's
        "model") be offered as a dropdown of server-side choices instead of a
        local file picker. Not cached: called once per module setup(), and the
        server-side list can change independently of the /tools schema.
        """
        try:
            response = requests.get(
                f"{self._server_url}/tools/{tool_name}/data",
                headers={"Authorization": f"Bearer {self._token}"},
                timeout=_TOOLS_FETCH_TIMEOUT,
                verify=self._verify_tls,
            )
        except requests.RequestException as exc:
            raise ServerToolError(f"Could not reach the tool server: {exc}") from exc

        if not response.ok:
            raise error_for_status(response.status_code, self._server_message(response))

        try:
            data = response.json()
        except ValueError as exc:
            raise ServerToolError(f"Malformed response from the tool server: {exc}") from exc

        logger.info(
            "GET %s/tools/%s/data -> %d model(s), %d testfile(s)",
            self._server_url, tool_name, len(data.get("models", [])), len(data.get("testfiles", [])),
        )
        return {"models": data.get("models", []), "testfiles": data.get("testfiles", [])}

    def _fetch_tools(self) -> dict:
        try:
            response = requests.get(
                f"{self._server_url}/tools", timeout=_TOOLS_FETCH_TIMEOUT, verify=self._verify_tls
            )
        except requests.RequestException as exc:
            raise ServerToolError(f"Could not reach the tool server: {exc}") from exc

        if not response.ok:
            raise error_for_status(response.status_code, self._server_message(response))

        try:
            tools = response.json()
        except ValueError as exc:
            raise ServerToolError(f"Malformed response from the tool server: {exc}") from exc

        by_name = {tool["name"]: tool for tool in tools}
        logger.info("GET %s/tools -> %d tool(s): %s", self._server_url, len(by_name), sorted(by_name.keys()))
        return by_name

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(
        self,
        tool_name: str,
        args: Optional[dict] = None,
        files: Optional[dict] = None,
        output_dir: Optional[str] = None,
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> ToolResult:
        """`files`: {schema_argument_name: local_file_path}, one entry per
        `type: "file"` argument you're providing. Each is uploaded as its own
        multipart field named after its schema argument — a tool can declare
        several independent file arguments (e.g. SurgMovPred's "model" +
        "input"); there is no single reserved "file" key."""
        args = args or {}
        files = files or {}
        schema = self.get_tool_schema(tool_name)
        self._validate_against_schema(schema, args, files)

        if progress_cb:
            progress_cb(f"Sending '{tool_name}' request...")

        headers = {"Authorization": f"Bearer {self._token}"}
        data = self._stringify(args)

        # Debug visibility only: argument/file *names*, never the token or the
        # argument/file contents. Silent unless the caller has raised this
        # logger's level (see ARCHITECTURE.md "How to inspect a request").
        logger.debug(
            "POST %s/run/%s | arg keys=%s | file args=%s",
            self._server_url,
            tool_name,
            sorted(data.keys()),
            {name: os.path.basename(path) for name, path in files.items()},
        )

        file_handles = []
        try:
            files_payload = {}
            for arg_name, path in files.items():
                file_handle = open(path, "rb")
                file_handles.append(file_handle)
                # The filename (with extension) must travel with the upload: the
                # server validates extensions (.nii/.nii.gz/...) from it. Without
                # it, requests defaults to a bare filename and every upload with
                # an extension check fails server-side.
                files_payload[arg_name] = (os.path.basename(path), file_handle)

            try:
                response = requests.post(
                    f"{self._server_url}/run/{tool_name}",
                    headers=headers,
                    data=data,
                    files=files_payload or None,
                    timeout=self._timeout,
                    verify=self._verify_tls,
                )
            except requests.RequestException as exc:
                raise ServerToolError(f"Network error while calling '{tool_name}': {exc}") from exc
        finally:
            for file_handle in file_handles:
                file_handle.close()

        logger.debug(
            "Response from %s: status=%s content-type=%s",
            tool_name,
            response.status_code,
            response.headers.get("Content-Type"),
        )

        if progress_cb:
            progress_cb("Processing response...")

        return self._build_result(tool_name, response, schema, output_dir)

    def _build_result(self, tool_name: str, response, schema: dict, output_dir: Optional[str]) -> ToolResult:
        if not response.ok:
            raise error_for_status(response.status_code, self._server_message(response))

        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            try:
                payload = response.json()
            except ValueError as exc:
                raise ServerToolError(f"Malformed response from the tool server: {exc}") from exc
            return ToolResult(kind="text", text=payload.get("result"))

        if not output_dir:
            raise ServerToolError("An output directory is required to save the returned file.")

        os.makedirs(output_dir, exist_ok=True)
        dest_path = os.path.join(output_dir, self._result_filename(tool_name, response, schema, content_type))
        with open(dest_path, "wb") as fh:
            fh.write(response.content)
        return ToolResult(kind="file", path=dest_path)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _result_filename(tool_name: str, response, schema: dict, content_type: str) -> str:
        """Prefer the server-provided filename (Content-Disposition); otherwise
        derive one from the schema's output_kind so file loaders that key off the
        extension (e.g. slicer.util.loadSegmentation expects .nii/.nii.gz) work."""
        content_disposition = response.headers.get("Content-Disposition", "")
        match = _CONTENT_DISPOSITION_FILENAME_RE.search(content_disposition)
        if match:
            return match.group(1).strip()

        if schema.get("output_kind") == "segmentation":
            extension = ".nii.gz"
        else:
            # Mirror the server's own mimetypes.guess_type(): derive a real
            # extension from Content-Type instead of a generic .bin/.gz guess.
            # This keeps extension-based decisions downstream (e.g.
            # slicer_io.is_extractable_archive) correct even without a
            # Content-Disposition header.
            bare_content_type = content_type.split(";", 1)[0].strip()
            extension = mimetypes.guess_extension(bare_content_type) if bare_content_type else None
            if not extension:
                extension = ".gz" if "gzip" in content_type else ".bin"
        return f"{tool_name}_result{extension}"

    @staticmethod
    def _server_message(response) -> Optional[str]:
        """For 400/422 the server's own message must be propagated verbatim. Try
        JSON's "detail"/"message" first (FastAPI-style errors), then fall back to
        the raw response body so a plain-text error is never silently dropped."""
        try:
            payload = response.json()
        except ValueError:
            payload = None

        if isinstance(payload, dict):
            message = payload.get("detail") or payload.get("message")
            if message:
                return message

        text = (getattr(response, "text", None) or "").strip()
        if not text:
            return None
        return text[:_SERVER_MESSAGE_MAX_LEN]

    @staticmethod
    def _stringify(args: dict) -> dict:
        """Every scalar becomes a string; the server does the type coercion."""
        stringified = {}
        for key, value in args.items():
            if isinstance(value, bool):
                stringified[key] = "true" if value else "false"
            else:
                stringified[key] = str(value)
        return stringified

    @staticmethod
    def _validate_against_schema(schema: dict, args: dict, files: dict) -> None:
        """Catch obvious mistakes before paying a network round-trip.

        Mirrors the server's own checks (unexpected/missing arguments); a real
        request can still fail server-side (e.g. disallowed file extension).
        """
        tool_name = schema.get("name", "?")
        arguments = schema.get("arguments", {})

        for name in args:
            if name not in arguments:
                raise ServerToolError(f"Unexpected argument '{name}' for tool '{tool_name}'.")

        for name in files:
            if name not in arguments:
                raise ServerToolError(f"Unexpected file argument '{name}' for tool '{tool_name}'.")
            if not is_file_type(arguments[name].get("type", "")):
                raise ServerToolError(f"Argument '{name}' for tool '{tool_name}' is not a file argument.")

        for name, spec in arguments.items():
            if is_file_type(spec.get("type", "")):
                if spec.get("required") and name not in files:
                    raise ServerToolError(f"Missing required file argument '{name}' for tool '{tool_name}'.")
            elif spec.get("required") and name not in args:
                raise ServerToolError(f"Missing required argument '{name}' for tool '{tool_name}'.")
