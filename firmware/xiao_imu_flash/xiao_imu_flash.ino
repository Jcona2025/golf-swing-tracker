/*
 * XIAO nRF52840 Sense — flash-logging IMU recorder
 *
 * Records IMU at ~50Hz to the onboard 2MB QSPI flash for unattended
 * use during a P&P round. No BLE, no phone, no laptop required while
 * recording. After the round, plug into USB and run the dump command.
 *
 * Layout:
 *   Sector 0:        metadata (magic + sectors_used)
 *   Sectors 1..511:  IMU data (256 samples × 16 bytes per sector)
 *   Total capacity:  ~130k samples → ~43 min @ 50Hz
 *
 * Sample (16 bytes, little-endian):
 *   uint32  t_ms
 *   int16   ax raw   (±16g range)
 *   int16   ay raw
 *   int16   az raw
 *   int16   gx raw   (±2000 dps range)
 *   int16   gy raw
 *   int16   gz raw
 *
 * Serial protocol (115200 baud):
 *   On boot, sketch waits 3s for a one-character command, then:
 *     'd'  — dump all stored samples as CSV, then go idle
 *     'e'  — erase all data
 *     'l'  — explicitly enter logging mode
 *   No command in 3s → logging mode (so battery-only boots just log)
 *
 * LED:
 *   Fast blink during 3s startup window
 *   Solid ON while logging
 *   Slow blink while dumping
 *   OFF when idle or full
 */
#include "Adafruit_SPIFlash.h"
#include "LSM6DS3.h"
#include "Wire.h"

Adafruit_FlashTransport_QSPI flashTransport;
Adafruit_SPIFlash flash(&flashTransport);

LSM6DS3 imu(I2C_MODE, 0x6A);

constexpr uint32_t SECTOR_SIZE        = 4096;
constexpr uint32_t TOTAL_SECTORS      = 512;            // 2MB / 4KB
constexpr uint32_t DATA_SECTORS       = TOTAL_SECTORS - 1;
constexpr uint32_t SAMPLE_SIZE        = 16;
constexpr uint32_t SAMPLES_PER_SECTOR = SECTOR_SIZE / SAMPLE_SIZE;  // 256
constexpr uint32_t MAGIC              = 0x4C4F4753;     // 'LOGS'

struct Metadata {
  uint32_t magic;
  uint32_t sectorsUsed;
};

uint8_t  ramBuffer[SECTOR_SIZE];
uint32_t ramSampleIdx    = 0;
uint32_t sectorsUsed     = 0;

const float ACCEL_SCALE = 16.0f   / 32768.0f;
const float GYRO_SCALE  = 2000.0f / 32768.0f;

enum Mode { MODE_IDLE, MODE_LOGGING, MODE_DUMPING };
Mode currentMode = MODE_IDLE;

void writeMetadata() {
  Metadata meta = { MAGIC, sectorsUsed };
  flash.eraseSector(0);
  flash.writeBuffer(0, (uint8_t*)&meta, sizeof(meta));
}

void readMetadata() {
  Metadata meta = {0, 0};
  flash.readBuffer(0, (uint8_t*)&meta, sizeof(meta));
  if (meta.magic == MAGIC) sectorsUsed = meta.sectorsUsed;
  else                     sectorsUsed = 0;
}

void eraseAll() {
  sectorsUsed = 0;
  writeMetadata();
}

