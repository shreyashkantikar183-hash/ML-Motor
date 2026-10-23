import time
import random

import pandas as pd
import joblib
import streamlit as st

st.set_page_config(page_title="Motor Digital Stethoscope", layout="wide")

st.title("Multimodal Motor Digital Stethoscope")
st.caption("Edge-AI motor health monitoring — Random Forest classifier (simulation mode) — DC & 3-phase AC")

@st.cache_resource
def load_model():
    try:
        return joblib.load("motor_model.pkl")
    except FileNotFoundError:
        return None

model = load_model()

if model is None:
    st.error("motor_model.pkl not found. Run generate_dataset.py then train_model.py first.")
    st.stop()

FEATURES = [
    "motor_type", "temperature", "vibration_rms",
    "current_rms_avg", "current_imbalance_pct",
    "voltage_rms_avg", "voltage_imbalance_pct",
    "acoustic_level", "rpm",
]

# ---------------------------------------------------------
# Simulation ranges, per motor type
# ---------------------------------------------------------
DC_RANGES = {
    "Normal":  dict(temperature=(35, 55), vibration_rms=(0.01, 0.03), current_rms_avg=(2.0, 3.5),
                     current_imbalance_pct=(0.0, 0.0), voltage_rms_avg=(11.5, 12.5), voltage_imbalance_pct=(0.0, 0.0),
                     acoustic_level=(40, 55), rpm=(1450, 1550)),
    "Warning": dict(temperature=(56, 75), vibration_rms=(0.031, 0.07), current_rms_avg=(3.6, 5.0),
                     current_imbalance_pct=(0.0, 0.0), voltage_rms_avg=(10.5, 11.5), voltage_imbalance_pct=(0.0, 0.0),
                     acoustic_level=(56, 70), rpm=(1300, 1450)),
    "Fault":   dict(temperature=(76, 100), vibration_rms=(0.071, 0.15), current_rms_avg=(5.1, 7.5),
                     current_imbalance_pct=(0.0, 0.0), voltage_rms_avg=(9.0, 10.5), voltage_imbalance_pct=(0.0, 0.0),
                     acoustic_level=(71, 90), rpm=(900, 1300)),
}
AC_RANGES = {
    "Normal":  dict(temperature=(35, 55), vibration_rms=(0.01, 0.03), current_rms_avg=(2.0, 3.5),
                     current_imbalance_pct=(0.0, 2.0), voltage_rms_avg=(400, 415), voltage_imbalance_pct=(0.0, 1.0),
                     acoustic_level=(40, 55), rpm=(1450, 1550)),
    "Warning": dict(temperature=(56, 75), vibration_rms=(0.031, 0.07), current_rms_avg=(3.6, 5.0),
                     current_imbalance_pct=(2.0, 5.0), voltage_rms_avg=(385, 400), voltage_imbalance_pct=(1.0, 3.0),
                     acoustic_level=(56, 70), rpm=(1300, 1450)),
    "Fault":   dict(temperature=(76, 100), vibration_rms=(0.071, 0.15), current_rms_avg=(5.1, 7.5),
                     current_imbalance_pct=(5.0, 15.0), voltage_rms_avg=(350, 385), voltage_imbalance_pct=(3.0, 8.0),
                     acoustic_level=(71, 90), rpm=(900, 1300)),
}

def sample_reading(motor_type_code, true_state):
    ranges = DC_RANGES if motor_type_code == 0 else AC_RANGES
    r = ranges[true_state]
    sample = {f: round(random.uniform(*r[f]), 4) for f in r}
    sample["motor_type"] = motor_type_code
    return sample

