import cv2
import socket
import struct
import time
import av
import numpy as np

def receive_frames_from_network(port):
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(('0.0.0.0', port))
    server_sock.listen(1)
    print(f"Listening on port {port}...")

    conn, addr = server_sock.accept()
    print(f"Connected by {addr}")

    try:
        while True:
            # Read the 8-byte header: 4 bytes for width, 4 bytes for height
            header = conn.recv(8)
            if len(header) != 8:
                print("Incomplete header. Closing connection.")
                break

            width, height = struct.unpack("!II", header)
            frame_size = width * height * 3  # Assuming 3 channels (BGR)
            # Debug: print the received resolution
            # print(f"Received header: width={width}, height={height}, frame_size={frame_size}")

            # Read the frame data based on computed frame_size
            frame_data = b""
            while len(frame_data) < frame_size:
                chunk = conn.recv(frame_size - len(frame_data))
                if not chunk:
                    break
                frame_data += chunk

            if len(frame_data) != frame_size:
                print("Incomplete frame data. Closing connection.")
                break

            try:
                # Reshape the frame using the received width and height
                frame = np.frombuffer(frame_data, dtype=np.uint8).reshape((height, width, 3))
                yield frame
            except Exception as e:
                print(f"Frame reshape error: {e}")
    finally:
        conn.close()
        server_sock.close()

def encode_and_send_frames(frame_gen, udp_ip, udp_port):
    # Get the first frame to determine dimensions
    try:
        first_frame = next(frame_gen)
    except StopIteration:
        print("No frames received")
        return

    height, width, _ = first_frame.shape
    print(f"Detected frame dimensions: {width}x{height}")

    # Initialize PyAV encoder with the detected dimensions
    container = av.open('stream.h264', mode='w', format='h264')
    stream = container.add_stream('h264', rate=30)
    stream.width = width
    stream.height = height
    stream.pix_fmt = 'yuv420p'
    stream.options = {'preset': 'ultrafast', 'tune': 'zerolatency'}

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    try:
        # Process the first frame
        av_frame = av.VideoFrame.from_ndarray(first_frame, format='bgr24')
        for packet in stream.encode(av_frame):
            udp_sock.sendto(bytes(packet), (udp_ip, udp_port))

        # Process subsequent frames
        for frame in frame_gen:
            av_frame = av.VideoFrame.from_ndarray(frame, format='bgr24')
            for packet in stream.encode(av_frame):
                udp_sock.sendto(bytes(packet), (udp_ip, udp_port))

            cv2.imshow('Received', frame)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        # Flush the encoder
        for packet in stream.encode(None):
            udp_sock.sendto(bytes(packet), (udp_ip, udp_port))
            
    finally:
        udp_sock.close()
        container.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    gen = receive_frames_from_network(6000)
    encode_and_send_frames(gen, "127.0.0.1", 5002)
