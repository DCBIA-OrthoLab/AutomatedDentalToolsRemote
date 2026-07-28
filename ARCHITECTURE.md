# Architecture: client/server tool infrastructure

This describes `ServerToolsCore`, the shared infrastructure that lets a Slicer
module become a thin GUI over a tool exposed by the remote tool server, and
`SurgMovPred`, the first module rebuilt on top of it. Read this before adding
or touching either.

## Goal

Move computation off the Slicer interpreter and onto a server. Slicer modules
stop containing business logic, HTTP calls, threading, or CSS; they declare
*what* tool they call and *how* its input/output map onto the Slicer scene,
and inherit everything else.

## Directory layout

```
SlicerAutomatedDentalTools/
├── CMakeLists.txt                          # add_subdirectory for each module below
├── ARCHITECTURE.md                         # this file
├── ServerToolsCore/                        # hidden scripted module, no GUI
│   ├── CMakeLists.txt
│   ├── ServerToolsCore.py                  # ScriptedLoadableModule shell, parent.hidden = True
│   │                                        # (also applies saved settings on Slicer startup)
│   ├── Testing/Python/test_client.py       # plain unittest, requests mocked, no Slicer needed
│   ├── Testing/Python/test_formgen.py      # plain unittest, qt/ctk/slicer stubbed, no Slicer needed
│   ├── Testing/Python/qt_stubs.py          # the stand-ins test_formgen runs against
│   └── ServerToolsCoreLib/                 # the importable Python package
│       ├── __init__.py                     # get_client() + ToolServerClient/ToolResult/ServerToolError
│       ├── config.py                       # SERVER_URL, API_TOKEN, VERIFY_TLS, TIMEOUT (compiled-in defaults)
│       ├── client.py                       # ToolServerClient — the only class that speaks HTTP
│       ├── errors.py                       # ServerToolError + HTTP status → message mapping
│       ├── slicer_io.py                    # TempWorkspace, node export, zip/unzip, result loading
│       ├── design.py                       # theme tokens, dark/light detection, styled-widget factories
│       ├── formgen.py                      # /tools schema → Qt widgets, and back
│       ├── worker.py                       # off-UI-thread execution (BackgroundJob)
│       ├── base_widget.py                  # ServerToolWidgetBase: all the Slicer boilerplate
│       └── settings_qt.py                  # QSettings-backed override of config.py's defaults
├── ServerToolsSettings/                    # visible module: edit server URL/API key/TLS/timeout
│   ├── CMakeLists.txt
│   └── ServerToolsSettings.py
├── SurgMovPred/
│   ├── CMakeLists.txt
│   └── SurgMovPred.py                      # ~35 lines, declarative
├── ExampleTool/                            # reference client for the server's example_tool
│   ├── CMakeLists.txt
│   └── ExampleTool.py                      # ~35 lines, declarative
└── SurgMovPred_CLI/                        # left in place but unwired (see "SurgMovPred_CLI" below)
```

### Deviation from a literal reading of the brief

The task brief sketched the tree with everything nested under a top-level
`SlicerServerTools/` wrapper folder. That was a diagram, not a literal
instruction — every existing module in this repository (`AMASSS`, `ALI`,
`SurgMovPred`, ...) lives flat at the repository root and is registered
directly from the root `CMakeLists.txt`. `ServerToolsCore/` and `SurgMovPred/`
follow that convention instead of introducing a new nesting level nothing else
in the repo uses.

## Dependency rule — enforced, not just documented

> `client.py` and `errors.py` import neither `slicer` nor `qt`.
> `base_widget.py`, `formgen.py`, `design.py`, `slicer_io.py`, `worker.py`
> import neither `requests` nor anything HTTP.

`ServerToolsCoreLib/__init__.py` only imports `client`, `errors` and `config`
— none of which touch `slicer`/`qt`/`ctk`. That is what makes
`import ServerToolsCoreLib` (and therefore `client.py`) work in plain CI with
no Slicer installed: see `ServerToolsCore/Testing/Python/test_client.py`,
which mocks `requests` and runs with `python3 -m unittest`.

The GUI-facing modules (`design`, `formgen`, `slicer_io`, `worker`,
`base_widget`) are imported explicitly and only by code that already runs
inside Slicer (`base_widget.py` does `from . import get_client` lazily inside
`__init__`, precisely so importing `base_widget` doesn't require pulling in
`requests` at class-definition time either way — though in practice it will,
since `client.py` has no Slicer dependency to avoid).

## Tests

Two plain-unittest suites, both registered as ctests and both runnable with
`python3 -m unittest` from `ServerToolsCore/Testing/Python/` — no Slicer
interpreter launch:

- **`test_client.py`** — `requests` mocked. HTTP behavior, local schema
  validation, the request/response shape (including the whole `example_tool`
  round-trip: what each argument type looks like as a form field), error
  mapping, result filenames.
- **`test_formgen.py`** — `qt`/`ctk`/`slicer` replaced by the small stand-ins
  in `qt_stubs.py`. Which widgets a schema produces, in which order, with which
  initial state, and what they read back as. That is pure Python once the
  widget classes are stubbed; it obviously does not test Qt itself, only the
  schema-to-widget logic, which is where the tool contract actually lives.
  It runs against `EXAMPLE_TOOL_SCHEMA`, the server's real `GET /tools` entry
  for `example_tool` copied verbatim.

