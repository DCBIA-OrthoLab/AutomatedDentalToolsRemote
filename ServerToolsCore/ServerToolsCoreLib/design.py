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

# Corner radii, and they are tokens for the same reason the spacings are: with
# the outlines gone it is the SHAPE of a fill that says what kind of thing
# something is, and three radii used consistently are a vocabulary where a
# dozen improvised ones are noise.
RADIUS_SM = 6    # a control: a field, a dropdown, a small button
RADIUS_MD = 8    # a tab, a chip, a grouped block
RADIUS_LG = 12   # a card: a section, an input row, a table

# **Nothing on this panel is outlined.** The structure is carried by four
# stacked SURFACES and by the accent, which is how a screen built this decade
# reads: a ground, a card raised on it, a slot sunk into the card, and the
# accent for the one thing that is chosen or in progress. A stroked box around
# every control is the older idiom, and drawn around a form of eight rows it
# turns the panel into a stack of cells with the content incidental.
#
#   BACKGROUND  the panel's own ground -- nothing is painted on it directly
#   SURFACE     a card standing on the ground: a collapsible section
#   FIELD       a slot sunk INTO a card: every control you type in or open
#   SURFACE_TABLE  a card holding a catalogue: a tab pane, an arch of teeth
#
# The two accent tints are the state, and they are the only saturated colour on
# a panel at rest: ACCENT_SOFT fills what is chosen, PRIMARY draws what is
# focused. Both have to be legible against SURFACE and against FIELD, which is
# what stops the soft tint from drifting any closer to the neutrals.
#
# BORDER survives for exactly two things, and both FLOAT above the panel rather
# than sit on it -- a tooltip and an open dropdown list. A surface with nothing
# behind it needs an edge; a surface on a card does not.
_LIGHT = {
    "PRIMARY": "#2b7fd4",
    "PRIMARY_HOVER": "#2168b0",
    "PRIMARY_PRESSED": "#17538f",
    "DANGER": "#e05252",
    "DANGER_HOVER": "#c33d3d",
    "DANGER_PRESSED": "#9c2c2c",
    "SUCCESS": "#1f9d57",
    "TEXT": "#1b2733",
    "TEXT_MUTED": "#5b6b7c",
    "BORDER": "#d3dce6",
    "BACKGROUND": "#e8ecf2",
    "SURFACE": "#ffffff",
    "SURFACE_HOVER": "#f4f7fb",
    "SURFACE_TABLE": "#ffffff",
    "FIELD": "#e7ebf1",
    "FIELD_HOVER": "#dbe2ea",
    "ACCENT_SOFT": "#d5e8fa",
    "DISABLED_BG": "#dfe4ea",
    "DISABLED_TEXT": "#9aa7b4",
}

_DARK = {
    "PRIMARY": "#4ba3ff",
    "PRIMARY_HOVER": "#6cb6ff",
    "PRIMARY_PRESSED": "#2b7fd4",
    "DANGER": "#f0655f",
    "DANGER_HOVER": "#f4837e",
    "DANGER_PRESSED": "#c54a45",
    "SUCCESS": "#3ddc84",
    "TEXT": "#e6eaef",
    "TEXT_MUTED": "#99a5b3",
    "BORDER": "#3d444d",
    "BACKGROUND": "#1c1f24",
    "SURFACE": "#262b31",
    "SURFACE_HOVER": "#2f353d",
    "SURFACE_TABLE": "#22262c",
    "FIELD": "#333942",
    "FIELD_HOVER": "#3d444e",
    "ACCENT_SOFT": "#1d3d5c",
    "DISABLED_BG": "#2b3037",
    "DISABLED_TEXT": "#6b7682",
}

# One FLAT fill per button role and state. It was a vertical `qlineargradient`
# until 2026-09-24, inherited from the original SlicerAutomatedDentalTools
# `.ui` files so that a converted module would not read as a different product
# sitting next to an unconverted one -- and the unconverted five still paint
# theirs that way. The inheritance is dropped deliberately: a top-lit gradient
# on a button is the one detail that dates a panel at a glance, and the rest of
# this file now says what it has to say with flat surfaces.
#
# Three states rather than two shades of one: `hover` and `pressed` are steps
# along the same hue, so the button answers a pointer by getting lighter and a
# click by getting darker, which is the direction every surface on a screen
# moves.
_BUTTON_FILLS_LIGHT = {
    "primary":   {"base": "#2b7fd4", "hover": "#3a90e6", "pressed": "#1f66ad"},
    "danger":    {"base": "#e05252", "hover": "#ea6666", "pressed": "#bd3c3c"},
    "success":   {"base": "#1f9d57", "hover": "#27b165", "pressed": "#177f45"},
    "secondary": {"base": "#64748b", "hover": "#76879e", "pressed": "#4f5d72"},
}
_BUTTON_FILLS_DARK = {
    "primary":   {"base": "#3d8fe0", "hover": "#4ba3ff", "pressed": "#2f74b8"},
    "danger":    {"base": "#d9534f", "hover": "#e86b67", "pressed": "#b4403d"},
    "success":   {"base": "#2fa367", "hover": "#3cb878", "pressed": "#248352"},
    "secondary": {"base": "#5b6875", "hover": "#6d7b8a", "pressed": "#49545f"},
}

# The two colors of a checkable on/off button (see toggle_button). Fixed
# Material values in both themes, exactly as GreedyReg's interactive-tool
# toggle: blue reads "click to start", red reads "active, click to stop".
_TOGGLE_OFF = "#2196f3"
_TOGGLE_ON = "#f44336"

