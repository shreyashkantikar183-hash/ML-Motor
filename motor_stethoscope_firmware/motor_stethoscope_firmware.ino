/*
  motor_stethoscope_firmware.ino
  Multimodal Motor Digital Stethoscope — ESP32 firmware

  Reads 6 sensor channels, runs the on-device Random Forest classifier
  (motor_model.h, exported from train_model.py) and streams results over
  USB serial in the format both collect_real_data.py and dashboard_live.py
  expect:

      DATA,temperature,vibration_rms,current_rms,voltage,acoustic_level,rpm,condition

  Feature order MUST match train_model.py's FEATURES list exactly:
      temperature, vibration_rms, current_rms, voltage, acoustic_level, rpm

  --------------------------------------------------------------------------
  ASSUMED HARDWARE (edit the pin map / calibration constants below if yours
  differs — nothing here depends on exact sensor brand except the library
  calls noted per sensor):

    Temperature   : DS18B20 (OneWire digital)             -> GPIO 4
    Vibration     : ADXL345 accelerometer (I2C)            -> SDA/SCL (I2C default)
    Current       : ACS712 hall-effect current sensor (analog) -> GPIO 34
    Voltage       : resistor-divider onto motor supply rail (analog) -> GPIO 35
    Sound/acoustic: KY-038 (or similar) sound sensor, analog envelope out -> GPIO 32
    Speed (RPM)   : IR slot sensor or Hall proximity sensor,
                    one pulse per revolution, digital interrupt -> GPIO 27

  Libraries needed (Arduino Library Manager):
    - OneWire
    - DallasTemperature
    - (Wire.h is built in, used for the ADXL345 over I2C)
  --------------------------------------------------------------------------
*/
#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "motor_model.h"

using namespace Eloquent::ML::Port;
RandomForest model;

// ---------------------------------------------------------------
// Pin map — change these to match your actual wiring
// ---------------------------------------------------------------
#define PIN_TEMP_ONEWIRE   4
#define PIN_CURRENT_ADC    34
#define PIN_VOLTAGE_ADC    35
#define PIN_SOUND_ADC      32
#define PIN_SPEED_PULSE    27

const uint8_t ADXL345_ADDR = 0x53;

// ---------------------------------------------------------------
// Calibration constants — adjust to your actual sensors/wiring
// ---------------------------------------------------------------
// ACS712: 66 mV/A for the 30A variant, 100 mV/A for 20A, 185 mV/A for 5A.
const float ACS712_SENSITIVITY_V_PER_A = 0.066;   // 30A module default
const float ADC_VREF = 3.3;
const int   ADC_MAX_COUNTS = 4095;                // 12-bit ADC on ESP32

// Voltage divider onto the motor supply rail: Vin -- R1 --+-- R2 -- GND
// ADC reads the node between R1 and R2.
const float VOLTAGE_DIVIDER_R1 = 30000.0;  // ohms
const float VOLTAGE_DIVIDER_R2 = 7500.0;   // ohms

// Speed sensor: pulses generated per full shaft revolution
// (1 for a single slot/marker, more if using a multi-tooth encoder wheel)
const int PULSES_PER_REV = 1;

// Sampling windows
const int   VIBRATION_SAMPLES = 100;   // accel samples per RMS window
const int   CURRENT_SAMPLES = 200;     // ADC samples per RMS window (covers >1 AC cycle)
const int   SOUND_SAMPLES = 200;       // ADC samples for acoustic envelope
const unsigned long RPM_WINDOW_MS = 1000; // measure pulses over this window

// ---------------------------------------------------------------
// Globals
// ---------------------------------------------------------------
OneWire oneWire(PIN_TEMP_ONEWIRE);
DallasTemperature tempSensor(&oneWire);

volatile unsigned long pulseCount = 0;

void IRAM_ATTR onSpeedPulse() {
  pulseCount++;
}

// ---------------------------------------------------------------
// ADXL345 minimal driver (avoids pulling in a heavy external library)
// ---------------------------------------------------------------
void adxl345Write(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

void adxl345Init() {
  Wire.begin();
  adxl345Write(0x2D, 0x08);  // POWER_CTL: measurement mode
  adxl345Write(0x31, 0x08);  // DATA_FORMAT: full resolution, +/-2g
}

// Returns acceleration in g for X, Y, Z
void adxl345Read(float &ax, float &ay, float &az) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(0x32);  // DATAX0
  Wire.endTransmission(false);
  Wire.requestFrom((int)ADXL345_ADDR, 6);

  int16_t rawX = Wire.read() | (Wire.read() << 8);
  int16_t rawY = Wire.read() | (Wire.read() << 8);
  int16_t rawZ = Wire.read() | (Wire.read() << 8);

  const float SCALE = 0.0039; // g per LSB at full resolution
  ax = rawX * SCALE;
  ay = rawY * SCALE;
  az = rawZ * SCALE;
}

