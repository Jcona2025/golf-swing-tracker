/*
 * XIAO nRF52840 Sense — flash-logging + BLE control (v3)
 *
 * Combines the v2 internal-flash logger with a tiny BLE control service.
 * The phone acts as a remote "start" button: connect via nRF Connect (or a
 * future custom app), write one byte to the command characteristic, and
 * the sensor begins logging to flash. The phone can disconnect immediately;
 * logging continues autonomously off battery.
 *
 * BLE service (advertised as "Swing"):
 *   Service UUID:     6162656e-696c-0001-736e-657342534d4f
 *   Command char:     6162656e-696c-0003-...  (write, 1 byte)
 *     'l' (0x6C) — start logging
 *     's' (0x73) — stop logging
 *     'e' (0x65) — erase /log.bin
 *   Status char:      6162656e-696c-0004-...  (notify, 8 bytes)
 *     [0]   mode (0=IDLE, 1=LOGGING)
 *     [4..7] file size in bytes (uint32 LE)
 *
 * Same USB Serial commands as v2 (d/e/l/s) for laptop offload.
 *
 * After upload, default state on boot is IDLE so the sensor doesn't
 * eat its flash budget on the drive to the course. Phone or USB
 * triggers logging explicitly.
 */
#include <bluefruit.h>
#include <Adafruit_LittleFS.h>
#include <InternalFileSystem.h>
#include "LSM6DS3.h"
#include "Wire.h"

using namespace Adafruit_LittleFS_Namespace;

LSM6DS3 imu(I2C_MODE, 0x6A);

const char* LOG_PATH = "/log.bin";

constexpr uint32_t SAMPLE_SIZE       = 16;
constexpr uint32_t FLUSH_EVERY_SAMPS = 64;
constexpr uint32_t MAX_FILE_BYTES    = 250 * 1024;

uint8_t  ramBuffer[FLUSH_EVERY_SAMPS * SAMPLE_SIZE];
uint32_t ramSampleIdx = 0;
uint32_t totalBytesWritten = 0;

const float ACCEL_SCALE = 16.0f   / 32768.0f;
const float GYRO_SCALE  = 2000.0f / 32768.0f;

enum Mode { MODE_IDLE, MODE_LOGGING, MODE_DUMPING };
volatile Mode currentMode = MODE_IDLE;

// BLE UUIDs (little-endian byte order for Bluefruit)
const uint8_t SVC_UUID[16]    = { 0x4F,0x4D,0x53,0x42, 0x73,0x65,0x6E,0x73, 0x01,0x00, 0x6C,0x69,0x6E,0x65,0x62,0x61 };
const uint8_t CTRL_UUID[16]   = { 0x4F,0x4D,0x53,0x42, 0x73,0x65,0x6E,0x73, 0x03,0x00, 0x6C,0x69,0x6E,0x65,0x62,0x61 };
const uint8_t STATUS_UUID[16] = { 0x4F,0x4D,0x53,0x42, 0x73,0x65,0x6E,0x73, 0x04,0x00, 0x6C,0x69,0x6E,0x65,0x62,0x61 };

BLEService        swingSvc(SVC_UUID);
BLECharacteristic ctrlChr(CTRL_UUID);
BLECharacteristic statusChr(STATUS_UUID);
BLEBas            batteryServ;

// ===== Flash helpers =====
uint32_t fileSizeBytes() {
  File f = InternalFS.open(LOG_PATH, FILE_O_READ);
  if (!f) return 0;
  uint32_t sz = f.size();
  f.close();
  return sz;
}

void flushBuffer() {
  if (ramSampleIdx == 0) return;
  File f = InternalFS.open(LOG_PATH, FILE_O_WRITE);
  if (!f) return;
  f.seek(f.size());
  uint32_t bytes = ramSampleIdx * SAMPLE_SIZE;
  f.write(ramBuffer, bytes);
  f.close();
  totalBytesWritten += bytes;
  ramSampleIdx = 0;
}

void eraseLog() {
  InternalFS.remove(LOG_PATH);
  totalBytesWritten = 0;
  ramSampleIdx = 0;
}

void pushStatus() {
  uint8_t buf[8] = {0};
  buf[0] = (uint8_t)currentMode;
  uint32_t sz = totalBytesWritten + ramSampleIdx * SAMPLE_SIZE;
  memcpy(buf + 4, &sz, 4);
  if (Bluefruit.connected()) statusChr.notify(buf, sizeof(buf));
  statusChr.write(buf, sizeof(buf));   // also stored for readers
}

void startLogging() {
  currentMode = MODE_LOGGING;
  digitalWrite(LED_BUILTIN, LOW);
  Serial.println("# logging");
  pushStatus();
}

void stopLogging() {
  currentMode = MODE_IDLE;
  flushBuffer();
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.println("# stopped");
  pushStatus();
}

