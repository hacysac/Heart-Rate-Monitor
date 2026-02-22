from machine import Pin, SoftI2C
import asyncio
import aioble
import bluetooth
import struct
from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM
from time import ticks_ms, ticks_diff

# I2C and sensor setup
I2C_SDA = 4 #TODO
I2C_SCL = 5 #TODO
i2c = SoftI2C(sda=Pin(I2C_SDA), scl=Pin(I2C_SCL), freq=400000)
sensor = MAX30102(i2c=i2c)
sensor.setup_sensor()
sensor.set_sample_rate(400)
sensor.set_fifo_average(8)
sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)

# Buzzer setup
BUZZER_PIN = 0 #TODO
buzzer = Pin(BUZZER_PIN, Pin.OUT)
buzzer.value(0)

# Heart rate limits (update from app)
HR_MIN = 50
HR_MAX = 120

# Threshold for no finger detected based on ir values
NO_FINGER_THRESHOLD = 50000  # TODO

# BLE services
HR_SERVICE_UUID = bluetooth.UUID(0x180D)
HR_CHAR_UUID = bluetooth.UUID(0x2A37)

SPO2_SERVICE_UUID = bluetooth.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
SPO2_CHAR_UUID = bluetooth.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e")

THRESHOLD_SERVICE_UUID = bluetooth.UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e")
THRESHOLD_CHAR_UUID = bluetooth.UUID("6e400004-b5a3-f393-e0a9-e50e24dcca9e")

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

# handles threshold updates
async def threshold_task(threshold_char):
    global HR_MIN, HR_MAX

    while True:
        print("Waiting for connection...")
        async with await aioble.advertise(
            250_000,
            name="PicoW-HR",
            services=[HR_SERVICE_UUID, SPO2_SERVICE_UUID, THRESHOLD_SERVICE_UUID]
        ):
            print("Connected!")
            
            # Send current limits to phone on connect
            data = struct.pack("BB", HR_MIN, HR_MAX)
            threshold_char.write(data, send_update=True)
            
            # Now listen for threshold updates until disconnected
            while True:
                try:
                    # Wait up to 1 second for a write, then loop and check connection
                    _, data = await asyncio.wait_for(threshold_char.written(), timeout=1.0)
                    
                    if len(data) >= 2:
                        new_min = data[0]
                        new_max = data[1]
                        # check that found values are reasonable before updating
                        if 30 <= new_min <= 200 and 30 <= new_max <= 200 and new_min < new_max:
                            HR_MIN = new_min
                            HR_MAX = new_max
                            print(f"Updated limits: {HR_MIN}-{HR_MAX}")
                except asyncio.TimeoutError:
                    pass  # No write received, just loop back and check connection
                except Exception as e:
                    print(f"BLE error: {e}")
                    break
            
            print("Disconnected")

# Main sensor reading
async def sensor_task(hr_char, spo2_char):
    # Create monitor
    hr_monitor = HeartRateMonitor(sample_rate=100, window_size=50, smoothing_window=5)
    
    buzzer_on = False
    
    while True:
        try:
            # Check if sensor has data
            sensor.check()
            
            if sensor.available():
                # Remove old readings
                red = sensor.pop_red_from_storage()
                ir = sensor.pop_ir_from_storage()

                # Check for no finger condition
                if ir < NO_FINGER_THRESHOLD:
                    print("No finger detected")
                    buzzer_on = False  # Don't alert if no finger, just wait for valid readings
                    # reset monitor to not polute readings with false data
                    hr_monitor = HeartRateMonitor(
                        sample_rate=100,
                        window_size=50,
                        smoothing_window=5
                    )
                    await asyncio.sleep_ms(500)
                    continue #skip the rest of the loop and wait for next reading
                
                # Add samples to monitor (both IR and Red)
                hr_monitor.add_sample(ir, red)
                
                # Calculate heart rate and SpO2
                hr = hr_monitor.calculate_heart_rate()
                spo2 = hr_monitor.calculate_spo2()
                
                # Only send if readings are valid
                if hr is not None and spo2 is not None:
                    hr = int(hr)
                    print(f"HR: {hr} | SpO2: {spo2}%")
                    
                    # Send via BLE
                    hr_data = struct.pack("BB", 0x00, hr)
                    hr_char.write(hr_data, send_update=True)
                    spo2_data = struct.pack("B", spo2)
                    spo2_char.write(spo2_data, send_update=True)
                    
                    # Check if out of range
                    if hr < HR_MIN or hr > HR_MAX:
                        if not buzzer_on:
                            print(f"ALERT! HR: {hr}")
                            buzzer_on = True
                    else:
                        buzzer_on = False
            
            # Buzzer control
            if buzzer_on:
                buzzer.value(1)
                await asyncio.sleep_ms(200)
                buzzer.value(0)
                await asyncio.sleep_ms(200)
            else:
                buzzer.value(0)
                await asyncio.sleep_ms(50)

        # Catch errors     
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(1)

# Main code
async def main():
    # Setup BLE services
    hr_service = aioble.Service(HR_SERVICE_UUID)
    hr_char = aioble.Characteristic(hr_service, HR_CHAR_UUID, read=True, notify=True)
    
    spo2_service = aioble.Service(SPO2_SERVICE_UUID)
    spo2_char = aioble.Characteristic(spo2_service, SPO2_CHAR_UUID, read=True, notify=True)
    
    threshold_service = aioble.Service(THRESHOLD_SERVICE_UUID)
    threshold_char = aioble.Characteristic(threshold_service, THRESHOLD_CHAR_UUID, 
                                          read=True, write=True, notify=True)
    
    aioble.register_services(hr_service, spo2_service, threshold_service)
    
    # Run everything
    task1 = asyncio.create_task(threshold_task(threshold_char))
    task2 = asyncio.create_task(sensor_task(hr_char, spo2_char))
    
    # Async allows both tasks to run at the same time (more efficient)
    await asyncio.gather(task1, task2)

# run the full program until a keyboard interrupt
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("Stopped")
    buzzer.value(0)
