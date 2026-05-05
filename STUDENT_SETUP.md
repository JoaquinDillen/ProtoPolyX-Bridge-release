# Student Setup Guide

This guide gets a student machine running the PolyScope X to ProtoTwin classroom
configuration.

There are two supported modes:

```text
Python bridge mode:
  URSim -> RTDE port 30004 -> bridge.py/app.py -> ProtoTwin Connect

Direct Modbus mode:
  URSim Modbus TCP port 502 -> ProtoTwin Connect -> URModbusJointMapper
```

Use Python bridge mode for live manual jogging. Use direct Modbus mode for
normal PolyScope program playback and gripper control through ProtoTwin Connect.

## 1. Install required software

Install Docker Desktop:

```text
https://docs.docker.com/desktop/setup/install/windows-install/
```

Install ProtoTwin Connect:

```text
https://prototwin.com/account/signin
```

ProtoTwin Connect installers are available from the ProtoTwin account page after
signing in.

Install Python 3.9 or newer, then install the Python packages:

```powershell
pip install customtkinter ur-rtde prototwin
```

## 2. Use the app install buttons

The app includes install shortcuts in the Services section:

```text
Docker Desktop      Install | Launch
ProtoTwin Connect   Install | Launch
```

The Docker button opens the official Docker Desktop Windows installation page.
The ProtoTwin button opens the ProtoTwin sign-in page where students can download
ProtoTwin Connect from their account.

## 3. Start the app

From this repository:

```powershell
python app.py
```

The app can:

```text
1. Launch Docker Desktop.
2. Start the URSim PolyScope X container.
3. Launch ProtoTwin Connect.
4. Open PolyScope X in the browser.
5. Open ProtoTwin in the browser.
6. Start or stop the Python bridge.
7. Control the ProtoTwin gripper through Bridge, Modbus, or Both.
```

## 4. Start URSim

In the app, click:

```text
Docker Desktop -> Launch
URSim Container -> Launch
```

The app starts URSim with these important ports:

```text
8000  PolyScope X web UI
29999 Dashboard server
30004 RTDE
502   Modbus TCP Server
```

The ports are bound to `127.0.0.1` only. This means each student's simulator is
reachable only from their own computer, not from other machines on the classroom
network.

Manual command, if needed:

```powershell
docker run --rm --privileged --add-host host.docker.internal:host-gateway --env HOST_ARCH=amd64 --network bridge -p 127.0.0.1:8000:80 -p 127.0.0.1:29999:29999 -p 127.0.0.1:30004:30004 -p 127.0.0.1:502:502 universalrobots/ursim_polyscopex:latest
```

Verify Modbus is reachable:

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 502
```

Expected:

```text
TcpTestSucceeded: True
```

## 5. Enable PolyScope X services

Open PolyScope X:

```text
http://localhost:8000
```

In Settings / Services, enable:

```text
Modbus TCP Server    Port 502
RTDE                 Port 30004
```

## 6. Prepare ProtoTwin Connect for direct Modbus

In ProtoTwin Connect, add a Modbus server:

```text
Protocol: Modbus/TCP
Type: Generic
Name: URSim
Host: 127.0.0.1
Port: 502
Unit ID: 255
Scan Rate: 0.02
```

Add these tags:

```text
Name         Type    Area              Address
J1_raw       UInt16  Holding Register  129
J2_raw       UInt16  Holding Register  130
J3_raw       UInt16  Holding Register  131
J4_raw       UInt16  Holding Register  132
J5_raw       UInt16  Holding Register  133
J6_raw       UInt16  Holding Register  134
Gripper_raw  UInt16  Holding Register  135
```

For all tags:

```text
Access: Read
Masked write: Off
High word first: Default
```

## 7. Add the ProtoTwin mapper

In ProtoTwin, add the scripted component:

```text
Prototwin Examples/URModbusJointMapper.ts
```

Bind tags to mapper inputs:

```text
J1_raw      -> URModbusJointMapper / Raw J 1
J2_raw      -> URModbusJointMapper / Raw J 2
J3_raw      -> URModbusJointMapper / Raw J 3
J4_raw      -> URModbusJointMapper / Raw J 4
J5_raw      -> URModbusJointMapper / Raw J 5
J6_raw      -> URModbusJointMapper / Raw J 6
Gripper_raw -> URModbusJointMapper / Raw Gripper
```

Create direct IO connections:

```text
Target J 1 -> A1 Target Position
Target J 2 -> A2 Target Position
Target J 3 -> A3 Target Position
Target J 4 -> A4 Target Position
Target J 5 -> A5 Target Position
Target J 6 -> A6 Target Position

Target Left Finger  -> Left Finger Target Position
Target Right Finger -> Right Finger Target Position
```

If a joint or finger moves in the wrong direction, flip the matching direction
property on `URModbusJointMapper`.

## 8. Test direct Modbus communication

In PolyScope X, run this once:

```urscript
write_port_register(128, 12345)
```

Expected in ProtoTwin:

```text
J1_raw = 12345
Raw J 1 = 12345
```

## 9. Use the classroom scripts

One-shot position update after manual jogging:

```text
Prototwin Examples/update_prototwin_position_once.script
```

Continuous joint sync during a PolyScope program:

```text
Prototwin Examples/modbus_joint_sync_thread.script
```

Finite movement test:

```text
Prototwin Examples/modbus_joint_sync_move_test.script
```

Gripper close/open test:

```text
Prototwin Examples/set_prototwin_gripper.script
```

## 10. Gripper commands from PolyScope X

Use these functions in a PolyScope script:

```urscript
def gripper_set_position(position):
  write_port_register(134, floor(position * 10000 + 0.5))
end

def gripper_open():
  gripper_set_position(0.0)
end

def gripper_close():
  gripper_set_position(0.4)
end
```

Example:

```urscript
gripper_close()
sleep(1.0)
gripper_open()
```

## 11. App gripper mode

The app gripper section has an output selector:

```text
Both
Bridge
Modbus
```

Use:

```text
Both:
  Writes gripper_cmd.json and Modbus register 134.

Bridge:
  Uses the existing Python bridge path only.

Modbus:
  Writes direct Modbus register 134 only.
```

## 12. When to use each mode

Use Python bridge mode when:

```text
Students manually jog the robot and need live ProtoTwin mirroring.
```

Use direct Modbus mode when:

```text
Students run PolyScope programs and ProtoTwin should follow.
Students need simple open/close gripper commands from PolyScope X.
Students manually jog, then run "Update ProtoTwin Position" as a checkpoint.
```

More technical details are in:

```text
Prototwin Examples/Direct_Connection_Attempt.md
```