# White check mark drawn inside a checked QCheckBox indicator. An inline SVG
# rather than a Qt resource (:/Icons/SmallCheckMark.png in the original .ui
# files) so it needs no resource file compiled into the extension.
_CHECKMARK_SVG = (
    "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
    "<path fill='white' d='M13.854 3.646a.5.5 0 0 1 0 .708l-7 7a.5.5 0 0 1-.708 0"
    "l-3.5-3.5a.5.5 0 1 1 .708-.708L6.5 10.293l6.646-6.647a.5.5 0 0 1 .708 0z'/></svg>"
)

# How wide the tinted zone at a dropdown's right edge is, and how big the
# chevron drawn in it is. Wide enough to read as a part of the control rather
# than as a sliver of colour, and the whole width of it is clickable because
# QComboBox opens on a click anywhere.
DROPDOWN_ARROW_WIDTH = 24
_CHEVRON_SIDE = 10


def _rgb(color: str) -> str:
    """`#4ba3ff` as `rgb(75, 163, 255)`; anything else passed through, so a
    keyword like `white` still reaches the SVG intact."""
    value = color.strip()
    if not (value.startswith("#") and len(value) == 7):
        return value
    red, green, blue = (int(value[index:index + 2], 16) for index in (1, 3, 5))
    return "rgb({}, {}, {})".format(red, green, blue)


