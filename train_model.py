"""
train_model.py
Canonical training script for the Motor Digital Stethoscope.

Input:  motor_dataset.csv  (run generate_dataset.py first, or supply real
        data collected via collect_real_data.py)
Output: motor_model.pkl    (used by dashboard.py / dashboard_live.py)
        motor_model.h      (used by the ESP32 firmware for on-device inference)

Features (in this exact order — the firmware and dashboards must match):
    temperature, vibration_rms, current_rms, voltage, acoustic_level, rpm
"""

import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
import joblib

from export_cpp import port_random_forest

FEATURES = [
    "motor_type", "temperature", "vibration_rms",
    "current_rms_avg", "current_imbalance_pct",
    "voltage_rms_avg", "voltage_imbalance_pct",
    "acoustic_level", "rpm",
]
TARGET = "condition"

# 1. Load dataset
data = pd.read_csv("motor_dataset.csv")
print(f"Loaded motor_dataset.csv: {len(data)} rows")
print(data[TARGET].value_counts())

missing = [c for c in FEATURES + [TARGET] if c not in data.columns]
if missing:
    raise SystemExit(f"Dataset is missing required columns: {missing}")

X = data[FEATURES]
y = data[TARGET]

# 2. Split
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.25, random_state=42, stratify=y
)

# 3. Train — small forest (20 trees, capped depth) so it's cheap enough
#    to run on an ESP32 once ported to C++.
model = RandomForestClassifier(
    n_estimators=20, max_depth=6, random_state=42
)
model.fit(X_train, y_train)

# 4. Evaluate
y_pred = model.predict(X_test)
print("\nAccuracy:", accuracy_score(y_test, y_pred))
print("\nClassification Report:")
print(classification_report(y_test, y_pred, zero_division=0))
print("Confusion Matrix:")
print(confusion_matrix(y_test, y_pred, labels=model.classes_))
print("Classes:", list(model.classes_))

# 5. Save sklearn model for the Python dashboards
joblib.dump(model, "motor_model.pkl")
print("\nSaved motor_model.pkl")

# 6. Export C++ header for the ESP32 firmware.
#    class_names[i] must correspond to model.classes_[i] (alphabetical by default).
class_names = list(model.classes_)
cpp_code = port_random_forest(model, FEATURES, class_names)
with open("motor_model.h", "w") as f:
    f.write(cpp_code)
print("Saved motor_model.h")
print(f"Feature order for firmware: {FEATURES}")
print(f"Class index mapping: {list(enumerate(class_names))}")
