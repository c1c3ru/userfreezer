#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Smoke grafico real, somente Xvfb Linux; nao faz operacoes privilegiadas."""
import argparse
import os
import subprocess
import tkinter as tk
from ui import health_panel


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--screenshot", required=True)
    args = p.parse_args()
    entries = [
        {"target": "/srv/lab-a", "state": "healthy",
         "frozen": True, "overlay": "/srv/lab-a.dfreezer",
         "baseline_paths": 23, "pending_ops": {"W": 1},
         "overlay_bytes": 4096, "overlay_size_partial": False},
        {"target": "/srv/lab-b", "state": "error",
         "frozen": False, "overlay": "/srv/lab-b.dfreezer",
         "baseline_paths": 0, "pending_ops": {},
         "overlay_bytes": 0, "overlay_size_partial": False,
         "error": "ACL nao aplicada"},
    ]
    snapshot = {"state": "degraded", "timestamp": "CI fixture",
                "scope": "application-level", "targets": entries}
    health_panel.request = lambda *a, **kw: {"ok": True, "result": snapshot}
    root = tk.Tk()
    try:
        panel = health_panel.AdminPanel(root)
        root.update()
        assert len(panel.table.get_children()) == 2
        assert "degraded" in panel.status.cget("text")
        root.geometry("+20+20")
        root.update()
        os.makedirs(os.path.dirname(os.path.abspath(args.screenshot)),
                    exist_ok=True)
        subprocess.run(["scrot", "-z", args.screenshot], check=True)
        assert os.path.getsize(args.screenshot) > 1000
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
