#%%----------------------------------------------------------------------------
# FlipDotCircleClock - CircuitPython Flip Dot Clock with Mechanical Minute Hand
#
# Requires: CircuitPython 10.x (tested on 10.1.4)
#
# Supported Hardware:
#   - UnexpectedMaker Feather S2 (ESP32-S2)
#   - UnexpectedMaker Feather S3 (ESP32-S3)
#
# Required External Hardware:
#   - Flip Dot Display (4-column matrix) via SPI
#   - Stepper Motor: MT-1701HSM140AE (0.9°/400 steps) or similar
#   - Stepper Driver: TMC2209 (recommended) or A4988/DRV8825
#   - Hall Effect Sensor for home position detection
#   - DS3231 RTC Module (I2C)
#   - SH1107 128x64 OLED Display (I2C)
#   - 24V Relay Module for flip dot power
#   - 3x Momentary Push Buttons
#   - 24V Power Supply for flip dots
#   - Magnet on minute hand for hall sensor
#
# Pin Configuration (same for S2 and S3):
#   SPI (Flip Dots): SCK=IO36, MOSI=IO35, LATCH=IO37, OE=IO18
#   Stepper: EN=IO6, STEP=IO12, DIR=IO5, HOME=IO14, MS1=IO17
#
# TMC2209 Configuration:
#   - MS1 (IO17) = HIGH, MS2 floating = 32 microsteps
#   - With 0.9° motor (400 steps): 400 × 32 = 12800 steps/rev
#   - StealthChop provides silent operation
#   Buttons: A=IO1, B=IO38, C=IO33
#   Relay: IO11
#   I2C: SDA/SCL (default pins)
#   LED: DotStar (S2) or NeoPixel (S3) - auto-detected
#
#%%----------------------------------------------------------------------------
# General Libraries
import time, gc, os
import rtc
import board
import digitalio
import displayio
import terminalio
import simpleio
import random as r

#RTC Libraries
import adafruit_ds3231

# AS5600 Magnetic Angle Sensor (optional closed-loop control)
try:
    import adafruit_as5600
    AS5600_AVAILABLE = True
except ImportError:
    AS5600_AVAILABLE = False
    print("AS5600 library not found - closed-loop disabled")

# Display Libraries
from adafruit_display_text import label
import adafruit_displayio_sh1107
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_display_shapes.circle import Circle
import i2cdisplaybus

# WIFI Libraries
import ssl
import wifi
import socketpool
import adafruit_requests
import adafruit_ntp
import json
import microcontroller

# Web Server Libraries
from adafruit_httpserver import Server, Request, Response, POST

# LED Libraries - auto-detect board type
# Feather S2 uses DotStar (APA102), Feather S3 uses NeoPixel (WS2812)
BOARD_TYPE = "unknown"
if hasattr(board, 'APA102_SCK'):
    # Feather S2 - has DotStar LED
    import adafruit_dotstar
    BOARD_TYPE = "feather_s2"
elif hasattr(board, 'NEOPIXEL'):
    # Feather S3 - has NeoPixel LED
    import neopixel
    BOARD_TYPE = "feather_s3"
else:
    # Fallback - try DotStar
    try:
        import adafruit_dotstar
        BOARD_TYPE = "feather_s2"
    except ImportError:
        import neopixel
        BOARD_TYPE = "feather_s3"

print(f"Detected board type: {BOARD_TYPE}")


# Panel Header
# |- SCK      - SCK (IO36)
# |- MOSI     - SDO (IO35)
# |- SS/LATCH - SPI (IO37)
# |- GND

# Use FeatherS2 SPI Port
clockPin = digitalio.DigitalInOut(board.SCK)
dataPin = digitalio.DigitalInOut(board.IO35)
latchPin = digitalio.DigitalInOut(board.IO37)
oePin = digitalio.DigitalInOut(board.IO18)

clockPin.direction = digitalio.Direction.OUTPUT
dataPin.direction = digitalio.Direction.OUTPUT
latchPin.direction = digitalio.Direction.OUTPUT
oePin.direction = digitalio.Direction.OUTPUT

# disable outputs (or True, depending on your OE polarity)
clockPin.value = False
dataPin.value = False
latchPin.value = False
oePin.value = False

# OE Clarity
OE_ENABLE  = True
OE_DISABLE = False
oePin.value = OE_DISABLE

# Initialize Step Counter
stepNow = 0
lastHourShown = None

# AS5600 sensor (initialized later if available)
as5600_sensor = None
as5600_home_offset = 0  # AS5600 raw value at 12 o'clock - auto-detected after homing

# Calibration mode (Button C long-press or web UI)
calibration_mode = False  # True when in calibration mode - motor disabled for manual positioning
 
# Stepper Motor Setup
motorEnabled  = False   # active-low
motorDisabled = True

# Relay Setup
relayPrechargeS = 0.20   # seconds to let 24V rails charge
relayHoldS      = 0.08   # seconds to keep rails up after last flip

# Flipdot timing (seconds between actuations, allows capacitor recharge)
flipdotDelay = 0.5

flipPwrIsOn = False
flipPwrOffAtS = 0.0

# Init Time Variables
secOld = 255
minOld = 255
hrOld  = 255

# Web Server Variables
server = None
action_log = []
LOG_MAX = 50
start_time = 0
last_wifi_sync_time = "Never"

# WiFi state machine
WIFI_DISCONNECTED = 0  # Not connected, will attempt connection
WIFI_CONNECTING = 1    # Currently attempting to connect
WIFI_CONNECTED = 2     # Connected with working server
WIFI_OFFLINE = 3       # Failed, no auto-retry (manual or top-of-hour only)
wifi_state = WIFI_DISCONNECTED
WIFI_STATE_NAMES = ["DISCONNECTED", "CONNECTING", "CONNECTED", "OFFLINE"]

# Network health tracking
last_successful_poll = 0
poll_failure_count = 0
POLL_HEALTH_TIMEOUT = 60  # Seconds without successful poll = unhealthy
POLL_FAILURE_THRESHOLD = 5  # Consecutive failures before triggering recovery

# WiFi recovery settings
NVM_WIFI_RESET_COUNT = 200   # NVM offset for reset counter
NVM_WIFI_RESET_MARKER = 201  # NVM offset for marker byte
WIFI_RESET_MARKER = 0xAA     # Marker value indicating WiFi failure reset
MAX_WIFI_RESETS = 3          # Max consecutive resets before offline mode
OFFLINE_RETRY_AT_TOP_OF_HOUR = True  # Retry WiFi at top of each hour
last_wifi_retry_hour = -1    # Track last retry hour to avoid duplicates
LONG_PRESS_THRESHOLD = 2.0   # Seconds to hold button A for WiFi reconnect

def set_wifi_state(new_state, update_ui=True):
    """Set WiFi state and optionally update display."""
    global wifi_state
    old_state = wifi_state
    wifi_state = new_state
    print("WiFi state: %s -> %s" % (WIFI_STATE_NAMES[old_state], WIFI_STATE_NAMES[new_state]))

    # Update UI if display is available and requested
    if update_ui:
        try:
            if new_state == WIFI_OFFLINE:
                wifiStatus.text = "Offline"
                wifiAddress.text = "Hold A=retry"
            elif new_state == WIFI_CONNECTING:
                wifiStatus.text = "Connecting"
                wifiAddress.text = "---"
            elif new_state == WIFI_DISCONNECTED:
                wifiStatus.text = "Disconnected"
                wifiAddress.text = "---"
            # WIFI_CONNECTED UI is set by the caller with actual SSID/IP
        except NameError:
            pass  # Display not set up yet

# HTML Dashboard - loaded from index.html file
INDEX_HTML_FILE = "/index.html"

# Timezone table: (key, display_name, utc_offset_minutes, dst_rule)
# dst_rule: None=no DST, "US"=US rules, "EU"=EU rules, "AU"=AU rules, "NZ"=NZ rules
TIMEZONES = (
    ("US/Hawaii",    "Hawaii",             -600, None),
    ("US/Alaska",    "Alaska",             -540, "US"),
    ("US/Pacific",   "Pacific (LA)",       -480, "US"),
    ("US/Mountain",  "Mountain (Denver)",  -420, "US"),
    ("US/Arizona",   "Arizona",            -420, None),
    ("US/Central",   "Central (Chicago)",  -360, "US"),
    ("US/Eastern",   "Eastern (New York)", -300, "US"),
    ("EU/London",    "London",                0, "EU"),
    ("EU/Paris",     "Paris",               +60, "EU"),
    ("EU/Berlin",    "Berlin",              +60, "EU"),
    ("EU/Moscow",    "Moscow",             +180, None),
    ("AS/Dubai",     "Dubai",              +240, None),
    ("AS/Mumbai",    "Mumbai",             +330, None),
    ("AS/Singapore", "Singapore",          +480, None),
    ("AS/Tokyo",     "Tokyo",              +540, None),
    ("OC/Sydney",    "Sydney",             +600, "AU"),
    ("OC/Auckland",  "Auckland",           +720, "NZ"),
    ("UTC",          "UTC",                   0, None),
)


#%%----------------------------------------------------------------------------
def getBit(value, bitIdx):
    # Return bit mask of value at bitIdx.
    return value & (1 << bitIdx)

#%%----------------------------------------------------------------------------
def setBit(value, bitIdx):
    # Return value with bitIdx set to 1.
    return value | (1 << bitIdx)

#%%----------------------------------------------------------------------------
def clrBit(value, bitIdx):
    # Return value with bitIdx cleared to 0.
    return value & ~(1 << bitIdx)

#%%----------------------------------------------------------------------------
def log_action(msg):
    # Add timestamped entry to action log.
    global action_log
    try:
        t = rtc.datetime
        ts = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
    except:
        ts = "??:??:??"
    action_log.insert(0, {"ts": ts, "msg": msg})
    if len(action_log) > LOG_MAX:
        action_log.pop()
    print("[LOG]", ts, msg)

#%%----------------------------------------------------------------------------
def get_uptime():
    # Return uptime in seconds since start.
    global start_time
    return int(time.monotonic() - start_time)

#%%----------------------------------------------------------------------------
# NVM Storage Layout (persists across reboots without filesystem access)
# NVM[0] = magic byte (0xAB) to verify intentional write (guards against garbage)
# NVM[1] = timezone index into TIMEZONES tuple
# NVM[2] = home offset high byte (16-bit signed, range ±1056, stored as offset + 32768)
# NVM[3] = home offset low byte
# NVM[4] = step delay high byte (16-bit, microseconds, 100-1000 range)
# NVM[5] = step delay low byte
# NVM[6] = AS5600 calibration high byte (0-4095, or 0xFFFF = uncalibrated)
# NVM[7] = AS5600 calibration low byte
NVM_MAGIC = 0xAB
NVM_AS5600_CAL_HIGH = 6
NVM_AS5600_CAL_LOW = 7
AS5600_CAL_UNCALIBRATED = 0xFFFF
DEFAULT_STEP_DELAY_US = 450  # Default 450 microseconds (0.00045 seconds)
#%%----------------------------------------------------------------------------
def load_timezone_nvm():
    # Load timezone key from NVM. Returns key string or default.
    # Only trust NVM if magic byte is present (guards against random garbage)
    try:
        if microcontroller.nvm[0] == NVM_MAGIC:
            tz_index = microcontroller.nvm[1]
            if tz_index < len(TIMEZONES):
                return TIMEZONES[tz_index][0]
    except Exception as e:
        print("NVM read error:", e)
    return "US/Eastern"  # Default timezone for fresh devices

#%%----------------------------------------------------------------------------
def save_timezone_nvm(tz_key):
    # Save timezone key to NVM. Returns True on success.
    for i, tz in enumerate(TIMEZONES):
        if tz[0] == tz_key:
            try:
                microcontroller.nvm[0] = NVM_MAGIC  # Write magic byte
                microcontroller.nvm[1] = i          # Write timezone index
                print("Timezone saved to NVM: index", i, tz_key)
                return True
            except Exception as e:
                print("NVM write error:", e)
                return False
    return False