# ---------------------------------------------------------
# Health diagnosis + recommended actions (type-aware thresholds)
# ---------------------------------------------------------
THRESHOLDS = {
    0: {  # DC
        "temperature":    dict(normal_max=55,  warning_max=75,  unit="°C"),
        "vibration_rms":  dict(normal_max=0.03, warning_max=0.07, unit="g"),
        "current_rms_avg": dict(normal_max=3.5, warning_max=5.0,  unit="A"),
        "voltage_rms_avg": dict(normal_min=11.5, warning_min=10.5, unit="V"),
        "acoustic_level": dict(normal_max=55,  warning_max=70,  unit="dB"),
        "rpm":            dict(normal_min=1450, warning_min=1300, unit="rpm"),
    },
    1: {  # AC (3-phase)
        "temperature":    dict(normal_max=55,  warning_max=75,  unit="°C"),
        "vibration_rms":  dict(normal_max=0.03, warning_max=0.07, unit="g"),
        "current_rms_avg": dict(normal_max=3.5, warning_max=5.0,  unit="A"),
        "current_imbalance_pct": dict(normal_max=2.0, warning_max=5.0, unit="%"),
        "voltage_rms_avg": dict(normal_min=400, warning_min=385, unit="V"),
        "voltage_imbalance_pct": dict(normal_max=1.0, warning_max=3.0, unit="%"),
        "acoustic_level": dict(normal_max=55,  warning_max=70,  unit="dB"),
        "rpm":            dict(normal_min=1450, warning_min=1300, unit="rpm"),
    },
}

LABELS = {
    "temperature": "Temperature",
    "vibration_rms": "Vibration",
    "current_rms_avg": "Current (avg)",
    "current_imbalance_pct": "Current imbalance",
    "voltage_rms_avg": "Voltage (avg)",
    "voltage_imbalance_pct": "Voltage imbalance",
    "acoustic_level": "Acoustic level",
    "rpm": "Speed (RPM)",
}

ACTIONS = {
    "temperature": {
        "Warning": "Check ventilation and cooling airflow; reduce load if the motor is running hot.",
        "Fault": "Stop the motor and let it cool. Inspect bearings and windings for heat damage before restarting.",
    },
    "vibration_rms": {
        "Warning": "Inspect mounting bolts and shaft alignment; check the coupling for wear.",
        "Fault": "Stop the motor. Inspect bearings for damage and check for rotor imbalance before restarting.",
    },
    "current_rms_avg": {
        "Warning": "Check for mechanical overload and confirm the load matches the motor's rated capacity.",
        "Fault": "Shut down the motor. Inspect for a winding short, stalled rotor, or mechanical jam.",
    },
    "current_imbalance_pct": {
        "Warning": "Phase currents are drifting apart — check connections and load balance across phases.",
        "Fault": "Severe current imbalance — risk of single-phasing. Stop the motor and check for a blown fuse, loose terminal, or failing winding on one phase.",
    },
    "voltage_rms_avg": {
        "Warning": "Check supply voltage stability and inspect wiring/terminal connections for looseness.",
        "Fault": "Stop the motor. Inspect the power supply, transformer tap, and wiring for faults.",
    },
    "voltage_imbalance_pct": {
        "Warning": "Voltage is unequal across phases — check the incoming supply and connections.",
        "Fault": "Significant supply voltage imbalance — this causes excess heating. Stop and have the supply checked before continuing.",
    },
    "acoustic_level": {
        "Warning": "Listen for grinding, whining, or knocking; inspect bearings and belts.",
        "Fault": "Stop the motor. Inspect for mechanical damage such as bearing failure or loose components.",
    },
    "rpm": {
        "Warning": "Speed is drifting from rated RPM — check load, belt tension/slippage, or supply frequency.",
        "Fault": "Speed has sagged significantly — check for mechanical overload, stalling, or a jammed load. Stop and inspect.",
    },
}

