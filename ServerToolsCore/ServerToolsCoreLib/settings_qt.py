"""Persists a user-editable override of config.py's defaults via Slicer's
native qt.QSettings (an ini/plist file on disk, independent of the Slicer
process - survives restarts).

Not imported by `__init__.py` on purpose: it depends on `qt`, and the package
must stay importable outside Slicer for client.py's unit tests. Only Slicer-
side code (ServerToolsCore.py at startup, ServerToolsSettingsWidget) uses it.

`config.py` remains the compiled-in defaults; this module is the optional
layer on top, edited via the "Server Tools Settings" module.
"""

import qt

_GROUP = "ServerTools"
_KEY_SERVER_URL = f"{_GROUP}/ServerUrl"
_KEY_API_TOKEN = f"{_GROUP}/ApiToken"
_KEY_VERIFY_TLS = f"{_GROUP}/VerifyTls"
_KEY_TIMEOUT = f"{_GROUP}/Timeout"


def load_overrides() -> dict:
    """Return only the settings the user has actually saved, e.g. {} if none."""
    settings = qt.QSettings()
    overrides = {}
    if settings.contains(_KEY_SERVER_URL):
        overrides["server_url"] = str(settings.value(_KEY_SERVER_URL))
    if settings.contains(_KEY_API_TOKEN):
        overrides["token"] = str(settings.value(_KEY_API_TOKEN))
    if settings.contains(_KEY_VERIFY_TLS):
        overrides["verify_tls"] = bool(settings.value(_KEY_VERIFY_TLS, True))
    if settings.contains(_KEY_TIMEOUT):
        overrides["timeout"] = int(settings.value(_KEY_TIMEOUT, 600))
    return overrides


def save_overrides(server_url: str, token: str, verify_tls: bool, timeout: int) -> None:
    settings = qt.QSettings()
    settings.setValue(_KEY_SERVER_URL, server_url)
    settings.setValue(_KEY_API_TOKEN, token)
    settings.setValue(_KEY_VERIFY_TLS, verify_tls)
    settings.setValue(_KEY_TIMEOUT, timeout)
    settings.sync()


def clear_overrides() -> None:
    settings = qt.QSettings()
    settings.remove(_GROUP)
    settings.sync()


def apply_saved_overrides(client) -> bool:
    """Apply whatever was saved onto `client` (e.g. get_client()). Returns
    whether an override was found and applied - used at Slicer startup."""
    overrides = load_overrides()
    if overrides:
        client.configure(**overrides)
    return bool(overrides)
