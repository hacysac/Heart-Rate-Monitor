#include <Wire.h> //IC2 connection
#include "MAX30105.h" //Heart sensor

//Bluetoth Low Energy (BLE)
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

// unique BLE ids, generate at uuidgenerator.net
#define SERVICE_UUID "12345678-1234-5678-1234-56789abcdef0"
#define CHAR_UUID "12345678-1234-5678-1234-56789abcdef1"

MAX30105 sensor; // Sensor object
BLECharacteristic* pCharacteristic; // BLE data channel
bool deviceConnected = false; // Connection status

class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("Connected!");
    }

    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("Disonnected!");
    }
};

// runs once at startup
void setup() {

  // start serial messaging for debugging
  Serial.begin(115200);
  delay(1000); // 1 second delay
  Serial.println("-Start!-");
  
  // initialize the sensor pins
  Wire.begin(4,5); //defines xiao specific pins
  
  if (!sensor.begin(Wire, I2C_SPEED_FAST)){
    Serial.println("ERROR: Sensor not found");
    while(1);
  }
  sensor.setup();
  
  // BLE setup
  BLEDevice::init("HeartSensor"); //Names the wrist device as "Heart Sensor"
  BLEServer* pServer = BLEDevice::createServer(); //
  pServer->setCallbacks(new MyServerCallbacks());
  BLEService* pService = pServer->createService(SERVICE_UUID);
  pCharacteristic = pService->createCharacteristic(
      CHAR_UUID, //unique id
      BLECharacteristic::PROPERTY_NOTIFY // allow notifications
  );
  pCharacteristic->addDescriptor(new BLE2902());
  pService->start();

  //start advertising data
  BLEAdvertising* pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  BLEDevice::startAdvertising();

  Serial.println("BLE setup complete, advertising as 'Heart Sensor'");
}

// runs continuously
void loop() {
  
  // sensor reading
  uint32_t red = sensor.getRed(); // red value
  uint32_t ir = sensor.getIR(); // ir value
  
  //send on BLE
  if (deviceConnected) {
    
    // sensor values are 32-bit (4 bytes) but BLE reads 8-bit (1 byte)
    // convert sensor values to 8-bit bytes stores in a data list 
    
    // Create 8-byte array
    uint8_t data[8];
    
    // Put red value into bytes 0-3 to be red by BLE
    data[0] = (red >> 24) & 0xFF;  // Highest byte
    data[1] = (red >> 16) & 0xFF;
    data[2] = (red >> 8) & 0xFF;
    data[3] = red & 0xFF;          // Lowest byte
    
    // Put IR value into bytes 4-7 to be red by BLE
    data[4] = (ir >> 24) & 0xFF;   // Highest byte
    data[5] = (ir >> 16) & 0xFF;
    data[6] = (ir >> 8) & 0xFF;
    data[7] = ir & 0xFF;           // Lowest byte
    
    // Send on BLE
    pCharacteristic->setValue(data, 8);
    pCharacteristic->notify();
    
    // Debug output
    Serial.print("Sent Red: ");
    Serial.print(red);
    Serial.print(" & IR: ");
    Serial.println(ir);
    
  } else {
    // No connection - just print
    Serial.print("Waiting for connection | Red: ");
    Serial.print(red);
    Serial.print(" | IR: ");
    Serial.println(ir);
  }
  
  delay(10);  // 10ms delay
}