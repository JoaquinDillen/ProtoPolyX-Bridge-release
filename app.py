"""
app.py — URSim → ProtoTwin Bridge Control Panel

A CustomTkinter GUI that manages the full digital twin pipeline:
  1. Docker Desktop
  2. URSim container
  3. ProtoTwin Connect desktop app
  4. PolyScope X (browser)
  5. ProtoTwin model (browser, confirmed by user)
  6. The bridge script

Run from the same conda environment where ur-rtde and prototwin are installed:
    python app.py
"""

import asyncio
import customtkinter as ctk
import subprocess
import threading
import queue
import sys
import socket
import json
import webbrowser
import re
import time
import struct
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

APP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
WRITABLE_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

DOCKER_EXE_PATHS = [
    r"C:\Program Files\Docker\Docker\Docker Desktop.exe",
    r"C:\Program Files\Docker Desktop\Docker Desktop.exe",
]
DOCKER_INSTALL_URL = "https://docs.docker.com/desktop/setup/install/windows-install/"

PROTOTWIN_CONNECT_EXE_PATHS = [
    Path.home() / "AppData/Local/Programs/ProtoTwinConnect/ProtoTwinConnect.exe",
    Path.home() / "AppData/Local/ProtoTwinConnect/ProtoTwinConnect.exe",
    r"C:\Program Files\ProtoTwin\ProtoTwinConnect.exe",
]
PROTOTWIN_CONNECT_INSTALL_URL = "https://prototwin.com/account/signin"

# Start Menu folder — used as fallback if the exe path isn't found directly
PROTOTWIN_STARTMENU = Path(
    r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\ProtoTwin Connect"
)

URSIM_DOCKER_CMD = (
    "docker run --rm --privileged "
    "--add-host host.docker.internal:host-gateway "
    "--env HOST_ARCH=amd64 "
    "--network bridge "
    "-p 127.0.0.1:8000:80 "     # PolyScope X web UI
    "-p 127.0.0.1:29999:29999 " # Dashboard Server
    "-p 127.0.0.1:30004:30004 " # RTDE
    "-p 127.0.0.1:502:502 "     # Modbus TCP Server
    "universalrobots/ursim_polyscopex:latest"
)

POLYSCOPE_URL   = "http://localhost:8000"
PROTOTWIN_URL   = "https://play.prototwin.com"
CONFIG_PATH     = WRITABLE_DIR / "bridge_config.json"

DEFAULT_JOINT_ADDRESSES       = [18, 39, 11, 32, 46, 25]
DEFAULT_JOINT_DIRECTIONS      = [-1, 1, -1, 1, -1, 1]
JOINT_NAMES_SHORT             = ["base", "shld", "elbw", "wst1", "wst2", "wst3"]
DEFAULT_RIGHT_FINGER_ADDRESS  = 60
DEFAULT_LEFT_FINGER_ADDRESS   = 53
BRIDGE_SCRIPT   = APP_DIR / "bridge.py"
GRIPPER_CMD_PATH = WRITABLE_DIR / "gripper_cmd.json"
APP_ICON_PATH = APP_DIR / "AppIcon.ico"
MODBUS_HOST = "127.0.0.1"
MODBUS_PORT = 502
MODBUS_UNIT_ID = 255
MODBUS_GRIPPER_REGISTER = 134
GRIPPER_MODBUS_SCALE = 10000

DEFAULT_BRIDGE_CONFIG = {
    "joint_signal_addresses": list(DEFAULT_JOINT_ADDRESSES),
    "joint_directions": list(DEFAULT_JOINT_DIRECTIONS),
    "right_finger_address": DEFAULT_RIGHT_FINGER_ADDRESS,
    "left_finger_address": DEFAULT_LEFT_FINGER_ADDRESS,
}
DEFAULT_GRIPPER_CMD = {"value": 0.0}

POLL_INTERVAL_MS = 2000   # service status poll interval


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def is_docker_running() -> bool:
    try:
        r = subprocess.run(
            ["docker", "info"],
            capture_output=True, timeout=5
        )
        return r.returncode == 0
    except Exception:
        return False


def is_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except Exception:
        return False


def write_modbus_register(register: int, value: int) -> None:
    transaction_id = int(time.time() * 1000) & 0xFFFF
    request = struct.pack(
        ">HHHBBHH",
        transaction_id,
        0,
        6,
        MODBUS_UNIT_ID,
        0x06,  # Write Single Register
        register,
        value,
    )
    with socket.create_connection((MODBUS_HOST, MODBUS_PORT), timeout=1) as conn:
        conn.sendall(request)
        response = conn.recv(260)
    if len(response) < 12 or response[7] & 0x80:
        raise ConnectionError(f"Modbus write failed: {response.hex(' ')}")



def find_exe(paths) -> str | None:
    for p in paths:
        if Path(p).exists():
            return str(p)
    return None


def check_dependencies() -> list[str]:
    missing = []
    for pkg, imp in [("ur-rtde", "rtde_receive"), ("prototwin", "prototwin")]:
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    return missing