## How the pieces fit together

```
                       ┌─────────────────────┐
                       │   Tool server (HTTP) │
                       └──────────┬───────────┘
                                  │ requests
                            ┌─────▼─────┐
                            │ client.py │  ToolServerClient, ToolResult, ServerToolError
                            └─────┬─────┘
                                  │ get_client() singleton
                    ┌─────────────▼──────────────┐
                    │      base_widget.py         │  ServerToolWidgetBase
                    │  (Slicer lifecycle, apply/  │
                    │   cancel, error handling)   │
                    └──┬──────────┬─────────┬─────┘
                       │          │         │
                 formgen.py  slicer_io.py  worker.py
              (schema→Qt)   (MRML bridge)  (background thread + QTimer drain)
                       │
                  design.py (theme/colors, used by all of the above)
                       │
              ┌────────▼────────┐
              │ SurgMovPredWidget│  TOOL_NAME / FILE_INPUTS / RESULT_KIND + optional hook overrides
              └──────────────────┘
```

## `client.py`

- `ToolServerClient(server_url, token, verify_tls=True, timeout=600)`.
- `health()` → bool, never raises (a failed health check just means "offline").
  Uses a short fixed timeout (`_HEALTH_CHECK_TIMEOUT = 10`s), not the tool
  timeout — it feeds the status banner on every `enter()` and must not be able
  to block the UI for up to 600s. Only `(requests.RequestException, ValueError)`
  are swallowed into `False`; a programming error (e.g. an unexpected response
  shape raising `AttributeError`) is not silently hidden.
- `list_tools(force_refresh=False)` → `{tool_name: schema}`, cached on the
  instance after the first call. `get_client()` in `__init__.py` returns a
  singleton so the whole extension shares one cache — the first module opened
  pays for `GET /tools`, the rest are free.
- `get_tool_schema(tool_name)` looks the tool up in the cache (fetching if
  needed) and raises `ServerToolError` listing the available tool names if it
  doesn't exist (e.g. `"Unknown tool 'x'. Available: a, b, c"`).
- `is_file_type(type_name)` — `type_name == "file" or type_name.endswith("_file")`.
  The server does **not** stick to a generic `"file"` type: the real schema
  uses `"nifti_file"`, `"zip_file"`, and presumably more later. Every place in
  the codebase that needs to know "is this schema argument a file upload"
  (`client.py`, `formgen.py`, `base_widget.py`) goes through this one
  function instead of comparing against the literal string `"file"` — so a
  new `..._file` type the server introduces needs no client-side code change.
  Exported from `ServerToolsCoreLib/__init__.py` alongside `get_client()`.