#%%----------------------------------------------------------------------------
def load_home_offset_nvm():
    # Load home offset from NVM bytes 2-3. Returns signed int (-1056 to +1056).
    # Requires magic byte in NVM[0] to be valid
    # Stored as 16-bit unsigned (offset + 32768)
    try:
        if microcontroller.nvm[0] != NVM_MAGIC:  # NVM not initialized
            return 0
        high_byte = microcontroller.nvm[2]
        low_byte = microcontroller.nvm[3]
        stored = (high_byte << 8) | low_byte
        if stored == 0:  # Uninitialized
            return 0
        offset = stored - 32768  # Convert from unsigned to signed
        # Clamp to valid range in case of corrupted data
        offset = max(-1056, min(1056, offset))
        return offset
    except Exception as e:
        print("NVM home offset read error:", e)
    return 0

#%%----------------------------------------------------------------------------
def save_home_offset_nvm(offset):
    # Save home offset to NVM bytes 2-3. Offset range: -1056 to +1056 (~30 degrees).
    # stored = offset + 32768, so offset 0 = stored 32768
    try:
        # Clamp to valid range (±1056 steps = ~±30 degrees at 12800 steps/rev)
        offset = max(-1056, min(1056, offset))
        stored = offset + 32768  # Convert from signed to unsigned (1-65535)
        high_byte = (stored >> 8) & 0xFF
        low_byte = stored & 0xFF
        microcontroller.nvm[0] = NVM_MAGIC  # Ensure magic byte is set
        microcontroller.nvm[2] = high_byte
        microcontroller.nvm[3] = low_byte
        print("Home offset saved to NVM:", offset, "steps")
        return True
    except Exception as e:
        print("NVM home offset write error:", e)
        return False

#%%----------------------------------------------------------------------------
def load_as5600_cal_nvm():
    # Load AS5600 calibration angle from NVM bytes 6-7.
    # Returns 0-4095 if calibrated, or None if uncalibrated/invalid.
    try:
        if microcontroller.nvm[0] != NVM_MAGIC:
            return None
        high = microcontroller.nvm[NVM_AS5600_CAL_HIGH]
        low = microcontroller.nvm[NVM_AS5600_CAL_LOW]
        value = (high << 8) | low
        if value == AS5600_CAL_UNCALIBRATED or value > 4095:
            return None
        return value
    except:
        return None

#%%----------------------------------------------------------------------------
def save_as5600_cal_nvm(angle):
    # Save AS5600 calibration angle to NVM bytes 6-7. Pass None to clear.
    try:
        microcontroller.nvm[0] = NVM_MAGIC
        if angle is None:
            microcontroller.nvm[NVM_AS5600_CAL_HIGH] = 0xFF
            microcontroller.nvm[NVM_AS5600_CAL_LOW] = 0xFF
            print("AS5600 calibration cleared from NVM")
        else:
            angle = angle % 4096
            microcontroller.nvm[NVM_AS5600_CAL_HIGH] = (angle >> 8) & 0xFF
            microcontroller.nvm[NVM_AS5600_CAL_LOW] = angle & 0xFF
            print("AS5600 calibration saved to NVM: %d" % angle)
        return True
    except Exception as e:
        print("NVM AS5600 cal write error:", e)
        return False

#%%----------------------------------------------------------------------------
def load_step_delay_nvm():
    # Load step delay from NVM bytes 4-5. Returns delay in seconds (float).
    # Stored as microseconds (100-1000 range). Returns default if not set.
    try:
        if microcontroller.nvm[0] != NVM_MAGIC:  # NVM not initialized
            return DEFAULT_STEP_DELAY_US / 1000000.0
        high_byte = microcontroller.nvm[4]
        low_byte = microcontroller.nvm[5]
        delay_us = (high_byte << 8) | low_byte
        if delay_us == 0:  # Uninitialized
            return DEFAULT_STEP_DELAY_US / 1000000.0
        # Clamp to valid range
        delay_us = max(100, min(1000, delay_us))
        return delay_us / 1000000.0  # Convert to seconds
    except Exception as e:
        print("NVM step delay read error:", e)
    return DEFAULT_STEP_DELAY_US / 1000000.0

#%%----------------------------------------------------------------------------
def save_step_delay_nvm(delay_us):
    # Save step delay to NVM bytes 4-5. Delay in microseconds (100-1000 range).
    try:
        # Clamp to valid range
        delay_us = max(100, min(1000, int(delay_us)))
        high_byte = (delay_us >> 8) & 0xFF
        low_byte = delay_us & 0xFF
        microcontroller.nvm[0] = NVM_MAGIC  # Ensure magic byte is set
        microcontroller.nvm[4] = high_byte
        microcontroller.nvm[5] = low_byte
        print("Step delay saved to NVM:", delay_us, "us")
        return True
    except Exception as e:
        print("NVM step delay write error:", e)
        return False

#%%----------------------------------------------------------------------------
def enter_calibration_mode():
    # Enter AS5600 calibration mode - disable motor for manual positioning.
    global calibration_mode
    calibration_mode = True
    en.value = motorDisabled  # Power down motor so user can move hand
    ucStatus.text = "CAL: Move to 12"
    print("Calibration mode: Move hand to 12 o'clock, then hold C")

#%%----------------------------------------------------------------------------
def confirm_calibration():
    # Confirm calibration - save current AS5600 position as 12 o'clock to NVM.
    global calibration_mode, as5600_home_offset, stepNow

    if as5600_sensor and as5600_sensor.magnet_detected:
        # Read current AS5600 angle - this becomes the new 12 o'clock reference
        angle = read_as5600_angle()
        if angle is not None:
            as5600_home_offset = angle
            save_as5600_cal_nvm(angle)
            ucStatus.text = "CAL: Saved!"
            print("AS5600 home offset set to: %d" % angle)
        else:
            ucStatus.text = "CAL: Read fail!"
            print("Calibration failed: Could not read AS5600")
    else:
        ucStatus.text = "CAL: No magnet!"
        print("Calibration failed: AS5600 magnet not detected")

    time.sleep(1)
    calibration_mode = False
    en.value = motorEnabled
    ucStatus.text = ""
    stepNow = 0  # At 12 o'clock = step 0

    # Move to current minute position
    minUpdate()

#%%----------------------------------------------------------------------------
# DST Calculation Functions
#%%----------------------------------------------------------------------------
def nth_weekday(year, month, weekday, n):
    # Find nth occurrence of weekday in month.
    # weekday: 0=Monday, 6=Sunday. n: 1=first, 2=second, -1=last.
    if n == -1:
        # Last occurrence - find last day of month
        if month == 12:
            next_month_start = time.mktime((year + 1, 1, 1, 0, 0, 0, 0, 0, -1))
        else:
            next_month_start = time.mktime((year, month + 1, 1, 0, 0, 0, 0, 0, -1))
        last_day_epoch = next_month_start - 86400
        last_day = time.localtime(last_day_epoch)
        day = last_day.tm_mday
        wday = last_day.tm_wday
        diff = (wday - weekday) % 7
        return day - diff
    else:
        # Find first day of month's weekday
        first_epoch = time.mktime((year, month, 1, 0, 0, 0, 0, 0, -1))
        first = time.localtime(first_epoch)
        first_wday = first.tm_wday
        diff = (weekday - first_wday) % 7
        first_occurrence = 1 + diff
        return first_occurrence + (n - 1) * 7

#%%----------------------------------------------------------------------------
def is_dst_us(year, month, day, hour):
    # US DST: 2nd Sunday March 2am -> 1st Sunday November 2am
    if month < 3 or month > 11:
        return False
    if month > 3 and month < 11:
        return True
    dst_start_day = nth_weekday(year, 3, 6, 2)   # 2nd Sunday March
    dst_end_day = nth_weekday(year, 11, 6, 1)    # 1st Sunday November
    if month == 3:
        return day > dst_start_day or (day == dst_start_day and hour >= 2)
    if month == 11:
        return day < dst_end_day or (day == dst_end_day and hour < 2)
    return False

#%%----------------------------------------------------------------------------
def is_dst_eu(year, month, day, hour):
    # EU DST: Last Sunday March 1am UTC -> Last Sunday October 1am UTC
    if month < 3 or month > 10:
        return False
    if month > 3 and month < 10:
        return True
    dst_start_day = nth_weekday(year, 3, 6, -1)  # Last Sunday March
    dst_end_day = nth_weekday(year, 10, 6, -1)   # Last Sunday October
    if month == 3:
        return day > dst_start_day or (day == dst_start_day and hour >= 1)
    if month == 10:
        return day < dst_end_day or (day == dst_end_day and hour < 1)
    return False

#%%----------------------------------------------------------------------------
def is_dst_au(year, month, day, hour):
    # AU DST: 1st Sunday October 2am -> 1st Sunday April 3am (Southern Hemisphere)
    dst_start_day = nth_weekday(year, 10, 6, 1)  # 1st Sunday October
    dst_end_day = nth_weekday(year, 4, 6, 1)     # 1st Sunday April
    # Southern hemisphere: DST is Oct-Apr
    if month > 10 or month < 4:
        return True
    if month > 4 and month < 10:
        return False
    if month == 10:
        return day > dst_start_day or (day == dst_start_day and hour >= 2)
    if month == 4:
        return day < dst_end_day or (day == dst_end_day and hour < 3)
    return False

#%%----------------------------------------------------------------------------
def is_dst_nz(year, month, day, hour):
    # NZ DST: Last Sunday September 2am -> 1st Sunday April 3am
    dst_start_day = nth_weekday(year, 9, 6, -1)  # Last Sunday September
    dst_end_day = nth_weekday(year, 4, 6, 1)     # 1st Sunday April
    if month > 9 or month < 4:
        return True
    if month > 4 and month < 9:
        return False
    if month == 9:
        return day > dst_start_day or (day == dst_start_day and hour >= 2)
    if month == 4:
        return day < dst_end_day or (day == dst_end_day and hour < 3)
    return False

#%%----------------------------------------------------------------------------
def get_timezone_offset(tz_key):
    # Return base UTC offset in minutes for timezone key.
    for tz in TIMEZONES:
        if tz[0] == tz_key:
            return tz[2]
    return 0  # Default to UTC

#%%----------------------------------------------------------------------------
def calculate_dst_offset(tz_key, utc_time):
    # Return DST offset in minutes (60 if active, 0 otherwise).
    tz_entry = None
    for tz in TIMEZONES:
        if tz[0] == tz_key:
            tz_entry = tz
            break
    if not tz_entry or tz_entry[3] is None:
        return 0

    dst_rule = tz_entry[3]
    year = utc_time.tm_year
    month = utc_time.tm_mon
    day = utc_time.tm_mday
    hour = utc_time.tm_hour

    if dst_rule == "US":
        return 60 if is_dst_us(year, month, day, hour) else 0
    elif dst_rule == "EU":
        return 60 if is_dst_eu(year, month, day, hour) else 0
    elif dst_rule == "AU":
        return 60 if is_dst_au(year, month, day, hour) else 0
    elif dst_rule == "NZ":
        return 60 if is_dst_nz(year, month, day, hour) else 0
    return 0


#%%----------------------------------------------------------------------------
def sayHello():
    # Print startup banner plus free RAM and flash stats.
    print("\nHello from FeatherS3!")
    print("---------------------\n")

    # Show available memory
    print("Memory Info - gc.mem_free()")
    print("---------------------------")
    print("{} Bytes\n".format(gc.mem_free()))

    flash = os.statvfs('/')
    flash_size = flash[0] * flash[2]
    flash_free = flash[0] * flash[3]
    # Show flash size
    print("Flash - os.statvfs('/')")
    print("---------------------------")
    print("Size: {} Bytes\nFree: {} Bytes\n".format(flash_size, flash_free))

#%%----------------------------------------------------------------------------
def setupButton():
    # Configure 3 pull-up inputs and return button objects.
    butA = digitalio.DigitalInOut(board.IO1)
    butA.direction = digitalio.Direction.INPUT
    butA.pull = digitalio.Pull.UP

    butB = digitalio.DigitalInOut(board.IO38)
    butB.direction = digitalio.Direction.INPUT
    butB.pull = digitalio.Pull.UP

    butC = digitalio.DigitalInOut(board.IO33)
    butC.direction = digitalio.Direction.INPUT
    butC.pull = digitalio.Pull.UP

    return [butA, butB, butC]

#%%----------------------------------------------------------------------------
def setupI2C():
    # Initialize and return I2C bus object.
    i2c = board.I2C()
    return i2c

