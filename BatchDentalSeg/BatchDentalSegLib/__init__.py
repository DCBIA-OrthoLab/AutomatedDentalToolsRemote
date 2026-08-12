"""Helpers for the BatchDentalSeg module's panel.

Only `results` lives here, and deliberately: it is the half of the module that
does not need Slicer, so it can be unit-tested outside one. Everything that
touches MRML stays in BatchDentalSeg.py.
"""

from . import results  # noqa: F401