# Concrete, ordered corrective steps shown prominently when a Fault is detected —
# these are the "bold measures" a technician would actually walk through to
# try to resolve the specific fault, not just a one-line diagnosis.
RESOLUTION_STEPS = {
    "temperature": [
        "**Cut power to the motor immediately** — do not let it keep running hot.",
        "**Let it cool** for at least 15-20 minutes before touching or inspecting it.",
        "**Check the cooling path**: fan operation, airflow vents, and ambient temperature around the motor.",
        "**Inspect bearings and windings** for discoloration, burnt smell, or insulation damage once cool.",
        "**Reduce the load** or duty cycle before restarting if overloading caused the rise.",
    ],
    "vibration_rms": [
        "**Stop the motor** before the vibration worsens into a bearing or shaft failure.",
        "**Check mounting bolts** — tighten anything loose at the base or coupling.",
        "**Inspect shaft alignment** between the motor and driven load.",
        "**Inspect bearings** for wear, pitting, or lack of lubrication.",
        "**Check for rotor imbalance** — look for debris, damage, or an unbalanced load on the shaft.",
    ],
    "current_rms_avg": [
        "**Shut down the motor** — sustained overcurrent risks winding damage.",
        "**Check the mechanical load** — confirm nothing is jammed or over-specified for this motor.",
        "**Inspect for a stalled rotor** by trying to turn the shaft by hand once power is off.",
        "**Check winding resistance** with a multimeter for signs of a short.",
        "**Verify supply voltage is correct** before restarting — undervoltage causes overcurrent.",
    ],
    "current_imbalance_pct": [
        "**Stop the motor immediately** — this is the classic sign of single-phasing, which can destroy the motor fast.",
        "**Check for a blown fuse or tripped breaker** on one phase.",
        "**Check for a loose or corroded terminal connection** on each phase.",
        "**Measure each phase's current individually** to confirm which phase is low.",
        "**Inspect that phase's winding** for a partial short or damage once safe to do so.",
    ],
    "voltage_rms_avg": [
        "**Stop the motor** — running on incorrect supply voltage causes ongoing damage.",
        "**Check the incoming supply** at the panel/transformer tap.",
        "**Inspect wiring and terminal connections** along the supply path for looseness or corrosion.",
        "**Confirm the supply matches the motor's rated voltage** before restarting.",
    ],
    "voltage_imbalance_pct": [
        "**Stop the motor** — voltage imbalance causes disproportionate heating in the windings.",
        "**Check the incoming three-phase supply** for an unbalanced load elsewhere on the circuit.",
        "**Inspect connections at the supply and at the motor terminals** for looseness.",
        "**Have the utility/supply checked** if the imbalance persists after connections are confirmed good.",
    ],
    "acoustic_level": [
        "**Stop the motor** and listen closely once it spins down.",
        "**Identify the noise type**: grinding (bearing), whining (electrical), knocking (mechanical looseness).",
        "**Inspect bearings** for wear or lack of lubrication.",
        "**Check belts/couplings** for slippage, wear, or misalignment.",
    ],
    "rpm": [
        "**Stop the motor** — a large speed sag usually means it's fighting a mechanical or electrical problem.",
        "**Check for a jammed or stalled load** on the shaft.",
        "**Check for mechanical overload** beyond the motor's rated capacity.",
        "**Check supply voltage/frequency** — low voltage or wrong frequency reduces speed.",
        "**Inspect for belt slippage** if speed is measured downstream of a belt drive.",
    ],
}

