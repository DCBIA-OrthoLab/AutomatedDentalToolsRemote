# Refactor: client/server architecture for SlicerAutomatedDentalTools

## Implementation status (updated after the initial build-out)

`ServerToolsCore` and the rebuilt `SurgMovPred` described below are implemented,
wired into the CMake build, and covered by unit tests (see
`ServerToolsCore/Testing/Python/test_client.py`). **`ARCHITECTURE.md` is the
authoritative, up-to-date reference** — dependency diagram, per-file
responsibilities, the "add a module in 5 minutes" guide, and a full list of
debatable decisions and known limitations. Read it before making further
changes here.

The implementation deviates from a few specifics of the brief below, based on
what testing against the real dev server surfaced. Each is explained in
`ARCHITECTURE.md`; summarized here:

- **Flat directory layout**: `ServerToolsCore/` and `SurgMovPred/` live at the
  repo root, not nested under a `SlicerServerTools/` wrapper — matching every
  other module in this repository.
- **CMake pattern**: `ServerToolsCoreLib` is wired in via
  `slicerMacroBuildScriptedModule` with its files listed as extra `SCRIPTS`
  (mirroring the existing `BATCHDENTALSEGLib` in this repo), not a manual
  `install(DIRECTORY ...)`.
- **Multi-file support was needed immediately, not deferred**: the real
  `surg_mov_pred` tool requires *two* independent file uploads (a model
  package and the input data), not one. `client.run()` takes
  `files={arg_name: path, ...}` — there is no single reserved `"file"` key.
  `ServerToolWidgetBase` exposes this as `FILE_INPUTS = {arg_name: mode}`
  instead of a single `INPUT_MODE`.
- **File-type detection is a naming convention, not a fixed string**: the
  real server types file arguments as `"nifti_file"` / `"zip_file"`, never
  the literal `"file"` used in this brief's examples. `is_file_type()`
  treats `"file"` and any `"..._file"` type as a file upload, so a new
  file-ish type the server introduces later needs no client-side change.
- **The model does *not* stay purely server-side**: contrary to "modelPath
  disappears from the client — it is server configuration" below, the real
  `surg_mov_pred` schema requires the client to upload a model package
  (`"model"`) on every call. If the intent is still to keep the model
  server-side, that requires a server-side schema change, not a client-side
  workaround.
- **Result handling bug fixed**: the first version decided whether to unpack
  a "save_as" result by sniffing its bytes for a zip signature
  (`zipfile.is_zipfile`). Since OOXML formats (`.xlsx`, `.docx`, `.ods`) are
  zip containers internally, a returned `predictions_outputs.xlsx` was being
  wrongly "extracted" into raw XML parts. Fixed to decide from the resolved
  filename's extension only (`slicer_io.is_extractable_archive`).
- **Result downloads are streamed, verified, and reported on.** The brief's
  `response.content` write assumed small results; a real AMASSS run returns an
  archive of one segmentation plus one surface per structure per scan, which is
  not something to buffer whole in Slicer's RAM. `run()` now POSTs with
  `stream=True` and writes 1 MB chunks straight to disk. A file result is then
  checked against `Content-Length` and, for a `.zip`, CRC-checked member by
  member before being accepted — a truncated archive still unpacks, so without
  this a dropped connection would have silently delivered a *subset* of a
  patient's segmentations. On failure the partial file is deleted and the error
  raised.
- **Added beyond the original brief: "the panel is alive" feedback.** A tool run
  is one HTTP request lasting minutes, during which the worker thread is blocked
  and has nothing to report — so the panel showed nothing at all and read as
  frozen. A real AMASSS run was cancelled at three minutes for that reason,
  forty seconds from finishing. A main-thread `QTimer` now ticks the current
  phase plus elapsed time into a label under the Cancel button, `progress_cb`
  reports MB/percent during the download, and the extraction announces itself.
  What it still can't show is progress *within* the inference: that needs a
  server-side job API. See ARCHITECTURE.md, "Telling the user something is
  happening".