#%%----------------------------------------------------------------------------
def setupRTC(i2c):
    # Create and return DS3231 RTC on the provided I2C bus.
    rtc = adafruit_ds3231.DS3231(i2c)  # adafruit_pcf8523.PCF8523(i2c)#
    return rtc

#%%----------------------------------------------------------------------------
def setupAS5600(i2c):
    # Initialize AS5600 magnetic angle sensor for closed-loop control.
    # Returns sensor object if successful, None otherwise.
    global as5600_sensor
    if not AS5600_AVAILABLE:
        print("AS5600: Library not available")
        return None
    try:
        sensor = adafruit_as5600.AS5600(i2c)
        if sensor.magnet_detected:
            print(f"AS5600: Magnet detected, AGC={sensor.agc}, Mag={sensor.magnitude}")
            as5600_sensor = sensor
            return sensor
        else:
            print("AS5600: No magnet detected - closed-loop disabled")
            return None
    except Exception as e:
        print(f"AS5600: Init failed ({e}) - closed-loop disabled")
        return None

#%%----------------------------------------------------------------------------
def read_as5600_angle():
    # Read current angle from AS5600 (0-4095) or None if unavailable.
    if as5600_sensor:
        try:
            return as5600_sensor.angle
        except:
            return None
    return None

def as5600_to_degrees(raw):
    # Convert AS5600 raw value (0-4095) to degrees (0-360).
    return raw * 360.0 / 4096.0

def as5600_to_steps(raw):
    # Convert AS5600 raw value (0-4095) to motor steps (0-STEPS).
    return int(raw * STEPS / 4096) % STEPS

def minute_to_as5600(minute):
    # Convert minute (0-59) to expected AS5600 raw value.
    # Uses as5600_home_offset as the reference for 12 o'clock (minute 0).
    minute_angle = int(minute * 4096 / 60)
    return (as5600_home_offset + minute_angle) % 4096

def as5600_angle_diff(current, target):
    # Calculate shortest path difference between angles (positive = CW needed).
    # Both values are raw AS5600 (0-4095).
    diff = (target - current) % 4096
    if diff > 2048:  # Shorter to go CCW
        diff = diff - 4096
    return diff

#%%----------------------------------------------------------------------------
def setHrs():
    # Increment RTC hour by 1 (wrap 0-23) and update screen.
    ucStatus.text = "+1 Hrs"
    t = rtc.datetime

    newHrs = t.tm_hour + 1
    if newHrs > 23:
        newHrs = 0

    rtc.datetime = time.struct_time(
        (t.tm_year, t.tm_mon, t.tm_mday, newHrs, t.tm_min, 0, 0, 0, -1)
    )
    screenUpdate()

#%%----------------------------------------------------------------------------
def setMins():
    # Increment RTC minute by 1 (wrap 0-59) and update screen.
    ucStatus.text = "+1 Mins"
    t = rtc.datetime

    newMins = t.tm_min + 1
    if newMins > 59:
        newMins = 0

    rtc.datetime = time.struct_time(
        (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, newMins, 0, 0, 0, -1)
    )
    screenUpdate()

#%%----------------------------------------------------------------------------
def setupMotor():
    # Configure stepper driver IO and return motor pin objects.
    ucStatus.text = "Setup Motor"
    global STEPS, STEP_DELAY
    STEPS = 12800  # TMC2209 at 32 microsteps × 400 base steps (0.9° motor) = 12800 steps per revolution
    STEP_DELAY = load_step_delay_nvm()  # Load configurable delay from NVM
    print("Step delay loaded:", STEP_DELAY * 1000000, "us")

    en = digitalio.DigitalInOut(board.IO6)
    en.direction = digitalio.Direction.OUTPUT
    
    en.value = motorDisabled  # start disabled

    step = digitalio.DigitalInOut(board.IO12)
    step.direction = digitalio.Direction.OUTPUT

    direct = digitalio.DigitalInOut(board.IO5)
    direct.direction = digitalio.Direction.OUTPUT

    home = digitalio.DigitalInOut(board.IO14)
    home.direction = digitalio.Direction.INPUT
    home.pull = digitalio.Pull.UP

    stepSelect = digitalio.DigitalInOut(board.IO17)
    stepSelect.direction = digitalio.Direction.OUTPUT
    stepSelect.value = True  # set stepping mode once

    return [en, step, direct, home, stepSelect]

#%%----------------------------------------------------------------------------
def setupFlipdotPower():
    # Configure flipdot relay control pin and return it.
    pwr = digitalio.DigitalInOut(board.IO11)
    pwr.direction = digitalio.Direction.OUTPUT
    pwr.value = False  # flipdot power OFF by default
    return pwr

#%%----------------------------------------------------------------------------
def flipsPower(on: bool):
    # Turn flipdot relay on/off with precharge delay on enable.
    global flipPwrIsOn

    if on:
        if not flipPwrIsOn:
            pwr.value = True
            flipPwrIsOn = True
            time.sleep(relayPrechargeS)
    else:
        if flipPwrIsOn:
            pwr.value = False
            flipPwrIsOn = False

#%%----------------------------------------------------------------------------
def extendFlipPowerWindow():
    # Push relay off deadline out by relayHoldS seconds.
    global flipPwrOffAtS
    nowS = time.monotonic()
    offAtS = nowS + relayHoldS
    if offAtS > flipPwrOffAtS:
        flipPwrOffAtS = offAtS

#%%----------------------------------------------------------------------------
def serviceFlipPowerWindow():
    # Turn relay off when window expires; reset cache.
    global flipPwrOffAtS
    if flipPwrIsOn and (time.monotonic() >= flipPwrOffAtS):
        flipsPower(False)
        invalidateFlipCache()

#%%----------------------------------------------------------------------------
def invalidateFlipCache():
    # Force next flip update by invalidating oldData cache.
    global oldData
    oldData = [255, 255, 255, 255]

#%%----------------------------------------------------------------------------
def setFlips(dataIn, flagXOR, managePower=True, forceFull=False, doPrecharge=False):
    # Compute/shift flipdot data with optional power management flags.
    if forceFull:
        flagXOR = 1

    if managePower:
        flipsPower(True)
        extendFlipPowerWindow()
        if doPrecharge:
            time.sleep(relayPrechargeS)

    regData = setFlipsCore(dataIn, flagXOR)

    if managePower:
        extendFlipPowerWindow()

    return regData

#%%----------------------------------------------------------------------------
def setFlipsCore(dataIn, flagXOR):
    # Build 4x12-bit register words and shift them to hardware.
    global oldData

    try:
        oldData
    except NameError:
        oldData = [255, 255, 255, 255]

    supBits = [0, 3, 6, 9]
    setBits = [1, 4, 7, 10]
    resBits = [2, 5, 8, 11]

    xorData = [0, 0, 0, 0]
    regData = [0, 0, 0, 0]

    colData = [dataIn[3], dataIn[2], dataIn[1], dataIn[0]]

    for i in range(0, 4):
        xorData[i] = colData[i] ^ oldData[i]
        for j in range(0, 4):
            xorIdx = getBit(xorData[i], j)
            dotIdx = getBit(colData[i], j)

            if xorIdx == 1 or flagXOR == 1:
                regData[i] = setBit(regData[i], supBits[j])
                if dotIdx == 0:
                    regData[i] = clrBit(regData[i], setBits[j])
                    regData[i] = setBit(regData[i], resBits[j])
                else:
                    regData[i] = setBit(regData[i], setBits[j])
                    regData[i] = clrBit(regData[i], resBits[j])
            else:
                regData[i] = clrBit(regData[i], supBits[j])
                regData[i] = clrBit(regData[i], setBits[j])
                regData[i] = clrBit(regData[i], resBits[j])

    shiftData(regData)
    oldData = colData
    return regData

#%%----------------------------------------------------------------------------
def setupLed():
    # Configure onboard LED pin and return LED object.
    led = digitalio.DigitalInOut(board.LED)
    led.direction = digitalio.Direction.OUTPUT
    return led

#%%----------------------------------------------------------------------------
def hallTest():
    # Read hall sensor and mirror state on LED.
    if home.value == False:
        led.value = True
        return False
    else:
        led.value = 0
        return True

#%%----------------------------------------------------------------------------
def setDir(data):
    # Set motor direction pin based on 0/1 input.
    if data == 0:
        direct.value = False
    else:
        direct.value = True

#%%----------------------------------------------------------------------------
def oneStep(data, delay):
    # Perform one motor step, update stepNow, and sample hall sensor.
    setDir(data)
    step.value = True
    # Brief pulse - toggle quickly
    step.value = False
    # Simple delay loop - each iteration ~1.7μs on ESP32-S3
    # Scale delay to loop count (calibrated for ESP32-S3 at 240MHz)
    loops = int(delay * 580000)  # Calibrated: 580k loops per second
    for _ in range(loops):
        pass

    global stepNow
    if data == 0:
        stepNow -= 1
    else:
        stepNow += 1
    stepNow %= STEPS
    hallTest()

#%%----------------------------------------------------------------------------
def pollServer():
    # Poll web server if available to maintain responsiveness during long operations.
    global server, last_successful_poll, poll_failure_count
    if server:
        try:
            server.poll()
            last_successful_poll = time.monotonic()
            poll_failure_count = 0
        except Exception as e:
            print("Server poll error:", e)
            poll_failure_count += 1

#%%----------------------------------------------------------------------------
def getStatusDict():
    # Build status dictionary for WebSocket/JSON responses.
    try:
        t = rtc.datetime
        time_str = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
        hr12 = hour24ToHour12(t.tm_hour)
        minute = t.tm_min
    except:
        time_str = "??:??:??"
        hr12 = 0
        minute = 0

    tz = load_timezone_nvm()
    return {
        "time": time_str,
        "hour_12": hr12,
        "minute": minute,
        "wifi_connected": wifi.radio.connected,
        "ip_address": str(wifi.radio.ipv4_address) if wifi.radio.connected else "None",
        "motor_position": stepNow,
        "motor_steps_total": STEPS,
        "flipdot_power": flipPwrIsOn,
        "uptime_s": get_uptime(),
        "free_memory": gc.mem_free(),
        "timezone": tz,
        "home_offset": load_home_offset_nvm(),
        "step_delay_us": int(STEP_DELAY * 1000000),
    }

#%%----------------------------------------------------------------------------
def multiStep(data, steps, delay):
    # Step motor multiple times with enable control.
    en.value = motorEnabled
    poll_interval = 100  # Poll server every N steps
    for i in range(steps):
        oneStep(data, delay)
        if i % poll_interval == 0:
            pollServer()

#%%----------------------------------------------------------------------------
def moveToAngle(target_raw, tolerance=15, max_steps=1000):
    # Move motor to target AS5600 angle using closed-loop feedback.
    # target_raw: target angle (0-4095)
    # tolerance: acceptable error in raw units (~1.3° at tolerance=15)
    # max_steps: safety limit to prevent infinite loops
    # Returns True if target reached, False if AS5600 unavailable or max_steps exceeded.
    #
    # Uses batched stepping to reduce I2C overhead and eliminate jerkiness:
    # - Bulk moves: take multiple steps without reading sensor
    # - Fine-tune: single steps only when close to target
    if not as5600_sensor:
        return False

    try:
        en.value = motorEnabled
        steps_taken = 0
        # AS5600-to-step ratio: ~3.125 steps per AS5600 unit (12800/4096)
        STEPS_PER_AS5600 = STEPS / 4096

        while steps_taken < max_steps:
            current = read_as5600_angle()
            if current is None:
                return False

            diff = as5600_angle_diff(current, target_raw)
            abs_diff = abs(diff)

            if abs_diff <= tolerance:
                # Update stepNow from AS5600 for consistency with open-loop tracking
                global stepNow
                stepNow = as5600_to_steps(current)
                return True

            # Determine step direction (diff > 0 means CW needed)
            direction = 1 if diff > 0 else 0

            # Choose batch size based on distance to target
            # Larger batches for far distances, smaller for fine-tuning
            if abs_diff > 200:  # Far away: batch 50 steps (~16 AS5600 units)
                batch_size = 50
            elif abs_diff > 50:  # Medium distance: batch 15 steps
                batch_size = 15
            elif abs_diff > tolerance * 2:  # Close: batch 5 steps
                batch_size = 5
            else:  # Very close: single step fine-tuning
                batch_size = 1

            # Take batched steps without reading sensor between them
            for _ in range(batch_size):
                oneStep(direction, STEP_DELAY)
                steps_taken += 1
                if steps_taken >= max_steps:
                    break

            # Poll server occasionally to keep web responsive
            if steps_taken % 100 == 0:
                pollServer()

        print(f"moveToAngle: max_steps exceeded, diff={diff}")
        return False
    except Exception as e:
        print(f"moveToAngle error: {e}")
        return False

