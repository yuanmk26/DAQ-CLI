"""daq-cli GUI console main window.

The GUI is a thin shell over the existing application services: it collects
form values, calls the services on background threads, and renders results.
All hardware/business logic stays in the application/infrastructure layers.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from daq_cli.application.profile_service import ProfileService

_LOG_MAX_LINES = 5000
_FONT_FAMILY = "Microsoft YaHei"
_FONT_SIZE = 9


class DaqGuiApp:
    """Main application window: profile bar, tab notebook, shared log panel."""

    def __init__(self, root: tk.Tk, profile_path: str | Path | None = None) -> None:
        self.root = root
        root.title("daq-cli 控制台")
        root.option_add("*Font", (_FONT_FAMILY, _FONT_SIZE))
        root.geometry("1100x760")

        self._profile_service = ProfileService()
        self.profile = None  # loaded ProfileData, refreshed on load
        self.profile_path: Path | None = None

        self._build_profile_bar(root)
        self._build_notebook(root)
        self._build_log_panel(root)

        self.tabs: list = [self.board_tab, self.acquire_tab, self.monitor_tab, self.tcm_tab]

        if profile_path is not None:
            self.load_profile(Path(profile_path))

        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------------------------------------------------------------- layout

    def _build_profile_bar(self, root: tk.Tk) -> None:
        bar = ttk.Frame(root, padding=(8, 6))
        bar.pack(side=tk.TOP, fill=tk.X)
        self._profile_var = tk.StringVar()
        profile_entry = ttk.Entry(bar, textvariable=self._profile_var, width=60)
        profile_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(bar, text="加载 Profile", command=self._choose_profile).pack(
            side=tk.LEFT, padx=(6, 0)
        )

    def _build_notebook(self, root: tk.Tk) -> None:
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=8, pady=(6, 0))

        # Imported lazily at the end of the module to keep the TkAgg backend
        # selection in cli/gui.py effective for matplotlib.
        from daq_cli.presentation.gui.boards_tab import BoardTab
        from daq_cli.presentation.gui.acquire_tab import AcquireTab
        from daq_cli.presentation.gui.monitor_tab import MonitorTab
        from daq_cli.presentation.gui.tcm_tab import TcmTab

        self.board_tab = BoardTab(self, self.notebook)
        self.acquire_tab = AcquireTab(self, self.notebook)
        self.monitor_tab = MonitorTab(self, self.notebook)
        self.tcm_tab = TcmTab(self, self.notebook)
        self.notebook.add(self.board_tab.frame, text="板卡")
        self.notebook.add(self.acquire_tab.frame, text="采集")
        self.notebook.add(self.monitor_tab.frame, text="监视")
        self.notebook.add(self.tcm_tab.frame, text="TCM")

    def _build_log_panel(self, root: tk.Tk) -> None:
        from tkinter import scrolledtext

        frame = ttk.LabelFrame(root, text="日志", padding=(6, 4))
        frame.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=8, pady=(4, 8))
        self._log_text = scrolledtext.ScrolledText(
            frame, height=10, state=tk.DISABLED, wrap=tk.WORD
        )
        self._log_text.pack(fill=tk.BOTH, expand=True)

    # ---------------------------------------------------------------- actions

    def _choose_profile(self) -> None:
        chosen = filedialog.askopenfilename(
            title="选择 profile 文件",
            filetypes=[("YAML 文件", "*.yaml *.yml"), ("所有文件", "*.*")],
        )
        if chosen:
            self.load_profile(Path(chosen))

    def load_profile(self, profile_path: Path) -> None:
        try:
            profile = self._profile_service.load_profile(profile_path)
        except Exception as exc:  # noqa: BLE001 - surface to the user
            self.log(f"Profile 加载失败: {exc}")
            return
        self.profile = profile
        self.profile_path = profile.path
        self._profile_var.set(str(profile.path))
        self.log(f"Profile 已加载: {profile.path}（设备 {len(profile.devices)}，"
                 f"组 {len(profile.groups)}，TCM {len(profile.tcm)}）")
        for tab in self.tabs:
            tab.refresh(profile)

    def schedule(self, callback) -> None:
        """Run ``callback`` on the GUI thread (tkinter-safe from workers)."""
        self.root.after(50, callback)

    def log(self, message: str) -> None:
        self._log_text.configure(state=tk.NORMAL)
        self._log_text.insert(tk.END, message + "\n")
        self._trim_log()
        self._log_text.see(tk.END)
        self._log_text.configure(state=tk.DISABLED)

    def _trim_log(self) -> None:
        line_count = int(self._log_text.index("end-1c").split(".")[0])
        if line_count > _LOG_MAX_LINES:
            self._log_text.delete("1.0", f"{line_count - _LOG_MAX_LINES}.0")

    def on_close(self) -> None:
        for tab in self.tabs:
            tab.shutdown()
        self.root.destroy()
