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

# The collapsible box an argument declaring no `section` goes into — i.e. the
# single box every tool's panel is today.
DEFAULT_SECTION = "Inputs"

# Options per row inside a "tabs" tab. Fixed rather than computed from the
# panel width: the module panel is resizable and a reflow on every drag would
# move check boxes under the user's cursor mid-click.
_TAB_COLUMNS = 4

# Where the leftovers go when `groups` doesn't mention every option. The server
# rejects a group naming an option that doesn't exist, but not the reverse —
# and silently dropping an option would mean the user cannot select something
# the tool offers.
_UNGROUPED_LABEL = "Other"

SELECT_ALL_LABEL = "All"
SELECT_NONE_LABEL = "None"
SELECT_DEFAULT_LABEL = "Default"

# Leads the dropdown of an OPTIONAL scalar `server_selectable` argument, and
# reads back as "" so collectArgs drops the argument entirely and the server
# applies its own rule.
#
# It exists because a QComboBox cannot be empty: `addItems` selects index 0 the
# moment the list arrives, so an optional argument whose schema says "leave
# empty and the server decides" (ALI's `model`, ASO's `landmark_models`) had no
# way to be left empty — the first hosted name was submitted by a user who
# never chose it. For ASO that list is DATA/ASO/models/, which holds reference
# bundles next to weight bundles, so the silent default was routinely a
# reference and the run died on "No CBCT landmark weights found in ...".
#
# Only for OPTIONAL arguments: a required one has no server-side fallback to
# defer to, so offering the entry would only produce a 422.
AUTOMATIC_OPTION = "(automatic — the server chooses)"

# The two browse buttons of an argument accepting a file or a folder. Which of
# the two the user ends up giving is read back from the path, not from these.
BROWSE_FILE_LABEL = "File..."
BROWSE_FOLDER_LABEL = "Folder..."
PATH_PLACEHOLDER = "Select a file or a folder"


