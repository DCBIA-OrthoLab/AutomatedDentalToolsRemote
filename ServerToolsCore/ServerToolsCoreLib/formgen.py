"""Builds Qt widgets from a server tool's argument schema, and reads them back.

Imports neither `requests` nor anything HTTP — see ARCHITECTURE.md dependency
rule. The server is the single source of truth for the schema: adding a field
to a tool server-side makes it appear here without touching any module code.

File-type arguments (any type accepted by `is_file_type` — "file", "zip_file",
"nifti_file", ...) are skipped by build()/collect(): they are not generic
scalar fields, they get their own row in base_widget's "Inputs" section. The
*widget* for such an input is still built here (`file_widget`), so that every
"schema shape -> Qt widget" decision lives in one file.

So is the translation from the server's vocabulary to the one base_widget acts
on — `file_input_modes`, `auto_file_mode`, `result_kind_for` — for the same
reason: it is all "what does the schema say this panel should be". A module
then declares only what the schema *cannot* say (see file_input_modes).

Two schema types render as several widgets rather than one, so they get a small
Python holder class each (`MultiChoiceGroup`, `FileOrFolderInput`) instead of a
QWidget subclass — PythonQt makes subclassing awkward, and everything the rest
of this module needs fits in a plain object exposing `container` for layout.

Escape hatch: a hand-written .ui can still be used by giving its widgets a Qt
dynamic property named "serverArgName" matching the schema argument name —
collect() will pick them up as if they had been generated. Not used by
SurgMovPred; documented for future modules that need custom layout.
"""

import logging
import os

import ctk
import qt

from . import accepts_folder, argument_types, design, file_extensions_for, is_file_type

logger = logging.getLogger("ServerToolsCore.formgen")

ARG_NAME_PROPERTY = "serverArgName"

# The two browse buttons of an argument accepting a file or a folder. Which of
# the two the user ends up giving is read back from the path, not from these.
BROWSE_FILE_LABEL = "File..."
BROWSE_FOLDER_LABEL = "Folder..."
PATH_PLACEHOLDER = "Select a file or a folder"


class MultiChoiceGroup:
    """The stack of checkboxes rendered for a `"multichoice"` argument.

    Holds one QCheckBox per option, in the schema's declaration order (the
    order `choices` arrives in — never sorted), and reads back the *complete*
    {option: checked} state. Sending the full state is required, not a
    convenience: see ToolServerClient._stringify for why a missing option is
    not the same as an unchecked one.
    """

    def __init__(self, choices: dict):
        self.container = qt.QWidget()
        box_layout = qt.QVBoxLayout(self.container)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(design.SPACING_XS)

        self.boxes = {}
        for option, checked in choices.items():
            box = qt.QCheckBox(option)
            box.setChecked(bool(checked))
            box_layout.addWidget(box)
            self.boxes[option] = box

    def value(self) -> dict:
        return {option: box.isChecked() for option, box in self.boxes.items()}

    # -- the slice of the QWidget API build()/base_widget use on a field ----

    def setProperty(self, name, value) -> None:
        self.container.setProperty(name, value)

    def setToolTip(self, text) -> None:
        self.container.setToolTip(text)


