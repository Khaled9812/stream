import socket
import cv2
import sqlite3
from flask import Flask, Response, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from threading import Thread, Lock
import numpy as np
import time
import av
from datetime import datetime
from collections import defaultdict
import requests
import os

app = Flask(__name__)
app.secret_key = "secret"

# Dictionary to store the latest decoded frame for each client_id
frames = {}
frames_lock = Lock()

DB_FILENAME = "clients.db"
RECORDINGS_DIR = os.path.abspath("recordings")

##################
# DATABASE HELPERS
##################

def init_db():
    """Initialize the SQLite database and create tables if they don't exist."""
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS clients (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    client_ip TEXT NOT NULL,
                    client_tcp_port INTEGER NOT NULL,
                    client_name TEXT NOT NULL,
                    server_udp_port INTEGER NOT NULL,
                    last_connected TEXT,
                    status TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    client_id TEXT,
                    event_message TEXT NOT NULL
                )''')
    conn.commit()
    conn.close()

def log_event(client_id, message):
    """Insert a log event into the database."""
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO logs (timestamp, client_id, event_message) VALUES (?, ?, ?)",
              (timestamp, client_id, message))
    conn.commit()
    conn.close()
    print(f"[{timestamp}] {client_id} {message}")

def upsert_client(client_ip, client_tcp_port, client_name, server_udp_port):
    """
    Insert/update a client in the DB. Returns a URL-safe client_id string.
    """
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client_id = f"{client_name}-{client_ip}-{server_udp_port}"
    
    c.execute("""SELECT id FROM clients
                 WHERE client_ip = ? AND client_tcp_port = ?
                       AND client_name = ? AND server_udp_port = ?""",
              (client_ip, client_tcp_port, client_name, server_udp_port))
    row = c.fetchone()
    if row:
        client_db_id = row[0]
        c.execute("""UPDATE clients
                     SET last_connected = ?, status = ?
                     WHERE id = ?""",
                  (timestamp, "active", client_db_id))
    else:
        c.execute("""INSERT INTO clients (
                        client_ip, client_tcp_port, client_name,
                        server_udp_port, last_connected, status)
                     VALUES (?, ?, ?, ?, ?, ?)""",
                  (client_ip, client_tcp_port, client_name,
                   server_udp_port, timestamp, "active"))
    conn.commit()
    conn.close()
    return client_id

def mark_client_inactive(client_id, new_status="inactive"):
    """
    Update a camera's status in the DB using the URL-safe client_id.
    """
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    c.execute("""UPDATE clients
                 SET status = ?
                 WHERE client_name || '-' || client_ip || '-' || server_udp_port = ?""",
              (new_status, client_id))
    conn.commit()
    conn.close()

def get_all_clients():
    """Return all clients from the DB as a list of rows."""
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    c.execute("""SELECT id, client_ip, client_tcp_port, client_name,
                        server_udp_port, last_connected, status
                 FROM clients
                 ORDER BY id DESC""")
    rows = c.fetchall()
    conn.close()
    return rows

#############################
# AUTO-RECONNECT THREAD
#############################

def auto_reconnect_clients():
    """
    Periodically checks all clients in the DB. If they're not in frames or not active,
    attempts to reconnect them automatically.
    """
    while True:
        all_clients = get_all_clients()
        for row in all_clients:
            client_db_id, client_ip, client_tcp_port, client_name, server_udp_port, last_connected, status = row
            temp_client_id = f"{client_name}-{client_ip}-{server_udp_port}"

            with frames_lock:
                if temp_client_id in frames:
                    continue

            if status != "active":
                success, cid = connect_to_client(client_ip, client_tcp_port, server_udp_port, client_name,
                                                 auto_reconnect=True)
                if success:
                    log_event(cid, "Auto-reconnected.")
        time.sleep(60)

##################
# FLASK ROUTES
##################

@app.route('/')
def index():
    page = int(request.args.get('page', 1))
    clients_per_page = 6

    with frames_lock:
        client_ids = list(frames.keys())

    total_pages = (len(client_ids) + clients_per_page - 1) // clients_per_page
    start_index = (page - 1) * clients_per_page
    end_index = start_index + clients_per_page
    visible_clients = client_ids[start_index:end_index]

    return render_template('index.html',
                           client_ids=visible_clients,
                           page=page,
                           total_pages=total_pages)

@app.route('/video_feed/<client_id>')
def video_feed(client_id):
    def generate():
        while True:
            with frames_lock:
                frame = frames.get(client_id)
                if frame is None:
                    break

            ret, buffer = cv2.imencode('.jpg', frame)
            if not ret:
                continue

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
            time.sleep(0.03)

    return Response(generate(),
                    mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/add_client', methods=['GET', 'POST'])
def add_client():
    if request.method == 'POST':
        client_ip = request.form.get('client_ip')
        client_tcp_port = int(request.form.get('client_tcp_port'))
        client_name = request.form.get('client_name')
        server_udp_port = int(request.form.get('server_udp_port'))

        success, client_id = connect_to_client(client_ip, client_tcp_port, server_udp_port, client_name)
        if success:
            flash(f"Client {client_id} added successfully.", "success")
        else:
            flash("Failed to connect to client.", "danger")

        return redirect(url_for('index'))

    return render_template('add_client.html')

@app.route('/logs')
def logs():
    selected_date = request.args.get('date', datetime.today().strftime('%Y-%m-%d'))
    
    try:
        datetime.strptime(selected_date, '%Y-%m-%d')
    except ValueError:
        selected_date = datetime.today().strftime('%Y-%m-%d')

    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    c.execute("""SELECT timestamp, client_id, event_message 
                 FROM logs 
                 WHERE DATE(timestamp) = ?
                 ORDER BY timestamp DESC""", (selected_date,))
    logs_data = c.fetchall()
    conn.close()

    logs_by_date = defaultdict(list)
    for timestamp, client_id, event_message in logs_data:
        date_part = timestamp.split()[0]
        time_part = timestamp.split()[1][:5]
        logs_by_date[date_part].append({
            "time": time_part,
            "client_name": client_id,
            "event": event_message
        })

    return render_template(
        'logs.html',
        logs_by_date=dict(logs_by_date),
        selected_date=selected_date
    )

@app.route('/manage_cams')
def manage_cams():
    all_clients = get_all_clients()
    return render_template('manage_cams.html', all_clients=all_clients)

@app.route('/remove_cam/<int:client_db_id>', methods=['POST'])
def remove_cam(client_db_id):
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    c.execute("""SELECT client_name, client_ip, server_udp_port
                 FROM clients
                 WHERE id = ?""", (client_db_id,))
    row = c.fetchone()
    if row:
        client_name, client_ip, server_udp_port = row
        client_id = f"{client_name}-{client_ip}-{server_udp_port}"

        with frames_lock:
            frames.pop(client_id, None)

        c.execute("DELETE FROM clients WHERE id = ?", (client_db_id,))
        conn.commit()
        flash(f"Camera '{client_name}' removed successfully.", "success")
        log_event(client_id, "Manually removed from DB and frames.")
    else:
        flash("Camera not found in database.", "danger")

    conn.close()
    return redirect(url_for('manage_cams'))

@app.route('/reconnect_cam/<int:client_db_id>', methods=['POST'])
def reconnect_cam(client_db_id):
    conn = sqlite3.connect(DB_FILENAME)
    c = conn.cursor()
    c.execute("""SELECT client_name, client_ip, client_tcp_port, server_udp_port
                 FROM clients
                 WHERE id = ?""", (client_db_id,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash("Camera not found in database.", "danger")
        return redirect(url_for('manage_cams'))

    client_name, client_ip, client_tcp_port, server_udp_port = row
    conn.close()

    success, client_id = connect_to_client(client_ip, client_tcp_port, server_udp_port, client_name)
    if success:
        flash(f"Camera '{client_name}' reconnected successfully.", "success")
    else:
        flash(f"Failed to reconnect camera '{client_name}'.", "danger")

    return redirect(url_for('manage_cams'))

@app.route('/api/active-cameras')
def active_cameras():
    with frames_lock:
        active_cams = list(frames.keys())
    return jsonify({"cameras": active_cams})

@app.route('/api/frames/<path:client_id>')
def api_frame(client_id):
    with frames_lock:
        frame = frames.get(client_id)
        if frame is None:
            return jsonify({"error": "Camera not found"}), 404
        
        # Clone frame to prevent concurrent modification
        frame_copy = frame.copy()
        _, buffer = cv2.imencode('.jpg', frame_copy)
        return Response(buffer.tobytes(), mimetype='image/jpeg')

@app.route('/recordings')
def recordings():
    try:
        response = requests.get("http://localhost:8001/api/recordings/dates")
        dates = response.json().get('dates', [])
    except:
        dates = []
    return render_template('recordings.html', dates=dates)

@app.route('/recordings/<date>')
def date_recordings(date):
    try:
        response = requests.get(f"http://localhost:8001/api/recordings/{date}")
        data = response.json()
    except:
        data = {"date": date, "recordings": []}
    return render_template('date_recordings.html', **data)

@app.route('/recordings/<path:filename>')
def serve_recording(filename):
    return send_from_directory(RECORDINGS_DIR, filename)

#########################
# NETWORK / STREAMING
#########################

def handle_udp_stream(client_id, server_udp_port):
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_socket.settimeout(5)

    udp_socket.bind(('0.0.0.0', server_udp_port))
    decoder = av.codec.CodecContext.create('h264', 'r')

    try:
        while True:
            try:
                data, addr = udp_socket.recvfrom(65536)
            except socket.timeout:
                raise ConnectionError("UDP receive timeout")

            try:
                packet = av.Packet(data)
                frames_decoded = decoder.decode(packet)
                for decoded_frame in frames_decoded:
                    img = decoded_frame.to_ndarray(format='bgr24')
                    img = cv2.resize(img, (640, 480))
                    with frames_lock:
                        frames[client_id] = img
            except Exception as e:
                log_event(client_id, f"Decoding failed: {e}")
    except Exception as e:
        log_event(client_id, f"Error/Disconnect: {e}")
    finally:
        with frames_lock:
            frames.pop(client_id, None)
        udp_socket.close()
        mark_client_inactive(client_id, "disconnected")
        log_event(client_id, "Disconnected.")

def connect_to_client(client_ip, client_tcp_port, server_udp_port, client_name, auto_reconnect=False):
    tmp_id = f"{client_name}-{client_ip}-{server_udp_port}"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(10)
        s.connect((client_ip, client_tcp_port))
        s.sendall(str(server_udp_port).encode())
        s.close()

        client_id = upsert_client(client_ip, client_tcp_port, client_name, server_udp_port)
        log_event(client_id, "Connected.")

        Thread(target=handle_udp_stream, args=(client_id, server_udp_port), daemon=True).start()
        return True, client_id
    except Exception as e:
        log_event(tmp_id, f"Connection failed: {e}")
        return False, None

########
# MAIN
########

if __name__ == "__main__":
    init_db()
    Thread(target=auto_reconnect_clients, daemon=True).start()
    app.run(host='0.0.0.0', port=8000)