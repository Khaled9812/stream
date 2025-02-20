import cv2
import socket
import struct
import time
import av  # PyAV
import numpy as np

# The port where we listen for incoming frames (from the capture app)
LISTEN_PORT = 6000

DESIRED_FPS = 30
FRAME_INTERVAL = 1.0 / DESIRED_FPS
IDLE_TIMEOUT = 60  # 1 minute with no data => close connection & re-listen

# Define the expected frame dimensions (must match the capture app)
WIDTH = 640
HEIGHT = 480
CHANNELS = 3
EXPECTED_SIZE = WIDTH * HEIGHT * CHANNELS

def receive_frames_from_network(listen_port):
    """
    A generator function that repeatedly listens on TCP port `listen_port` for a connection
    from the capture app. Once connected, it receives frames in the following format:
      - 4-byte frame size (big-endian integer)
      - that many bytes of raw frame data (BGR format, row-major)
    It then converts the raw bytes into a NumPy array with shape (HEIGHT, WIDTH, CHANNELS)
    and yields the resulting frame.
    If no data is received for IDLE_TIMEOUT seconds, or the connection ends, it closes
    the connection and re-listens.
    """
    while True:
        # Create a fresh listening socket for each cycle.
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind(('0.0.0.0', listen_port))
        server_sock.listen(1)
        print(f"[Receiver] Waiting for raw frame connection on port {listen_port}...")
        
        conn, addr = server_sock.accept()
        print(f"[Receiver] Connected by {addr}")
        
        # Set a 1-second timeout on socket reads.
        conn.settimeout(1.0)
        last_received = time.time()

        try:
            while True:
                if (time.time() - last_received) > IDLE_TIMEOUT:
                    print("[Receiver] No data for 60s. Closing connection & re-listening.")
                    break

                # Read 4-byte size header.
                try:
                    raw_size = conn.recv(4)
                except socket.timeout:
                    continue

                if not raw_size or len(raw_size) < 4:
                    print("[Receiver] Incomplete size header. Closing connection.")
                    break

                frame_size = struct.unpack("!I", raw_size)[0]
                if frame_size != EXPECTED_SIZE:
                    print(f"[Receiver] Warning: Expected frame size {EXPECTED_SIZE}, got {frame_size}. Skipping frame.")
                    # Skip reading the frame data.
                    conn.recv(frame_size)
                    continue

                # Read the raw frame data.
                frame_data = b""
                remaining = frame_size
                while remaining > 0:
                    try:
                        chunk = conn.recv(remaining)
                    except socket.timeout:
                        if (time.time() - last_received) > IDLE_TIMEOUT:
                            print("[Receiver] Idle timeout while reading frame. Closing connection.")
                            break
                        continue
                    if not chunk:
                        print("[Receiver] Connection closed while reading frame data.")
                        break
                    frame_data += chunk
                    remaining -= len(chunk)
                    last_received = time.time()

                if len(frame_data) < frame_size:
                    print("[Receiver] Incomplete frame data. Closing connection.")
                    break

                # Convert raw bytes to NumPy array and reshape.
                try:
                    frame_array = np.frombuffer(frame_data, dtype=np.uint8)
                    frame = frame_array.reshape((HEIGHT, WIDTH, CHANNELS))
                except Exception as e:
                    print(f"[Receiver] Error reshaping frame: {e}")
                    continue

                yield frame

        finally:
            conn.close()
            server_sock.close()
            print("[Receiver] Socket closed. Re-listening for a new connection.")

def encode_and_send_frames(frame_generator, server_ip, server_udp_port):
    """
    Processes frames from the generator by encoding them as H.264 via PyAV
    and sends each encoded packet via UDP to the specified server.
    """
    # Get the first frame from the generator.
    first_frame = next(frame_generator, None)
    if first_frame is None:
        print("[Sender] No frames received. Exiting.")
        return

    height, width, channels = first_frame.shape
    print(f"[Sender] First frame dimensions: {width}x{height} (channels: {channels})")

    # Initialize PyAV H.264 encoder.
    codec = av.codec.CodecContext.create('h264', 'w')
    codec.width = width
    codec.height = height
    codec.pix_fmt = 'yuv420p'
    codec.options = {'preset': 'ultrafast', 'tune': 'zerolatency'}

    # Create a UDP socket for sending the encoded packets.
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    try:
        frames_to_process = [first_frame]

        while True:
            if not frames_to_process:
                raw_data = next(frame_generator, None)
                if raw_data is None:
                    print("[Sender] No more frames from generator. Exiting loop.")
                    break
                # raw_data is a raw frame; no decoding here is needed because our generator yields frames.
                f = raw_data  # already a NumPy array
                frames_to_process.append(f)

            start_time = time.time()
            frame = frames_to_process.pop(0)

            # Convert from BGR to RGB for PyAV.
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            av_frame = av.VideoFrame.from_ndarray(frame_rgb, format='rgb24')
            av_frame = av_frame.reformat(width, height, format='yuv420p')

            # Encode the frame.
            try:
                for packet in codec.encode(av_frame):
                    data = bytes(packet)
                    udp_socket.sendto(data, (server_ip, server_udp_port))
            except Exception as e:
                print(f"[Sender] Error during encoding/sending: {e}")
                break

            elapsed_time = time.time() - start_time
            time_to_wait = max(0, FRAME_INTERVAL - elapsed_time)
            time.sleep(time_to_wait)

            # (Optional) Display the frame locally.
            cv2.imshow('Processed Frames (2nd App)', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[Sender] User requested exit from second app.")
                break

        # Flush remaining packets.
        for packet in codec.encode(None):
            data = bytes(packet)
            udp_socket.sendto(data, (server_ip, server_udp_port))

    except KeyboardInterrupt:
        print("[Sender] User interrupted. Exiting.")
    finally:
        udp_socket.close()
        cv2.destroyAllWindows()

def main():
    # Receive raw frames (which are raw, not JPEG, because the capture app is sending raw data)
    frame_gen = receive_frames_from_network(LISTEN_PORT)
    SERVER_IP = "127.0.0.1"
    SERVER_UDP_PORT = 5002
    encode_and_send_frames(frame_gen, SERVER_IP, SERVER_UDP_PORT)

if __name__ == "__main__":
    main()
