/*
 * XIAO nRF52840 Sense — IMU smoke test (verbose / diagnostic)
 *
 * Adds boot-time prints and re-prints the init error every second so
 * we can see exactly where it gets stuck if anything fails.
 */
#include "LSM6DS3.h"
#include "Wire.h"

LSM6DS3 imu(I2C_MODE, 0x6A);   // primary address
bool imu_ok = false;

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000) { }

  Serial.println();
  Serial.println("===========================");
  Serial.println("XIAO Sense IMU diagnostic");
  Serial.println("===========================");
  Serial.println("Step 1: Serial up.");

  Serial.print("Step 2: Calling imu.begin() at 0x6A ... ");
  int r = imu.begin();
  Serial.print("returned ");
  Serial.println(r);

  if (r == 0) {
    imu_ok = true;
    Serial.println("Step 3: IMU OK — streaming ax,ay,az (g)");
    Serial.println("ax_g,ay_g,az_g");
  } else {
    Serial.println("Step 3: IMU FAILED. Will keep retrying every second...");
  }
}

void loop() {
  if (imu_ok) {
    float ax = imu.readFloatAccelX();
    float ay = imu.readFloatAccelY();
    float az = imu.readFloatAccelZ();
    Serial.print(ax, 3); Serial.print(",");
    Serial.print(ay, 3); Serial.print(",");
    Serial.println(az, 3);
    delay(10);
  } else {
    // Keep error visible + retry at the other I2C address some boards use
    Serial.print("RETRY imu.begin(0x6A)=");
    Serial.print(imu.begin());
    LSM6DS3 alt(I2C_MODE, 0x6B);
    Serial.print("  imu.begin(0x6B)=");
    Serial.println(alt.begin());
    delay(1000);
  }
}