- **Added beyond the original brief: a runtime settings module.** The brief's
  "constants at the top of a config file" decision (below) covered defaults,
  but not how a user changes server URL/API key/TLS/timeout without editing
  source and rebuilding. Added `ServerToolsSettings` (a small visible module,
  4 fields matching `config.py`) backed by `qt.QSettings` (persists across
  restarts) and `ToolServerClient.configure()` (applies immediately, no
  restart needed, via the shared `get_client()` singleton). `config.py`
  remains the compiled-in defaults; `QSettings` is the optional user override
  on top. See ARCHITECTURE.md, "Runtime configuration".

Local/dev server endpoints, tokens, and any other non-public details used
while testing are kept out of this file — see `claude.secret.md` (gitignored,
not committed) if you need them.

---

## Mission

Rework the extension's architecture so that **all computation moves to a remote server**
("tool-registry" architecture, see `claude.md`) and the Slicer code becomes a **thin GUI**.

Scope of this task:

1. Build the shared infrastructure (`ServerToolsCore`).
2. Rewrite **only `SurgMovPred`** on top of that infrastructure.
3. Do not touch the other modules (AMASSS, ALI, MRI2CBCT, ...) for now — but the architecture must
   make migrating them later trivial.

> **The architecture is the primary deliverable, not the SurgMovPred code.**
> Take the time to think it through before writing anything. If a choice feels debatable, write it
> down in `ARCHITECTURE.md` with the alternatives you considered rather than silently picking one.

All code, comments, docstrings and documentation must be written in English.

---

## Success criteria

The architecture succeeds if these four operations are **simple, localized and obvious**:

| Operation | Expected cost |
|---|---|
| **Add a module** for a new server tool | a ~5-line class + a `CMakeLists.txt` |
| **Add a text field / checkbox** to a tool | zero lines on the Slicer side (the field comes from the server schema) |
| **Add a custom button** to a module | override a single hook, without touching the base class |
| **Fix a network or display bug** | one file to edit, the fix propagates to every module |

If any of these four requires duplicating code, the architecture needs rethinking.

---

## Context: what exists today

`SurgMovPred` is ~1200 lines across 4 files:

| File | Lines | Fate |
|---|---|---|
| `SurgMovPred/SurgMovPred.py` | 873 | shrink to ~45 lines |
| `SurgMovPred/Resources/UI/SurgMovPred.ui` | — | delete (GUI is auto-generated) |
| `SurgMovPred_CLI/SurgMovPred_CLI.py` | 321 | **moves to the server**; don't delete it from the repo yet, just take it out of the module's execution path |
| `SurgMovPred_CLI/SurgMovPred_CLI.xml` | — | same |

Breakdown of the 873 widget lines and what happens to each block:

| Current block | Lines | Action |
|---|---|---|
| `check_lib_installed` / `install_function` / `ensure_mac_openmp` / `check_dependencies` | 38–224 | **Delete.** This is exactly what the server replaces: no more heavy dependencies (pandas, sklearn, joblib) inside the Slicer interpreter. |
| `class SurgMovPred(ScriptedLoadableModule)` (metadata) | 225–249 | Keep — required and trivial |
| `@parameterNodeWrapper class SurgMovPredParameterNode` | 250–266 | Delete — replaced by generic collection from the widgets |
| `setup` / `cleanup` / `enter` / `exit` / `onSceneStartClose` / `onSceneEndClose` / `initializeParameterNode` / `setParameterNode` / `_checkCanApply` | 267–402 | **Factor out** into the base class: 100% generic |
| `_isDarkMode` / `_getStyleSheet` / `_applyLabelStyleSheets` / `_applyButtonStyleSheets` | 449–708 | **260 lines of CSS duplicated in most modules of the repo.** → move into a shared design class (see dedicated section) |
| `DownloadUnzip` / `DownloadTestFiles` / `onDownloadDefaultModel` | 709–797 | **Delete.** Models live on the server; the client has nothing left to download. Optionally keep a "download test files" button *if* the server exposes test files — otherwise remove it. |
| `onApplyButton` / `onCancelCliButton` / `onCliFinished` | 403–448 | Replace with the async HTTP call |
| `SurgMovPredLogic.process` → `slicer.cli.run(slicer.modules.surgmovpred_cli, ...)` | 798–873 | Replace with `client.run(...)` |

