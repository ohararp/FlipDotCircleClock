# FlipDotCircleClock

A CircuitPython-based flip dot clock with a mechanical minute hand, running on UnexpectedMaker Feather S2 or S3 microcontrollers. Features WiFi time synchronization, OLED status display, and a web interface for remote monitoring and control.

## Features

- **Flip Dot Hour Display**: 4-column flip dot display shows the current hour (1-12)
- **Mechanical Minute Hand**: Stepper motor-driven minute hand with precision hall sensor homing
- **NTP Time Sync**: Automatic time synchronization via NTP with timezone and DST support
- **OLED Status Display**: 128x64 SH1107 display showing time, WiFi status, and IP address
- **Web Interface**: Browser-based dashboard for remote monitoring and control
- **Physical Buttons**: 3 buttons for manual time adjustment and display control
- **Battery-Backed RTC**: DS3231 real-time clock maintains time during power loss

## Requirements

- **CircuitPython 10.x** (tested on 10.1.4)
- **Supported Boards:**
  - UnexpectedMaker Feather S2 (ESP32-S2)
  - UnexpectedMaker Feather S3 (ESP32-S3)

## Hardware Requirements

### Microcontroller Board

| Board | Processor | WiFi | Onboard LED | Purchase Link |
|-------|-----------|------|-------------|---------------|
| **Feather S2** | ESP32-S2 240MHz | 2.4GHz | DotStar (APA102) | [Adafruit](https://www.adafruit.com/product/5000) |
| **Feather S3** | ESP32-S3 240MHz Dual-Core | 2.4GHz + BLE 5.0 | NeoPixel (WS2812) | [Adafruit](https://www.adafruit.com/product/5399) |

Both boards use the same pin layout - the code auto-detects which board is running.

### Required External Components

| Component | Specifications | Purpose | Approx. Cost |
|-----------|---------------|---------|--------------|
| **Flip Dot Display** | 4-column flip dot matrix, 24V | Hour display (1-12) | $50-150 |
| **Stepper Motor** | MT-1701HSM140AE or similar, 0.9°/step (400 steps/rev) | Minute hand drive | $10-20 |
| **Stepper Driver** | TMC2209 (recommended) or A4988/DRV8825 | Motor control with microstepping | $2-10 |
| **DS3231 RTC Module** | I2C, with CR2032 battery | Battery-backed timekeeping | $3-10 |
| **SH1107 OLED Display** | 128x64, I2C @ 0x3C | Status display | $8-15 |
| **5V Relay Module** | Single channel, 24V/10A rated | Flip dot power switching | $2-5 |
| **Hall Effect Sensor** | A3144 or similar, digital output | Home position detection | $1-3 |
| **Momentary Push Buttons** | 3x normally-open | Manual controls | $1-3 |
| **24V Power Supply** | 2A minimum | Flip dot power | $10-20 |
| **Neodymium Magnet** | Small disc, ~5mm | Minute hand home marker | $1-2 |
| **5V Power Supply** | USB-C or 5V adapter | Microcontroller power | $5-10 |

### Wiring Diagram

```
                    +--------+
                    | Feather|
                    | S2/S3  |
                    +---++---+
                        ||
    +-------------------++-------------------+
    |                   ||                   |
    v                   v                    v
+--------+         +--------+           +--------+
|Flip Dot|         |Stepper |           |  I2C   |
| Matrix |         | Motor  |           |Devices |
+--------+         +--------+           +--------+
    |                   |                   |
    v                   v                   v
  24V PS            TMC2209             DS3231 RTC
                   (or A4988)           SH1107 OLED
                      |
                   Hall Sensor
```

### Component Connections

| Component | Connection | GPIO Pin | Description |
|-----------|------------|----------|-------------|
| **Flip Dot Display** | SPI Clock | IO36 (SCK) | Shift register clock |
| | SPI Data | IO35 (MOSI) | Serial data to shift registers |
| | Latch | IO37 | Latches data to outputs |
| | Output Enable | IO18 | Enables flip dot drivers |
| **Stepper Motor** | Enable | IO6 | Motor driver enable (active low) |
| | Step | IO12 | Step pulse input |
| | Direction | IO5 | Rotation direction |
| | Home Sensor | IO14 | Hall effect sensor input |
| | MS1 (Microstep) | IO17 | Microstepping configuration (HIGH for TMC2209) |
| **Relay** | Control | IO11 | 24V power control |
| **Button A** | Input | IO1 | Animation/reset button |
| **Button B** | Input | IO38 | +1 Hour button |
| **Button C** | Input | IO33 | +1 Minute button |
| **DS3231 RTC** | I2C | SDA/SCL | Address: 0x68 |
| **SH1107 OLED** | I2C | SDA/SCL | Address: 0x3C |
| **Onboard LED** | Auto | Internal | Status indicator (auto-detected) |

### Pin Summary
```
Flip Dot SPI:
  - Clock: IO36 (SCK)
  - Data:  IO35 (MOSI)
  - Latch: IO37
  - OE:    IO18

Stepper Motor (via A4988/DRV8825):
  - Enable:    IO6 (active low)
  - Step:      IO12
  - Direction: IO5
  - Home:      IO14 (hall sensor)
  - Mode:      IO17 (microstepping)

Power Control:
  - Relay: IO11

User Input:
  - Button A: IO1
  - Button B: IO38
  - Button C: IO33

I2C Bus (shared):
  - DS3231 RTC:   0x68
  - SH1107 OLED:  0x3C
```

### Stepper Motor Configuration

The minute hand uses a high-resolution stepper with TMC2209 driver:
- **Motor**: MT-1701HSM140AE or similar 0.9° stepper (400 steps/rev)
- **Driver**: TMC2209 in standalone mode
- **Microstepping**: 32x (MS1=HIGH via IO17, MS2=floating)
- **Total**: 400 × 32 = **12800 microsteps per revolution**

#### TMC2209 Wiring

| TMC2209 Pin | Connection | Notes |
|-------------|------------|-------|
| EN | IO6 | Enable (active low) |
| STEP | IO12 | Step pulse input |
| DIR | IO5 | Direction control |
| MS1 | IO17 | HIGH for 32 microsteps |
| MS2 | Float | Leave unconnected (internal pull-down) |
| VIO | 3.3V | Logic voltage |
| VM | 12V | Motor voltage |
| GND | GND | Common ground |

#### TMC2209 Microstepping Table

| MS2 | MS1 | Microsteps | Steps/Rev (0.9° motor) |
|-----|-----|------------|------------------------|
| LOW | LOW | 8 | 3200 |
| LOW | HIGH | 32 | 12800 |
| HIGH | LOW | 64 | 25600 |
| HIGH | HIGH | 16 | 6400 |

**Note**: TMC2209's StealthChop mode provides silent operation. The driver automatically interpolates to 256 microsteps internally for smooth motion.

#### Alternative: A4988/DRV8825

If using A4988 or DRV8825 instead of TMC2209, adjust `STEPS` in code.py:
```python
STEPS = 800   # A4988 at 2 microsteps × 400 base steps
STEPS = 3200  # A4988 at 8 microsteps × 400 base steps
```

### Power Requirements

| Rail | Voltage | Current | Source |
|------|---------|---------|--------|
| Logic | 3.3V | ~200mA | USB-C via Feather regulator |
| Motor | 5-12V | ~500mA | Stepper driver VCC |
| Flip Dots | 24V | ~2A peak | External 24V PSU via relay |

**Important**: The relay controls 24V power to the flip dots. The code includes precharge timing to allow capacitors to charge before flipping.

## Setup

### 1. Install CircuitPython 10.x

Download CircuitPython for your board:
- **Feather S2**: https://circuitpython.org/board/unexpectedmaker_feathers2/
- **Feather S3**: https://circuitpython.org/board/unexpectedmaker_feathers3/

### 2. Copy Files to Device

Copy the following files/folders from this repository to your CIRCUITPY drive:

| Source | Destination | Purpose |
|--------|-------------|---------|
| `code.py` | `CIRCUITPY/code.py` | Main application |
| `index.html` | `CIRCUITPY/index.html` | Web dashboard |
| `adafruit_ntp.py` | `CIRCUITPY/adafruit_ntp.py` | NTP client |
| `lib/` | `CIRCUITPY/lib/` | Required libraries |
| `settings.toml` | `CIRCUITPY/settings.toml` | Configuration (edit first) |

The `lib/` folder includes all required CircuitPython libraries pre-compiled (.mpy format) from the Adafruit bundle dated March 14, 2026.

**Note**: The code auto-detects which board you're using (Feather S2 or S3) and loads the appropriate LED library.

### 3. Configure Settings

Edit `settings.toml` with your WiFi credentials:

```toml
CIRCUITPY_WIFI_SSID = "YOUR_WIFI_SSID"
CIRCUITPY_WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
CIRCUITPY_WEB_API_PASSWORD = "your_password"
CIRCUITPY_WEB_API_PORT = 8080  # CircuitPython code editor port

# Clock web interface port
CLOCK_WEB_PORT = 80

# NTP Server (default: pool.ntp.org)
NTP_SERVER = "pool.ntp.org"
```

**Port Configuration:**
- `CLOCK_WEB_PORT` - Clock web interface (default: 80)
- `CIRCUITPY_WEB_API_PORT` - CircuitPython code editor (default: 8080)

**Code Editor Authentication:** Username is empty (leave blank), password is `CIRCUITPY_WEB_API_PASSWORD`

## Configuration

### Timing Constants (in code.py)

These values can be adjusted at the top of `code.py`:

```python
relayPrechargeS = 0.20   # seconds to let 24V rails charge
relayHoldS      = 0.08   # seconds to keep rails up after last flip
flipdotDelay    = 0.5    # seconds between flipdot actuations (capacitor recharge)
```

## Web Interface

Once connected to WiFi, the clock starts a web server on port 80:
```
http://<ip-address>/
```

The CircuitPython code editor is available on port 8080:
```
http://<ip-address>:8080/
```

The IP address is shown on the OLED display and printed to the serial console.

### Dashboard Features

- **Clock Status**: Current time, hour (12h), timezone, IP, SSID, uptime, free memory
- **Timezone Selector**: Dropdown to change timezone (18 worldwide options with DST support)
- **Motor Status**: Current position, steps total, last hour shown, flipdot power state
- **Control Buttons**: Reset to NTP, +1 Hour, +1 Minute, Wipe Display, Sync WiFi
- **Animation Buttons**: Demo, Chase, Chaos, Sync (showcase flipdots and minute hand)
- **Action Log**: Timestamped history of actions
- **Auto-refresh**: Status updates every 5 seconds

### Animations

| Animation | Description |
|-----------|-------------|
| **Demo** | Full 360° minute hand sweep, counts flipdots 1→12→blank, restores time |
| **Chase** | Flipdots ripple 1→12 while minute hand follows along |
| **Chaos** | Random flipdot patterns with oscillating hand movement |
| **Sync** | Hand sweeps to each hour position, flipdots light up in sync |

> **Note:** All demo patterns need to be reviewed and may require updates.

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | HTML dashboard |
| `/status.json` | GET | Clock status as JSON |
| `/log.json` | GET | Action log entries |
| `/get_timezone` | GET | Current timezone and available options |
| `/set_timezone` | POST | Set timezone (saves to NVM, resyncs clock) |
| `/wipe` | POST | Full reset: blank display, re-home motor, redisplay time |
| `/set_hour` | POST | Increment hour by 1 |
| `/set_min` | POST | Increment minute by 1 |
| `/sync_wifi` | POST | Trigger WiFi time sync |
| `/anim/demo` | POST | Run demo animation sequence |
| `/anim/chase` | POST | Run chase/wave animation |
| `/anim/chaos` | POST | Run random chaos animation |
| `/anim/sync` | POST | Run synchronized dance animation |
| `/home` | POST | Home motor, pause 2s at 12 o'clock, return to time |
| `/calibrate` | POST | Home motor and stay at 12 o'clock for calibration |
| `/nudge_cw` | POST | Move hand 1 step clockwise |
| `/nudge_ccw` | POST | Move hand 1 step counter-clockwise |
| `/set_home` | POST | Save current position as home offset (persists to NVM) |
| `/reset_calibration` | POST | Reset home offset to zero |
| `/get_speed` | GET | Get current step delay in microseconds |
| `/set_speed` | POST | Set step delay (100-1000 μs, persists to NVM) |

### Status JSON Response

```json
{
  "time": "14:35:22",
  "hour_12": 2,
  "minute": 35,
  "wifi_connected": true,
  "ip_address": "192.168.1.100",
  "ssid": "MyNetwork",
  "timezone": "US/Eastern",
  "timezone_name": "Eastern (New York)",
  "motor_position": 467,
  "motor_steps_total": 800,
  "last_hour_shown": 2,
  "flipdot_power": false,
  "uptime_s": 3600,
  "free_memory": 45000,
  "last_wifi_sync": "14:30:00"
}
```

## Physical Button Functions

| Button | Function |
|--------|----------|
| **A** | Blank display, animate to current hour, re-home motor |
| **B** | Increment RTC hour (+1), refresh flipdot display |
| **C** | Increment RTC minute (+1), update minute hand |

## Motor Homing Algorithm

The minute hand uses a hall sensor and magnet for precise homing. The algorithm uses symmetric edge detection for accuracy:

1. Step forward until hall sensor triggers (entering magnet zone)
2. Reverse until hall sensor releases (precise edge A)
3. Continue reversing until hall triggers again (other side)
4. Step forward until hall releases (precise edge B)
5. Move to midpoint between edge A and edge B
6. Set this position as 12:00 (stepNow = 0)

Both edges are detected at the **release point** for consistency, eliminating hall sensor hysteresis variations.

The "Home" web button pauses at 12:00 for visual verification before the next minute update moves the hand.

## Home Position Calibration

If the minute hand doesn't align exactly at 12 o'clock after homing, use the web UI calibration controls to fine-tune:

1. Click **Calibrate** - homes the motor and stays at 12 o'clock position
2. Use **+ CW** / **- CCW** buttons to nudge the hand until it points exactly at 12
3. Click **Set Home** - saves the offset to NVM (persists across reboots)

The offset (range: ±1056 steps, ~30 degrees) is automatically applied after every homing operation. Click **Reset** to clear the offset back to zero.

## Motor Speed Configuration

The stepper motor speed is configurable via the web interface and persists across reboots (stored in NVM).

### Speed Settings

| Setting | Delay | Description |
|---------|-------|-------------|
| 100 μs | Fastest | May cause missed steps |
| 300 μs | Fast | Good for quick movements |
| **450 μs** | **Default** | Balanced speed and reliability |
| 700 μs | Slow | Very smooth motion |
| 1000 μs | Slowest | Maximum torque |

The dropdown in the web UI offers options from 100-1000 μs in 25 μs increments.

### Timing Calibration

CircuitPython's `time.sleep()` does not provide reliable microsecond-level delays on ESP32. The code uses a calibrated busy-wait loop instead:

```python
# Calibrated delay loop for ESP32-S3 at 240MHz
loops = int(delay * 580000)  # 580k iterations per second
for _ in range(loops):
    pass
```

**Calibration process:**
1. The ESP32-S3 runs at 240MHz with a Python interpreter overhead
2. A simple `for` loop was benchmarked to determine iterations per second
3. The calibration factor (580,000) was tuned to achieve 98%+ timing accuracy
4. Actual vs expected timing was verified via `time.monotonic()` measurements

**Verification results (at 1000 μs setting):**
- 6400 steps: expected 6.400s, actual 6.746s (94% accurate)
- 213 steps: expected 0.213s, actual 0.209s (98% accurate)

If running on different hardware (Feather S2 vs S3, different clock speed), you may need to adjust the calibration factor in `oneStep()`.

## Operation

### Startup Sequence
1. Initialize hardware (LEDs, I2C, RTC, buttons, OLED)
2. Blank display sequence (black → white → black)
3. Calibrate motor home position using hall sensor
4. Display current hour on flipdots
5. Position minute hand
6. Connect to WiFi and sync time
7. Start web server on port 80
8. Enter main loop

### Main Loop
- **Every second**: Update OLED time display, toggle heartbeat LED
- **Every minute**: Move minute hand to new position
- **Every hour**: Update flipdot hour display, re-home motor
- **Continuous**: Poll web server, check buttons, manage flipdot power

## Timezone Configuration

Timezone can be changed via the web UI dropdown. The selected timezone is saved to the microcontroller's non-volatile memory (NVM) and persists across reboots. Fresh devices default to US/Eastern.

Timezone changes work even with USB connected - no need to disconnect.

### Supported Timezones

| Key | Name | UTC Offset | DST |
|-----|------|------------|-----|
| `US/Hawaii` | Hawaii | -10:00 | No |
| `US/Alaska` | Alaska | -9:00 | Yes |
| `US/Pacific` | Pacific (LA) | -8:00 | Yes |
| `US/Mountain` | Mountain (Denver) | -7:00 | Yes |
| `US/Arizona` | Arizona | -7:00 | No |
| `US/Central` | Central (Chicago) | -6:00 | Yes |
| `US/Eastern` | Eastern (New York) | -5:00 | Yes |
| `EU/London` | London | +0:00 | Yes |
| `EU/Paris` | Paris | +1:00 | Yes |
| `EU/Berlin` | Berlin | +1:00 | Yes |
| `EU/Moscow` | Moscow | +3:00 | No |
| `AS/Dubai` | Dubai | +4:00 | No |
| `AS/Mumbai` | Mumbai | +5:30 | No |
| `AS/Singapore` | Singapore | +8:00 | No |
| `AS/Tokyo` | Tokyo | +9:00 | No |
| `OC/Sydney` | Sydney | +10:00 | Yes |
| `OC/Auckland` | Auckland | +12:00 | Yes |
| `UTC` | UTC | +0:00 | No |

### DST Rules

Daylight Saving Time is automatically calculated for:
- **US**: 2nd Sunday March → 1st Sunday November
- **EU**: Last Sunday March → Last Sunday October
- **AU**: 1st Sunday October → 1st Sunday April
- **NZ**: Last Sunday September → 1st Sunday April

## Troubleshooting

### WiFi Connection Issues
- Check SSID and password in `settings.toml`
- Ensure 2.4GHz network (ESP32-S2/S3 doesn't support 5GHz)
- Check serial console for error messages
- Feather S3 also supports BLE, but this project uses WiFi only

**Note on CircuitPython 10.1.4**: A 3-second delay was added before WiFi connection to allow the WiFi radio to stabilize after motor initialization. Without this delay, WiFi and NTP connections may fail intermittently during startup. This timing fix is already implemented in the code.

### Motor Not Homing Correctly
- Verify hall sensor connection (IO14)
- Check magnet position on minute hand
- Use "Home Motor" web button to verify 12:00 position
- Motor should detect magnet within one full rotation

### Flipdots Not Flipping
- Check 24V power supply
- Verify relay clicks when flipdot power enabled
- Increase `flipdotDelay` if capacitors need more recharge time
- Check SPI connections

### Web Interface Not Loading
- Confirm WiFi connected (check OLED display)
- Clock interface runs on **port 80** (default HTTP)
- CircuitPython code editor runs on **port 8080**
- Try accessing `/status.json` directly
- Check serial console for server errors

## License

MIT License
