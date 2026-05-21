/*
 * XIAO nRF52840 Sense — flash-logging IMU recorder (internal flash, v2)
 *
 * Switches storage from QSPI (Adafruit_SPIFlash) to the nRF52's internal
 * flash via Adafruit_LittleFS. The QSPI path had a silent failure mode on
 * battery-only operation (data lost on USB plug-cycle). Internal flash
 * shares the MCU's own voltage rail so it's reliable wherever the chip
 * itself is running.
 *
 * Tradeoff: smaller capacity. Internal LittleFS partition is ~250-700KB
 * on the Adafruit nRF52 bootloader (varies). At 50Hz × 16B/sample we get
 * roughly 5-15 minutes of continuous data. Enough for a putting session
 * or a short P&P round. For longer sessions we'd add an SD card later.
 *
 * Sample (16 bytes, little-endian):
 *   uint32  t_ms
 *   int16   ax raw   (±16g)
 *   int16   ay raw
 *   int16   az raw
 *   int16   gx raw   (±2000 dps)
 *   int16   gy raw
 *   int16   gz raw
 *
 * Serial protocol (115200 baud):
 *   'd'  — dump /log.bin contents as CSV
 *   'e'  — delete /log.bin (erase)
 *   'l'  — explicitly start logging
 *   's'  — status (mode + file size)
 *   No command in 3s after boot → logging mode
 *
 * LED:
 *   Fast blink during 3s startup window
 *   Solid ON while logging
 *   Slow blink while dumping
 *   OFF when idle
 */
#include <Adafruit_LittleFS.h>
#include <InternalFileSystem.h>
#include "LSM6DS3.h"
#include "Wire.h"

using namespace Adafruit_LittleFS_Namespace;

LSM6DS3 imu(I2C_MODE, 0x6A);

const char* LOG_PATH = "/log.bin";

constexpr uint32_t SAMPLE_SIZE       = 16;
constexpr uint32_t FLUSH_EVERY_SAMPS = 64;   // close+reopen every 64 samples (~1.3s @ 50Hz)
constexpr uint32_t MAX_FILE_BYTES    = 250 * 1024;  // cap to avoid filling fs (~15 min @ 50Hz × 16B)

uint8_t  ramBuffer[FLUSH_EVERY_SAMPS * SAMPLE_SIZE];
uint32_t ramSampleIdx = 0;
uint32_t totalBytesWritten = 0;

const float ACCEL_SCALE = 16.0f   / 32768.0f;
const float GYRO_SCALE  = 2000.0f / 32768.0f;

enum Mode { MODE_IDLE, MODE_LOGGING, MODE_DUMPING };
Mode currentMode = MODE_IDLE;

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
  f.seek(f.size());  // append
  uint32_t bytes = ramSampleIdx * SAMPLE_SIZE;
  f.write(ramBuffer, bytes);
  f.close();
  totalBytesWritten += bytes;
  ramSampleIdx = 0;
}

void enterDumpMode() {
  digitalWrite(LED_BUILTIN, HIGH);
  flushBuffer();
  uint32_t sz = fileSizeBytes();
  uint32_t n = sz / SAMPLE_SIZE;
  Serial.print("# samples="); Serial.println(n);
  Serial.println("t_ms,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps");
  File f = InternalFS.open(LOG_PATH, FILE_O_READ);
  if (!f) { Serial.println("# no log file"); Serial.println("# END_DUMP"); return; }

  uint8_t buf[SAMPLE_SIZE];
  uint32_t printed = 0;
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
    printed++;
    if (printed % 256 == 0) digitalWrite(LED_BUILTIN, (printed/256) % 2 ? HIGH : LOW);
  }
  f.close();
  Serial.println("# END_DUMP");
  digitalWrite(LED_BUILTIN, HIGH);
  currentMode = MODE_IDLE;
}

void eraseLog() {
  InternalFS.remove(LOG_PATH);
  totalBytesWritten = 0;
  ramSampleIdx = 0;
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

  // LittleFS on internal flash
  if (!InternalFS.begin()) {
    Serial.println("# ERR: InternalFS.begin() failed");
  }

  totalBytesWritten = fileSizeBytes();
  Serial.print("# boot, existing log bytes: "); Serial.println(totalBytesWritten);
  Serial.println("# send 'd' dump, 'e' erase, 'l' log, 's' status — or wait 3s to start logging");

  // 3-second command window with fast blink
  uint32_t start = millis();
  while (millis() - start < 3000) {
    digitalWrite(LED_BUILTIN, ((millis() / 100) % 2) ? HIGH : LOW);
    if (Serial.available()) {
      char c = Serial.read();
      if (c == 'd') { enterDumpMode(); return; }
      if (c == 'e') { eraseLog(); Serial.println("# erased"); currentMode = MODE_IDLE; return; }
      if (c == 'l') { currentMode = MODE_LOGGING; break; }
      if (c == 's') {
        Serial.print("# status: mode="); Serial.print(currentMode);
        Serial.print(" bytes="); Serial.println(fileSizeBytes());
      }
    }
  }
  if (currentMode == MODE_IDLE) currentMode = MODE_LOGGING;

  if (currentMode == MODE_LOGGING) {
    digitalWrite(LED_BUILTIN, LOW);
    Serial.println("# logging");
  }
}

void loop() {
  // Always accept commands
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'd') { currentMode = MODE_IDLE; enterDumpMode(); return; }
    if (c == 'e') { currentMode = MODE_IDLE; eraseLog(); Serial.println("# erased"); digitalWrite(LED_BUILTIN, HIGH); return; }
    if (c == 'l') { currentMode = MODE_LOGGING; digitalWrite(LED_BUILTIN, LOW); Serial.println("# logging"); }
    if (c == 's') {
      Serial.print("# status: mode="); Serial.print(currentMode);
      Serial.print(" bytes="); Serial.print(fileSizeBytes());
      Serial.print(" ramIdx="); Serial.println(ramSampleIdx);
    }
  }

  if (currentMode != MODE_LOGGING) {
    delay(50);
    return;
  }

  if (totalBytesWritten + ramSampleIdx * SAMPLE_SIZE >= MAX_FILE_BYTES) {
    Serial.println("# log full, stopping");
    flushBuffer();
    currentMode = MODE_IDLE;
    digitalWrite(LED_BUILTIN, HIGH);
    return;
  }

  // Capture one sample
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
  }

  delay(20);  // ~50Hz
}
