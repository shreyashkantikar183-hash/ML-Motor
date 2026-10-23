/*
  motor_stethoscope_firmware.ino
  Multimodal Motor Digital Stethoscope — ESP32 firmware
  Supports BOTH a DC motor and a three-phase AC motor, selected at RUNTIME
  by a physical toggle switch — no re-flashing needed to switch between them.

  Both sensor sets (DC's 2 analog channels, AC's 6 analog channels) are wired
  to the board permanently. The switch just tells the firmware which set to
  actually read and report on each loop.

  Streams over USB serial in the format dashboard_live.py / collect_real_data.py expect:
      DATA,motor_type,temperature,vibration_rms,current_rms_avg,current_imbalance_pct,
           voltage_rms_avg,voltage_imbalance_pct,acoustic_level,rpm,condition

  Feature order for the on-device model (motor_model.h) MUST match train_model.py's
  FEATURES list exactly:
      motor_type, temperature, vibration_rms, current_rms_avg, current_imbalance_pct,
      voltage_rms_avg, voltage_imbalance_pct, acoustic_level, rpm

  ==========================================================================
  *** SAFETY WARNING — READ BEFORE WIRING THE AC (3-PHASE) SENSOR SET ***
  Three-phase mains voltage (commonly ~400V line-line / ~230V line-neutral)
  is LETHAL. Do NOT connect ADC pins directly to mains, and do NOT use a
  plain resistor divider the way the DC channel does for its low-voltage
  supply. Use proper ISOLATED voltage sensing (e.g. a ZMPT101B-style
  precision voltage transducer module per phase) rated for your actual
  supply voltage, keep the ESP32 and its low-voltage wiring physically
  separated from the mains side, and have someone experienced with mains
  wiring review the build before powering it up. This firmware only reads
  sensor OUTPUTS in software — it is not a substitute for safe electrical
  practice, proper enclosures, and fusing/isolation on the AC side.
  ==========================================================================

  See HARDWARE.md for the full bill of materials and wiring diagram.

  Libraries needed (Arduino Library Manager): OneWire, DallasTemperature
  (Wire.h for the ADXL345 I2C link is built in.)
*/

#include <Wire.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include "motor_model.h"

using namespace Eloquent::ML::Port;
RandomForest model;

// ---------------------------------------------------------------
// Pin map — see HARDWARE.md for the matching wiring diagram.
// All pins are used simultaneously; the switch just picks which
// readings get reported.
// ---------------------------------------------------------------
#define PIN_TEMP_ONEWIRE      4    // DS18B20 (shared)
// I2C (ADXL345, shared) uses the board's default SDA/SCL (usually 21/22)
#define PIN_MOTOR_TYPE_SWITCH 13   // toggle switch: LOW = DC, HIGH = AC
#define PIN_SPEED_PULSE       27   // IR/Hall RPM pulse sensor (shared, interrupt)
#define PIN_SOUND_ADC         25   // sound sensor (shared)

#define PIN_DC_CURRENT_ADC    34
#define PIN_DC_VOLTAGE_ADC    35

#define PIN_AC_CURRENT_R_ADC  32
#define PIN_AC_CURRENT_Y_ADC  33
#define PIN_AC_CURRENT_B_ADC  36
#define PIN_AC_VOLTAGE_R_ADC  39
#define PIN_AC_VOLTAGE_Y_ADC  26
#define PIN_AC_VOLTAGE_B_ADC  14

const uint8_t ADXL345_ADDR = 0x53;

// ---------------------------------------------------------------
// Calibration constants — adjust to your actual sensors/wiring
// ---------------------------------------------------------------
const float ADC_VREF = 3.3;
const int   ADC_MAX_COUNTS = 4095;

// ACS712: 66 mV/A for the 30A variant, 100 mV/A for 20A, 185 mV/A for 5A.
const float ACS712_SENSITIVITY_V_PER_A = 0.066;

// DC supply divider: Vin -- R1 --+-- R2 -- GND, ADC reads the midpoint.
const float VOLTAGE_DIVIDER_R1 = 30000.0;  // ohms
const float VOLTAGE_DIVIDER_R2 = 7500.0;   // ohms

// AC voltage transducer output scaling: volts of actual AC line per volt
// measured at the ADC pin. CALIBRATE against a trusted multimeter reading
// before trusting the numbers — this default is a placeholder.
const float AC_VOLTAGE_TRANSDUCER_SCALE = 200.0;

