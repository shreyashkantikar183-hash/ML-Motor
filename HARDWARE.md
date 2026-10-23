# Motor Digital Stethoscope — Hardware Guide

Covers both variants: monitoring a small **DC motor** and a **three-phase AC motor**,
switchable at runtime with one physical toggle switch — no re-flashing required.

---

## ⚠️ Safety first — read this before wiring anything

- **The AC side of this build touches real mains-level voltage** (commonly
  ~400V line-line / ~230V line-neutral for a 3-phase supply). This is
  **lethal** if mishandled.
- Never connect an ESP32 ADC pin directly to mains, and never use a plain
  resistor divider on AC mains the way this project's DC channel uses one
  on its low-voltage supply.
- Use **isolated** voltage sensing modules (e.g. ZMPT101B-style precision
  AC voltage transducers) and **isolated** current sensing (ACS712-style
  Hall-effect sensors are already galvanically isolated — good) rated for
  your actual supply.
- Keep the low-voltage ESP32/logic side physically separated from the
  mains side (separate enclosure sections, proper clearances, strain relief).
- Fuse the AC side appropriately, and if you're not experienced with mains
  wiring, have someone who is review the build before it's powered on.
- This document tells you how to wire sensor *outputs* into the ESP32. It
  is not a substitute for proper electrical safety practice, code compliance,
  or a qualified second opinion.

---

## Bill of materials

| Component | Qty | Used for | Notes |
|---|---|---|---|
| ESP32 dev board (30-pin, e.g. DevKitC) | 1 | Main controller | Needs 8+ ADC pins available |
| DS18B20 temperature sensor | 1 | Temperature (shared) | Digital, OneWire |
| 4.7kΩ resistor | 1 | DS18B20 pull-up | Between DS18B20 data line and 3.3V |
| ADXL345 accelerometer module | 1 | Vibration (shared) | I2C |
| ACS712 current sensor module | 1 (DC) or 3 (AC) | Current sensing | Pick 5A/20A/30A variant to match your motor's current draw |
| Isolated AC voltage transducer (e.g. ZMPT101B module) | 3 (AC only) | Phase voltage sensing | **Do not substitute a resistor divider here** |
| Resistors for DC voltage divider (e.g. 30kΩ + 7.5kΩ) | 1 pair (DC only) | Scaling DC supply voltage down to ADC-safe range | Ratio must bring max expected voltage under 3.3V |
| Sound sensor module (e.g. KY-038) | 1 | Acoustic level (shared) | Analog envelope output |
| IR slot sensor or Hall proximity sensor + encoder marker | 1 | RPM (shared) | 1 pulse per revolution assumed by default |
| SPDT toggle switch | 1 | DC/AC mode select | Wired to one digital pin |
| 10kΩ resistor (optional) | 1 | Switch pull-down | Or use ESP32's internal `INPUT_PULLDOWN` |
| Breadboard/perfboard, jumper wires, enclosure | — | Assembly | AC section should be enclosed separately from logic section |

---

## Pin map

All sensors are wired **simultaneously** — the switch only decides which
readings the firmware reports each loop, so nothing needs re-wiring when
you change motors.

| Signal | GPIO | Notes |
|---|---|---|
| DS18B20 (temperature) | 4 | OneWire, shared |
| ADXL345 SDA / SCL | 21 / 22 | I2C default pins, shared |
| Sound sensor (acoustic) | 25 | Shared |
| RPM pulse sensor | 27 | Interrupt-capable, shared |
| **Mode switch** | 13 | LOW = DC, HIGH = AC |
| DC current (ACS712) | 34 | DC only |
| DC voltage (divider) | 35 | DC only |
| AC current — Phase R (ACS712) | 32 | AC only |
| AC current — Phase Y (ACS712) | 33 | AC only |
| AC current — Phase B (ACS712) | 36 | AC only |
| AC voltage — Phase R (transducer) | 39 | AC only |
| AC voltage — Phase Y (transducer) | 26 | AC only |
| AC voltage — Phase B (transducer) | 14 | AC only |

If your specific board doesn't break out one of these pins, or you'd
rather rearrange them, just edit the `#define PIN_...` lines at the top
of `motor_stethoscope_firmware.ino` — nothing else depends on the exact
pin numbers.

---

## The mode switch

A simple SPDT toggle switch, wired as:

```
3.3V ---- [switch] ---- GPIO 13
                             |
                          (internal pull-down, set in firmware)
```

- Switch **open/DC position** → GPIO 13 reads LOW → firmware reports `motor_type = 0` (DC)
- Switch **closed/AC position** → GPIO 13 reads HIGH → firmware reports `motor_type = 1` (AC)

The firmware debounces this in software (50ms), so a cheap mechanical
switch is fine — flipping it takes effect within about a second, no
reset or re-flash needed.

---

## Sensor wiring notes

### Shared sensors
- **DS18B20**: data pin to GPIO 4, with a 4.7kΩ pull-up resistor between
  data and 3.3V, as is standard for OneWire sensors.
- **ADXL345**: standard I2C — VCC to 3.3V, GND to GND, SDA/SCL to the
  ESP32's default I2C pins (21/22 on most dev boards).
- **Sound sensor**: analog output to GPIO 25.
- **RPM sensor**: digital pulse output to GPIO 27. Mount it to pick up
  one pulse per shaft revolution (a single reflective marker for an IR
  slot sensor, or a single magnet for a Hall sensor).

### DC-only sensors
- **ACS712**: in-line on the motor's supply current path, analog output
  to GPIO 34.
- **Voltage divider**: across the DC supply rail, midpoint to GPIO 35.
  Size R1/R2 so the ADC never sees more than 3.3V at your motor's max
  expected supply voltage.

### AC-only sensors (three-phase)
- **3x ACS712**: one per phase, in-line on each phase conductor, outputs
  to GPIO 32/33/36.
- **3x isolated voltage transducers**: one per phase (phase-to-neutral is
  the simpler and safer measurement point than line-to-line), outputs to
  GPIO 39/26/14.
- Calibrate `AC_VOLTAGE_TRANSDUCER_SCALE` in the firmware against a
  trusted multimeter reading on each phase before trusting the numbers —
  transducer module gain varies unit to unit.

---

## After wiring

1. Flash `motor_stethoscope_firmware.ino` once — it now handles both
   motor types, so you won't need to re-flash when switching.
2. Open the Arduino IDE Serial Monitor at 115200 baud to confirm you see
   `DATA,...` lines and that the first field (motor_type) changes between
   `0` and `1` when you flip the switch.
3. Run `dashboard_live.py` — it reads `motor_type` automatically from
   each DATA line and adjusts the displayed thresholds/recommendations
   accordingly.