// ===== USB Serial dump =====
void enterDumpMode() {
  flushBuffer();
  uint32_t sz = fileSizeBytes();
  uint32_t n = sz / SAMPLE_SIZE;
  Serial.print("# samples="); Serial.println(n);
  Serial.println("t_ms,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps");
  File f = InternalFS.open(LOG_PATH, FILE_O_READ);
  if (!f) { Serial.println("# no log file"); Serial.println("# END_DUMP"); return; }
  uint8_t buf[SAMPLE_SIZE];
  while (f.available() >= (int)SAMPLE_SIZE) {
    f.read(buf, SAMPLE_SIZE);
    uint32_t t; int16_t ax,ay,az,gx,gy,gz;
    memcpy(&t,  buf+0, 4);
    memcpy(&ax, buf+4, 2); memcpy(&ay, buf+6, 2); memcpy(&az, buf+8, 2);
    memcpy(&gx, buf+10,2); memcpy(&gy, buf+12,2); memcpy(&gz, buf+14,2);
    Serial.print(t); Serial.print(',');
    Serial.print(ax * ACCEL_SCALE, 4); Serial.print(',');
    Serial.print(ay * ACCEL_SCALE, 4); Serial.print(',');
    Serial.print(az * ACCEL_SCALE, 4); Serial.print(',');
    Serial.print(gx * GYRO_SCALE,  2); Serial.print(',');
    Serial.print(gy * GYRO_SCALE,  2); Serial.print(',');
    Serial.println(gz * GYRO_SCALE, 2);
  }
  f.close();
  Serial.println("# END_DUMP");
}

// ===== BLE callbacks =====
void onCtrlWrite(uint16_t conn_handle, BLECharacteristic* chr, uint8_t* data, uint16_t len) {
  if (len < 1) return;
  char c = (char)data[0];
  if      (c == 'l') startLogging();
  else if (c == 's') stopLogging();
  else if (c == 'e') {
    if (currentMode == MODE_LOGGING) stopLogging();
    eraseLog();
    Serial.println("# erased (via BLE)");
    pushStatus();
  }
}

void onConnect(uint16_t conn_handle) {
  Serial.println("BLE connected");
  pushStatus();
}
void onDisconnect(uint16_t conn_handle, uint8_t reason) {
  Serial.print("BLE disconnected, reason 0x"); Serial.println(reason, HEX);
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);

  // IMU
  imu.settings.accelSampleRate = 416;
  imu.settings.accelRange      = 16;
  imu.settings.gyroSampleRate  = 416;
  imu.settings.gyroRange       = 2000;
  imu.begin();

  // LittleFS
  if (!InternalFS.begin()) Serial.println("# ERR: InternalFS");
  totalBytesWritten = fileSizeBytes();
  Serial.print("# boot, existing log bytes: "); Serial.println(totalBytesWritten);

  // BLE
  Bluefruit.begin();
  Bluefruit.setTxPower(4);
  Bluefruit.setName("SwingLogger");
  Bluefruit.Periph.setConnectCallback(onConnect);
  Bluefruit.Periph.setDisconnectCallback(onDisconnect);

  swingSvc.begin();
  ctrlChr.setProperties(CHR_PROPS_WRITE | CHR_PROPS_WRITE_WO_RESP);
  ctrlChr.setPermission(SECMODE_OPEN, SECMODE_OPEN);
  ctrlChr.setMaxLen(1);
  ctrlChr.setWriteCallback(onCtrlWrite);
  ctrlChr.begin();

  statusChr.setProperties(CHR_PROPS_READ | CHR_PROPS_NOTIFY);
  statusChr.setPermission(SECMODE_OPEN, SECMODE_NO_ACCESS);
  statusChr.setMaxLen(8);
  statusChr.begin();
  pushStatus();

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

  Serial.println("# Ready. IDLE on boot. BLE write 'l' to start, or USB 'l'.");
}

void loop() {
  // USB Serial commands (laptop side)
  if (Serial.available()) {
    char c = Serial.read();
    if      (c == 'd') { stopLogging(); enterDumpMode(); }
    else if (c == 'e') { stopLogging(); eraseLog(); Serial.println("# erased"); pushStatus(); }
    else if (c == 'l') { startLogging(); }
    else if (c == 's') {
      Serial.print("# status: mode="); Serial.print(currentMode);
      Serial.print(" bytes="); Serial.print(fileSizeBytes());
      Serial.print(" ramIdx="); Serial.println(ramSampleIdx);
    }
  }

  if (currentMode != MODE_LOGGING) {
    // Heartbeat blink while idle (advertising)
    digitalWrite(LED_BUILTIN, ((millis() / 1000) % 2) ? LOW : HIGH);
    delay(50);
    return;
  }

  if (totalBytesWritten + ramSampleIdx * SAMPLE_SIZE >= MAX_FILE_BYTES) {
    Serial.println("# log full");
    stopLogging();
    return;
  }

  uint32_t t  = millis();
  int16_t ax = imu.readRawAccelX();
  int16_t ay = imu.readRawAccelY();
  int16_t az = imu.readRawAccelZ();
  int16_t gx = imu.readRawGyroX();
  int16_t gy = imu.readRawGyroY();
  int16_t gz = imu.readRawGyroZ();

  uint8_t* p = ramBuffer + ramSampleIdx * SAMPLE_SIZE;
  memcpy(p + 0,  &t,  4);
  memcpy(p + 4,  &ax, 2);
  memcpy(p + 6,  &ay, 2);
  memcpy(p + 8,  &az, 2);
  memcpy(p + 10, &gx, 2);
  memcpy(p + 12, &gy, 2);
  memcpy(p + 14, &gz, 2);
  ramSampleIdx++;

  if (ramSampleIdx >= FLUSH_EVERY_SAMPS) {
    flushBuffer();
    pushStatus();   // periodic status push
  }

  delay(20);  // ~50Hz target
}
