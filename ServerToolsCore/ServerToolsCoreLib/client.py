"""The only class in the extension that speaks HTTP to the tool server.

Imports neither `slicer` nor `qt` — see ARCHITECTURE.md dependency rule. This
makes it testable in plain CI with `requests` mocked out (see
ServerToolsCore/Testing/Python/test_client.py).
"""

import json
import logging
import mimetypes
import os
import re
import zipfile
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

# A result archive can weigh hundreds of MB (AMASSS: one .nii.gz + .vtk per
# structure and per scan). It is streamed to disk in chunks of this size, so
# the whole body is never held in Slicer's RAM.
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024


def _download_message(received: int, expected: Optional[int]) -> str:
    """"Downloading results... 8.2 / 14.1 MB (58%)", or without the total when
    the server sent no usable Content-Length."""
    received_mb = received / (1024 * 1024)
    if not expected:
        return f"Downloading results... {received_mb:.1f} MB"
    expected_mb = expected / (1024 * 1024)
    percent = min(100, round(100 * received / expected))
    return f"Downloading results... {received_mb:.1f} / {expected_mb:.1f} MB ({percent}%)"


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


# Fallback only. The server publishes each file type's extensions in its
# `types`' company (see file_extensions_for), which is the single source of
# truth; this table is what a *pre-`extensions`* server leaves us guessing
# with, and it is a copy of that server's own FILE_TYPES — the kind of
# duplication that drifts. It once did: "volume_or_zip_file" was missing here
# and derived as ".volume_or_zip", a file dialog matching nothing.
#
# Do not grow it for a new type. Publish the type's extensions server-side
# instead; anything not listed still falls back to the obvious ".<x>"
# ("csv_file" -> ".csv") when the name spells one out.
_FILE_TYPE_EXTENSIONS = {
    "file": (),  # deliberately unrestricted: the generic type accepts anything
    "nifti_file": (".nii", ".nii.gz"),
    "zip_file": (".zip",),
    # A medical volume or a zip of a folder of them (AMASSS's `input`): the
    # type name doesn't spell out an extension, so it needs an entry here.
    "volume_or_zip_file": (".nii", ".nii.gz", ".nrrd", ".nrrd.gz", ".gipl", ".gipl.gz", ".zip"),
}

# The one non-file type that may appear alongside file types in `types`: it is
# a *local* selection kind, not something HTTP can carry — a folder is zipped
# client-side and uploaded as the .zip the server then unpacks.
FOLDER_TYPE = "folder"


def _guessed_extension(type_name: str) -> tuple:
    """The extension a "<x>_file" type name spells out, when it spells one.

    `"csv_file"` -> `(".csv",)`. But a compound name like
    `"volume_or_zip_file"` names a *set* of formats, not an extension: guessing
    `".volume_or_zip"` there produces a file dialog that matches nothing, which
    is worse than not filtering at all. Such a name (recognisable by the
    underscores left once "_file" is stripped) that has no entry in
    _FILE_TYPE_EXTENSIONS falls back to no restriction, so a new one the server
    introduces degrades to an unfiltered picker instead of an empty one.
    """
    if not type_name.endswith("_file"):
        return ()
    stem = type_name[: -len("_file")]
    return () if "_" in stem else (f".{stem}",)


def argument_types(spec: dict) -> list:
    """Every type a schema argument accepts.

    The server sends both a single `type` (the primary/first one) and the full
    `types` list; an argument accepting several — e.g. example_tool's `input`:
    `["csv_file", "folder"]` — is only fully described by the latter. Falls
    back to `[type]` so a schema predating the `types` field still works.
    """
    types = spec.get("types")
    if types:
        return list(types)
    type_name = spec.get("type")
    return [type_name] if type_name else []


def accepts_folder(spec: dict) -> bool:
    """Whether the user may pick a whole folder for this argument (which the
    client then zips before uploading — see slicer_io.zip_folder)."""
    return FOLDER_TYPE in argument_types(spec)


