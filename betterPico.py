from machine import SoftI2C, Pin, PWM
import time
from utime import ticks_diff, ticks_us, ticks_ms
from time import sleep
import network
import urequests
import json
from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM


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

def current_datetime_iso():
    t = time.localtime()  # (year, month, day, hour, min, sec, weekday, yearday)
    return "{:04d}-{:02d}-{:02d}T{:02d}:{:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])

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
    return 50, 120  # fallback defaults

# main loop
def main():

    # Heart rate limits (update from app)
    hr_min, hr_max = get_settings()
    settings_timer = ticks_ms()

    # Threshold for no finger detected based on ir values
    no_finger_threshold = 2000  # TODO

    # I2C software instance
    i2c = SoftI2C(
        sda=Pin(18),  # Here, use your I2C SDA pin
        scl=Pin(17),  # Here, use your I2C SCL pin
        freq=400000,
    )  # Fast: 400kHz, slow: 100kHz

    # Sensor instance
    sensor = MAX30102(i2c=i2c)  # An I2C instance is required

    # Scan I2C bus to ensure that the sensor is connected
    if sensor.i2c_address not in i2c.scan():
        print("Sensor not found.")
        return
    elif not (sensor.check_part_id()):
        # Check that the targeted sensor is compatible
        print("I2C device ID not corresponding to MAX30102 or MAX30105.")
        return
    else:
        print("Sensor connected and recognized.")

    # Load the default configuration
    print("Setting up sensor with default configuration.", "\n")
    sensor.setup_sensor()

    # Set the sample rate to 400: 400 samples/s are collected by the sensor
    sensor_sample_rate = 400
    sensor.set_sample_rate(sensor_sample_rate)

    # Set the number of samples to be averaged per each reading
    sensor_fifo_average = 8
    sensor.set_fifo_average(sensor_fifo_average)

    # Set LED brightness to a medium value
    sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)

    # Expected acquisition rate: 400 Hz / 8 = 50 Hz
    actual_acquisition_rate = int(sensor_sample_rate / sensor_fifo_average)

    # Buzzer setup
    buzzer = PWM(Pin(15))
    buzzer.freq(1000)   # TODO: tone frequency
    buzzer.duty_u16(0)  # start off
    buzzer_on = False

    sleep(1)

    print(
        "Starting data acquisition from RED & IR registers...",
        "press Ctrl+C to stop.",
        "\n",
    )
    sleep(1)

    # Initialize the heart rate monitor
    hr_monitor = HeartRateMonitor(
        # Select a sample rate that matches the sensor's acquisition rate
        sample_rate=actual_acquisition_rate,
        # Select a significant window size to calculate the heart rate (2-5 seconds)
        window_size=int(actual_acquisition_rate * 3),
    )

    # Setup to calculate the heart rate every 2 seconds
    hr_compute_interval = 2  # seconds
    ref_time = ticks_ms()  # Reference time

    while True:
        # The check() method has to be continuously polled, to check if
        # there are new readings into the sensor's FIFO queue. When new
        # readings are available, this function will put them into the storage.
        sensor.check()

        # Check if the storage contains available samples
        if sensor.available():
            # Access the storage FIFO and gather the readings (integers)
            red_reading = sensor.pop_red_from_storage()
            ir_reading = sensor.pop_ir_from_storage()

            # Check for no finger condition
            if ir_reading < no_finger_threshold:
                print("No finger detected")
                buzzer_on = False  # Don't alert if no finger
                
                # reset monitor to not polute readings with false data: TODO
                hr_monitor = HeartRateMonitor(sample_rate=actual_acquisition_rate, window_size=int(actual_acquisition_rate * 3), smoothing_window=5)
                
                time.sleep(0.5) # wait 0.5 seconds before next reading
                continue #skip the rest of the loop and wait for next reading

            # Add the IR reading to the heart rate monitor
            # Note: based on the skin color, the red, IR or green LED can be used
            # to calculate the heart rate with more accuracy.
            hr_monitor.add_sample(ir_reading, red_reading)

        # Periodically calculate the heart rate every `hr_compute_interval` seconds
        if ticks_diff(ticks_ms(), ref_time) / 1000 > hr_compute_interval:
            # Calculate the heart rate
            heart_rate = hr_monitor.calculate_heart_rate()
            spo2 = hr_monitor.calculate_spo2()
            if heart_rate is not None and spo2 is not None:
                heart_rate = int(heart_rate)
                print("Heart Rate: {:.0f} BPM".format(heart_rate))
                print("SpO2: {}%".format(spo2))
                send_data(heart_rate, spo2)  # Send data to Airtable
                
                # Check if out of range
                if heart_rate < hr_min or heart_rate > hr_max:
                    if not buzzer_on:
                        print(f"ALERT! HR: {heart_rate}")
                        buzzer_on = True
                else:
                    buzzer_on = False
            else:
                print("No valid reading.")
            # Reset the reference time
            ref_time = ticks_ms()

        # Buzzer control
        if buzzer_on:
            buzzer.duty_u16(32768) # TODO
            time.sleep(0.2) # buzzer on for 0.2 seconds
            buzzer.duty_u16(0) # off
            time.sleep(0.2) # buzzer off for 0.2 seconds
        else:
            buzzer.duty_u16(0) # buzzer off
            time.sleep(0.05) # wait 0.05 seconds before next reading

        if ticks_diff(ticks_ms(), settings_timer) / 1000 > 60:
            hr_min, hr_max = get_settings()
            settings_timer = ticks_ms()

main() # run the main loop
