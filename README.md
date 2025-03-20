# Camera Streaming System

This project consists of three main components that work together to capture, process, and display live video streams. The system supports multiple camera feeds and maintains logs for connection status and errors.

## Components Overview

## 1. `capture.py`
- Captures video frames from a camera using OpenCV providing videoframecapture class with dummy frames.
### VideoFrameSender class
- Packages each frame with an 8‑byte header (4 bytes for width and 4 bytes for height) followed by the raw frame data.
- Establishes a TCP connection with the receiver (i.e. `send.py`) and continuously transmits these raw frames at the specified frame rate.
- Responsible solely for capturing and sending raw frames without any encoding.

## 2. `send.py`
- Listens on a TCP port to receive raw frames transmitted from `capture.py`.
- Reads the 8‑byte header to determine the frame's resolution and reconstructs the frame data.
- Encodes the received frames using H.264 compression via PyAV.
- Transmits the H.264 encoded packets via UDP to `server.py` when a connection is available.
- Optionally displays the received frames locally for monitoring.

### 3. `server.py`
- Receives and processes video streams from `send.py`.
- Displays the streams on a web-based interface.
- Supports multiple camera feeds from different devices.
- Logs connection status, errors, and timestamps for when cameras connect or disconnect.

## Web Interface

The system includes a web-based UI for managing cameras and viewing logs:

- **`index.html`**: Displays live camera feeds in a grid format.
- **`logs.html`**: Shows logs for camera connections, disconnections, and errors.
- **`manage_cams.html`**: Allows users to manage connected cameras.
- **`add_client.html`**: Provides a form to add new camera clients.

## Database (`clients.db`)
- Stores client information, including IP addresses, ports, and connection status.
- Keeps logs for events related to camera connections.

## How It Works

1. `capture.py` starts and captures video frames.
2. `send.py` receives raw frames, encodes them, and transmits them to `server.py`.
3. `server.py` processes incoming streams and displays them on the website.
4. The web interface allows users to monitor and manage camera feeds.
5. The system logs all activity, including connections and disconnections.

## Features
- Supports multiple cameras.
- Web interface for easy monitoring.
- Stores logs for tracking events.
- Auto-reconnect mechanism for lost connections.

## Usage
- Start `capture.py` on the device with the camera.
- Start `send.py` to encode and transmit video.
- Run `server.py` to receive and display feeds.

This system is designed for real-time video monitoring with logging and management capabilities.