const int PULSES_PER_REV = 1;
const int VIBRATION_SAMPLES = 100;
const int CURRENT_SAMPLES = 200;   // per channel, covers >1 AC cycle at 50/60Hz
const int SOUND_SAMPLES = 200;
const unsigned long RPM_WINDOW_MS = 1000;
const unsigned long SWITCH_DEBOUNCE_MS = 50;

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
// ADXL345 minimal driver
// ---------------------------------------------------------------
void adxl345Write(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

void adxl345Init() {
  Wire.begin();
  adxl345Write(0x2D, 0x08);
  adxl345Write(0x31, 0x08);
}

void adxl345Read(float &ax, float &ay, float &az) {
  Wire.beginTransmission(ADXL345_ADDR);
  Wire.write(0x32);
  Wire.endTransmission(false);
  Wire.requestFrom((int)ADXL345_ADDR, 6);
  int16_t rawX = Wire.read() | (Wire.read() << 8);
  int16_t rawY = Wire.read() | (Wire.read() << 8);
  int16_t rawZ = Wire.read() | (Wire.read() << 8);
  const float SCALE = 0.0039;
  ax = rawX * SCALE; ay = rawY * SCALE; az = rawZ * SCALE;
}

// ---------------------------------------------------------------
// Shared sensor reads
// ---------------------------------------------------------------
float readTemperature() {
  tempSensor.requestTemperatures();
  float t = tempSensor.getTempCByIndex(0);
  return (t == DEVICE_DISCONNECTED_C) ? NAN : t;
}

float readVibrationRMS() {
  float sumSq = 0;
  for (int i = 0; i < VIBRATION_SAMPLES; i++) {
    float ax, ay, az;
    adxl345Read(ax, ay, az);
    float magnitude = sqrt(ax * ax + ay * ay + (az - 1.0) * (az - 1.0));
    sumSq += magnitude * magnitude;
    delay(2);
  }
  return sqrt(sumSq / VIBRATION_SAMPLES);
}

float readAcousticLevel() {
  int minVal = ADC_MAX_COUNTS, maxVal = 0;
  for (int i = 0; i < SOUND_SAMPLES; i++) {
    int raw = analogRead(PIN_SOUND_ADC);
    if (raw < minVal) minVal = raw;
    if (raw > maxVal) maxVal = raw;
    delayMicroseconds(500);
  }
  int peakToPeak = maxVal - minVal;
  return (peakToPeak / (float)ADC_MAX_COUNTS) * 100.0;
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

float readCurrentRMS(int pin) {
  float sumSq = 0;
  int zeroOffset = ADC_MAX_COUNTS / 2;
  for (int i = 0; i < CURRENT_SAMPLES; i++) {
    int raw = analogRead(pin);
    int centered = raw - zeroOffset;
    float voltage = (centered * ADC_VREF) / ADC_MAX_COUNTS;
    float amps = voltage / ACS712_SENSITIVITY_V_PER_A;
    sumSq += amps * amps;
    delayMicroseconds(500);
  }
  return sqrt(sumSq / CURRENT_SAMPLES);
}

float readVoltageDC() {
  int raw = analogRead(PIN_DC_VOLTAGE_ADC);
  float vAtPin = (raw * ADC_VREF) / ADC_MAX_COUNTS;
  float ratio = (VOLTAGE_DIVIDER_R1 + VOLTAGE_DIVIDER_R2) / VOLTAGE_DIVIDER_R2;
  return vAtPin * ratio;
}

float readVoltageChannelRMS(int pin) {
  float sumSq = 0;
  int zeroOffset = ADC_MAX_COUNTS / 2;
  for (int i = 0; i < CURRENT_SAMPLES; i++) {
    int raw = analogRead(pin);
    int centered = raw - zeroOffset;
    float voltage = (centered * ADC_VREF) / ADC_MAX_COUNTS;
    sumSq += voltage * voltage;
    delayMicroseconds(500);
  }
  return sqrt(sumSq / CURRENT_SAMPLES);
}

float pctImbalance(float a, float b, float c) {
  float avg = (a + b + c) / 3.0;
  if (avg <= 0.0001) return 0.0;
  float maxV = max(a, max(b, c));
  float minV = min(a, min(b, c));
  return ((maxV - minV) / avg) * 100.0;
}

// ---------------------------------------------------------------
// Debounced switch read: LOW = DC (0), HIGH = AC (1)
// ---------------------------------------------------------------
int readMotorTypeSwitch() {
  static int stableState = LOW;
  static int lastReading = LOW;
  static unsigned long lastChangeTime = 0;

  int reading = digitalRead(PIN_MOTOR_TYPE_SWITCH);
  if (reading != lastReading) {
    lastChangeTime = millis();
    lastReading = reading;
  }
  if ((millis() - lastChangeTime) > SWITCH_DEBOUNCE_MS) {
    stableState = reading;
  }
  return (stableState == HIGH) ? 1 : 0;
}

// ---------------------------------------------------------------
// Setup / loop
// ---------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1000);

  tempSensor.begin();
  adxl345Init();

  pinMode(PIN_SOUND_ADC, INPUT);
  pinMode(PIN_SPEED_PULSE, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PIN_SPEED_PULSE), onSpeedPulse, FALLING);

  pinMode(PIN_MOTOR_TYPE_SWITCH, INPUT_PULLDOWN); // switch pulls HIGH for AC, floats/LOW for DC

  pinMode(PIN_DC_CURRENT_ADC, INPUT);
  pinMode(PIN_DC_VOLTAGE_ADC, INPUT);
  pinMode(PIN_AC_CURRENT_R_ADC, INPUT);
  pinMode(PIN_AC_CURRENT_Y_ADC, INPUT);
  pinMode(PIN_AC_CURRENT_B_ADC, INPUT);
  pinMode(PIN_AC_VOLTAGE_R_ADC, INPUT);
  pinMode(PIN_AC_VOLTAGE_Y_ADC, INPUT);
  pinMode(PIN_AC_VOLTAGE_B_ADC, INPUT);

  Serial.println("Motor Digital Stethoscope firmware ready. Flip the switch to select DC or AC.");
}

