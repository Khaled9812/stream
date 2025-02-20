import cv2
import socket
import struct
import time
import numpy as np

# Which camera do we open locally?
CAMERA_INDEX = 0

# Our desired FPS as a guideline (the camera will supply frames at its own rate)
DESIRED_FPS = 30
# FRAME_INTERVAL is computed for reference; we remove extra waiting to send frames instantly.
FRAME_INTERVAL = 1.0 / DESIRED_FPS

# List of target hosts to send frames to.
# Each entry is a tuple (ip, port)
TARGETS = [
    ("127.0.0.1", 6000),  # Example: send to another app on the same machine on port 6000
    # Add more hosts if needed.
]

def reconnect_target(target):
    ip, port = target
    try:
        print(f"Attempting to reconnect to {ip}:{port}...")
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect((ip, port))
        print(f"Reconnected to {ip}:{port}")
        return s
    except Exception as e:
        print(f"Reconnect failed for {ip}:{port}: {e}")
        return None

def main():
    cap = cv2.VideoCapture(CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FPS, DESIRED_FPS)
    if not cap.isOpened():
        print("Error: Could not open camera.")
        return

    # Create a dictionary for sockets keyed by target tuple.
    sockets = {}
    for target in TARGETS:
        ip, port = target
        print(f"Connecting to {ip}:{port}...")
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ip, port))
            sockets[target] = s
            print(f"Connected to {ip}:{port}")
        except Exception as e:
            print(f"Failed to connect to {ip}:{port}: {e}")
            sockets[target] = None

    try:
        while True:
            start_time = time.time()
            ret, frame = cap.read()
            if not ret:
                print("Error reading frame from camera.")
                continue

            # Remove encoding: convert the frame directly to raw bytes.
            frame_bytes = frame.tobytes()
            frame_size = len(frame_bytes)
            # Prepare data: 4-byte size header (big-endian) followed by the raw frame data.
            data_to_send = struct.pack("!I", frame_size) + frame_bytes

            # Send to each target.
            for target in TARGETS:
                if sockets.get(target) is None:
                    sockets[target] = reconnect_target(target)
                s = sockets.get(target)
                if s is None:
                    continue  # skip if not connected
                try:
                    s.sendall(data_to_send)
                except Exception as e:
                    print(f"Error sending to {s.getpeername()}: {e}")
                    try:
                        s.close()
                    except Exception:
                        pass
                    sockets[target] = None  # Mark as disconnected

            # Let the loop run as soon as processing is complete.
            elapsed = time.time() - start_time
            to_wait = FRAME_INTERVAL - elapsed
            if to_wait > 0:
                time.sleep(to_wait)

            # (Optional) Display the camera feed locally.
            cv2.imshow('Client Camera Feed', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("User requested exit.")
                break

    except KeyboardInterrupt:
        print("User interrupted. Exiting.")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        for s in sockets.values():
            if s:
                s.close()
        print("Cleanup done.")

if __name__ == "__main__":
    main()
