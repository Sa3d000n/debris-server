from flask import Flask, request, jsonify, render_template, send_file, Response , url_for 
from flask_cors import CORS
import matplotlib.pyplot as plt
import numpy as np
import io
import cv2
import requests
import time
from ultralytics import YOLO

app = Flask(__name__)
CORS(app)

clients = {}
data_ = {}
thermal_data_ = {}
threshold_temp = None  # Global threshold variable

# ESP32-CAM MJPEG stream URL
esp32_cam_url = 'http://192.168.1.83/cam-lo.jpg'

# Desired frame dimensions
frame_width = 320
frame_height = 240

# Desired frames per second
fps = 80
delay = 1 / fps

# Load the YOLOv8n model
model = YOLO("yolov8n.pt")

@app.route('/')
def navigation():
    return render_template('navigation.html')


@app.route('/home')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/data/<client_id>', methods=['POST'])
def receive_data(client_id):
    data = request.get_json()  # Use get_json to get the full JSON data

    if client_id and data:
        print(f'Received data from {client_id}: {data}')

        if client_id not in data_:
            data_[client_id] = []
        data_[client_id].append(data)
        print(f'Parsed data: {data}')

        # Add client_id to clients dictionary
        clients[client_id] = True

        response = {"message": f"Data received from {client_id}"}
        return jsonify(response), 200
    else:
        return jsonify({"error": "Client ID and Data are required"}), 400

@app.route('/thermal_data/<client_id>', methods=['POST'])
def receive_thermal_data(client_id):
    data = request.get_json()  # Use get_json to get the full JSON data

    if client_id and data:
        print(f'Received thermal data from {client_id}: {data}')

        if client_id not in thermal_data_:
            thermal_data_[client_id] = []
        thermal_data_[client_id].append(data)
        print(f'Parsed thermal data: {data}')

        # Add client_id to clients dictionary
        clients[client_id] = True

        response = {"message": f"Thermal data received from {client_id}"}
        return jsonify(response), 200
    else:
        return jsonify({"error": "Client ID and Data are required"}), 400

@app.route('/clients', methods=['GET'])
def get_clients():
    return jsonify(list(clients.keys()))

@app.route('/data_show', methods=['GET'])
def get_data():
    return jsonify(data_)

@app.route('/thermal_data_show', methods=['GET'])
def get_thermal_data():
    return jsonify(thermal_data_)

@app.route('/update_threshold', methods=['POST'])
def update_threshold():
    global threshold_temp
    data = request.get_json()
    threshold_temp = data.get('threshold')
    return jsonify({"message": "Threshold updated", "threshold": threshold_temp}), 200

@app.route('/thermal_image/<client_id>', methods=['GET'])
def generate_thermal_image(client_id):
    global threshold_temp

    if client_id not in thermal_data_ or len(thermal_data_[client_id]) == 0:
        return jsonify({"error": "No thermal data available for this client"}), 400

    # Use the latest thermal data
    thermal_data = thermal_data_[client_id][-1]['pixels']
    thermal_matrix = np.array(thermal_data).reshape((8, 8))  # Adjust based on actual sensor resolution

    # Apply threshold if specified
    if threshold_temp is not None:
        thermal_matrix = np.where(thermal_matrix >= threshold_temp, thermal_matrix, np.nan)

    # Create heatmap
    plt.figure(figsize=(8, 8))
    plt.imshow(thermal_matrix, cmap='hot', interpolation='nearest')
    plt.colorbar()
    plt.title(f'Thermal Image for {client_id}')

    # Save the image to a BytesIO object
    img_io = io.BytesIO()
    plt.savefig(img_io, format='png')
    img_io.seek(0)
    plt.close()

    return send_file(img_io, mimetype='image/png')

@app.route('/live_stream')
def live_stream():
    def generate_frames():
        while True:
            start_time = time.time()
            
            # Get frame from ESP32-CAM stream
            frame = get_frame_from_stream(esp32_cam_url)
            if frame is None:
                print("Failed to capture image")
                continue

            # Resize the frame to the desired dimensions
            frame = cv2.resize(frame, (frame_width, frame_height))

            # Run YOLOv8 inference on the frame
            results = model(frame)

            # Filter results to detect persons only (class ID for person in COCO dataset is 0)
            person_detections = []
            for result in results:
                if hasattr(result, 'boxes'):
                    for box in result.boxes:
                        if int(box.cls) == 0:
                            person_detections.append(box)

            # Plot the filtered results
            if person_detections:
                for det in person_detections:
                    bbox = det.xyxy.cpu().numpy()[0]  # Bounding box coordinates
                    conf = det.conf.cpu().numpy()[0]  # Confidence score
                    label = model.names[int(det.cls.cpu().numpy()[0])]  # Class label
                    x1, y1, x2, y2 = map(int, bbox)  # Bounding box coordinates

                    # Draw the bounding box and label on the frame
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"{label} {conf:.2f}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

            # Encode the frame in JPEG format
            ret, buffer = cv2.imencode('.jpg', frame)
            frame = buffer.tobytes()

            # Yield the frame in multipart format
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

            # Calculate the time taken to process the frame
            elapsed_time = time.time() - start_time
            sleep_time = max(0, delay - elapsed_time)

            # Sleep to control the FPS
            time.sleep(sleep_time)

    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def get_frame_from_stream(url):
    try:
        resp = requests.get(url, timeout=5)
        img_arr = np.array(bytearray(resp.content), dtype=np.uint8)
        frame = cv2.imdecode(img_arr, -1)
        return frame
    except Exception as e:
        print(f"Failed to fetch frame: {e}")
        return None

if __name__ == '__main__':
    print("[starting] Flask server is starting....")
    app.run(host='0.0.0.0', port=5000,debug=True)