#%%----------------------------------------------------------------------------
def findExactHome(delay=None, apply_offset=True, skip_as5600_capture=False):
    # Find magnet center using symmetric edge detection.
    # Both edges detected at release point for consistency.
    # delay: step delay in seconds, defaults to STEP_DELAY
    # apply_offset: if True, apply stored NVM offset after finding center
    # skip_as5600_capture: if True, don't overwrite as5600_home_offset (use saved NVM cal)
    if delay is None:
        delay = STEP_DELAY
    print('Finding Exact Home')
    ucStatus.text = "Finding Home..."
    en.value = motorEnabled

    global stepNow
    stepNow = 0  # Reset counter for relative measurements

    # Step 1: Move forward until hall triggers (enter magnet zone)
    print('Step 1: Finding magnet zone')
    ucStatus.text = "Home: Magnet..."
    step_count = 0
    while not hallStable(False):
        oneStep(1, delay)
        step_count += 1
        if step_count % 100 == 0:
            pollServer()

    # Step 2: Reverse until hall releases (precise edge A)
    print('Step 2: Finding edge A (release point)')
    ucStatus.text = "Home: Edge A..."
    step_count = 0
    while not hallStable(True):
        oneStep(0, delay)
        step_count += 1
        if step_count % 100 == 0:
            pollServer()
    edge_a = stepNow
    print('Edge A at step: %d' % edge_a)

    # Step 3: Continue reversing until hall triggers (other side of magnet)
    print('Step 3: Passing through to other side')
    ucStatus.text = "Home: Crossing..."
    step_count = 0
    while not hallStable(False):
        oneStep(0, delay)
        step_count += 1
        if step_count % 100 == 0:
            pollServer()

    # Step 4: Reverse again (forward) until hall releases (precise edge B)
    print('Step 4: Finding edge B (release point)')
    ucStatus.text = "Home: Edge B..."
    step_count = 0
    while not hallStable(True):
        oneStep(1, delay)
        step_count += 1
        if step_count % 100 == 0:
            pollServer()
    edge_b = stepNow
    print('Edge B at step: %d' % edge_b)

    # Step 5: Calculate center and move there (with wrap-around handling)
    raw_diff = abs(edge_a - edge_b)

    # Check if edges wrap around the 0/STEPS boundary
    if raw_diff > STEPS // 2:
        # Wrap-around case: add STEPS to the smaller edge before averaging
        if edge_a < edge_b:
            center = ((edge_a + STEPS) + edge_b) // 2 % STEPS
        else:
            center = (edge_a + (edge_b + STEPS)) // 2 % STEPS
        magnet_width = STEPS - raw_diff  # Correct width for wrap-around
    else:
        center = (edge_a + edge_b) // 2
        magnet_width = raw_diff

    steps_to_center = center - stepNow

    # Handle wrap-around for movement calculation
    if steps_to_center > STEPS // 2:
        steps_to_center -= STEPS
    elif steps_to_center < -STEPS // 2:
        steps_to_center += STEPS

    print('Magnet width: %d steps' % magnet_width)
    print('Center at: %d, moving %d steps' % (center, steps_to_center))
    ucStatus.text = "Home: Centering..."

    if steps_to_center > 0:
        for _ in range(steps_to_center):
            oneStep(1, delay)
    elif steps_to_center < 0:
        for _ in range(abs(steps_to_center)):
            oneStep(0, delay)

    # Step 6: Set home position
    stepNow = 0
    print('Home set at center of magnet')
    ucStatus.text = "Home Found"

    # Step 7: Apply calibration offset from NVM (unless in calibration mode)
    if apply_offset:
        offset = load_home_offset_nvm()
        if offset != 0:
            print('Applying home offset: %d steps' % offset)
            if offset > 0:
                multiStep(1, offset, delay)  # CW
            else:
                multiStep(0, abs(offset), delay)  # CCW
            stepNow = 0  # Reset after offset applied
            print('Offset applied, home position adjusted')
    else:
        print('Calibration mode: staying at raw magnet center')

    # Step 8: Record AS5600 angle at 12 o'clock (unless using saved calibration)
    if not skip_as5600_capture:
        global as5600_home_offset
        if as5600_sensor:
            try:
                as5600_home_offset = as5600_sensor.angle
                print(f'AS5600 at home (12:00): {as5600_home_offset} ({as5600_home_offset * 360.0 / 4096.0:.1f} deg)')
            except Exception as e:
                print(f'AS5600 read error at home: {e}')
                as5600_home_offset = 0
    else:
        print('Skipping AS5600 capture (using saved calibration)')

    return magnet_width

#%%----------------------------------------------------------------------------
def goHome(tolerance=15):
    """
    Move to home position (12 o'clock) using AS5600 absolute position.
    Always moves clockwise (CW).
    """
    global stepNow
    
    # Update OLED status
    ucStatus.text = "Going Home..."

    if not as5600_sensor:
        print("goHome: AS5600 not available, using findExactHome()")
        findExactHome()
        return

    current = read_as5600_angle()
    target = as5600_home_offset

    # Calculate CW distance in AS5600 units (AS5600 increases with CW rotation)
    # To move CW from current to target: (target - current) % 4096
    cw_as5600 = (target - current) % 4096

    if cw_as5600 < tolerance:
        print("goHome: Already at home (AS5600=%d, home=%d)" % (current, target))
        stepNow = 0
        return

    # Convert to steps (12800 steps / 4096 units)
    cw_steps = int(cw_as5600 * STEPS / 4096)

    print("goHome: AS5600=%d, home=%d, moving %d steps CW" % (current, target, cw_steps))
    multiStep(1, cw_steps, STEP_DELAY)

    # Fine-tune with AS5600 closed-loop
    moveToAngle(target, tolerance)

    stepNow = 0
    print("goHome: At home")

#%%----------------------------------------------------------------------------
def setupScreen(i2c):
    # Init OLED and return screen group + label/status objects.
    blk = 0x000000
    wht = 0xFFFFFF
    displayio.release_displays()
    display_bus = i2cdisplaybus.I2CDisplayBus(i2c, device_address=0x3C)

    screenWidth  = 128
    screenHeight = 64
    screenBorder = 2
    screenRadius = 5

    display = adafruit_displayio_sh1107.SH1107(
        display_bus, width=screenWidth, height=screenHeight
    )

    screen = displayio.Group()
    display.root_group = screen

    rect = RoundRect(
        int(screenBorder/2), int(screenBorder/2),
        screenWidth-screenBorder, screenHeight-screenBorder,
        screenRadius, fill=None, outline=wht, stroke=1
    )
    screen.append(rect)

    timeArea = label.Label(terminalio.FONT, text="HH:MM", color=wht)
    timeArea.anchor_point = (0.5, 0.5)
    timeArea.anchored_position = (64, 9)
    screen.append(timeArea)

    ucStatus = label.Label(terminalio.FONT, text=" Startup", color=wht)
    ucStatus.anchor_point = (0.5, 0.5)
    ucStatus.anchored_position = (64, 27)
    screen.append(ucStatus)

    circleRadius = 4
    wifiCircle = Circle(120, 8, circleRadius, fill=None, outline=wht, stroke=1)
    screen.append(wifiCircle)

    wifiStatus = label.Label(terminalio.FONT, text="No WiFi", color=wht)
    wifiStatus.anchor_point = (0.5, 0.5)
    wifiStatus.anchored_position = (64, 44)
    screen.append(wifiStatus)

    wifiAddress = label.Label(terminalio.FONT, text="000.000.00.00", color=wht)
    wifiAddress.anchor_point = (0.5, 0.5)
    wifiAddress.anchored_position = (64, 54)
    screen.append(wifiAddress)

    return [screen, timeArea, ucStatus, wifiCircle, wifiStatus, wifiAddress]

#%%----------------------------------------------------------------------------
def screenUpdate():
    # Refresh OLED time text and blink the onboard LED.
    t = rtc.datetime
    timeArea.text = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
    print(timeArea.text)
    # Don't clear status during calibration mode
    if not calibration_mode:
        ucStatus.text = " "
    led.value = not led.value

#%%----------------------------------------------------------------------------
def minUpdate():
    """Move minute hand to current minute using AS5600 with CW-only bulk movement."""
    t = rtc.datetime
    target_minute = t.tm_min
    global stepNow

    # Calculate target AS5600 angle for this minute
    target_angle = minute_to_as5600(target_minute)

    if as5600_sensor and as5600_sensor.magnet_detected:
        # AS5600-based CW movement (like goHome)
        current = read_as5600_angle()

        # Calculate CW distance in AS5600 units
        cw_as5600 = (target_angle - current) % 4096

        # Check if already close (either direction)
        min_distance = min(cw_as5600, 4096 - cw_as5600)

        if min_distance < 15:  # tolerance - already at target
            print("minUpdate: At target (AS5600=%d, target=%d)" % (current, target_angle))
        elif min_distance < 68:  # ~6 degrees - small correction only (~1 minute of movement)
            print("minUpdate: Small correction (AS5600=%d, target=%d, diff=%d)" % (current, target_angle, min_distance))
            ucStatus.text = "Min Update..."
            moveToAngle(target_angle, tolerance=15)
        else:
            # Bulk CW movement + fine-tune
            cw_steps = int(cw_as5600 * STEPS / 4096)
            print("minUpdate: %d -> %d, moving %d steps CW" % (current, target_angle, cw_steps))
            ucStatus.text = "Min Update..."
            multiStep(1, cw_steps, STEP_DELAY)
            moveToAngle(target_angle, tolerance=15)

        # Sync stepNow with target
        stepNow = int(round(target_minute / 60.0 * STEPS)) % STEPS
    else:
        # Fallback: open-loop step counting
        print("minUpdate: Open-loop fallback")
        stepNow %= STEPS
        minSteps = int(round(target_minute / 60.0 * STEPS)) % STEPS
        stepsNeeded = (minSteps - stepNow) % STEPS
        print("%d %d %d (CW)" % (minSteps, stepNow, stepsNeeded))
        if stepsNeeded > 0:
            ucStatus.text = "Min Update..."
            multiStep(1, stepsNeeded, STEP_DELAY)
        stepNow = minSteps
#%%----------------------------------------------------------------------------
def hrUpdate(forceHour=False):
    # Move minute hand and force flipdot blank then hour refresh.
    print("hrUpdate()-Updating Flip Dot Hours")
    t = rtc.datetime

    global lastHourShown
    hr12 = hour24ToHour12(t.tm_hour)

    if forceHour or (lastHourShown != hr12):
        ucStatus.text = "Updating Hour..."
        flipsPower(True)
        try:
            setFlips([0, 0, 0, 0], 1, managePower=False)   # force black
            time.sleep(flipdotDelay)

            setFlips(hourIn(hr12), 1, managePower=False)  # force hour
            time.sleep(flipdotDelay)

            setFlips(hourIn(hr12), 1, managePower=False)  # small retry
        finally:
            extendFlipPowerWindow()

        lastHourShown = hr12

#%%----------------------------------------------------------------------------
# Animation Functions
#%%----------------------------------------------------------------------------
def anim_demo():
    # Full demo: sweep hand 360°, count through hours, restore time
    ucStatus.text = "Anim: Demo"
    flipsPower(True)
    try:
        # Sweep minute hand full rotation
        multiStep(1, STEPS, STEP_DELAY)
        # Count through hours 1-12
        for h in range(1, 13):
            setFlips(hourIn(h), 1, managePower=False)
            time.sleep(0.5)
        # Blank
        setFlips([0, 0, 0, 0], 1, managePower=False)
        time.sleep(0.5)
    finally:
        extendFlipPowerWindow()
    # Restore time
    goHome()
    hrUpdate(forceHour=True)
    minUpdate()

