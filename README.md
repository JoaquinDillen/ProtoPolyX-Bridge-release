# URSim → ProtoTwin Bridge

Streams live joint positions from a UR robot running in **URSim (PolyScope X)**
to a **UR10 digital twin in ProtoTwin**, so programs written in PolyScope animate
the 3D model in real time.

```
URSim (Docker)  →  RTDE port 30004  →  bridge.py  →  ProtoTwin Connect  →  3D robot
```

## Quick Start — GUI (recommended)

Install the GUI dependency, then launch the control panel:

```bash
pip install customtkinter
python app.py
```

The app guides you through each step: starting Docker, URSim, ProtoTwin Connect,
opening the browser tabs, and starting the bridge — all from one window.

## Quick Start — Command line

---

## Requirements

- Windows 11
- Python 3.9+
- Docker Desktop with the URSim image
- [ProtoTwin Connect](https://prototwin.com) desktop app (logged in)
- A ProtoTwin model containing a UR10 robot with joint input signals configured

---

## 1. Install Dependencies

```bash
pip install ur-rtde prototwin
```

> **Note:** `ur-rtde` is the pip package name; the import inside Python is
> `rtde_receive`. If the install fails on Windows, upgrade pip first:
> `python -m pip install --upgrade pip`

---

## 2. Start URSim in Docker

```bash
docker run --rm -it \
  -p 30001:30001 \
  -p 30002:30002 \
  -p 30003:30003 \
  -p 30004:30004 \
  -p 29999:29999 \
  universalrobots/ursim_polyscopex:latest
```

Wait until the PolyScope X web interface loads (usually `http://localhost:29999`).
The RTDE interface on port **30004** is active as soon as the controller boots.

---

## 3. Configure Robot Joint Signals in ProtoTwin

This is the only manual setup step. The bridge writes to ProtoTwin signals by
**integer address**. You need to look these up in your model.

### How to find the signal addresses

1. Open your model at [play.prototwin.com](https://play.prototwin.com)
2. Click each joint component of the UR10 arm in the scene
3. Open **Properties → Signals** in the panel on the right
4. Find the **input** signal for joint position (typically named something like
   `Joint Position` or `q`) and note its **address** integer
5. Open `bridge.py` and update `JOINT_SIGNAL_ADDRESSES` near the top:

```python
JOINT_SIGNAL_ADDRESSES = [
    12,   # base     (J1)  ← replace with your real addresses
    13,   # shoulder (J2)
    14,   # elbow    (J3)
    15,   # wrist1   (J4)
    16,   # wrist2   (J5)
    17,   # wrist3   (J6)
]
```

### Radians vs degrees

RTDE delivers angles in **radians**. The bridge converts them to **degrees**
before writing to ProtoTwin (`CONVERT_TO_DEGREES = True`).

If your ProtoTwin joint signals expect radians instead, set this flag to `False`
at the top of `bridge.py`.

---

## 4. Start ProtoTwin Connect

Launch the **ProtoTwin Connect** desktop application and make sure you are signed in.
It runs a local gRPC server that the Python client (`prototwin.start()`) connects to.
The bridge will not start until this app is running.

---

## 5. Run the Bridge

```bash
python bridge.py
```

### Expected startup output

```
============================================================
  URSim → ProtoTwin Bridge
  Streaming UR10 joint angles via RTDE → ProtoTwin
============================================================

[Config] WARNING: JOINT_SIGNAL_ADDRESSES are still set to placeholder …
         (this warning disappears once you set real addresses)

[RTDE] Connecting to 127.0.0.1:30004 …
[RTDE] Connected.

[ProtoTwin] Connecting to ProtoTwin Connect …
[ProtoTwin] Connected.

[Bridge] Streaming at 50 Hz — press Ctrl+C to stop.

[Bridge] base=0.0°, shoulder=-90.0°, elbow=90.0°, wrist1=-90.0°, wrist2=0.0°, wrist3=0.0°
[Bridge] base=0.0°, shoulder=-90.0°, elbow=90.0°, wrist1=-90.0°, wrist2=0.0°, wrist3=0.0°
…
```

Now **play a program in PolyScope X** — the UR10 in your ProtoTwin scene should
move in sync with the simulator.

Press **Ctrl+C** to stop. The RTDE connection is closed cleanly on exit.

---

## Behaviour Reference

| Situation | What the bridge does |
|---|---|
| Normal operation | Forwards joint angles to ProtoTwin at ~50 Hz |
| URSim not yet running | Retries RTDE connection every 3 s |
| ProtoTwin Connect not running | Retries ProtoTwin connection every 3 s |
| Either side disconnects mid-run | Reconnects both ends automatically |
| Ctrl+C | Graceful shutdown; RTDE socket closed |

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'rtde_receive'`**  
→ Run `pip install ur-rtde` (the pip name and the import name differ)

**`[RTDE] Connection failed: …` and keeps retrying**  
→ Check the Docker container is running: `docker ps`  
→ Confirm port 30004 is forwarded: `docker run … -p 30004:30004 …`

**`[ProtoTwin] Connection failed`**  
→ Open ProtoTwin Connect, sign in, then retry

**Robot in ProtoTwin doesn't move (but bridge is running)**  
→ The signal addresses in `JOINT_SIGNAL_ADDRESSES` are wrong  
→ Re-check the addresses in your ProtoTwin model (step 3 above)  
→ Check that `CONVERT_TO_DEGREES` matches what the ProtoTwin signals expect

**`TypeError: object is not awaitable` on `client.set()`**  
→ Your version of the prototwin package exposes `set()` as a coroutine  
→ In `bridge.py`, change `client.set(address, value)` to `await client.set(address, value)`

---

## Files

| File | Purpose |
|---|---|
| `bridge.py` | The bridge script |
| `README.md` | This file |
