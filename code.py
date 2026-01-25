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
from adafruit_display_shapes.line import Line
from adafruit_display_shapes.circle import Circle
import i2cdisplaybus

# WIFI Libraries
import ipaddress
import ssl
import wifi
import socketpool
import adafruit_requests
import json

# Web Server Libraries
from adafruit_httpserver import Server, Request, Response, POST

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
 
# Stepper Motor Setup
motorEnabled  = False   # active-low
motorDisabled = True

# Relay Setup
relayPrechargeS = 0.20   # seconds to let 24V rails charge
relayHoldS      = 0.08   # seconds to keep rails up after last flip

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

# HTML Dashboard Template
INDEX_HTML = """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FlipDotCircleClock</title>
  <style>
    :root {
      --bg: #050608;
      --panel: #14171d;
      --panel2: #1a1f27;
      --border: rgba(255,255,255,0.22);
      --text: #ffffff;
      --shadow: 0 16px 40px rgba(0,0,0,0.75);
      --radius: 16px;
      --focus: 0 0 0 3px rgba(255,255,255,0.25);
      --ok: #2ecc71;
      --warn: #f1c40f;
      --fail: #e74c3c;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background: radial-gradient(1200px 700px at 15% 0%, rgba(255,255,255,0.05), transparent 60%),
        radial-gradient(900px 600px at 85% 20%, rgba(255,255,255,0.03), transparent 55%), var(--bg);
      color: var(--text);
    }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 22px 18px 40px 18px; }
    .topbar { display:flex; align-items:center; justify-content:space-between; gap:12px; margin-bottom:16px; flex-wrap:wrap; }
    .brand { display:flex; align-items:center; gap:12px; }
    .logo { width:42px; height:42px; border-radius:12px; background:linear-gradient(180deg,#20242c,#0e1015); border:1px solid var(--border); box-shadow:var(--shadow); }
    h1 { margin:0; font-size:18px; font-weight:700; color:#ffffff; }
    .subtitle { margin-top:2px; font-size:12px; color:#ffffff; opacity:0.92; }
    .pillrow { display:flex; gap:10px; flex-wrap:wrap; align-items:center; justify-content:flex-end; }
    .pill { display:inline-flex; gap:8px; align-items:center; padding:8px 10px; border-radius:999px; background:rgba(255,255,255,0.06); border:1px solid var(--border); font-size:12px; color:#ffffff; }
    .dot { width:8px; height:8px; border-radius:999px; background:var(--warn); box-shadow:0 0 0 4px rgba(241,196,15,0.25); }
    .dot.ok { background:var(--ok); box-shadow:0 0 0 4px rgba(46,204,113,0.25); }
    .dot.bad { background:var(--fail); box-shadow:0 0 0 4px rgba(231,76,60,0.25); }
    .card { background:linear-gradient(180deg,var(--panel2),var(--panel)); border:1px solid var(--border); border-radius:var(--radius); box-shadow:var(--shadow); padding:14px; }
    .twocol { display:grid; grid-template-columns:1fr 1fr; gap:14px; align-items:start; }
    @media (max-width:900px) { .pillrow{justify-content:flex-start;} .twocol{grid-template-columns:1fr;} }
    .section h2 { margin:0 0 10px 0; font-size:13px; letter-spacing:0.6px; text-transform:uppercase; color:#ffffff; opacity:0.95; }
    .kv { display:grid; grid-template-columns:140px 1fr; gap:8px 10px; align-items:center; }
    @media (max-width:520px) { .kv{grid-template-columns:1fr;} }
    .k { font-size:12px; color:#ffffff; opacity:0.92; }
    .v { font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace; font-size:12px; padding:8px 10px; border-radius:12px; background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.25); color:#ffffff; overflow-wrap:anywhere; }
    .actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:10px; align-items:center; }
    button { border-radius:12px; border:1px solid rgba(255,255,255,0.35); background:rgba(255,255,255,0.10); color:#ffffff; padding:10px 12px; font-size:13px; outline:none; cursor:pointer; transition:transform 0.04s ease,background 0.15s ease; }
    button:hover { background:rgba(255,255,255,0.16); }
    button:active { transform:translateY(1px); }
    button.primary { background:linear-gradient(180deg,rgba(255,255,255,0.22),rgba(255,255,255,0.12)); border-color:rgba(255,255,255,0.45); }
    button.primary:hover { background:linear-gradient(180deg,rgba(255,255,255,0.30),rgba(255,255,255,0.16)); }
    button:focus { box-shadow:var(--focus); }
    .logwrap { margin-top:14px; }
    .logtitle { margin-top:6px; font-size:12px; color:#ffffff; opacity:0.92; }
    .log { margin-top:8px; height:200px; overflow:auto; white-space:pre-wrap; border-radius:var(--radius); border:1px solid rgba(255,255,255,0.25); background:rgba(0,0,0,0.45); padding:12px; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace; font-size:13px; line-height:1.35; color:#ffffff; }
    .footer { margin-top:10px; font-size:12px; color:#ffffff; opacity:0.92; }
    .linkpill { display:inline-block; padding:6px 10px; border-radius:999px; border:1px solid rgba(255,255,255,0.30); background:rgba(255,255,255,0.06); color:#ffffff; text-decoration:none; font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace; font-size:12px; }
    .linkpill:hover { background:rgba(255,255,255,0.12); }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div>
          <h1>FlipDotCircleClock</h1>
          <div class="subtitle">Feather S2 Flip Dot Display</div>
        </div>
      </div>
      <div class="pillrow">
        <div class="pill"><span class="dot" id="dotWifi"></span>WiFi</div>
        <div class="pill">Time: <span id="currentTime" style="margin-left:6px;">...</span></div>
      </div>
    </div>
    <div class="card">
      <div class="twocol">
        <div class="section">
          <h2>Clock Status</h2>
          <div class="kv">
            <div class="k">Time</div><div class="v" id="time">...</div>
            <div class="k">Hour (12h)</div><div class="v" id="hour12">...</div>
            <div class="k">Timezone</div><div class="v" id="timezone">...</div>
            <div class="k">IP Address</div><div class="v" id="ipAddress">...</div>
            <div class="k">SSID</div><div class="v" id="ssid">...</div>
            <div class="k">Uptime</div><div class="v" id="uptime">...</div>
            <div class="k">Free Memory</div><div class="v" id="freeMemory">...</div>
            <div class="k">Last WiFi Sync</div><div class="v" id="lastSync">...</div>
          </div>
          <div class="actions">
            <button class="primary" id="wipeBtn">Wipe Display</button>
            <button id="refreshBtn">Refresh Hour</button>
            <button id="syncBtn">Sync WiFi</button>
          </div>
        </div>
        <div class="section">
          <h2>Motor &amp; Display</h2>
          <div class="kv">
            <div class="k">Motor Position</div><div class="v" id="motorPos">...</div>
            <div class="k">Steps Total</div><div class="v" id="stepsTotal">...</div>
            <div class="k">Last Hour Shown</div><div class="v" id="lastHour">...</div>
            <div class="k">Flipdot Power</div><div class="v" id="flipPower">...</div>
          </div>
          <div class="actions">
            <button id="hourPlusBtn">+1 Hour</button>
            <button id="minPlusBtn">+1 Minute</button>
            <button id="homeBtn">Home Motor</button>
          </div>
        </div>
      </div>
      <div class="logwrap">
        <div class="logtitle">Action Log</div>
        <div class="log" id="log">Loading...</div>
        <div class="footer">
          API: <a class="linkpill" href="/status.json">/status.json</a>
          <a class="linkpill" style="margin-left:8px;" href="/log.json">/log.json</a>
        </div>
      </div>
    </div>
  </div>
<script>
(function(){
  function setText(id,val){var el=document.getElementById(id);if(!el)return;if(val===null||val===undefined||val==="")val="--";el.textContent=String(val);}
  function setDot(id,ok){var el=document.getElementById(id);if(!el)return;el.className="dot "+(ok?"ok":"bad");}
  function refreshStatus(){
    fetch('/status.json',{cache:'no-store'}).then(function(r){return r.json();}).then(function(d){
      setText('currentTime',d.time);
      setText('time',d.time);
      setText('hour12',d.hour_12);
      setText('timezone',d.timezone);
      setText('ipAddress',d.ip_address);
      setText('ssid',d.ssid);
      setText('uptime',d.uptime_s+'s');
      setText('freeMemory',d.free_memory+' bytes');
      setText('lastSync',d.last_wifi_sync);
      setText('motorPos',d.motor_position+'/'+d.motor_steps_total);
      setText('stepsTotal',d.motor_steps_total);
      setText('lastHour',d.last_hour_shown);
      setText('flipPower',d.flipdot_power?'ON':'OFF');
      setDot('dotWifi',d.wifi_connected);
    }).catch(function(){});
  }
  function fetchLog(){
    fetch('/log.json',{cache:'no-store'}).then(function(r){return r.json();}).then(function(d){
      var el=document.getElementById('log');
      if(!el)return;
      if(!d.entries||!d.entries.length){el.textContent="No entries.";return;}
      el.textContent=d.entries.map(function(e){return e.ts+"  "+e.msg;}).join("\\n");
    }).catch(function(){});
  }
  function postAction(endpoint){
    fetch(endpoint,{method:'POST'}).then(function(){setTimeout(function(){refreshStatus();fetchLog();},500);}).catch(function(){});
  }
  document.getElementById('wipeBtn').addEventListener('click',function(){postAction('/wipe');});
  document.getElementById('refreshBtn').addEventListener('click',function(){postAction('/refresh');});
  document.getElementById('syncBtn').addEventListener('click',function(){postAction('/sync_wifi');});
  document.getElementById('hourPlusBtn').addEventListener('click',function(){postAction('/set_hour');});
  document.getElementById('minPlusBtn').addEventListener('click',function(){postAction('/set_min');});
  document.getElementById('homeBtn').addEventListener('click',function(){postAction('/home');});
  refreshStatus();
  fetchLog();
  setInterval(function(){refreshStatus();fetchLog();},5000);
})();
</script>
</body>
</html>"""


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

    # Step 5: Calculate center and move there
    magnet_width = abs(edge_a - edge_b)
    center = (edge_a + edge_b) // 2
    steps_to_center = center - stepNow

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
            time.sleep(0.05)

            setFlips(hourIn(hr12), 1, managePower=False)  # force hour
            time.sleep(0.05)

            setFlips(hourIn(hr12), 1, managePower=False)  # small retry
        finally:
            extendFlipPowerWindow()

        lastHourShown = hr12

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
class timeOut:
    # Parse time JSON response into fields or mark all fields as 99.
    def __init__(self, reqMsg):
        # Parse time JSON or mark error fields as 99s.
        reqMsg.find("error")
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
    # Connect WiFi, fetch time (tz-aware), set RTC, and optionally resync outputs.
    global wifiError
    global secOld, minOld, hrOld

    # Get credentials from settings.toml via os.getenv()
    ssid = os.getenv("CIRCUITPY_WIFI_SSID")
    password = os.getenv("CIRCUITPY_WIFI_PASSWORD")
    timezone = os.getenv("TIMEZONE", "Etc/UTC")
    aio_username = os.getenv("AIO_USERNAME")
    aio_key = os.getenv("AIO_KEY")

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
        "dst": None,
        "delta_s": None,
        "msg": "Init",
    }

    setDotstar(PURPLE, 0.25)
    wifiCircle.fill = None
    ucStatus.text = "Connecting to WiFi"; print("Connecting to WiFi")
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

    ucStatus.text = "WiFi Available"; print("WiFi Available")
    wifiCircle.fill = 0xFFFFFF
    wifiStatus.text = ssid
    wifiAddress.text = str(ipAddress)
    setDotstar(GREEN, 0.25)
    result["msg"] = "WiFi Available"

    try:
        pool = socketpool.SocketPool(wifi.radio)
        requests = adafruit_requests.Session(pool, ssl.create_default_context())

        # Adafruit IO time integration supports tz; server applies DST for that tz.
        TIME_URL = (
            "https://io.adafruit.com/api/v2/%s/integrations/time/struct"
            "?x-aio-key=%s&tz=%s" % (aio_username, aio_key, timezone)
        )
        print("Fetching time from", TIME_URL)

        ucStatus.text = "Sending Request"; print("Sending Request")
        result["msg"] = "Sending Request"

        req = requests.get(TIME_URL)
        t = timeOut(req.text)
        req.close()

        result["dst"] = t.isdst

        rtc_before = rtc.datetime
        wifi_struct = time.struct_time(
            (t.year, t.mon, t.mday, t.hour, t.min, t.sec, t.wday, t.yday, t.isdst)
        )

        WIFI_RESYNC_THRESHOLD_S = 120
        try:
            delta_s = abs(time.mktime(wifi_struct) - time.mktime(rtc_before))
        except Exception as e:
            print("Delta calc failed:", e)
            delta_s = WIFI_RESYNC_THRESHOLD_S

        result["delta_s"] = delta_s

        rtc.datetime = wifi_struct
        result["rtc_time"] = rtc.datetime

        if delta_s >= WIFI_RESYNC_THRESHOLD_S:
            print("WiFi drift %.1fs, resyncing hands/display" % delta_s)
            hrUpdate(forceHour=True)
            minUpdate()
            syncOldTrackers()

        ucStatus.text = "RTC update via WiFi"; print("RTC update via WiFi")
        result["msg"] = "RTC update via WiFi"

    except Exception as e:
        print("Request Error - Time Not Updated:", e)
        setDotstar(YELLOW, 0.25)
        ucStatus.text = "Request Error"; print("Request Error")
        result["msg"] = "Request Error"
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
        return Response(request, body=INDEX_HTML, content_type="text/html")

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
        tz = os.getenv("TIMEZONE", "Unknown")

        status = {
            "time": time_str,
            "hour_12": hr12,
            "minute": t.tm_min if t else 0,
            "wifi_connected": wifi.radio.connected,
            "ip_address": str(wifi.radio.ipv4_address) if wifi.radio.connected else "None",
            "ssid": ssid,
            "timezone": tz,
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
        blankDisplay()
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

    @server.route("/home", POST)
    def home_route(request: Request):
        log_action("Home motor via web - pausing at 12:00")
        findExactHome(0.002125)
        # Don't call minUpdate() - leave hand at 12:00 for visual verification
        return Response(request, body='{"ok":true,"msg":"Homed to 12:00 - hand will stay here until next minute update"}', content_type="application/json")

    @server.route("/sync_wifi", POST)
    def sync_wifi_route(request: Request):
        global last_wifi_sync_time
        log_action("WiFi sync triggered via web")
        result = getWifiTime()
        if not result["wifiError"]:
            t = rtc.datetime
            last_wifi_sync_time = "{:02}:{:02}:{:02}".format(t.tm_hour, t.tm_min, t.tm_sec)
        return Response(request, body=json.dumps({"ok": not result["wifiError"]}), content_type="application/json")

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
        server.start(str(wifi.radio.ipv4_address))
        print("Web server started at http://{}".format(wifi.radio.ipv4_address))
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
