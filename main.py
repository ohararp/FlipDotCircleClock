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
import sys

#RTC Libraries
import adafruit_ds3231
#import adafruit_pcf8523

# Display Libraries
from adafruit_display_text import label
import adafruit_displayio_sh1107
from adafruit_display_shapes.rect import Rect
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_display_shapes.line import Line
from adafruit_display_shapes.circle import Circle

# WIFI Libraries
import ipaddress
import ssl
import wifi
import socketpool
import adafruit_requests
import secrets
import json

# LED Libraries
import adafruit_dotstar
import adafruit_fancyled.adafruit_fancyled as fancy


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

# Relay Setup
relayPrechargeS = 0.20   # seconds to let 24V rails charge
relayHoldS      = 0.08   # seconds to keep rails up after last flip

flipPwrIsOn = False
flipPwrOffAtS = 0.0

#%%----------------------------------------------------------------------------
def getBit(value, bitIdx):
    return value & (1 << bitIdx)
#%%----------------------------------------------------------------------------
def setBit(value, bitIdx):
    return value | (1 << bitIdx)
#%%----------------------------------------------------------------------------
def clrBit(value, bitIdx):
    return value & ~(1 << bitIdx)
#%%----------------------------------------------------------------------------
def writeBit(value, bitIdx, bitValue):
    if bitValue == 1:  # setBit
        output = value | (1 << bitIdx)
    else:  # clear Bit
        output = value & ~(1 << bitIdx)
    return output
#------------------------------------------------------------------------------
def leftRotate(n, d):
    # rotate n by d bits
    intBits=12
    result = (n << d)|(n >> (intBits - d))
    return result
#------------------------------------------------------------------------------
def rightRotate(n, d):
    # rotate n by d bits
    intBits=12
    result = (n >> d)|(n << (intBits - d)) & 0xFFFFFFFF
    return result

#%%----------------------------------------------------------------------------
def sayHello():
    # Say hello
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
    butA = digitalio.DigitalInOut(board.IO1)
    butA.direction = digitalio.Direction.INPUT
    butA.pull = digitalio.Pull.UP

    butB = digitalio.DigitalInOut(board.IO38)
    butB.direction = digitalio.Direction.INPUT
    butB.pull = digitalio.Pull.UP

    butC = digitalio.DigitalInOut(board.IO33)
    butC.direction = digitalio.Direction.INPUT
    butC.pull = digitalio.Pull.UP

    return [butA,butB,butC]
#%%----------------------------------------------------------------------------
def setupI2C():
    i2c = board.I2C()
    return i2c
#%%----------------------------------------------------------------------------
def setupRTC(i2c):
    rtc = adafruit_ds3231.DS3231(i2c) #adafruit_pcf8523.PCF8523(i2c)#
    return rtc
#%%----------------------------------------------------------------------------
def setHrs():
    ucStatus.text = "+1 Hrs"
    t = rtc.datetime

    # Increment Hour Value
    newHrs = t.tm_hour + 1

    # Handle Hour Overflow
    if newHrs > 23:
        newHrs = 0

    rtc.datetime = time.struct_time((t.tm_year,t.tm_mon,t.tm_mday,newHrs,t.tm_min,0,0,0,-1))
    screenUpdate()
#%%----------------------------------------------------------------------------
def setMins():
    ucStatus.text = "+1 Mins"
    t = rtc.datetime

    # Increment Minute Value
    newMins = t.tm_min + 1

    # Handle Minute Overflow
    if newMins > 59:
        newMins = 0

    rtc.datetime = time.struct_time((t.tm_year,t.tm_mon,t.tm_mday,t.tm_hour,newMins,0,0,0,-1))
    screenUpdate()
#%%----------------------------------------------------------------------------
def setupMotor():
    ucStatus.text = "Setup Motor"
    global STEPS
    STEPS = 800 #(2 usteps * 400 = 800 steps per revolution)

    #Enable Pin for the Motor Driver
    en = digitalio.DigitalInOut(board.IO6)
    en.direction = digitalio.Direction.OUTPUT

    step = digitalio.DigitalInOut(board.IO12)
    step.direction = digitalio.Direction.OUTPUT

    direct= digitalio.DigitalInOut(board.IO5)
    direct.direction = digitalio.Direction.OUTPUT

    home = digitalio.DigitalInOut(board.IO14)
    home.direction = digitalio.Direction.INPUT
    home.pull = digitalio.Pull.UP

    stepSelect = digitalio.DigitalInOut(board.IO17)
    stepSelect.direction = digitalio.Direction.OUTPUT
    stepSelect.value = True  # set stepping mode once
    
    """
    MS1    MS2  Steps  Interp
    GND    GND  8      256
    VIO    GND  2      256 <-----CURRENT SETTING WITH MS1 HIGH
    GND    VIO  4      256
    VIO    VIO  16      256

    """
    return [en,step,direct,home,stepSelect]