class FileOrFolderInput:
    """One input row for a file argument that also accepts a whole folder —
    `types` containing "folder", e.g. example_tool's `input`:
    `["csv_file", "folder"]`.

    HTTP has no notion of a folder, so a folder selection is zipped before
    upload (base_widget._prepareOneInputFile); the server sees an archive,
    extracts it, and strips a lone root directory if there is one — so whether
    the zip holds `cohort/a.csv` or `a.csv` makes no difference.

    **The user never declares which of the two they are providing**: there is
    one path field, and `is_folder()` answers from the path itself. Asking
    first was not just an extra click, it was a source of wrong requests — a
    folder pasted into a field set to "File" was uploaded as if it were one,
    and failed at `open()` with an unhelpful error.

    This is a plain QLineEdit with its own two browse buttons rather than a
    ctkPathLineEdit, and that is forced by ctkPathLineEdit's behavior, not a
    matter of taste. It emits `currentPathChanged` only for input its name
    filters accept, so restricting a picker to `*.csv` — which the schema asks
    for, `types` naming the accepted extensions — silently swallows the change
    signal for **every folder** (measured against Slicer 5.13: with a `*.csv`
    filter, only the `.csv` selections of a file/folder/file/xlsx sequence
    notify; filter order changes nothing). The Apply button would then never
    enable after picking a folder. Driving both dialogs here keeps the file
    dialog filtered by the declared extensions *and* every selection
    observable.
    """

    def __init__(self, extensions=()):
        self._extensions = tuple(extensions)

        self.container = qt.QWidget()
        row_layout = qt.QHBoxLayout(self.container)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(design.SPACING_XS)

        self.pathEdit = qt.QLineEdit()
        self.pathEdit.setPlaceholderText(PATH_PLACEHOLDER)
        self.fileButton = qt.QPushButton(BROWSE_FILE_LABEL)
        self.folderButton = qt.QPushButton(BROWSE_FOLDER_LABEL)
        row_layout.addWidget(self.pathEdit, 1)
        row_layout.addWidget(self.fileButton)
        row_layout.addWidget(self.folderButton)

        self.fileButton.clicked.connect(self._onBrowseFile)
        self.folderButton.clicked.connect(self._onBrowseFolder)

    @property
    def currentPath(self) -> str:
        """Same name as ctkPathLineEdit's, so base_widget's readiness check
        treats this field like any other path input."""
        return self.pathEdit.text.strip()

    def is_folder(self) -> bool:
        """Whether what the user picked is a folder — read off the filesystem,
        never off a mode the user had to set correctly beforehand."""
        path = self.currentPath
        return bool(path) and os.path.isdir(path)

    def _onBrowseFile(self) -> None:
        path = qt.QFileDialog.getOpenFileName(
            self.container, BROWSE_FILE_LABEL, self.currentPath, ";;".join(name_filters(self._extensions))
        )
        if path:
            self.pathEdit.setText(path)

    def _onBrowseFolder(self) -> None:
        folder = qt.QFileDialog.getExistingDirectory(self.container, BROWSE_FOLDER_LABEL, self.currentPath)
        if folder:
            self.pathEdit.setText(folder)

    # -- the slice of the QWidget API build()/base_widget use on a field ----

    def setProperty(self, name, value) -> None:
        self.container.setProperty(name, value)

    def setToolTip(self, text) -> None:
        self.container.setToolTip(text)


def row_widget(field):
    """The QWidget to put in a form row for `field` — composite fields lay
    several widgets out inside a container."""
    return getattr(field, "container", field)


def build(arguments_schema: dict, layout) -> dict:
    """Add one row per non-file argument to `layout` (a qt.QFormLayout). Returns
    {arg_name: widget}."""
    widgets = {}
    for name, spec in arguments_schema.items():
        if is_file_type(spec.get("type", "")):
            continue

        widget = _make_widget(name, spec)
        widget.setProperty(ARG_NAME_PROPERTY, name)
        description = spec.get("description")
        if description:
            widget.setToolTip(description)

        label = design.required_label(name) if spec.get("required") else design.section_title(name)
        layout.addRow(label, row_widget(widget))
        widgets[name] = widget
    return widgets


def _make_widget(name: str, spec: dict):
    arg_type = spec.get("type", "str")

    # A scalar argument flagged server_selectable (e.g. SurgMovPred's
    # "model": the *name* of a model hosted on the server) is a choice among
    # server-side files, not free text: render a dropdown. base_widget
    # populates it from GET /tools/{tool}/data once the schema is known —
    # formgen itself never talks HTTP (dependency rule, see ARCHITECTURE.md).
    # Checked before the type so a server-filled dropdown is never overwritten
    # with a schema-declared choice list.
    if spec.get("server_selectable"):
        return qt.QComboBox()

    if arg_type == "str":
        return qt.QLineEdit()
    if arg_type == "int":
        widget = qt.QSpinBox()
        widget.setRange(-2147483648, 2147483647)
        return widget
    if arg_type == "float":
        widget = qt.QDoubleSpinBox()
        widget.setRange(-1e12, 1e12)
        widget.setDecimals(6)
        return widget
    if arg_type == "bool":
        return qt.QCheckBox()
    if arg_type == "choice":
        return _make_choice_widget(name, spec)
    if arg_type == "multichoice":
        return MultiChoiceGroup(_choices(name, spec))
    if is_file_type(arg_type):
        return file_widget(spec)

    logger.warning("Unknown argument type '%s' for '%s', falling back to QLineEdit", arg_type, name)
    return qt.QLineEdit()


