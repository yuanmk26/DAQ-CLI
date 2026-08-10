"""TCM tab：TCM 板触发联动配置与状态。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class TcmTab:
    def __init__(self, app, notebook) -> None:
        self.app = app
        self.frame = ttk.Frame(notebook, padding=8)

    def refresh(self, profile) -> None:
        """Re-populate TCM dropdowns when the profile changes."""

    def shutdown(self) -> None:
        """Stop any background work owned by this tab."""
