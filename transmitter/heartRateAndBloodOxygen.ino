#include <Wire.h>
#include "MAX30105.h"
#include "spo2_algorithm.h"  // Maxim's HR and SpO2 algorithms

// BLE Libraries
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// unique BLE ids, generate at uuidgenerator.net
#define SERVICE_UUID "12345678-1234-5678-1234-56789abcdef0"
#define CHAR_UUID    "12345678-1234-5678-1234-56789abcdef1"

BLECharacteristic* pCharacteristic = NULL;
bool deviceConnected = false;
MAX30105 particleSensor;

#define MAX_BRIGHTNESS 255

// ESP32-C3 has enough memory for 32-bit samples
uint32_t irBuffer[100]; // Infrared LED sensor data
uint32_t redBuffer[100]; // Red LED sensor data

int32_t bufferLength; // Data length
int32_t spo2; // SpO2 value
int8_t validSPO2; // Indicator if SPO2 is valid
int32_t heartRate; // Heart rate value
int8_t validHeartRate; // Indicator if HR is valid

// Alert pin for vibration/buzzer
#define ALERT_PIN 2
#define HR_THRESHOLD_HIGH 100
#define HR_THRESHOLD_LOW 50

// BLE callbacks to handle connection events
class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("Connected via BLE!");
    }

    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("Disconnected from BLE!");
    }
};

//BLE setup
void setupBLE() {
  Serial.println("\nInitializing BLE...");
  
  // Create BLE Device
  BLEDevice::init("HeartSensor");
  Serial.println("BLE device: 'HeartSensor'");
  
  // Create BLE Server
  BLEServer *pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());
  Serial.println("Server created");
  
  // Create BLE Service
  BLEService *pService = pServer->createService(SERVICE_UUID);
  Serial.println("Service created");
  
  // Create BLE Characteristic
  pCharacteristic = pService->createCharacteristic(
      CHAR_UUID,
      BLECharacteristic::PROPERTY_READ |
      BLECharacteristic::PROPERTY_NOTIFY
  );
  
  // Add descriptor for notifications
  pCharacteristic->addDescriptor(new BLE2902());
  Serial.println("Characteristic created");
  
  // Start the service
  pService->start();
  Serial.println("Service started");
  
  // Start advertising
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(false);
  BLEDevice::startAdvertising();
  Serial.println("Advertising started");
  
  Serial.println("BLE setup complete!\n");
}

//send BLE data
void sendBLEData(int32_t hr, int32_t spo2) {
  if (!deviceConnected) return;  // Only send if connected
  
  // HR and SpO2 into 8 bytes
  uint8_t data[8];
  
  // Heart Rate (bytes 0-3)
  data[0] = (hr >> 24) & 0xFF;
  data[1] = (hr >> 16) & 0xFF;
  data[2] = (hr >> 8) & 0xFF;
  data[3] = hr & 0xFF;
  
  // SpO2 (bytes 4-7)
  data[4] = (spo2 >> 24) & 0xFF;
  data[5] = (spo2 >> 16) & 0xFF;
  data[6] = (spo2 >> 8) & 0xFF;
  data[7] = spo2 & 0xFF;
  
  // Send via BLE
  pCharacteristic->setValue(data, 8);
  pCharacteristic->notify();
}

// Check heart rate and trigger alerts
void checkAndAlert(int32_t hr) {
  if (hr > HR_THRESHOLD_HIGH) {
    // High heart rate - triple buzz
    for (int i = 0; i < 3; i++) {
      digitalWrite(ALERT_PIN, HIGH);
      delay(100);
      digitalWrite(ALERT_PIN, LOW);
      delay(100);
    }
    Serial.println("ALERT: High heart rate!");
  }
  else if (hr < HR_THRESHOLD_LOW && hr > 0) {
    // Low heart rate - double buzz
    for (int i = 0; i < 2; i++) {
      digitalWrite(ALERT_PIN, HIGH);
      delay(300);
      digitalWrite(ALERT_PIN, LOW);
      delay(300);
    }
    Serial.println("ALERT: Low heart rate!");
  }
}

