/*
 * XIAO nRF52840 Sense — high-rate 6-axis capture
 *
 * Streams accel + gyro at the LSM6DS3's 416Hz preset, with a millisecond
 * timestamp, in CSV format over USB Serial (CDC — baud setting is cosmetic).
 *
 * Output:  t_ms,ax,ay,az,gx,gy,gz
 *  - ax/ay/az in g  (±16g range — handles real golf impacts)
 *  - gx/gy/gz in dps (±2000 dps range — handles swing rotation)
 *
 * Capture from host:
 *   arduino-cli.exe monitor -p COM6 -c baudrate=115200 --quiet > capture.csv
 */
#include "LSM6DS3.h"
#include "Wire.h"

LSM6DS3 imu(I2C_MODE, 0x6A);

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000) { }

  // Configure for impact-capable sampling BEFORE imu.begin()
  imu.settings.accelSampleRate = 416;   // Hz
  imu.settings.accelRange = 16;         // ±16g
  imu.settings.gyroSampleRate = 416;    // Hz
  imu.settings.gyroRange = 2000;        // ±2000 dps

  if (imu.begin() != 0) {
    Serial.println("# ERR: IMU init failed");
    while (1) { delay(1000); }
  }

  // CSV header
  Serial.println("t_ms,ax,ay,az,gx,gy,gz");
}

void loop() {
  unsigned long t = millis();

  float ax = imu.readFloatAccelX();
  float ay = imu.readFloatAccelY();
  float az = imu.readFloatAccelZ();
  float gx = imu.readFloatGyroX();
  float gy = imu.readFloatGyroY();
  float gz = imu.readFloatGyroZ();

  // One line per sample; no delay, run as fast as the IMU + USB allow
  Serial.print(t);       Serial.print(",");
  Serial.print(ax, 3);   Serial.print(",");
  Serial.print(ay, 3);   Serial.print(",");
  Serial.print(az, 3);   Serial.print(",");
  Serial.print(gx, 1);   Serial.print(",");
  Serial.print(gy, 1);   Serial.print(",");
  Serial.println(gz, 1);
}
