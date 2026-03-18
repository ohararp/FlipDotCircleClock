"""
AS5600 Linearity Test
Homes to 12 o'clock first using hall sensor, then tests linearity
Saves results to NVM for later retrieval
"""
import board
import time
import digitalio
import displayio
import terminalio
import i2cdisplaybus
import adafruit_displayio_sh1107
from adafruit_display_text import label
import adafruit_as5600
import microcontroller
import struct

# Motor pins
STEP_PIN = board.IO12
DIR_PIN = board.IO5
EN_PIN = board.IO6
MS_PIN = board.IO17
HALL_PIN = board.IO14

STEPS_PER_REV = 12800
TEST_INCREMENTS = 32
STEPS_PER_INCREMENT = STEPS_PER_REV // TEST_INCREMENTS
STEP_DELAY = 0.001
SETTLE_TIME = 0.3

# Display setup
displayio.release_displays()
i2c = board.I2C()
display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)
display = adafruit_displayio_sh1107.SH1107(display_bus, width=128, height=64)

screen = displayio.Group()
color_bitmap = displayio.Bitmap(128, 64, 1)
color_palette = displayio.Palette(1)
color_palette[0] = 0x000000
bg_sprite = displayio.TileGrid(color_bitmap, pixel_shader=color_palette, x=0, y=0)
screen.append(bg_sprite)
display.root_group = screen

line1 = label.Label(terminalio.FONT, text="Linearity Test", color=0xFFFFFF, x=0, y=6)
line2 = label.Label(terminalio.FONT, text="Init...", color=0xFFFFFF, x=0, y=20)
line3 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=0, y=34)
line4 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=0, y=48)
screen.append(line1)
screen.append(line2)
screen.append(line3)
screen.append(line4)

def show(l2="", l3="", l4=""):
    if l2: line2.text = l2[:21]
    if l3: line3.text = l3[:21]
    if l4: line4.text = l4[:21]

print("Linearity Test Starting")

# Setup AS5600
sensor = adafruit_as5600.AS5600(i2c)
if not sensor.magnet_detected:
    show("NO MAGNET!", "Check AS5600", "Aborting")
    print("No magnet detected")
    while True: pass

show(f"Magnet OK", f"AGC:{sensor.agc}", f"Mag:{sensor.magnitude}")
print(f"Magnet OK - AGC:{sensor.agc} Mag:{sensor.magnitude}")
time.sleep(1)

# Setup motor pins
step = digitalio.DigitalInOut(STEP_PIN)
step.direction = digitalio.Direction.OUTPUT
step.value = False

dir_pin = digitalio.DigitalInOut(DIR_PIN)
dir_pin.direction = digitalio.Direction.OUTPUT
dir_pin.value = True

en = digitalio.DigitalInOut(EN_PIN)
en.direction = digitalio.Direction.OUTPUT
en.value = True  # Disabled

ms = digitalio.DigitalInOut(MS_PIN)
ms.direction = digitalio.Direction.OUTPUT
ms.value = True  # 32 microsteps

# Setup hall sensor
hall = digitalio.DigitalInOut(HALL_PIN)
hall.direction = digitalio.Direction.INPUT
hall.pull = digitalio.Pull.UP

def setDir(cw):
    dir_pin.value = cw

def oneStep(cw=True):
    setDir(cw)
    step.value = True
    time.sleep(STEP_DELAY)
    step.value = False
    time.sleep(STEP_DELAY)

def multiStep(n, cw=True):
    for _ in range(n):
        oneStep(cw)

def hallStable(expected, samples=5):
    for _ in range(samples):
        if hall.value != expected:
            return False
        time.sleep(0.0005)
    return True

