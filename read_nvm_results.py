"""Read linearity test results from NVM - with OLED display"""
import board
import microcontroller
import struct
import displayio
import terminalio
import i2cdisplaybus
import adafruit_displayio_sh1107
from adafruit_display_text import label
import time

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

line1 = label.Label(terminalio.FONT, text="NVM Results", color=0xFFFFFF, x=0, y=6)
line2 = label.Label(terminalio.FONT, text="Reading...", color=0xFFFFFF, x=0, y=20)
line3 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=0, y=34)
line4 = label.Label(terminalio.FONT, text="", color=0xFFFFFF, x=0, y=48)
screen.append(line1)
screen.append(line2)
screen.append(line3)
screen.append(line4)

try:
    nvm = microcontroller.nvm

    if nvm[0] != 0xBB:
        line1.text = "NO DATA"
        line2.text = f"Marker: {hex(nvm[0])}"
        line3.text = "Run test first"
        line4.text = ""
    else:
        result_code = nvm[1]
        result_names = ["PASS", "MARGINAL", "FAIL"]
        result = result_names[result_code] if result_code < 3 else "?"

        max_err = struct.unpack('<f', bytes(nvm[2:6]))[0]
        avg_err = struct.unpack('<f', bytes(nvm[6:10]))[0]
        num_points = nvm[10]

        line1.text = f"Result: {result}"
        line2.text = f"Max: {max_err:.2f} deg"
        line3.text = f"Avg: {avg_err:.2f} deg"
        line4.text = f"Points: {num_points}"

        # Print details to serial
        print(f"Result: {result}")
        print(f"Max error: {max_err:.2f} deg")
        print(f"Avg error: {avg_err:.2f} deg")
        print(f"Points: {num_points}")
        print()
        for i in range(min(num_points, 33)):
            err_int = struct.unpack('<h', bytes(nvm[11 + i*2 : 13 + i*2]))[0]
            err = err_int / 100.0
            raw = struct.unpack('<H', bytes(nvm[75 + i*2 : 77 + i*2]))[0]
            print(f"Pt {i+1}: err={err:+.2f} raw={raw}")

except Exception as e:
    line1.text = "ERROR"
    line2.text = str(e)[:20]
    line3.text = ""
    line4.text = ""
    print(f"Error: {e}")

while True:
    time.sleep(1)
