"""The Slicer bridge, isolated: MRML export, zipping, and result loading.

Nothing here speaks HTTP. Every temporary file used by a tool module (an
exported volume, a zipped folder, a downloaded result) should go through
TempWorkspace so cleanup on error is never forgotten.
"""

import logging
import os
import shutil
import tempfile
import zipfile

import slicer

logger = logging.getLogger("ServerToolsCore.slicer_io")


class TempWorkspace:
    """Context manager for a temp directory, removed on exit including on error."""

    def __init__(self, prefix="ServerTools_"):
        self._prefix = prefix
        self.path = None

    def __enter__(self):
        self.path = tempfile.mkdtemp(prefix=self._prefix)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.path and os.path.isdir(self.path):
            shutil.rmtree(self.path, ignore_errors=True)
        self.path = None
        return False

    def file(self, name: str) -> str:
        return os.path.join(self.path, name)


def export_volume(volume_node, dest_path: str) -> str:
    ok = slicer.util.saveNode(volume_node, dest_path)
    if not ok:
        raise IOError(f"Failed to export volume to {dest_path}")
    return dest_path


def is_extractable_archive(path: str) -> bool:
    """Whether `path` should be unpacked as a delivery archive.

    Deliberately extension-based, not `zipfile.is_zipfile()`: OOXML formats
    (.xlsx, .docx, .ods, .pptx, ...) are zip containers structurally, so a
    signature check would "extract" a result .xlsx into its raw XML parts
    instead of keeping it as the file it actually is. Only a genuine `.zip`
    is meant to be unpacked here.
    """
    return path.lower().endswith(".zip")


# Extensions whose bytes are already compressed. DEFLATE gains ~0% on them and
# runs at ~45 MB/s on one core, so a folder of .nii.gz scans used to spend
# seconds per 100 MB shrinking nothing -- measured 2.3s to pack 105 MB of
# gzipped CBCT into an archive of exactly the same 105 MB, before a single byte
# was sent, and the server paid it again inflating them. `.gz` covers the
# compound medical extensions (.nii.gz, .nrrd.gz, .gipl.gz); the OOXML formats
# are zip containers by design. Mirrors the server's own table in
# file_utils.py.
_STORED_EXTENSIONS = (
    ".gz", ".bz2", ".xz", ".zip", ".7z",
    ".xlsx", ".ods", ".docx", ".pptx",
    ".png", ".jpg", ".jpeg",
)

# Level 1 for everything else: it compresses at roughly twice the rate of the
# default 6 and gives up about 3% of size on the one kind of member still worth
# deflating here (binary .vtk, ~2.7:1 at either level).
_COMPRESS_LEVEL = 1


def zip_folder(folder: str, dest_path: str) -> str:
    """Pack a folder for upload, choosing the compression per member.

    A folder argument is zipped only because HTTP has no notion of a folder --
    the archive is a container, not an attempt to make the data smaller. So
    already-compressed members are STORED as-is and only what genuinely
    deflates is deflated, which is 14x faster to pack for exactly the same
    bytes on the wire.
    """
    if not os.path.isdir(folder):
        raise IOError(f"Not a folder: {folder}")
    with zipfile.ZipFile(
        dest_path, "w", zipfile.ZIP_DEFLATED, compresslevel=_COMPRESS_LEVEL
    ) as archive:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                full_path = os.path.join(root, name)
                # compress_type=None defers to the archive's default (DEFLATED
                # at _COMPRESS_LEVEL); already-compressed members opt out.
                stored = name.lower().endswith(_STORED_EXTENSIONS)
                archive.write(
                    full_path,
                    os.path.relpath(full_path, folder),
                    compress_type=zipfile.ZIP_STORED if stored else None,
                )
    return dest_path


class UnsafeArchiveError(Exception):
    """An archive member that would be written outside its destination."""


def unzip_folder(zip_path: str, dest_dir: str) -> str:
    """Unpack an archive, refusing any member that escapes `dest_dir`.

    The archive comes from our own server, and "we trust the server" is
    exactly the assumption a zip-slip check exists to remove -- the server
    applies the same check to every archive a client uploads to it. This is
    the single function both result paths unpack through (the blocking one and
    the streamed one), so the guard lives here rather than beside either.
    """
    os.makedirs(dest_dir, exist_ok=True)
    root = os.path.abspath(dest_dir)
    with zipfile.ZipFile(zip_path, "r") as archive:
        for member in archive.infolist():
            target = os.path.abspath(os.path.join(dest_dir, member.filename))
            if os.path.commonpath([root, target]) != root:
                raise UnsafeArchiveError(
                    f"Refusing an archive entry that would be written outside "
                    f"{dest_dir}: {member.filename!r}"
                )
        archive.extractall(dest_dir)
    return dest_dir


_LOADERS = {
    "segmentation": lambda path: slicer.util.loadSegmentation(path),
    "volume": lambda path: slicer.util.loadVolume(path),
    "model": lambda path: slicer.util.loadModel(path),
    "transform": lambda path: slicer.util.loadTransform(path),
}


def load_result(path: str, kind: str):
    loader = _LOADERS.get(kind)
    if loader is None:
        raise ValueError(f"No MRML loader registered for result kind '{kind}'.")
    return loader(path)
