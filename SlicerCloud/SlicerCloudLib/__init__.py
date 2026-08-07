"""Support package for the Slicer Cloud module.

Only `deploy` lives here, and it imports neither `slicer` nor `qt` — see
ARCHITECTURE.md's dependency rule and `Testing/Python/test_deploy.py`, which
runs it under plain `python3 -m unittest`.
"""

from .deploy import (
    DEFAULT_BRANCH,
    DEFAULT_INSTALL_DIR,
    DEFAULT_REPO_URL,
    DEFAULT_SERVER_URL,
    DeploymentError,
    LocalServerDeployment,
    find_python,
    probe_host,
)

__all__ = [
    "LocalServerDeployment",
    "DeploymentError",
    "probe_host",
    "find_python",
    "DEFAULT_REPO_URL",
    "DEFAULT_BRANCH",
    "DEFAULT_INSTALL_DIR",
    "DEFAULT_SERVER_URL",
]
