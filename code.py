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
#import adafruit_pcf8523

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

# LED Libraries
import adafruit_dotstar


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

# Calibration tracking (for interactive calibration via web UI)
calibration_steps = 0  # Tracks nudges during calibration session
 
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
def writeBit(value, bitIdx, bitValue):
    # Set/clear bitIdx in value based on bitValue.
    if bitValue == 1:  # setBit
        output = value | (1 << bitIdx)
    else:  # clear Bit
        output = value & ~(1 << bitIdx)
    return output

#------------------------------------------------------------------------------
def leftRotate(n, d):
    # Rotate 12-bit integer n left by d bits.
    intBits = 12
    result = (n << d) | (n >> (intBits - d))
    return result

#------------------------------------------------------------------------------
def rightRotate(n, d):
    # Rotate 12-bit integer n right by d bits (masked).
    intBits = 12
    result = (n >> d) | (n << (intBits - d)) & 0xFFFFFFFF
    return result

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
# NVM Storage for Timezone (index 0 = timezone index into TIMEZONES tuple)
# NVM persists across reboots without filesystem access
#%%----------------------------------------------------------------------------
def load_timezone_nvm():
    # Load timezone key from NVM. Returns key string or default.
    try:
        tz_index = microcontroller.nvm[0]
        if tz_index < len(TIMEZONES):
            return TIMEZONES[tz_index][0]
    except Exception as e:
        print("NVM read error:", e)
    return os.getenv("TIMEZONE", "US/Eastern")

#%%----------------------------------------------------------------------------
def save_timezone_nvm(tz_key):
    # Save timezone key to NVM. Returns True on success.
    for i, tz in enumerate(TIMEZONES):
        if tz[0] == tz_key:
            try:
                microcontroller.nvm[0] = i
                print("Timezone saved to NVM: index", i, tz_key)
                return True
            except Exception as e:
                print("NVM write error:", e)
                return False
    return False

#%%----------------------------------------------------------------------------
def load_home_offset_nvm():
    # Load home offset from NVM byte 1. Returns signed int (-127 to +127).
    # NVM byte 0 means uninitialized = no offset
    # NVM byte 1-255 maps to offset -127 to +127 (stored = offset + 128)
    try:
        stored = microcontroller.nvm[1]
        if stored == 0:  # Uninitialized NVM
            return 0
        offset = stored - 128  # Convert from unsigned (1-255) to signed (-127 to +127)
        return offset
    except Exception as e:
        print("NVM home offset read error:", e)
    return 0

#%%----------------------------------------------------------------------------
def save_home_offset_nvm(offset):
    # Save home offset to NVM byte 1. Offset must be -127 to +127.
    # stored = offset + 128, so offset 0 = stored 128
    try:
        # Clamp to valid range (-127 to +127, since stored 0 = uninitialized)
        offset = max(-127, min(127, offset))
        stored = offset + 128  # Convert from signed to unsigned (1-255)
        microcontroller.nvm[1] = stored
        print("Home offset saved to NVM:", offset, "steps")
        return True
    except Exception as e:
        print("NVM home offset write error:", e)
        return False

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
    print("\nHello from FeatherS2!")
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
    global STEPS
    STEPS = 800  # (2 usteps * 400 = 800 steps per revolution)

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
    time.sleep(delay)
    step.value = False
    time.sleep(delay)

    global stepNow
    if data == 0:
        stepNow -= 1
    else:
        stepNow += 1
    stepNow %= STEPS
    hallTest()

#%%----------------------------------------------------------------------------
def multiStep(data, steps, delay):
    # Step motor multiple times with enable control.
    en.value = motorEnabled
    for _ in range(steps):
        oneStep(data, delay)
    #en.value = motorDisabled

#%%----------------------------------------------------------------------------
def moveHome(delay):
    # Spin motor until hall sensor detects magnet; zero stepNow.
    en.value = motorEnabled
    while 1:
        oneStep(1, delay)
        if home.value == False:
            global stepNow
            stepNow = 0
            break
    #en.value = motorDisabled

