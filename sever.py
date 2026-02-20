from flask import Flask, render_template, request, jsonify, send_file
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
import io

app = Flask(__name__)

# Setup database
def setup_db():
    conn = sqlite3.connect('heart_rate.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS readings
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  device_id TEXT,
                  timestamp INTEGER,
                  heart_rate INTEGER,
                  spo2 INTEGER,
                  min_hr INTEGER,
                  max_hr INTEGER,
                  is_normal INTEGER)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (device_id TEXT PRIMARY KEY,
                  age_range TEXT,
                  activity_level TEXT,
                  min_hr INTEGER,
                  max_hr INTEGER)''')
    conn.commit()
    conn.close()

setup_db()

@app.route('/')
def home():
    return render_template('index.html')

# Calculate min/max heart rate
@app.route('/api/calculate', methods=['POST'])
def calculate():
    data = request.json
    age = data['ageRange']
    activity = data['activityLevel']
    
    # Get average age
    ages = {'18-25': 21, '26-35': 30, '36-45': 40, '46-55': 50, '56-65': 60, '66+': 70}
    avg_age = ages[age]
    
    # Calculate max HR
    max_hr = 220 - avg_age
    
    # Calculate min HR
    activity_percent = {'sedentary': 0.50, 'light': 0.60, 'moderate': 0.65, 'active': 0.70, 'athlete': 0.75}
    min_hr = round(max_hr * activity_percent[activity])
    
    return jsonify({'minHR': min_hr, 'maxHR': max_hr})

# Save reading to database
@app.route('/api/reading', methods=['POST'])
def save_reading():
    data = request.json
    
    conn = sqlite3.connect('heart_rate.db')
    c = conn.cursor()
    c.execute('INSERT INTO readings (device_id, timestamp, heart_rate, spo2, min_hr, max_hr, is_normal) VALUES (?, ?, ?, ?, ?, ?, ?)',
              (data['deviceId'], data['timestamp'], data['heartRate'], data['spo2'], data['minHR'], data['maxHR'], data['isNormal']))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'ok'})

# Get statistics
@app.route('/api/stats/<device_id>')
def stats(device_id):
    conn = sqlite3.connect('heart_rate.db')
    df = pd.read_sql_query("SELECT * FROM readings WHERE device_id = ?", conn, params=(device_id,))
    conn.close()
    
    if len(df) == 0:
        return jsonify({'totalReadings': 0, 'avgHR': 0, 'avgSpO2': 0, 'alerts': 0})
    
    alerts = len(df[df['is_normal'] == 0])
    
    return jsonify({
        'totalReadings': len(df),
        'avgHR': int(df['heart_rate'].mean()),
        'avgSpO2': int(df['spo2'].mean()),
        'alerts': alerts
    })

# Save settings
@app.route('/api/settings', methods=['POST'])
def save_settings():
    data = request.json
    
    conn = sqlite3.connect('heart_rate.db')
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO settings VALUES (?, ?, ?, ?, ?)',
              (data['deviceId'], data['ageRange'], data['activityLevel'], data['minHR'], data['maxHR']))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'ok'})

# Get settings
@app.route('/api/settings/<device_id>')
def get_settings(device_id):
    conn = sqlite3.connect('heart_rate.db')
    c = conn.cursor()
    c.execute('SELECT * FROM settings WHERE device_id = ?', (device_id,))
    row = c.fetchone()
    conn.close()
    
    if row:
        return jsonify({'settings': {'ageRange': row[1], 'activityLevel': row[2], 'minHR': row[3], 'maxHR': row[4]}})
    return jsonify({'settings': None})

# Export CSV
@app.route('/api/export/<device_id>')
def export(device_id):
    conn = sqlite3.connect('heart_rate.db')
    df = pd.read_sql_query("SELECT * FROM readings WHERE device_id = ?", conn, params=(device_id,))
    conn.close()
    
    if len(df) == 0:
        return "No data", 404
    
    df['Timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df['Status'] = df['is_normal'].apply(lambda x: 'Normal' if x else 'Alert')
    
    csv = df[['Timestamp', 'heart_rate', 'spo2', 'min_hr', 'max_hr', 'Status']].to_csv(index=False)
    
    return csv, 200, {'Content-Type': 'text/csv', 'Content-Disposition': 'attachment; filename=data.csv'}

# Generate graph
@app.route('/api/graph/<device_id>/<metric>/<timerange>')
def graph(device_id, metric, timerange):
    conn = sqlite3.connect('heart_rate.db')
    df = pd.read_sql_query("SELECT * FROM readings WHERE device_id = ?", conn, params=(device_id,))
    conn.close()
    
    if len(df) == 0:
        return "No data", 404
    
    df['Timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    
    # Filter by time
    now = datetime.now()
    if timerange == 'day':
        start = now - timedelta(days=1)
    elif timerange == 'month':
        start = now - timedelta(days=30)
    else:
        start = now - timedelta(days=365)
    
    df = df[df['Timestamp'] >= start]
    
    if len(df) == 0:
        return "No data", 404
    
    # Make graph
    fig, ax = plt.subplots(figsize=(10, 5))
    
    if metric == 'hr':
        ax.plot(df['Timestamp'], df['heart_rate'], color='#667eea', linewidth=2, label='Heart Rate')
        ax.axhline(y=df['max_hr'].iloc[0], color='red', linestyle='--', label=f"Max ({df['max_hr'].iloc[0]} bpm)")
        ax.axhline(y=df['min_hr'].iloc[0], color='orange', linestyle='--', label=f"Min ({df['min_hr'].iloc[0]} bpm)")
        ax.set_ylabel('Heart Rate (bpm)')
        ax.set_title(f'Heart Rate - Last {timerange}')
    else:
        ax.plot(df['Timestamp'], df['spo2'], color='green', linewidth=2, label='SpO2')
        ax.axhline(y=95, color='orange', linestyle='--', label='Normal (95%)')
        ax.set_ylabel('SpO2 (%)')
        ax.set_title(f'SpO2 - Last {timerange}')
        ax.set_ylim(90, 100)
    
    ax.set_xlabel('Time')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # Format time axis
    if timerange == 'day':
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    elif timerange == 'month':
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    else:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))
    
    plt.xticks(rotation=45)
    plt.tight_layout()
    
    # Return image
    img = io.BytesIO()
    plt.savefig(img, format='png', dpi=100)
    img.seek(0)
    plt.close()
    
    return send_file(img, mimetype='image/png')

# Clear data
@app.route('/api/clear/<device_id>', methods=['DELETE'])
def clear(device_id):
    conn = sqlite3.connect('heart_rate.db')
    c = conn.cursor()
    c.execute('DELETE FROM readings WHERE device_id = ?', (device_id,))
    c.execute('DELETE FROM settings WHERE device_id = ?', (device_id,))
    conn.commit()
    conn.close()
    
    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    print("Server running at http://localhost:5000")
    app.run(debug=True, port=5000)