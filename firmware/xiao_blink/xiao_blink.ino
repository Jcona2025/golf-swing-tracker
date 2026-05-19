/*
 * XIAO nRF52840 Sense — battery test
 * Blinks the user LED every 500ms so we can see if the board is alive
 * on battery alone (active LOW: LOW = ON, HIGH = OFF).
 */
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
}

void loop() {
  digitalWrite(LED_BUILTIN, LOW);   // ON
  delay(500);
  digitalWrite(LED_BUILTIN, HIGH);  // OFF
  delay(500);
}
