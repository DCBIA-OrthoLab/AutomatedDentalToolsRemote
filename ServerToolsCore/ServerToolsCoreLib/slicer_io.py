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


def zip_folder(folder: str, dest_path: str) -> str:
    if not os.path.isdir(folder):
        raise IOError(f"Not a folder: {folder}")
    with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, _dirs, files in os.walk(folder):
            for name in files:
                full_path = os.path.join(root, name)
                archive.write(full_path, os.path.relpath(full_path, folder))
    return dest_path


def unzip_folder(zip_path: str, dest_dir: str) -> str:
    os.makedirs(dest_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
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