def _chevron_svg(color: str, up: bool = False) -> str:
    """A chevron as an inline data URI, in whatever colour the theme wants.

    Parameterised where `_CHECKMARK_SVG` is a constant, because this one is
    drawn on a light fill and has to take a real colour rather than white --
    and the OPEN state points the other way, which is the only feedback a
    collapsed combo box gives that its list is down.

    The colour is rewritten as `rgb(r, g, b)` and NEVER reaches the URI as a
    hex literal. `#` is a data URI's fragment marker: left as it is the SVG is
    truncated at the fill, and percent-escaping it only moves the question to
    whether Qt decodes the escape before handing the bytes to the SVG reader.
    `rgb()` needs no character a URI reserves, so neither question arises --
    and the failure both would have had is silent, the arrow simply not being
    drawn with nothing logged.
    """
    tint = _rgb(color)
    points = "4,10 8,6 12,10" if up else "4,6 8,10 12,6"
    return (
        "data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'>"
        "<polyline points='{}' fill='none' stroke='{}' stroke-width='2'"
        " stroke-linecap='round' stroke-linejoin='round'/></svg>"
    ).format(points, tint)


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
    """The whole panel, painted in surfaces.

    Two rules run through all of it. **Nothing is outlined**: a control is a
    slot sunk into its card, and what it does is said by the fill changing, not
    by a line appearing around it. And **no rule changes a widget's geometry
    between states** -- the focus ring is a border that was always there and
    transparent, so a field cannot shift by a pixel under the pointer, and no
    selected tab can grow wider than the slot Qt laid out for it.
    """
    return f"""
    qMRMLWidget {{ background-color: {t['BACKGROUND']}; }}
    /* A card standing on the ground, and the fill is the whole of what raises
       it. The hairline it used to carry was the loudest line on the panel,
       repeated once per section. */
    ctkCollapsibleButton {{
      background-color: {t['SURFACE']};
      border: none;
      border-radius: {RADIUS_LG}px;
      margin-bottom: {SPACING_MD}px;
      font-weight: 600;
      padding: {SPACING_MD}px {SPACING_LG}px;
      color: {t['TEXT']};
    }}
    ctkCollapsibleButton:hover {{ background-color: {t['SURFACE_HOVER']}; }}
    QLabel {{
      color: {t['TEXT']};
      font-weight: 500;
      background: transparent;
    }}
    /* Every control you type in or open: a slot SUNK into the card, filled and
       unstroked. The border is 2px of nothing, kept so the focus ring can
       appear without moving the text inside by a pixel -- Qt paints a widget's
       background under its border, so a transparent one simply shows the
       fill. */
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
      background-color: {t['FIELD']};
      border: 2px solid transparent;
      border-radius: {RADIUS_SM}px;
      color: {t['TEXT']};
      selection-background-color: {t['PRIMARY']};
      selection-color: white;
    }}
    QLineEdit, QTextEdit {{ padding: {SPACING_SM}px {SPACING_MD}px; }}
    QComboBox, QSpinBox, QDoubleSpinBox {{ padding: {SPACING_SM}px {SPACING_MD}px; }}
    QLineEdit:hover, QTextEdit:hover, QComboBox:hover,
    QSpinBox:hover, QDoubleSpinBox:hover {{ background-color: {t['FIELD_HOVER']}; }}
    /* Focused: the slot lifts to the card's own colour and the accent ring
       comes up around it. Two changes rather than one, because on a dense
       panel a ring alone is a thin line among many rows. */
    QLineEdit:focus, QTextEdit:focus, QComboBox:focus,
    QSpinBox:focus, QDoubleSpinBox:focus {{
      background-color: {t['SURFACE']};
      border-color: {t['PRIMARY']};
    }}
    QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled,
    QSpinBox:disabled, QDoubleSpinBox:disabled {{
      background-color: {t['DISABLED_BG']};
      color: {t['DISABLED_TEXT']};
    }}
    /* The right of a dropdown is tinted, so the one control on the panel that
       hides something behind it is the one control that is two colours. The
       chevron turns over while the list is down. */
    QComboBox {{ padding-right: {DROPDOWN_ARROW_WIDTH + SPACING_MD}px; }}
    QComboBox::drop-down {{
      subcontrol-origin: padding;
      subcontrol-position: top right;
      width: {DROPDOWN_ARROW_WIDTH}px;
      border: none;
      border-top-right-radius: {RADIUS_SM - 2}px;
      border-bottom-right-radius: {RADIUS_SM - 2}px;
      background-color: {t['ACCENT_SOFT']};
    }}
    QComboBox::down-arrow {{
      width: {_CHEVRON_SIDE}px;
      height: {_CHEVRON_SIDE}px;
      image: url("{_chevron_svg(t['PRIMARY'])}");
    }}
    QComboBox::down-arrow:on {{ image: url("{_chevron_svg(t['PRIMARY'], up=True)}"); }}
    QComboBox::drop-down:disabled {{ background-color: transparent; }}
    /* The open list FLOATS above the panel, so it is one of the two things
       here with nothing behind it -- and the only two that keep an edge. */
    QComboBox QAbstractItemView {{
      background-color: {t['SURFACE']};
      color: {t['TEXT']};
      selection-background-color: {t['PRIMARY']};
      selection-color: white;
      border: 1px solid {t['BORDER']};
      border-radius: {RADIUS_SM}px;
      padding: {SPACING_XS}px;
      outline: none;
    }}
    QComboBox QAbstractItemView::item {{
      padding: {SPACING_XS}px {SPACING_SM}px;
      border-radius: {RADIUS_SM - 2}px;
    }}
    /* A catalogue, on a card of its own. The fill is what separates it from
       the panel; it needs no line to say where it ends. */
    QTabWidget::pane {{
      background-color: {t['SURFACE_TABLE']};
      /* The fill's own colour, and not `none`: a QSS rule with no border at
         all leaves Qt free to draw the pane with the native style, and this
         guarantees the surface is painted and still shows no edge. */
      border: 1px solid {t['SURFACE_TABLE']};
      border-radius: {RADIUS_LG}px;
      top: 0px;
    }}
    /* A segmented control, not a row of folder tabs: pills that fill when
       chosen. Only the background and the text colour move between states --
       Qt sizes a tab from what it holds when the bar is laid out, so a border
       or a weight that changed with the selection would make the open tab
       wider than its own slot and clip its label. */
    QTabBar {{ background: transparent; }}
    QTabBar::tab {{
      background-color: transparent;
      color: {t['TEXT_MUTED']};
      border: none;
      border-radius: {RADIUS_MD}px;
      padding: {SPACING_SM}px {SPACING_MD}px;
      margin-right: {SPACING_XS}px;
      margin-bottom: {SPACING_XS}px;
      font-weight: 500;
    }}
    QTabBar::tab:hover:!selected {{ background-color: {t['FIELD']}; }}
    QTabBar::tab:selected {{
      background-color: {t['ACCENT_SOFT']};
      color: {t['PRIMARY']};
    }}
    /* The pane already IS the surface; a scroll area inside one would draw a
       second, squarer box just inside the rounded one. */
    QScrollArea {{ border: none; background-color: transparent; }}
    QScrollBar:vertical {{
      background: transparent; width: 10px; margin: 0px;
    }}
    QScrollBar:horizontal {{
      background: transparent; height: 10px; margin: 0px;
    }}
    QScrollBar::handle:vertical, QScrollBar::handle:horizontal {{
      background-color: {t['FIELD_HOVER']};
      border-radius: 5px;
      min-height: 24px;
      min-width: 24px;
    }}
    QScrollBar::handle:hover {{ background-color: {t['PRIMARY']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    QCheckBox {{
      color: {t['TEXT']};
      font-weight: 500;
      spacing: {SPACING_SM}px;
      background: transparent;
    }}
    /* A filled slot, like every other control, at the size of one. */
    QCheckBox::indicator {{
      width: 18px;
      height: 18px;
      border: none;
      border-radius: {RADIUS_SM - 1}px;
      background-color: {t['FIELD']};
    }}
    QCheckBox::indicator:hover {{ background-color: {t['FIELD_HOVER']}; }}
    QCheckBox::indicator:checked {{
      background-color: {t['PRIMARY']};
      image: url("{_CHECKMARK_SVG}");
    }}
    QSlider::groove:horizontal {{
      border: none;
      height: 6px;
      background-color: {t['FIELD']};
      border-radius: 3px;
    }}
    QSlider::sub-page:horizontal {{
      background-color: {t['PRIMARY']};
      border-radius: 3px;
    }}
    QSlider::handle:horizontal {{
      background-color: {t['PRIMARY']};
      border: none;
      width: 16px;
      margin: -5px 0;
      border-radius: 8px;
    }}
    QSlider::handle:horizontal:hover {{ background-color: {t['PRIMARY_HOVER']}; }}
    QProgressBar {{
      border: none;
      border-radius: {RADIUS_SM}px;
      background-color: {t['FIELD']};
      color: {t['TEXT']};
      text-align: center;
    }}
    QProgressBar::chunk {{
      background-color: {t['PRIMARY']};
      border-radius: {RADIUS_SM}px;
    }}
    /* Floats above the panel: the second of the two things that keep an edge. */
    QToolTip {{
      background-color: {t['SURFACE']};
      color: {t['TEXT']};
      border: 1px solid {t['BORDER']};
      border-radius: {RADIUS_SM}px;
      padding: {SPACING_SM}px {SPACING_MD}px;
    }}
    {_button_stylesheet("primary", t)}
    """