Expected outcome: **~600 lines deleted**, ~150 lines factored into the core, ~45 lines genuinely
specific to SurgMovPred.

---

## Server API contract

Use it as-is; do not invent endpoints or field names.

### `GET /health`
→ `{"status": "ok"}`, no auth.

### `GET /tools`
→ list of every registered tool with its expected arguments. Real example:

```json
[
  {"name": "example_tool", "arguments": {
      "label":      {"type": "str",   "required": true,  "description": "..."},
      "file":       {"type": "file",  "required": true,  "description": "..."},
      "threshold":  {"type": "float", "required": true,  "description": "..."},
      "iterations": {"type": "int",   "required": false, "description": "..."}
  }, "output_kind": "text"},
  {"name": "test_tool", "arguments": {"text_1": {}, "text_2": {}}, "output_kind": "text"}
]
```

### `POST /run/{tool_name}`
The only endpoint that executes anything. Protected by a Bearer token.

- **Multipart form-data** (`requests` with `files=` / `data=`, **not JSON**).
- Header `Authorization: Bearer <token>`.
- Each scalar argument is a separate form-data field, using the exact name listed in `/tools`.
  Everything arrives on the server as a `string`; the server coerces to `int`/`float`/`bool` itself
  based on the schema. **So the client must not type-cast, only stringify.**
- If the tool has a `type: "file"` argument, it **must** be sent under the key `file`
  (reserved name, **one file per request for now**): `files={"file": open(path, "rb")}`.
- Never send a field absent from the tool's `arguments` → 422 `"Unexpected argument..."`.
- Never omit a `required: true` field → 422 `"Missing required argument..."`.

### Response
- `output_kind: "text"` → JSON `{"result": "..."}`.
- `output_kind: "file"` or `"segmentation"` → **raw bytes** (`application/gzip` or
  `application/octet-stream`), to be written to disk then loaded into Slicer
  (`slicer.util.loadSegmentation`).
- Distinguish the two via the response `Content-Type` header (`application/json` vs anything else).

### Error codes to handle client-side

| Code | Cause | Widget-side action |
|---|---|---|
| 401 | missing/invalid token | `errorDisplay("Authentication failed")` |
| 404 | unknown `tool_name` | check spelling, list `/tools` |
| 422 | missing, unexpected, or wrong-typed argument | **the server message is already explicit — show it verbatim** |
| 400 | disallowed file extension | check `.nii` / `.nii.gz` (server-configurable) |
| 413 | file too large (`MAX_UPLOAD_MB`) | warn the user |
| 500 | the tool crashed server-side | generic error |

### Client-side security
- `verify_tls=True` by default (`False` only in dev, **never in production**).
- Token/URL: for this version, **constants at the top of a config file** (`SERVER_URL`,
  `API_TOKEN`). This decision is already settled for this project — do not read them from a Slicer
  environment variable.
- **Never log the token, nor the contents of files/arguments.** Add a scrubbing pass in the logging
  layer if needed.

### Slicer environment constraints
- Libraries available in the Slicer interpreter: `requests`, `slicer`, `qt`, `vtk`, `os`,
  `tempfile`. **Nothing else.** No `pandas`, no `numpy`, no `httpx`, no `pydantic`.
- A 3D volume from the scene (`vtkMRMLScalarVolumeNode`) must be exported to disk before upload:
  `slicer.util.saveNode(volume_node, path)` to a temporary `.nii.gz`.
- Clean up temporary files (export + downloaded result) after use, **including on error**
  (`try`/`finally`).

---

## Target architecture