def file_extensions_for(spec: dict) -> tuple:
    """The extensions a file picker should offer for this argument —
    `["csv_file", "folder"]` gives `(".csv",)`.

    Read from the schema's own `extensions` (`{type name: [extension, ...]}`,
    the server's FILE_TYPES table published alongside `types`), so the client
    holds no copy of it. Only the *file* types count: `"folder"`'s extensions
    say what a zipped folder may be uploaded as, not what a file picker should
    show.

    A server that predates the field leaves it out, and each type then falls
    back to _FILE_TYPE_EXTENSIONS or to what its name spells out.

    An empty tuple means "don't restrict": either the argument declares the
    generic "file" type, or it accepts no file type at all (folder only).
    """
    published = spec.get("extensions") or {}
    extensions = []
    for type_name in argument_types(spec):
        if not is_file_type(type_name):
            continue
        known = published.get(type_name, _FILE_TYPE_EXTENSIONS.get(type_name))
        if known is None:
            known = _guessed_extension(type_name)
        if not known:
            # Either the generic "file", or a type the server declines to
            # restrict: anything goes, so no filter at all.
            return ()
        extensions.extend(extension for extension in known if extension not in extensions)
    return tuple(extensions)


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

    def get_tool_schema(self, tool_name: str, force_refresh: bool = False) -> dict:
        """`force_refresh` re-fetches /tools instead of trusting the cache —
        used when retrying after a failure, where the cached list may be the
        very reason the tool wasn't found."""
        tools = self.list_tools(force_refresh=force_refresh)
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
                # stream=True: the body is NOT downloaded here but inside
                # _build_result, chunk by chunk straight to disk. Without it,
                # requests buffers the entire result archive in RAM before a
                # single byte can be written -- the larger a run's output, the
                # closer that gets to taking Slicer down with it. The read
                # timeout then applies between chunks, not to the whole
                # download, so a big-but-flowing response can never time out
                # merely for being big.
                response = requests.post(
                    f"{self._server_url}/run/{tool_name}",
                    headers=headers,
                    data=data,
                    files=files_payload or None,
                    timeout=self._timeout,
                    verify=self._verify_tls,
                    stream=True,
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

        return self._build_result(tool_name, response, schema, output_dir, progress_cb)

    def _build_result(
        self,
        tool_name: str,
        response,
        schema: dict,
        output_dir: Optional[str],
        progress_cb: Optional[Callable[[str], None]] = None,
    ) -> ToolResult:
        # run() sends the request with stream=True, so the body has not been
        # read yet: .json()/.text below consume it for the small responses,
        # the iter_content loop consumes it for file results, and close() in
        # the finally releases the connection on every path.
        try:
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
            dest_path = os.path.join(
                output_dir, self._result_filename(tool_name, response, schema, content_type)
            )
            expected_bytes = self._expected_length(response)
            received = 0
            with open(dest_path, "wb") as fh:
                for chunk in response.iter_content(_DOWNLOAD_CHUNK_BYTES):
                    fh.write(chunk)
                    received += len(chunk)
                    if progress_cb:
                        progress_cb(_download_message(received, expected_bytes))
            self._verify_download(tool_name, response, dest_path, received)

            # INFO on purpose (the request-shape logs above are DEBUG): this
            # is the one line that decides, after the fact, whether a
            # missing-results report is a transfer problem or a server one.
            # Only sizes and headers -- never the file's contents.
            logger.info(
                "POST %s/run/%s -> %d byte(s) saved to %s (Content-Type: %s, Content-Disposition: %s)",
                self._server_url,
                tool_name,
                received,
                dest_path,
                content_type or "<none>",
                response.headers.get("Content-Disposition") or "<none>",
            )
            return ToolResult(kind="file", path=dest_path)
        finally:
            response.close()

    @staticmethod
    def _expected_length(response) -> Optional[int]:
        """The download's total size, when it can be trusted.

        None whenever the body is transfer-compressed: Content-Length then
        counts wire bytes while what lands on disk is the decompressed stream,
        so using it would report a progress percentage running past 100.
        """
        if response.headers.get("Content-Encoding"):
            return None
        raw = response.headers.get("Content-Length")
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    @classmethod
    def _verify_download(cls, tool_name: str, response, dest_path: str, received: int) -> None:
        """A file result must arrive complete or fail loudly, whatever its size.

        Without this, a connection dropped mid-body leaves a truncated file on
        disk; for a .zip the base widget then unpacks whatever central
        directory survives, silently delivering a SUBSET of the results -- the
        worst possible failure for medical data. The partial file is removed
        before raising, so no later step can pick it up by accident.
        """
        expected_bytes = cls._expected_length(response)
        if expected_bytes is not None and received != expected_bytes:
            os.remove(dest_path)
            raise ServerToolError(
                f"Truncated result from '{tool_name}': received {received} of "
                f"{expected_bytes} bytes. Nothing was kept; run the tool again."
            )
        if dest_path.lower().endswith(".zip"):
            # CRC-check every member: catches corruption that a matching byte
            # count cannot (and truncation too, when the server never sent a
            # Content-Length). Reads the archive once from local disk --
            # seconds, next to an inference measured in minutes.
            try:
                with zipfile.ZipFile(dest_path) as archive:
                    corrupt = archive.testzip()
            except zipfile.BadZipFile as exc:
                os.remove(dest_path)
                raise ServerToolError(
                    f"The result archive from '{tool_name}' is unreadable "
                    f"(incomplete transfer?): {exc}. Nothing was kept; run the tool again."
                ) from exc
            if corrupt is not None:
                os.remove(dest_path)
                raise ServerToolError(
                    f"The result archive from '{tool_name}' failed its integrity check "
                    f"at '{corrupt}'. Nothing was kept; run the tool again."
                )

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
        """Every scalar becomes a string; the server does the type coercion.

        A "multichoice" argument arrives here as the *complete* {option:
        checked} dict (see formgen.MultiChoiceGroup) and is sent as JSON. Two
        things about that are load-bearing:

        - The whole dict travels, unchecked options included. Server-side, what
          is sent *is* the selection: an option left out counts as unchecked
          whatever its declared default, and omitting the argument entirely is
          what applies the defaults. So "everything unchecked" and "argument
          absent" are different requests, and only the real state of the boxes
          can tell them apart.
        - JSON, not the `a,b` shortcut. The server also accepts a
          comma-separated list of the checked options, but that spelling is for
          curl: it breaks the moment an option name contains a comma.
        """
        stringified = {}
        for key, value in args.items():
            if isinstance(value, bool):
                stringified[key] = "true" if value else "false"
            elif isinstance(value, dict):
                stringified[key] = json.dumps(value)
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
                # A `server_selectable` file argument has two valid shapes: an
                # upload, or the NAME of a file the server hosts, sent as a
                # plain form value under the same field name. Requiring an
                # upload here would reject the second — the very shape that
                # keeps a hosted test cohort from travelling.
                satisfied = name in files or (spec.get("server_selectable") and name in args)
                if spec.get("required") and not satisfied:
                    raise ServerToolError(f"Missing required file argument '{name}' for tool '{tool_name}'.")
            elif spec.get("required") and name not in args:
                raise ServerToolError(f"Missing required argument '{name}' for tool '{tool_name}'.")