def _fills_for(t: dict) -> dict:
    """The button fills belonging to the palette `t`.

    Taken FROM the palette rather than from `is_dark_mode()`, which is what
    `_button_stylesheet` used to do: it accepts a theme and then asked the
    application which theme it was, so a caller handing it one palette got the
    buttons of the other. Harmless in production, where `apply` passes
    `tokens()` and the two agree -- and exactly the kind of agreement that
    holds until someone renders a sheet for a theme that is not the live one.
    """
    return _BUTTON_FILLS_DARK if t is _DARK else _BUTTON_FILLS_LIGHT


def _button_fills() -> dict:
    return _fills_for(tokens())


def _button_stylesheet(role: str, t: dict) -> str:
    """The QSS of one button role. Also embedded in the base stylesheet as the
    bare-QPushButton rule (role "primary"), so a plain button someone adds
    (formgen's File.../Folder... browse buttons) comes out looking like the
    original's Search buttons rather than falling back to Slicer's default."""
    stops = _fills_for(t)[role]
    return f"""
    QPushButton {{
      background-color: {stops['base']};
      color: white;
      border: none;
      border-radius: {RADIUS_MD}px;
      font-weight: 600;
      font-size: 10pt;
      padding: {SPACING_MD}px;
      margin-top: {SPACING_XS}px;
    }}
    QPushButton:hover:!pressed {{ background-color: {stops['hover']}; }}
    QPushButton:pressed {{ background-color: {stops['pressed']}; }}
    QPushButton:disabled {{ background-color: {t['DISABLED_BG']}; color: {t['DISABLED_TEXT']}; }}
    """


def apply(widget) -> None:
    """Apply the current theme's stylesheet to a widget tree (e.g. the module's root widget)."""
    widget.setStyleSheet(_base_stylesheet(tokens()))


def _role_button(text: str, role: str) -> qt.QPushButton:
    button = qt.QPushButton(text)
    button.setStyleSheet(_button_stylesheet(role, tokens()))
    return button


def primary_button(text: str) -> qt.QPushButton:
    """The panel's main action: Apply, Retry."""
    return _role_button(text, "primary")


def danger_button(text: str) -> qt.QPushButton:
    """A destructive or interrupting action: Cancel."""
    return _role_button(text, "danger")


def success_button(text: str) -> qt.QPushButton:
    """A confirming action distinct from the main one: GreedyReg's green
    Run/Save family. Not used by the generated panel itself; offered to
    modules adding their own buttons (addExtraWidgets)."""
    return _role_button(text, "success")


def secondary_button(text: str) -> qt.QPushButton:
    """A secondary tool that must not compete with the main action: the
    blue-gray of the original's utility buttons."""
    return _role_button(text, "secondary")


def _compact_button(text: str, role: str) -> qt.QPushButton:
    t = tokens()
    stops = _button_fills()[role]
    button = qt.QPushButton(text)
    button.setStyleSheet(
        f"QPushButton {{ background-color: {stops['base']}; color: white;"
        f" border: none; border-radius: {RADIUS_SM}px; font-weight: 600;"
        f" padding: {SPACING_XS}px {SPACING_MD}px; margin: 0px; }}"
        f"QPushButton:hover:!pressed {{ background-color: {stops['hover']}; }}"
        f"QPushButton:pressed {{ background-color: {stops['pressed']}; }}"
        f"QPushButton:disabled {{ background-color: {t['DISABLED_BG']}; color: {t['DISABLED_TEXT']}; }}"
    )
    return button


def compact_button(text: str) -> qt.QPushButton:
    """A small inline button for a form row (the browse actions): the
    primary gradient with tighter padding and no top margin, so a row of them
    stays one text-field tall and the whole input fits on a single line."""
    return _compact_button(text, "primary")


# How tall a navigation button is, and how big the glyph on it is. Large on
# purpose: stepping through a cohort is the one action a reader repeats
# hundreds of times in a sitting, and it is done while looking at the SCAN
# rather than at the panel. A button found by peripheral vision has to be
# bigger than a button read.
NAV_BUTTON_HEIGHT = 44
NAV_GLYPH_POINT_SIZE = 18


def nav_button(text: str) -> qt.QPushButton:
    """A large stepper for moving through a list: VISU's previous/next.

    NOT `primary_button`: a panel's primary is the one action that commits
    something, and these commit nothing -- they move the view. The secondary
    gradient keeps them quiet while the height keeps them findable.
    """
    t = tokens()
    stops = _button_fills()["secondary"]
    button = qt.QPushButton(text)
    button.setMinimumHeight(NAV_BUTTON_HEIGHT)
    button.setStyleSheet(
        f"QPushButton {{ background-color: {stops['base']}; color: white;"
        f" border: none; border-radius: {RADIUS_MD}px; font-weight: 700;"
        f" font-size: {NAV_GLYPH_POINT_SIZE}pt; padding: 0px; margin: 0px; }}"
        f"QPushButton:hover:!pressed {{ background-color: {stops['hover']}; }}"
        f"QPushButton:pressed {{ background-color: {stops['pressed']}; }}"
        f"QPushButton:disabled {{ background-color: {t['DISABLED_BG']}; color: {t['DISABLED_TEXT']}; }}"
    )
    return button


def compact_danger_button(text: str) -> qt.QPushButton:
    """A small interrupting action attached to ONE line of a list: the Cancel
    that belongs to a single run, next to that run's own progress line.

    Deliberately NOT danger_button: the panel already has one of those, full
    width under Apply, and it cancels everything. A second full-width red
    button per run would read as another main action and would be the easiest
    thing on the panel to hit by accident -- which here means throwing away an
    inference that has been going for twenty minutes. Small, inline, and
    unmistakably subordinate to the button above it.
    """
    return _compact_button(text, "danger")