void loop() {
  unsigned long windowStart = millis();

  int motor_type = readMotorTypeSwitch();  // 0 = DC, 1 = AC — read fresh each loop

  float temperature = readTemperature();
  float vibration_rms = readVibrationRMS();
  float acoustic_level = readAcousticLevel();

  float current_rms_avg, current_imbalance_pct;
  float voltage_rms_avg, voltage_imbalance_pct;

  if (motor_type == 0) {
    current_rms_avg = readCurrentRMS(PIN_DC_CURRENT_ADC);
    current_imbalance_pct = 0.0;
    voltage_rms_avg = readVoltageDC();
    voltage_imbalance_pct = 0.0;
  } else {
    float iR = readCurrentRMS(PIN_AC_CURRENT_R_ADC);
    float iY = readCurrentRMS(PIN_AC_CURRENT_Y_ADC);
    float iB = readCurrentRMS(PIN_AC_CURRENT_B_ADC);
    current_rms_avg = (iR + iY + iB) / 3.0;
    current_imbalance_pct = pctImbalance(iR, iY, iB);

    float vR = readVoltageChannelRMS(PIN_AC_VOLTAGE_R_ADC) * AC_VOLTAGE_TRANSDUCER_SCALE;
    float vY = readVoltageChannelRMS(PIN_AC_VOLTAGE_Y_ADC) * AC_VOLTAGE_TRANSDUCER_SCALE;
    float vB = readVoltageChannelRMS(PIN_AC_VOLTAGE_B_ADC) * AC_VOLTAGE_TRANSDUCER_SCALE;
    voltage_rms_avg = (vR + vY + vB) / 3.0;
    voltage_imbalance_pct = pctImbalance(vR, vY, vB);
  }

  long remaining = RPM_WINDOW_MS - (millis() - windowStart);
  if (remaining > 0) delay(remaining);
  float rpm = readRPM();

  if (isnan(temperature)) {
    Serial.println("ERROR,temperature_sensor_disconnected");
    return;
  }

  // Feature order MUST match FEATURES in train_model.py:
  // motor_type, temperature, vibration_rms, current_rms_avg, current_imbalance_pct,
  // voltage_rms_avg, voltage_imbalance_pct, acoustic_level, rpm
  float x[9] = {
    (float)motor_type, temperature, vibration_rms,
    current_rms_avg, current_imbalance_pct,
    voltage_rms_avg, voltage_imbalance_pct,
    acoustic_level, rpm
  };
  const char* condition = model.predictLabel(x);

  Serial.print("DATA,");
  Serial.print(motor_type);             Serial.print(",");
  Serial.print(temperature, 2);         Serial.print(",");
  Serial.print(vibration_rms, 4);       Serial.print(",");
  Serial.print(current_rms_avg, 2);     Serial.print(",");
  Serial.print(current_imbalance_pct, 2); Serial.print(",");
  Serial.print(voltage_rms_avg, 2);     Serial.print(",");
  Serial.print(voltage_imbalance_pct, 2); Serial.print(",");
  Serial.print(acoustic_level, 2);      Serial.print(",");
  Serial.print(rpm, 0);                 Serial.print(",");
  Serial.println(condition);
}
