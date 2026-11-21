"""DPI and font helpers for the GUI console.

Three facts drive this module:

- ttk widgets ignore ``root.option_add("*Font", ...)``; they read Tk's named
  fonts (``TkDefaultFont``, ``TkTextFont``, ...).  Reconfiguring those named
  fonts is the only global font switch that reaches every widget.
- Tk does not mark the process DPI-aware, so on a high-PPI laptop Windows
  reports 96 DPI to the app and 9pt UI text becomes physically tiny.  We opt
  into system DPI awareness *before* ``tk.Tk()`` and let Tk convert point
  sizes with the real DPI.
- The user-level size multiplier is machine-local (laptop vs lab monitor),
  so it is stored under ``%APPDATA%`` rather than in the DAQ profile.
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from pathlib import Path

#: Design size at 96 DPI.  11pt is ~22% larger than Tk's Windows default 9pt.
BASE_FONT_PT = 11
FONT_SCALE_OPTIONS = (1.0, 1.15, 1.30, 1.50)

_UI_FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
_FIXED_FONT_CANDIDATES = ("Consolas", "Courier New")

#: Tk named fonts used by the native widgets (ttk and classic).
_UI_NAMED_FONTS = (
    "TkDefaultFont",
    "TkTextFont",
    "TkMenuFont",
    "TkHeadingFont",
    "TkCaptionFont",
    "TkSmallCaptionFont",
    "TkIconFont",
    "TkTooltipFont",
)


def enable_dpi_awareness() -> bool:
    """Make the process system-DPI aware.

    Must run before the first ``tk.Tk()``; calling it later has no effect.
    System-aware (rather than per-monitor) is deliberate: Tk 8.6 does not
    handle ``WM_DPICHANGED``, so per-monitor mode would need manual rescaling
    on every monitor switch.
    """
    if sys.platform != "win32":
        return False
    try:
        # PROCESS_SYSTEM_DPI_AWARE = 1.  E_ACCESSDENIED (0x80070005) only
        # means awareness was already set, which is fine.
        result = ctypes.windll.shcore.SetProcessDpiAwareness(1)
        if result in (0, -2147024891):
            return True
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return True
    except Exception:
        return False


def dpi_scale(root) -> float:
    """Pixels per 96 logical DPI, e.g. 1.5 at 150% Windows scaling."""
    try:
        return max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except Exception:
        return 1.0


def font_size_pt(base_pt: int = BASE_FONT_PT, user_scale: float = 1.0) -> int:
    """Tk font size in points (Tk applies the DPI scaling itself)."""
    return max(8, int(base_pt * float(user_scale) + 0.5))


def _pick_family(root, candidates: tuple[str, ...]) -> str:
    import tkinter.font as tkfont

    families = set(tkfont.families(root))
    for name in candidates:
        if name in families:
            return name
    return tkfont.nametofont("TkDefaultFont").actual("family")


def apply_ui_fonts(root, size_pt: int) -> None:
    """Apply one size to every Tk named font used by the GUI.

    Existing widgets are reconfigured by Tk automatically, so this doubles as
    the live handler for the font-size selector.
    """
    import tkinter.font as tkfont

    ui_family = _pick_family(root, _UI_FONT_CANDIDATES)
    fixed_family = _pick_family(root, _FIXED_FONT_CANDIDATES)

    for name in _UI_NAMED_FONTS:
        try:
            tkfont.nametofont(name).configure(family=ui_family, size=size_pt)
        except Exception:
            pass
    try:
        # Logs / result areas (tk.Text) default to this font.
        tkfont.nametofont("TkFixedFont").configure(
            family=fixed_family, size=size_pt
        )
    except Exception:
        pass
    # Classic tk widgets (if any are added later) still read the option
    # database; ttk widgets are covered by the named fonts above.
    root.option_add("*Font", (ui_family, size_pt))


def window_geometry(
    screen_w: int,
    screen_h: int,
    dpi_scale_value: float = 1.0,
    user_scale: float = 1.0,
    base_w: int = 1100,
    base_h: int = 760,
    max_w_frac: float = 0.92,
    max_h_frac: float = 0.88,
) -> tuple[int, int, int, int]:
    """Return ``(width, height, x, y)`` capped to the visible screen.

    Both DPI and the user size multiplier grow the window, otherwise a
    DPI-aware build would look like a smaller window on a scaled laptop.
    """
    factor = max(0.8, float(dpi_scale_value)) * max(0.8, float(user_scale))
    width = min(round(base_w * factor), round(screen_w * max_w_frac))
    height = min(round(base_h * factor), round(screen_h * max_h_frac))
    width = max(1, int(width))
    height = max(1, int(height))
    x = max(0, (int(screen_w) - width) // 2)
    y = max(0, (int(screen_h) - height) // 3)
    return width, height, x, y


def nearest_font_scale(value: float) -> float:
    """Snap an arbitrary multiplier to one of the offered presets."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(FONT_SCALE_OPTIONS, key=lambda option: abs(option - number))


def _config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / ".config"
    return base / "daq-cli" / "gui.json"


def load_font_scale(path: str | Path | None = None) -> float:
    config_path = Path(path) if path is not None else _config_path()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return nearest_font_scale(float(data.get("font_scale", 1.0)))
    except Exception:
        return 1.0


def save_font_scale(scale: float, path: str | Path | None = None) -> None:
    config_path = Path(path) if path is not None else _config_path()
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = config_path.with_name(config_path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(
                {"font_scale": nearest_font_scale(scale)}, ensure_ascii=False
            ),
            encoding="utf-8",
        )
        os.replace(tmp_path, config_path)
    except OSError:
        # A read-only home directory must not break the GUI.
        pass


def apply_matplotlib_font_scale(factor: float) -> None:
    """Apply the user's font multiplier to embedded matplotlib figures.

    DPI is already handled by ``FigureCanvasTkAgg``, which sets the figure
    dpi to the Tk display dpi.  Multiplying by the DPI factor here as well
    double-scales the plot text and makes the layout look very loose.
    """
    try:
        import matplotlib
    except Exception:
        return
    factor = max(1.0, float(factor))
    matplotlib.rcParams.update(
        {
            "font.size": 10.0 * factor,
            "axes.titlesize": 11.0 * factor,
            "axes.labelsize": 10.0 * factor,
            "xtick.labelsize": 9.0 * factor,
            "ytick.labelsize": 9.0 * factor,
            "legend.fontsize": 9.0 * factor,
            "figure.titlesize": 12.0 * factor,
        }
    )