def ensure_runtime_files() -> None:
    if not CONFIG_PATH.exists():
        with open(CONFIG_PATH, "w") as f:
            json.dump(DEFAULT_BRIDGE_CONFIG, f, indent=2)
    if not GRIPPER_CMD_PATH.exists():
        with open(GRIPPER_CMD_PATH, "w") as f:
            json.dump(DEFAULT_GRIPPER_CMD, f)


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION
# ─────────────────────────────────────────────────────────────────────────────

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("URSim → ProtoTwin Bridge")
        if APP_ICON_PATH.exists():
            try:
                self.iconbitmap(str(APP_ICON_PATH))
            except Exception:
                pass
        self.geometry("640x820")
        self.resizable(False, True)

        self._bridge_proc: subprocess.Popen | None = None
        self._ursim_proc:  subprocess.Popen | None = None
        self._log_queue:   queue.Queue = queue.Queue()

        # cached statuses from last poll (avoids blocking the UI thread)
        self._docker_ok    = False
        self._ursim_ok     = False
        self._ptconnect_ok = False
        self._modbus_ok    = False

        # URSim boot timer
        self._ursim_start_time: float | None = None

        # Set to True when the "Simulator Is Ready" banner appears in URSim output
        self._simulator_ready = False

        # Settings popup (only one at a time)
        self._settings_window: ctk.CTkToplevel | None = None

        # StringVars for live joint angle display (shared with Settings popup)
        self._angle_strvars: list[ctk.StringVar] = [ctk.StringVar(value="—") for _ in range(6)]

        # Per-joint direction values (+1 or -1); loaded/saved via Settings
        self._dir_values: list[int] = [1, 1, 1, 1, 1, 1]
        self._dir_btns:   list[ctk.CTkButton] = []
        self._gripper_mode_var = ctk.StringVar(value="Both")
        self._gripper_write_after_id: str | None = None
        self._gripper_pending_value = 0.0
        self._gripper_controls_enabled: bool | None = None
        self._gripper_status_key: tuple[bool, bool] | None = None

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        ensure_runtime_files()
        self._build_ui()
        self._check_first_run()
        self._poll_status()
        self._drain_log()

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        PAD = {"padx": 16, "pady": 6}

        # ── Header
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=16, pady=(16, 4))

        ctk.CTkButton(
            hdr, text="Settings", width=90,
            command=self._open_settings
        ).pack(side="right", anchor="center")

        titles = ctk.CTkFrame(hdr, fg_color="transparent")
        titles.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(
            titles, text="URSim -> ProtoTwin Bridge",
            font=ctk.CTkFont(size=20, weight="bold")
        ).pack(anchor="w")
        ctk.CTkLabel(
            titles, text="Digital twin control panel",
            font=ctk.CTkFont(size=12), text_color="gray"
        ).pack(anchor="w")

        # ── Services
        svc = ctk.CTkFrame(self)
        svc.pack(fill="x", **PAD)
        self._section_label(svc, "SERVICES")
        self._docker_row    = self._service_row(
            svc, "Docker Desktop", self._launch_docker,
            install_url=DOCKER_INSTALL_URL
        )
        self._ursim_row     = self._service_row(svc, "URSim Container",   self._start_ursim,
                                                stop_cmd=self._stop_ursim,
                                                initially_disabled=True)
        self._ptconnect_row = self._service_row(
            svc, "ProtoTwin Connect", self._launch_ptconnect,
            install_url=PROTOTWIN_CONNECT_INSTALL_URL
        )

        # ── Browser
        brw = ctk.CTkFrame(self)
        brw.pack(fill="x", **PAD)
        self._section_label(brw, "BROWSER")
        self._polyscope_row = self._browser_row(
            brw, "PolyScope X",
            lambda: webbrowser.open(POLYSCOPE_URL),
            initially_disabled=True
        )
        self._polyscope_status_lbl = self._polyscope_row["status"]
        self._ptmodel_row, self._model_ready_var = self._model_row(brw)

        # ── Bridge controls
        bctrl = ctk.CTkFrame(self)
        bctrl.pack(fill="x", **PAD)
        self._section_label(bctrl, "BRIDGE")

        btn_row = ctk.CTkFrame(bctrl, fg_color="transparent")
        btn_row.pack(fill="x", padx=12, pady=(0, 10))

        self._start_btn = ctk.CTkButton(
            btn_row, text="Start Bridge", width=140,
            command=self._start_bridge, state="disabled"
        )
        self._start_btn.pack(side="left", padx=(0, 8))

        self._stop_btn = ctk.CTkButton(
            btn_row, text="Stop", width=80,
            fg_color="#c0392b", hover_color="#922b21",
            command=self._stop_bridge, state="disabled"
        )
        self._stop_btn.pack(side="left")

        self._bridge_status_lbl = ctk.CTkLabel(
            btn_row, text="● Stopped",
            text_color="#e74c3c", font=ctk.CTkFont(size=13)
        )
        self._bridge_status_lbl.pack(side="right")

        opts_row = ctk.CTkFrame(bctrl, fg_color="transparent")
        opts_row.pack(fill="x", padx=12, pady=(0, 8))
        self._home_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            opts_row,
            text="Home robot on start  (requires Remote Control mode in PolyScope X)",
            variable=self._home_var,
            font=ctk.CTkFont(size=11)
        ).pack(side="left")

        # ── Gripper
        grp = ctk.CTkFrame(self)
        grp.pack(fill="x", **PAD)
        self._section_label(grp, "GRIPPER")
        self._build_gripper_section(grp)

        # ── Joint angles
        ang = ctk.CTkFrame(self)
        ang.pack(fill="x", **PAD)
        self._section_label(ang, "JOINT ANGLES")

        grid = ctk.CTkFrame(ang, fg_color="transparent")
        grid.pack(fill="x", padx=12, pady=(0, 10))

        self._angle_labels: dict[str, ctk.CTkLabel] = {}
        joints = ["base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"]
        for i, name in enumerate(joints):
            col = ctk.CTkFrame(grid, fg_color="transparent")
            col.grid(row=0, column=i, padx=8)
            ctk.CTkLabel(
                col, text=name,
                font=ctk.CTkFont(size=10), text_color="gray"
            ).pack()
            lbl = ctk.CTkLabel(
                col, textvariable=self._angle_strvars[i],
                font=ctk.CTkFont(size=14, weight="bold")
            )
            lbl.pack()
            self._angle_labels[name] = lbl

        # ── Footer — packed before the expanding console so it always gets space
        ctk.CTkLabel(
            self, text="Designed by Joaquin Dillen",
            font=ctk.CTkFont(size=9), text_color="gray"
        ).pack(side="bottom", anchor="e", padx=16, pady=(0, 6))

        # ── Console
        log = ctk.CTkFrame(self)
        log.pack(fill="both", expand=True, **PAD)
        self._section_label(log, "CONSOLE")

        self._log_box = ctk.CTkTextbox(
            log,
            font=ctk.CTkFont(family="Consolas", size=11),
            state="disabled", wrap="word"
        )
        self._log_box.pack(fill="both", expand=True, padx=12, pady=(0, 10))

    def _section_label(self, parent, text: str):
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
        ).pack(anchor="w", padx=12, pady=(8, 2))

    def _service_row(
        self,
        parent,
        label: str,
        cmd,
        stop_cmd=None,
        initially_disabled=False,
        install_url: str | None = None,
    ) -> dict:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=3)

        ctk.CTkLabel(frame, text=label, width=170, anchor="w").pack(side="left")

        status = ctk.CTkLabel(
            frame, text="● Checking…",
            text_color="gray", font=ctk.CTkFont(size=13),
            width=120, anchor="w"
        )
        status.pack(side="left")

        stop_btn = None
        if stop_cmd:
            stop_btn = ctk.CTkButton(
                frame, text="Stop", width=70,
                fg_color="#c0392b", hover_color="#922b21",
                command=stop_cmd, state="disabled"
            )
            stop_btn.pack(side="right", padx=(4, 0))

        btn = ctk.CTkButton(
            frame, text="Launch", width=90, command=cmd,
            state="disabled" if initially_disabled else "normal"
        )
        btn.pack(side="right")

        install_btn = None
        if install_url is not None:
            install_btn = ctk.CTkButton(
                frame,
                text="Install",
                width=70,
                fg_color="gray35",
                hover_color="gray28",
                command=lambda url=install_url: webbrowser.open(url),
            )
            install_btn.pack(side="right", padx=(0, 4))

        return {"status": status, "btn": btn, "stop_btn": stop_btn, "install_btn": install_btn}

    def _browser_row(self, parent, label: str, cmd, initially_disabled=False) -> dict:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=3)

        ctk.CTkLabel(frame, text=label, width=170, anchor="w").pack(side="left")

        status_lbl = ctk.CTkLabel(
            frame, text="",
            text_color="gray", font=ctk.CTkFont(size=13),
            width=120, anchor="w"
        )
        status_lbl.pack(side="left")

        btn = ctk.CTkButton(
            frame, text="Open", width=90, command=cmd,
            state="disabled" if initially_disabled else "normal"
        )
        btn.pack(side="right")

        return {"btn": btn, "status": status_lbl}

    def _model_row(self, parent) -> tuple[dict, ctk.BooleanVar]:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(fill="x", padx=12, pady=3)

        ctk.CTkLabel(frame, text="ProtoTwin Model", width=170, anchor="w").pack(side="left")

        var = ctk.BooleanVar(value=False)
        chk = ctk.CTkCheckBox(
            frame, text="Model loaded & ready",
            variable=var, command=self._update_start_btn
        )
        chk.pack(side="left")

        btn = ctk.CTkButton(
            frame, text="Open", width=90,
            command=lambda: webbrowser.open(PROTOTWIN_URL)
        )
        btn.pack(side="right")

        return {"btn": btn, "chk": chk}, var

    # ── Settings popup ───────────────────────────────────────────────────────

    def _load_bridge_config(self) -> dict:
        try:
            with open(CONFIG_PATH) as f:
                data = json.load(f)
            return {
                "joint_signal_addresses": data.get("joint_signal_addresses", DEFAULT_JOINT_ADDRESSES),
                "joint_directions":       data.get("joint_directions",       DEFAULT_JOINT_DIRECTIONS),
                "right_finger_address":   data.get("right_finger_address",   DEFAULT_RIGHT_FINGER_ADDRESS),
                "left_finger_address":    data.get("left_finger_address",    DEFAULT_LEFT_FINGER_ADDRESS),
            }
        except Exception:
            return {
                "joint_signal_addresses": list(DEFAULT_JOINT_ADDRESSES),
                "joint_directions":       list(DEFAULT_JOINT_DIRECTIONS),
                "right_finger_address":   DEFAULT_RIGHT_FINGER_ADDRESS,
                "left_finger_address":    DEFAULT_LEFT_FINGER_ADDRESS,
            }

    def _open_settings(self):
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.focus()
            return

        win = ctk.CTkToplevel(self)
        win.title("Signal Address Mapping")
        win.geometry("620x660")
        win.resizable(False, False)
        win.grab_set()
        self._settings_window = win

        config     = self._load_bridge_config()
        addresses  = config["joint_signal_addresses"]
        directions = config["joint_directions"]

        # Sync in-memory direction state with loaded config
        self._dir_values = list(directions)
        self._dir_btns   = []

        bridge_running  = self._bridge_proc is not None and self._bridge_proc.poll() is None
        ptconnect_ready = is_port_open(8084)
        test_enabled    = ptconnect_ready and not bridge_running

        # ── Header ──────────────────────────────────────────────────────────
        ctk.CTkLabel(
            win, text="Signal Address Mapping",
            font=ctk.CTkFont(size=16, weight="bold")
        ).pack(anchor="w", padx=20, pady=(16, 2))
        ctk.CTkLabel(
            win,
            text="Enter the Motor 'Target Position' address for each joint.\n"
                 "Dir ▲/▼ flips the axis direction. Live shows the current RTDE angle.",
            font=ctk.CTkFont(size=11), text_color="gray", justify="left"
        ).pack(anchor="w", padx=20, pady=(0, 4))

        if bridge_running:
            ctk.CTkLabel(
                win, text="  Bridge running — Test disabled. Dir and Live are active.",
                font=ctk.CTkFont(size=11), text_color="#f39c12"
            ).pack(anchor="w", padx=20, pady=(0, 6))
        elif not ptconnect_ready:
            ctk.CTkLabel(
                win, text="  Start ProtoTwin Connect to enable Test buttons.",
                font=ctk.CTkFont(size=11), text_color="gray"
            ).pack(anchor="w", padx=20, pady=(0, 6))
        else:
            ctk.CTkLabel(
                win, text="  ProtoTwin Connect is running — Test buttons are active.",
                font=ctk.CTkFont(size=11), text_color="#2ecc71"
            ).pack(anchor="w", padx=20, pady=(0, 6))

        # ── Column headers ───────────────────────────────────────────────────
        hdr = ctk.CTkFrame(win, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(4, 0))
        ctk.CTkLabel(hdr, text="URSim Joint", width=140, anchor="w",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")
        ctk.CTkLabel(hdr, text="Addr",        width=71,  anchor="w",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")
        ctk.CTkLabel(hdr, text="Dir",         width=52,  anchor="center",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")
        ctk.CTkLabel(hdr, text="",            width=68               ).pack(side="left")
        ctk.CTkLabel(hdr, text="Live (RTDE)", width=80,  anchor="w",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")
        ctk.CTkLabel(hdr, text="Status",      anchor="w",
                     font=ctk.CTkFont(size=11), text_color="gray").pack(side="left")

        # ── Joint rows ───────────────────────────────────────────────────────
        _JOINT_FULL = ["Base (J1)", "Shoulder (J2)", "Elbow (J3)",
                       "Wrist 1 (J4)", "Wrist 2 (J5)", "Wrist 3 (J6)"]
        self._addr_entries: list[ctk.CTkEntry] = []

        for i, (name, addr) in enumerate(zip(_JOINT_FULL, addresses)):
            self._settings_address_row(
                win, name, str(addr),
                is_finger=False, test_enabled=test_enabled,
                entry_list=self._addr_entries,
                dir_idx=i,
                angle_var=self._angle_strvars[i],
            )

        # ── Gripper section ──────────────────────────────────────────────────
        ctk.CTkLabel(
            win, text="GRIPPER FINGERS",
            font=ctk.CTkFont(size=11, weight="bold"), text_color="gray"
        ).pack(anchor="w", padx=20, pady=(14, 2))

        self._right_finger_entry = self._settings_address_row(
            win, "Right Finger", str(config["right_finger_address"]),
            is_finger=True, test_enabled=test_enabled)
        self._left_finger_entry = self._settings_address_row(
            win, "Left Finger", str(config["left_finger_address"]),
            is_finger=True, test_enabled=test_enabled)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(18, 16))
        ctk.CTkButton(
            btn_row, text="Close", width=80,
            fg_color="gray40", hover_color="gray30",
            command=win.destroy
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btn_row, text="Save", width=100,
            command=self._save_bridge_config
        ).pack(side="right")

    def _settings_address_row(
        self, parent, label: str, value: str,
        is_finger: bool, test_enabled: bool,
        entry_list: list | None = None,
        dir_idx: int | None = None,
        angle_var: ctk.StringVar | None = None,
    ) -> ctk.CTkEntry:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=2)

        ctk.CTkLabel(row, text=label, width=140, anchor="w").pack(side="left")

        entry = ctk.CTkEntry(row, width=65, justify="center")
        entry.insert(0, value)
        entry.pack(side="left", padx=(0, 6))
        if entry_list is not None:
            entry_list.append(entry)

        # Direction toggle (joints only)
        if dir_idx is not None:
            d_text = "▲" if self._dir_values[dir_idx] > 0 else "▼"
            dir_btn = ctk.CTkButton(
                row, text=d_text, width=46,
                font=ctk.CTkFont(size=13),
                command=lambda idx=dir_idx: self._toggle_direction(idx)
            )
            dir_btn.pack(side="left", padx=(0, 6))
            self._dir_btns.append(dir_btn)
        else:
            ctk.CTkLabel(row, text="", width=52).pack(side="left")

        status_lbl = ctk.CTkLabel(row, text="", width=80, anchor="w",
                                  font=ctk.CTkFont(size=12))
        ctk.CTkButton(
            row, text="Test", width=62,
            state="normal" if test_enabled else "disabled",
            command=lambda e=entry, s=status_lbl, f=is_finger: self._test_address(e, s, f)
        ).pack(side="left", padx=(0, 6))

        # Live RTDE angle (joints only)
        if angle_var is not None:
            ctk.CTkLabel(
                row, textvariable=angle_var, width=76, anchor="w",
                font=ctk.CTkFont(size=12), text_color="#3498db"
            ).pack(side="left", padx=(0, 4))
        else:
            ctk.CTkLabel(row, text="", width=80).pack(side="left")

        status_lbl.pack(side="left")

        return entry

    def _toggle_direction(self, idx: int):
        self._dir_values[idx] *= -1
        self._dir_btns[idx].configure(text="▲" if self._dir_values[idx] > 0 else "▼")

    def _test_address(self, entry: ctk.CTkEntry, status_lbl: ctk.CTkLabel, is_finger: bool):
        try:
            address = int(entry.get())
        except ValueError:
            status_lbl.configure(text="bad address", text_color="#e74c3c")
            return
        status_lbl.configure(text="● pulsing…", text_color="#f39c12")
        threading.Thread(
            target=self._run_test_pulse,
            args=(address, is_finger, status_lbl),
            daemon=True
        ).start()

    def _run_test_pulse(self, address: int, is_finger: bool, status_lbl: ctk.CTkLabel):
        try:
            import prototwin  # type: ignore
            asyncio.run(self._async_test_pulse(prototwin, address, is_finger, status_lbl))
        except Exception as exc:
            self.after(0, lambda: status_lbl.configure(
                text="● error", text_color="#e74c3c"))
            self._log(f"[Test] addr {address}: {exc}")

    async def _async_test_pulse(self, prototwin_mod, address: int,
                                 is_finger: bool, status_lbl: ctk.CTkLabel):
        client = await prototwin_mod.attach()
        await client.sync()
        original  = client.get(address)
        pulse_val = 0.35       if is_finger else original + 25.0
        rest_val  = 0.0        if is_finger else original
        client.set(address, pulse_val)
        await client.sync()
        await asyncio.sleep(1.2)
        client.set(address, rest_val)
        await client.sync()
        self.after(0, lambda: status_lbl.configure(
            text="● moved", text_color="#2ecc71"))

    def _save_bridge_config(self):
        try:
            addresses    = [int(e.get()) for e in self._addr_entries]
            right_finger = int(self._right_finger_entry.get())
            left_finger  = int(self._left_finger_entry.get())
        except ValueError:
            self._log("Config error: all addresses must be integers.")
            return
        data = {
            "joint_signal_addresses": addresses,
            "joint_directions":       list(self._dir_values),
            "right_finger_address":   right_finger,
            "left_finger_address":    left_finger,
        }
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
        self._log(f"Config saved: joints={addresses}, directions={self._dir_values}, fingers=[{right_finger}, {left_finger}]")
        self._log("Restart the bridge to apply changes.")

    # ── Gripper section ──────────────────────────────────────────────────────

    def _build_gripper_section(self, parent):
        status_row = ctk.CTkFrame(parent, fg_color="transparent")
        status_row.pack(fill="x", padx=12, pady=(0, 4))

        self._gripper_status_lbl = ctk.CTkLabel(
            status_row,
            text="● Waiting for bridge or Modbus",
            text_color="gray",
            font=ctk.CTkFont(size=12),
            anchor="w",
            width=260,
        )
        self._gripper_status_lbl.pack(side="left")

        self._gripper_raw_lbl = ctk.CTkLabel(
            status_row,
            text="Modbus raw: —",
            text_color="gray",
            font=ctk.CTkFont(size=12),
            anchor="e",
            width=130,
        )
        self._gripper_raw_lbl.pack(side="right")

        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(0, 10))

        self._gripper_open_btn = ctk.CTkButton(
            row, text="Open", width=70,
            command=lambda: self._set_gripper(0.0),
            state="disabled"
        )
        self._gripper_open_btn.pack(side="left", padx=(0, 4))

        self._gripper_close_btn = ctk.CTkButton(
            row, text="Close", width=70,
            command=lambda: self._set_gripper(0.4),
            state="disabled"
        )
        self._gripper_close_btn.pack(side="left", padx=(0, 12))

        ctk.CTkLabel(
            row,
            text="Output",
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(side="left", padx=(0, 4))

        self._gripper_mode = ctk.CTkOptionMenu(
            row,
            values=["Both", "Bridge", "Modbus"],
            variable=self._gripper_mode_var,
            width=110,
        )
        self._gripper_mode.pack(side="left", padx=(0, 12))

        self._gripper_val_lbl = ctk.CTkLabel(row, text="0.00", width=40, anchor="e")
        self._gripper_val_lbl.pack(side="right")

        self._gripper_slider = ctk.CTkSlider(
            row, from_=0.0, to=0.4,
            command=self._on_gripper_slider,
            state="disabled", width=200
        )
        self._gripper_slider.set(0.0)
        self._gripper_slider.pack(side="right", padx=(0, 8))

    def _on_gripper_slider(self, value: float):
        self._gripper_val_lbl.configure(text=f"{value:.2f}")
        self._schedule_gripper_write(value)

    def _set_gripper(self, value: float):
        self._gripper_slider.set(value)
        self._gripper_val_lbl.configure(text=f"{value:.2f}")
        self._schedule_gripper_write(value, delay_ms=0)

    def _schedule_gripper_write(self, value: float, delay_ms: int = 100):
        self._gripper_pending_value = value
        if self._gripper_write_after_id is not None:
            self.after_cancel(self._gripper_write_after_id)
        self._gripper_write_after_id = self.after(delay_ms, self._flush_gripper_write)

    def _flush_gripper_write(self):
        self._gripper_write_after_id = None
        threading.Thread(
            target=self._write_gripper_cmd,
            args=(self._gripper_pending_value,),
            daemon=True,
        ).start()

    def _write_gripper_cmd(self, value: float):
        mode = self._gripper_mode_var.get()
        if mode in ("Both", "Bridge"):
            try:
                with open(GRIPPER_CMD_PATH, "w") as f:
                    json.dump({"value": round(value, 4)}, f)
            except Exception as exc:
                self._log(f"Gripper write error: {exc}")
        if mode in ("Both", "Modbus"):
            self._write_gripper_modbus(value)

    def _write_gripper_modbus(self, value: float):
        if not is_port_open(MODBUS_PORT):
            self.after(0, lambda: self._gripper_raw_lbl.configure(text="Modbus raw: —"))
            return
        raw_value = max(0, min(65535, int(round(value * GRIPPER_MODBUS_SCALE))))
        try:
            write_modbus_register(MODBUS_GRIPPER_REGISTER, raw_value)
            self.after(0, lambda: self._gripper_raw_lbl.configure(text=f"Modbus raw: {raw_value}"))
        except Exception as exc:
            self._log(f"Gripper Modbus write error: {exc}")

    def _set_gripper_controls(self, enabled: bool):
        if self._gripper_controls_enabled == enabled:
            return
        self._gripper_controls_enabled = enabled
        state = "normal" if enabled else "disabled"
        self._gripper_slider.configure(state=state)
        self._gripper_open_btn.configure(state=state)
        self._gripper_close_btn.configure(state=state)
        self._gripper_mode.configure(state=state)

    def _update_gripper_status(self, bridge_running: bool, modbus_ok: bool):
        self._modbus_ok = modbus_ok
        self._set_gripper_controls(bridge_running or modbus_ok)
        status_key = (bridge_running, modbus_ok)
        if self._gripper_status_key == status_key:
            return
        self._gripper_status_key = status_key
        if bridge_running and modbus_ok:
            self._gripper_status_lbl.configure(
                text="● Ready: bridge + direct Modbus",
                text_color="#2ecc71",
            )
        elif bridge_running:
            self._gripper_status_lbl.configure(
                text="● Ready: Python bridge",
                text_color="#2ecc71",
            )
        elif modbus_ok:
            self._gripper_status_lbl.configure(
                text="● Ready: direct Modbus",
                text_color="#2ecc71",
            )
        else:
            self._gripper_status_lbl.configure(
                text="● Waiting for bridge or Modbus",
                text_color="gray",
            )
            self._gripper_raw_lbl.configure(text="Modbus raw: —")

    # ── Status polling ───────────────────────────────────────────────────────

    def _poll_status(self):
        threading.Thread(target=self._check_all_status, daemon=True).start()
        self.after(POLL_INTERVAL_MS, self._poll_status)

    def _check_all_status(self):
        docker_ok    = is_docker_running()
        ursim_ok     = is_port_open(30004)   # RTDE port — container running
        # If WE launched the container this session, wait for the "Simulator Is Ready"
        # banner in the log (port 29999 opens early as Dashboard Server, not web UI).
        # If the container was already running when the app started, trust it's ready.
        launched_by_us = self._ursim_start_time is not None or self._ursim_proc is not None
        polyscope_ok = self._simulator_ready or (ursim_ok and not launched_by_us)
        ptconnect_ok = is_port_open(8084)
        modbus_ok = is_port_open(MODBUS_PORT)
        self.after(0, self._apply_status, docker_ok, ursim_ok, polyscope_ok, ptconnect_ok, modbus_ok)

    def _apply_status(self, docker_ok, ursim_ok, polyscope_ok, ptconnect_ok, modbus_ok):
        self._docker_ok    = docker_ok
        self._ptconnect_ok = ptconnect_ok
        self._modbus_ok    = modbus_ok

        # stop the boot timer once the container's RTDE port is up
        if ursim_ok and not self._ursim_ok:
            self._ursim_start_time = None
        self._ursim_ok = ursim_ok

        self._set_status(self._docker_row,    docker_ok,    "Running", "Not running")
        self._set_status(self._ursim_row,     ursim_ok,     "Running", "Stopped")
        self._set_status(self._ptconnect_row, ptconnect_ok, "Running", "Not running")

        # Docker — disable Launch while already running
        self._docker_row["btn"].configure(
            state="disabled" if docker_ok else "normal"
        )

        # URSim — disable Launch while running or launching; enable only when
        # Docker is ready and the container is not yet up
        ursim_launching = self._ursim_start_time is not None
        if not ursim_launching:
            can_launch_ursim = docker_ok and not ursim_ok
            self._ursim_row["btn"].configure(
                state="normal" if can_launch_ursim else "disabled"
            )

        # URSim Stop button — enable whenever container is up, regardless of
        # whether we launched it this session
        if self._ursim_row["stop_btn"] is not None:
            self._ursim_row["stop_btn"].configure(
                state="normal" if ursim_ok else "disabled"
            )

        # ProtoTwin Connect — disable Launch while already running
        self._ptconnect_row["btn"].configure(
            state="disabled" if ptconnect_ok else "normal"
        )

        # PolyScope X Open button unlocks when port 29999 responds
        self._polyscope_row["btn"].configure(state="normal" if polyscope_ok else "disabled")
        self._update_polyscope_label(polyscope_ok)
        self._update_start_btn()
        bridge_running = self._bridge_proc is not None and self._bridge_proc.poll() is None
        self._update_gripper_status(bridge_running, modbus_ok)

    def _update_polyscope_label(self, polyscope_ok: bool):
        if polyscope_ok:
            self._polyscope_status_lbl.configure(text="● Ready", text_color="#2ecc71")
        elif self._ursim_ok:
            self._polyscope_status_lbl.configure(text="● Starting…", text_color="#f39c12")
        else:
            self._polyscope_status_lbl.configure(text="", text_color="gray")

    def _set_status(self, row: dict, ok: bool, ok_text: str, fail_text: str):
        row["status"].configure(
            text=f"● {ok_text}" if ok else f"● {fail_text}",
            text_color="#2ecc71" if ok else "#e74c3c"
        )

    def _update_start_btn(self):
        bridge_stopped = self._bridge_proc is None or self._bridge_proc.poll() is not None
        can_start = bridge_stopped and self._model_ready_var.get() and self._ptconnect_ok
        self._start_btn.configure(state="normal" if can_start else "disabled")

    # ── Service launchers ────────────────────────────────────────────────────

    def _launch_docker(self):
        exe = find_exe(DOCKER_EXE_PATHS)
        if exe:
            subprocess.Popen([exe])
            self._log("Launching Docker Desktop…")
        else:
            self._log("ERROR: Docker Desktop not found. Is it installed?")
            self._log("       Expected path: C:\\Program Files\\Docker\\Docker\\Docker Desktop.exe")
            self._log(f"       Install: {DOCKER_INSTALL_URL}")

    def _start_ursim(self):
        if self._ursim_proc and self._ursim_proc.poll() is None:
            self._log("URSim container is already running.")
            return
        self._log("Starting URSim container…")
        self._log(f"  > {URSIM_DOCKER_CMD}")
        self._ursim_proc = subprocess.Popen(
            URSIM_DOCKER_CMD,
            shell=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        self._ursim_start_time = time.monotonic()
        self._simulator_ready = False
        self._ursim_row["btn"].configure(state="disabled")
        self._ursim_row["stop_btn"].configure(state="normal")
        self._tick_ursim_timer()
        threading.Thread(
            target=self._stream_proc,
            args=(self._ursim_proc, "[URSim]"),
            daemon=True
        ).start()

    def _stop_ursim(self):
        self._log("Stopping URSim container…")
        # Stop the container by its image name — docker stop finds it automatically
        threading.Thread(target=self._do_stop_ursim, daemon=True).start()

    def _do_stop_ursim(self):
        # Find the container ID by image name and stop it
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter",
             "ancestor=universalrobots/ursim_polyscopex:latest"],
            capture_output=True, text=True
        )
        container_id = result.stdout.strip()
        if container_id:
            subprocess.run(["docker", "stop", container_id], capture_output=True)
            self._log("URSim container stopped.")
        # Also terminate the subprocess if still running
        if self._ursim_proc and self._ursim_proc.poll() is None:
            self._ursim_proc.terminate()
        self._ursim_proc = None
        self._ursim_start_time = None
        self._simulator_ready = False
        self.after(0, self._on_ursim_stopped)

    def _on_ursim_stopped(self):
        self._ursim_row["btn"].configure(state="normal")
        self._ursim_row["stop_btn"].configure(state="disabled")
        self._polyscope_row["btn"].configure(state="disabled")

    def _tick_ursim_timer(self):
        if self._ursim_ok or self._ursim_start_time is None:
            return
        elapsed = int(time.monotonic() - self._ursim_start_time)
        m, s = divmod(elapsed, 60)
        self._ursim_row["status"].configure(
            text=f"● Starting… {m}:{s:02d}",
            text_color="#f39c12"
        )
        self.after(1000, self._tick_ursim_timer)

    def _launch_ptconnect(self):
        # Try direct exe paths first
        exe = find_exe(PROTOTWIN_CONNECT_EXE_PATHS)
        if exe:
            subprocess.Popen([exe])
            self._log("Launching ProtoTwin Connect…")
            return

        # Fall back to launching the Start Menu shortcut (.lnk)
        if PROTOTWIN_STARTMENU.exists():
            lnk_files = list(PROTOTWIN_STARTMENU.glob("*.lnk"))
            if lnk_files:
                import os
                os.startfile(str(lnk_files[0]))
                self._log("Launching ProtoTwin Connect via Start Menu shortcut…")
                return

        self._log("ERROR: ProtoTwin Connect not found.")
        self._log(f"       Checked: {PROTOTWIN_STARTMENU}")
        self._log("       Update PROTOTWIN_CONNECT_EXE_PATHS in app.py with the correct path.")
        self._log(f"       Install/sign in: {PROTOTWIN_CONNECT_INSTALL_URL}")

    # ── Bridge ───────────────────────────────────────────────────────────────

    def _start_bridge(self):
        self._log("─" * 50)
        self._log("Starting bridge…")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--bridge"]
        else:
            cmd = [sys.executable, "-u", str(BRIDGE_SCRIPT)]
        if self._home_var.get():
            cmd.append("--home")
            self._log("  Home robot on start: ON (needs Remote Control mode)")
        creationflags = subprocess.CREATE_NO_WINDOW if getattr(sys, "frozen", False) else 0
        self._bridge_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        self._bridge_status_lbl.configure(text="● Running", text_color="#2ecc71")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        self._set_gripper_controls(True)
        threading.Thread(
            target=self._stream_proc,
            args=(self._bridge_proc, ""),
            daemon=True
        ).start()

    def _stop_bridge(self):
        if self._bridge_proc and self._bridge_proc.poll() is None:
            self._bridge_proc.terminate()
            self._log("Bridge stopped.")
        self._bridge_proc = None
        self._bridge_status_lbl.configure(text="● Stopped", text_color="#e74c3c")
        self._stop_btn.configure(state="disabled")
        self._update_gripper_status(False, self._modbus_ok)
        for var in self._angle_strvars:
            var.set("—")
        self._update_start_btn()

    # ANSI escape codes (color, cursor, erase sequences)
    _ANSI_ESC = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\[[0-9;]*m')

    # Inner docker-compose container log lines look like:
    #   "service-name  | actual log message"
    # (service name, two or more spaces, pipe character)
    _URSIM_INNER = re.compile(r'^\S[\w-]*\s{2,}\|')

    def _stream_proc(self, proc: subprocess.Popen, prefix: str):
        last_line = ""
        for raw in iter(proc.stdout.readline, b''):
            line = raw.decode('utf-8', errors='replace').rstrip()
            if not line:
                continue
            if prefix:  # URSim container output — apply cleanup
                line = self._ANSI_ESC.sub('', line).strip()
                if not line:
                    continue
                # Drop inner container logs (service-name  | message)
                if self._URSIM_INNER.search(line):
                    continue
                # Suppress consecutive duplicate lines (repeated "Waiting for…")
                if line == last_line:
                    continue
                last_line = line
                # "Simulator Is Ready" banner starts and ends with ***
                if line.startswith('***'):
                    self._simulator_ready = True
            self._log_queue.put(f"{prefix} {line}".strip() if prefix else line)
            self._parse_angles(line)
        # process ended — update bridge status if it was the bridge
        if proc is self._bridge_proc:
            self.after(0, self._on_bridge_ended)

    def _on_bridge_ended(self):
        self._bridge_status_lbl.configure(text="● Stopped", text_color="#e74c3c")
        self._stop_btn.configure(state="disabled")
        self._update_gripper_status(False, self._modbus_ok)
        for var in self._angle_strvars:
            var.set("—")
        self._bridge_proc = None
        self._update_start_btn()

    def _parse_angles(self, line: str):
        m = re.search(
            r'base=([+-]?\d+\.?\d*)°.*shoulder=([+-]?\d+\.?\d*)°.*'
            r'elbow=([+-]?\d+\.?\d*)°.*wrist1=([+-]?\d+\.?\d*)°.*'
            r'wrist2=([+-]?\d+\.?\d*)°.*wrist3=([+-]?\d+\.?\d*)°',
            line
        )
        if m:
            joints = ["base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"]
            self.after(0, self._update_angles, joints, m.groups())

    def _update_angles(self, joints, values):
        joint_order = ["base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"]
        for name, val in zip(joints, values):
            text = f"{float(val):.1f}°"
            idx = joint_order.index(name)
            self._angle_strvars[idx].set(text)

    # ── Log ──────────────────────────────────────────────────────────────────

    def _drain_log(self):
        try:
            while True:
                self._append_log(self._log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(100, self._drain_log)

    def _log(self, msg: str):
        self._log_queue.put(msg)

    def _append_log(self, msg: str):
        self._log_box.configure(state="normal")
        self._log_box.insert("end", msg + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    # ── Window close ─────────────────────────────────────────────────────────

    def _on_close(self):
        if self._bridge_proc and self._bridge_proc.poll() is None:
            self._bridge_proc.terminate()
        threading.Thread(target=self._shutdown_and_destroy, daemon=True).start()

    def _shutdown_and_destroy(self):
        result = subprocess.run(
            ["docker", "ps", "-q", "--filter",
             "ancestor=universalrobots/ursim_polyscopex:latest"],
            capture_output=True, text=True
        )
        container_id = result.stdout.strip()
        if container_id:
            subprocess.run(["docker", "stop", container_id], capture_output=True)
        if self._ursim_proc and self._ursim_proc.poll() is None:
            self._ursim_proc.terminate()
        self.after(0, self.destroy)

    # ── First run ─────────────────────────────────────────────────────────────

    def _check_first_run(self):
        missing = check_dependencies()
        if missing:
            self._log(f"Missing packages: {', '.join(missing)}")
            self._log("Installing… (this may take a moment)")
            threading.Thread(
                target=self._install_deps, args=(missing,), daemon=True
            ).start()
        else:
            self._log("All dependencies OK.")
            self._log("Ready — launch services then start the bridge.")


    def _install_deps(self, packages: list[str]):
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install"] + packages,
            capture_output=True, text=True
        )
        if result.returncode == 0:
            self._log("Dependencies installed. You may need to restart app.py.")
        else:
            self._log("Dependency install failed:")
            for line in result.stderr.splitlines():
                self._log(f"  {line}")


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--bridge" in sys.argv:
        import bridge

        asyncio.run(bridge.main())
    else:
        app = App()
        app.mainloop()