def anim_chaos():
    # Random chaos: random flipdots with minute hand pointing to displayed hour
    ucStatus.text = "Anim: Chaos"
    global stepNow

    # Start at home position (12 o'clock)
    goHome()
    current_pos = 0  # stepNow is 0 at 12 o'clock
    steps_per_hour = STEPS // 12  # ~1067 steps per hour position

    flipsPower(True)
    try:
        for _ in range(20):
            # Pick random hour 1-12 (0 = 12 o'clock position)
            hour = r.randint(1, 12)
            target_pos = (hour % 12) * steps_per_hour  # hour 12 -> pos 0

            # Display hour on flipdots
            setFlips(hourIn(hour), 1, managePower=False)

            # Calculate CW-only movement (like minUpdate)
            if target_pos >= current_pos:
                steps_needed = target_pos - current_pos
            else:
                steps_needed = (STEPS - current_pos) + target_pos

            # Move to target position
            if steps_needed > 0:
                multiStep(1, steps_needed, STEP_DELAY)  # CW only
                current_pos = target_pos

            time.sleep(0.25)
    finally:
        extendFlipPowerWindow()

    # Restore time display
    goHome()
    hrUpdate(forceHour=True)
    minUpdate()

def anim_sync():
    # Sync dance: hand sweeps to each hour, flipdots light up in sync
    ucStatus.text = "Anim: Sync"
    flipsPower(True)
    try:
        setFlips([0, 0, 0, 0], 1, managePower=False)  # Start blank
        findExactHome()  # Start at 12
        steps_per_hour = STEPS // 12
        for h in range(1, 13):
            # Move hand to hour position
            multiStep(1, steps_per_hour, STEP_DELAY)
            # Light up matching hour
            setFlips(hourIn(h), 1, managePower=False)
            time.sleep(0.375)
    finally:
        extendFlipPowerWindow()
    # Restore time
    hrUpdate(forceHour=True)
    minUpdate()

#%%----------------------------------------------------------------------------
def setupDot():
    # Initialize onboard LED and define global color constants.
    # Supports both DotStar (Feather S2) and NeoPixel (Feather S3).
    global BOARD_TYPE

    if BOARD_TYPE == "feather_s3":
        # Feather S3: NeoPixel on GPIO40, power on GPIO39
        # Enable the NeoPixel power (LDO2)
        if hasattr(board, 'NEOPIXEL_POWER'):
            neopixel_power = digitalio.DigitalInOut(board.NEOPIXEL_POWER)
            neopixel_power.direction = digitalio.Direction.OUTPUT
            neopixel_power.value = True
        pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=1.0, auto_write=True)
    else:
        # Feather S2: DotStar on APA102 pins
        pixel = adafruit_dotstar.DotStar(
            board.APA102_SCK, board.APA102_MOSI, 1,
            brightness=1.0, auto_write=True
        )

    global RED, YELLOW, ORANGE, GREEN, TEAL, CYAN, BLUE, PURPLE, MAGENTA, WHITE
    RED     = (255, 0, 0)
    YELLOW  = (200, 255, 0)
    ORANGE  = (255, 40, 0)
    GREEN   = (0, 255, 0)
    TEAL    = (0, 255, 120)
    CYAN    = (0, 255, 255)
    BLUE    = (0, 0, 255)
    PURPLE  = (180, 0, 255)
    MAGENTA = (255, 0, 20)
    WHITE   = (255, 255, 255)

    return pixel

#%%----------------------------------------------------------------------------
def setDotstar(color, brightness):
    # Set onboard LED color and brightness.
    # Works with both DotStar (S2) and NeoPixel (S3).
    if BOARD_TYPE == "feather_s3":
        # NeoPixel: brightness is set on the pixel object, not per-pixel
        dotstar.brightness = brightness
        dotstar[0] = color
    else:
        # DotStar: supports per-pixel brightness as 4th tuple element
        dotstar[0] = (color[0], color[1], color[2], brightness)

#%%----------------------------------------------------------------------------
def getWifiTime():
    # Connect WiFi, fetch UTC time via NTP, apply timezone/DST, set RTC.
    global secOld, minOld, hrOld, wifi_state

    # Check if we've had too many consecutive WiFi-failure resets
    nvm = microcontroller.nvm
    reset_count = nvm[NVM_WIFI_RESET_COUNT] if nvm[NVM_WIFI_RESET_MARKER] == WIFI_RESET_MARKER else 0
    print("WiFi reset count: %d" % reset_count)

    if reset_count >= MAX_WIFI_RESETS:
        print("Too many WiFi failures (%d resets), entering offline mode" % reset_count)
        # Clear counter so next manual power cycle tries WiFi again
        nvm[NVM_WIFI_RESET_COUNT] = 0
        nvm[NVM_WIFI_RESET_MARKER] = 0
        # Load timezone for offline operation
        timezone = load_timezone_nvm()
        set_wifi_state(WIFI_OFFLINE)
        ucStatus.text = "Offline Mode"
        setDotstar(YELLOW, 0.25)
        return {
            "wifiError": True,
            "ntpError": True,
            "rtc_time": rtc.datetime,
            "ipAddress": None,
            "timezone": timezone,
            "dst": False,
            "delta_s": None,
            "msg": "Offline mode - too many WiFi failures",
        }

    # Get WiFi credentials from settings.toml
    ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
    ntp_server = os.getenv("NTP_SERVER", "pool.ntp.org")

    # Load timezone from NVM or fallback to settings.toml
    timezone = load_timezone_nvm()

    if not ssid or not password:
        print("WiFi credentials missing in settings.toml!")
        return {
            "wifiError": True,
            "ntpError": False,
            "rtc_time": rtc.datetime,
            "ipAddress": None,
            "timezone": timezone,
            "dst": None,
            "delta_s": None,
            "msg": "Check settings.toml",
        }

    result = {
        "wifiError": False,
        "ntpError": False,
        "rtc_time": rtc.datetime,
        "ipAddress": None,
        "timezone": timezone,
        "dst": False,
        "delta_s": None,
        "msg": "Init",
    }

    setDotstar(PURPLE, 0.25)
    wifiCircle.fill = None
    ucStatus.text = "Connecting WiFi"; print("Connecting to WiFi")
    wifiStatus.text = "---"
    wifiAddress.text = "---"
    result["msg"] = "Connecting to WiFi"

    # Ensure clean state before connecting
    if wifi.radio.connected:
        wifi.radio.stop_station()
        sleepWithUpdates(1)

    print("Connecting to %s" % ssid)
    wifiStatus.text = "Connecting"

    # Try connection with retries
    wifi_connect_attempts = 3
    wifi_connected = False
    for attempt in range(wifi_connect_attempts):
        try:
            wifiStatus.text = "Try %d/%d" % (attempt + 1, wifi_connect_attempts)
            if attempt > 0:
                ucStatus.text = "WiFi Retry %d" % (attempt + 1)
                print("WiFi retry attempt %d of %d" % (attempt + 1, wifi_connect_attempts))
            wifi.radio.connect(ssid, password, timeout=15)
            # Verify connection actually succeeded
            time.sleep(0.5)
            if wifi.radio.connected:
                wifi_connected = True
                print("WiFi connect succeeded on attempt %d" % (attempt + 1))
                break
            else:
                print("WiFi connect returned but not connected, attempt %d" % (attempt + 1))
                if attempt < wifi_connect_attempts - 1:
                    wifiStatus.text = "Retry..."
                    sleepWithUpdates(3)
        except Exception as e:
            print("WiFi attempt %d failed: %s" % (attempt + 1, e))
            if attempt < wifi_connect_attempts - 1:
                wifiStatus.text = "Retry..."
                sleepWithUpdates(3)

    if not wifi_connected:
        result["wifiError"] = True
        result["msg"] = "WiFi Error"
        print("WiFi Error - All connect attempts failed")
        ucStatus.text = "WiFi Error"; print("WiFi Error")
        set_wifi_state(WIFI_OFFLINE)
        setDotstar(YELLOW, 0.25)
        return result

    # Wait for DHCP to assign IP address (up to 15 seconds)
    ucStatus.text = "DHCP Wait..."
    print("Waiting for DHCP...")
    for i in range(30):
        if wifi.radio.ipv4_address is not None:
            ucStatus.text = "DHCP OK"
            print("DHCP assigned IP after %d iterations" % i)
            break
        time.sleep(0.5)

    ipAddress = wifi.radio.ipv4_address
    result["ipAddress"] = ipAddress

    if not ipAddress:
        print("WARNING: No IP address assigned after DHCP wait")
        result["wifiError"] = True
        result["msg"] = "No IP"
        ucStatus.text = "No IP"
        set_wifi_state(WIFI_OFFLINE)
        setDotstar(YELLOW, 0.25)
        return result

    print("WiFi connected - IP:", ipAddress, "DNS:", wifi.radio.ipv4_dns)
    ucStatus.text = "WiFi Connected"; print("WiFi Available")
    wifiCircle.fill = 0xFFFFFF
    wifiStatus.text = ssid
    wifiAddress.text = str(ipAddress)
    setDotstar(GREEN, 0.25)
    result["msg"] = "WiFi Available"

    # Clear WiFi reset counter on successful connection
    if nvm[NVM_WIFI_RESET_MARKER] == WIFI_RESET_MARKER:
        print("Clearing WiFi reset counter (connection successful)")
        nvm[NVM_WIFI_RESET_COUNT] = 0
        nvm[NVM_WIFI_RESET_MARKER] = 0
    set_wifi_state(WIFI_CONNECTED, update_ui=False)  # UI updated below with IP

    pool = socketpool.SocketPool(wifi.radio)
    ntp_max_retries = 3
    ntp_success = False

    for ntp_attempt in range(ntp_max_retries):
        try:
            if ntp_attempt > 0:
                ucStatus.text = "NTP Retry %d" % (ntp_attempt + 1)
                print("NTP retry attempt %d of %d" % (ntp_attempt + 1, ntp_max_retries))
                sleepWithUpdates(2)  # Keep display updated during retry
            else:
                ucStatus.text = "NTP Sync"
            print("Fetching NTP from", ntp_server)
            result["msg"] = "NTP Sync"

            # Create NTP client and get UTC time (with increased timeout)
            ntp = adafruit_ntp.NTP(pool, server=ntp_server, tz_offset=0, socket_timeout=10)
            utc_time = ntp.datetime

            # Look up timezone offset and DST
            tz_offset_min = get_timezone_offset(timezone)
            dst_offset_min = calculate_dst_offset(timezone, utc_time)
            total_offset_min = tz_offset_min + dst_offset_min

            result["dst"] = dst_offset_min > 0

            # Apply offset to get local time
            utc_epoch = time.mktime(utc_time)
            local_epoch = utc_epoch + (total_offset_min * 60)
            local_time = time.localtime(local_epoch)

            # Build struct_time for RTC
            local_struct = time.struct_time((
                local_time.tm_year,
                local_time.tm_mon,
                local_time.tm_mday,
                local_time.tm_hour,
                local_time.tm_min,
                local_time.tm_sec,
                local_time.tm_wday,
                local_time.tm_yday,
                1 if result["dst"] else 0
            ))

            rtc_before = rtc.datetime

            WIFI_RESYNC_THRESHOLD_S = 120
            try:
                delta_s = abs(time.mktime(local_struct) - time.mktime(rtc_before))
            except Exception as e:
                print("Delta calc failed:", e)
                delta_s = WIFI_RESYNC_THRESHOLD_S

            result["delta_s"] = delta_s

            rtc.datetime = local_struct
            result["rtc_time"] = rtc.datetime

            if delta_s >= WIFI_RESYNC_THRESHOLD_S:
                print("Time drift %.1fs, resyncing" % delta_s)
                hrUpdate(forceHour=True)
                minUpdate()
                syncOldTrackers()

            tz_name = timezone
            for tz in TIMEZONES:
                if tz[0] == timezone:
                    tz_name = tz[1]
                    break
            print("RTC updated via NTP (%s, DST=%s)" % (tz_name, result["dst"]))
            ucStatus.text = "NTP Synced"
            result["msg"] = "RTC update via NTP"
            ntp_success = True
            break  # Success - exit retry loop

        except Exception as e:
            print("NTP Error (attempt %d): %s" % (ntp_attempt + 1, e))
            if ntp_attempt < ntp_max_retries - 1:
                # More retries available, continue loop
                continue

    # If all retries failed, set NTP error state
    if not ntp_success:
        setDotstar(CYAN, 0.25)
        ucStatus.text = "NTP Error"
        print("NTP Error - all %d retries failed" % ntp_max_retries)
        result["msg"] = "NTP Error"
        result["ntpError"] = True
        result["rtc_time"] = rtc.datetime

    return result


