"""
bridge.py — URSim -> ProtoTwin Joint Angle Bridge

Reads joint positions from a UR robot running in URSim (PolyScope X) via the
RTDE interface, then forwards them to a UR10 digital twin in ProtoTwin so the
3D model mirrors the simulator in real time.

Architecture:
    URSim (Docker)
      └─ RTDE port 30004
           └─ bridge.py
                └─ ProtoTwin Connect (local desktop app)
                     └─ 3D robot in ProtoTwin browser tab

Usage:
    python bridge.py

Press Ctrl+C to stop cleanly.
"""

import asyncio
import json
import math
import sys
import time
from pathlib import Path

import rtde_receive          # pip install ur-rtde
import rtde_control          # included in the ur-rtde package
import prototwin             # pip install prototwin  (ProtoTwin Connect must be running)


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION — edit via the app's "Joint Signal Addresses" section,
# or directly in bridge_config.json next to this file.
# ─────────────────────────────────────────────────────────────────────────────

URSIM_HOST    = "127.0.0.1"  # URSim IP; 127.0.0.1 when the container is on this machine
LOOP_HZ       = 50           # target read/write rate (Hz)
RETRY_DELAY_S = 3.0          # seconds to wait between reconnection attempts

APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent

_DEFAULT_CONFIG = {
    "joint_signal_addresses": [18, 39, 11, 32, 46, 25],
    "joint_directions": [-1, 1, -1, 1, -1, 1],
    "right_finger_address": 60,
    "left_finger_address": 53,
}

def _load_config() -> dict:
    cfg = APP_DIR / "bridge_config.json"
    try:
        with open(cfg) as f:
            return json.load(f)
    except Exception:
        try:
            with open(cfg, "w") as f:
                json.dump(_DEFAULT_CONFIG, f, indent=2)
        except Exception:
            pass
        return dict(_DEFAULT_CONFIG)

_cfg = _load_config()

# Motor TARGET POSITION signal addresses (one per joint).
JOINT_SIGNAL_ADDRESSES  = _cfg.get("joint_signal_addresses", _DEFAULT_CONFIG["joint_signal_addresses"])
RIGHT_FINGER_ADDRESS    = _cfg.get("right_finger_address", 60)
LEFT_FINGER_ADDRESS     = _cfg.get("left_finger_address", 53)

# Motor TARGET VELOCITY signal addresses — target + 1 in ProtoTwin's Motor I/O layout.
JOINT_VELOCITY_ADDRESSES = [addr + 1 for addr in JOINT_SIGNAL_ADDRESSES]

# Motor CURRENT POSITION signal addresses — target + 3 in ProtoTwin's Motor I/O layout.
JOINT_CURRENT_ADDRESSES = [addr + 3 for addr in JOINT_SIGNAL_ADDRESSES]

# Motor STATE signal addresses — target - 1 in ProtoTwin's Motor I/O layout.
JOINT_STATE_ADDRESSES   = [addr - 1 for addr in JOINT_SIGNAL_ADDRESSES]

# Finger velocity and state addresses derived from finger target position addresses.
RIGHT_FINGER_VELOCITY   = RIGHT_FINGER_ADDRESS + 1
LEFT_FINGER_VELOCITY    = LEFT_FINGER_ADDRESS  + 1
RIGHT_FINGER_STATE      = RIGHT_FINGER_ADDRESS - 1
LEFT_FINGER_STATE       = LEFT_FINGER_ADDRESS  - 1

# Per-joint direction multiplier: +1 = same as URSim, -1 = inverted.
# Flip any joint whose ProtoTwin axis rotates the wrong way.
JOINT_DIRECTIONS = _cfg.get("joint_directions", _DEFAULT_CONFIG["joint_directions"])

GRIPPER_CMD_PATH = APP_DIR / "gripper_cmd.json"

def _read_gripper_cmd() -> float | None:
    try:
        with open(GRIPPER_CMD_PATH) as f:
            return float(json.load(f).get("value", 0.0))
    except Exception:
        try:
            with open(GRIPPER_CMD_PATH, "w") as f:
                json.dump({"value": 0.0}, f)
        except Exception:
            pass
        return None

# Human-readable joint names used in status output
JOINT_NAMES = ["base", "shoulder", "elbow", "wrist1", "wrist2", "wrist3"]

# ProtoTwin's Target Position signal uses radians, matching RTDE's native unit.
# Sending degrees caused a 57× position error (value × 180/π).
CONVERT_TO_DEGREES = False

# Minimum change (in radians) required before sending a new value to ProtoTwin.
DEADBAND = math.radians(0.1)  # 0.1° expressed in radians

# Speed written to ProtoTwin's Target Velocity signal.
# IMPORTANT: this signal uses rad/s, not deg/s. Sending degrees/s causes a 57×
# speed multiplier (180/π) and the motor runs away past every target.
# math.pi rad/s = 180°/s — above UR10 max (120°/s) with only 1.6° stopping
# distance at Decel=9999 deg/s².
FOLLOW_SPEED = math.pi  # rad/s  ≈ 180 °/s


