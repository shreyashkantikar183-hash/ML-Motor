"""
collect_real_data.py
Logs labeled real sensor readings from the ESP32 (over USB serial) to build
a real-world training set covering both DC and 3-phase AC motors.

Expects lines from the firmware in the format:
    DATA,motor_type,temperature,vibration_rms,current_rms_avg,current_imbalance_pct,
         voltage_rms_avg,voltage_imbalance_pct,acoustic_level,rpm,condition
(11 comma-separated fields total, first one literally "DATA")

We ignore the device's own predicted condition and log the ground-truth label
you enter below instead.
"""

import csv
import os
import time
import serial
import serial.tools.list_ports

OUTPUT_FILE = "real_motor_data.csv"
HEADER = [
    "motor_type", "temperature", "vibration_rms",
    "current_rms_avg", "current_imbalance_pct",
    "voltage_rms_avg", "voltage_imbalance_pct",
    "acoustic_level", "rpm", "condition",
]


def pick_port():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    if not ports:
        print("No COM ports found. Is the ESP32 plugged in?")
        exit(1)
    print("Available ports:")
    for i, p in enumerate(ports):
        print(f"  [{i}] {p}")
    choice = int(input("Select port number: "))
    return ports[choice]


def parse_line(line):
    parts = line.strip().split(",")
    if len(parts) != 11 or parts[0] != "DATA":
        return None
    try:
        return {
            "motor_type": int(float(parts[1])),
            "temperature": float(parts[2]),
            "vibration_rms": float(parts[3]),
            "current_rms_avg": float(parts[4]),
            "current_imbalance_pct": float(parts[5]),
            "voltage_rms_avg": float(parts[6]),
            "voltage_imbalance_pct": float(parts[7]),
            "acoustic_level": float(parts[8]),
            "rpm": float(parts[9]),
        }
    except ValueError:
        return None


def main():
    port = pick_port()
    baud = 115200

    label = input("What condition are you inducing right now? (Normal / Warning / Fault): ").strip()
    if label not in ("Normal", "Warning", "Fault"):
        print("Label must be exactly one of: Normal, Warning, Fault")
        exit(1)

    file_exists = os.path.isfile(OUTPUT_FILE)

    ser = serial.Serial(port, baud, timeout=2)
    time.sleep(2)

    print(f"\nLogging '{label}' readings to {OUTPUT_FILE}. Press Ctrl+C to stop this session.\n")
    print("Note: motor_type (0=DC, 1=AC) is read automatically from the firmware's DATA line.\n")

    count = 0
    with open(OUTPUT_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(HEADER)

        try:
            while True:
                raw_line = ser.readline().decode("utf-8", errors="ignore")
                parsed = parse_line(raw_line)
                if parsed is None:
                    continue

                row = [
                    parsed["motor_type"],
                    parsed["temperature"],
                    parsed["vibration_rms"],
                    parsed["current_rms_avg"],
                    parsed["current_imbalance_pct"],
                    parsed["voltage_rms_avg"],
                    parsed["voltage_imbalance_pct"],
                    parsed["acoustic_level"],
                    parsed["rpm"],
                    label,
                ]
                writer.writerow(row)
                f.flush()
                count += 1
                mtype = "DC" if parsed["motor_type"] == 0 else "AC"
                print(f"[{count}] type={mtype} temp={parsed['temperature']:.1f} vib={parsed['vibration_rms']:.4f} "
                      f"cur_avg={parsed['current_rms_avg']:.2f} cur_imb={parsed['current_imbalance_pct']:.2f}% "
                      f"volt_avg={parsed['voltage_rms_avg']:.1f} volt_imb={parsed['voltage_imbalance_pct']:.2f}% "
                      f"ac={parsed['acoustic_level']:.1f} rpm={parsed['rpm']:.0f}  -> logged as {label}")

        except KeyboardInterrupt:
            print(f"\nStopped. Logged {count} readings for '{label}' this session.")
            print(f"Run this script again to log another condition or another session.")

    ser.close()


if __name__ == "__main__":
    main()