def option_chip(text: str) -> qt.QPushButton:
    """One option of a dense multichoice: the label IS the control.

    A check box puts an 18 px target next to the word a clinician is actually
    reading, and asks them to hit the square. Over ALI's 119 landmarks or ASO's
    32 teeth that is the difference between a list and a chore -- and the state
    of a whole grid reads at a glance as filled against outlined, which a grid
    of small ticks does not.

    Still a real CHECKABLE widget, not a painted label: `isChecked`,
    `setChecked` and `toggled` are Qt's own, so `MultiChoiceGroup` reads it back
    exactly as it read a check box, and the keyboard reaches it. Nothing about
    the wire changes.

    Two FILLS, not an outline that tints. Unchecked it is the same slot every
    other control on the panel is -- a chip is a control, and reading as one
    without being stroked is exactly what the rest of the panel does now.
    Checked it takes the accent whole. Over a hundred and nineteen landmarks
    the difference between filled and unfilled reads across the whole grid at
    once, where a hundred and nineteen outlines read as a mesh.

    `toggle_button` is the opposite case -- two saturated states where the
    COLOUR is the information -- and the two must not be confused.
    """
    t = tokens()
    button = qt.QPushButton(text)
    button.setCheckable(True)
    button.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
    button.setStyleSheet(
        f"QPushButton {{ background-color: {t['FIELD']}; color: {t['TEXT']};"
        f" border: none; border-radius: {RADIUS_MD}px;"
        f" padding: {SPACING_XS}px {SPACING_MD}px; font-weight: 500; text-align: center; }}"
        f"QPushButton:hover {{ background-color: {t['FIELD_HOVER']}; }}"
        # Same weight as an unselected chip, deliberately. Qt sizes a button
        # from the text it has when the grid is laid out, so bolding the checked
        # state made the label wider than its own chip: "LPo" rendered "LPc".
        # The fill carries the selection; nothing moves.
        f"QPushButton:checked {{ background-color: {t['PRIMARY']}; color: white; }}"
        f"QPushButton:disabled {{ background-color: {t['DISABLED_BG']};"
        f" color: {t['DISABLED_TEXT']}; }}"
    )
    return button


def toggle_button(text: str) -> qt.QPushButton:
    """A checkable on/off button: blue when off ("click to start"), red while
    checked ("active, click to stop"), as GreedyReg's interactive-tool toggle.
    Flat fills, not gradients: the two-state color IS the information, and a
    gradient would make it read as one more action button."""
    t = tokens()
    button = qt.QPushButton(text)
    button.setCheckable(True)
    button.setStyleSheet(
        f"QPushButton {{ background-color: {_TOGGLE_OFF}; color: white; border: none;"
        f" border-radius: {RADIUS_SM}px; font-weight: 600; padding: {SPACING_SM}px; }}"
        f"QPushButton:checked {{ background-color: {_TOGGLE_ON}; }}"
        f"QPushButton:disabled {{ background-color: {t['DISABLED_BG']}; color: {t['DISABLED_TEXT']}; }}"
    )
    return button


def section_title(text: str, explained: bool = False) -> qt.QLabel:
    """The name of a field, beside it.

    `explained` marks a label whose argument carries a description, and the
    mark is a dotted underline -- the oldest convention there is for "there is
    more here if you hover", and one that costs the label no words. The
    description itself is the label's TOOLTIP, and that is a deliberate move:
    it used to be printed under the field as a small grey paragraph, several
    lines of it on a crowded panel, and at that size and that contrast it was
    text a reader skipped rather than read.

    What it costs is stated rather than hidden: a paragraph that only applies
    to one of two always-visible fields -- ALI publishes `cbct_regions` and
    `ios_networks` together and the description of each says which input it is
    for -- is now one hover away rather than on the panel. The dotted rule is
    what has to carry that, so it is drawn on every explained label and on no
    other.
    """
    t = tokens()
    label = qt.QLabel(text)
    hint = (f" border-bottom: 1px dotted {t['TEXT_MUTED']};"
            f" padding-bottom: 1px;" if explained else "")
    label.setStyleSheet(f"color: {t['TEXT_MUTED']}; font-weight: 600;{hint}")
    return label


def required_label(text: str, explained: bool = False) -> qt.QLabel:
    return section_title(f"{text} *", explained)


def optional_label(text: str, explained: bool = False) -> qt.QLabel:
    """A file argument the tool can do without.

    Said in words rather than by the absence of the `*`: an empty file picker
    looks like a demand whatever the label does, and a tool that computes the
    file itself when it is left empty -- AREG's landmarks, produced by ALI
    through the supervisor -- otherwise reads as a missing input.
    """
    return section_title(f"{text} (optional)", explained)


def group_heading(text: str) -> qt.QLabel:
    """The name of one GROUP inside a field: AMASSS's Bones, Soft tissue and
    Masks, each over its own row of chips.

    **Small, bold, muted, and TIGHT against the chips under it.** A heading and
    the options it names are one block, and the whole point of the grouping is
    that Bones, Soft tissue and Masks can be compared in one look -- so every
    pixel spent separating a heading from its own chips is a pixel that pushes
    the third group off the eye's first pass. The air goes above the heading,
    where it separates one group from the NEXT, and nowhere else.

    It first shipped with the air on both sides and a rule underneath. The rule
    is gone with every other line on this panel, and it is not missed: at two
    sizes and two weights below a chip, the heading is already a different kind
    of thing.

    The gap is a MARGIN and not a spacer widget: `MultiChoiceGroup.rebuild`
    empties its column by reparenting the widgets in it, and a spacer item is
    not a widget -- it would survive the redraw and stack up one gap per mode
    switch.
    """
    t = tokens()
    label = qt.QLabel(text)
    label.setStyleSheet(
        f"color: {t['TEXT_MUTED']}; font-weight: 700; font-size: 8pt;"
        f" background: transparent; border: none;"
        f" margin-top: {SPACING_SM}px; padding: 0px;"
    )
    return label