def _make_choice_widget(name: str, spec: dict):
    """A `"choice"` argument: one option among `choices`, whose single true
    entry is the server's declared default."""
    choices = _choices(name, spec)
    options = list(choices)

    widget = qt.QComboBox()
    widget.addItems(options)
    selected = [option for option, on in choices.items() if on]
    if selected:
        widget.setCurrentIndex(options.index(selected[0]))
    return widget


# What each single-kind file-input mode means for a ctkPathLineEdit. There is
# deliberately no "file_or_folder" entry: an argument accepting both is a
# FileOrFolderInput, for the reasons spelled out in that class.
_PATH_FILTERS = {
    "single_file": ctk.ctkPathLineEdit.Files,
    "folder_zip": ctk.ctkPathLineEdit.Dirs,
}


def path_widget(extensions=(), mode: str = "single_file"):
    """A ctkPathLineEdit for one file-input mode, restricted to `extensions`
    where that applies.

    A ctkPathLineEdit is configured **once, here, at construction**, and never
    touched again: re-assigning `nameFilters` on a live one corrupts it and
    takes Slicer down with it — reproduced against Slicer 5.13, and the reason
    the mode is a constructor argument rather than something the widget
    switches between later. Hence also the `if`: an unrestricted picker is left
    with its default rather than handed an empty list.
    """
    widget = ctk.ctkPathLineEdit()
    widget.filters = _PATH_FILTERS.get(mode, ctk.ctkPathLineEdit.Files)
    if mode != "folder_zip" and extensions:
        widget.nameFilters = name_filters(extensions)
    return widget


def auto_file_mode(spec: dict) -> str:
    """Which kind of picker a file argument gets, from what its `types` accept.

    The general rule, in one place: an argument accepting "folder" may be given
    a whole folder (zipped before upload); one accepting a file type as well
    gets the choice between the two. Returns a base_widget FILE_INPUTS mode,
    because the answer is needed twice — to build the widget, and again at
    upload time to know whether to zip (see base_widget._prepareOneInputFile).
    """
    if not accepts_folder(spec):
        return "single_file"
    if any(is_file_type(type_name) for type_name in argument_types(spec)):
        return "file_or_folder"
    return "folder_zip"


def file_input_modes(arguments_schema: dict, overrides=None) -> dict:
    """`{argument_name: mode}` for every file argument the client provides, in
    schema order.

    **Which arguments those are is the schema's answer, not a module's**: every
    file-typed argument gets an input row. A module's `FILE_INPUTS` is merged
    on top and only has to say what the schema cannot express —

    - `"volume_node"`: filled from a node in the MRML scene rather than from
      disk. The server does not know a scene exists;
    - a forced `"folder_zip"`/`"single_file"`: SurgMovPred's `input` is typed
      `zip_file`, and the module still wants to hand the user a folder picker
      and zip it client-side. "Give me a zip" is the contract; "let them pick a
      folder" is an ergonomics decision that lives here;
    - `"none"`: an optional file argument this module deliberately doesn't
      offer.

    Everything else stays `"auto"` and is resolved by `auto_file_mode`.
    """
    modes = {
        name: "auto"
        for name, spec in arguments_schema.items()
        if is_file_type(spec.get("type", ""))
    }
    modes.update(overrides or {})

    resolved = {}
    for name, mode in modes.items():
        if mode == "none":
            continue
        resolved[name] = auto_file_mode(arguments_schema.get(name, {})) if mode == "auto" else mode
    return resolved


# How a tool's server-side `output_kind` maps onto the client's RESULT_KIND.
_RESULT_KIND_FOR_OUTPUT = {
    "text": "text",
    "segmentation": "segmentation",
    "file": "save_as",
    "files": "save_as",
}


