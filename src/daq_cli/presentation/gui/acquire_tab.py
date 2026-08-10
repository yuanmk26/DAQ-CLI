"""采集 tab：单板/多板采集控制与进度。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class AcquireTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=8)

    def refresh(self, profile) -> None:
        """Re-populate device/group dropdowns when the profile changes."""

    def shutdown(self) -> None:
        """Stop any background work owned by this tab."""