def findHome():
    """Find magnet center using hall sensor edge detection"""
    show("Homing...", "Finding magnet", "")
    print("Homing: Finding magnet zone")

    # Step CW until hall triggers (enter magnet zone)
    count = 0
    while not hallStable(False):
        oneStep(True)
        count += 1
        if count > STEPS_PER_REV:
            show("HOMING FAIL", "No magnet found", "")
            print("Homing failed - no magnet")
            return False

    # Reverse until hall releases (edge A)
    show("Homing...", "Finding edge A", "")
    print("Finding edge A")
    edge_a_steps = 0
    while not hallStable(True):
        oneStep(False)
        edge_a_steps += 1

    # Continue reversing until hall triggers again
    show("Homing...", "Crossing magnet", "")
    print("Crossing magnet")
    while not hallStable(False):
        oneStep(False)

    # Reverse (forward) until hall releases (edge B)
    show("Homing...", "Finding edge B", "")
    print("Finding edge B")
    edge_b_steps = 0
    while not hallStable(True):
        oneStep(True)
        edge_b_steps += 1

    # Calculate center offset from current position
    # We're at edge B, need to go back half the magnet width
    # But we measured from edge A to edge B going CCW then CW
    # The magnet width in CW direction from edge B is edge_b_steps
    # Go CW half the magnet width to reach center
    magnet_width = edge_b_steps
    center_offset = magnet_width // 2

    show("Homing...", f"Width: {magnet_width}", f"Moving to center")
    print(f"Magnet width: {magnet_width} steps, moving {center_offset} to center")

    # Move CCW to center (we're at edge B, center is CCW)
    multiStep(center_offset, False)

    show("Homed!", "At 12 o'clock", "")
    print("Homed to 12 o'clock position")
    return True

# Enable motor
en.value = False
time.sleep(0.1)

# Home first
if not findHome():
    en.value = True
    while True: pass

time.sleep(1)

# Record starting AS5600 angle (should be ~0 or ~4096 at 12:00)
start_angle = sensor.angle
start_deg = start_angle * 360.0 / 4096.0
show("Home angle:", f"raw={start_angle}", f"deg={start_deg:.1f}")
print(f"Starting angle: raw={start_angle}, deg={start_deg:.1f}")
time.sleep(2)

show("Starting test", "3 seconds...", "")
print("Starting linearity test in 3 seconds...")
time.sleep(3)

# Run test - store raw angles for analysis
errors = []
raw_angles = []
total_steps = 0
max_err = 0.0

print("step,expected,raw,measured,error")

for i in range(TEST_INCREMENTS + 1):
    show(f"Point {i+1}/{TEST_INCREMENTS+1}", f"Steps: {total_steps}", "Measuring...")
    time.sleep(SETTLE_TIME)

    # Read angle (average of 5)
    readings = [sensor.angle for _ in range(5)]
    raw = sum(readings) // 5
    raw_angles.append(raw)

    measured = raw * 360.0 / 4096.0
    # Expected is relative to starting angle
    expected = start_deg + (total_steps / STEPS_PER_REV) * 360.0
    if expected >= 360: expected -= 360

    error = measured - expected
    if error > 180: error -= 360
    elif error < -180: error += 360

    errors.append(error)  # Store signed error
    if abs(error) > max_err:
        max_err = abs(error)

    print(f"{total_steps},{expected:.1f},{raw},{measured:.1f},{error:.2f}")
    show(f"Point {i+1}/{TEST_INCREMENTS+1}", f"raw={raw}", f"err={error:.1f} max={max_err:.1f}")

    if i < TEST_INCREMENTS:
        multiStep(STEPS_PER_INCREMENT, True)
        total_steps += STEPS_PER_INCREMENT

# Done
en.value = True
abs_errors = [abs(e) for e in errors]
avg_err = sum(abs_errors) / len(abs_errors)

if max_err < 2.0:
    result = "PASS"
    result_code = 0
elif max_err < 5.0:
    result = "MARGINAL"
    result_code = 1
else:
    result = "FAIL"
    result_code = 2

# Save results to NVM
nvm = microcontroller.nvm
nvm[0] = 0xBB  # Marker for linearity test data
nvm[1] = result_code
nvm[2:6] = struct.pack('<f', max_err)
nvm[6:10] = struct.pack('<f', avg_err)
nvm[10] = len(errors)
# Store signed errors (error * 100)
for idx, err in enumerate(errors[:32]):
    err_int = int(err * 100)
    err_int = max(-32768, min(32767, err_int))
    nvm[11 + idx*2 : 13 + idx*2] = struct.pack('<h', err_int)
# Store raw angles (2 bytes each) starting at offset 75
for idx, raw in enumerate(raw_angles[:32]):
    nvm[75 + idx*2 : 77 + idx*2] = struct.pack('<H', raw)

print("Results saved to NVM")

line1.text = f"DONE: {result}"
show(f"MaxErr: {max_err:.1f} deg", f"AvgErr: {avg_err:.1f} deg", "Saved to NVM")

print()
print(f"RESULT: {result}")
print(f"Max error: {max_err:.2f} deg")
print(f"Avg error: {avg_err:.2f} deg")

while True:
    time.sleep(1)