class MultiChoiceGroup:
    """The checkboxes rendered for a `"multichoice"` argument.

    Holds one QCheckBox per option, in the schema's declaration order (the
    order `choices` arrives in — never sorted), and reads back the *complete*
    {option: checked} state. Sending the full state is required, not a
    convenience: see ToolServerClient._stringify for why a missing option is
    not the same as an unchecked one.

    The argument's `description` is rendered as a visible wrapped hint above
    the boxes, not only as a tooltip. A group of check boxes is the one widget
    whose meaning routinely does not fit in its label — ALI's `cbct_regions`
    and `ios_networks` are both always shown and only one applies to any given
    input, and the server says which in its description ("CBCT only: ...").
    A tooltip nobody hovers is not where that belongs.

    **`layout` and `groups` change only where the boxes are put.** `self.boxes`
    is keyed and ordered by `choices` whatever the layout, so `value()`,
    `collect()`, `connect_changed()` and `all_required_filled()` cannot tell
    the four apart — which is what makes the layouts safe to add: a wrong one
    is ugly, never wrong on the wire. See `LAYOUTS` for what each does and the
    server's `ArgSpec.ui` for why they exist at all.
    """

    def __init__(self, choices: dict, description: str = "", layout=None, groups=None):
        self.container = qt.QWidget()
        column = qt.QVBoxLayout(self.container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(design.SPACING_XS)

        if description:
            column.addWidget(design.hint_label(description))

        # The state the server declared, kept for the "Default" button — which
        # is the old ASO module's per-mode `Suggest()` button, now on every
        # multichoice of every tool and with the suggestion living server-side.
        self._defaults = dict(choices)

        builder = _LAYOUT_BUILDERS.get(layout)
        if builder is None:
            if layout is not None:
                logger.warning(
                    "Unknown multichoice layout '%s', falling back to a single column", layout
                )
            builder = _build_flat_boxes
        made = builder(column, choices, groups)

        # Declaration order, whatever order the layout visited the options in.
        self.boxes = {option: made[option] for option in choices}

        if len(choices) > 1:
            column.addWidget(self._selectionToolbar())

    def _selectionToolbar(self):
        """All / None / Default. Cheap here, and the difference between usable
        and not once an argument publishes 130 options: without it, restoring
        the server's suggested selection means remembering and re-ticking it by
        hand."""
        bar = qt.QWidget()
        row = qt.QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(design.SPACING_XS)
        row.addStretch(1)
        for label, action in (
            (SELECT_ALL_LABEL, lambda: self.setAll(True)),
            (SELECT_NONE_LABEL, lambda: self.setAll(False)),
            (SELECT_DEFAULT_LABEL, self.restoreDefaults),
        ):
            button = design.link_button(label)
            button.clicked.connect(action)
            row.addWidget(button)
        return bar

    def setAll(self, checked: bool) -> None:
        for box in self.boxes.values():
            box.setChecked(checked)

    def restoreDefaults(self) -> None:
        for option, box in self.boxes.items():
            box.setChecked(bool(self._defaults.get(option)))

    def value(self) -> dict:
        return {option: box.isChecked() for option, box in self.boxes.items()}

    # -- the slice of the QWidget API build()/base_widget use on a field ----

    def setProperty(self, name, value) -> None:
        self.container.setProperty(name, value)

    def setToolTip(self, text) -> None:
        self.container.setToolTip(text)


def _make_box(option: str, checked) -> qt.QCheckBox:
    box = qt.QCheckBox(option)
    box.setChecked(bool(checked))
    return box


def _grouped(choices: dict, groups) -> list:
    """[(group name, [option, ...])] — the declared groups, then whatever they
    left out. Options keep `choices` order within each group, so a group
    listing them in a different order does not reorder the display."""
    if not groups:
        return [("", list(choices))]

    claimed = {option for options in groups.values() for option in options}
    grouped = [
        (name, [option for option in choices if option in set(options)])
        for name, options in groups.items()
    ]
    leftovers = [option for option in choices if option not in claimed]
    if leftovers:
        grouped.append((_UNGROUPED_LABEL, leftovers))
    return [(name, options) for name, options in grouped if options]


def _build_flat_boxes(column, choices: dict, _groups=None) -> dict:
    """One box per line. The default, and what every tool declaring no `ui`
    gets — unchanged from before layouts existed."""
    boxes = {}
    for option, checked in choices.items():
        boxes[option] = _make_box(option, checked)
        column.addWidget(boxes[option])
    return boxes


def _build_inline_boxes(column, choices: dict, _groups=None) -> dict:
    """One horizontal row. For a handful of short options (ASO's two jaws, its
    eight landmark types) that waste a line each stacked vertically."""
    row_container = qt.QWidget()
    row = qt.QHBoxLayout(row_container)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(design.SPACING_MD)

    boxes = {}
    for option, checked in choices.items():
        boxes[option] = _make_box(option, checked)
        row.addWidget(boxes[option])
    row.addStretch(1)

    column.addWidget(row_container)
    return boxes


def _build_grid_boxes(column, choices: dict, groups=None) -> dict:
    """One row per group, options as columns — the chart layout.

    For options whose *position* carries meaning: ASO asks for teeth "spread
    across the arch", and a column of 32 check boxes is the one layout that
    cannot show whether a selection is spread or clustered.

    Sixteen teeth do not fit in a Slicer module panel, so the grid scrolls
    horizontally rather than being squeezed or wrapped — wrapping an arch onto
    two lines would destroy the very adjacency the layout exists to show. The
    old module did the same (`ASO.ui`'s scrollArea around LayoutSemiIOS_tooth).
    """
    grid_container = qt.QWidget()
    grid = qt.QGridLayout(grid_container)
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setSpacing(design.SPACING_XS)

    boxes = {}
    for row_index, (group_name, options) in enumerate(_grouped(choices, groups)):
        if group_name:
            grid.addWidget(design.hint_label(group_name), row_index, 0)
        for offset, option in enumerate(options):
            boxes[option] = _make_box(option, choices[option])
            grid.addWidget(boxes[option], row_index, offset + 1)

    column.addWidget(_horizontal_scroll(grid_container))
    return boxes


def _build_tabs_boxes(column, choices: dict, groups=None) -> dict:
    """One tab per group, options in a scrollable multi-column grid.

    For a catalog too long to scroll through in one piece: ASO publishes 130
    CBCT landmarks, and the grouping (cranial base / upper / lower) is how the
    people who use them already think about them — the server sends it, so the
    tabs are the server's own grouping rather than a client-side guess.
    """
    tabs = qt.QTabWidget()
    boxes = {}
    for group_name, options in _grouped(choices, groups):
        page = qt.QWidget()
        grid = qt.QGridLayout(page)
        grid.setContentsMargins(design.SPACING_SM, design.SPACING_SM, design.SPACING_SM, design.SPACING_SM)
        grid.setSpacing(design.SPACING_XS)
        for index, option in enumerate(options):
            boxes[option] = _make_box(option, choices[option])
            grid.addWidget(boxes[option], index // _TAB_COLUMNS, index % _TAB_COLUMNS)
        tabs.addTab(_vertical_scroll(page), group_name or _UNGROUPED_LABEL)

    column.addWidget(tabs)
    return boxes


def _horizontal_scroll(widget):
    area = qt.QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setVerticalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
    # Without this the area collapses to a couple of pixels: a QScrollArea's
    # size hint ignores its child, so it has to be told how tall one row of
    # check boxes is.
    area.setMinimumHeight(design.CHART_MIN_HEIGHT)
    return area


def _vertical_scroll(widget):
    area = qt.QScrollArea()
    area.setWidget(widget)
    area.setWidgetResizable(True)
    area.setHorizontalScrollBarPolicy(qt.Qt.ScrollBarAlwaysOff)
    area.setMinimumHeight(design.TABS_MIN_HEIGHT)
    return area


# The server's ArgSpec.ui values. A layout it does not know about falls back to
# the flat column with a warning rather than failing the panel: a presentation
# hint from a newer server must never be able to break an older client.
_LAYOUT_BUILDERS = {
    None: _build_flat_boxes,
    "inline": _build_inline_boxes,
    "grid": _build_grid_boxes,
    "tabs": _build_tabs_boxes,
}

LAYOUTS = tuple(name for name in _LAYOUT_BUILDERS if name)


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


class ServerFileInput:
    """One input row for a file argument the SERVER can also provide by name —
    `server_selectable` on a file type, e.g. ALI's and AMASSS's `input`.

    Such an argument accepts either shape: the caller uploads its own file, or
    it sends the *name* of one the server already hosts (`GET
    /tools/<tool>/data`), which the server resolves against its read-only data
    store. The named file never travels, in either direction — which is the
    whole point for a test cohort of confidential scans.

    On the wire the two are genuinely different: an upload is a multipart file
    part, a server-side selection is a plain form value under the argument's
    own name. So this holder keeps the local picker it wraps, and answers which
    of the two the user actually chose (`server_name`).

    The two are kept mutually exclusive by clearing the other one, not by
    letting one silently win: picking a server file empties the path field, and
    typing/browsing a path resets the dropdown. A precedence rule the user
    cannot see is how you end up uploading a file you thought you had replaced.
    """

    # First entry, and the one that means "no server-side file": a combo box
    # cannot express "nothing selected" in a way a user reads as deliberate.
    UPLOAD_OPTION = "Upload my own file..."

    def __init__(self, local):
        self.local = local
        self._syncing = False

        self.container = qt.QWidget()
        column = qt.QVBoxLayout(self.container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(design.SPACING_XS)

        self.combo = qt.QComboBox()
        self.combo.addItems([self.UPLOAD_OPTION])
        column.addWidget(self.combo)
        column.addWidget(row_widget(local))

        self.combo.currentTextChanged.connect(self._onServerChoice)
        connect_changed(local, self._onLocalChoice)

    def setChoices(self, names) -> None:
        """Fill the dropdown with the server-side names, keeping the upload
        entry first. Called once the schema is known — formgen never talks
        HTTP (see ARCHITECTURE.md dependency rule)."""
        self.combo.clear()
        self.combo.addItems([self.UPLOAD_OPTION] + list(names))

    def server_name(self) -> str:
        """The chosen server-side file name, or "" when uploading."""
        text = self.combo.currentText
        return "" if text in ("", self.UPLOAD_OPTION) else text

    @property
    def currentPath(self) -> str:
        """The LOCAL path to upload — empty while a server-side file is chosen,
        so nothing is uploaded for an argument that is already satisfied."""
        return "" if self.server_name() else _local_path(self.local)

    def is_folder(self) -> bool:
        checker = getattr(self.local, "is_folder", None)
        return bool(checker()) if checker else False

    def _onServerChoice(self, _text=None) -> None:
        if self._syncing or not self.server_name():
            return
        self._syncing = True
        try:
            _set_local_path(self.local, "")
        finally:
            self._syncing = False

    def _onLocalChoice(self, *_args) -> None:
        if self._syncing or not _local_path(self.local):
            return
        self._syncing = True
        try:
            self.combo.setCurrentIndex(0)
        finally:
            self._syncing = False

    # -- the slice of the QWidget API build()/base_widget use on a field ----

    def setProperty(self, name, value) -> None:
        self.container.setProperty(name, value)

    def setToolTip(self, text) -> None:
        self.container.setToolTip(text)


def _local_path(widget) -> str:
    return (getattr(widget, "currentPath", "") or "").strip()


def _set_local_path(widget, value: str) -> None:
    """Write a path into whichever picker kind `widget` is.

    A FileOrFolderInput drives a plain QLineEdit (see that class for why it is
    not a ctkPathLineEdit); everything else exposes ctkPathLineEdit's writable
    `currentPath`.
    """
    if isinstance(widget, FileOrFolderInput):
        widget.pathEdit.setText(value)
    else:
        widget.currentPath = value


def row_widget(field):
    """The QWidget to put in a form row for `field` — composite fields lay
    several widgets out inside a container."""
    return getattr(field, "container", field)


def label_for(name: str, spec: dict) -> str:
    """The text shown next to an argument's widget.

    **The schema's `label` when it declares one**, so the words a user reads
    are the tool's own — "Scan / Landmark Folder", not something this file
    invented. The fallback prettifies the argument name and is exactly that: a
    fallback for a tool that declares none. It cannot do better than
    "Cbct landmarks" for `cbct_landmarks`, and it has no way to know that ASO's
    `input` is the folder holding both the scans and their landmarks.

    There is ONE rule and it lives here. There used to be two — `build()` used
    the raw schema name while base_widget prettified it — so a single panel
    showed "Reference" and "cbct_landmarks" one above the other.
    """
    declared = (spec.get("label") or "").strip()
    return declared or name.replace("_", " ").capitalize()


def section_of(spec: dict) -> str:
    """The collapsible box this argument belongs in. An argument declaring no
    `section` — every argument of every tool but ASO today — lands in the one
    box a panel has always had, so the grouping is opt-in per tool and no
    existing panel moves."""
    return spec.get("section") or DEFAULT_SECTION


def sections_of(arguments_schema: dict, extra=()) -> list:
    """Every distinct section a tool's arguments name, in the order they are
    first mentioned — the schema's declaration order, which is the tool
    author's intended reading order. `extra` names boxes the client adds on its
    own (the output folder), appended unless an argument already claimed them.
    """
    ordered = []
    for spec in arguments_schema.values():
        name = section_of(spec)
        if name not in ordered:
            ordered.append(name)
    for name in extra:
        if name not in ordered:
            ordered.append(name)
    return ordered


def is_visible(spec: dict, values: dict) -> bool:
    """Whether `visible_when` is satisfied by the panel's current values.

    `{"modality": "CBCT", "automation": "Fully-Automated"}` — every entry must
    match, and a tuple/list of values means "any of these". An argument
    declaring nothing is always visible.

    A controlling argument absent from `values` counts as NOT matching. That
    only happens when the schema could not be fetched (so the panel holds an
    error, not a form) or when a server declares a `visible_when` naming an
    argument it doesn't publish — which its own check_schema rejects at boot.
    Hiding is the safe answer either way: a field whose precondition cannot be
    evaluated is a field the user cannot fill in meaningfully.
    """
    conditions = spec.get("visible_when")
    if not conditions:
        return True
    for other_name, expected in conditions.items():
        if other_name not in values:
            return False
        wanted = expected if isinstance(expected, (list, tuple)) else (expected,)
        if values[other_name] not in wanted:
            return False
    return True


def controlling_arguments(arguments_schema: dict) -> set:
    """Every argument some other argument's visibility depends on — the ones
    whose change has to re-evaluate the panel."""
    return {
        other_name
        for spec in arguments_schema.values()
        for other_name in (spec.get("visible_when") or {})
    }


def build(arguments_schema: dict, layout, sections=None, rows=None) -> dict:
    """Add one row per non-file argument. Returns {arg_name: widget}.

    `layout` is a qt.QFormLayout — the single-box behavior, kept as the default
    so a caller that knows nothing about sections is unaffected. `sections` is
    {section name: QFormLayout}; when given, each argument goes to the layout
    its `section` names and `layout` is only the fallback for a section the
    caller didn't create.

    `rows`, if given, is filled with `{arg_name: (label, field)}` — the two
    widgets a caller has to show or hide together to make a row appear or
    disappear. An out-parameter rather than a second return value so the
    signature stays what every existing caller and test expects; the labels are
    created in here, and a caller cannot recover a QFormLayout's label for a
    field reliably across PythonQt versions.
    """
    widgets = {}
    for name, spec in arguments_schema.items():
        if is_file_type(spec.get("type", "")):
            continue

        widget = _make_widget(name, spec)
        widget.setProperty(ARG_NAME_PROPERTY, name)
        description = spec.get("description")
        if description:
            widget.setToolTip(description)

        text = label_for(name, spec)
        label = design.required_label(text) if spec.get("required") else design.section_title(text)
        target = (sections or {}).get(section_of(spec), layout)
        field = row_widget(widget)
        target.addRow(label, field)
        widgets[name] = widget
        if rows is not None:
            rows[name] = (label, field)
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

    # `initial` is the scalar counterpart of a choice argument's `choices`: the
    # value the SERVER wants the widget to start at. It matters because collect()
    # always sends every widget, so a field the user never touched still travels
    # — a spin box left at Qt's own 0 sent 0, never letting the tool's own
    # default apply. None means the tool declared none; leave Qt's default then.
    initial = spec.get("initial")

    if arg_type == "str":
        widget = qt.QLineEdit()
        if initial is not None:
            widget.setText(str(initial))
        return widget
    if arg_type == "int":
        widget = qt.QSpinBox()
        widget.setRange(-2147483648, 2147483647)
        if initial is not None:
            widget.setValue(int(initial))
        return widget
    if arg_type == "float":
        widget = qt.QDoubleSpinBox()
        widget.setRange(-1e12, 1e12)
        widget.setDecimals(6)
        if initial is not None:
            widget.setValue(float(initial))
        return widget
    if arg_type == "bool":
        widget = qt.QCheckBox()
        if initial is not None:
            widget.setChecked(bool(initial))
        return widget
    if arg_type == "choice":
        return _make_choice_widget(name, spec)
    if arg_type == "multichoice":
        return MultiChoiceGroup(
            _choices(name, spec),
            spec.get("description", ""),
            layout=spec.get("ui"),
            groups=spec.get("groups"),
        )
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
        local = FileOrFolderInput(extensions)
    else:
        local = path_widget(extensions, mode)

    # A file argument the server can also provide by name gets the dropdown
    # too. Only file-typed ones reach here: a SCALAR server_selectable argument
    # (a model, which must never leave the server) is a plain combo box built
    # by _make_widget, with no local picker at all.
    if spec.get("server_selectable"):
        return ServerFileInput(local)
    return local


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
        #
        # The "(automatic)" entry reads back as "" so the argument is dropped
        # rather than sent: matched on the text because that is what the entry
        # IS here, and no server-side file name nor `choices` option can
        # collide with it (both come from the server; one is a file name, the
        # other a declared option, and this string is neither).
        text = widget.currentText
        return "" if text == AUTOMATIC_OPTION else text
    if isinstance(widget, (qt.QSpinBox, qt.QDoubleSpinBox)):
        return widget.value
    if isinstance(widget, ctk.ctkPathLineEdit):
        return widget.currentPath
    if isinstance(widget, qt.QLineEdit):
        return widget.text
    raise TypeError(f"Don't know how to read value from widget {widget!r}")


def all_required_filled(arg_widgets: dict, arguments_schema: dict, hidden=()) -> bool:
    """Whether every required scalar argument holds a value.

    A `hidden` argument is skipped: it is not sent (see base_widget.collectArgs),
    so the server applies its default and an empty widget behind a hidden row
    must not be able to disable Apply forever with nothing on screen to explain
    why. No tool declares a required argument under a `visible_when` today, and
    this is what keeps that from becoming a dead-locked panel if one does.
    """
    for name, spec in arguments_schema.items():
        if is_file_type(spec.get("type", "")) or not spec.get("required") or name in hidden:
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
    elif isinstance(widget, ServerFileInput):
        # Either half can satisfy the argument, so either half changing must
        # re-evaluate whether Apply can be enabled.
        widget.combo.currentTextChanged.connect(callback)
        connect_changed(widget.local, callback)
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
