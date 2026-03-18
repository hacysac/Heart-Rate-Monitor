from machine import Pin, SoftI2C, PWM
from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM
from time import ticks_ms, ticks_diff, time
import network
import urequests
import json

# Wifi settings
wifi_name = "Galaxy A33 5GD612" #TODO: hotspot
wifi_password = "wnra0297" #TODO: hotspot

# Airtable settings
api_token = "patGz4JcukRlR4LvJ.4dfda0a68e64d255546261075196ebf4af726ee167081dbfe18ae59e6e7c14a8"
data_url = "https://api.airtable.com/v0/appDlLYVrXfd9nmKj/data"
settings_url = "https://api.airtable.com/v0/appDlLYVrXfd9nmKj/settings"

headers = {
    "Authorization": "Bearer " + api_token,
    "Content-Type": "application/json"
}

# Connect to WiFi
wifi = network.WLAN(network.STA_IF)
wifi.active(True)
wifi.connect(wifi_name, wifi_password)

#wait until wifi connects (will freeze here until connection is successful)
while not wifi.isconnected():
    time.sleep(1)


# I2C and sensor setup
I2C_SDA = 18 #TODO gpio pin
I2C_SCL = 17 #TODO gpio pin
i2c = SoftI2C(sda=Pin(I2C_SDA), scl=Pin(I2C_SCL), freq=400000)
sensor = MAX30102(i2c=i2c)
i2c.scan()
sensor.setup_sensor()
sensor.set_sample_rate(400)
sensor.set_fifo_average(8)
sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)

# Buzzer setup
BUZZER_PIN = 15 #TODO gpio pin
buzzer = PWM(Pin(BUZZER_PIN))
buzzer.freq(1000)   # TODO: tone frequency
buzzer.duty_u16(0)  # start off

# Heart rate limits (update from app)
hr_min = 50
hr_max = 120

# Threshold for no finger detected based on ir values
no_finger_threshold = 2000  # TODO

# Class to handle heart rate and SpO2 calculations
class HeartRateMonitor:
    
    def __init__(self, sample_rate=100, window_size=10, smoothing_window=5):
        self.sample_rate = sample_rate
        self.window_size = window_size
        self.smoothing_window = smoothing_window
        self.samples = []
        self.timestamps = []
        self.filtered_samples = []
        self.red_buffer = []
        
    def add_sample(self, ir, red):
        timestamp = ticks_ms()
        self.samples.append(ir)
        self.timestamps.append(timestamp)
        self.red_buffer.append(red)
        
        # Apply smoothing
        if len(self.samples) >= self.smoothing_window:
            smoothed_sample = (
                sum(self.samples[-self.smoothing_window :]) / self.smoothing_window
            )
            self.filtered_samples.append(smoothed_sample)
        else:
            self.filtered_samples.append(ir)
        
        # Remove last entry if exceeding window size
        if len(self.samples) > self.window_size:
            self.samples.pop(0)
            self.timestamps.pop(0)
            self.filtered_samples.pop(0)
            self.red_buffer.pop(0)
            
    def find_peaks(self):
        peaks = []
        if len(self.filtered_samples) < 3:  # Need at least three samples to find a peak
            return peaks
        
        # Calculate dynamic threshold based on the min and max of the recent window of filtered samples
        recent_samples = self.filtered_samples[-self.window_size :]
        min_val = min(recent_samples)
        max_val = max(recent_samples)
        threshold = (
            min_val + (max_val - min_val) * 0.5
        )  # 50% between min and max as a threshold
        
        for i in range(1, len(self.filtered_samples) - 1):
            if (
                self.filtered_samples[i] > threshold
                and self.filtered_samples[i - 1] < self.filtered_samples[i]
                and self.filtered_samples[i] > self.filtered_samples[i + 1]
            ):
                peak_time = self.timestamps[i]
                peaks.append((peak_time, self.filtered_samples[i]))
        
        return peaks
    
    def calculate_heart_rate(self):
        peaks = self.find_peaks()
        if len(peaks) < 2:
            return None  # Not enough peaks to calculate heart rate
        
        # Calculate the average interval between peaks in milliseconds
        intervals = []
        for i in range(1, len(peaks)):
            interval = ticks_diff(peaks[i][0], peaks[i - 1][0])
            intervals.append(interval)
        
        average_interval = sum(intervals) / len(intervals)
        
        # Convert intervals to heart rate in beats per minute (BPM)
        heart_rate = (
            60000 / average_interval
        )  # 60 seconds per minute * 1000 ms per second
        
        return heart_rate
    
    def calculate_spo2(self):
        if len(self.red_buffer) < 10 or len(self.samples) < 10:
            return None
        
        # Calculate AC (peak-to-peak amplitude)
        red_ac = max(self.red_buffer) - min(self.red_buffer)
        ir_ac = max(self.samples) - min(self.samples)
        
        # Calculate DC (average)
        red_dc = sum(self.red_buffer) / len(self.red_buffer)
        ir_dc = sum(self.samples) / len(self.samples)
        
        # Calculate R ratio
        if ir_dc != 0 and red_dc != 0 and ir_ac != 0:
            R = (red_ac / red_dc) / (ir_ac / ir_dc)
            # Empirical formula for SpO2
            spo2 = 110 - 25 * R
            
            # Clamp to valid range
            if spo2 < 70:
                spo2 = 70
            elif spo2 > 100:
                spo2 = 100
            
            return int(spo2)
        
        return None
    
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
        response = urequests.post(data_url, headers=headers, data=json.dumps(data))
        print("Sent:", bpm, spo2)
        print(response.text)
        response.close()

    except:
        print("Error sending data")