// ---------------------------------------------------------------
// Sensor reading functions — each returns one feature value
// ---------------------------------------------------------------
float readTemperature() {
  tempSensor.requestTemperatures();
  float t = tempSensor.getTempCByIndex(0);
  if (t == DEVICE_DISCONNECTED_C) {
    return NAN;
  }
  return t;
}

float readVibrationRMS() {
  float sumSq = 0;
  for (int i = 0; i < VIBRATION_SAMPLES; i++) {
    float ax, ay, az;
    adxl345Read(ax, ay, az);
    // Subtract gravity on Z axis (assumes sensor mounted with Z roughly vertical;
    // re-orient this baseline if your sensor is mounted differently)
    float magnitude = sqrt(ax * ax + ay * ay + (az - 1.0) * (az - 1.0));
    sumSq += magnitude * magnitude;
    delay(2);
  }
  return sqrt(sumSq / VIBRATION_SAMPLES);
}

float readCurrentRMS() {
  float sumSq = 0;
  int zeroOffset = ADC_MAX_COUNTS / 2; // ACS712 outputs VCC/2 at 0A
  for (int i = 0; i < CURRENT_SAMPLES; i++) {
    int raw = analogRead(PIN_CURRENT_ADC);
    int centered = raw - zeroOffset;
    float voltage = (centered * ADC_VREF) / ADC_MAX_COUNTS;
    float amps = voltage / ACS712_SENSITIVITY_V_PER_A;
    sumSq += amps * amps;
    delayMicroseconds(500);
  }
  return sqrt(sumSq / CURRENT_SAMPLES);
}

float readVoltage() {
  int raw = analogRead(PIN_VOLTAGE_ADC);
  float vAtPin = (raw * ADC_VREF) / ADC_MAX_COUNTS;
  float ratio = (VOLTAGE_DIVIDER_R1 + VOLTAGE_DIVIDER_R2) / VOLTAGE_DIVIDER_R2;
  return vAtPin * ratio;
}

float readAcousticLevel() {
  // Reads the analog envelope from a sound sensor module and maps peak-to-peak
  // swing onto an approximate 0-100 "level" scale matching the training data's
  // acoustic_level range. This is NOT calibrated SPL (dB) — if you need true
  // dB readings, replace with a calibrated I2S/SPL microphone module.
  int minVal = ADC_MAX_COUNTS, maxVal = 0;
  for (int i = 0; i < SOUND_SAMPLES; i++) {
    int raw = analogRead(PIN_SOUND_ADC);
    if (raw < minVal) minVal = raw;
    if (raw > maxVal) maxVal = raw;
    delayMicroseconds(500);
  }
  int peakToPeak = maxVal - minVal;
  float level = (peakToPeak / (float)ADC_MAX_COUNTS) * 100.0;
  return level;
}

float readRPM() {
  noInterrupts();
  unsigned long count = pulseCount;
  pulseCount = 0;
  interrupts();

  float revs = count / (float)PULSES_PER_REV;
  float minutes = RPM_WINDOW_MS / 60000.0;
  return revs / minutes;
}

// ---------------------------------------------------------------
// Setup / loop
// ---------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1000);

  tempSensor.begin();
  adxl345Init();

  pinMode(PIN_CURRENT_ADC, INPUT);
  pinMode(PIN_VOLTAGE_ADC, INPUT);
  pinMode(PIN_SOUND_ADC, INPUT);

  pinMode(PIN_SPEED_PULSE, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_SPEED_PULSE), onSpeedPulse, FALLING);

  Serial.println("Motor Digital Stethoscope firmware ready.");
}

void loop() {
  unsigned long windowStart = millis();

  float temperature = readTemperature();
  float vibration_rms = readVibrationRMS();
  float current_rms = readCurrentRMS();
  float voltage = readVoltage();
  float acoustic_level = readAcousticLevel();

  // Let pulses continue accumulating for the remainder of the RPM window
  // while the (fast) sensor reads above happen, then read RPM.
  long remaining = RPM_WINDOW_MS - (millis() - windowStart);
  if (remaining > 0) delay(remaining);
  float rpm = readRPM();

  if (isnan(temperature)) {
    Serial.println("ERROR,temperature_sensor_disconnected");
    return;
  }

  // Feature order MUST match FEATURES in train_model.py:
  // temperature, vibration_rms, current_rms, voltage, acoustic_level, rpm
  float x[6] = { temperature, vibration_rms, current_rms, voltage, acoustic_level, rpm };
  const char* condition = model.predictLabel(x);

  Serial.print("DATA,");
  Serial.print(temperature, 2);
  Serial.print(",");
  Serial.print(vibration_rms, 4);
  Serial.print(",");
  Serial.print(current_rms, 2);
  Serial.print(",");
  Serial.print(voltage, 2);
  Serial.print(",");
  Serial.print(acoustic_level, 2);
  Serial.print(",");
  Serial.print(rpm, 0);
  Serial.print(",");
  Serial.println(condition);
}