#%%----------------------------------------------------------------------------
def setupFlipdotPower():
    # IO-0 causes FeatherS2 to not use IO11 
    pwr = digitalio.DigitalInOut(board.IO11)
    pwr.direction = digitalio.Direction.OUTPUT
    pwr.value = False  # flipdot power OFF by default
    return pwr
#%%----------------------------------------------------------------------------    
def flipsPower(on: bool):
    global flipPwrIsOn

    if on:
        if not flipPwrIsOn:
            pwr.value = True
            flipPwrIsOn = True
            time.sleep(relayPrechargeS)  # only when turning on
    else:
        if flipPwrIsOn:
            pwr.value = False
            flipPwrIsOn = False
#%%---------------------------------------------------------------------------- 
def extendFlipPowerWindow():
    global flipPwrOffAtS
    nowS = time.monotonic()
    offAtS = nowS + relayHoldS
    if offAtS > flipPwrOffAtS:
        flipPwrOffAtS = offAtS
#%%---------------------------------------------------------------------------- 
def serviceFlipPowerWindow():
    global flipPwrOffAtS
    if flipPwrIsOn and (time.monotonic() >= flipPwrOffAtS):
        flipsPower(False)
        invalidateFlipCache()  # important: next time force a real refresh
#%%----------------------------------------------------------------------------
def invalidateFlipCache():
    global oldData
    oldData = [255, 255, 255, 255]
        
#%%----------------------------------------------------------------------------
def setFlips(dataIn, flagXOR, manage_power=True):
    if manage_power:
        flipsPower(True)
        extendFlipPowerWindow()

    regData = setFlipsCore(dataIn, flagXOR)

    if manage_power:
        extendFlipPowerWindow()  # extend again after the shift completes

    return regData
#%%----------------------------------------------------------------------------
def setFlipsCore(dataIn, flagXOR):
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
    # Init Blink LED
    led = digitalio.DigitalInOut(board.LED)
    led.direction = digitalio.Direction.OUTPUT
    return led
#%%----------------------------------------------------------------------------
def hallTest():
    if home.value == False: # False = Magnet
        led.value = True
        return False
    else:
        led.value = 0
        return True # True = No Magnet
#%%----------------------------------------------------------------------------
def setDir(data):
    if data == 0:
        direct.value = False
    else:
        direct.value = True
#%%----------------------------------------------------------------------------
def oneStep(data,delay):
    setDir(data)
    step.value = True
    time.sleep(delay)
    step.value = False
    time.sleep(delay)
    global stepNow
    if data == 0:      # reverse
        stepNow -= 1
    else:              # forward
        stepNow += 1
    stepNow %= STEPS
    hallTest()
#%%----------------------------------------------------------------------------
def multiStep(data, steps, delay):
    en.value = False          # enable driver (your comment says False=Enabled)
    for _ in range(steps):
        oneStep(data, delay)
    en.value = True           # disable driver
   
#%%----------------------------------------------------------------------------
def moveHome(delay):
    en.value = False #False = Enabled
    while 1:
        oneStep(1,delay)

        if home.value == False: # False = Magnet
            global stepNow
            stepNow = 0
            break
    en.value = True #True = disabled
#%%----------------------------------------------------------------------------
def findExactHome(delay):
    print('Finding Exact Home')
    en.value = False #False = Enabled

    ctr0 = 0
    ctr1 = 0

    # Find the Location of the Front Part of Magnet
    print('Finding Beg of Magnet')
    while 1:
        oneStep(1, delay)
        ctr0 += 1
        if hallStable(False): # False = Magnet
            break

    print('Ctr0 = %d' % ctr0)
    # Find the Back Part of the Magnet
    print('Finding End of Magnet')
    
    while 1:
        oneStep(1, delay)
        ctr1 += 1
        if hallStable(True): # True = No Magnet
            break

    # Move back half the magnet width to land at the center
    half_width = ctr1 // 2
    for _ in range(half_width):
        oneStep(0, delay)

    print('Ctr1 = %d' % ctr1)

    global stepNow
    stepNow = 0
    en.value = True #True = disabled
    return ctr1
