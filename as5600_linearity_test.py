"""
AS5600 Linearity Test
- Step motor through full revolution in known increments
- Record AS5600 angle at each position
- Save CSV data to file for analysis
"""
import board
import time
import digitalio
import adafruit_as5600
import adafruit_displayio_sh1107
import displayio
import terminalio
from adafruit_display_text import label

# Motor pins (same as code.py)
STEP_PIN = board.IO12
DIR_PIN = board.IO5
EN_PIN = board.IO6
MS_PIN = board.IO17  # Microstep mode (HIGH = 32 microsteps)

STEPS_PER_REV = 12800  # 400 * 32 microsteps
TEST_INCREMENTS = 64   # Number of measurement points
STEPS_PER_INCREMENT = STEPS_PER_REV // TEST_INCREMENTS  # 200 steps each
STEP_DELAY = 0.001     # Slower stepping for smoother motion
SETTLE_TIME = 0.5      # Time to wait after moving before reading

OUTPUT_FILE = "/linearity_data.csv"  # Save to CIRCUITPY root

# Release any existing displays
displayio.release_displays()

# Setup I2C
i2c = board.I2C()

# Setup OLED display
display_bus = displayio.I2CDisplay(i2c, device_address=0x3C)
display = adafruit_displayio_sh1107.SH1107(display_bus, width=128, height=64)

# Create display group
group = displayio.Group()
display.root_group = group

# Create text labels
title_label = label.Label(terminalio.FONT, text="AS5600 Test", x=0, y=6)
status_label = label.Label(terminalio.FONT, text="Init...", x=0, y=20)
progress_label = label.Label(terminalio.FONT, text="", x=0, y=34)
data_label = label.Label(terminalio.FONT, text="", x=0, y=48)

group.append(title_label)
group.append(status_label)
group.append(progress_label)
group.append(data_label)

def update_display(status="", progress="", data=""):
    if status:
        status_label.text = status[:21]
    if progress:
        progress_label.text = progress[:21]
    if data:
        data_label.text = data[:21]
    display.refresh()

update_display("Init sensor...")

# Setup AS5600
sensor = adafruit_as5600.AS5600(i2c)

print("AS5600 Linearity Test")
print(f"Magnet detected: {sensor.magnet_detected}")
print(f"AGC: {sensor.agc}")
print(f"Magnitude: {sensor.magnitude}")

if not sensor.magnet_detected:
    update_display("NO MAGNET!", "Check sensor", "Aborting...")
    print("ERROR: No magnet detected. Aborting.")
    while True:
        pass

update_display(f"Magnet OK", f"AGC:{sensor.agc}", f"Mag:{sensor.magnitude}")

# Setup motor pins
step = digitalio.DigitalInOut(STEP_PIN)
step.direction = digitalio.Direction.OUTPUT
step.value = False

dir_pin = digitalio.DigitalInOut(DIR_PIN)
dir_pin.direction = digitalio.Direction.OUTPUT
dir_pin.value = True  # CW direction

en = digitalio.DigitalInOut(EN_PIN)
en.direction = digitalio.Direction.OUTPUT
en.value = True  # Disabled initially

ms = digitalio.DigitalInOut(MS_PIN)
ms.direction = digitalio.Direction.OUTPUT
ms.value = True  # 32 microsteps


def oneStep(delay=STEP_DELAY):
    """Execute one motor step"""
    step.value = True
    time.sleep(delay)
    step.value = False
    time.sleep(delay)


def multiStep(n, delay=STEP_DELAY):
    """Execute multiple motor steps"""
    for _ in range(n):
        oneStep(delay)


print()
print("Starting in 3 seconds...")
print("Data will be saved to:", OUTPUT_FILE)
update_display("Starting...", "Wait 3 sec", OUTPUT_FILE)
time.sleep(3)

# Enable motor
en.value = False  # Active low
time.sleep(0.1)

# Open file for writing
print("Running test...")
update_display("Running test", "Opening file...", "")
data_points = []
total_steps = 0

with open(OUTPUT_FILE, "w") as f:
    f.write("step_count,expected_angle,as5600_raw,as5600_deg,error_deg\n")

    for i in range(TEST_INCREMENTS + 1):
        # Update display with progress
        update_display("Testing...", f"Point {i+1}/{TEST_INCREMENTS+1}", f"Steps: {total_steps}")

        # Settle time for motor vibration to damp out
        time.sleep(SETTLE_TIME)

        # Read AS5600 (average of 5 readings for stability)
        readings = [sensor.angle for _ in range(5)]
        raw = sum(readings) // 5
        measured_deg = raw * 360.0 / 4096.0

        # Calculate expected angle
        expected_deg = (total_steps / STEPS_PER_REV) * 360.0

        # Calculate error (handle wrap-around)
        error = measured_deg - expected_deg
        if error > 180:
            error -= 360
        elif error < -180:
            error += 360

        # Write CSV line to file
        line = f"{total_steps},{expected_deg:.2f},{raw},{measured_deg:.2f},{error:.2f}\n"
        f.write(line)
        f.flush()  # Ensure data is written

        # Store for summary
        data_points.append((total_steps, expected_deg, raw, measured_deg, error))

        # Progress indicator
        print(f"  Point {i+1}/{TEST_INCREMENTS+1}: raw={raw}, error={error:.2f} deg")
        update_display("Testing...", f"Point {i+1}/{TEST_INCREMENTS+1}", f"raw={raw} e={error:.1f}")

        # Move to next position (except on last iteration)
        if i < TEST_INCREMENTS:
            multiStep(STEPS_PER_INCREMENT)
            total_steps += STEPS_PER_INCREMENT

print()
print("Test complete!")
update_display("Calculating...", "Results", "")

# Disable motor
en.value = True

# Summary statistics
errors = [abs(d[4]) for d in data_points]
max_error = max(errors)
avg_error = sum(errors) / len(errors)
min_raw = min(d[2] for d in data_points)
max_raw = max(d[2] for d in data_points)

print()
print("=== SUMMARY ===")
print(f"Data points: {len(data_points)}")
print(f"AS5600 raw range: {min_raw} to {max_raw}")
print(f"Max absolute error: {max_error:.2f} degrees")
print(f"Avg absolute error: {avg_error:.2f} degrees")

if max_error < 2.0:
    result = "PASS"
    result_full = "PASS - Linearity is acceptable (< 2 deg error)"
elif max_error < 5.0:
    result = "MARGINAL"
    result_full = "MARGINAL - Some non-linearity detected (2-5 deg error)"
else:
    result = "FAIL"
    result_full = "FAIL - Significant non-linearity (> 5 deg error)"

print(f"RESULT: {result_full}")
print()
print(f"Data saved to: {OUTPUT_FILE}")
print("Motor disabled. Test complete.")

# Write summary to file too
with open("/linearity_summary.txt", "w") as f:
    f.write(f"Data points: {len(data_points)}\n")
    f.write(f"AS5600 raw range: {min_raw} to {max_raw}\n")
    f.write(f"Max absolute error: {max_error:.2f} degrees\n")
    f.write(f"Avg absolute error: {avg_error:.2f} degrees\n")
    f.write(f"RESULT: {result_full}\n")

# Show final result on OLED
update_display(f"DONE: {result}", f"MaxErr:{max_error:.1f}deg", f"AvgErr:{avg_error:.1f}deg")

# Stay alive so user knows it's done
while True:
    time.sleep(1)
