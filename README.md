# FlipDotCircleClock

A CircuitPython-based flip dot clock with a mechanical minute hand, running on a Feather S2 microcontroller. Features WiFi time synchronization, OLED status display, and a web interface for remote monitoring and control.

## Features

- **Flip Dot Hour Display**: 4-column flip dot display shows the current hour (1-12)
- **Mechanical Minute Hand**: Stepper motor-driven minute hand with precision hall sensor homing
- **NTP Time Sync**: Automatic time synchronization via NTP with timezone and DST support
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
- `adafruit_requests`
- `adafruit_httpserver`
- `adafruit_ntp`

### 3. Configure Settings

Copy `settings.toml.example` to `settings.toml` and fill in your details:

```toml
CIRCUITPY_WIFI_SSID = "YOUR_WIFI_SSID"
CIRCUITPY_WIFI_PASSWORD = "YOUR_WIFI_PASSWORD"
CIRCUITPY_WEB_API_PASSWORD = "your_password"
CIRCUITPY_WEB_API_PORT = 80

# NTP Server (default: pool.ntp.org)
NTP_SERVER = "pool.ntp.org"

# Default timezone (can be changed via web UI)
TIMEZONE = "US/Eastern"
```

### 4. Deploy

Copy the following files to your CIRCUITPY drive:
- `code.py` - Main application
- `settings.toml` - WiFi and NTP configuration
- `index.html` - Web dashboard

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
- **Timezone Selector**: Dropdown to change timezone (18 worldwide options with DST support)
- **Motor Status**: Current position, steps total, last hour shown, flipdot power state
- **Control Buttons**: Wipe Display, Refresh Hour, Sync WiFi, +1 Hour, +1 Minute, Reset to NTP, Home Motor
- **Action Log**: Timestamped history of actions
- **Auto-refresh**: Status updates every 5 seconds

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | HTML dashboard |
| `/status.json` | GET | Clock status as JSON |
| `/log.json` | GET | Action log entries |
| `/get_timezone` | GET | Current timezone and available options |
| `/set_timezone` | POST | Set timezone (saves to NVM, resyncs clock) |
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

Timezone can be changed via the web UI dropdown or set as default in `settings.toml`. The selected timezone is saved to the microcontroller's non-volatile memory (NVM) and persists across reboots.

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
