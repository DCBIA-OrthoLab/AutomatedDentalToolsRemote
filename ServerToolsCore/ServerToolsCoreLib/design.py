"""Single source of truth for colors, spacing and styled-widget factories.

No module built on ServerToolsCore should write its own CSS. Changing the
primary color, or any other token, is a one-file edit that propagates to every
module using these factories. `_isDarkMode` (here: is_dark_mode) exists in
exactly one place in the whole extension.
"""

import qt
import slicer

SPACING_XS = 4
SPACING_SM = 6
SPACING_MD = 8
SPACING_LG = 12

_LIGHT = {
    "PRIMARY": "#3498db",
    "PRIMARY_HOVER": "#2980b9",
    "PRIMARY_PRESSED": "#1f618d",
    "DANGER": "#e74c3c",
    "DANGER_HOVER": "#c0392b",
    "DANGER_PRESSED": "#922b21",
    "SUCCESS": "#27ae60",
    "TEXT": "#2c3e50",
    "TEXT_MUTED": "#34495e",
    "BORDER": "#e0e6ed",
    "BACKGROUND": "#f8f9fa",
    "SURFACE": "#ffffff",
    "DISABLED_BG": "#bdc3c7",
    "DISABLED_TEXT": "#95a5a6",
}

_DARK = {
    "PRIMARY": "#4ba3ff",
    "PRIMARY_HOVER": "#3498db",
    "PRIMARY_PRESSED": "#2980b9",
    "DANGER": "#e74c3c",
    "DANGER_HOVER": "#ec7063",
    "DANGER_PRESSED": "#a93226",
    "SUCCESS": "#2ecc71",
    "TEXT": "#e0e0e0",
    "TEXT_MUTED": "#b0b0b0",
    "BORDER": "#454545",
    "BACKGROUND": "#2b2b2b",
    "SURFACE": "#383838",
    "DISABLED_BG": "#555555",
    "DISABLED_TEXT": "#888888",
}


def is_dark_mode() -> bool:
    try:
        palette = slicer.app.palette()
        bg = palette.color(qt.QPalette.Window)
        luminance = (0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()) / 255.0
        return luminance < 0.5
    except Exception:
        return False


def tokens() -> dict:
    """Resolved palette for the current theme. Always re-reads the app palette,
    so a mode switch takes effect the next time a factory or apply() runs."""
    return _DARK if is_dark_mode() else _LIGHT


def _base_stylesheet(t: dict) -> str:
    return f"""
    qMRMLWidget {{ background-color: {t['BACKGROUND']}; }}
    ctkCollapsibleButton {{
      background-color: {t['SURFACE']};
      border: 1px solid {t['BORDER']};
      border-radius: 6px;
      margin-bottom: {SPACING_MD}px;
      font-weight: 600;
      padding: {SPACING_SM}px 10px;
      color: {t['TEXT']};
    }}
    ctkCollapsibleButton:hover {{
      border: 1px solid {t['PRIMARY']};
    }}
    QLineEdit, QTextEdit {{
      background-color: {t['SURFACE']};
      border: 1px solid {t['BORDER']};
      border-radius: 4px;
      padding: {SPACING_SM}px;
      color: {t['TEXT']};
      selection-background-color: {t['PRIMARY']};
    }}
    QLineEdit:focus, QTextEdit:focus {{
      border: 2px solid {t['PRIMARY']};
    }}
    QComboBox {{
      background-color: {t['SURFACE']};
      border: 1px solid {t['BORDER']};
      border-radius: 4px;
      padding: {SPACING_XS}px {SPACING_SM}px;
      color: {t['TEXT']};
    }}
    QComboBox:focus {{ border: 2px solid {t['PRIMARY']}; }}
    QComboBox::drop-down {{ width: 20px; border: none; }}
    QComboBox QAbstractItemView {{
      background-color: {t['SURFACE']};
      color: {t['TEXT']};
      selection-background-color: {t['PRIMARY']};
      border: 1px solid {t['BORDER']};
    }}
    QProgressBar {{
      border: 1px solid {t['BORDER']};
      border-radius: 4px;
      background-color: {t['SURFACE']};
      padding: 2px;
      color: {t['TEXT']};
    }}
    QProgressBar::chunk {{
      background-color: {t['PRIMARY']};
      border-radius: 3px;
    }}
    """


