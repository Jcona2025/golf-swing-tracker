/*
 * XIAO nRF52840 Sense — BLE IMU streaming v2
 *
 * Improvements over v1:
 *   - Larger MTU (247 vs default 23) lets us pack multiple samples per notify
 *   - 5 samples per packet (80 bytes) — fewer notifications, more throughput
 *   - Faster BLE connection interval (target 7.5-15ms) — Windows may negotiate higher
 *   - Sampling loop at ~100Hz (every 10ms)
 *
 * Packet format — 80 bytes, 5 samples × 16 bytes:
 *   Sample N (16 bytes, little-endian):
 *     uint32  t_ms       — millis() timestamp
 *     int16   ax raw     — accel X (±16g)
 *     int16   ay raw
 *     int16   az raw
 *     int16   gx raw     — gyro X  (±2000 dps)
 *     int16   gy raw
 *     int16   gz raw
 *
 * Host scaling:
 *   accel_g  = raw * 16   / 32768.0
 *   gyro_dps = raw * 2000 / 32768.0
 */
#include <bluefruit.h>
#include "LSM6DS3.h"
#include "Wire.h"

const uint8_t SVC_UUID[16] = {
  0x4F,0x4D,0x53,0x42, 0x73, 0x65, 0x6E, 0x73,
  0x01, 0x00, 0x6C, 0x69, 0x6E, 0x65, 0x62, 0x61
};
const uint8_t IMU_UUID[16] = {
  0x4F,0x4D,0x53,0x42, 0x73, 0x65, 0x6E, 0x73,
  0x02, 0x00, 0x6C, 0x69, 0x6E, 0x65, 0x62, 0x61
};

BLEService        swingSvc(SVC_UUID);
BLECharacteristic imuChr(IMU_UUID);
BLEBas            batteryServ;

LSM6DS3 imu(I2C_MODE, 0x6A);

constexpr int SAMPLES_PER_PACKET = 5;
constexpr int SAMPLE_SIZE_BYTES  = 16;
constexpr int PACKET_SIZE_BYTES  = SAMPLES_PER_PACKET * SAMPLE_SIZE_BYTES;  // 80
uint8_t packetBuf[PACKET_SIZE_BYTES];
int     sampleIdx = 0;

bool isConnected = false;

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);   // OFF (active low)

  imu.settings.accelSampleRate = 416;
  imu.settings.accelRange      = 16;
  imu.settings.gyroSampleRate  = 416;
  imu.settings.gyroRange       = 2000;
  if (imu.begin() != 0) { Serial.println("ERR: IMU init"); }
  else                  { Serial.println("IMU OK");          }

  // ---- BLE config for high throughput ----
  // Args: att_mtu, event_length, hvn_qsize (notify queue), wrcmd_qsize
  // 247 MTU comfortably fits an 80-byte payload + ATT overhead
  Bluefruit.configPrphConn(247, BLE_GAP_EVENT_LENGTH_DEFAULT, 16, 3);
  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.setName("SwingLogger");
  // Request fast connection interval: 7.5ms - 15ms (units of 1.25ms)
  // Windows often refuses < 15ms; firmware just asks, host decides.
  Bluefruit.Periph.setConnInterval(6, 12);
  Bluefruit.Periph.setConnectCallback(onConnect);
  Bluefruit.Periph.setDisconnectCallback(onDisconnect);

  // Service + characteristic
  swingSvc.begin();
  imuChr.setProperties(CHR_PROPS_NOTIFY);
  imuChr.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  imuChr.setMaxLen(PACKET_SIZE_BYTES);   // 80 bytes (was 16 in v1)
  imuChr.begin();

  batteryServ.begin();
  batteryServ.write(80);

  Bluefruit.Advertising.addFlags(BLE_GAP_ADV_FLAGS_LE_ONLY_GENERAL_DISC_MODE);
  Bluefruit.Advertising.addTxPower();
  Bluefruit.Advertising.addService(swingSvc);
  Bluefruit.Advertising.addName();
  Bluefruit.Advertising.restartOnDisconnect(true);
  Bluefruit.Advertising.setInterval(32, 244);
  Bluefruit.Advertising.setFastTimeout(30);
  Bluefruit.Advertising.start(0);
  Serial.println("BLE advertising as 'SwingLogger' (v2 batched)");
}

void onConnect(uint16_t conn_handle) {
  isConnected = true;
  sampleIdx = 0;
  digitalWrite(LED_BUILTIN, LOW);  // solid ON
  Serial.println("BLE connected");

  // Try to negotiate the larger MTU explicitly
  BLEConnection* conn = Bluefruit.Connection(conn_handle);
  if (conn) {
    conn->requestMtuExchange(247);
    conn->requestConnectionParameter(12);   // 15ms
  }
}

void onDisconnect(uint16_t conn_handle, uint8_t reason) {
  isConnected = false;
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.print("BLE disconnected, reason 0x");
  Serial.println(reason, HEX);
}

void appendSample() {
  uint32_t t = millis();
  int16_t ax = imu.readRawAccelX();
  int16_t ay = imu.readRawAccelY();
  int16_t az = imu.readRawAccelZ();
  int16_t gx = imu.readRawGyroX();
  int16_t gy = imu.readRawGyroY();
  int16_t gz = imu.readRawGyroZ();

  uint8_t* p = packetBuf + sampleIdx * SAMPLE_SIZE_BYTES;
  memcpy(p + 0,  &t,  4);
  memcpy(p + 4,  &ax, 2);
  memcpy(p + 6,  &ay, 2);
  memcpy(p + 8,  &az, 2);
  memcpy(p + 10, &gx, 2);
  memcpy(p + 12, &gy, 2);
  memcpy(p + 14, &gz, 2);
  sampleIdx++;
}

void loop() {
  if (isConnected) {
    appendSample();
    if (sampleIdx >= SAMPLES_PER_PACKET) {
      imuChr.notify(packetBuf, PACKET_SIZE_BYTES);
      sampleIdx = 0;
    }
    delay(10);  // 100Hz sampling
  } else {
    // Heartbeat blink while waiting
    digitalWrite(LED_BUILTIN, LOW);
    delay(100);
    digitalWrite(LED_BUILTIN, HIGH);
    delay(900);
  }
}