#------------------------------------------------------------------------------
def retryNtpSync():
    """Lightweight NTP sync retry - assumes WiFi is already connected.
    Returns True if sync succeeded, False otherwise."""
    global last_wifi_sync_time

    ntp_server = os.getenv("NTP_SERVER", "pool.ntp.org")
    timezone = load_timezone_nvm()

    print("Attempting NTP resync...")
    ucStatus.text = "NTP Retry"
    log_action("NTP retry at top of hour")

    try:
        pool = socketpool.SocketPool(wifi.radio)
        ntp = adafruit_ntp.NTP(pool, server=ntp_server, tz_offset=0)
        utc_time = ntp.datetime

        # Look up timezone offset and DST
        tz_offset_min = get_timezone_offset(timezone)
        dst_offset_min = calculate_dst_offset(timezone, utc_time)
        total_offset_min = tz_offset_min + dst_offset_min

        # Apply offset to get local time
        utc_epoch = time.mktime(utc_time)
        local_epoch = utc_epoch + (total_offset_min * 60)
        local_time = time.localtime(local_epoch)

        # Build struct_time for RTC
        local_struct = time.struct_time((
            local_time.tm_year,
            local_time.tm_mon,
            local_time.tm_mday,
            local_time.tm_hour,
            local_time.tm_min,
            local_time.tm_sec,
            local_time.tm_wday,
            local_time.tm_yday,
            1 if dst_offset_min > 0 else 0
        ))

        rtc.datetime = local_struct

        t = rtc.datetime
        last_wifi_sync_time = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)

        print("NTP resync successful")
        ucStatus.text = "NTP Synced"
        setDotstar(GREEN, 0.25)
        log_action("NTP resync successful")
        return True

    except Exception as e:
        print("NTP resync failed:", e)
        ucStatus.text = "NTP Error"
        log_action("NTP resync failed")
        return False


#------------------------------------------------------------------------------
def hour24ToHour12(hour24):
    # Convert 24h hour to 12h range (1-12).
    hour12 = hour24 % 12
    if hour12 == 0:
        hour12 = 12
    return hour12
#------------------------------------------------------------------------------
def hourIn(hour):
    # Map hour number to 4-column flipdot bit patterns.
    if hour > 12:
        hour = hour - 12

    id0 = 2
    id1 = 6
    id2 = 14
    id3 = 30

    idd0 = 1
    idd1 = 3
    idd2 = 7
    idd3 = 15

    fullIdx = ([[0,0,0,0],   #0
               [id0,0,0,0],  #1
               [id1,0,0,0],  #2
               [id2,0,0,0],  #3
               [id3,idd0,0,0], #4
               [id3,idd1,0,0], #5
               [id3,idd2,0,0], #6
               [id3,idd3,0,0], #7
               [id3,idd3,idd0,0], #8
               [id3,idd3,idd1,0], #9
               [id3,idd3,idd2,0], #10
               [id3,idd3,idd3,0], #11
               [15,15,15,15]]) #12
    data = fullIdx[hour]
    return data

#%%----------------------------------------------------------------------------
def shiftData(regData):
    # Shift 4 words into registers, latch, then clear outputs.
    oePin.value = OE_ENABLE

    for i in range(0, 4):
        latchPin.value = False
        simpleio.shift_out(dataPin, clockPin, (regData[i] >> 8), msb_first=True)
        simpleio.shift_out(dataPin, clockPin, regData[i], msb_first=True)

    latchPin.value = True
    latchPin.value = False
    time.sleep(0.005)

    for i in range(0, 4):
        latchPin.value = False
        simpleio.shift_out(dataPin, clockPin, 0, msb_first=True)
        simpleio.shift_out(dataPin, clockPin, 0, msb_first=True)

    latchPin.value = True
    latchPin.value = False
    oePin.value = OE_DISABLE

#%%----------------------------------------------------------------------------
def blankDisplay():
    # Run full blank-white-blank sequence and reset flip cache.
    print("Blanking Display")
    ucStatus.text = "Blanking Display"

    flipsPower(True)
    try:
        setFlips([0, 0, 0, 0], 1, managePower=False)
        time.sleep(2.5)

        setFlips([15, 15, 15, 15], 1, managePower=False)
        time.sleep(2.5)

        setFlips([0, 0, 0, 0], 1, managePower=False)
        time.sleep(2.5)
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()

#%%----------------------------------------------------------------------------
def roundTo(numIn):
    # Animate through hours then land on target hour; update cache.
    time.sleep(0.5)

    print("RoundTo Animation: (", numIn, ")", end=" ")

    flipsPower(True)
    try:
        for n in range(0, numIn):
            print(n, end=" ")
            setFlips(hourIn(n), 1, managePower=False)
            time.sleep(0.5)

        #print("|", numIn) 

        #setFlips(hourIn(numIn), 1, managePower=False)

        global lastHourShown
        lastHourShown = numIn
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()

#%%----------------------------------------------------------------------------
def hallStable(expected, samples=5, delay=0.0005):
    # Debounce hall sensor by requiring N consecutive readings.
    for _ in range(samples):
        if home.value != expected:
            return False
        time.sleep(delay)
    return True

#%%----------------------------------------------------------------------------
def syncOldTrackers():
    # Sync secOld/minOld/hrOld to RTC so main loop won't re-trigger updates.
    global secOld, minOld, hrOld
    t = rtc.datetime
    secOld = t.tm_sec
    minOld = t.tm_min
    hrOld  = t.tm_hour

#%%----------------------------------------------------------------------------
def setupWebServer(pool):
    # Initialize HTTP server with routes for status and control.
    global server
    server = Server(pool, debug=True)

    @server.route("/")
    def index_route(request: Request):
        with open(INDEX_HTML_FILE, "r") as f:
            html_content = f.read()
        return Response(request, body=html_content, content_type="text/html")

    @server.route("/status.json")
    def status_route(request: Request):
        try:
            t = rtc.datetime
            time_str = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
            hr12 = hour24ToHour12(t.tm_hour)
        except:
            time_str = "??:??:??"
            hr12 = 0

        ssid = os.getenv("CIRCUITPY_WIFI_SSID", "Unknown")

        # Load timezone from NVM
        tz = load_timezone_nvm()
        tz_name = tz
        for timezone in TIMEZONES:
            if timezone[0] == tz:
                tz_name = timezone[1]
                break

        # Get AS5600 status
        as5600_angle = read_as5600_angle()
        as5600_deg = round(as5600_angle * 360.0 / 4096.0, 1) if as5600_angle is not None else None

        status = {
            "time": time_str,
            "hour_12": hr12,
            "minute": t.tm_min if t else 0,
            "wifi_connected": wifi.radio.connected,
            "ip_address": str(wifi.radio.ipv4_address) if wifi.radio.connected else "None",
            "ssid": ssid,
            "timezone": tz,
            "timezone_name": tz_name,
            "motor_position": stepNow,
            "motor_steps_total": STEPS,
            "last_hour_shown": lastHourShown if lastHourShown else 0,
            "flipdot_power": flipPwrIsOn,
            "uptime_s": get_uptime(),
            "free_memory": gc.mem_free(),
            "last_wifi_sync": last_wifi_sync_time,
            "home_offset": load_home_offset_nvm(),
            "step_delay_us": int(STEP_DELAY * 1000000),
            "as5600_available": as5600_sensor is not None,
            "as5600_angle": as5600_angle,
            "as5600_degrees": as5600_deg,
        }
        return Response(request, body=json.dumps(status), content_type="application/json")

    @server.route("/log.json")
    def log_route(request: Request):
        return Response(request, body=json.dumps({"entries": action_log}), content_type="application/json")

    @server.route("/wipe", POST)
    def wipe_route(request: Request):
        log_action("Wipe display triggered via web")
        blankDisplay()                        # Clear display
        t = rtc.datetime
        numIn = hour24ToHour12(t.tm_hour)
        roundTo(numIn)                        # Animate flipdots to current hour
        findExactHome()               # Re-home minute hand
        hrUpdate(forceHour=True)              # Force hour refresh
        minUpdate()                           # Sync minute hand
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/set_hour", POST)
    def set_hour_route(request: Request):
        log_action("+1 hour via web")
        setHrs()
        hrUpdate(forceHour=True)
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/set_min", POST)
    def set_min_route(request: Request):
        log_action("+1 minute via web")
        setMins()
        minUpdate()
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/refresh", POST)
    def refresh_route(request: Request):
        log_action("Refresh hour via web")
        hrUpdate(forceHour=True)
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/sync_wifi", POST)
    def sync_wifi_route(request: Request):
        global last_wifi_sync_time
        log_action("WiFi sync triggered via web")
        result = getWifiTime()
        if not result["wifiError"]:
            t = rtc.datetime
            last_wifi_sync_time = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
        return Response(request, body=json.dumps({"ok": not result["wifiError"]}), content_type="application/json")

    @server.route("/get_timezone")
    def get_timezone_route(request: Request):
        # Return current timezone and list of all available timezones.
        current_tz = load_timezone_nvm()

        tz_list = []
        for tz in TIMEZONES:
            tz_list.append({
                "key": tz[0],
                "name": tz[1],
                "offset": tz[2],
                "dst": tz[3] is not None
            })

        response = {
            "current": current_tz,
            "timezones": tz_list
        }
        return Response(request, body=json.dumps(response), content_type="application/json")

    @server.route("/set_timezone", POST)
    def set_timezone_route(request: Request):
        # Set timezone, save to NVM, and immediately resync clock.
        global last_wifi_sync_time

        try:
            # Parse JSON body
            body = request.body.decode("utf-8") if request.body else "{}"
            data = json.loads(body)
            new_tz = data.get("timezone", "").strip()

            # Validate timezone exists
            valid = False
            tz_name = new_tz
            for tz in TIMEZONES:
                if tz[0] == new_tz:
                    valid = True
                    tz_name = tz[1]
                    break

            if not valid:
                return Response(
                    request,
                    body='{"ok":false,"error":"Invalid timezone"}',
                    content_type="application/json"
                )

            # Save to NVM
            if not save_timezone_nvm(new_tz):
                return Response(
                    request,
                    body='{"ok":false,"error":"Failed to save to NVM"}',
                    content_type="application/json"
                )

            log_action("Timezone set to " + tz_name)

            # Immediately resync with new timezone
            result = getWifiTime()
            if not result["wifiError"]:
                t = rtc.datetime
                last_wifi_sync_time = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)

            return Response(
                request,
                body=json.dumps({"ok": not result["wifiError"], "timezone": new_tz, "name": tz_name}),
                content_type="application/json"
            )

        except Exception as e:
            print("set_timezone error:", e)
            return Response(
                request,
                body='{"ok":false,"error":"Parse error"}',
                content_type="application/json"
            )

    # Animation routes
    @server.route("/anim/demo", POST)
    def anim_demo_route(request: Request):
        log_action("Animation: Demo sequence")
        anim_demo()
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/anim/chaos", POST)
    def anim_chaos_route(request: Request):
        log_action("Animation: Random chaos")
        anim_chaos()
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/anim/sync", POST)
    def anim_sync_route(request: Request):
        log_action("Animation: Sync dance")
        anim_sync()
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/home", POST)
    def home_route(request: Request):
        # Home minute hand, pause at 12 o'clock, then return to current time
        log_action("Home motor triggered via web")
        findExactHome()  # Use current algorithm (swap to V2 after testing)
        time.sleep(2)  # Pause at 12 o'clock for verification
        minUpdate()  # Return to current time
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/cal_start", POST)
    def cal_start_route(request: Request):
        # Enter calibration mode - disable motor for manual positioning
        enter_calibration_mode()
        log_action("Calibration mode started")
        as5600_angle = read_as5600_angle()
        return Response(request, body='{"ok":true,"as5600":%s}' % (as5600_angle if as5600_angle else "null"), content_type="application/json")

    @server.route("/cal_save", POST)
    def cal_save_route(request: Request):
        # Save current AS5600 position as 12 o'clock
        global calibration_mode, as5600_home_offset, stepNow
        if not calibration_mode:
            return Response(request, body='{"ok":false,"error":"Not in calibration mode"}', content_type="application/json")

        if as5600_sensor and as5600_sensor.magnet_detected:
            angle = read_as5600_angle()
            if angle is not None:
                as5600_home_offset = angle
                save_as5600_cal_nvm(angle)
                log_action("AS5600 calibration saved: %d" % angle)
                calibration_mode = False
                en.value = motorEnabled
                stepNow = 0
                minUpdate()
                return Response(request, body='{"ok":true,"as5600_offset":%d}' % angle, content_type="application/json")
            else:
                return Response(request, body='{"ok":false,"error":"AS5600 read failed"}', content_type="application/json")
        else:
            return Response(request, body='{"ok":false,"error":"No magnet detected"}', content_type="application/json")

    @server.route("/cal_cancel", POST)
    def cal_cancel_route(request: Request):
        # Cancel calibration mode without saving
        global calibration_mode
        calibration_mode = False
        en.value = motorEnabled
        log_action("Calibration cancelled")
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/get_speed")
    def get_speed_route(request: Request):
        # Return current step delay in microseconds
        delay_us = int(STEP_DELAY * 1000000)
        return Response(request, body='{"delay_us":%d}' % delay_us, content_type="application/json")

    @server.route("/set_speed", POST)
    def set_speed_route(request: Request):
        # Set step delay in microseconds (100-1000 range)
        global STEP_DELAY
        try:
            body = request.body.decode("utf-8") if request.body else "{}"
            data = json.loads(body)
            delay_us = int(data.get("delay_us", DEFAULT_STEP_DELAY_US))
            # Clamp to valid range
            delay_us = max(100, min(1000, delay_us))
            save_step_delay_nvm(delay_us)
            STEP_DELAY = delay_us / 1000000.0
            log_action("Step delay set to %d us" % delay_us)
            return Response(request, body='{"ok":true,"delay_us":%d}' % delay_us, content_type="application/json")
        except Exception as e:
            print("set_speed error:", e)
            return Response(request, body='{"ok":false,"error":"Parse error"}', content_type="application/json")

    @server.route("/status")
    def status_route(request: Request):
        # HTTP endpoint for status polling (replaces WebSocket)
        status = getStatusDict()
        return Response(request, body=json.dumps(status), content_type="application/json")

    return server