# Preventive measures — what to do so the problem does NOT come back.
# Shown for Warning and Fault, per sensor that tripped.
PREVENTIVE_MEASURES = {
    "temperature": [
        "**Keep cooling clear**: clean vents, fins and fan guards on a regular schedule.",
        "**Keep ambient temperature in range** and leave space around the motor for airflow.",
        "**Stay within rated load and duty cycle** — avoid long overloads and frequent start/stop.",
        "**Lubricate bearings on schedule** — friction is a hidden heat source.",
        "**Fit thermal overload protection** (thermal relay or embedded thermistor) so it trips before damage.",
    ],
    "vibration_rms": [
        "**Re-check mounting bolts and baseplate** at regular intervals.",
        "**Re-align motor and load** after any maintenance or coupling change.",
        "**Grease bearings on schedule** and replace them proactively near end of life.",
        "**Keep the shaft, fan and coupling clean and balanced** — remove debris build-up.",
        "**Trend vibration over time** so a slow rise is caught early.",
    ],
    "current_rms_avg": [
        "**Keep load within the rated capacity**; size the motor with some headroom.",
        "**Keep the drive train free** (bearings, gearbox, belts lubricated) so the motor never drags.",
        "**Test insulation resistance periodically** to catch winding deterioration early.",
        "**Use correctly rated fuses / overload protection.**",
        "**Use soft-start or current limiting** if the motor sees heavy starting current.",
    ],
    "current_imbalance_pct": [
        "**Tighten and inspect terminals periodically** — heating cycles loosen connections.",
        "**Install a phase-loss / phase-failure relay** so single-phasing trips the motor automatically.",
        "**Replace fuses as a matched set** (all three phases together).",
        "**Do a periodic thermal-imaging or temperature check** of terminals and connections.",
        "**Balance single-phase loads across the three phases** on the supply side.",
    ],
    "voltage_rms_avg": [
        "**Use a regulated supply or voltage stabilizer** where the supply fluctuates.",
        "**Check cable sizing and connections** — undersized or loose wiring causes voltage drop.",
        "**Add under/over-voltage protection.**",
        "**For DC systems:** use a regulated supply with current margin and check battery health.",
    ],
    "voltage_imbalance_pct": [
        "**Balance loads across the three phases** upstream of the motor.",
        "**Install a voltage-monitoring / phase-sequence relay.**",
        "**Periodically inspect supply-side connections and transformer taps.**",
        "**Log supply voltage over time** to catch utility-side problems early.",
    ],
    "acoustic_level": [
        "**Follow the bearing lubrication schedule** — and avoid over-greasing.",
        "**Replace worn belts and couplings** before they fail.",
        "**Keep guards and covers secured** and tighten loose components.",
        "**Track acoustic level over time** — a rising trend is an early bearing-wear warning.",
    ],
    "rpm": [
        "**Avoid sudden overloads** and keep load within rated capacity.",
        "**Maintain belt tension** and replace worn belts.",
        "**Keep supply voltage and frequency stable.**",
        "**Keep the drive free to turn** (lubrication, no debris or binding).",
        "**Re-check the speed sensor mounting and marker alignment** so readings stay trustworthy.",
    ],
}

# General routine upkeep, shown when the motor is healthy.
GENERAL_PREVENTIVE = {
    0: [  # DC
        "**Inspect and replace brushes, and clean the commutator** at regular intervals (brushed motors).",
        "**Keep the motor clean and dry**; clear dust from vents.",
        "**Lubricate bearings** per the manufacturer's schedule.",
        "**Check supply wiring and connectors** for looseness or corrosion.",
        "**Log readings regularly** to spot slow drifts before they become faults.",
    ],
    1: [  # AC 3-phase
        "**Tighten and inspect terminal connections** periodically.",
        "**Test insulation resistance** on a schedule.",
        "**Keep phases balanced** and use phase-loss protection.",
        "**Clean vents and lubricate bearings** per the manufacturer's schedule.",
        "**Log readings regularly** to spot slow drifts before they become faults.",
    ],
}

def diagnose(sample):
    motor_type_code = int(sample["motor_type"])
    th_set = THRESHOLDS[motor_type_code]
    issues = []
    for feat, val in sample.items():
        th = th_set.get(feat)
        if not th:
            continue
        severity = None
        if "normal_min" in th:
            if val < th["warning_min"]:
                severity = "Fault"
            elif val < th["normal_min"]:
                severity = "Warning"
        else:
            if val > th["warning_max"]:
                severity = "Fault"
            elif val > th["normal_max"]:
                severity = "Warning"
        if severity:
            issues.append((feat, severity, val))
    issues.sort(key=lambda t: (t[1] != "Fault",))
    return issues

