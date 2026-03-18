import network
import urequests
import time
import json
from machine import Pin

# WIFI SETTINGS
SSID = "Galaxy A33 5GD612"
PASSWORD = "wnra0297"

# AIRTABLE SETTINGS
BASE_ID = "appDlLYVrXfd9nmKj"
TOKEN = "patGz4JcukRlR4LvJ.4dfda0a68e64d255546261075196ebf4af726ee167081dbfe18ae59e6e7c14a8"

MAIN_URL = "https://api.airtable.com/v0/" + BASE_ID + "/data"
SETTINGS_URL = "https://api.airtable.com/v0/" + BASE_ID + "/settings"

headers = {
    "Authorization": "Bearer " + TOKEN,
    "Content-Type": "application/json"
}

# Connect to WiFi
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(SSID, PASSWORD)

print("Connecting to WiFi...")

while not wifi.isconnected():
    time.sleep(1)

print("Connected!")
print(wifi.ifconfig())

def current_datetime_iso():
    t = time.localtime()
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])

# Age midpoints for 220 - age formula
AGE_MIDPOINTS = {
    "18-25": 21, "26-35": 30, "36-45": 40,
    "46-55": 50, "56-65": 60, "65+": 68
}

# Activity zones as % of max HR (min, max)
ACTIVITY_ZONES = {
    "sedentary":   (0.50, 0.60),
    "light":       (0.55, 0.65),
    "moderate":    (0.60, 0.75),
    "active":      (0.70, 0.85),
    "very_active": (0.80, 0.95)
}

def calc_min_max(age_range, activity_level):
    age = AGE_MIDPOINTS.get(age_range, 40)        # default age 40
    zone = ACTIVITY_ZONES.get(activity_level, (0.60, 0.75))  # default activity moderate
    max_hr = 220 - age
    min_bpm = int(max_hr * zone[0])
    max_bpm = int(max_hr * zone[1])
    return min_bpm, max_bpm

def fetch_settings():
    try:
        response = urequests.get(SETTINGS_URL, headers=headers)
        data = json.loads(response.text)
        response.close()
        if data["records"]:
            fields = data["records"][0]["fields"]
            age_range = fields.get("Age", "36-45")
            activity_level = fields.get("Activity", "moderate")
            min_bpm, max_bpm = calc_min_max(age_range, activity_level)
            print("Age range:", age_range, "| Activity:", activity_level)
            print("Calculated - Min BPM:", min_bpm, "Max BPM:", max_bpm)
            return min_bpm, max_bpm
    except Exception as e:
        print("Error fetching settings:", e)
    return 60, 100  # fallback defaults

# Function to send data
def send_data(bpm, spo2):

    data = {
        "records": [
            {
                "fields": {
                    "BPM": bpm,
                    "SpO2": spo2,
                    "Timestamp": current_datetime_iso()
                }
            }
        ]
    }

    try:
        response = urequests.post(MAIN_URL, headers=headers, data=json.dumps(data))
        print("Sent:", bpm, spo2)
        print(response.text)
        response.close()

    except Exception as e:
        print("Error sending data:", e)


# Fetch settings once at startup, then re-check every 60 seconds
min_bpm, max_bpm = fetch_settings()
settings_timer = 0

# Example loop (replace bpm/spo2 with sensor readings)
while True:

    bpm = 72      # replace with MAX30102 bpm
    spo2 = 98     # replace with MAX30102 SpO2

    # Re-fetch settings every 60 seconds in case user updated them
    if settings_timer >= 60:
        min_bpm, max_bpm = fetch_settings()
        settings_timer = 0

    # Check if BPM is outside the target range
    if bpm < min_bpm:
        print("WARNING: BPM too low!", bpm, "< min", min_bpm)
    elif bpm > max_bpm:
        print("WARNING: BPM too high!", bpm, "> max", max_bpm)
    else:
        print("BPM in range:", bpm, "(", min_bpm, "-", max_bpm, ")")

    send_data(bpm, spo2)

    time.sleep(10)
    settings_timer += 10