#%%----------------------------------------------------------------------------
def findExactHome(delay):
    # Find magnet center using symmetric edge detection.
    # Both edges detected at release point for consistency.
    print('Finding Exact Home')
    en.value = motorEnabled

    global stepNow
    stepNow = 0  # Reset counter for relative measurements

    # Step 1: Move forward until hall triggers (enter magnet zone)
    print('Step 1: Finding magnet zone')
    while not hallStable(False):
        oneStep(1, delay)

    # Step 2: Reverse until hall releases (precise edge A)
    print('Step 2: Finding edge A (release point)')
    while not hallStable(True):
        oneStep(0, delay)
    edge_a = stepNow
    print('Edge A at step: %d' % edge_a)

    # Step 3: Continue reversing until hall triggers (other side of magnet)
    print('Step 3: Passing through to other side')
    while not hallStable(False):
        oneStep(0, delay)

    # Step 4: Reverse again (forward) until hall releases (precise edge B)
    print('Step 4: Finding edge B (release point)')
    while not hallStable(True):
        oneStep(1, delay)
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

    if steps_to_center > 0:
        for _ in range(steps_to_center):
            oneStep(1, delay)
    elif steps_to_center < 0:
        for _ in range(abs(steps_to_center)):
            oneStep(0, delay)

    # Step 6: Set home position
    stepNow = 0
    print('Home set at center of magnet')

    # Step 7: Apply calibration offset from NVM
    offset = load_home_offset_nvm()
    if offset != 0:
        print('Applying home offset: %d steps' % offset)
        if offset > 0:
            multiStep(1, offset, delay)  # CW
        else:
            multiStep(0, abs(offset), delay)  # CCW
        stepNow = 0  # Reset after offset applied
        print('Offset applied, home position adjusted')

    return magnet_width

#%%----------------------------------------------------------------------------
def hourHome():
    # Re-home on the magnet and print the current OLED time text.
    findExactHome(0.000525)
    print(timeArea.text)

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
    ucStatus.text = " "
    led.value = not led.value

#%%----------------------------------------------------------------------------
def minUpdate():
    # Move minute hand and force flipdot blank then hour refresh.
    print("Updating Dial and Flip Dot")
    t = rtc.datetime

    global stepNow
    stepNow %= STEPS

    minSteps = int(round(t.tm_min / 60.0 * STEPS)) % STEPS
    stepsNeeded = (minSteps - stepNow) % STEPS
    print("%d %d %d (CW)" % (minSteps, stepNow, stepsNeeded))

    if stepsNeeded > 0:
        multiStep(1, stepsNeeded, 0.005125)

def hrUpdate(forceHour=False):
    # Move minute hand and force flipdot blank then hour refresh.
    print("hrUpdate()-Updating Flip Dot Hours")
    t = rtc.datetime

    global lastHourShown
    hr12 = hour24ToHour12(t.tm_hour)

    if forceHour or (lastHourShown != hr12):
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
    flipsPower(True)
    try:
        # Sweep minute hand full rotation
        multiStep(1, STEPS, 0.003)
        # Count through hours 1-12
        for h in range(1, 13):
            setFlips(hourIn(h), 1, managePower=False)
            time.sleep(0.3)
        # Blank
        setFlips([0, 0, 0, 0], 1, managePower=False)
        time.sleep(0.2)
    finally:
        extendFlipPowerWindow()
    # Restore time
    findExactHome(0.002125)
    hrUpdate(forceHour=True)
    minUpdate()

def anim_chase():
    # Chase pattern: flipdots ripple, hand follows
    flipsPower(True)
    try:
        findExactHome(0.002125)  # Start at 12
        steps_per_hour = STEPS // 12
        for h in range(1, 13):
            # Move hand to hour position
            multiStep(1, steps_per_hour, 0.003)
            # Light up matching hour
            setFlips(hourIn(h), 1, managePower=False)
            time.sleep(0.15)
        # Blank at end
        setFlips([0, 0, 0, 0], 1, managePower=False)
        time.sleep(0.1)
    finally:
        extendFlipPowerWindow()
    # Restore time
    findExactHome(0.002125)
    hrUpdate(forceHour=True)
    minUpdate()

def anim_chaos():
    # Random chaos: random flipdots, oscillating hand
    flipsPower(True)
    try:
        for _ in range(20):
            setFlips(hourIn(r.randint(0, 12)), 1, managePower=False)
            # Oscillate hand randomly
            multiStep(r.choice([0, 1]), r.randint(20, 100), 0.002)
            time.sleep(0.08)
    finally:
        extendFlipPowerWindow()
    # Restore time
    findExactHome(0.002125)
    hrUpdate(forceHour=True)
    minUpdate()

def anim_sync():
    # Sync dance: hand sweeps to each hour, flipdots light up in sync
    flipsPower(True)
    try:
        setFlips([0, 0, 0, 0], 1, managePower=False)  # Start blank
        findExactHome(0.002125)  # Start at 12
        steps_per_hour = STEPS // 12
        for h in range(1, 13):
            # Move hand to hour position
            multiStep(1, steps_per_hour, 0.004)
            # Light up matching hour
            setFlips(hourIn(h), 1, managePower=False)
            time.sleep(0.25)
    finally:
        extendFlipPowerWindow()
    # Restore time
    findExactHome(0.002125)
    hrUpdate(forceHour=True)
    minUpdate()