```
SlicerServerTools/
├── CMakeLists.txt
├── ARCHITECTURE.md                         # to be written (see below)
├── ServerToolsCore/                        # hidden scripted module, no GUI
│   ├── CMakeLists.txt
│   ├── ServerToolsCore.py                  # ScriptedLoadableModule shell, parent.hidden = True
│   └── ServerToolsCoreLib/                 # the actual importable Python package
│       ├── __init__.py                     # exposes get_client() and the public types
│       ├── config.py                       # SERVER_URL, API_TOKEN, VERIFY_TLS, TIMEOUT
│       ├── client.py                       # ToolServerClient — ALL HTTP requests
│       ├── errors.py                       # ServerToolError + HTTP status mapping
│       ├── slicer_io.py                    # node → file export, zip, result loading, TempWorkspace
│       ├── formgen.py                      # /tools schema → Qt widgets, and widgets → args dict
│       ├── design.py                       # theme, styles, styled-widget factories (see design section)
│       ├── worker.py                       # off-UI-thread execution + marshalling back to the Qt thread
│       └── base_widget.py                  # ServerToolWidgetBase: all the Slicer boilerplate
├── SurgMovPred/
│   ├── CMakeLists.txt
│   └── SurgMovPred.py                      # ~45 lines, declarative
└── (other modules stay untouched for now)
```

### Dependency rule to enforce strictly

> `client.py` and `errors.py` **import neither `slicer` nor `qt`.**
> `base_widget.py` and `formgen.py` **import neither `requests` nor anything HTTP.**

Consequence: `client.py` is testable in CI outside Slicer with a simple `requests` mock. Write at
least a few unit tests for it.

---

## `client.py` — the class that factors out requests

This is the heart of the request: **one class makes the requests; nothing else speaks HTTP.**

```python
class ToolResult:
    """Uniform result regardless of output_kind."""
    kind: str          # "text" | "file"
    text: str | None
    path: str | None


class ToolServerClient:
    def __init__(self, server_url, token, verify_tls=True, timeout=600): ...

    def health(self) -> bool: ...
    def list_tools(self, force_refresh=False) -> dict[str, dict]: ...
    def get_tool_schema(self, tool_name) -> dict: ...
    def run(self, tool_name, args=None, file_path=None,
            output_dir=None, progress_cb=None) -> ToolResult: ...
```

Required behaviors:

- **Cache `/tools`** on the instance. The first module opened pays for the call; the rest are free.
  Provide `force_refresh=True` and a way to trigger it while the server is being developed.
- **Singleton** via `get_client()` in `__init__.py` — one client for the whole extension, hence one
  cache.
- **Local validation against the schema before sending** (`_validate_against_schema`): catch
  unexpected arguments and missing `required` fields without paying a network round-trip. The
  messages should mirror the server's wording so users aren't confused by two different phrasings.
- **Stringify** every scalar (`bool` → `"true"`/`"false"`), since the server does the coercion.
- **The file handle must be closed** — the original skeleton calls `open(path, "rb")` and never
  closes it. Use `with` or `try`/`finally`.
- **Every `requests.RequestException` is converted into a `ServerToolError`** with a presentable
  message. No `requests` exception should ever reach the GUI.
- For 400 and 422, **propagate the server message verbatim** (it is already explicit). For the
  others, use a clear application-level message.

Minimal reference skeleton for the POST part (from the contract):

```python
headers = {"Authorization": f"Bearer {token}"}
files = {"file": fh} if file_path else None
response = requests.post(
    f"{server_url.rstrip('/')}/run/{tool_name}",
    headers=headers, data=args, files=files,
    timeout=timeout, verify=verify_tls,
)
```

---

## `base_widget.py` — boilerplate written once

`ServerToolWidgetBase(ScriptedLoadableModuleWidget, VTKObservationMixin)` owns:

- the Slicer lifecycle (`setup`, `cleanup`, `enter`, `exit`, scene observers);
- building the GUI from the schema (`formgen`);
- applying the theme (`design`);
- the server status banner (green/red indicator from `GET /health` on `enter()` — heads off the
  "it doesn't work" tickets);
- the Apply / Cancel buttons, conditional enabling, busy state;
- the async call, error handling, and temp-file cleanup.

A subclass declares only class attributes and optionally overrides hooks:

