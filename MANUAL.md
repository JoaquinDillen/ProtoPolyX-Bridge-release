# URSim → ProtoTwin Bridge — Manual

This manual explains the full system end to end: what each piece does, how they
connect, how to set everything up from scratch, and how to diagnose problems when
something does not work.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Concepts and Terminology](#2-concepts-and-terminology)
3. [Prerequisites](#3-prerequisites)
4. [Installation](#4-installation)
5. [Setting Up URSim](#5-setting-up-ursim)
6. [Setting Up ProtoTwin](#6-setting-up-prototwin)
7. [Configuring the Bridge](#7-configuring-the-bridge)
8. [Running the Bridge](#8-running-the-bridge)
9. [How the Code Works](#9-how-the-code-works)
10. [Configuration Reference](#10-configuration-reference)
11. [Troubleshooting](#11-troubleshooting)
12. [Glossary](#12-glossary)

---

## 1. System Overview

The bridge connects two otherwise separate systems:

```
┌──────────────────────────────────────────────────────────────────────┐
│  Your Windows 11 machine                                             │
│                                                                      │
│  ┌─────────────────┐   RTDE    ┌─────────────┐   gRPC   ┌─────────┐  │
│  │  URSim (Docker) │ ───────── │  bridge.py  │ ──────── │ProtoTwin│  │
│  │  PolyScope X    │  port     │  (Python)   │  local   │Connect  │  │
│  │  UR10 robot sim │  30004    │             │  server  │  app    │  │
│  └─────────────────┘           └─────────────┘          └─────────┘  │
│                                                              │       │
│                                                         WebSocket    │
│                                                              │       │
│                                                    ┌─────────────┐   │
│                                                    │  Browser    │   │
│                                                    │  ProtoTwin  │   │
│                                                    │  3D model   │   │
│                                                    └─────────────┘   │
└──────────────────────────────────────────────────────────────────────┘
```

**What happens at runtime:**

1. You write and run a robot program in the PolyScope X interface
2. URSim executes the program and moves the simulated robot joints
3. Every 20 ms (50 Hz), the bridge reads the current joint angles over RTDE
4. The bridge converts each angle from radians to degrees and writes it to the
   corresponding signal in ProtoTwin Connect
5. ProtoTwin forwards the new values to the browser tab, where the 3D robot
   updates its pose

The result is that the robot in ProtoTwin mirrors the URSim robot in real time.

---

## 2. Concepts and Terminology

### URSim

**Universal Robots Simulator** — an official software replica of a real UR robot
controller. It runs the same PolyScope X firmware as a physical robot, meaning
programs you develop here run without changes on real hardware.

It is distributed as a Docker image so it requires no installation of its own
beyond Docker Desktop.

### PolyScope X

The web-based teach pendant (user interface) that runs inside URSim. You use it
to write robot programs, jog joints manually, and start/stop programs. It is
accessed through a browser pointed at the URSim container's web port.

### RTDE

**Real-Time Data Exchange** — a high-frequency binary protocol built into every
UR controller. It runs on TCP port **30004** and streams robot state data
(joint positions, velocities, forces, I/O, etc.) to any client that subscribes.

The `ur-rtde` Python library wraps this protocol. The specific value the bridge
reads is `actual_q`: the actual (encoder-measured) joint positions as a list of
six floating-point numbers in radians.

### ProtoTwin

A browser-based 3D simulation platform for industrial robots and machinery
(played at `play.prototwin.com`). You build or import robot models there and
connect external data sources to animate them.

### ProtoTwin Connect

A desktop application that acts as a local relay between Python code and the
ProtoTwin browser session. It runs a gRPC server on localhost. The Python
`prototwin` package connects to this local server; ProtoTwin Connect then
forwards signal writes to the active browser tab over a WebSocket.

**ProtoTwin Connect must be running before you start the bridge.**

### Signals

In ProtoTwin, every controllable property of a component (a joint angle, a
conveyor speed, a cylinder position) is exposed as a **signal**. Each signal
has an integer **address** and a data type (Double, Float, Int, etc.).

The bridge writes to the six joint-position input signals of the UR10 model.
You must find these addresses in your specific ProtoTwin model and enter them
in `bridge.py`.

### RTDE `actual_q`

The six-element list that RTDE produces for joint positions. The order is always:

| Index | UR name | Joint |
|-------|---------|-------|
| 0 | q[0] | Base (J1) |
| 1 | q[1] | Shoulder (J2) |
| 2 | q[2] | Elbow (J3) |
| 3 | q[3] | Wrist 1 (J4) |
| 4 | q[4] | Wrist 2 (J5) |
| 5 | q[5] | Wrist 3 (J6) |

Values are in **radians**. The bridge converts them to degrees before writing to
ProtoTwin (unless you disable that conversion).

---

## 3. Prerequisites

### Software

| Requirement | Version | Notes |
|---|---|---|
| Windows 11 | any | x64 |
| Python | 3.9 or newer | `python --version` to check |
| Docker Desktop | latest | Must be running before starting URSim |
| ProtoTwin Connect | latest | Download from prototwin.com |
| Google Chrome / Edge / Firefox | latest | For PolyScope X and ProtoTwin |

### Network

All communication is local (127.0.0.1). No firewall rules are needed unless
Windows Defender Firewall blocks Docker's virtual network adapter — if so, allow
it when prompted during Docker installation.

### ProtoTwin account

You need a ProtoTwin account at [play.prototwin.com](https://play.prototwin.com)
to open models in the browser and to sign in to ProtoTwin Connect.

---

## 4. Installation

### 4.1 Install Docker Desktop

Download from [docker.com](https://www.docker.com/products/docker-desktop/) and
run the installer. After installation, start Docker Desktop and wait for the
whale icon in the system tray to stop animating (engine ready).

### 4.2 Pull the URSim image

```bash
docker pull universalrobots/ursim_polyscopex:latest
```

This downloads about 3 GB. You only need to do this once.

### 4.3 Install Python packages

```bash
pip install ur-rtde prototwin
```

Verify:

```bash
python -c "import rtde_receive; print('ur-rtde OK')"
python -c "import prototwin; print('prototwin OK')"
```

Both lines should print `OK`. If either fails, see [Troubleshooting](#11-troubleshooting).

### 4.4 Install ProtoTwin Connect

1. Go to [prototwin.com](https://prototwin.com) and download ProtoTwin Connect
   for Windows
2. Run the installer
3. Launch ProtoTwin Connect and sign in with your ProtoTwin account

---

## 5. Setting Up URSim

### 5.1 Start the container

Open a terminal (PowerShell or Command Prompt) and run:

```bash
docker run --rm -it \
  -p 30001:30001 \
  -p 30002:30002 \
  -p 30003:30003 \
  -p 30004:30004 \
  -p 29999:29999 \
  universalrobots/ursim_polyscopex:latest
```

`--rm` removes the container when it stops (your robot programs are not saved
between runs unless you add a volume mount — see section 5.4).

The terminal will print boot messages. Wait until you see lines indicating the
UR controller service has started.

### 5.2 Open PolyScope X

Open a browser and navigate to:

```
http://localhost:29999
```

The PolyScope X interface loads. The first time, it may ask you to accept a
license agreement or choose a robot model — select **UR10** if prompted.

### 5.3 Verify RTDE is active

RTDE is always running once the controller boots. You can verify it quickly:

```bash
python -c "
import rtde_receive
r = rtde_receive.RTDEReceiveInterface('127.0.0.1')
print('Connected:', r.isConnected())
print('Joints:', r.getActualQ())
r.disconnect()
"
```

Expected output:

```
Connected: True
Joints: [0.0, -1.5707963267948966, 0.0, -1.5707963267948966, 0.0, 0.0]
```

(Exact values depend on the robot's initial pose in the simulator.)

### 5.4 Persisting robot programs between runs (optional)

By default, any programs you create in PolyScope X are lost when the container
stops. To persist them, mount a local directory:

```bash
docker run --rm -it \
  -p 30001:30001 -p 30002:30002 -p 30003:30003 \
  -p 30004:30004 -p 29999:29999 \
  -v "%USERPROFILE%\ursim-programs:/ursim/programs" \
  universalrobots/ursim_polyscopex:latest
```

Programs saved in PolyScope X will be stored in `%USERPROFILE%\ursim-programs`
on your Windows machine.

---

## 6. Setting Up ProtoTwin

### 6.1 Open your UR10 model

1. Go to [play.prototwin.com](https://play.prototwin.com) and sign in
2. Open (or create) a scene that contains a UR10 robot model

If you do not have a UR10 model yet, look in the ProtoTwin asset library for a
pre-built Universal Robot component. Import it into a new scene.

### 6.2 Find the joint signal addresses

This is the most important configuration step for the bridge.

1. In the 3D scene, click the **base joint** of the UR10 arm
2. Open the **Properties** panel (usually on the right side)
3. Click the **Signals** tab
4. Look for an input signal labelled `Joint Position`, `q`, `angle`, or similar
5. Note the **address** — a small integer displayed next to the signal name
6. Repeat for all six joints: Base, Shoulder, Elbow, Wrist1, Wrist2, Wrist3

You should end up with six integers, for example:

| Joint | Address |
|-------|---------|
| Base (J1) | 12 |
| Shoulder (J2) | 13 |
| Elbow (J3) | 14 |
| Wrist 1 (J4) | 15 |
| Wrist 2 (J5) | 16 |
| Wrist 3 (J6) | 17 |

Your actual values will differ.

### 6.3 Check the signal unit

Look at each joint signal in the Properties panel and check whether it expects
**degrees** or **radians**. The bridge converts RTDE radians to degrees by
default (`CONVERT_TO_DEGREES = True`). If your model expects radians, you will
change that flag in `bridge.py` (see [Section 7](#7-configuring-the-bridge)).

### 6.4 Confirm ProtoTwin Connect is connected to the browser tab

In the ProtoTwin browser tab, there is usually a connection indicator or a
"Connected" status showing that ProtoTwin Connect is linked to the session.
The bridge's signal writes will have no effect until this link is active.

---

## 7. Configuring the Bridge

Open `bridge.py` in a text editor. All user-configurable values are near the top
of the file, between the two `───` separator comments.

### 7.1 Set the joint signal addresses

Replace the placeholder values in `JOINT_SIGNAL_ADDRESSES` with the addresses
you found in step 6.2:

```python
JOINT_SIGNAL_ADDRESSES = [
    12,   # base     (J1)
    13,   # shoulder (J2)
    14,   # elbow    (J3)
    15,   # wrist1   (J4)
    16,   # wrist2   (J5)
    17,   # wrist3   (J6)
]
```

The order is fixed by the UR joint convention. Do not reorder the list — instead
match each index to the correct joint's address.

### 7.2 Set the unit conversion

```python
CONVERT_TO_DEGREES = True   # change to False if ProtoTwin signals expect radians
```

### 7.3 Other settings (usually leave as-is)

```python
URSIM_HOST    = "127.0.0.1"  # change only if URSim runs on another machine
LOOP_HZ       = 50           # 50 Hz is the RTDE maximum; lower if needed
RETRY_DELAY_S = 3.0          # seconds between reconnect attempts
```

---

## 8. Running the Bridge

### 8.1 Start everything in the right order

The bridge can tolerate either end being unavailable at startup (it retries), but
the cleanest experience is:

1. Start Docker Desktop
2. Start URSim container (`docker run …`)
3. Open PolyScope X in the browser, confirm it loads
4. Open your ProtoTwin model in the browser
5. Launch ProtoTwin Connect desktop app and confirm it shows as connected
6. Run the bridge:

```bash
python bridge.py
```

### 8.2 Expected output

```
============================================================
  URSim → ProtoTwin Bridge
  Streaming UR10 joint angles via RTDE → ProtoTwin
============================================================

[RTDE] Connecting to 127.0.0.1:30004 …
[RTDE] Connected.

[ProtoTwin] Connecting to ProtoTwin Connect …
[ProtoTwin] Connected.

[Bridge] Streaming at 50 Hz — press Ctrl+C to stop.

[Bridge] base=0.0°, shoulder=-90.0°, elbow=90.0°, wrist1=-90.0°, wrist2=0.0°, wrist3=0.0°
```

The status line refreshes every 2 seconds.

### 8.3 Play a program in PolyScope X

With the bridge running, write a simple MoveJ or MoveL program in PolyScope X
and press Play. The joint angles in the status line should change, and the robot
in the ProtoTwin browser tab should move to match.

### 8.4 Stop the bridge

Press **Ctrl+C**. The bridge prints:

```
[Bridge] Stopped by user.
[RTDE] Disconnected cleanly.
```

---

## 9. How the Code Works

This section walks through `bridge.py` function by function.

### `connect_rtde()`

Creates an `RTDEReceiveInterface` object from the `ur-rtde` library. The second
argument (`LOOP_HZ`) tells the RTDE server to throttle its output to 50 Hz
rather than sending as fast as possible. The function blocks in a `while True`
loop, retrying every `RETRY_DELAY_S` seconds on failure. It re-raises
`KeyboardInterrupt` immediately so Ctrl+C is never swallowed.

### `connect_prototwin()`

An `async` function (note the `await`) because `prototwin.start()` opens a
network connection to the local ProtoTwin Connect gRPC server and returns a
client object. Same retry pattern as `connect_rtde()`.

### `run_bridge(rtde_r, client)`

The main loop, also `async`. Each iteration:

1. Calls `rtde_r.getActualQ()` — a synchronous read that returns immediately
   with the latest 6-element joint list from the RTDE buffer
2. Iterates over all six joints, optionally converts radians → degrees, and
   calls `client.set(address, value)` for each one
3. Every 100 iterations prints the current joint angles
4. Sleeps for the remainder of the 20 ms interval using `asyncio.sleep()` (not
   `time.sleep()`) so the event loop stays responsive

The function **returns** (rather than raising) when an error occurs. This lets
the caller reconnect and call it again, giving the bridge its auto-reconnect
behaviour.

### `main()`

Orchestrates the whole thing: connect both ends, call `run_bridge()`, reconnect
if it returns, repeat until Ctrl+C. The `finally` block ensures the RTDE socket
is always closed, even if an unexpected exception escapes.

### Why asyncio?

The `prototwin` package's connection API is async (`await prototwin.start()`).
Using `asyncio.run(main())` as the entry point means the bridge runs in an event
loop from the start, which lets `asyncio.sleep()` work correctly without
blocking the event loop during the idle portion of each 20 ms tick.

---

## 10. Configuration Reference

All configuration lives in the `CONFIGURATION` section of `bridge.py`.

| Variable | Type | Default | Description |
|---|---|---|---|
| `URSIM_HOST` | `str` | `"127.0.0.1"` | Hostname or IP of the URSim RTDE server |
| `LOOP_HZ` | `int` | `50` | Target loop frequency in Hz (max 500 for UR RTDE) |
| `RETRY_DELAY_S` | `float` | `3.0` | Seconds between reconnection attempts |
| `JOINT_SIGNAL_ADDRESSES` | `list[int]` | `[0,1,2,3,4,5]` | ProtoTwin signal address for each of the 6 joints |
| `JOINT_NAMES` | `list[str]` | `["base",…]` | Human-readable names used in status output |
| `CONVERT_TO_DEGREES` | `bool` | `True` | Convert RTDE radians to degrees before writing |

---

## 11. Troubleshooting

### Bridge prints `[RTDE] Connection failed` and keeps retrying

**Check 1 — Is the Docker container running?**

```bash
docker ps
```

You should see a row with `universalrobots/ursim_polyscopex`. If not, start the
container with the `docker run` command from section 5.1.

**Check 2 — Is port 30004 forwarded?**

Look at the `PORTS` column in `docker ps`. It must include `0.0.0.0:30004->30004/tcp`.
If it does not, you forgot the `-p 30004:30004` flag.

**Check 3 — Has PolyScope X finished booting?**

The RTDE server only accepts connections after the UR controller service is
fully initialised. Open `http://localhost:29999` and wait until the main
PolyScope X screen appears before starting the bridge.

---

### Bridge prints `[ProtoTwin] Connection failed`

**Check 1 — Is ProtoTwin Connect running?**

Look in the Windows system tray or taskbar. If the app is not open, launch it.

**Check 2 — Are you signed in?**

ProtoTwin Connect requires you to be logged in with a ProtoTwin account.

**Check 3 — Is the ProtoTwin model open in the browser?**

ProtoTwin Connect links to the active browser session. Open your model at
`play.prototwin.com` before starting the bridge.

---

### Bridge runs but the robot in ProtoTwin doesn't move

**Check 1 — Are the signal addresses correct?**

The bridge prints a warning at startup if `JOINT_SIGNAL_ADDRESSES` is still
`[0, 1, 2, 3, 4, 5]`. Even if the warning is absent, verify the addresses by
clicking each joint in ProtoTwin and comparing to your `bridge.py` config.

**Check 2 — Is the robot program playing?**

The bridge forwards whatever URSim reports. If no program is running and you
have not moved the robot manually, all joints stay at their home position and
the ProtoTwin model will appear stationary. Start a program in PolyScope X.

**Check 3 — Unit mismatch?**

If the robot in ProtoTwin moves but to wrong positions (very small offsets or
wild jumps), check whether the joint signals expect radians and you are sending
degrees, or vice versa. Toggle `CONVERT_TO_DEGREES` in `bridge.py`.

---

### `ModuleNotFoundError: No module named 'rtde_receive'`

The pip package is named `ur-rtde` but the Python import is `rtde_receive`:

```bash
pip install ur-rtde
```

---

### `ModuleNotFoundError: No module named 'prototwin'`

```bash
pip install prototwin
```

If that does not work, check the ProtoTwin Connect documentation for the current
package name — it may have changed.

---

### `TypeError: object is not awaitable` on `client.set()`

Your version of the `prototwin` package makes `set()` an async method. In
`bridge.py`, find the `client.set(address, value)` line (inside `run_bridge`)
and add `await`:

```python
await client.set(address, value)
```

---

### High CPU usage

If the bridge loop is consuming a lot of CPU, the `asyncio.sleep()` at the end
of each tick may not be sleeping long enough. Check that `LOOP_HZ` is not set
higher than 50 — at higher values the RTDE server may not keep up and the loop
spins waiting.

---

### Bridge crashes immediately with `RuntimeError: Event loop is closed`

This can happen if you run the script inside an environment that already manages
an event loop (e.g., Jupyter notebook). Replace the final lines of `bridge.py`:

```python
# Instead of:
asyncio.run(main())

# Use:
import nest_asyncio
nest_asyncio.apply()
asyncio.get_event_loop().run_until_complete(main())
```

And install `nest-asyncio`: `pip install nest-asyncio`.

---

## 12. Glossary

| Term | Meaning |
|---|---|
| **actual_q** | The RTDE variable holding the 6 measured joint positions in radians |
| **asyncio** | Python's built-in async I/O library; used here because the ProtoTwin client is async |
| **Docker** | A container runtime; runs URSim in an isolated environment on Windows |
| **gRPC** | A binary RPC protocol over HTTP/2; used internally by ProtoTwin Connect |
| **Hz** | Hertz — cycles per second. 50 Hz = 50 reads/writes per second |
| **MoveJ** | A PolyScope X instruction that moves the robot to a target pose via joint interpolation |
| **PolyScope X** | Universal Robots' web-based robot programming interface |
| **ProtoTwin** | Browser-based 3D simulation platform for industrial machines |
| **ProtoTwin Connect** | Desktop app that bridges Python code and a ProtoTwin browser session |
| **RTDE** | Real-Time Data Exchange — UR's high-frequency robot data streaming protocol |
| **Signal address** | Integer identifier for a controllable property within a ProtoTwin model |
| **URSim** | Universal Robots Simulator — runs the real PolyScope firmware in Docker |
| **ur-rtde** | The Python library for connecting to RTDE (imports as `rtde_receive`) |