//runs one on initialization
void setup()
{
  Serial.begin(115200);
  delay(1000);
  
  Serial.println("XIAO Smart Wristband - Starting");

  // Initialize alert pin (for vibration motor or buzzer)
  pinMode(ALERT_PIN, OUTPUT);
  digitalWrite(ALERT_PIN, LOW);
  Serial.println("Alert pin initialized (GP2)");

  // Initialize I2C on XIAO-specific pins
  Wire.begin(4, 5);  // SDA=GP4, SCL=GP5
  Serial.println("I2C initialized (SDA=GP4, SCL=GP5)");

  // Initialize MAX30102 sensor
  Serial.println("\nInitializing MAX30102 sensor...");
  if (!particleSensor.begin(Wire, I2C_SPEED_FAST))
  {
    Serial.println("ERROR: MAX30102 not found!");
    while (1);  // Stop here
  }
  Serial.println("MAX30102 found!");

  Serial.println("Attach sensor to finger with rubber band");

  Serial.read();

  // Configure sensor
  byte ledBrightness = 60; // Options: 0=Off to 255=50mA
  byte sampleAverage = 4; // Options: 1, 2, 4, 8, 16, 32
  byte ledMode = 2; // Options: 1=Red, 2=Red+IR, 3=Red+IR+Green
  byte sampleRate = 100; // Options: 50, 100, 200, 400, 800, 1000, 1600, 3200
  int pulseWidth = 411; // Options: 69, 118, 215, 411
  int adcRange = 4096; // Options: 2048, 4096, 8192, 16384

  particleSensor.setup(ledBrightness, sampleAverage, ledMode, sampleRate, pulseWidth, adcRange);
  Serial.println("Sensor configured");
  
  // Setup BLE
  setupBLE();
  
  Serial.println("READY! Collecting data: ");
}

//main loop
void loop()
{
  bufferLength = 100; // Buffer stores 4 seconds at 25sps

  //find first 100 values(buffer fill)
  Serial.println("Collecting initial 100 samples...");
  for (byte i = 0 ; i < bufferLength ; i++)
  {
    while (particleSensor.available() == false)
      particleSensor.check();

    redBuffer[i] = particleSensor.getRed();
    irBuffer[i] = particleSensor.getIR();
    particleSensor.nextSample();

    Serial.print(F("red="));
    Serial.print(redBuffer[i], DEC);
    Serial.print(F(", ir="));
    Serial.println(irBuffer[i], DEC);
  }

  //calc heart rate and SpO2 from 100 samples
  Serial.println("\nCalculating heart rate and SpO2...\n");
  maxim_heart_rate_and_oxygen_saturation(irBuffer, bufferLength, redBuffer, &spo2, &validSPO2, &heartRate, &validHeartRate);

  //continuous data collection
  while (1)
  {
    // Shift buffer: dump first 25 samples, move last 75 to top
    for (byte i = 25; i < 100; i++)
    {
      redBuffer[i - 25] = redBuffer[i];
      irBuffer[i - 25] = irBuffer[i];
    }

    // Take 25 new samples
    for (byte i = 75; i < 100; i++)
    {
      while (particleSensor.available() == false)
        particleSensor.check();

      redBuffer[i] = particleSensor.getRed();
      irBuffer[i] = particleSensor.getIR();
      particleSensor.nextSample();

      // Print samples
      Serial.print(F("red="));
      Serial.print(redBuffer[i], DEC);
      Serial.print(F(", ir="));
      Serial.print(irBuffer[i], DEC);

      Serial.print(F(", HR="));
      Serial.print(heartRate, DEC);

      Serial.print(F(", HRvalid="));
      Serial.print(validHeartRate, DEC);

      Serial.print(F(", SPO2="));
      Serial.print(spo2, DEC);

      Serial.print(F(", SPO2Valid="));
      Serial.print(validSPO2, DEC);
      
      //check BLE connection status
      Serial.print(F(", BLE="));
      Serial.println(deviceConnected ? F("Connected") : F("Disconnected"));
    }

    //recalc heart rate and SpO2
    maxim_heart_rate_and_oxygen_saturation(irBuffer, bufferLength, redBuffer, &spo2, &validSPO2, &heartRate, &validHeartRate);
    
    // send BLE data if valid
    if (validHeartRate && validSPO2) {
      sendBLEData(heartRate, spo2);
      
      Serial.print("\n📱 Sent to phone → HR: ");
      Serial.print(heartRate);
      Serial.print(" BPM | SpO2: ");
      Serial.print(spo2);
      Serial.println("%\n");
    }
    
    // Check heart rate for alerts
    if (validHeartRate) {
      checkAndAlert(heartRate);
    }
  }
}
