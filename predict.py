"""
predict.py
Quick manual test: load motor_model.pkl and classify one hand-entered reading.
Edit motor_type (0=DC, 1=AC) and the sensor numbers to try different scenarios.
"""

import pandas as pd
import joblib

model = joblib.load("motor_model.pkl")
FEATURES = [
    "motor_type", "temperature", "vibration_rms",
    "current_rms_avg", "current_imbalance_pct",
    "voltage_rms_avg", "voltage_imbalance_pct",
    "acoustic_level", "rpm",
]

# Example: a DC motor reading in Fault territory
dc_example = {
    "motor_type": 0,
    "temperature": 91,
    "vibration_rms": 0.10,
    "current_rms_avg": 6.2,
    "current_imbalance_pct": 0.0,   # always 0 for DC
    "voltage_rms_avg": 9.6,
    "voltage_imbalance_pct": 0.0,   # always 0 for DC
    "acoustic_level": 80,
    "rpm": 1050,
}

# Example: a 3-phase AC motor reading with a developing phase imbalance (Warning)
ac_example = {
    "motor_type": 1,
    "temperature": 65,
    "vibration_rms": 0.045,
    "current_rms_avg": 4.2,
    "current_imbalance_pct": 3.5,
    "voltage_rms_avg": 392,
    "voltage_imbalance_pct": 1.8,
    "acoustic_level": 60,
    "rpm": 1400,
}

for name, example in [("DC example", dc_example), ("AC example", ac_example)]:
    X = pd.DataFrame([example])[FEATURES]
    prediction = model.predict(X)[0]
    probability = model.predict_proba(X)[0]
    print(f"\n--- {name} ---")
    print(X)
    print("Predicted condition:", prediction)
    print("Class probabilities:", dict(zip(model.classes_, probability)))