def current_datetime_iso():
    t = time.localtime()  # (year, month, day, hour, min, sec, weekday, yearday)
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])

# Age midpoints for 220 - age formula
age_ranges = {
    "18-25": 21, "26-35": 30, "36-45": 40,
    "46-55": 50, "56-65": 60, "65+": 68
}

# Activity zones as % of max HR (min, max)
activity_zones = {
    "sedentary":   (0.50, 0.60),
    "light":       (0.55, 0.65),
    "moderate":    (0.60, 0.75),
    "active":      (0.70, 0.85),
    "very_active": (0.80, 0.95)
}

def calc_min_max(age_range, activity_level):
    age = age_ranges.get(age_range, 40)        # default age 40
    zone = activity_zones.get(activity_level, (0.60, 0.75))  # default activity moderate
    max_hr = 220 - age
    min_bpm = int(max_hr * zone[0])
    max_bpm = int(max_hr * zone[1])
    return min_bpm, max_bpm

def get_settings():
    try:
        response = urequests.get(settings_url, headers=headers)
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
    except:
        print("Error geting settings")
    return 60, 100  # fallback defaults

# Create monitor
hr_monitor = HeartRateMonitor(sample_rate=100, window_size=200, smoothing_window=5) #TODO

buzzer_on = False

# Get settings once at startup, then re-check every 60 seconds
hr_min, hr_max = get_settings()
settings_timer = 0

# Main loop
while True:
    try:

         # Get settings every 60 seconds in case user updated them
        if settings_timer >= 60:
            hr_min, hr_max = get_settings()
            settings_timer = 0

        # Check if sensor has data
        sensor.check()
        
        if sensor.available():
            # Remove old readings
            red = sensor.pop_red_from_storage()
            ir = sensor.pop_ir_from_storage()

            # Check for no finger condition
            if ir < no_finger_threshold:
                print("No finger detected")
                buzzer_on = False  # Don't alert if no finger
                
                # reset monitor to not polute readings with false data
                hr_monitor = HeartRateMonitor(
                    sample_rate=100,
                    window_size=200, #TODO
                    smoothing_window=5
                )
                time.sleep(0.5) # wait 0.5 seconds before next reading
                continue #skip the rest of the loop and wait for next reading
            
            # Add samples to monitor (both IR and Red)
            hr_monitor.add_sample(ir, red)
            
            # Calculate heart rate and SpO2
            hr = hr_monitor.calculate_heart_rate()
            spo2 = hr_monitor.calculate_spo2()
            
            # Only send or alert if readings are valid
            if hr is not None and spo2 is not None:
                hr = int(hr)
                print(f"HR: {hr} | SpO2: {spo2}%")

                send_data(hr, spo2)  # Send data to Airtable
                
                # Check if out of range
                if hr < hr_min or hr > hr_max:
                    if not buzzer_on:
                        print(f"ALERT! HR: {hr}")
                        buzzer_on = True
                else:
                    buzzer_on = False
        
        # Buzzer control
        if buzzer_on:
            buzzer.duty_u16(32768) # TODO
            time.sleep(0.2) # buzzer on for 0.2 seconds
            buzzer.duty_u16(0) # off
            time.sleep(0.2) # buzzer off for 0.2 seconds
        else:
            buzzer.duty_u16(0) # buzzer off
            time.sleep(0.05) # wait 0.05 seconds before next reading

        time.sleep(10)
        settings_timer += 10

    # Catch errors     
    except:
        print(f"Error")
        time.sleep(1) # wait for 1 second after error before trying again
