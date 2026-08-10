"""监视 tab：live/demo/replay 波形监视（matplotlib 嵌入）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class MonitorTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=8)

    def refresh(self, profile) -> None:
        """Re-populate device dropdowns when the profile changes."""

    def shutdown(self) -> None:
        """Stop any background work owned by this tab."""