def render_recommendations(container, sample, prediction):
    with container.container():
        st.subheader("Health Summary & Recommended Actions")
        motor_type_code = int(sample["motor_type"])
        motor_label = "DC" if motor_type_code == 0 else "AC (3-phase)"
        st.caption(f"Motor type: {motor_label}")

        if prediction == "Normal":
            st.success("Motor is operating within normal parameters. No action needed.")
            with st.expander("🛡️ Routine preventive maintenance — keep it healthy"):
                for tip in GENERAL_PREVENTIVE[motor_type_code]:
                    st.markdown(f"- {tip}")
            return

        issues = diagnose(sample)

        if prediction == "Fault":
            st.error("**CRITICAL — Fault detected.** Recommended: stop the motor now and inspect before restarting.")
        else:
            st.warning("**Warning — early signs of a developing issue.** Recommended: schedule an inspection soon; keep monitoring.")

        if not issues:
            st.write("Model flagged an anomaly, but no single sensor crossed its threshold — recommend a general inspection.")
            st.markdown("### 🛡️ Preventive Measures — keep it from happening again")
            for tip in GENERAL_PREVENTIVE[motor_type_code]:
                st.markdown(f"- {tip}")
            return

        for feat, severity, val in issues:
            unit = THRESHOLDS[motor_type_code][feat]["unit"]
            icon = "🔴" if severity == "Fault" else "🟠"
            st.markdown(f"{icon} **{LABELS[feat]}** — {val:.3g} {unit} ({severity})")
            st.caption(ACTIONS[feat][severity])

        # Prominent, step-by-step corrective measures for whatever caused the Fault
        fault_issues = [i for i in issues if i[1] == "Fault"]
        if fault_issues:
            st.markdown("---")
            st.markdown("### 🛠️ Corrective Measures to Resolve This")
            st.caption("Always isolate power (lock-out / tag-out) before opening the motor or touching its wiring.")
            seen = set()
            for feat, severity, val in fault_issues:
                if feat in seen:
                    continue
                seen.add(feat)
                st.markdown(f"**{LABELS[feat]} fault — recommended steps:**")
                for i, step in enumerate(RESOLUTION_STEPS.get(feat, []), start=1):
                    st.markdown(f"{i}. {step}")
                st.markdown("")

        # Preventive measures for every sensor that tripped (Warning or Fault)
        st.markdown("---")
        st.markdown("### 🛡️ Preventive Measures — keep it from happening again")
        seen = set()
        for feat, severity, val in issues:
            if feat in seen:
                continue
            seen.add(feat)
            st.markdown(f"**{LABELS[feat]}:**")
            for tip in PREVENTIVE_MEASURES.get(feat, []):
                st.markdown(f"- {tip}")

st.sidebar.header("Simulation Controls")
motor_type_label = st.sidebar.radio("Motor type", ["DC", "AC (3-phase)"])
motor_type_code = 0 if motor_type_label == "DC" else 1
scenario = st.sidebar.selectbox(
    "Scenario",
    ["Auto (drift over time)", "Force: Normal", "Force: Warning", "Force: Fault"],
)
refresh_rate = st.sidebar.slider("Refresh interval (seconds)", 0.5, 3.0, 1.0, 0.5)
run = st.sidebar.toggle("Run simulation", value=True)
reset = st.sidebar.button("Reset history")

if "history" not in st.session_state or reset or st.session_state.get("last_motor_type") != motor_type_code:
    st.session_state.history = pd.DataFrame(columns=FEATURES + ["condition", "time"])
    st.session_state.alerts = []
    st.session_state.drift_state = "Normal"
    st.session_state.tick = 0
    st.session_state.last_motor_type = motor_type_code

status_col, sensor_col, log_col = st.columns([1, 2, 1])
status_placeholder = status_col.empty()
votes_placeholder = status_col.empty()
sensor_placeholder = sensor_col.empty()
chart_placeholder = sensor_col.empty()
log_placeholder = log_col.empty()
recommendation_placeholder = st.empty()

COLOR = {"Normal": "green", "Warning": "orange", "Fault": "red"}