- **Schema-reading helpers**, next to `is_file_type` and exported the same way
  (no Qt, no HTTP — just "how do I read a schema argument", which keeps them
  unit-testable in plain CI):
  - `argument_types(spec)` — every type an argument accepts. The server sends
    both a single `type` and the full `types` list; an argument accepting
    several (`example_tool`'s `input`: `["csv_file", "folder"]`) is only
    described by the latter. Falls back to `[type]` for an older schema.
  - `accepts_folder(spec)` — whether `"folder"` is among them, i.e. whether the
    user may pick a whole directory (zipped client-side before upload; HTTP has
    no notion of a folder). The server detects a `"folder"`-typed argument,
    extracts the archive, and strips a lone root directory — so it makes no
    difference whether the zip holds `cohort/a.csv` or `a.csv`.
  - `file_extensions_for(spec)` — the extensions a file picker should offer,
    derived from the file-ish entries of `types`: `["csv_file", "folder"]` →
    `(".csv",)`. A table covers the types whose name doesn't spell out their
    extension (`nifti_file` → `.nii`/`.nii.gz`, `zip_file` → `.zip`) and
    anything else follows the `"<x>_file"` → `".<x>"` convention, so a new
    file type needs no client change. An empty result means "don't restrict"
    (the generic `"file"` type, or a folder-only argument).
- `list_tool_data(tool_name)` → `{"models": [...], "testfiles": [...]}` — the
  file names hosted server-side for this tool (`GET /tools/{tool}/data`,
  Bearer-protected unlike `/tools`). Backs the server-selectable dropdowns
  (see `formgen.py` / `base_widget.py` below). Not cached: fetched once per
  module `setup()`, since the server-side list can change independently of
  the `/tools` schema. Uses `_TOOLS_FETCH_TIMEOUT`, same rationale as the
  schema fetch.
- `run(tool_name, args=None, files=None, output_dir=None, progress_cb=None)`
  → `ToolResult(kind="text"|"file", text=..., path=...)`. `files` is
  `{schema_argument_name: local_file_path}` — **there is no single reserved
  "file" key**: a tool can declare several independent file-type (per
  `is_file_type`) arguments (the real `surg_mov_pred` schema has both
  `"model": {"type": "zip_file", ...}` and `"input": {"type": "zip_file",
  ...}`), each uploaded as its own multipart field named after its schema
  argument. A tool with one file argument just passes a one-entry dict. It:
  1. validates `args`/`files` against the cached schema locally
     (`_validate_against_schema`) — unexpected/missing scalar arguments, an
     unexpected file argument name, a file argument name whose schema type
     isn't file-like, and a missing *required* file argument are all caught
     before a network round-trip (an optional file argument doesn't force an
     entry in `files`);
  2. stringifies every scalar (`bool` → `"true"`/`"false"`) since the server
     does the coercion. A `dict` — how a `"multichoice"` argument arrives, see
     `formgen` below — is sent as `json.dumps(...)`, e.g.
     `outputs={"summary": true, "preview": false, "columns": true}`. **Two
     things there are load-bearing.** *The whole dict travels, unchecked
     options included*: server-side, what is sent **is** the selection — an
     option left out counts as unchecked whatever its declared default, and
     omitting the argument entirely is what applies the defaults. So "every box
     unchecked" and "argument absent" are different requests, and only the real
     state of the boxes tells them apart. *And it is JSON, not the `a,b`
     shortcut*: the server also accepts a comma-separated list of the checked
     options, but that spelling is for `curl` — it breaks the moment an option
     name contains a comma. A `"choice"` argument is a plain string (the
     selected option's name) and needs none of this;
  3. opens every file in `files` in a loop, all closed in one `finally` so a
     handle is never leaked even if a later one fails to open; each is sent as
     `files_payload[arg_name] = (basename, handle)` — the filename (with
     extension) has to travel with the upload since the server validates
     extensions from it; POSTs multipart form-data with the
     `Authorization: Bearer` header;
  4. converts every `requests.RequestException` into `ServerToolError` — no
     `requests` exception is allowed to reach the GUI;
  5. dispatches on `Content-Type`: `application/json` → text result;
     anything else → written to `output_dir` under a filename resolved by
     `_result_filename`: the response's `Content-Disposition` header if
     present (the real filename, e.g. `predictions_outputs.xlsx`); otherwise
     `.nii.gz` when the tool's schema declares `output_kind == "segmentation"`
     (so `slicer.util.loadSegmentation`, which picks its reader from the
     extension, doesn't choke on a bare `.bin`/`.gz`); otherwise
     `mimetypes.guess_extension(Content-Type)` (mirrors the server's own
     `mimetypes.guess_type()`), falling back to `.gz`/`.bin` only if that
     lookup fails. Getting a real extension here matters beyond cosmetics: see
     `slicer_io.is_extractable_archive` below, which decides whether to unpack
     a "save_as" result purely from this filename's extension.
- `errors.error_for_status(status_code, server_message)` maps 401/404/422/400/
  413/500 to a `ServerToolError`. The server's `detail` is shown **verbatim**
  whenever there is one; the strings in that function are fallbacks for a
  response with no usable body. `_server_message` reads JSON `detail`/`message`
  first, then falls back to the raw response body (truncated to 500 chars) so a
  plain-text error response isn't dropped. This matters most for the argument
  errors, where the server's message is the only one that can be specific:
  - **422** — missing / wrong-typed argument, or an option outside a
    `choice`/`multichoice` list: `Argument 'preview_format': unknown option
    'xml'. Expected one of: csv, json`. Nothing client-side second-guesses that
    or falls back to some other value — an out-of-list value is simply shown as
    the server explains it.
  - **400** — wrong extension or invalid archive: `Unsupported file extension
    for 'input'. Allowed: ('.csv', '.zip')`.
  - **413** — the detail names the actual limit (`File exceeds the 500 MB
    limit.`), which the client has no other way of knowing.
  - **401** — missing or wrong token.

  500 is the one exception: a crash inside a tool is not a message meant for
  the user, and its detail may leak server-side internals, so it keeps a
  generic wording.
- `configure(server_url=None, token=None, verify_tls=None, timeout=None)` /
  read-only properties `server_url`/`token`/`verify_tls`/`timeout` — updates
  the already-constructed singleton **in place** (only the fields passed) and
  unconditionally drops the cached `/tools` schema, since it may no longer
  belong to the newly-configured server. This is what lets
  `ServerToolsSettings` change the server URL/API key at runtime without a
  Slicer restart — see the dedicated section below.

## `base_widget.py` — `ServerToolWidgetBase`

Owns the entire Slicer lifecycle (`setup`/`cleanup`/`enter`/`exit`, scene
observers), the schema-driven GUI, the theme, the server status banner
(`GET /health` refreshed in `enter()`, on a background thread), the Apply/
Cancel buttons and their enabled state, the async call via `worker.py`, error
display, and temp-file cleanup (`try/finally` around a `TempWorkspace`, and
also on `cleanup()` in case the module is closed mid-request).

A subclass declares:

```python
class SurgMovPredWidget(ServerToolWidgetBase):
    TOOL_NAME   = "surg_mov_pred"
    FILE_INPUTS = {"input": "folder_zip"}   # {schema_arg_name: mode}
    RESULT_KIND = "save_as"         # "text" | "segmentation" | "volume" | "model" | "save_as"
    AUTO_UI     = True              # False → override buildCustomUI()
```

**The schema is fetched before any widget is built** (`_buildAutoUI`), not
after: a file argument's declared `types` decide what its picker looks like —
file, folder, or the choice between both, and with which extensions — so the
widgets cannot be built without it. Each input's tooltip comes from the same
place, the argument's `description`. The failure path still builds the panel
from an empty schema, with the error shown in it, so the module is never blank.

Overridable hooks (kept deliberately few):

| Hook | Purpose | Default behavior |
|---|---|---|
| `buildCustomUI(layout)` | used when `AUTO_UI = False` | raises `NotImplementedError` |
| `addExtraWidgets(layout)` | add a custom button/field without touching `setup()` | no-op |
| `collectArgs()` | transform values before sending | `formgen.collect(self._argWidgets)` |
| `prepareInputFiles(workspace)` | produce `{schema_arg_name: file_path}` to upload | covers all `FILE_INPUTS` modes already |
| `handleResult(result)` | custom result display | dispatches on `RESULT_KIND` |

`FILE_INPUTS` is `{schema_argument_name: mode}` — one entry per file-type
(per `is_file_type`) argument the tool's schema declares that the client
provides. A tool with a
single file input declares a one-entry dict (e.g. `{"file": "volume_node"}`);
a tool needing several independent files just adds another entry — no other
code changes. Each
entry builds one row in the "Inputs" section, labeled from the argument name.

- `"auto"` — **the recommended default**: the picker is derived from the
  argument's declared `types` (`formgen.auto_file_mode`), so the module names
  no type and no extension. The general rule, in one place: an argument
  accepting `"folder"` may be given a whole folder, and one accepting a file
  type as well gets the choice between the two; the file picker's extensions
  come from the other entries of `types`. It resolves to one of the three
  concrete modes below, once, at build time — the answer is needed twice, to
  build the widget and again at upload time to know whether to zip.
- `"single_file"` — a `ctkPathLineEdit` (file mode), name-filtered to the
  argument's extensions; its `currentPath` is sent as-is.
- `"folder_zip"` — a `ctkPathLineEdit` (directory mode); the folder is zipped
  to `<workspace>/<tool>_<arg_name>.zip` via `slicer_io.zip_folder`.
- `"file_or_folder"` — a `formgen.FileOrFolderInput`: **one** path field with a
  "File..." and a "Folder..." browse button. A folder selection is zipped
  exactly like `"folder_zip"`; a file is sent as-is.

  **The user never declares which kind they are providing** — `is_folder()`
  answers from the path itself (`os.path.isdir`), so a mode cannot be set
  wrong. An earlier version had an explicit File/Folder selector; besides the
  extra step, it made wrong requests possible — a folder pasted into a field
  left on "File" was uploaded as a file and died at `open()`.

  It is a plain `QLineEdit` with two buttons rather than a `ctkPathLineEdit`,
  and both halves of that are forced by CTK, not chosen:

  - **A `ctkPathLineEdit` emits `currentPathChanged` only for input its name
    filters accept.** Restricting a picker to `*.csv` — which the schema asks
    for, since `types` names the accepted extensions — silently swallows the
    change signal for *every folder* (and every non-matching file), so Apply
    would never enable after choosing a folder. Measured against Slicer 5.13:
    with a `*.csv` filter, a file/folder/file/xlsx sequence notifies only for
    the `.csv` selections; filter order changes nothing. Driving both dialogs
    ourselves keeps the file dialog filtered by the declared extensions *and*
    every selection observable.
  - **Its browse button opens a file dialog or a directory dialog according to
    `filters`, and those cannot be flipped at runtime.** Re-assigning
    `nameFilters` on a live `ctkPathLineEdit` corrupts it: Slicer dies either
    on the next `filters` assignment or later, at teardown. (Toggling
    `filters` alone, or assigning `nameFilters` exactly once, are both fine.)

  Hence the rule enforced by `formgen.path_widget`, which still backs the
  single-kind modes: **a ctkPathLineEdit is configured once, at construction,
  and never touched again** — and an unrestricted picker is left with its
  default rather than handed an empty filter list. `test_formgen.py` guards
  both findings: it counts assignments to `filters`/`nameFilters`, and asserts
  every selection notifies whatever its kind.
- `"volume_node"` — a `qMRMLNodeComboBox` restricted to `vtkMRMLScalarVolumeNode`;
  the selected node is exported to `<workspace>/<tool>_<arg_name>.nii.gz` via
  `slicer_io.export_volume`.

The explicit modes remain for what the schema cannot express (picking a volume
from the MRML scene) or to force one selection kind — `SurgMovPred` keeps
`"folder_zip"` because its `input` is typed `zip_file`, with the "give me a
folder, I'll zip it" step being a client-side convention rather than something
the schema declares.

A mismatch between `FILE_INPUTS` and what the schema actually declares as file
arguments surfaces immediately as a visible warning in the panel
(`_warnAboutFileInputsMismatch`) instead of a confusing 422 at Apply time.

`RESULT_KIND` controls `handleResult`'s default and whether an "Output
folder" field is shown:

- `"text"` → `slicer.util.infoDisplay(result.text)`.
- `"segmentation" | "volume" | "model"` → `slicer_io.load_result(result.path, kind)`.
  (`"model"` here is Slicer's `vtkMRMLModelNode` — a 3D surface mesh loaded via
  `loadModel` — unrelated to a machine-learning model; those live server-side
  entirely, e.g. SurgMovPred's `.joblib` files, and never reach the client.)
- `"save_as"` → an explicit output-folder picker is added; the result is
  written there. This is also what a tool declaring `output_kind: "files"`
  server-side needs — several result files arrive as one `.zip`, unpacked into
  the chosen folder. Since one HTTP response can only carry a single blob, a tool
  whose CLI writes several files (SurgMovPred's CLI writes both
  `predictions_outputs.xlsx` and `predictions_outputs.csv`) needs its
  server-side wrapper to zip `outputFolder` before returning it — so
  `_handleSaveAsResult` checks `slicer_io.is_extractable_archive(result.path)`
  and, if true, unzips it into the output folder and discards the archive,
  rather than leaving the user with one opaque `.gz`/`.bin` file. A tool that
  genuinely returns a single file (SurgMovPred currently returns just
  `predictions_outputs.xlsx`, not a zip) is left as-is.

  **`is_extractable_archive` decides purely from the filename's extension
  (`.zip`), never by sniffing the file's bytes for a zip signature.** This was
  a real bug: the first version checked `zipfile.is_zipfile(result.path)`,
  which is also `True` for `.xlsx`/`.docx`/`.ods`/`.pptx` — OOXML formats are
  zip containers internally. A returned `predictions_outputs.xlsx` was being
  silently "extracted" into its raw `[Content_Types].xml`/`_rels/`/`xl/` parts
  instead of being kept as the spreadsheet it is. Getting the extension right
  is therefore load-bearing, not cosmetic — see `_result_filename` above.

## `formgen.py`

The server's `/tools` response is the single source of truth for a tool's
scalar arguments. `build(arguments_schema, layout)` renders one row per
argument (skipping every file-type entry per `is_file_type` — those are
handled by `base_widget` according to `FILE_INPUTS`, not as generic scalar
fields) into a `qt.QFormLayout`, using the type table below, and returns
`{arg_name: widget}`. `collect(arg_widgets)` reads them back;
`all_required_filled(...)` drives the Apply button's enabled state;
`connect_changed(widget, callback)` wires the right Qt signal per widget type.

| Schema `type` | Qt widget |
|---|---|
| any non-file type with `server_selectable` set | `QComboBox` (populated by `base_widget._populateServerSelectables` from `GET /tools/{tool}/data` — `formgen` itself never talks HTTP) |
| `str` | `QLineEdit` |
| `int` | `QSpinBox` |
| `float` | `QDoubleSpinBox` |
| `bool` | `QCheckBox` |
| `choice` | `QComboBox` filled from `choices` |
| `multichoice` | a `MultiChoiceGroup`: one `QCheckBox` per entry of `choices` |
| any type where `is_file_type()` is true (`file`, `zip_file`, `nifti_file`, ...) | `ctkPathLineEdit`, or a `FileOrFolderInput` when `types` also contains `"folder"` (`file_widget`; `build()` itself never emits one — see `FILE_INPUTS` and the escape hatch below) |
| (unknown, non-file) | `QLineEdit` + a logged warning |

`description` becomes the tooltip; `required: true` fields get an asterisk
label via `design.required_label`.

### `choice` and `multichoice`

Both carry a `choices` dict — `{option_name: initial_state}`, `null` on every
other type. **Its key order is the declaration order and is preserved as-is,
never sorted**, in the widget and in what is read back.

| `type` | Widget | Items | Initial state | Read back as |
|---|---|---|---|---|
| `choice` | `QComboBox` | the keys of `choices` | the key whose value is `true` (the server guarantees exactly one) | the selected option's name, e.g. `"json"` |
| `multichoice` | N × `QCheckBox` | the keys of `choices` | each key's boolean | the complete `{option: checked}` dict |

Neither is a single Qt widget mapping 1:1 onto an argument, so `multichoice`
gets a small holder class, `MultiChoiceGroup` (a plain Python object, not a
`QWidget` subclass — PythonQt makes those awkward): it owns the container to
lay out (`row_widget(field)` returns it), the checkboxes in declaration order,
and `value()`. `FileOrFolderInput` follows the same shape. Both expose the
slice of the QWidget API `build()` and `base_widget` use on a field
(`setProperty`, `setToolTip`), so nothing upstream needs to know they are
special; `collect()`, `connect_changed()` and `all_required_filled()`
special-case them in one branch each.

A `multichoice` always reads back as *every* option, and is therefore always
"filled" as far as the Apply button is concerned — every box unchecked is a
meaningful selection, not a missing value. Turning that dict into a form field
is `client.py`'s job (JSON, never the `a,b` shortcut — see `run()` above), so
`formgen` stays free of any wire-format knowledge.

There is deliberately **no client-side handling of a value outside the list**:
the server answers 422 with an explicit `detail` (`Argument 'preview_format':
unknown option 'xml'. Expected one of: csv, json`) and that message is what the
user sees.

**Escape hatch**, not used by `SurgMovPred`: if a tool ever needs a
hand-written `.ui` (grouping, an MRML node selector, default values), give the
relevant widgets a Qt dynamic property named `serverArgName` matching the
schema argument name — the same mechanism as `SlicerParameterName` already
used by this repo's `.ui` files — and `collect()`/`connect_changed()` can be
pointed at those widgets instead of calling `build()`. This is documented,
not implemented.

## `design.py`

One dict of tokens per theme (`_LIGHT`/`_DARK`: `PRIMARY`, `DANGER`, `SUCCESS`,
`TEXT`, `TEXT_MUTED`, `BORDER`, `BACKGROUND`, `SURFACE`, `DISABLED_*`) plus a
spacing scale. `is_dark_mode()` is the **only** place in the extension that
inspects `slicer.app.palette()` luminance. `tokens()` re-reads it every call,
so `apply()`/the factories always reflect the current mode — `base_widget`
calls `design.apply(self.uiWidget)` again in `enter()`, which is when a user
switching Slicer's theme and reopening the module will see it recompute.
(A live in-place recompute while the module is already open and visible is
not wired up — see "Known limitations".)

Factories: `primary_button(text)`, `danger_button(text)`, `section_title(text)`,
`required_label(text)`, `status_badge()` / `update_status_badge(label, ok)`.
Changing the primary color across the whole extension is a one-line edit to
`_LIGHT["PRIMARY"]` / `_DARK["PRIMARY"]`.

## `worker.py`

`BackgroundJob(target, on_success, on_error, on_progress)` runs `target` on a
`threading.Thread`; the thread only ever puts `("progress"|"success"|"error",
payload)` tuples on a `queue.Queue`. A `qt.QTimer` (100 ms) on the main thread
drains the queue and invokes the callbacks there — so `on_success`/`on_error`,
which are the only places allowed to touch `slicer.*`/MRML, always run on the
main thread. `cancel()` stops the timer and marks the job so any
already-queued outcome is discarded; the underlying `requests.post` is not
actually interrupted (see limitations).

## `slicer_io.py`

`TempWorkspace` is a context manager: `mkdtemp` on `__enter__`, `rmtree` on
`__exit__` regardless of exception. `export_volume`, `zip_folder`,
`unzip_folder`, and `load_result(path, kind)` (dispatch to `loadSegmentation`/
`loadVolume`/`loadModel`/`loadTransform`) are the only functions in the
extension that touch node I/O directly.

## Runtime configuration: `ServerToolsSettings` + `settings_qt.py`

`config.py` holds the **compiled-in defaults**; users need a way to point the
extension at a different server (URL, API key, TLS verification, timeout)
without editing source and rebuilding. Two pieces:

- **`settings_qt.py`** (in `ServerToolsCoreLib`, not imported by `__init__.py`):
  reads/writes a `qt.QSettings()` group (`"ServerTools"`, one key per field).
  `QSettings` is Slicer's native prefs mechanism — an ini/plist file on disk,
  independent of the Slicer process, so it survives restarts. Kept out of
  `__init__.py` on purpose: it imports `qt`, and the package must stay
  importable outside Slicer for `client.py`'s unit tests (see the dependency
  rule above). Only Slicer-side code imports it directly.
  - `load_overrides()` → `{}` if the user never saved anything, otherwise only
    the fields that were actually saved.
  - `save_overrides(server_url, token, verify_tls, timeout)`,
    `clear_overrides()` ("restore defaults" — removes the whole group).
  - `apply_saved_overrides(client)` — applies `load_overrides()` onto a
    `ToolServerClient` via `configure()`, if any override exists.
- **`ServerToolsCore.py`** calls `apply_saved_overrides(get_client())` in its
  `__init__` — this runs once, when Slicer discovers the module at startup
  (before any tool module is opened), so a setting saved in a previous
  session is already active by the time the user opens e.g. `SurgMovPred`.
- **`ServerToolsSettings`** (new visible module, category
  `"Automated Dental Tools.Advanced"`, depends on `ServerToolsCore`): a plain
  `ScriptedLoadableModuleWidget` (not a `ServerToolWidgetBase` — its Apply/
  async-job machinery is for calling remote tools, not for a local save
  action) with four fields matching `config.py` 1:1 (Server URL, API key as a
  password-masked `QLineEdit`, Verify TLS checkbox, Timeout spinbox), styled
  via `design.py` for consistency. **Save** calls both `save_overrides(...)`
  (persists) and `client.configure(...)` (applies immediately, no restart
  needed — every module sees it since they all share the same `get_client()`
  singleton). **Restore defaults** calls `clear_overrides()` and
  `client.configure(...)` back to `config.py`'s values.

**Limitation**: changing the server while a tool module (e.g. `SurgMovPred`)
is already open updates its `client` (same singleton) but does **not**
retroactively rebuild that widget's already-built AUTO_UI form — `_buildAutoUI`
only runs once, in `setup()`. If the new server has a different schema for the
same tool name, the user needs to close and reopen the module (or use
Developer mode's "Reload") to see the new fields.

## `SurgMovPred`

```python
class SurgMovPredWidget(ServerToolWidgetBase):
    TOOL_NAME   = "surg_mov_pred"
    FILE_INPUTS = {"input": "folder_zip"}
    RESULT_KIND = "save_as"
    AUTO_UI     = True
```

That, plus the standard `ScriptedLoadableModule` metadata class, is the entire
file (~35 lines). No overrides are needed: the input folder of
`.csv`/`.xlsx`/`.ods` files is zipped automatically, and the result is written
to a user-chosen output folder.

**The model is selected on the server, not uploaded.** The server's
`surg_mov_pred` schema declares `"model"` as
`{"type": "str", "server_selectable": "model", "required": true}`: the client
sends the *name* of a model hosted in the server's data store, and the server
resolves it internally (`GET /tools/surg_mov_pred/data` lists what's
available). Client-side this needs zero SurgMovPred-specific code: any scalar
argument flagged `server_selectable` is rendered by `formgen` as a `QComboBox`
and populated by `base_widget._populateServerSelectables` via
`client.list_tool_data()` — the value collected is the selected name, sent as
a plain form field. An unreachable server or an empty model list surfaces as a
visible warning label in the panel, and the Apply button stays disabled while
the dropdown is empty (an empty `currentText` fails
`formgen.all_required_filled`). Uploading a local model package is not just
unsupported client-side, the server actively rejects a file upload for a
scalar argument with a 400. (Historical note: an earlier iteration had
`"model"` as a second `zip_file` upload — `FILE_INPUTS = {"input":
"folder_zip", "model": "folder_zip"}` — because the server of the time
required it. The multi-file upload machinery it forced into `client.run()` /
`FILE_INPUTS` remains, and is still exercised by tests, for any future tool
with several genuine file inputs.)

### `SurgMovPred_CLI`

Left in the repository but **not** added to the root `CMakeLists.txt` — it is
out of the Slicer build's execution path, per the brief. Its `main(inputFolder,
modelPath, outputFolder)` is unchanged and is exactly what the server-side
tool wrapper for `surg_mov_pred` should call: create a temp dir, unzip the
uploaded archive into `inputFolder`, inject `modelPath` from the server's own
config, call `main()`, re-zip `outputFolder` into the HTTP response. That
wrapper is server-side and out of scope for this change.

## `ExampleTool`

```python
class ExampleToolWidget(ServerToolWidgetBase):
    TOOL_NAME   = "example_tool"
    FILE_INPUTS = {"input": "auto"}
    RESULT_KIND = "save_as"
    AUTO_UI     = True
```

The server's `example_tool` is the one tool exercising everything the client
has to know how to do, which makes this module the reference client — and a
quick way to check a server connection end to end without running a real
analysis. Its schema declares, and this module renders with **zero
tool-specific code**:

- `label` (str), `threshold` (float), `iterations` (optional int) — the
  ordinary scalar fields;
- `preview_format`, a `choice` → a combo box of `csv`/`json`, `csv`
  preselected, sent as `preview_format=json`;
- `outputs`, a `multichoice` → three checkboxes (`summary`, `preview`,
  `columns`) starting at `true, true, false`, sent as
  `outputs={"summary": true, "preview": false, "columns": true}`;
- `input`, typed `["csv_file", "folder"]` → one path field taking either; a
  `.csv` goes up as-is, a folder is zipped first, and which one it got is
  detected, not declared (`"auto"` resolves to `"file_or_folder"`);
- `output_kind: "files"` → the response is a `.zip` of several result files
  (`summary.txt`, `preview.json`, ...) named by `Content-Disposition`, unpacked
  into the output folder the user picks (`RESULT_KIND = "save_as"`).

## How to add a new module in 5 minutes

Worked example: migrating `AMASSS` (CBCT volume in, segmentation out).
Assume the server exposes a tool named `amasss_segmentation` with one
file-type argument (e.g. `"file": {"type": "nifti_file", ...}` — the volume)
plus whatever scalar options AMASSS needs (e.g. a
`threshold` float) — no other server-side change is asked of you, only what
the client needs:

1. **CMakeLists.txt** (`AMASSS/CMakeLists.txt`) — drop the `.ui` resource
   entry (deleted, see below), keep the icon, no other change.

2. **Delete `AMASSS/Resources/UI/AMASSS.ui`** — the GUI is generated from the
   server schema now.

3. **Rewrite `AMASSS/AMASSS.py`**:

   ```python
   from slicer.i18n import tr as _
   from slicer.ScriptedLoadableModule import ScriptedLoadableModule
   from ServerToolsCoreLib.base_widget import ServerToolWidgetBase


   class AMASSS(ScriptedLoadableModule):
       def __init__(self, parent):
           ScriptedLoadableModule.__init__(self, parent)
           self.parent.title = _("AMASSS")
           self.parent.categories = ["Automated Dental Tools"]
           self.parent.dependencies = ["ServerToolsCore"]
           self.parent.contributors = ["..."]
           self.parent.helpText = _("CBCT segmentation, served remotely.")
           self.parent.acknowledgementText = ""


   class AMASSSWidget(ServerToolWidgetBase):
       TOOL_NAME   = "amasss_segmentation"
       FILE_INPUTS = {"file": "volume_node"}  # user picks a scene volume; exported to .nii.gz automatically
       RESULT_KIND = "segmentation"    # result is loaded into the scene via loadSegmentation
       AUTO_UI     = True              # the "threshold" float field is generated from /tools
   ```

4. That's it. No CSS, no HTTP, no threading code, no `.ui` file to keep in
   sync with the server. If AMASSS later needs a "preview" button, add:

   ```python
   def addExtraWidgets(self, layout):
       button = design.primary_button(_("Preview"))
       button.clicked.connect(self._onPreview)
       layout.addWidget(button)
   ```

   without touching `setup()` — satisfying the "adding a custom button" cost
   target in the brief.

This confirms the four success criteria from the brief:
- **new module** = a ~15-line class + `CMakeLists.txt` change;
- **new field** = zero client-side lines (comes from the server schema);
- **custom button** = one `addExtraWidgets` override;
- **network/display bug fix** = edit `client.py` / `base_widget.py` once, every module gets it.

## Debatable decisions & known limitations

- **CMake pattern for `ServerToolsCoreLib`**: uses `slicerMacroBuildScriptedModule`
  with the library's files listed as extra `SCRIPTS`, mirroring
  `BATCHDENTALSEGLib` (already in this repo) rather than a raw
  `install(DIRECTORY ... DESTINATION ${Slicer_QTSCRIPTEDMODULES_LIB_DIR})`.
  This macro only registers exactly one Slicer module (`NAME`); the extra
  `SCRIPTS` are copied/byte-compiled alongside it, not turned into modules of
  their own. Chosen because it is a proven pattern already used in this exact
  codebase; documented here since the original brief suggested the manual
  `install()` route instead.
- **Multi-file support was added once it turned out to be needed now, not
  later**: the original plan assumed one file per request under a reserved
  `"file"` key, with multi-file support deferred as a documented future need.
  Testing against the real server showed `surg_mov_pred` already requires two
  independent file arguments (`"model"` + `"input"`), so `client.run()` and
  `FILE_INPUTS` were generalized immediately instead of shipping something
  that couldn't call the actual tool. There is no more reserved `"file"` key:
  every file argument is uploaded under its own schema argument name. This
  subsumes the single-file case (a schema whose one file argument happens to
  be named `"file"` still works exactly as before).
- **File-type detection is a suffix convention, not a fixed enum**: after
  `FILE_INPUTS` shipped, the real server's schema turned out to type its file
  arguments as `"nifti_file"` / `"zip_file"` — never the literal `"file"` used
  everywhere in the original brief's examples. Every exact-match check
  (`spec.get("type") == "file"`) was replaced by `is_file_type()`
  (`client.py`), which treats `"file"` and any `"..._file"` type as a file
  upload. This was necessary, not cosmetic: without it, `formgen.build()`
  rendered bogus `QLineEdit` rows for `"model"`/`"input"` *in addition to*
  their real `FILE_INPUTS` widgets, and `_validate_against_schema` demanded
  `"model"`/`"input"` as required *scalar* arguments (since they didn't match
  the literal string `"file"`), which would have made every real call to
  `surg_mov_pred` fail local validation. If the server ever introduces a
  differently-shaped file type name (not ending in `_file`), `is_file_type`
  needs a one-line update — everything downstream (`formgen`, `base_widget`)
  picks it up automatically since they all go through this single function.
- **`"auto"` file inputs degrade when the schema can't be fetched**: the mode
  is resolved from the argument's `types`, so with an unreachable server
  `formgen.auto_file_mode({})` falls back to `"single_file"` — the panel offers
  a file picker with no extension filter instead of the file/folder choice. The
  reason is already on screen (the schema-fetch warning label) and the module
  is unusable anyway without a server, so this is a degraded display rather
  than a silent wrong behavior. A module that must keep its picker regardless
  declares the concrete mode instead of `"auto"`.
- **`/tools` cache never auto-invalidates**: `get_client()` is a singleton
  cached for the process lifetime; `list_tools(force_refresh=True)` exists but
  nothing currently calls it automatically. If the server's schema changes
  while Slicer is running, a user has to restart Slicer (or a future "Refresh
  tools" button would need to call `force_refresh=True` and rebuild the
  affected widgets — not implemented).
- **No true server-side cancel**: `BackgroundJob.cancel()` discards the
  result and releases the UI immediately, but the in-flight `requests.post`
  keeps running against the server until it finishes or times out
  (`timeout=600`). A real cancel would need the server to expose a
  cancellation endpoint keyed by a request id.
- **Schema fetch is synchronous**: `get_tool_schema()` inside `_buildAutoUI`
  runs on the main thread during `setup()` (i.e. opening the module). This is
  a deliberate choice — `GET /tools` is cheap and cached, and building the
  form needs the schema before the first paint — but it is technically a
  blocking network call, unlike `run()`. Capped at `_TOOLS_FETCH_TIMEOUT = 15`s
  (separate from the 600s tool-execution timeout) so a slow/unreachable server
  can only stall module opening briefly, not for minutes, before falling back
  to an empty schema — and that fallback is shown as a visible warning label
  in the panel itself (`design.warning_label`), not just logged, so "the
  module looks broken" always comes with a reason on screen. The same applies
  to any other exception raised while building the UI (`setup()` wraps
  `_buildAutoUI`/`buildCustomUI` and shows the exception instead of leaving a
  half-built, silently broken panel).
- **Theme recompute is on `enter()`, not live**: switching Slicer's
  application-wide theme while a ServerTools module is the currently visible
  one does not repaint it until the user leaves and re-enters the module (or
  reopens Slicer). `design.tokens()` itself always reflects the current mode;
  only the "when do we re-apply the stylesheet" question is coarse.
- **`SurgMovPred_CLI` is orphaned, not deleted**: kept in the repo per the
  brief, no longer wired into the CMake build or called by the widget. It is
  the reference implementation for the server-side tool wrapper.
- **`config.py` ships a placeholder token**: `API_TOKEN = "REPLACE_ME"` and a
  placeholder `SERVER_URL`. Both must be set to real values before this is
  deployed; do not commit a real production token to this file.