#%%----------------------------------------------------------------------------
def hourHome():
    findExactHome(0.000525)
    print(timeArea.text)
#%%----------------------------------------------------------------------------
def setupScreen(i2c):
    blk = 0x000000
    wht = 0xFFFFFF
    displayio.release_displays()
    display_bus = displayio.I2CDisplay(i2c, device_address=0x3C)
    # SH1107 is vertically oriented 64x128
    screenWidth  = 128
    screenHeight = 64
    screenBorder = 2
    screenRadius = 5

    display = adafruit_displayio_sh1107.SH1107(display_bus, width=screenWidth, height=screenHeight)

    # Make the display context
    screen = displayio.Group()
    display.show(screen)

    #Border
    rect = RoundRect(int(screenBorder/2),int(screenBorder/2),screenWidth-screenBorder,screenHeight-screenBorder,screenRadius, fill=None, outline=wht, stroke=1)
    screen.append(rect)

    # Print the Time
    timeArea = label.Label(terminalio.FONT, text="HH:MM", color=wht)
    timeArea.anchor_point = (0.5,0.5)
    timeArea.anchored_position = (64,9)
    screen.append(timeArea)

    # Print the Time
    ucStatus = label.Label(terminalio.FONT, text=" Startup", color=wht)
    ucStatus.anchor_point = (0.5,0.5)
    ucStatus.anchored_position = (64,27)
    screen.append(ucStatus)

    # Wifi Circle
    circleRadius = 4
    wifiCircle = Circle(120,8,circleRadius,fill=None, outline=wht, stroke=1)
    screen.append(wifiCircle)

    # Wifi Status
    wifiStatus = label.Label(terminalio.FONT, text="No WiFi", color=wht)
    wifiStatus.anchor_point = (0.5, 0.5)
    wifiStatus.anchored_position = (64, 44)
    screen.append(wifiStatus)

    # IP Address
    wifiAddress = label.Label(terminalio.FONT, text="000.000.00.00", color=wht)
    wifiAddress.anchor_point = (0.5, 0.5)
    wifiAddress.anchored_position = (64, 54)
    screen.append(wifiAddress)

    return [screen, timeArea, ucStatus, wifiCircle, wifiStatus, wifiAddress]
#%%----------------------------------------------------------------------------
def screenUpdate():
    t = rtc.datetime

    # Update Display
    timeArea.text = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
    print(timeArea.text)

    ucStatus.text = " "
    led.value = not led.value
#%%----------------------------------------------------------------------------
def mechUpdate(forceHour=False):
    print("Updating Dial and Flip Dot")
    t = rtc.datetime

    global stepNow
    stepNow %= STEPS

    minSteps = int(round(t.tm_min / 60.0 * STEPS)) % STEPS
    stepsNeeded = (minSteps - stepNow) % STEPS
    print("%d %d %d (CW)" % (minSteps, stepNow, stepsNeeded))

    if stepsNeeded > 0:
        multiStep(1, stepsNeeded, 0.005125)

    global lastHourShown
    hr12 = t.tm_hour if t.tm_hour <= 12 else t.tm_hour - 12
    hourChanged = (lastHourShown != hr12)

    if forceHour or hourChanged:
        blankToBlack()

        t = rtc.datetime
        hr12 = t.tm_hour if t.tm_hour <= 12 else t.tm_hour - 12

        roundTo(hr12)
        lastHourShown = hr12

#%%----------------------------------------------------------------------------
def setupDot():
    # Create a DotStar instance
    numPixels = 1
    dotstar = adafruit_dotstar.DotStar(board.APA102_SCK, board.APA102_MOSI, numPixels, brightness = 1.0, auto_write=True)

    global RED
    RED = (255, 0, 0)
    global YELLOW
    YELLOW = (200, 255, 0)
    global ORANGE
    ORANGE = (255, 40, 0)
    global GREEN
    GREEN = (0, 255, 0)
    global TEAL
    TEAL = (0, 255, 120)
    global CYAN
    CYAN = (0, 255, 255)
    global BLUE
    BLUE = (0, 0, 255)
    global PURPLE
    PURPLE = (180, 0, 255)
    global MAGENTA
    MAGENTA = (255, 0, 20)
    global WHITE
    WHITE = (255, 255, 255)

    return dotstar
