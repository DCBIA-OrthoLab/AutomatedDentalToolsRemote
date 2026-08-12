"""What the panel does with a finished run, minus Slicer.

Everything here is pure Python: reading `BatchDentalSeg_report.json`, deciding
which of the returned volumes to load, and turning a label value into a segment
name and a colour. It imports neither `slicer` nor `qt`, for the same reason
`client.py` imports neither — that is what makes it unit-testable outside a
Slicer interpreter (see Testing/Python/test_batchdentalseg_client.py), and the
label mapping is precisely the part worth testing: getting it wrong does not
fail, it renames anatomy.

**The names are the server's, the colours are ours.** `report["labels"]` is the
table the trained weights emit and the only thing that says what an integer in
the returned volume means, so nothing here hardcodes a structure list — a model
added server-side arrives with its own table. What is client-side is
presentation: which colour each structure is drawn in, and how translucent it
is in 3D.
"""

import colorsys
import json
import logging
import os
import re

logger = logging.getLogger("BatchDentalSeg.results")

# Written by BatchDentalSegLogic.segment() into the root of the archive.
REPORT_NAME = "BatchDentalSeg_report.json"

# The extensions the tool writes a label volume as: the server keeps the
# input's own container (a .nrrd scan comes back as .nrrd.gz), so this is
# broader than "the thing nnUNet produced". Longest compound forms first, so
# `stem()` strips ".nii.gz" rather than leaving a dangling ".nii".
VOLUME_EXTENSIONS = (".nii.gz", ".nrrd.gz", ".gipl.gz", ".nii", ".nrrd", ".gipl")

# Slicer names a segment imported from a labelmap after the integer it came
# from ("Segment_5"). Parsed as a fallback only — see segment_label_value.
_TRAILING_INTEGER = re.compile(r"(\d+)$")

# A published colour is applied to a segment without further checking, so it is
# matched rather than trusted: `#RRGGBB`, nothing else.
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")

# The six structures the DentalSegmentator / PediatricDentalSeg /
# NasoMaxillaDentSeg tables share, in the colours the original
# BATCHDENTALSEG module drew them in, so a clinician moving to the remote
# module recognises their own scan. Keyed by the lowercased server-side name;
# anything else (every UniversalLab tooth, any structure a future model adds)
# gets a stable generated colour rather than a wrong one.
_NAMED_COLORS = {
    "upper skull": "#E3DD90",
    "mandible": "#D4A1E6",
    "maxilla": "#6AC4A4",
    "upper teeth": "#DC9565",
    "lower teeth": "#EBDFB4",
    "mandibular canal": "#D8654F",
}

# Drawn translucent in 3D: these enclose the teeth, and at full opacity they
# are all one sees of the result.
_TRANSLUCENT = ("upper skull", "mandible", "maxilla")
_TRANSLUCENT_OPACITY = 0.65

# The golden angle, walked in hue space. Any two consecutive label values land
# far apart on the colour wheel, so the 52 teeth of UniversalLab are told apart
# without a 52-entry table of anatomy living in this client.
_GOLDEN_RATIO_CONJUGATE = 0.618033988749895


def read_report(result_dir: str):
    """The run report, or None when there isn't a readable one.

    Never fatal: the segmentations are already on disk and are what the user
    asked for. A missing or malformed report costs them the summary and the
    segment names, not the run.
    """
    path = os.path.join(result_dir, REPORT_NAME)
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        logger.warning("Could not read %s: %s", path, exc)
        return None


def label_names(report) -> dict:
    """`{the integer the network emits: segment name}` for the model that ran.

    Inverted from `report["labels"]`, which is `{name: value}` because that is
    the direction the tool declares it in. An entry whose value is not an
    integer is dropped rather than crashing the load: the rest of the table is
    still correct, and a segment left unnamed is visibly a segment left
    unnamed.
    """
    labels = (report or {}).get("labels") or {}
    names = {}
    for name, value in labels.items():
        try:
            names[int(value)] = name
        except (TypeError, ValueError):
            logger.warning("Ignoring non-integer label value for '%s': %r", name, value)
    return names


def stem(filename: str) -> str:
    """The file name without its (possibly compound) volume extension."""
    lower = filename.lower()
    for extension in VOLUME_EXTENSIONS:
        if lower.endswith(extension):
            return filename[: -len(extension)]
    return os.path.splitext(filename)[0]


