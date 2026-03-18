"""
AS5600 Test using official Adafruit CircuitPython library
With OLED display output
"""

import board
import time
import displayio
import terminalio
import i2cdisplaybus
import adafruit_displayio_sh1107
from adafruit_display_text import label
import adafruit_as5600

# Display constants
DISPLAY_ADDR = 0x3C
DISPLAY_WIDTH = 128
DISPLAY_HEIGHT = 64

def setup_display(i2c):
    displayio.release_displays()
    display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=DISPLAY_ADDR)
    display = adafruit_displayio_sh1107.SH1107(
        display_bus, width=DISPLAY_WIDTH, height=DISPLAY_HEIGHT
    )

    screen = displayio.Group()

    # Black background
    color_bitmap = displayio.Bitmap(DISPLAY_WIDTH, DISPLAY_HEIGHT, 1)
    color_palette = displayio.Palette(1)
    color_palette[0] = 0x000000
    bg_sprite = displayio.TileGrid(color_bitmap, pixel_shader=color_palette, x=0, y=0)
    screen.append(bg_sprite)

    display.root_group = screen

    title = label.Label(
        terminalio.FONT, text="AS5600 Angle", color=0xFFFFFF,
        anchor_point=(0.5, 0), anchored_position=(64, 0)
    )
    screen.append(title)

    angle_label = label.Label(
        terminalio.FONT, text="---.-", color=0xFFFFFF, scale=2,
        anchor_point=(0.5, 0.5), anchored_position=(64, 28)
    )
    screen.append(angle_label)

    raw_label = label.Label(
        terminalio.FONT, text="Raw: ----", color=0xFFFFFF,
        anchor_point=(0.5, 0), anchored_position=(64, 46)
    )
    screen.append(raw_label)

    status_label = label.Label(
        terminalio.FONT, text="", color=0xFFFFFF,
        anchor_point=(0.5, 0), anchored_position=(64, 56)
    )
    screen.append(status_label)

    return angle_label, raw_label, status_label

# Initialize
i2c = board.I2C()

print("AS5600 Official Library Test")
angle_label, raw_label, status_label = setup_display(i2c)
print("Display initialized")

sensor = adafruit_as5600.AS5600(i2c)
print(f"Magnet detected: {sensor.magnet_detected}")
print(f"AGC: {sensor.agc}")
print(f"Magnitude: {sensor.magnitude}")
print()

count = 0

while True:
    angle = sensor.angle  # Use scaled angle (full 360°)
    degrees = angle * 360.0 / 4096.0

    # Update display
    angle_label.text = f"{degrees:.1f}"
    raw_label.text = f"Raw: {angle}"

    # Update status periodically
    if count == 0:
        agc = sensor.agc
        mag = sensor.magnitude
        if not sensor.magnet_detected:
            status_label.text = "NO MAGNET"
        elif sensor.max_gain_overflow:
            status_label.text = f"WEAK A:{agc}"
        elif sensor.min_gain_overflow:
            status_label.text = f"STRONG A:{agc}"
        else:
            status_label.text = f"AGC:{agc} M:{mag}"

    count = (count + 1) % 20
    if count == 0:
        print(f"angle={angle:4d} deg={degrees:5.1f} AGC={sensor.agc}")

    time.sleep(0.05)