```python
class SurgMovPredWidget(ServerToolWidgetBase):
    TOOL_NAME   = "surg_mov_pred"
    INPUT_MODE  = "folder_zip"      # "none" | "single_file" | "volume_node" | "folder_zip"
    RESULT_KIND = "save_as"         # "text" | "segmentation" | "volume" | "model" | "save_as"
    AUTO_UI     = True              # False → override buildCustomUI()
```

Overridable hooks (keep them few and well named):

| Hook | Purpose |
|---|---|
| `buildCustomUI()` | when `AUTO_UI = False` |
| `addExtraWidgets(layout)` | **add a custom button without breaking anything** — called after the auto-generated GUI |
| `collectArgs()` | transform values before sending |
| `prepareInputFile(workspace)` | produce the file to upload (exotic cases) |
| `handleResult(result)` | custom result display |

`addExtraWidgets` matters: it is what guarantees the "adding a button is simple" criterion. Make
sure overriding `setup()` is never necessary.

---

## `formgen.py` — GUI generated from the schema

The server is the **single source of truth** for the schema. No more `.ui` files, no more
client/server drift: adding a field to a tool server-side makes it appear in Slicer without
touching the client. This is what satisfies the "adding a text field = zero lines" criterion.

Type → widget mapping:

| Schema `type` | Qt widget |
|---|---|
| `str` | `QLineEdit` |
| `int` | `QSpinBox` |
| `float` | `QDoubleSpinBox` |
| `bool` | `QCheckBox` |
| `file` | `ctkPathLineEdit` |
| (unknown) | `QLineEdit` + warning in the log |

Expected API:

```python
build(arguments_schema, layout) -> dict[str, QWidget]
collect(arg_widgets) -> dict[str, str]
all_required_filled(arg_widgets, arguments_schema) -> bool
connect_changed(widget, callback) -> None
```

- The schema's `description` becomes the widget's tooltip.
- `required: true` fields are visually marked (asterisk or bold label — see `design.py`).
- `all_required_filled` replaces the hard-coded check at line 398 of the old code.

**Escape hatch to plan for:** if ergonomics one day demand a hand-written `.ui` (grouping fields, an
MRML node selector, default values), design `collect()` so it can read widgets carrying a Qt dynamic
property `serverArgName` — the same mechanism as the `SlicerParameterName` already used in the
repo's `.ui` files. Document it, but don't use it for SurgMovPred.

---

## `design.py` — styling refactor

**You have full latitude to refactor the visual layer completely.** The 260 lines of CSS in
`_getStyleSheet` / `_applyLabelStyleSheets` / `_applyButtonStyleSheets` are duplicated nearly
verbatim across most modules in the repo. It is the worst duplication in the project.

Expected:

- A **single design class/module** centralizing colors, spacing, fonts, and dark/light mode support
  (`_isDarkMode` must exist in exactly one place).
- **Named tokens** instead of hard-coded values scattered around: a palette (`PRIMARY`, `DANGER`,
  `TEXT_MUTED`, `BORDER`, ...) and spacing scale, resolved per theme.
- **Styled-widget factories** so modules never write CSS: `design.primary_button("Apply")`,
  `design.danger_button("Cancel")`, `design.section_title("Inputs")`, `design.status_badge()`,
  `design.required_label("threshold")`.
- A `design.apply(widget)` function that applies the theme to a widget tree.
- The theme must recompute if the user switches mode inside Slicer.

The test: **changing the primary button color across the whole extension should require editing one
line.**

On the visual result itself, aim for something restrained and consistent with Slicer's native look —
don't invent a design language that clashes with the rest of the application. Prioritize legibility
and consistency over originality.

---

## `worker.py` — async, the critical piece

`requests.post` with `timeout=600` **blocks the Slicer UI**. Left as-is, Slicer freezes for up to
10 minutes and the user assumes it crashed.

Hard constraint: **never touch the MRML scene from a secondary thread.**