#%%----------------------------------------------------------------------------
def setupDot():
    # Initialize DotStar and define global color constants.
    numPixels = 1
    dotstar = adafruit_dotstar.DotStar(
        board.APA102_SCK, board.APA102_MOSI, numPixels,
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

    return dotstar

#%%----------------------------------------------------------------------------
def setDotstar(color, brightness):
    # Set DotStar color and brightness.
    dotstar[0] = (color[0], color[1], color[2], brightness)

#%%----------------------------------------------------------------------------
def getWifiTime():
    # Connect WiFi, fetch UTC time via NTP, apply timezone/DST, set RTC.
    global wifiError
    global secOld, minOld, hrOld

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
            "rtc_time": rtc.datetime,
            "ipAddress": None,
            "timezone": timezone,
            "dst": None,
            "delta_s": None,
            "msg": "Check settings.toml",
        }

    wifiError = False

    result = {
        "wifiError": False,
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

    print("Connecting to %s" % ssid)
    try:
        wifi.radio.connect(ssid, password)
    except Exception as e:
        wifiError = True
        result["wifiError"] = True
        result["msg"] = "WiFi Error"
        print("WiFi Error - Could Not Connect:", e)
        ucStatus.text = "WiFi Error"; print("WiFi Error")
        setDotstar(YELLOW, 0.25)
        return result

    ipAddress = wifi.radio.ipv4_address
    result["ipAddress"] = ipAddress

    ucStatus.text = "WiFi Connected"; print("WiFi Available")
    wifiCircle.fill = 0xFFFFFF
    wifiStatus.text = ssid
    wifiAddress.text = str(ipAddress)
    setDotstar(GREEN, 0.25)
    result["msg"] = "WiFi Available"

    try:
        pool = socketpool.SocketPool(wifi.radio)

        ucStatus.text = "NTP Sync"; print("Fetching NTP from", ntp_server)
        result["msg"] = "NTP Sync"

        # Create NTP client and get UTC time
        ntp = adafruit_ntp.NTP(pool, server=ntp_server, tz_offset=0)
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

    except Exception as e:
        print("NTP Error:", e)
        setDotstar(YELLOW, 0.25)
        ucStatus.text = "NTP Error"; print("NTP Error")
        result["msg"] = "NTP Error"
        result["wifiError"] = True
        result["rtc_time"] = rtc.datetime

    return result


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
               #[1,0,0,0]])   #12
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
def blankToBlack():
    # Quickly force display to black and reset flip cache.
    flipsPower(True)
    try:
        setFlips([0, 0, 0, 0], 1, managePower=False)
        time.sleep(0.05)
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()

#%%----------------------------------------------------------------------------
def playAnimation():
    # Run simple wipe animation frames on flipdots.
    ucStatus.text = "Play Animation"

    wipeLt = [[15,0,0,0],[0,15,0,0],[0,0,15,0],[0,0,0,0]]
    wipeRt = [[0,0,0,15],[0,0,15,0],[0,15,0,0],[15,0,0,0]]
    frames = [wipeLt, wipeRt]

    flipsPower(True)
    try:
        for frame in frames:
            for col in frame:
                setFlips(col, 1, managePower=False)
                time.sleep(0.5)
                led.value = not led.value
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()

#%%----------------------------------------------------------------------------
def roundAnim():
    # Cycle hours repeatedly to exercise the flipdot display.
    time.sleep(0.5)
    print("Round Animation")

    flipsPower(True)
    try:
        for _ in range(2):
            for n in range(0, 13):
                print(n)
                setFlips(hourIn(n), 1, managePower=False)
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
        findExactHome(0.002125)               # Re-home minute hand
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

    @server.route("/anim/chase", POST)
    def anim_chase_route(request: Request):
        log_action("Animation: Chase pattern")
        anim_chase()
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
        findExactHome(0.002125)  # Use current algorithm (swap to V2 after testing)
        time.sleep(2)  # Pause at 12 o'clock for verification
        minUpdate()  # Return to current time
        return Response(request, body='{"ok":true}', content_type="application/json")

    @server.route("/calibrate", POST)
    def calibrate_route(request: Request):
        # Home motor and stay at 12 o'clock for calibration
        global calibration_steps
        calibration_steps = 0  # Reset nudge counter
        log_action("Calibration started")
        findExactHome(0.002125)
        # Don't call minUpdate - stay at 12 o'clock for adjustment
        offset = load_home_offset_nvm()
        return Response(request, body='{"ok":true,"offset":%d,"nudged":0}' % offset, content_type="application/json")

    @server.route("/nudge_cw", POST)
    def nudge_cw_route(request: Request):
        # Nudge hand 1 step clockwise
        global calibration_steps
        oneStep(1, 0.005)
        calibration_steps += 1
        return Response(request, body='{"ok":true,"nudged":%d}' % calibration_steps, content_type="application/json")

    @server.route("/nudge_ccw", POST)
    def nudge_ccw_route(request: Request):
        # Nudge hand 1 step counter-clockwise
        global calibration_steps
        oneStep(0, 0.005)
        calibration_steps -= 1
        return Response(request, body='{"ok":true,"nudged":%d}' % calibration_steps, content_type="application/json")

    @server.route("/set_home", POST)
    def set_home_route(request: Request):
        # Save current position as new home offset
        global calibration_steps
        current_offset = load_home_offset_nvm()
        new_offset = current_offset + calibration_steps
        save_home_offset_nvm(new_offset)
        log_action("Home offset set to %d steps" % new_offset)
        calibration_steps = 0
        return Response(request, body='{"ok":true,"offset":%d}' % new_offset, content_type="application/json")

    return server

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

# while 1:
#     roundTo(13)
#     time.sleep(5)
#     blankDisplay()

# Play Startup Animation
ucStatus.text = "Blanking Display"
blankDisplay()
time.sleep(1.0)

# Determine MagOffset
ucStatus.text = "Magnet Offset"
time.sleep(1.0)
for i in range(2):
    multiStep(1,r.randint(125,STEPS),0.001)
    time.sleep(0.25)
    magOffset = findExactHome(0.002125)

# Show the Current RTC Time
ucStatus.text = "Show Time"
time.sleep(1.0)
hrUpdate(forceHour=True)
minUpdate()
screenUpdate()

# Connect to Wifi
ucStatus.text = "Connecting to Wifi"
wifi_status = getWifiTime()
print(
    wifi_status["msg"],
    "ok=", (not wifi_status["wifiError"]),
    "ip=", wifi_status["ipAddress"],
    "tz=", wifi_status["timezone"],
    "dst=", wifi_status["dst"],
    "delta_s=", wifi_status["delta_s"],
)

# Start Web Server if WiFi connected
if not wifi_status["wifiError"]:
    ucStatus.text = "Starting Web Server"
    t = rtc.datetime
    last_wifi_sync_time = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
    log_action("Clock started")
    log_action("WiFi connected: " + str(wifi_status["ipAddress"]))
    try:
        pool = socketpool.SocketPool(wifi.radio)
        server = setupWebServer(pool)
        clock_web_port = int(os.getenv("CLOCK_WEB_PORT", "80"))
        server.start(str(wifi.radio.ipv4_address), port=clock_web_port)
        print("Web server started at http://{}:{}".format(wifi.radio.ipv4_address, clock_web_port))
        log_action("Web server started")
    except Exception as e:
        print("Web server failed to start:", e)
        server = None

#%%----------------------------------------------------------------------------
# Main
#%%----------------------------------------------------------------------------
print("Starting Main Loop")

while True:
    # Poll web server for incoming requests
    if server:
        try:
            server.poll()
        except Exception as e:
            print("Server poll error:", e)

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
        hourHome()
        hrOld = hrTest

    # Begin Button Testing
    didManualUpdate = False   # Track whether a button caused a time/mech change

    if butA.value == 0:
        print("Button A - Pressed")
        blankDisplay()        # Clear display before re-animating hour

        t = rtc.datetime
        numIn = hour24ToHour12(t.tm_hour)
        roundTo(numIn)        # Animate flipdots to current hour

        magOffset = findExactHome(0.002125)  # Re-home minute hand
        hrUpdate(forceHour=True)              # Force hour refresh
        minUpdate()                           # Sync minute hand

        didManualUpdate = True

    elif butB.value == 0:
        setHrs()              # Increment RTC hour
        hrUpdate(forceHour=True)  # Force hour refresh
        didManualUpdate = True

    elif butC.value == 0:
        setMins()             # Increment RTC minute
        minUpdate()           # Sync minute hand
        didManualUpdate = True

    else:
        serviceFlipPowerWindow()  # Handle delayed flipdot power-off
        time.sleep(0.1)           # Idle delay to limit loop rate

    if didManualUpdate:
        syncOldTrackers()     # Prevent main loop from re-triggering updates


    else:
        serviceFlipPowerWindow()
        time.sleep(0.1)