def table_frame():
    """The surface a chart-shaped field is drawn on: ASO's arch of teeth.

    The same fill and the same 2px edge as a tab pane, because they are the
    same object seen twice -- a table of options -- and the tabbed one gets
    its frame from `QTabWidget::pane` while this one has no pane to inherit.

    A QFrame, like `cohort_frame`, and the id selector is what keeps the rule
    off its children. A bare QWidget is the shape that looks right and does
    not paint: Qt draws a style sheet's background and border for it only once
    `WA_StyledBackground` is set, and a QFrame carries that already -- while
    its own frame, left at the default `NoFrame`, draws nothing of its own.
    """
    t = tokens()
    frame = qt.QFrame()
    frame.setObjectName("tableFrame")
    frame.setStyleSheet(
        f"#tableFrame {{ background-color: {t['SURFACE_TABLE']};"
        f" border: none; border-radius: {RADIUS_LG}px; }}"
    )
    return frame


def hint_label(text: str) -> qt.QLabel:
    """A wrapped, muted, smaller label for explanatory text a module writes
    itself -- VISU's origin line, Slicer Cloud's per-tool summary.

    NOT for an argument's `description` any more. A generated panel used to
    print those under the fields they belong to, and several of them stacked
    down a form is text at a size and a contrast that a reader scrolls past.
    They are the row label's tooltip now, and `section_title(explained=True)`
    is what marks a label as having one.
    """
    t = tokens()
    label = qt.QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(f"color: {t['TEXT_MUTED']}; font-size: 8pt; padding-bottom: {SPACING_XS}px;")
    return label


def selection_label(text: str) -> qt.QLabel:
    """The line under an input row saying WHAT it currently holds.

    Deliberately not `hint_label`, and that distinction is the point. A hint is
    explanatory text a reader may skip; this is the only feedback that a choice
    registered at all -- there is no path field any more, and a dropdown
    returns to its prompt as soon as it is picked. Muted and 8pt, it read as a
    footnote, and a clinician who had just chosen a scan could not tell whether
    the panel had taken it.

    Raised twice before it read as feedback. 8pt muted was a footnote; 10pt
    was still close enough to the surrounding text to be scanned past. It is
    12pt now -- the largest text on the row, which is what it should be:
    everything above it is a control offering a choice, and this is the
    answer.

    It has TWO states, painted by `_paint_selection` and never set here: muted
    and medium while the row holds nothing, full-strength and semi-bold once
    it does. The weight is the whole difference -- "Nothing selected" is a
    prompt and should not shout, and the file name that replaces it should.
    `set_input_filled` paints it together with the card around it, so the box
    and the line inside it can never disagree about whether the row is
    satisfied.

    It stays a plain wrapped label all the same. It is a statement of fact,
    not a control, so it gets no border and no fill of its own: a filled block
    here would read as a third thing to click, beside two dropdowns and two
    buttons.
    """
    label = qt.QLabel(text)
    label.setWordWrap(True)
    _paint_selection(label, filled=False)
    return label


def _paint_selection(label, filled: bool) -> None:
    t = tokens()
    label.setStyleSheet(
        f"color: {t['TEXT'] if filled else t['TEXT_MUTED']};"
        f" font-size: 12pt; font-weight: {600 if filled else 500};"
        f" padding-top: {SPACING_XS}px; padding-bottom: {SPACING_SM}px;"
    )


# --- one input row, as one object -----------------------------------------
#
# An input row is up to five controls on one line -- two dropdowns, two browse
# buttons -- and a sentence under them saying what came of it. Laid out bare on
# the panel that is five things of five different shapes and no edge anywhere,
# and the question a clinician actually has ("have I given this tool its scan
# yet?") was answered only by a line of 12pt text among all of it.
#
# The card is the answer: ONE block per input, holding every way of filling it,
# and the block itself carries the state. It is a FILL and never an outline,
# like everything else here -- empty it is the same neutral slot a field is,
# filled it turns the accent tint, so a panel of four inputs says at a glance
# which are done without drawing four boxes to do it.
#
# The two fills are far enough apart to read at a glance and both quiet enough
# to sit under a form: a neutral grey-blue against a light accent blue. That
# distance is why FIELD is kept NEUTRAL in the token table -- drift it towards
# the accent and this row stops being able to say anything.


def input_card():
    """The block one file argument is chosen in. See the note above.

    A QFrame with an id selector: the frame is what makes Qt paint a style
    sheet's background at all (see `table_frame`), and the id is what keeps
    that rule off the controls inside, which must keep the styling the panel's
    own sheet gives them.
    """
    card = qt.QFrame()
    card.setObjectName("inputCard")
    set_input_filled(card, None, False)
    return card


def set_input_filled(card, caption, filled: bool) -> None:
    """Repaint an input row for whether it now holds something.

    Takes the caption too, and paints both from one call, because they are one
    statement: the block says THAT the row is satisfied and the line inside it
    says WITH WHAT, and a panel where those two disagreed would be worse than
    either alone. `caption` may be None for a card built before its label.
    """
    t = tokens()
    ground = t["ACCENT_SOFT"] if filled else t["FIELD"]
    card.setStyleSheet(
        f"#inputCard {{ background-color: {ground}; border: none;"
        f" border-radius: {RADIUS_LG}px;"
        f" padding: {SPACING_MD}px {SPACING_MD}px {SPACING_XS}px {SPACING_MD}px; }}"
    )
    if caption is not None:
        _paint_selection(caption, filled)


