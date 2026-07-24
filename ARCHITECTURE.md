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
├── CMakeLists.txt                          # add_subdirectory(ServerToolsCore) then add_subdirectory(SurgMovPred)
├── ARCHITECTURE.md                         # this file
├── ServerToolsCore/                        # hidden scripted module, no GUI
│   ├── CMakeLists.txt
│   ├── ServerToolsCore.py                  # ScriptedLoadableModule shell, parent.hidden = True
│   ├── Testing/Python/test_client.py       # plain unittest, requests mocked, no Slicer needed
│   └── ServerToolsCoreLib/                 # the importable Python package
│       ├── __init__.py                     # get_client() + ToolServerClient/ToolResult/ServerToolError
│       ├── config.py                       # SERVER_URL, API_TOKEN, VERIFY_TLS, TIMEOUT
│       ├── client.py                       # ToolServerClient — the only class that speaks HTTP
│       ├── errors.py                       # ServerToolError + HTTP status → message mapping
│       ├── slicer_io.py                    # TempWorkspace, node export, zip/unzip, result loading
│       ├── design.py                       # theme tokens, dark/light detection, styled-widget factories
│       ├── formgen.py                      # /tools schema → Qt widgets, and back
│       ├── worker.py                       # off-UI-thread execution (BackgroundJob)
│       └── base_widget.py                  # ServerToolWidgetBase: all the Slicer boilerplate
├── SurgMovPred/
│   ├── CMakeLists.txt
│   └── SurgMovPred.py                      # ~30 lines, declarative
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
     does the coercion;
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
  413/500 to a `ServerToolError`; for 400/422 the server's own message is
  propagated verbatim (already explicit per the API contract) — `_server_message`
  reads JSON `detail`/`message` first, then falls back to the raw response body
  (truncated to 500 chars) so a plain-text error response isn't dropped.

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
    FILE_INPUTS = {"input": "folder_zip", "model": "single_file"}   # {schema_arg_name: mode}
    RESULT_KIND = "save_as"         # "text" | "segmentation" | "volume" | "model" | "save_as"
    AUTO_UI     = True              # False → override buildCustomUI()
```

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
a tool needing several independent files, like the real `surg_mov_pred`
(`"model"` + `"input"`), just adds another entry — no other code changes. Each
entry builds one row in the "Inputs" section, labeled from the argument name,
and `prepareInputFiles`'s default handles all three modes per entry:

- `"single_file"` — a `ctkPathLineEdit` (file mode); its `currentPath` is sent as-is.
- `"volume_node"` — a `qMRMLNodeComboBox` restricted to `vtkMRMLScalarVolumeNode`;
  the selected node is exported to `<workspace>/<tool>_<arg_name>.nii.gz` via
  `slicer_io.export_volume`.
- `"folder_zip"` — a `ctkPathLineEdit` (directory mode); the folder is zipped
  to `<workspace>/<tool>_<arg_name>.zip` via `slicer_io.zip_folder`.

Once the schema loads, each input widget's tooltip is set from the matching
argument's `description` (`_applyFileArgumentTooltips`), and a mismatch
between `FILE_INPUTS` and what the schema actually declares as file arguments
surfaces immediately as a visible warning in the panel
(`_warnAboutFileInputsMismatch`) instead of a confusing 422 at Apply time.

`RESULT_KIND` controls `handleResult`'s default and whether an "Output
folder" field is shown:

- `"text"` → `slicer.util.infoDisplay(result.text)`.
- `"segmentation" | "volume" | "model"` → `slicer_io.load_result(result.path, kind)`.
  (`"model"` here is Slicer's `vtkMRMLModelNode` — a 3D surface mesh loaded via
  `loadModel` — unrelated to a machine-learning model; those live server-side
  entirely, e.g. SurgMovPred's `.joblib` files, and never reach the client.)
- `"save_as"` → an explicit output-folder picker is added; the result is
  written there. Since one HTTP response can only carry a single blob, a tool
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
| `str` | `QLineEdit` |
| `int` | `QSpinBox` |
| `float` | `QDoubleSpinBox` |
| `bool` | `QCheckBox` |
| any type where `is_file_type()` is true (`file`, `zip_file`, `nifti_file`, ...) | `ctkPathLineEdit` (kept for the escape hatch below; `build()` itself never emits one — see `FILE_INPUTS`) |
| (unknown, non-file) | `QLineEdit` + a logged warning |

`description` becomes the tooltip; `required: true` fields get an asterisk
label via `design.required_label`.

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

## `SurgMovPred`

```python
class SurgMovPredWidget(ServerToolWidgetBase):
    TOOL_NAME   = "surg_mov_pred"
    FILE_INPUTS = {"input": "folder_zip", "model": "folder_zip"}
    RESULT_KIND = "save_as"
    AUTO_UI     = True
```

That, plus the standard `ScriptedLoadableModule` metadata class, is the entire
file (~35 lines). No overrides are needed: both the input folder of
`.csv`/`.xlsx`/`.ods` files and the model folder are zipped automatically, and
the result is written to a user-chosen output folder. (`model` is
`"folder_zip"` rather than `"single_file"`: the user picks a folder of model
files, not an already-zipped archive — either mode works against the real
schema, since the server only cares that it receives a zip under the `model`
field; `folder_zip` was chosen so users don't have to zip anything by hand.)

**Correction to the original plan**: the brief this was built from stated that
`modelPath` "disappears from the client — it is server configuration" and that
"the widget must no longer expose a model selector." That does not hold
against the actual running server: its `surg_mov_pred` schema declares
`"model"` as a required file-type argument (`"type": "zip_file"`, description:
*"Model package: a zip archive containing one or more stacking_package.pkl
files"*) — the client is expected to upload a model package on every call,
not rely on server-side config. `FILE_INPUTS` reflects
reality over the original plan; if the intent really was "model lives on the
server," that's a server-side change to make (drop `"model"` from the
`surg_mov_pred` schema and read the model path from server config instead),
not something the client can paper over.

### `SurgMovPred_CLI`

Left in the repository but **not** added to the root `CMakeLists.txt` — it is
out of the Slicer build's execution path, per the brief. Its `main(inputFolder,
modelPath, outputFolder)` is unchanged and is exactly what the server-side
tool wrapper for `surg_mov_pred` should call: create a temp dir, unzip the
uploaded archive into `inputFolder`, inject `modelPath` from the server's own
config, call `main()`, re-zip `outputFolder` into the HTTP response. That
wrapper is server-side and out of scope for this change.

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