def render(sample, prediction, proba, classes):
    with status_placeholder.container():
        st.subheader("Motor Status")
        color = COLOR.get(prediction, "gray")
        st.markdown(
            f"<div style='padding:20px;border-radius:8px;background-color:{color}22;"
            f"border:1px solid {color};text-align:center;'>"
            f"<span style='font-size:28px;font-weight:700;color:{color};'>{prediction.upper()}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    with votes_placeholder.container():
        st.subheader("Class Probabilities")
        for cls, p in zip(classes, proba):
            st.write(f"{cls}: {p*100:.1f}%")
            st.progress(float(p))

    with sensor_placeholder.container():
        st.subheader("Live Sensor Readings")
        r1c1, r1c2, r1c3 = st.columns(3)
        r1c1.metric("Temperature", f"{sample['temperature']:.1f} °C")
        r1c2.metric("Vibration RMS", f"{sample['vibration_rms']:.3f} g")
        r1c3.metric("Current (avg)", f"{sample['current_rms_avg']:.2f} A")
        r2c1, r2c2, r2c3 = st.columns(3)
        r2c1.metric("Voltage (avg)", f"{sample['voltage_rms_avg']:.1f} V")
        r2c2.metric("Acoustic", f"{sample['acoustic_level']:.1f} dB")
        r2c3.metric("Speed", f"{sample['rpm']:.0f} RPM")
        if sample["motor_type"] == 1:
            r3c1, r3c2 = st.columns(2)
            r3c1.metric("Current imbalance", f"{sample['current_imbalance_pct']:.2f} %")
            r3c2.metric("Voltage imbalance", f"{sample['voltage_imbalance_pct']:.2f} %")

    with chart_placeholder.container():
        st.subheader("Trend — last 40 readings")
        if len(st.session_state.history) > 1:
            chart_df = st.session_state.history.tail(40).set_index("time")[["temperature", "current_rms_avg"]]
            st.line_chart(chart_df)

    with log_placeholder.container():
        st.subheader("Alert Log")
        if len(st.session_state.alerts) == 0:
            st.write("No warnings or faults yet")
        else:
            for a in reversed(st.session_state.alerts[-20:]):
                st.markdown(f"**{a['time']}** — {a['condition']}: {a['detail']}")

    render_recommendations(recommendation_placeholder, sample, prediction)

if run:
    st.session_state.tick += 1

    if scenario == "Auto (drift over time)":
        if st.session_state.tick % 8 == 0:
            st.session_state.drift_state = random.choices(
                ["Normal", "Warning", "Fault"], weights=[0.6, 0.25, 0.15]
            )[0]
        true_state = st.session_state.drift_state
    else:
        true_state = scenario.split(": ")[1]

    sample = sample_reading(motor_type_code, true_state)
    X = pd.DataFrame([sample])[FEATURES]

    prediction = model.predict(X)[0]
    proba = model.predict_proba(X)[0]
    classes = model.classes_

    row = dict(sample)
    row["condition"] = prediction
    row["time"] = time.strftime("%H:%M:%S")
    st.session_state.history = pd.concat([st.session_state.history, pd.DataFrame([row])], ignore_index=True)

    if prediction != "Normal":
        st.session_state.alerts.append({
            "time": row["time"],
            "condition": prediction,
            "detail": f"temp {sample['temperature']:.1f}°C, vib {sample['vibration_rms']:.3f}g, cur {sample['current_rms_avg']:.2f}A",
        })

    render(sample, prediction, proba, classes)
    time.sleep(refresh_rate)
    st.rerun()
else:
    if len(st.session_state.history) > 0:
        last = st.session_state.history.iloc[-1]
        sample = {f: last[f] for f in FEATURES}
        X = pd.DataFrame([sample])[FEATURES]
        prediction = model.predict(X)[0]
        proba = model.predict_proba(X)[0]
        render(sample, prediction, proba, model.classes_)
    else:
        st.info("Simulation paused. Toggle 'Run simulation' in the sidebar to start.")
