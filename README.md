# FlipDotCircleClock

A CircuitPython-based flip dot clock with a mechanical minute hand, running on a Feather S2 microcontroller. Features WiFi time synchronization, OLED status display, and a web interface for remote monitoring and control.

## Features

- **Flip Dot Hour Display**: 4-column flip dot display shows the current hour (1-12)
- **Mechanical Minute Hand**: Stepper motor-driven minute hand with precision hall sensor homing
- **WiFi Time Sync**: Automatic time synchronization via Adafruit IO with timezone support
- **OLED Status Display**: 128x64 SH1107 display showing time, WiFi status, and IP address
- **Web Interface**: Browser-based dashboard for remote monitoring and control
- **Physical Buttons**: 3 buttons for manual time adjustment and display control
- **Battery-Backed RTC**: DS3231 real-time clock maintains time during power loss

## Requirements

- **CircuitPython 10.x** (tested on 10.0.3)
- Feather S2 (ESP32-S2)

## Hardware

### Components
| Component | Connection | Description |
|-----------|------------|-------------|
| Flip Dot Display | SPI (IO35, IO36, IO37, IO18) | 4-column flip dot matrix |
| Stepper Motor | IO5, IO6, IO12, IO14, IO17 | Direct-drive minute hand |
| DS3231 RTC | I2C | Battery-backed timekeeping |
| SH1107 OLED | I2C (0x3C) | 128x64 status display |
| Relay | IO11 | 24V flipdot power control |
| Button A | IO1 | Display animation/reset |
| Button B | IO38 | +1 Hour |
| Button C | IO33 | +1 Minute |
| Hall Sensor | IO14 | Motor home position detection |
| DotStar LED | APA102 | Status indicator |

### Pin Summary
```
Flip Dot SPI:
  - Clock: IO36 (SCK)
  - Data:  IO35
  - Latch: IO37
  - OE:    IO18

Stepper Motor:
  - Enable:    IO6
  - Step:      IO12
  - Direction: IO5
  - Home:      IO14
  - Mode:      IO17

Power:
  - Relay: IO11

Buttons:
  - A: IO1
  - B: IO38
  - C: IO33
```

## Setup

### 1. Install CircuitPython 10.x

Download from: https://circuitpython.org/board/unexpectedmaker_feathers2/

### 2. Install Libraries

Copy these libraries to the `lib/` folder on your CIRCUITPY drive:
- `adafruit_ds3231`
- `adafruit_register`
- `adafruit_displayio_sh1107`
- `adafruit_display_text`
- `adafruit_display_shapes`
- `adafruit_dotstar`
- `adafruit_fancyled`
- `adafruit_requests`
- `adafruit_httpserver`

### 3. Configure Credentials

Copy `settings.toml.example` to `settings.toml` and fill in your details:

```toml
CIRCUITPY_WIFI_SSID = "YOUR_WIFI_SSID"
CIRCUITPY_WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
CIRCUITPY_WEB_API_PASSWORD = "your_password"
CIRCUITPY_WEB_API_PORT = 80

TIMEZONE = "America/New_York"

AIO_USERNAME = "YOUR_AIO_USERNAME"
AIO_KEY = "YOUR_AIO_KEY"
```

Get free Adafruit IO credentials at: https://io.adafruit.com

### 4. Deploy

Copy `code.py` and `settings.toml` to your CIRCUITPY drive.

## Configuration

### Timing Constants (in code.py)

These values can be adjusted at the top of `code.py`:

```python
relayPrechargeS = 0.20   # seconds to let 24V rails charge
relayHoldS      = 0.08   # seconds to keep rails up after last flip
flipdotDelay    = 0.5    # seconds between flipdot actuations (capacitor recharge)
```

## Web Interface

Once connected to WiFi, the clock starts a web server on port 5000:
```
http://<ip-address>:5000/
```

The IP address is shown on the OLED display and printed to the serial console.

### Dashboard Features

- **Clock Status**: Current time, hour (12h), timezone, IP, SSID, uptime, free memory
- **Motor Status**: Current position, steps total, last hour shown, flipdot power state
- **Control Buttons**: Wipe Display, Refresh Hour, Sync WiFi, +1 Hour, +1 Minute, Home Motor
- **Action Log**: Timestamped history of actions
- **Auto-refresh**: Status updates every 5 seconds

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | HTML dashboard |
| `/status.json` | GET | Clock status as JSON |
| `/log.json` | GET | Action log entries |
| `/wipe` | POST | Run blank-white-blank sequence |
| `/set_hour` | POST | Increment hour by 1 |
| `/set_min` | POST | Increment minute by 1 |
| `/refresh` | POST | Force flipdot hour refresh |
| `/home` | POST | Re-home motor (pauses at 12:00 for verification) |
| `/sync_wifi` | POST | Trigger WiFi time sync |

### Status JSON Response

```json
{
  "time": "14:35:22",
  "hour_12": 2,
  "minute": 35,
  "wifi_connected": true,
  "ip_address": "192.168.1.100",
  "ssid": "MyNetwork",
  "timezone": "America/New_York",
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

The "Home Motor" web button pauses at 12:00 for visual verification before the next minute update moves the hand.

## Operation

### Startup Sequence
1. Initialize hardware (LEDs, I2C, RTC, buttons, OLED)
2. Blank display sequence (black → white → black)
3. Calibrate motor home position using hall sensor
4. Display current hour on flipdots
5. Position minute hand
6. Connect to WiFi and sync time
7. Start web server on port 5000
8. Enter main loop

### Main Loop
- **Every second**: Update OLED time display, toggle heartbeat LED
- **Every minute**: Move minute hand to new position
- **Every hour**: Update flipdot hour display, re-home motor
- **Continuous**: Poll web server, check buttons, manage flipdot power

## Timezone Configuration

Supported timezones (set in `settings.toml`):

**United States**
- `America/New_York`
- `America/Chicago`
- `America/Denver`
- `America/Los_Angeles`
- `America/Phoenix`

**Europe**
- `Europe/London`
- `Europe/Paris`
- `Europe/Berlin`

**Asia**
- `Asia/Tokyo`
- `Asia/Shanghai`
- `Asia/Singapore`

**Australia**
- `Australia/Sydney`
- `Australia/Melbourne`

Full list: http://worldtimeapi.org/timezones

## Troubleshooting

### WiFi Connection Issues
- Check SSID and password in `settings.toml`
- Ensure 2.4GHz network (ESP32-S2 doesn't support 5GHz)
- Check serial console for error messages

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
- Note: web server runs on **port 5000**, not 80
- Try accessing `/status.json` directly
- Check serial console for server errors

## License

MIT License
