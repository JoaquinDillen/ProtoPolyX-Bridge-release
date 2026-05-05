# ProtoPolyX Bridge (Release)

<p align="center">
  <img src="assets/ProtoPolyX-Bridge_256.png" alt="ProtoPolyX Bridge Logo" width="180">
</p>

This repository hosts **public Windows releases** of **ProtoPolyX Bridge**.

ProtoPolyX Bridge connects **Universal Robots URSim / PolyScope X** with a **ProtoTwin digital twin** so students can practise robot programming workflows and see the robot motion reflected in simulation.

## Download

Go to **Releases** and download the latest `URSimProtoTwinBridge.exe`.

Current release notes: `v1.0.0`

## Requirements

- Windows 10/11
- Docker Desktop
- ProtoTwin Connect
- ProtoTwin account and model prepared for the bridge workflow
- Internet access for first Docker image pull

## What the app does

- Launches Docker Desktop when installed.
- Starts the URSim PolyScope X container with local-only ports.
- Opens PolyScope X and ProtoTwin in the browser.
- Launches ProtoTwin Connect when installed.
- Runs the RTDE bridge for live robot mirroring.

## Bridge workflow

Use this app for live mirroring, including manual jogging.

```text
URSim -> RTDE port 30004 -> ProtoPolyX Bridge -> ProtoTwin Connect
```

## First-time setup

1. Download `URSimProtoTwinBridge.exe` from Releases.
2. Run the app.
3. Use the app's **Install** buttons for Docker Desktop and ProtoTwin Connect if needed.
4. Launch Docker Desktop.
5. Launch the URSim container from the app.
6. Enable this PolyScope X service:

```text
RTDE                 Port 30004
```

7. Open ProtoTwin Connect and the prepared ProtoTwin model.
8. Start the bridge from the app.

## Network behavior

The app starts URSim with ports bound to `127.0.0.1` only. Each student's simulator is reachable only from their own computer, not from other machines on the classroom network.

## Documentation

Detailed setup guides are maintained with the source project and may also be attached to course material:

- Student setup guide
- Portuguese Portugal setup guide

## Troubleshooting

### Docker Desktop is not found

Use the **Install** button in the app or install Docker Desktop manually from Docker's official Windows installation page.

### ProtoTwin Connect is not found

Use the **Install** button in the app. ProtoTwin Connect is downloaded from your ProtoTwin account page after signing in.

### The bridge does not start

Check that URSim is running and RTDE is enabled on port `30004`. Also confirm ProtoTwin Connect is open and signed in.

## License

PolyForm Noncommercial 1.0.0 (see `LICENSE`).

[//]: # (This is a binary release repository.)
[//]: # (The Windows executable is published through GitHub Releases.)