#%%----------------------------------------------------------------------------
def sleepWithUpdates(seconds):
    """Sleep while keeping OLED display and minute hand updated."""
    global secOld, minOld
    for _ in range(int(seconds)):
        t = rtc.datetime
        # Update OLED every second
        if secOld != t.tm_sec:
            screenUpdate()
            secOld = t.tm_sec
        # Update minute hand when minute changes
        if minOld != t.tm_min:
            minUpdate()
            minOld = t.tm_min
        time.sleep(1)

#%%----------------------------------------------------------------------------
def scanForAP(ssid, max_attempts=3):
    """Scan for WiFi AP and return True if found with RSSI."""
    for attempt in range(max_attempts):
        ucStatus.text = "WiFi Scan %d" % (attempt + 1)
        print("Scanning for WiFi networks (attempt %d/%d)..." % (attempt + 1, max_attempts))
        try:
            found_networks = []
            for network in wifi.radio.start_scanning_networks():
                found_networks.append((network.ssid, network.rssi))
                if network.ssid == ssid:
                    ucStatus.text = "AP Found"
                    print("  Found %s (RSSI: %d dBm)" % (ssid, network.rssi))
                    wifi.radio.stop_scanning_networks()
                    return True, network.rssi
            wifi.radio.stop_scanning_networks()
            ucStatus.text = "AP Not Found"
            print("  Scanned %d networks, %s not found" % (len(found_networks), ssid))
            if found_networks:
                print("  Visible: %s" % ", ".join(n[0] for n in found_networks[:5]))
        except Exception as e:
            print("  Scan error: %s" % e)
            try:
                wifi.radio.stop_scanning_networks()
            except:
                pass
        if attempt < max_attempts - 1:
            time.sleep(2)
    return False, 0

#%%----------------------------------------------------------------------------
def teardownNetwork():
    # Cleanly tear down network stack for recovery.
    global server, wifi_state

    ucStatus.text = "Net Teardown..."
    print("Tearing down network stack...")

    # Stop server (if adafruit_httpserver supports it)
    if server:
        try:
            server.stop()
        except:
            pass
        server = None

    # Disconnect WiFi cleanly and reset radio
    try:
        wifi.radio.stop_station()
    except:
        pass

    # Try to reset WiFi radio by disabling/enabling with longer delays
    try:
        ucStatus.text = "WiFi Reset..."
        print("Resetting WiFi radio (this takes ~15s)...")
        wifi.radio.enabled = False
        sleepWithUpdates(5)   # 5 seconds disabled to fully reset
        wifi.radio.enabled = True
        sleepWithUpdates(10)  # 10 seconds for radio to fully initialize
        ucStatus.text = "WiFi Reset OK"
        print("WiFi radio reset complete")
    except Exception as e:
        ucStatus.text = "WiFi Reset Err"
        print("WiFi radio reset error: %s" % e)

    set_wifi_state(WIFI_DISCONNECTED)
    ucStatus.text = "Net Down"
    print("Network stack torn down")

#%%----------------------------------------------------------------------------
def recoverNetwork(max_wifi_attempts=3, wifi_timeout=15):
    # Attempt full network stack recovery.
    global server, wifi_state, last_successful_poll, poll_failure_count

    print("Starting network recovery...")
    ucStatus.text = "Network Recovery"
    set_wifi_state(WIFI_CONNECTING)
    setDotstar(PURPLE, 0.25)
    wifiCircle.fill = None

    ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    password = os.getenv("CIRCUITPY_WIFI_PASSWORD")

    if not ssid or not password:
        print("WiFi credentials missing")
        wifiStatus.text = "No Creds"
        setDotstar(YELLOW, 0.25)
        return False

    # Check if WiFi is actually still connected before tearing down
    if wifi.radio.connected and wifi.radio.ipv4_address:
        ucStatus.text = "WiFi OK"
        print("WiFi still connected (%s), skipping teardown - just restarting server" % wifi.radio.ipv4_address)
        # Will set WIFI_CONNECTED after server restart
    else:
        # Step 1: Tear down existing connections
        ucStatus.text = "Full Teardown"
        print("WiFi not connected, performing full teardown...")
        teardownNetwork()

        # Log radio state for debugging
        print("Radio state after teardown:")
        print("  enabled=%s, connected=%s" % (wifi.radio.enabled, wifi.radio.connected))
        try:
            mac = ":".join("%02x" % b for b in wifi.radio.mac_address)
            print("  mac=%s" % mac)
        except:
            pass

        # Step 1.5: Scan for AP before attempting connection
        wifiStatus.text = "Scanning..."
        ap_found, rssi = scanForAP(ssid)
        if not ap_found:
            ucStatus.text = "AP Not Found"
            print("AP %s not visible after scanning - may be out of range" % ssid)
            wifiStatus.text = "AP Not Found"
            setDotstar(YELLOW, 0.25)
            # Increment reset counter and check if we should enter offline mode instead
            nvm = microcontroller.nvm
            current_count = nvm[NVM_WIFI_RESET_COUNT] if nvm[NVM_WIFI_RESET_MARKER] == WIFI_RESET_MARKER else 0
            nvm[NVM_WIFI_RESET_COUNT] = current_count + 1
            nvm[NVM_WIFI_RESET_MARKER] = WIFI_RESET_MARKER
            print("WiFi reset counter: %d -> %d" % (current_count, current_count + 1))
            # Stay in offline mode instead of resetting
            ucStatus.text = "Offline Mode"
            print("Staying in offline mode (AP not found)")
            set_wifi_state(WIFI_OFFLINE)
            return False

        ucStatus.text = "AP Found"
        print("AP %s found (RSSI: %d dBm), proceeding with connection..." % (ssid, rssi))
        wifiStatus.text = "Connecting..."

        # Step 2: Reconnect WiFi with retries and exponential backoff
        wifi_connected = False
        for attempt in range(max_wifi_attempts):
            # Exponential backoff: 5s, 10s, 15s between attempts
            if attempt > 0:
                backoff = (attempt + 1) * 5
                print("Waiting %ds before retry %d/%d..." % (backoff, attempt + 1, max_wifi_attempts))
                wifiStatus.text = "Retry in %ds" % backoff
                sleepWithUpdates(backoff)

            ucStatus.text = "Connect %d/%d" % (attempt + 1, max_wifi_attempts)
            print("WiFi connect attempt %d/%d..." % (attempt + 1, max_wifi_attempts))
            print("  Radio state: enabled=%s, connected=%s" % (wifi.radio.enabled, wifi.radio.connected))

            try:
                wifi.radio.connect(ssid, password, timeout=wifi_timeout)
                # Verify connection actually succeeded (connect() doesn't always raise on failure)
                time.sleep(1)  # Give radio time to settle
                if wifi.radio.connected:
                    wifi_connected = True
                    ucStatus.text = "Connected!"
                    print("WiFi connect succeeded, connected=%s, ip=%s" % (wifi.radio.connected, wifi.radio.ipv4_address))
                    break
                else:
                    ucStatus.text = "Not Connected"
                    print("WiFi connect returned but not connected (attempt %d)" % (attempt + 1))
            except Exception as e:
                print("WiFi attempt %d exception: %s" % (attempt + 1, e))

        if not wifi_connected:
            ucStatus.text = "WiFi Failed"
            print("WiFi recovery failed after %d attempts" % max_wifi_attempts)
            wifiStatus.text = "WiFi Failed"
            setDotstar(YELLOW, 0.25)
            # Increment reset counter and check if we should enter offline mode instead
            nvm = microcontroller.nvm
            current_count = nvm[NVM_WIFI_RESET_COUNT] if nvm[NVM_WIFI_RESET_MARKER] == WIFI_RESET_MARKER else 0
            nvm[NVM_WIFI_RESET_COUNT] = current_count + 1
            nvm[NVM_WIFI_RESET_MARKER] = WIFI_RESET_MARKER
            print("WiFi reset counter: %d -> %d" % (current_count, current_count + 1))
            # Stay in offline mode instead of resetting
            ucStatus.text = "Offline Mode"
            print("Staying in offline mode (connect failed)")
            set_wifi_state(WIFI_OFFLINE)
            return False

        # Step 3: Wait for DHCP (up to 15 seconds)
        ucStatus.text = "DHCP Wait..."
        print("Waiting for DHCP...")
        for i in range(30):  # 30 × 0.5s = 15 seconds
            ip = wifi.radio.ipv4_address
            if ip:
                ucStatus.text = "DHCP OK"
                print("DHCP assigned IP after %d iterations: %s" % (i, ip))
                break
            time.sleep(0.5)

        if not wifi.radio.ipv4_address:
            ucStatus.text = "No IP"
            print("No IP address assigned after 15s")
            wifiStatus.text = "No IP"
            setDotstar(YELLOW, 0.25)
            return False

        print("WiFi recovered: %s" % wifi.radio.ipv4_address)

        # Clear WiFi reset counter on successful recovery
        nvm = microcontroller.nvm
        if nvm[NVM_WIFI_RESET_MARKER] == WIFI_RESET_MARKER:
            print("Clearing WiFi reset counter (recovery successful)")
            nvm[NVM_WIFI_RESET_COUNT] = 0
            nvm[NVM_WIFI_RESET_MARKER] = 0

    # Step 4: Recreate socket pool and server
    try:
        ucStatus.text = "Server Start"
        pool = socketpool.SocketPool(wifi.radio)
        server = setupWebServer(pool)
        clock_web_port = int(os.getenv("CLOCK_WEB_PORT", "80"))
        server.start("0.0.0.0", port=clock_web_port)
        last_successful_poll = time.monotonic()
        poll_failure_count = 0
        ucStatus.text = "Server OK"
        print("Server recovered on port %d" % clock_web_port)
    except Exception as e:
        ucStatus.text = "Server Fail"
        print("Server recovery failed: %s" % e)
        server = None
        set_wifi_state(WIFI_DISCONNECTED)
        setDotstar(CYAN, 0.25)
        return False

    # Step 5: Update UI and set connected state
    set_wifi_state(WIFI_CONNECTED, update_ui=False)  # Don't use default UI
    wifiCircle.fill = 0xFFFFFF
    wifiStatus.text = ssid
    wifiAddress.text = str(wifi.radio.ipv4_address)
    ucStatus.text = "WiFi Recovered"
    setDotstar(GREEN, 0.25)
    log_action("Network recovered: " + str(wifi.radio.ipv4_address))

    return True

