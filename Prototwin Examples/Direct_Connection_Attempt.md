# Direct PolyScope X -> ProtoTwin Connection Guide

This guide documents the current direct connection attempt between PolyScope X
and ProtoTwin without the external Python RTDE bridge.

Working path:

```text
PolyScope X / URSim Modbus TCP Server
  -> ProtoTwin Connect Modbus/TCP Generic server
  -> URModbusJointMapper TypeScript component
  -> direct IO connections to robot and gripper motor target positions
```

The existing Python bridge is still the best option for live manual jogging via
RTDE. This direct Modbus path is best for PolyScope program playback and simple
manual-sync workflows.

## 1. Start URSim with Modbus exposed

The URSim container must publish Modbus port `502` to Windows.

```powershell
docker run --rm --privileged --add-host host.docker.internal:host-gateway --env HOST_ARCH=amd64 --network bridge -p 127.0.0.1:8000:80 -p 127.0.0.1:29999:29999 -p 127.0.0.1:30004:30004 -p 127.0.0.1:502:502 universalrobots/ursim_polyscopex:latest
```

Expected `docker ps` output includes:

```text
127.0.0.1:502->502/tcp
```

The GUI launcher in `app.py` has also been updated to bind all URSim ports to
`127.0.0.1` only. This prevents other computers on the classroom network from
connecting to a student's simulator.

## 2. Enable PolyScope X services

In PolyScope X Services, enable:

```text
Modbus TCP Server    Port 502
RTDE                 Port 30004
```

RTDE is not required for the direct Modbus path, but it is useful for comparison
and for the existing Python bridge.

## 3. Verify Windows can reach Modbus

Run from Windows PowerShell:

```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 502
```

Expected:

```text
TcpTestSucceeded: True
```

## 4. Add ProtoTwin Connect server

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

## 5. Add ProtoTwin tags

This setup showed that ProtoTwin uses one-based register addresses for this UR
Modbus server. UR register `128` appears as ProtoTwin address `129`.

Joint tags:

```text
Name    Type    Area              Address
J1_raw  UInt16  Holding Register  129
J2_raw  UInt16  Holding Register  130
J3_raw  UInt16  Holding Register  131
J4_raw  UInt16  Holding Register  132
J5_raw  UInt16  Holding Register  133
J6_raw  UInt16  Holding Register  134
```

Gripper tag:

```text
Name         Type    Area              Address
Gripper_raw  UInt16  Holding Register  135
```

For all tags:

```text
Access: Read
Masked write: Off
High word first: Default
```

## 6. Add the ProtoTwin mapper component

Import or add `URModbusJointMapper.ts` as a scripted component in ProtoTwin.

The mapper exposes writable raw inputs:

```text
Raw J 1
Raw J 2
Raw J 3
Raw J 4
Raw J 5
Raw J 6
Raw Gripper
```

And readable decoded outputs:

```text
Target J 1
Target J 2
Target J 3
Target J 4
Target J 5
Target J 6
Target Left Finger
Target Right Finger
```

If the gripper signals do not appear, reload/re-import the TypeScript component,
remove the old mapper component from the entity, and add it again.

## 7. Bind Modbus tags to mapper inputs

In ProtoTwin Connect Bindings:

```text
J1_raw      -> URModbusJointMapper / Raw J 1
J2_raw      -> URModbusJointMapper / Raw J 2
J3_raw      -> URModbusJointMapper / Raw J 3
J4_raw      -> URModbusJointMapper / Raw J 4
J5_raw      -> URModbusJointMapper / Raw J 5
J6_raw      -> URModbusJointMapper / Raw J 6
Gripper_raw -> URModbusJointMapper / Raw Gripper
```

## 8. Connect mapper outputs to ProtoTwin actuators

Create direct IO connections from the mapper outputs:

```text
Target J 1 -> A1 Target Position
Target J 2 -> A2 Target Position
Target J 3 -> A3 Target Position
Target J 4 -> A4 Target Position
Target J 5 -> A5 Target Position
Target J 6 -> A6 Target Position
```

Gripper:

```text
Target Left Finger  -> Left Finger Target Position
Target Right Finger -> Right Finger Target Position
```

If a joint or finger moves in the wrong direction, change the corresponding
direction property on `URModbusJointMapper` from `1` to `-1` or from `-1` to `1`.

## 9. Encoding reference

Joints use tenths of a degree plus an offset:

```text
stored_value = floor(angle_rad * 572.957795 + 10000.5)
decoded_rad = ((stored_value - 10000) / 10) * pi / 180
```

Examples:

```text
10000 = 0.0 degrees
10050 = +5.0 degrees
9950  = -5.0 degrees
```

Gripper uses position multiplied by `10000`:

```text
stored_value = floor(gripper_position * 10000 + 0.5)
decoded_position = stored_value / 10000
```

For the current ProtoTwin gripper:

```text
0    = 0.0 = open
4000 = 0.4 = closed
```

## 10. Fixed communication test

In PolyScope X, run:

```urscript
write_port_register(128, 12345)
```

Expected:

```text
J1_raw = 12345
Raw J 1 = 12345
```

This proves:

```text
PolyScope X -> Modbus -> ProtoTwin Connect -> mapper input
```

## 11. One-shot position update

Use this when students manually jog the robot and then want ProtoTwin to jump to
the current pose.

File:

```text
update_prototwin_position_once.script
```

Code:

