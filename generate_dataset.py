"""
generate_dataset.py
Generates a synthetic labeled dataset for the Motor Digital Stethoscope,
covering BOTH DC motors and three-phase AC motors with one unified schema.

Unified features (identical meaning for either motor type):
    motor_type            0 = DC, 1 = AC (three-phase)
    temperature            (deg C)
    vibration_rms           (g)
    current_rms_avg         (A)   -- average of the phase currents (AC) or the single armature current (DC)
    current_imbalance_pct   (%)   -- max-min phase current spread / average, NEMA-style. Always 0 for DC.
    voltage_rms_avg         (V)   -- average of the phase/line voltages (AC) or the single supply voltage (DC)
    voltage_imbalance_pct   (%)   -- same idea for voltage. Always 0 for DC.
    acoustic_level          (dB-ish, 0-100 scale)
    rpm                     (revolutions per minute)

Labels: Normal, Warning, Fault

NOTE: the numeric ranges below are illustrative placeholders sized for a small
demo motor, not real nameplate data. Replace with your own motor's real specs
(and, ideally, real collected data via collect_real_data.py) before relying on
this for anything beyond a working demo.
"""

import numpy as np
import pandas as pd

np.random.seed(42)
N_PER_CLASS = 100  # per (motor_type, condition) combination

FEATURES = [
    "motor_type", "temperature", "vibration_rms",
    "current_rms_avg", "current_imbalance_pct",
    "voltage_rms_avg", "voltage_imbalance_pct",
    "acoustic_level", "rpm",
]

# ---------------------------------------------------------------
# DC motor ranges (motor_type = 0). No phases -> imbalance is always 0.
# Small demo motor, e.g. 12V supply.
# ---------------------------------------------------------------
DC_RANGES = {
    "Normal":  dict(temperature=(35, 55), vibration_rms=(0.01, 0.03), current_rms_avg=(2.0, 3.5),
                     voltage_rms_avg=(11.5, 12.5), acoustic_level=(40, 55), rpm=(1450, 1550)),
    "Warning": dict(temperature=(56, 75), vibration_rms=(0.031, 0.07), current_rms_avg=(3.6, 5.0),
                     voltage_rms_avg=(10.5, 11.5), acoustic_level=(56, 70), rpm=(1300, 1450)),
    "Fault":   dict(temperature=(76, 100), vibration_rms=(0.071, 0.15), current_rms_avg=(5.1, 7.5),
                     voltage_rms_avg=(9.0, 10.5), acoustic_level=(71, 90), rpm=(900, 1300)),
}

# ---------------------------------------------------------------
# Three-phase AC motor ranges (motor_type = 1). Line-line voltage ~415V class.
# Imbalance is the classic 3-phase fault signature: NEMA guidance treats
# >1% voltage imbalance as worth investigating, and current imbalance is
# typically ~6-10x the voltage imbalance in its heating effect on the motor.
# ---------------------------------------------------------------
AC_RANGES = {
    "Normal":  dict(temperature=(35, 55), vibration_rms=(0.01, 0.03), current_rms_avg=(2.0, 3.5),
                     current_imbalance_pct=(0.0, 2.0),
                     voltage_rms_avg=(400, 415), voltage_imbalance_pct=(0.0, 1.0),
                     acoustic_level=(40, 55), rpm=(1450, 1550)),
    "Warning": dict(temperature=(56, 75), vibration_rms=(0.031, 0.07), current_rms_avg=(3.6, 5.0),
                     current_imbalance_pct=(2.0, 5.0),
                     voltage_rms_avg=(385, 400), voltage_imbalance_pct=(1.0, 3.0),
                     acoustic_level=(56, 70), rpm=(1300, 1450)),
    "Fault":   dict(temperature=(76, 100), vibration_rms=(0.071, 0.15), current_rms_avg=(5.1, 7.5),
                     current_imbalance_pct=(5.0, 15.0),
                     voltage_rms_avg=(350, 385), voltage_imbalance_pct=(3.0, 8.0),
                     acoustic_level=(71, 90), rpm=(900, 1300)),
}


def make_class(motor_type, label, ranges, n=N_PER_CLASS):
    r = ranges[label]
    df = pd.DataFrame({
        "motor_type": motor_type,
        "temperature": np.round(np.random.uniform(*r["temperature"], n), 2),
        "vibration_rms": np.round(np.random.uniform(*r["vibration_rms"], n), 4),
        "current_rms_avg": np.round(np.random.uniform(*r["current_rms_avg"], n), 2),
        "current_imbalance_pct": np.round(
            np.random.uniform(*r.get("current_imbalance_pct", (0.0, 0.0)), n), 3
        ),
        "voltage_rms_avg": np.round(np.random.uniform(*r["voltage_rms_avg"], n), 2),
        "voltage_imbalance_pct": np.round(
            np.random.uniform(*r.get("voltage_imbalance_pct", (0.0, 0.0)), n), 3
        ),
        "acoustic_level": np.round(np.random.uniform(*r["acoustic_level"], n), 2),
        "rpm": np.round(np.random.uniform(*r["rpm"], n), 0),
        "condition": label,
    })
    return df


frames = []
for label in ("Normal", "Warning", "Fault"):
    frames.append(make_class(0, label, DC_RANGES))  # DC
    frames.append(make_class(1, label, AC_RANGES))  # AC

data = pd.concat(frames, ignore_index=True)
data = data.sample(frac=1, random_state=42).reset_index(drop=True)

noise_cols = ["temperature", "vibration_rms", "current_rms_avg", "current_imbalance_pct",
              "voltage_rms_avg", "voltage_imbalance_pct", "acoustic_level", "rpm"]
for col in noise_cols:
    std = data[col].std()
    if std > 0:
        noise = np.random.normal(0, std * 0.05, size=len(data))
        data[col] = np.round(data[col] + noise, 4)
data["rpm"] = data["rpm"].round(0)
data["current_imbalance_pct"] = data["current_imbalance_pct"].clip(lower=0)
data["voltage_imbalance_pct"] = data["voltage_imbalance_pct"].clip(lower=0)

data.to_csv("motor_dataset.csv", index=False)
print(f"Generated motor_dataset.csv with {len(data)} rows")
print(data.groupby(["motor_type", "condition"]).size())
print("\nSample rows:")
print(data.head())
