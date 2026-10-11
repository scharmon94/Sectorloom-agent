"""
The agent's window: settings at the top, activity log at the bottom.

Tkinter only, so there is nothing extra to install and the packaged
executable stays small.
"""
from __future__ import annotations

import os
import queue
import threading
import webbrowser
from typing import Any, Callable, Dict, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .cloud import Cloud, CloudError
from .watcher import default_dirs

PAD = {"padx": 10, "pady": 4}


class AgentWindow:
    def __init__(self, cfg: Dict[str, Any], save: Callable[[], None],
                 on_sign_in: Callable[[str, str], None],
                 on_scan_now: Callable[[], None],
                 on_quit: Callable[[], None],
                 on_retry: Optional[Callable[[], None]] = None):
        self.cfg = cfg
        self.save = save
        self.on_sign_in = on_sign_in
        self.on_scan_now = on_scan_now
        self.on_quit = on_quit
        self.on_retry = on_retry
        self.messages: "queue.Queue[str]" = queue.Queue()
        self.hidden = False

        self.root = tk.Tk()
        self.root.title("SectorLoom Telemetry Agent")
        self.root.geometry("680x560")
        self.root.minsize(620, 480)
        try:
            self.root.call("tk", "scaling", 1.2)
        except Exception:
            pass

        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.hide)
        self.root.after(200, self._drain)

    # ---- layout ---------------------------------------------------------
    def _build(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=8, pady=8)

        account = ttk.Frame(nb)
        folders = ttk.Frame(nb)
        activity = ttk.Frame(nb)
        nb.add(account, text="Account")
        nb.add(folders, text="Folders")
        nb.add(activity, text="Activity")
        self.nb = nb
        self.tab_activity = activity

        # --- account ---
        ttk.Label(account, text="These are the same details you use to sign in to the website.",
                  wraplength=600, foreground="#555").grid(row=0, column=0, columnspan=3, sticky="w", **PAD)

        # Only the site address is typed. Everything the agent needs to
        # reach the database is published in that site's config.js and is
        # read from there — a driver has no reason to know what Supabase
        # is, let alone go and find a key.
        self.v_site = tk.StringVar(value=self.cfg.get("site") or "https://sectorloom.com")
        self.v_email = tk.StringVar(value=self.cfg.get("email", ""))
        self.v_pass = tk.StringVar()

        rows = [
            ("Site address", self.v_site, False,
             "Leave this as it is unless you were given a different address"),
            ("Email", self.v_email, False, ""),
            ("Password", self.v_pass, True,
             "Used once to sign in. Only a session token is kept, never this."),
        ]
        for i, (label, var, secret, hint) in enumerate(rows, start=1):
            ttk.Label(account, text=label).grid(row=i * 2 - 1, column=0, sticky="w", **PAD)
            entry = ttk.Entry(account, textvariable=var, width=58, show="•" if secret else "")
            entry.grid(row=i * 2 - 1, column=1, sticky="we", **PAD)
            if hint:
                ttk.Label(account, text=hint, foreground="#777", font=("", 8)).grid(
                    row=i * 2, column=1, sticky="w", padx=10)
        account.columnconfigure(1, weight=1)

        self.status_label = ttk.Label(account, text="Not signed in.", foreground="#b00")
        self.status_label.grid(row=9, column=0, columnspan=2, sticky="w", **PAD)

        buttons = ttk.Frame(account)
        buttons.grid(row=10, column=0, columnspan=2, sticky="w", **PAD)
        ttk.Button(buttons, text="Sign in and save", command=self._sign_in).pack(side="left")
        ttk.Button(buttons, text="Open the website", command=self._open_site).pack(side="left", padx=6)

        # --- folders ---
        d = default_dirs()
        self.v_watch_ir = tk.BooleanVar(value=self.cfg.get("watch_iracing", True))
        self.v_watch_lmu = tk.BooleanVar(value=self.cfg.get("watch_lmu", True))
        self.v_dir_ir = tk.StringVar(value=self.cfg.get("iracing_dir") or d["iracing"])
        self.v_dir_lmu = tk.StringVar(value=self.cfg.get("lmu_dir") or d["lmu"])
        self.v_startup = tk.BooleanVar(value=self.cfg.get("start_with_windows", False))

        def folder_row(parent, row, check_var, label, path_var):
            ttk.Checkbutton(parent, text=label, variable=check_var).grid(
                row=row, column=0, sticky="w", **PAD)
            ttk.Entry(parent, textvariable=path_var, width=52).grid(
                row=row + 1, column=0, columnspan=2, sticky="we", **PAD)
            ttk.Button(parent, text="Browse…",
                       command=lambda: self._browse(path_var)).grid(row=row + 1, column=2, padx=6)

        folder_row(folders, 0, self.v_watch_ir, "Watch iRacing", self.v_dir_ir)
        folder_row(folders, 2, self.v_watch_lmu, "Watch Le Mans Ultimate", self.v_dir_lmu)
        ttk.Separator(folders, orient="horizontal").grid(
            row=4, column=0, columnspan=3, sticky="we", pady=10, padx=10)
        ttk.Checkbutton(folders, text="Start automatically when Windows starts",
                        variable=self.v_startup).grid(row=5, column=0, sticky="w", **PAD)
        ttk.Label(folders,
                  text="Turn telemetry on in each sim first, or these folders stay empty:\n"
                       "   iRacing — press Alt+L on track, or set it to always log\n"
                       "   Le Mans Ultimate — Settings → Gameplay → telemetry recording",
                  foreground="#555", justify="left").grid(
            row=6, column=0, columnspan=3, sticky="w", **PAD)
        ttk.Button(folders, text="Save folders", command=self._save_folders).grid(
            row=7, column=0, sticky="w", **PAD)
        folders.columnconfigure(0, weight=1)

        # --- activity ---
        self.log_box = tk.Text(activity, wrap="word", height=18, state="disabled",
                               font=("Consolas", 9))
        scroll = ttk.Scrollbar(activity, command=self.log_box.yview)
        self.log_box.configure(yscrollcommand=scroll.set)
        self.log_box.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
        scroll.pack(side="right", fill="y", padx=(0, 10), pady=10)

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=8, pady=(0, 8))
        self.foot = ttk.Label(bar, text="Starting…", foreground="#555")
        self.foot.pack(side="left")
        ttk.Button(bar, text="Quit", command=self.on_quit).pack(side="right")
        ttk.Button(bar, text="Check now", command=self.on_scan_now).pack(side="right", padx=6)
        if self.on_retry:
            ttk.Button(bar, text="Retry failed files",
                       command=self.on_retry).pack(side="right", padx=6)
        ttk.Button(bar, text="Hide", command=self.hide).pack(side="right")

    # ---- actions --------------------------------------------------------
    def _browse(self, var: tk.StringVar) -> None:
        start = var.get() if os.path.isdir(var.get()) else os.path.expanduser("~")
        chosen = filedialog.askdirectory(initialdir=start, parent=self.root)
        if chosen:
            var.set(chosen)

    def _open_site(self) -> None:
        url = self.v_site.get().strip()
        if url:
            webbrowser.open(url if url.startswith("http") else "https://" + url)

    def _save_folders(self) -> None:
        self.cfg["watch_iracing"] = self.v_watch_ir.get()
        self.cfg["watch_lmu"] = self.v_watch_lmu.get()
        self.cfg["iracing_dir"] = self.v_dir_ir.get().strip()
        self.cfg["lmu_dir"] = self.v_dir_lmu.get().strip()
        self.cfg["start_with_windows"] = self.v_startup.get()
        self.save()
        from .startup import set_start_with_windows
        ok, msg = set_start_with_windows(self.v_startup.get())
        self.log("Folders saved." + ("" if ok else f" ({msg})"))
        messagebox.showinfo("SectorLoom", "Saved." if ok else f"Saved, but: {msg}", parent=self.root)

    def _sign_in(self) -> None:
        site = self.v_site.get().strip()
        if site != (self.cfg.get("site") or ""):
            # a different site means a different project; drop what was
            # cached for the old one rather than signing in against it
            self.cfg["url"] = self.cfg["key"] = ""
        self.cfg["site"] = site
        self.cfg["email"] = self.v_email.get().strip()
        self.set_status("Signing in…", "#555")
        password = self.v_pass.get()

        def work():
            try:
                self.on_sign_in(self.cfg["email"], password)
                self.root.after(0, lambda: self.set_status(
                    f"Signed in as {self.cfg['email']}.", "#070"))
                self.root.after(0, lambda: self.v_pass.set(""))
            except Exception as e:
                msg = str(e)
                self.root.after(0, lambda: self.set_status(msg, "#b00"))

        threading.Thread(target=work, daemon=True).start()

    # ---- window state ---------------------------------------------------
    def set_status(self, text: str, colour: str = "#555") -> None:
        self.status_label.configure(text=text, foreground=colour)

    def set_foot(self, text: str) -> None:
        self.foot.configure(text=text)

    def log(self, line: str) -> None:
        self.messages.put(line)

    def _drain(self) -> None:
        wrote = False
        while True:
            try:
                line = self.messages.get_nowait()
            except queue.Empty:
                break
            self.log_box.configure(state="normal")
            self.log_box.insert("end", line + "\n")
            self.log_box.configure(state="disabled")
            wrote = True
        if wrote:
            self.log_box.see("end")
        self.root.after(200, self._drain)

    def show(self) -> None:
        self.hidden = False
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception:
            pass

    def hide(self) -> None:
        self.hidden = True
        try:
            self.root.withdraw()
        except Exception:
            pass

    def show_activity(self) -> None:
        self.show()
        try:
            self.nb.select(self.tab_activity)
        except Exception:
            pass
            pass