void enterDumpMode() {
  digitalWrite(LED_BUILTIN, HIGH);
  Serial.print("# samples="); Serial.println((uint32_t)sectorsUsed * SAMPLES_PER_SECTOR);
  Serial.println("t_ms,ax_g,ay_g,az_g,gx_dps,gy_dps,gz_dps");
  for (uint32_t s = 0; s < sectorsUsed; s++) {
    uint32_t addr = (s + 1) * SECTOR_SIZE;
    flash.readBuffer(addr, ramBuffer, SECTOR_SIZE);
    for (uint32_t i = 0; i < SAMPLES_PER_SECTOR; i++) {
      uint8_t* p = ramBuffer + i * SAMPLE_SIZE;
      uint32_t t; int16_t ax,ay,az,gx,gy,gz;
      memcpy(&t,  p+0, 4);
      memcpy(&ax, p+4, 2); memcpy(&ay, p+6, 2); memcpy(&az, p+8, 2);
      memcpy(&gx, p+10,2); memcpy(&gy, p+12,2); memcpy(&gz, p+14,2);
      Serial.print(t); Serial.print(',');
      Serial.print(ax * ACCEL_SCALE, 4); Serial.print(',');
      Serial.print(ay * ACCEL_SCALE, 4); Serial.print(',');
      Serial.print(az * ACCEL_SCALE, 4); Serial.print(',');
      Serial.print(gx * GYRO_SCALE,  2); Serial.print(',');
      Serial.print(gy * GYRO_SCALE,  2); Serial.print(',');
      Serial.println(gz * GYRO_SCALE, 2);
    }
    // Heartbeat LED so user sees progress
    digitalWrite(LED_BUILTIN, (s % 2) ? LOW : HIGH);
  }
  Serial.println("# END_DUMP");
  digitalWrite(LED_BUILTIN, HIGH);
  currentMode = MODE_IDLE;
}

void setup() {
  Serial.begin(115200);
  pinMode(LED_BUILTIN, OUTPUT);
  digitalWrite(LED_BUILTIN, HIGH);  // off

  // IMU
  imu.settings.accelSampleRate = 416;
  imu.settings.accelRange      = 16;
  imu.settings.gyroSampleRate  = 416;
  imu.settings.gyroRange       = 2000;
  imu.begin();

  // QSPI flash
  if (!flash.begin()) {
    Serial.println("# ERR: flash init failed");
  }

  readMetadata();
  Serial.print("# boot, sectors used: "); Serial.println(sectorsUsed);
  Serial.println("# send 'd' to dump, 'e' to erase, or wait 3s to start logging");

  // 3-second command window with fast blink
  uint32_t start = millis();
  while (millis() - start < 3000) {
    digitalWrite(LED_BUILTIN, ((millis() / 100) % 2) ? HIGH : LOW);
    if (Serial.available()) {
      char c = Serial.read();
      if (c == 'd') { enterDumpMode(); return; }
      if (c == 'e') { eraseAll(); Serial.println("# erased"); currentMode = MODE_IDLE; return; }
      if (c == 'l') { currentMode = MODE_LOGGING; break; }
    }
  }
  if (currentMode == MODE_IDLE) currentMode = MODE_LOGGING;

  if (currentMode == MODE_LOGGING) {
    digitalWrite(LED_BUILTIN, LOW);   // solid on while logging
    Serial.println("# logging");
  }
}

void loop() {
  // Always accept commands — including during logging, so dump can be
  // triggered from a host script without needing a reset.
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'd') {
      // Flush partial RAM buffer to flash before dumping, so no samples lost
      if (ramSampleIdx > 0 && sectorsUsed < DATA_SECTORS) {
        uint32_t flashAddr = (sectorsUsed + 1) * SECTOR_SIZE;
        flash.eraseSector(flashAddr / SECTOR_SIZE);
        flash.writeBuffer(flashAddr, ramBuffer, SECTOR_SIZE);
        sectorsUsed++;
        writeMetadata();
        ramSampleIdx = 0;
      }
      currentMode = MODE_IDLE;
      enterDumpMode();
      return;
    }
    if (c == 'e') {
      currentMode = MODE_IDLE;
      eraseAll();
      Serial.println("# erased");
      digitalWrite(LED_BUILTIN, HIGH);
      return;
    }
    if (c == 'l') {
      currentMode = MODE_LOGGING;
      digitalWrite(LED_BUILTIN, LOW);
      Serial.println("# logging");
    }
  }

  if (currentMode != MODE_LOGGING) {
    delay(50);
    return;
  }

  // Flash full?
  if (sectorsUsed >= DATA_SECTORS) {
    Serial.println("# flash full");
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

  // Flush if buffer full
  if (ramSampleIdx >= SAMPLES_PER_SECTOR) {
    uint32_t flashAddr = (sectorsUsed + 1) * SECTOR_SIZE;
    flash.eraseSector(flashAddr / SECTOR_SIZE);
    flash.writeBuffer(flashAddr, ramBuffer, SECTOR_SIZE);
    sectorsUsed++;
    writeMetadata();
    ramSampleIdx = 0;
  }

  delay(20);  // ~50Hz
}