# The two captions on a multichoice's bulk-select row, and on the per-tab pair
# inside a tabbed one -- ONE pair for what is one action in two places. They had
# drifted into two wordings and two casings ("Select none" above the options,
# "Deselect All" inside a tab), which made the same button look like two
# different controls depending on the layout the tool happened to ask for.
#
# Here rather than in formgen because they are the CLIENT's own words: formgen
# renders no literal text of its own, every label it shows having come from the
# tool's schema.
SELECT_ALL_TEXT = "Select all"
SELECT_NONE_TEXT = "Deselect all"


def ghost_button(text: str) -> qt.QPushButton:
    """A small outlined button for a bulk command acting on the field below it —
    the Select all / Deselect all pair above a group of check boxes.

    Neither of the two it sits between, and for a reason each:

    `link_button` is what this was, and an underlined caption is this
    extension's vocabulary for something that takes you ELSEWHERE — Server
    logs, Check for updates. These take you nowhere; they act on the very list
    under them. Two underlined captions side by side also read as one broken
    sentence rather than as two commands, which is what made the row look
    unfinished.

    `primary_button` is what the tabbed layout uses, and it earns it: there the
    pair spans a tab and is the only bulk control in it. Out here, a filled blue
    slab sitting a few rows above Apply competes with the one button that starts
    a run.

    A soft filled pill says "a control, and a quiet one", which is exactly what
    this is -- and it is the panel's own way of saying it, every control here
    being a fill rather than a stroke. Sized to its text, not stretched: it
    commands the group, it is not part of it.
    """
    t = tokens()
    button = qt.QPushButton(text)
    button.setStyleSheet(
        f"QPushButton {{ background-color: {t['FIELD']}; border: none;"
        f" border-radius: {RADIUS_MD}px; color: {t['TEXT_MUTED']}; font-weight: 600;"
        # Padding, never a fixed height: the text is the panel's own size (no
        # font-size override at all) so it reads at a glance, and the button is
        # kept compact by hugging it rather than by shrinking it.
        f" padding: {SPACING_XS}px {SPACING_MD}px; }}"
        f"QPushButton:hover {{ background-color: {t['ACCENT_SOFT']}; color: {t['PRIMARY']}; }}"
        f"QPushButton:pressed {{ background-color: {t['FIELD_HOVER']};"
        f" color: {t['PRIMARY_PRESSED']}; }}"
    )
    button.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
    return button


def link_button(text: str) -> qt.QPushButton:
    """A small, flat, text-only button for a secondary action next to a field —
    the All / None / Default row above a group of check boxes.

    Deliberately NOT primary_button: three filled blue buttons above a check
    box grid read as the panel's main actions and compete with Apply, which is
    the one button that starts a run.
    """
    t = tokens()
    button = qt.QPushButton(text)
    button.setStyleSheet(
        f"QPushButton {{ background: transparent; border: none; color: {t['PRIMARY']};"
        f" font-size: 8pt; font-weight: 600; padding: 0px {SPACING_SM}px; margin: 0px;"
        f" text-decoration: underline; }}"
        f"QPushButton:hover {{ color: {t['PRIMARY_HOVER']}; }}"
    )
    # A QCursor, not the bare Qt::CursorShape enum: PyQt converts one to the
    # other implicitly, PythonQt does not reliably, and this runs under
    # PythonQt.
    button.setCursor(qt.QCursor(qt.Qt.PointingHandCursor))
    return button


# A QScrollArea's size hint ignores its child, so a chart or a tab page laid
# out inside one collapses to a few pixels unless it is told how tall it is.
# Both are floors, not fixed heights: the layouts still grow with the panel.
CHART_MIN_HEIGHT = 90   # two rows of check boxes plus their group labels

# A tab box is sized to what it HOLDS, between these two. It used to be one
# fixed floor of 220 px that the panel's spare vertical space then stretched
# further -- so ASO's two arches of teeth and ALI's ten cranial landmarks both
# sat in a 380 px box that was mostly empty.
CHECKBOX_ROW_HEIGHT = 34  # a chip row: the label, its padding and its border
TABS_CHROME_HEIGHT = 88   # the tab bar, the grid's margins, the frame, and the
                          # full-width group button under every tab
TABS_MIN_HEIGHT = 96      # the floor a QScrollArea needs: its size hint ignores
                          # its child, so without one it collapses to a few px
TABS_MAX_HEIGHT = 320     # past this, one argument owns the whole panel


def tabs_height_for(rows: int) -> int:
    """How tall a tab box has to be to show `rows` of check boxes.

    Sized on the TALLEST tab, not the visible one: a box that resized as the
    user moved between tabs would make the whole panel jump under the pointer.
    Clamped both ways -- ALI's landmarks run to fifteen rows and would otherwise
    push Apply off the screen.
    """
    wanted = TABS_CHROME_HEIGHT + max(rows, 1) * CHECKBOX_ROW_HEIGHT
    return max(TABS_MIN_HEIGHT, min(wanted, TABS_MAX_HEIGHT))

