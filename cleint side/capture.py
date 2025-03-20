import cv2
import socket
import struct
import time
import numpy as np


# this class takes 
class VideoFrameSender:
    def __init__(self, targets, desired_fps=30):
        """
        Initializes the sender with target addresses and desired FPS.
        :param targets: A list of (ip, port) tuples to which frames will be sent.
        :param desired_fps: The desired frames-per-second rate for sending.
        """
        self.targets = targets
        self.desired_fps = desired_fps
        self.frame_interval = 1.0 / desired_fps
        self.sockets = {}

    def _reconnect_target(self, target):
        ip, port = target
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect((ip, port))
            print(f"Connected to {ip}:{port}")
            return s
        except Exception as e:
            print(f"Connection failed to {ip}:{port} -> {e}")
            return None

    def send_frame(self, frame):
        """
        Sends a provided frame to all targets.
        The frame is expected to be a NumPy array of shape (height, width, channels).
        It prepends an 8-byte header containing the width and height.
        """
        # Get frame dimensions
        height, width, channels = frame.shape

        # Create an 8-byte header: 4 bytes for width, 4 bytes for height
        header = struct.pack("!II", width, height)
        frame_bytes = frame.tobytes()
        data = header + frame_bytes

        start_time = time.time()

        # Send the frame data to each target
        for target in self.targets:
            s = self.sockets.get(target)
            if s is None:
                s = self._reconnect_target(target)
                self.sockets[target] = s
            if s:
                try:
                    s.sendall(data)
                except Exception as e:
                    print(f"Send error to {target}: {e}")
                    s.close()
                    self.sockets[target] = None

        # Control sending rate based on desired FPS
        elapsed = time.time() - start_time
        if elapsed < self.frame_interval:
            time.sleep(self.frame_interval - elapsed)

    def stop(self):
        """
        Closes all active target sockets.
        """
        for s in self.sockets.values():
            if s:
                s.close()
        print("Frame sender stopped")

if __name__ == "__main__":
    # Example usage: 
    # This sender sends frames to targets without capturing them directly.
    # For demonstration, we capture frames via cv2 (from a webcam or video file) 
    # and pass them to the sender.
    
    TARGETS = [("127.0.0.1", 6000)]
    sender = VideoFrameSender(TARGETS, desired_fps=30)
    
    # Use cv2 to capture frames (change 0 to a video file path if needed)
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    if not cap.isOpened():
        print("Failed to open video source")
        exit(1)
    
    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            # Send the frame using the sender instance
            sender.send_frame(frame)
            
            # Optional: display the source frame locally
            cv2.imshow("Source Frame", frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        print("Interrupted by user")
    finally:
        cap.release()
        sender.stop()
        cv2.destroyAllWindows()