def find_segmentations(result_dir: str, suffix: str = "") -> list:
    """Every multi-label segmentation in the unpacked archive.

    `suffix` is the run's `prediction_ID`: the tool writes the label volume as
    `<scan>_<ID>.nii.gz` and, when `separate_segments` was asked for, one
    `<scan>_<ID>_<Segment-Name>.nii.gz` per structure beside it. Only the first
    kind is loaded — the per-segment masks are the same voxels split up, and
    loading them too would put every structure in the scene twice.

    A suffix that matches nothing falls back to every volume found: a report
    that could not be read is not a reason to load nothing, and the archive
    holds only results anyway.
    """
    found = []
    for root, _dirs, names in os.walk(result_dir):
        for name in sorted(names):
            if name.lower().endswith(VOLUME_EXTENSIONS):
                found.append(os.path.join(root, name))
    found.sort()

    if not suffix:
        return found
    matching = [path for path in found if stem(os.path.basename(path)).endswith(f"_{suffix}")]
    if matching:
        return matching
    if found:
        logger.warning(
            "No result file ends in '_%s'; loading all %d volume(s) found instead.",
            suffix,
            len(found),
        )
    return found


def segment_label_value(segment_id: str, index: int, declared=None) -> int:
    """Which integer of the label volume a segment came from.

    `declared` is what the segment itself reports (`vtkSegment.GetLabelValue()`
    on a Slicer recent enough to have it) and is authoritative when it is a
    positive integer. Otherwise the id Slicer built from the label value is
    parsed ("Segment_5" -> 5), and only as a last resort does position decide.

    Position is the *wrong* answer whenever a structure is absent from a scan —
    the segments are then 1, 2, 4, 5 and everything after the gap shifts by one
    — which is exactly why it is last.
    """
    try:
        value = int(declared)
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass

    match = _TRAILING_INTEGER.search(segment_id or "")
    if match:
        return int(match.group(1))
    return index + 1


def label_colors(report) -> dict:
    """`{segment name: "#RRGGBB"}` as the SERVER assigned them, or `{}`.

    The server publishes this because a mesh export bakes the colour into the
    .vtk it writes: a client picking its own would draw the segmentation in one
    colour and the surface from the same run in another. Preferring the
    report's table is what keeps the two in step, and it means a model added
    server-side arrives with its colours as well as its labels.
    """
    published = (report or {}).get("label_colors") or {}
    return {
        name: value
        for name, value in published.items()
        if isinstance(value, str) and _HEX_COLOR.match(value)
    }


def color_for(name: str, value: int, published=None) -> tuple:
    """`(r, g, b)` in 0..1 for a segment.

    `published` is `label_colors(report)` and wins when it names this segment.
    The fallback below is what runs against a server too old to publish the
    table, and it is deliberately the same rule the server uses.

    Looking the colour up by NAME rather than by value is what keeps it right
    across models: NasoMaxillaDentSeg separates the maxilla and so shifts every
    later integer, and a palette indexed by integer would recolour the mandible
    as the teeth on that one model alone.
    """
    if published:
        from_server = published.get(name)
        if from_server:
            return hex_to_rgb(from_server)
    hex_color = _NAMED_COLORS.get((name or "").strip().lower())
    if hex_color:
        return hex_to_rgb(hex_color)
    hue = (max(int(value), 0) * _GOLDEN_RATIO_CONJUGATE) % 1.0
    return colorsys.hsv_to_rgb(hue, 0.55, 0.95)


def opacity_for(name: str) -> float:
    """3D opacity: the bone shells are translucent so the teeth inside them
    are visible, which is what the segmentation is usually opened for."""
    return _TRANSLUCENT_OPACITY if (name or "").strip().lower() in _TRANSLUCENT else 1.0


def hex_to_rgb(hex_color: str) -> tuple:
    value = hex_color.lstrip("#")
    return tuple(int(value[i: i + 2], 16) / 255.0 for i in (0, 2, 4))


def failed_scans(report) -> list:
    """`[(what the scan was called, why it failed), ...]`.

    A partial run is normal and is not an error: one unreadable patient in a
    cohort of forty is reported per scan while the other thirty-nine are
    segmented. Those failures exist only in the report — on screen they look
    like scans that quietly went missing — so they are what the end-of-run
    message is built around.
    """
    return [
        (scan.get("input") or scan.get("case_id") or "?", scan.get("error") or "failed")
        for scan in (report or {}).get("scans") or []
        if scan.get("status") != "ok"
    ]