Safe pattern to implement: the worker thread pushes the result (or the exception) into a
`queue.Queue`; a `qt.QTimer` on the main thread drains it every ~100 ms and invokes
`on_success` / `on_error`. Everything touching `slicer.*` therefore runs on the main thread.

Also provide a non-modal `QProgressDialog` or a status label fed by `progress_cb`, and a working
Cancel button (at minimum: abandon the client-side wait and re-enable the UI).

---

## `slicer_io.py` — the Slicer bridge, isolated

- `TempWorkspace`: context manager creating a temp dir and removing it in `__exit__`, **including on
  exception**. Every temporary file (export, zip, result) goes through it.
- `export_volume(volume_node, dest_path)`: `slicer.util.saveNode`, raises on failure.
- `zip_folder(folder, dest_path)`.
- `load_result(path, kind)`: dispatch table to `loadSegmentation` / `loadVolume` / `loadModel` /
  `loadTransform`.

---

## SurgMovPred special case: folder input

Note that SurgMovPred does not fit the typical "3D volume in → segmentation out" pattern. It works
on **folders**:

- `inputFolder`: a folder of `.csv` / `.xlsx` / `.ods` files (cephalometric measurements);
- `modelPath`: a folder of `joblib` models;
- `outputFolder`: where results are written.

Consequences:

1. **`modelPath` disappears from the client.** It is server configuration. The widget must no longer
   expose a model selector or download anything.
2. The API allows **only one file under the reserved key `file`**. The input folder must therefore
   be **zipped client-side** (`INPUT_MODE = "folder_zip"`) and unzipped server-side.
3. `outputFolder` stays client-side: that's where the returned raw bytes get written.

**Call this out explicitly in `ARCHITECTURE.md`:** if several tools end up needing two distinct
inputs (a scan plus landmarks, say), it is better to negotiate a `files={"file_1": ..., "file_2":
...}` convention with the server now than to keep inventing ad-hoc zips. Don't implement it, but
document the limitation and the recommended fix.

Server-side (out of scope here, but worth noting in the docs): `SurgMovPred_CLI.py` already exposes
a `main(args)` taking `inputFolder` / `modelPath` / `outputFolder`. The server wrapper only needs to
create a temp dir, unzip the input, inject `modelPath` from its own config, call `main()`, and
re-zip the output. **No rewrite of the business logic.**

---

## Build system

- `ServerToolsCoreLib` is a **Python package, not a Slicer module**. It must be installed into
  `${Slicer_QTSCRIPTEDMODULES_LIB_DIR}` via CMake, and **must not** be declared with
  `slicerMacroBuildScriptedModule` — otherwise Slicer will try to turn every file into a module.
- The `ServerToolsCore.py` shell (with `parent.hidden = True`) exists solely to guarantee the folder
  lands on Slicer's `sys.path` at load time.
- Verify that `import ServerToolsCoreLib` works from a scripted module after installation.
- Update the root `CMakeLists.txt` and the `SurgMovPred` one.

---

## Deliverables

1. The complete, working `ServerToolsCore/` tree.
2. `SurgMovPred/SurgMovPred.py` rewritten (~45 lines), `.ui` deleted.
3. Updated `CMakeLists.txt` files (root, `ServerToolsCore`, `SurgMovPred`).
4. **`ARCHITECTURE.md`** at the root: the dependency diagram, the "client knows no Qt / widget knows
   no HTTP" rule, and above all a section **"How to add a new module in 5 minutes"** with a complete
   copy-pasteable example (use AMASSS: volume in, segmentation out).
5. A few unit tests for `client.py` (mocked `requests`, outside Slicer).
6. A list of debatable decisions and known limitations (single-file constraint, `/tools` cache never
   auto-invalidated, no true server-side Cancel, ...).

## What not to do

- Don't add any Python dependency beyond `requests` / `slicer` / `qt` / `vtk` / stdlib.
- Don't reintroduce runtime package installation (`pip install` at runtime).
- Don't duplicate CSS in the modules.
- Don't put HTTP logic in widgets, or `slicer.*` calls in `client.py`.
- Don't migrate the other modules in this pass.
- Don't log the token or the contents of arguments/files.