#%%----------------------------------------------------------------------------
def checkNetworkHealth():
    # Check if network stack is healthy, return False if recovery needed.
    global last_successful_poll, wifi_state

    now = time.monotonic()

    # Check 1: WiFi connected with valid IP
    wifi_ok = wifi.radio.connected and wifi.radio.ipv4_address is not None
    if not wifi_ok:
        # Double-check - sometimes radio reports False briefly
        time.sleep(0.5)
        wifi_ok = wifi.radio.connected and wifi.radio.ipv4_address is not None
        if not wifi_ok:
            ucStatus.text = "WiFi Lost"
            print("Health check: WiFi disconnected (connected=%s, ip=%s)" % (
                wifi.radio.connected, wifi.radio.ipv4_address))
            set_wifi_state(WIFI_DISCONNECTED)
            return False

    # Check 2: Server poll succeeding (if we have a server)
    if server and last_successful_poll > 0 and (now - last_successful_poll) > POLL_HEALTH_TIMEOUT:
        ucStatus.text = "Poll Timeout"
        print("Health check: No successful poll in %ds" % POLL_HEALTH_TIMEOUT)
        set_wifi_state(WIFI_DISCONNECTED)
        return False

    return True

#%%----------------------------------------------------------------------------
# Setup Functions
#%%----------------------------------------------------------------------------
# Startup Stuff
start_time = time.monotonic()
sayHello()

# Setup Leds
led = setupLed()
dotstar = setupDot()
setDotstar(YELLOW,0.5)

# Setup Clock and Buttons
i2c = setupI2C()
rtc = setupRTC(i2c)
setupAS5600(i2c)  # Initialize AS5600 if available
butA,butB,butC = setupButton()
t = rtc.datetime

# Re-sync old trackers to current time so loop doesn't fight you
syncOldTrackers()

# Setup the Display
[screen, timeArea, ucStatus, wifiCircle, wifiStatus, wifiAddress] = setupScreen(i2c)
ucStatus.text = "Start Up"

# Setup the Relay for the Dots
pwr = setupFlipdotPower()

# Setup the Motor
[en,step,direct,home,stepSelect]= setupMotor()

# Play Startup Animation
blankDisplay()
time.sleep(1.0)

# Determine MagOffset
ucStatus.text = "Magnet Offset"
time.sleep(1.0)
multiStep(1, r.randint(125, STEPS), STEP_DELAY)
time.sleep(0.25)

# Check for saved AS5600 calibration (overrides findExactHome AS5600 capture)
saved_cal = load_as5600_cal_nvm()
if saved_cal is not None:
    as5600_home_offset = saved_cal
    print("Using saved AS5600 calibration: %d" % saved_cal)
    findExactHome(skip_as5600_capture=True)  # Home to hall sensor but keep saved cal
else:
    print("No AS5600 calibration - using findExactHome")
    findExactHome()

# Debug: show AS5600 home offset
print(f"DEBUG: as5600_home_offset = {as5600_home_offset}")
if as5600_sensor:
    current = read_as5600_angle()
    print(f"DEBUG: current AS5600 reading = {current}")

# Show the Current RTC Time
ucStatus.text = "Show Time"
time.sleep(1.0)
hrUpdate(forceHour=True)
minUpdate()
screenUpdate()

# Connect to Wifi - delay allows WiFi radio to stabilize after motor init
ucStatus.text = "Connecting to Wifi"
time.sleep(3)
wifi_status = getWifiTime()
print(
    wifi_status["msg"],
    "wifi_ok=", (not wifi_status["wifiError"]),
    "ntp_ok=", (not wifi_status["ntpError"]),
    "ip=", wifi_status["ipAddress"],
    "tz=", wifi_status["timezone"],
    "dst=", wifi_status["dst"],
    "delta_s=", wifi_status["delta_s"],
)

# Track if NTP failed at startup for hourly retry
ntp_failed_at_startup = wifi_status.get("ntpError", False)

# Start Web Server if WiFi connected (even if NTP failed)
if not wifi_status["wifiError"]:
    ucStatus.text = "Starting Web Server"
    t = rtc.datetime
    last_wifi_sync_time = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
    log_action("Clock started")
    log_action("WiFi connected: " + str(wifi_status["ipAddress"]))
    if wifi_status.get("ntpError", False):
        log_action("NTP sync failed - will retry at top of hour")
    try:
        pool = socketpool.SocketPool(wifi.radio)
        server = setupWebServer(pool)
        clock_web_port = int(os.getenv("CLOCK_WEB_PORT", "80"))
        server.start("0.0.0.0", port=clock_web_port)
        set_wifi_state(WIFI_CONNECTED, update_ui=False)  # UI already set by getWifiTime
        last_successful_poll = time.monotonic()  # Initialize poll tracker
        print("Web server started at http://{}:{}".format(wifi.radio.ipv4_address, clock_web_port))
        log_action("Web server started")
    except Exception as e:
        print("Web server failed to start:", e)
        server = None
        set_wifi_state(WIFI_DISCONNECTED)

#%%----------------------------------------------------------------------------
# Main
#%%----------------------------------------------------------------------------
print("Starting Main Loop")

last_wifi_check = time.monotonic()
wifi_check_interval = 30  # Check WiFi every 30 seconds

# NTP sync settings - sync at top of hour, one retry on startup failure
ntp_has_error = wifi_status.get("ntpError", False)
ntp_retry_pending = ntp_has_error  # One retry allowed if startup failed
ntp_retry_time = time.monotonic() + 60 if ntp_has_error else 0

while True:
    # Poll web server for incoming requests
    if server:
        try:
            server.poll()
            last_successful_poll = time.monotonic()
            poll_failure_count = 0
        except Exception as e:
            print("Server poll error:", e)
            poll_failure_count += 1
            if poll_failure_count >= POLL_FAILURE_THRESHOLD:
                print("Poll failed %d times, marking unhealthy" % poll_failure_count)
                set_wifi_state(WIFI_DISCONNECTED)

    # Check network health periodically and recover if needed
    # Skip automatic recovery when in WIFI_OFFLINE state (only retry via button or top-of-hour)
    if wifi_state != WIFI_OFFLINE and time.monotonic() - last_wifi_check > wifi_check_interval:
        last_wifi_check = time.monotonic()

        if not checkNetworkHealth():
            print("Network unhealthy, initiating recovery...")
            if recoverNetwork():
                print("Network recovery successful")
            else:
                print("Network recovery failed, entering offline mode")

    # One-time NTP retry if startup failed (after 1 minute)
    if ntp_retry_pending and time.monotonic() > ntp_retry_time:
        ntp_retry_pending = False  # Only try once
        if wifi.radio.connected:
            print("Retrying NTP sync after startup failure...")
            result = getWifiTime()
            ntp_has_error = result.get("ntpError", False)
            if not ntp_has_error:
                print("NTP retry successful")
                log_action("NTP retry OK")

    t = rtc.datetime

    # Perform Screen Update Every Second
    secTest = t.tm_sec
    if secOld != secTest:
        screenUpdate()
        secOld = secTest

    # Perform Mech Update Every Minute
    minTest = t.tm_min
    if minOld != minTest:
        minUpdate()
        minOld = minTest

    # Perform Mech Update Every Hour
    hrTest = t.tm_hour
    if hrOld != hrTest:
        hrUpdate(forceHour=True)
        goHome()
        print(timeArea.text)

        # Offline mode: retry WiFi at top of hour
        if wifi_state == WIFI_OFFLINE and OFFLINE_RETRY_AT_TOP_OF_HOUR:
            if hrTest != last_wifi_retry_hour:
                ucStatus.text = "Offline Retry"
                print("Offline mode: top of hour, attempting WiFi reconnection...")
                last_wifi_retry_hour = hrTest
                if recoverNetwork():
                    ucStatus.text = "WiFi Back!"
                    print("WiFi recovered from offline mode!")
                    log_action("WiFi recovered from offline")
                else:
                    ucStatus.text = "Retry Failed"
                    print("WiFi retry failed, will try again next hour")

        # Hourly NTP sync at top of hour (only if WiFi connected)
        if wifi.radio.connected:
            ucStatus.text = "Hourly NTP..."
            print("Hourly NTP sync...")
            result = getWifiTime()
            ntp_has_error = result.get("ntpError", False)
            if not ntp_has_error:
                log_action("Hourly NTP sync OK")

        hrOld = hrTest

        # Retry NTP sync at the top of each hour if it failed at startup
        if ntp_failed_at_startup and wifi.radio.connected:
            if retryNtpSync():
                ntp_failed_at_startup = False  # Success - stop retrying

    # Begin Button Testing
    didManualUpdate = False   # Track whether a button caused a time/mech change

    if butA.value == 0:
        # Track press start time for long-press detection
        press_start = time.monotonic()
        is_long_press = False

        # Wait for release or long-press threshold
        while butA.value == 0:
            held_time = time.monotonic() - press_start
            if held_time >= LONG_PRESS_THRESHOLD:
                # Long press - WiFi reconnect
                is_long_press = True
                print("Button A - Long press, attempting WiFi reconnect...")
                ucStatus.text = "WiFi Reconnect..."
                recoverNetwork()  # Will set state to CONNECTING then CONNECTED/OFFLINE
                # Wait for button release
                while butA.value == 0:
                    time.sleep(0.05)
                break
            time.sleep(0.05)

        if not is_long_press:
            # Short press - original behavior
            print("Button A - Short press, re-homing")
            ucStatus.text = "Re-homing..."
            blankDisplay()        # Clear display before re-animating hour

            t = rtc.datetime
            numIn = hour24ToHour12(t.tm_hour)
            roundTo(numIn)        # Animate flipdots to current hour

            goHome()  # Re-home minute hand
            hrUpdate(forceHour=True)              # Force hour refresh
            minUpdate()                           # Sync minute hand

            didManualUpdate = True

    elif butB.value == 0:
        # Track press start time for long-press detection
        press_start = time.monotonic()
        is_long_press = False

        # Wait for release or long-press threshold
        while butB.value == 0:
            held_time = time.monotonic() - press_start
            if held_time >= LONG_PRESS_THRESHOLD:
                # Long press - sync animation
                is_long_press = True
                ucStatus.text = "Sync Demo"
                print("Button B - Long press, sync animation...")
                anim_sync()
                # Wait for button release
                while butB.value == 0:
                    time.sleep(0.05)
                break
            time.sleep(0.05)

        if not is_long_press:
            # Short press - increment hour
            ucStatus.text = "+1 Hour"
            print("Button B - Short press, increment hour")
            setHrs()
            hrUpdate(forceHour=True)
        didManualUpdate = True

    elif butC.value == 0:
        # Track press start time for long-press detection
        press_start = time.monotonic()
        is_long_press = False

        # Wait for release or long-press threshold
        while butC.value == 0:
            held_time = time.monotonic() - press_start
            if held_time >= LONG_PRESS_THRESHOLD:
                is_long_press = True
                if calibration_mode:
                    # Already in calibration - confirm and save
                    print("Button C - Long press, confirming calibration...")
                    confirm_calibration()
                else:
                    # Enter calibration mode
                    print("Button C - Long press, entering calibration...")
                    enter_calibration_mode()
                # Wait for button release
                while butC.value == 0:
                    time.sleep(0.05)
                break
            time.sleep(0.05)

        if not is_long_press:
            if calibration_mode:
                # In calibration mode, short press shows reminder
                ucStatus.text = "Hold C to save"
                time.sleep(0.5)
                ucStatus.text = "CAL: Move to 12"
            else:
                # Normal short press - increment minute
                setMins()
                minUpdate()
                didManualUpdate = True

    else:
        serviceFlipPowerWindow()  # Handle delayed flipdot power-off
        time.sleep(0.01)          # Reduced idle delay for better server responsiveness

    if didManualUpdate:
        syncOldTrackers()     # Prevent main loop from re-triggering updates
    else:
        serviceFlipPowerWindow()
