"""Small reusable tkinter widgets for the GUI console."""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk


class ResultArea(ttk.LabelFrame):
    """Read-only scrollable text area used by every tab to show results."""

    def __init__(self, master, text: str = "结果", height: int = 14) -> None:
        super().__init__(master, text=text, padding=(6, 4))
        self._text = scrolledtext.ScrolledText(
            self, height=height, state=tk.DISABLED, wrap=tk.WORD
        )
        self._text.pack(fill=tk.BOTH, expand=True)

    def show(self, message: str) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.delete("1.0", tk.END)
        self._text.insert(tk.END, message + "\n")
        self._text.configure(state=tk.DISABLED)

    def append(self, message: str) -> None:
        self._text.configure(state=tk.NORMAL)
        self._text.insert(tk.END, message + "\n")
        self._text.see(tk.END)
        self._text.configure(state=tk.DISABLED)