def result_kind_for(output_kind, declared=None) -> str:
    """The client's RESULT_KIND for a tool's declared `output_kind`.

    Three of the server's four output kinds settle the question on their own:
    `text` is text, `segmentation` is a segmentation, and `files` can only be
    saved (a zip of several files cannot become one MRML node).

    **`file` is the one genuinely ambiguous case**: the server says a single
    file comes back, it cannot say whether that file is meant to be loaded into
    the scene as a volume or as a mesh, or just written to disk — that is MRML
    knowledge, and the server has no business holding it. It defaults to
    `save_as`, and a module wanting the result loaded declares
    `RESULT_KIND = "volume"` / `"model"`. A declared value always wins.
    """
    return declared or _RESULT_KIND_FOR_OUTPUT.get(output_kind, "text")


def file_widget(spec: dict, mode: str = "auto"):
    """The picker for a file argument. `mode` defaults to the schema-driven
    rule above; base_widget passes an explicit one for what the schema cannot
    express (or to force a single selection kind).

    Kept here (rather than in base_widget) so every "schema shape -> Qt widget"
    decision lives in one file; `build()` itself never emits one — see the
    module docstring and FILE_INPUTS.
    """
    if mode == "auto":
        mode = auto_file_mode(spec)

    extensions = file_extensions_for(spec)
    if mode == "file_or_folder":
        return FileOrFolderInput(extensions)
    return path_widget(extensions, mode)


def _choices(name: str, spec: dict) -> dict:
    """`choices` is a {option: initially_selected} dict, and its key order is
    the declaration order — preserved as-is, never sorted."""
    choices = spec.get("choices")
    if not choices:
        logger.warning("Argument '%s' is a '%s' but declares no choices", name, spec.get("type"))
        return {}
    return choices


def name_filters(extensions) -> list:
    """Qt name filters for a file picker restricted to `extensions` (an empty
    list — no restriction — when it is empty)."""
    if not extensions:
        return []
    patterns = " ".join(f"*{extension}" for extension in extensions)
    return [f"Supported files ({patterns})", "All files (*)"]


def collect(arg_widgets: dict) -> dict:
    return {name: _read_widget(widget) for name, widget in arg_widgets.items()}


def _read_widget(widget):
    if isinstance(widget, MultiChoiceGroup):
        # The complete state of every box, including the unchecked ones — the
        # server reads what it receives as the selection itself. Encoding it
        # for the wire is client.py's job (JSON, never the `a,b` shortcut).
        return widget.value()
    if isinstance(widget, qt.QCheckBox):
        return widget.isChecked()
    if isinstance(widget, qt.QComboBox):
        # The selected option's name for a "choice" argument, sent in clear.
        # "" while a server-side list hasn't been loaded (or is empty) — which
        # keeps all_required_filled() False and the Apply button disabled.
        return widget.currentText
    if isinstance(widget, (qt.QSpinBox, qt.QDoubleSpinBox)):
        return widget.value
    if isinstance(widget, ctk.ctkPathLineEdit):
        return widget.currentPath
    if isinstance(widget, qt.QLineEdit):
        return widget.text
    raise TypeError(f"Don't know how to read value from widget {widget!r}")


def all_required_filled(arg_widgets: dict, arguments_schema: dict) -> bool:
    for name, spec in arguments_schema.items():
        if is_file_type(spec.get("type", "")) or not spec.get("required"):
            continue
        widget = arg_widgets.get(name)
        if widget is None:
            return False
        value = _read_widget(widget)
        # A multichoice reads as a dict and is always "filled": every box
        # unchecked is a meaningful selection, not a missing value.
        if value in ("", None):
            return False
    return True


def connect_changed(widget, callback) -> None:
    if isinstance(widget, MultiChoiceGroup):
        for box in widget.boxes.values():
            box.toggled.connect(callback)
    elif isinstance(widget, FileOrFolderInput):
        # Both buttons write into the same field, so one connection covers
        # browsing either kind as well as typing or pasting a path.
        widget.pathEdit.textChanged.connect(callback)
    elif isinstance(widget, qt.QCheckBox):
        widget.toggled.connect(callback)
    elif isinstance(widget, qt.QComboBox):
        widget.currentTextChanged.connect(callback)
    elif isinstance(widget, (qt.QSpinBox, qt.QDoubleSpinBox)):
        widget.valueChanged.connect(callback)
    elif isinstance(widget, ctk.ctkPathLineEdit):
        widget.currentPathChanged.connect(callback)
    elif isinstance(widget, qt.QLineEdit):
        widget.textChanged.connect(callback)
    else:
        logger.warning("Don't know how to connect change signal for widget %r", widget)