```urscript
def encode_joint_for_modbus(angle_rad):
  return floor(angle_rad * 572.957795 + 10000.5)
end

q = get_actual_joint_positions()

write_port_register(128, encode_joint_for_modbus(q[0]))
write_port_register(129, encode_joint_for_modbus(q[1]))
write_port_register(130, encode_joint_for_modbus(q[2]))
write_port_register(131, encode_joint_for_modbus(q[3]))
write_port_register(132, encode_joint_for_modbus(q[4]))
write_port_register(133, encode_joint_for_modbus(q[5]))
```

Recommended classroom name:

```text
Update ProtoTwin Position
```

## 12. Continuous joint sync during programs

Use this when students run normal PolyScope programs and want ProtoTwin to follow
while the program executes.

File:

```text
modbus_joint_sync_thread.script
```

Code:

```urscript
global keep_modbus_joint_sync_running = True

def encode_joint_for_modbus(angle_rad):
  return floor(angle_rad * 572.957795 + 10000.5)
end

thread modbus_joint_sync_thread():
  while keep_modbus_joint_sync_running:
    q = get_actual_joint_positions()

    write_port_register(128, encode_joint_for_modbus(q[0]))
    write_port_register(129, encode_joint_for_modbus(q[1]))
    write_port_register(130, encode_joint_for_modbus(q[2]))
    write_port_register(131, encode_joint_for_modbus(q[3]))
    write_port_register(132, encode_joint_for_modbus(q[4]))
    write_port_register(133, encode_joint_for_modbus(q[5]))

    sync()
  end
end

modbus_joint_sync = run modbus_joint_sync_thread()

# Student robot program goes below this line.
```

Important:

```text
`modbus_joint_sync = run modbus_joint_sync_thread()` must execute once.
Do not put the thread-start line inside a program loop.
```

If PolyScope reports `Cannot create thread: All 50 allowed threads are used`,
the thread-start line was executed repeatedly. Stop the program and restart the
controller/simulator to clear leaked test threads.

For a finite program, cleanup can be added at the end:

```urscript
keep_modbus_joint_sync_running = False
join modbus_joint_sync
```

## 13. Finite movement test

File:

```text
modbus_joint_sync_move_test.script
```

This starts one sync thread, moves the robot twice, then stops the thread.

```urscript
global keep_modbus_joint_sync_running = True

def encode_joint_for_modbus(angle_rad):
  return floor(angle_rad * 572.957795 + 10000.5)
end

thread modbus_joint_sync_thread():
  while keep_modbus_joint_sync_running:
    q = get_actual_joint_positions()

    write_port_register(128, encode_joint_for_modbus(q[0]))
    write_port_register(129, encode_joint_for_modbus(q[1]))
    write_port_register(130, encode_joint_for_modbus(q[2]))
    write_port_register(131, encode_joint_for_modbus(q[3]))
    write_port_register(132, encode_joint_for_modbus(q[4]))
    write_port_register(133, encode_joint_for_modbus(q[5]))

    sync()
  end
end

modbus_joint_sync = run modbus_joint_sync_thread()

movej([0.3, -1.2, 1.4, -1.5, 0.2, 0.0], a=0.5, v=0.3)
movej([0.0, -1.57, 1.57, -1.57, 0.0, 0.0], a=0.5, v=0.3)

keep_modbus_joint_sync_running = False
join modbus_joint_sync
```

## 14. Gripper scripts

One-shot close/open:

```urscript
def encode_gripper_for_modbus(position):
  return floor(position * 10000 + 0.5)
end

write_port_register(134, encode_gripper_for_modbus(0.4))
sleep(1.0)
write_port_register(134, encode_gripper_for_modbus(0.0))
```

Looping test:

```urscript
def encode_gripper_for_modbus(position):
  return floor(position * 10000 + 0.5)
end

while True:
  write_port_register(134, encode_gripper_for_modbus(0.4))
  sleep(1.0)

  write_port_register(134, encode_gripper_for_modbus(0.0))
  sleep(1.0)
end
```

Student-facing wrapper functions:

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

These wrappers make the classroom code look like a normal gripper API. For a
real gripper, only the wrapper internals would need to change.

## 15. App gripper control

The `app.py` gripper controls now write to both paths:

```text
gripper_cmd.json
  Used by the existing Python RTDE bridge.

Modbus register 134 on 127.0.0.1:502
  Used by the direct ProtoTwin Connect Modbus setup.
```

This lets the same Open/Close buttons and slider control the ProtoTwin gripper
in either architecture.

## 16. Manual jogging limitation

URScript threads only run while a PolyScope program is running. Manual jogging
and program execution are mutually exclusive in the current workflow.

Use:

```text
Manual jogging with live mirroring:
  Existing Python RTDE bridge.

Manual jogging without external bridge:
  Jog manually, then run the one-shot "Update ProtoTwin Position" script.

Normal PolyScope program playback:
  Use the Modbus sync thread.
```

## 17. Future option: URCapX backend service

A true no-external-app live manual-jogging solution would likely require a
PolyScope X URCapX backend container.

Potential architecture:

```text
URSim / PolyScope X runtime container
  Runs PolyScope X, URControl, RTDE, Modbus, and the web UI.

URCapX backend container
  Runs a background joint-sync service installed/managed by PolyScope X.
  Reads actual_q via RTDE/ROS 2/internal API.
  Publishes joint values to Modbus or another ProtoTwin Connect source.
```

This is probably not worth building yet because it adds SDK setup, packaging,
deployment, backend container networking, and a second runtime container.

Current recommendation:

```text
1. Use the existing Python RTDE bridge when manual jogging must be mirrored live.
2. Use the Modbus URScript thread when students run normal PolyScope programs.
3. Use one-shot update scripts for manual jog checkpoints.
4. Keep URCapX as the future no-external-app path.
```