#%%----------------------------------------------------------------------------
def setDotstar(color,brightness):
    dotstar[0] = (color[0],color[1],color[2], brightness)
#%%----------------------------------------------------------------------------
class timeOut:
    # t=timeOut(req)
    def __init__(self, reqMsg):
        # Print the Request Packet
        reqMsg.find("error")
        # If Error is Found Load Class with Error Data
        if (reqMsg.find("error") != -1):
            self.year = 99
            self.mon  = 99
            self.mday = 99
            self.hour = 99
            self.min  = 99
            self.sec  = 99
            self.wday = 99
            self.yday = 99
            self.isdst = 99
        # If no error -> Load Class with Data
        else:
            req = json.loads(reqMsg)
            self.year = req['year']
            self.mon  = req['mon']
            self.mday = req['mday']
            self.hour = req['hour']
            self.min  = req['min']
            self.sec  = req['sec']
            self.wday = req['wday']
            self.yday = req['yday']
            self.isdst = req['isdst']
#%%----------------------------------------------------------------------------
def getWifiTime():
    # Create a global variable to store wifiError
    global wifiError

    # Add a check if Variable does not exist (ie at startup)
    try: wifiError
    except NameError: wifiError = False

    # Signal Trying to connect to internet
    setDotstar(PURPLE,0.25)
    wifiCircle.fill = None
    ucStatus.text = "Connecting to WiFi"
    wifiStatus.text = "---"
    wifiAddress.text = "---"

    # Get wifi details and more from a secrets.py file
    try:
        from secrets import secrets
    except ImportError:
        print("WiFi secrets are kept in secrets.py, please add them there!")
        ucStatus.text = "Check Secrets.py"

    # Get our username, key and desired timezone
    aio_username = secrets["aio_username"]
    aio_key = secrets["aio_key"]
    location = secrets.get("timezone", None)
    print("My MAC addr:", [hex(i) for i in wifi.radio.mac_address])

    print("Available WiFi networks:")
    for network in wifi.radio.start_scanning_networks():
        print("\t%s\t\tRSSI: %d\tChannel: %d" % (str(network.ssid, "utf-8"),
                network.rssi, network.channel))
    wifi.radio.stop_scanning_networks()

    print("Connecting to %s" % secrets["ssid"])

    try:
        wifi.radio.connect(secrets["ssid"], secrets["password"])
    except:
        # Handle Errors When Wifi Can't Connect
        wifiError = True
        t=timeOut("error")
        ipAddress = ipaddress.ip_address("999.999.99.99")

        # Update OLED Screen with Wifi Status
        wifiCircle.fill = None
        wifiAddress.text = str(ipAddress)
        wifiStatus.text = "WiFi Error"
        setDotstar(YELLOW,0.25)

    if wifiError == False:
        print("Connected  to %s!"%secrets["ssid"])
        print("My IP address is", wifi.radio.ipv4_address)
        ipAddress = wifi.radio.ipv4_address

        pool = socketpool.SocketPool(wifi.radio)
        print(pool)

        # Update OLED Screen with Wifi Status
        ucStatus.text = "WiFi Available"
        wifiCircle.fill = 0xFFFFFF
        wifiStatus.text = secrets["ssid"]
        wifiAddress.text = str(ipAddress)
        setDotstar(GREEN,0.25)

        # Request New Time from Internet
        try:
            #TIME_URL = "https://io.adafruit.com/api/v2/%s/integrations/time/strftime?x-aio-key=%s" % (aio_username, aio_key)
            #TIME_URL += "&fmt=%25Y-%25m-%25d+%25H%3A%25M%3A%25S.%25L+%25j+%25u+%25z+%25Z"
            # https://io.adafruit.com/ohararpS/services/time
            # Get Time in a json structured dictionary = {'isdst': 0, 'yday': 19, 'year': 2021, 'hour': 13, 'mday': 19, 'min': 29, 'sec': 34, 'wday': 2, 'mon': 1}
            TIME_URL = "https://io.adafruit.com/api/v2/%s/integrations/time/struct?x-aio-key=%s" % (aio_username, aio_key)
            print("Fetching text from", TIME_URL)

            ucStatus.text = "Sending Request"
            requests = adafruit_requests.Session(pool, ssl.create_default_context())
            print("Requests = %s" % requests)
            req=requests.get(TIME_URL)
            #print("req = %s" % req.text) #req.text = {"year":2021,"mon":4,"mday":13,"hour":18,"min":50,"sec":43,"wday":2,"yday":103,"isdst":1}
            t=timeOut(req.text)
            req.close()
            print("Wifi Time = %d%02d%02d - %02d:%02d:%02d" % (t.year, t.mon, t.mday, t.hour, t.min, t.sec))

            #Set the RTC to WIFI time
            rtc.datetime = time.struct_time((t.year, t.mon, t.mday, t.hour, t.min, t.sec, t.wday, t.yday, t.isdst))
            print("Set Time  = %d%02d%02d - %02d:%02d:%02d" % (t.year, t.mon, t.mday, t.hour, t.min, t.sec))

            # Update OLED Screen with Request Status
            ucStatus.text = "RTC update via WiFi"
        except:
            print("Request Error - Time Not Updated")
            setDotstar(YELLOW,0.25)
            t=timeOut("error")

            # Update OLED Screen with Request Status
            ucStatus.text = "Request Error"
            wifiCircle.fill = None
            wifiStatus.text = secrets["ssid"]
            wifiAddress.text = str(ipAddress)
            setDotstar(YELLOW,0.25)

        # Print The RTC Time and Date
        t = rtc.datetime
        print("RTC Time  = %d%02d%02d - %02d:%02d:%02d" % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec))
        ucStatus.text = " "
    return [wifiError,t,ipAddress]