# Speed and acceleration used when homing the robot (rad/s and rad/s²)
HOME_SPEED = 0.5
HOME_ACCEL = 0.5


# ─────────────────────────────────────────────────────────────────────────────
# RTDE CONNECTION  (synchronous — ur-rtde is not async)
# ─────────────────────────────────────────────────────────────────────────────

def connect_rtde() -> rtde_receive.RTDEReceiveInterface:
    """
    Open an RTDE receive connection to URSim.
    Blocks and retries until the connection succeeds or the user presses Ctrl+C.
    """
    while True:
        try:
            print(f"[RTDE] Connecting to {URSIM_HOST}:30004 …")
            rtde_r = rtde_receive.RTDEReceiveInterface(URSIM_HOST, LOOP_HZ)
            if not rtde_r.isConnected():
                raise ConnectionError("isConnected() returned False after init")
            print("[RTDE] Connected.\n")
            return rtde_r
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[RTDE] Connection failed: {exc}")
            print(f"[RTDE] Retrying in {RETRY_DELAY_S:.0f} s …\n")
            time.sleep(RETRY_DELAY_S)


# ─────────────────────────────────────────────────────────────────────────────
# HOMING  — move URSim to all-zeros before calibration
# ─────────────────────────────────────────────────────────────────────────────

def home_robot() -> None:
    """
    Move the URSim robot to [0, 0, 0, 0, 0, 0] degrees using RTDEControlInterface.
    Blocks until the motion completes. This ensures URSim and ProtoTwin
    (whose model zero is also all-zeros) are aligned before calibration runs.
    """
    print("[RTDE] Homing robot to all-zeros …")
    rtde_c = rtde_control.RTDEControlInterface(URSIM_HOST)
    # moveJ takes joint angles in radians — all zeros is a valid UR pose
    rtde_c.moveJ([0, 0, 0, 0, 0, 0], HOME_SPEED, HOME_ACCEL)
    rtde_c.disconnect()
    print("[RTDE] Robot at home position.\n")


# ─────────────────────────────────────────────────────────────────────────────
# PROTOTWIN CONNECTION  (async — prototwin.attach() is a coroutine)
# ─────────────────────────────────────────────────────────────────────────────

async def connect_prototwin():
    """
    Open a connection to the locally running ProtoTwin Connect desktop app.
    Retries until successful or the user presses Ctrl+C.
    """
    while True:
        try:
            print("[ProtoTwin] Connecting to ProtoTwin Connect …")
            client = await prototwin.attach()
            if client is None:
                raise ConnectionError("attach() returned None — is ProtoTwin Connect running?")
            print("[ProtoTwin] Connected.\n")
            return client
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[ProtoTwin] Connection failed: {exc}")
            print(f"[ProtoTwin] Is ProtoTwin Connect running? Retrying in {RETRY_DELAY_S:.0f} s …\n")
            await asyncio.sleep(RETRY_DELAY_S)


# ─────────────────────────────────────────────────────────────────────────────
# AUTO-CALIBRATION
# ─────────────────────────────────────────────────────────────────────────────

async def calibrate(rtde_r: rtde_receive.RTDEReceiveInterface, client) -> list[float]:
    """
    Compute per-joint zero offsets so the ProtoTwin model tracks URSim correctly
    regardless of where each model's 'zero' angle is defined.

    Method:
        offset[i] = prototwin_current[i] - ursim_current[i]

    At runtime:
        prototwin_target[i] = ursim_angle[i] + offset[i]

    This means: 'wherever the robot is right now in both systems is the
    agreed-upon reference point — move together from here.'

    The robot should be stationary in both URSim and ProtoTwin when this runs.
    """
    print("[Calibration] Enabling motors …")
    for state_addr in JOINT_STATE_ADDRESSES:
        client.set(state_addr, 1)
    client.set(RIGHT_FINGER_STATE, 1)
    client.set(LEFT_FINGER_STATE,  1)
    await client.sync()
    print("[Calibration] Motors enabled.")

    print("[Calibration] Reading current positions …")

    # Fetch the latest signal values from ProtoTwin into the local buffer
    await client.sync()

    actual_q = rtde_r.getActualQ()
    offsets = []

    for i, (cur_addr, angle_rad) in enumerate(
        zip(JOINT_CURRENT_ADDRESSES, actual_q)
    ):
        ursim_rad     = angle_rad * JOINT_DIRECTIONS[i]          # radians — sent to ProtoTwin
        prototwin_rad = client.get(cur_addr)                      # radians — read from ProtoTwin
        offset        = prototwin_rad - ursim_rad                 # radians
        offsets.append(offset)
        print(
            f"  {JOINT_NAMES[i]:10s}  URSim={math.degrees(ursim_rad):8.2f}°  "
            f"ProtoTwin={math.degrees(prototwin_rad):8.2f}°  offset={math.degrees(offset):+.2f}°"
        )

    print("[Calibration] Done.\n")
    return offsets


# ─────────────────────────────────────────────────────────────────────────────
# BRIDGE LOOP
# ─────────────────────────────────────────────────────────────────────────────