def _button_stylesheet(base: str, hover: str, pressed: str, disabled_bg: str, disabled_text: str) -> str:
    return f"""
    QPushButton {{
      background-color: {base};
      color: white;
      border: none;
      border-radius: 6px;
      font-weight: 600;
      font-size: 10pt;
      padding: {SPACING_MD}px;
      margin-top: {SPACING_XS}px;
    }}
    QPushButton:hover:!pressed {{ background-color: {hover}; }}
    QPushButton:pressed {{ background-color: {pressed}; }}
    QPushButton:disabled {{ background-color: {disabled_bg}; color: {disabled_text}; }}
    """


def apply(widget) -> None:
    """Apply the current theme's stylesheet to a widget tree (e.g. the module's root widget)."""
    widget.setStyleSheet(_base_stylesheet(tokens()))


def primary_button(text: str) -> qt.QPushButton:
    t = tokens()
    button = qt.QPushButton(text)
    button.setStyleSheet(
        _button_stylesheet(t["PRIMARY"], t["PRIMARY_HOVER"], t["PRIMARY_PRESSED"], t["DISABLED_BG"], t["DISABLED_TEXT"])
    )
    return button


def danger_button(text: str) -> qt.QPushButton:
    t = tokens()
    button = qt.QPushButton(text)
    button.setStyleSheet(
        _button_stylesheet(t["DANGER"], t["DANGER_HOVER"], t["DANGER_PRESSED"], t["DISABLED_BG"], t["DISABLED_TEXT"])
    )
    return button


def section_title(text: str) -> qt.QLabel:
    t = tokens()
    label = qt.QLabel(text)
    label.setStyleSheet(f"color: {t['TEXT_MUTED']}; font-weight: 600;")
    return label


def required_label(text: str) -> qt.QLabel:
    return section_title(f"{text} *")


def hint_label(text: str) -> qt.QLabel:
    """A wrapped, muted, smaller label for explanatory text shown next to a
    field — the server's own `description` when a tooltip is not enough (see
    formgen.MultiChoiceGroup)."""
    t = tokens()
    label = qt.QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {t['TEXT_MUTED']}; font-size: 8pt; padding-bottom: {SPACING_XS}px;")
    return label


def warning_label(text: str) -> qt.QLabel:
    """A visible, wrapped, danger-colored label — used when part of a module's
    UI could not be built, so a failure is never just a silent blank panel."""
    t = tokens()
    label = qt.QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {t['DANGER']}; font-weight: 600; padding: {SPACING_SM}px;")
    return label


def status_badge() -> qt.QLabel:
    """An initial, unresolved badge; call update_status_badge() once a health check returns."""
    label = qt.QLabel("Server: checking...")
    t = tokens()
    label.setStyleSheet(f"color: {t['TEXT_MUTED']}; font-weight: 600; padding: {SPACING_XS}px;")
    return label


def update_status_badge(label: qt.QLabel, ok: bool) -> None:
    t = tokens()
    color = t["SUCCESS"] if ok else t["DANGER"]
    label.setText("Server: online" if ok else "Server: offline")
    label.setStyleSheet(f"color: {color}; font-weight: 600; padding: {SPACING_XS}px;")


def progress_label() -> qt.QLabel:
    """Where a running job reports what it is doing, next to the Cancel button.

    The status bar alone is not enough: a tool run is minutes of server-side
    inference during which the client has nothing to say, and a panel that
    shows nothing at all reads as frozen. An AMASSS run was cancelled at three
    minutes for exactly that reason -- it was working, and finished 40 seconds
    later.
    """
    label = qt.QLabel("")
    label.setWordWrap(True)
    label.setVisible(False)
    t = tokens()
    label.setStyleSheet(f"color: {t['TEXT_MUTED']}; padding: {SPACING_XS}px;")
    return label