#------------------------------------------------------------------------------
def hourIn(hour):
    # Add an +1 shift to the hour
    # Account for 24 hour format
    if hour > 12:
        hour = hour-12
    # Decoder List from 0-12 of dots in columnar format
    id0=2
    id1=6
    id2=14
    id3=30

    idd0=1
    idd1=3
    idd2=7
    idd3=15

    fullIdx=([[0,0,0,0], #0
             [id0,0,0,0],#1
             [id1,0,0,0],#2
             [id2,0,0,0],#3
             [id3,idd0,0,0],#4
             [id3,idd1,0,0],#5
             [id3,idd2,0,0],#6
             [id3,idd3,0,0],#7
             [id3,idd3,idd0,0],#8
             [id3,idd3,idd1,0],#9
             [id3,idd3,idd2,0],#10
             [id3,idd3,idd3,0],#11
             [1,0,0,0]]) #12
    data = fullIdx[hour]
    return data
#%%----------------------------------------------------------------------------
def shiftData(regData):

    oePin.value = OE_ENABLE # Enable Shift Registers

    for i in range(0, 4):
        # print(bin(data2send))
        latchPin.value = False  # Pull latch LOW to stop sending data
        simpleio.shift_out(dataPin, clockPin, (regData[i] >> 8), msb_first=True)  # Send the data
        simpleio.shift_out(dataPin, clockPin, regData[i], msb_first=True)  # Send the data

    latchPin.value = True  # Pull latch HIGH to send data
    latchPin.value = False  # Pull latch LOW to stop sending data
    time.sleep(0.005)

    for i in range(0, 4):
        latchPin.value = False  # Pull latch LOW to stop sending data
        simpleio.shift_out(dataPin, clockPin, 0, msb_first=True)  # Send the data
        simpleio.shift_out(dataPin, clockPin, 0, msb_first=True)  # Send the data

    latchPin.value = True  # Pull latch HIGH to send data
    latchPin.value = False  # Pull latch LOW to stop sending data
    oePin.value = OE_DISABLE  # Disable Shift Registers

#%%----------------------------------------------------------------------------
def blankDisplay():
    print("Blanking Display")

    flipsPower(True)
    try:
        setFlips([0, 0, 0, 0], 1, manage_power=False)
        time.sleep(2.5)

        setFlips([15, 15, 15, 15], 1, manage_power=False)
        time.sleep(2.5)

        setFlips([0, 0, 0, 0], 1, manage_power=False)
        time.sleep(2.5)
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()
#%%----------------------------------------------------------------------------        
def blankToBlack():
    flipsPower(True)
    try:
        setFlips([0, 0, 0, 0], 1, manage_power=False)
        time.sleep(0.05)

    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()