async def run_bridge(
    rtde_r: rtde_receive.RTDEReceiveInterface,
    client,
    offsets: list[float],
) -> None:
    """
    Core loop: read actual_q from RTDE, apply calibration offsets, write to ProtoTwin.

    Returns when either end reports an error (the caller will reconnect).
    Raises KeyboardInterrupt when the user presses Ctrl+C.
    """
    interval_s   = 1.0 / LOOP_HZ
    iteration    = 0
    last_values  = [None] * 6
    last_gripper: float | None = None

    print(f"[Bridge] Streaming at {LOOP_HZ} Hz — press Ctrl+C to stop.\n")

    while True:
        tick_start = time.monotonic()

        # ── Step 1: read joint angles from URSim ────────────────────────────
        try:
            actual_q = rtde_r.getActualQ()
        except Exception as exc:
            print(f"\n[RTDE] Read error: {exc}")
            return

        # ── Step 2: write calibrated position + follow speed to ProtoTwin ───
        try:
            changed = False
            for i, (address, vel_address, angle_rad) in enumerate(
                zip(JOINT_SIGNAL_ADDRESSES, JOINT_VELOCITY_ADDRESSES, actual_q)
            ):
                ursim_rad = angle_rad * JOINT_DIRECTIONS[i]
                # Add the per-joint offset so ProtoTwin's zero aligns with URSim's
                value = ursim_rad + offsets[i]

                if last_values[i] is None or abs(value - last_values[i]) > DEADBAND:
                    client.set(address, value)
                    client.set(vel_address, FOLLOW_SPEED)
                    last_values[i] = value
                    changed = True

            # ── Step 2b: gripper ──────────────────────────────────────────────
            gripper_val = _read_gripper_cmd()
            if gripper_val is not None and gripper_val != last_gripper:
                client.set(RIGHT_FINGER_ADDRESS,    gripper_val)
                client.set(RIGHT_FINGER_VELOCITY,   FOLLOW_SPEED)
                client.set(LEFT_FINGER_ADDRESS,     gripper_val)
                client.set(LEFT_FINGER_VELOCITY,    FOLLOW_SPEED)
                last_gripper = gripper_val
                changed = True

            if changed:
                await client.sync()
            elif iteration % (LOOP_HZ * 2) == 0:
                # Keep-alive: re-write the last known positions so the WebSocket
                # carries real data every 2 s. A sync() with no prior set() is a
                # no-op at the protocol level and does not prevent timeout.
                for ka_addr, ka_vel, ka_val in zip(
                    JOINT_SIGNAL_ADDRESSES, JOINT_VELOCITY_ADDRESSES, last_values
                ):
                    if ka_val is not None:
                        client.set(ka_addr, ka_val)
                        client.set(ka_vel, FOLLOW_SPEED)
                if last_gripper is not None:
                    client.set(RIGHT_FINGER_ADDRESS,  last_gripper)
                    client.set(RIGHT_FINGER_VELOCITY, FOLLOW_SPEED)
                    client.set(LEFT_FINGER_ADDRESS,   last_gripper)
                    client.set(LEFT_FINGER_VELOCITY,  FOLLOW_SPEED)
                await client.sync()

        except Exception as exc:
            print(f"\n[ProtoTwin] Write error: {exc}")
            return

        # ── Step 3: print a status line every 2 seconds ──────────────────────
        iteration += 1
        if iteration % (LOOP_HZ * 2) == 0:
            parts = [
                f"{n}={math.degrees(a):.1f}°"
                for n, a in zip(JOINT_NAMES, actual_q)
            ]
            print(f"[Bridge] {', '.join(parts)}")

        # ── Step 4: sleep for the rest of the interval ───────────────────────
        elapsed   = time.monotonic() - tick_start
        remaining = interval_s - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — connect, calibrate, run, reconnect on error
# ─────────────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("=" * 60)
    print("  URSim -> ProtoTwin Bridge")
    print("  Streaming UR10 joint angles via RTDE -> ProtoTwin")
    print("=" * 60 + "\n")

    rtde_r = connect_rtde()

    if "--home" in sys.argv:
        try:
            home_robot()
        except Exception as exc:
            print(f"[RTDE] Homing failed: {exc}")
            print("[RTDE] Tip: homing requires PolyScope X to be in Remote Control mode.")
            print("[RTDE] Continuing without homing — calibration will use current positions.\n")

    client = await connect_prototwin()

    # Calibrate once — both robots are now at the same known pose
    offsets = await calibrate(rtde_r, client)

    try:
        while True:
            await run_bridge(rtde_r, client, offsets)

            print("[Bridge] Connection lost — reconnecting …\n")

            try:
                rtde_r.disconnect()
            except Exception:
                pass

            rtde_r = connect_rtde()
            client = await connect_prototwin()

            # Keep the original offsets — ProtoTwin resets its motor state on
            # reconnect and returns a bogus default, so recalibrating here
            # produces large wrong offsets. The initial calibration is still valid.
            print("[Bridge] Reconnected — resuming with existing calibration offsets.\n")

    except KeyboardInterrupt:
        print("\n[Bridge] Stopped by user.")

    finally:
        try:
            rtde_r.disconnect()
            print("[RTDE] Disconnected cleanly.")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
