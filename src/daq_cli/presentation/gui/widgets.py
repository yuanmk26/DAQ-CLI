"""Small reusable tkinter widgets for the GUI console."""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext, ttk


class ScrollableFrame(ttk.Frame):
    """Vertical-scrollable container.

    Children go into ``.inner``. The canvas tracks the content height: when
    the content fits the viewport no scrollbar is shown; when it overflows
    the vertical scrollbar appears. Mouse wheel works over the whole area.
    """

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._canvas = tk.Canvas(self, highlightthickness=0)
        self._scrollbar = ttk.Scrollbar(
            self, orient="vertical", command=self._canvas.yview
        )
        self.inner = ttk.Frame(self._canvas)
        self._window = self._canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )
        self._canvas.configure(yscrollcommand=self._scrollbar.set)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._wheel_bound: set[int] = set()

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)
        self.bind_wheel(self._canvas)
        self.bind_wheel(self.inner)

    def bind_wheel(self, widget) -> None:
        """Let the mouse wheel over ``widget`` scroll this frame.

        Idempotent: each widget is bound at most once, so widgets created
        after construction (embedded canvases, tab pages) can safely call
        this again.
        """
        if id(widget) in self._wheel_bound:
            return
        self._wheel_bound.add(id(widget))
        widget.bind("<MouseWheel>", self._on_mousewheel, add="+")

    def _bind_wheel_recursive(self, widget) -> None:
        for child in widget.winfo_children():
            # Text widgets (including ScrolledText) scroll themselves; the
            # wheel over them must not also scroll the page.
            if isinstance(child, tk.Text):
                continue
            self.bind_wheel(child)
            self._bind_wheel_recursive(child)

    def _on_inner_configure(self, _event) -> None:
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        # Children created after construction (tab pages, embedded canvases)
        # get the wheel binding once they appear.
        self._bind_wheel_recursive(self.inner)

    def _on_canvas_configure(self, event) -> None:
        # Keep the inner frame at the canvas width so children fill it.
        self._canvas.itemconfigure(self._window, width=event.width)

    def _on_mousewheel(self, event) -> str:
        self._canvas.yview_scroll(int(-event.delta / 120), "units")
        return "break"


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