#%%----------------------------------------------------------------------------
def playAnimation():
    ucStatus.text = "Play Animation"
    # Store Some Visual Patterns for display
    #xoAnim = [[0,0,0,0],[9,6,6,9],[15,9,9,15],[0,0,0,0]]
    wipeLt = [[15,0,0,0],[0,15,0,0],[0,0,15,0],[0,0,0,0]]
    wipeRt = [[0,0,0,15],[0,0,15,0],[0,15,0,0],[15,0,0,0]]
    #wipeUp = [[1,1,1,1],[2,2,2,2],[4,4,4,4],[8,8,8,8]]
    #wipeDn = [[8,8,8,8],[4,4,4,4],[2,2,2,2],[1,1,1,1]]
    frames = [wipeLt,wipeRt]

    flipsPower(True)
    try:
        for frame in frames:
            for col in frame:
                setFlips(col, 1, manage_power=False)
                time.sleep(0.5)
                led.value = not led.value
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()
#%%----------------------------------------------------------------------------
def roundAnim():
    time.sleep(0.5)
    print("Round Animation")

    flipsPower(True)
    try:
        for _ in range(2):
            for n in range(0, 13):
                print(n)
                setFlips(hourIn(n), 1, manage_power=False)
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()
#%%----------------------------------------------------------------------------
def roundTo(numIn):
    time.sleep(0.5)

    if numIn > 12:
        numIn -= 12

    print("RoundTo Animation:", end=" ")

    flipsPower(True)
    try:
        for n in range(0, 12):
            print(n, end=" ")
            setFlips(hourIn(n), 1, manage_power=False)
            time.sleep(0.5)

        print("|", numIn)

        setFlips(hourIn(numIn), 1, manage_power=False)

        global lastHourShown
        lastHourShown = numIn
    finally:
        time.sleep(relayHoldS)
        flipsPower(False)
        invalidateFlipCache()

#%%----------------------------------------------------------------------------    
def hallStable(expected, samples=5, delay=0.0005):
    """
    Return True only if home.value == expected for N consecutive samples
    """
    for _ in range(samples):
        if home.value != expected:
            return False
        time.sleep(delay)
    return True
    
#%%----------------------------------------------------------------------------
# Setup Functions
#%%----------------------------------------------------------------------------
# Startup Stuff
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

# Setup the Display
[screen, timeArea, ucStatus, wifiCircle, wifiStatus, wifiAddress] = setupScreen(i2c)
ucStatus.text = "Start Up"

# Setup the Relay for the Dots
pwr = setupFlipdotPower()

# Setup the Motor
[en,step,direct,home,stepSelect]= setupMotor()

# Play Startup Animation
ucStatus.text = "Blanking Display"
blankDisplay()
time.sleep(1.0)
roundTo(12)

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
mechUpdate(forceHour=True)
screenUpdate()

# Connect to Wifi
ucStatus.text = "Connecting to Wifi"
getWifiTime()
mechUpdate(forceHour=True)
screenUpdate()

secOld = 255
minOld = 255
hrOld  = 255


#%%----------------------------------------------------------------------------
# Main
#%%----------------------------------------------------------------------------
print("Starting Main Loop")
while True:
    t = rtc.datetime

    # Perform Screen Update Every Second
    secTest = t.tm_sec
    if secOld != secTest:
        screenUpdate()
        secOld = secTest

    # Perform Mech Update Every Minute
    minTest = t.tm_min
    if minOld != minTest:
        mechUpdate(forceHour=False)
        minOld = minTest

    # Perform Mech Update Every Hour
    hrTest = t.tm_hour
    if hrOld != hrTest:
        mechUpdate(forceHour=True)
        hourHome()
        hrOld = hrTest

    # Update the Time By Pressing Button A
    if butA.value == 0:
        print("Button A - Pressed")
        blankDisplay()

        # Re-read time after blanking, then animate to the correct hour
        t = rtc.datetime
        roundTo(t.tm_hour)

        magOffset = findExactHome(0.002125)
        mechUpdate(forceHour=True)

        # Re-sync old trackers to current time so loop doesn't fight you
        t = rtc.datetime
        secOld = t.tm_sec
        minOld = t.tm_min
        hrOld  = t.tm_hour

    elif butB.value == 0:
        setHrs()
        mechUpdate(forceHour=True)

        t = rtc.datetime
        secOld = t.tm_sec
        minOld = t.tm_min
        hrOld  = t.tm_hour

    elif butC.value == 0:
        setMins()
        mechUpdate(forceHour=True)

        t = rtc.datetime
        secOld = t.tm_sec
        minOld = t.tm_min
        hrOld  = t.tm_hour

    else:
        serviceFlipPowerWindow()
        time.sleep(0.1)