# Joystick pad (joystick.JoystickPad). The side is FlexReg's PAD_SIZE; the
# paint colors are FlexReg's pad palette, which was designed against this same
# blue theme. Hex strings rather than QColors so this module stays importable
# under the test stubs; the pad wraps them at paint time.
PAD_SIZE = 160
_PAD_LIGHT = {
    "background": "#f4f7fa", "border": "#d3dce5", "grid": "#e3eaf1",
    "text": "#93a2b1", "label": "#6b7c8d", "knob": "#3498db", "trail": "#bcd7ef",
}
_PAD_DARK = {
    "background": "#2b3138", "border": "#4a5560", "grid": "#3d454e",
    "text": "#8b97a3", "label": "#b6c2ce", "knob": "#4ba3ff", "trail": "#3f5871",
}


def pad_palette() -> dict:
    """The joystick pad's paint colors for the current theme, as hex strings."""
    return _PAD_DARK if is_dark_mode() else _PAD_LIGHT


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


def progress_bar() -> qt.QProgressBar:
    """A determinate bar for a run whose server-side progress is a real number.

    Hidden by default and shown ONLY while a tool reports a fraction: most
    runs report none at all, and a bar that has to fake motion to look alive
    is worse than the elapsed-time line beside it, which at least never
    claims to know how far along anything is. Styled entirely by the base
    stylesheet's QProgressBar rules, so it follows the theme with the rest of
    the panel.
    """
    bar = qt.QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setVisible(False)
    bar.setTextVisible(True)
    return bar


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


# --- a cohort in flight ----------------------------------------------------
#
# One Apply can now be several runs (a folder of 20 scans sent in batches), and
# the panel had nothing for that shape: it showed five lines of the same
# sentence and five Cancel buttons, which reads as five unrelated jobs a user
# started by accident. These four factories say the opposite -- ONE piece of
# work, made of parts -- and the design follows from it:
#
#   * one frame, so the cohort is one object on the panel. Not a card per
#     batch: a border around each would be five objects again.
#   * one headline count, in the size `selection_label` uses, because both
#     answer the same kind of question ("what have I actually got") and a
#     second size here would invent a vocabulary the panel does not have.
#   * bars WITHOUT their percentage. The exact figure is written underneath in
#     words; a "%" painted on the bar is a second, vaguer answer to a question
#     already answered precisely.
#   * the batch bars slim and the cohort bar full height, which is the only
#     hierarchy needed: what matters is the whole, what moves is a part.


def cohort_frame() -> qt.QFrame:
    """The box a whole cohort's progress lives in.

    A soft FILL and no line, like every other block on this panel. It shipped
    as a hairline with no fill, on the reasoning that a filled card reads as
    something pasted in from another application -- which was true of the pure
    white it had been painted before that, and is not true of the slot colour
    every control here already uses.

    The fill also says something the hairline could not: this box appears only
    while a cohort is in flight, and a tinted block arriving mid-panel reads as
    something happening, where an outline arriving reads as a field.
    """
    t = tokens()
    frame = qt.QFrame()
    frame.setObjectName("cohortFrame")
    frame.setStyleSheet(
        f"#cohortFrame {{ background-color: {t['FIELD']};"
        f" border: none; border-radius: {RADIUS_LG}px;"
        f" padding: {SPACING_MD}px; }}"
    )
    frame.setVisible(False)
    return frame


# How many batch lines the box shows before it stops listing them. Four fits
# the shape the queue actually takes -- at most two runs in flight plus the
# next couple waiting -- and a cohort of a hundred scans is twenty-five batches,
# which listed in full would be the tallest thing on the panel by a wide margin
# and would tell the reader nothing the headline count does not.
MAX_BATCH_ROWS = 4


def cohort_total_label(text: str) -> qt.QLabel:
    """"8 of 20 scans" -- the one number the user actually asked for.

    The largest text in the box, and deliberately the same 12pt semi-bold as
    `selection_label`: that one says what an input row holds, this says what a
    run has finished, and both are the answer rather than the offer. Counted in
    SCANS and not in batches, because a batch is an implementation detail of
    the transfer and nobody has twenty batches of work to do.
    """
    t = tokens()
    label = qt.QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {t['TEXT']}; font-size: 12pt; font-weight: 600;"
        f" border: none; padding: 0px;"
    )
    return label


def cohort_bar() -> qt.QProgressBar:
    """The whole cohort's progress, in one bar.

    Text off: the count underneath is exact and this is the impression. Unlike
    `progress_bar` it is shown for as long as the cohort runs -- there is always
    a real number behind it, because the number of scans in each batch is known
    before anything is sent.
    """
    bar = qt.QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setTextVisible(False)
    return bar


def batch_bar() -> qt.QProgressBar:
    """One batch's own progress, slim, under its line.

    Slim because a batch is a part: given the same weight as the cohort's bar,
    five of them would drown the one bar that answers the question. Shown only
    for a batch actually running -- an empty bar on each of four queued batches
    is four things that look stuck.
    """
    bar = qt.QProgressBar()
    bar.setRange(0, 100)
    bar.setValue(0)
    bar.setTextVisible(False)
    bar.setMaximumHeight(BATCH_BAR_HEIGHT)
    return bar


# Slim enough to read as a rule rather than a control, tall enough that its
# rounded chunk is not clipped to a sliver by the 1px border and 2px padding
# the base stylesheet gives every QProgressBar.
BATCH_BAR_HEIGHT = 8


def batch_label(text: str) -> qt.QLabel:
    """One batch's line: which batch it is, and what it is doing.

    Muted and small, the `hint_label` register: these are the detail under the
    headline, and a reader who only wants to know how far along the run is
    should be able to skip every one of them.
    """
    t = tokens()
    label = qt.QLabel(text)
    label.setWordWrap(True)
    label.setStyleSheet(
        f"color: {t['TEXT_MUTED']}; font-size: 9pt; border: none; padding: 0px;")
    return label
