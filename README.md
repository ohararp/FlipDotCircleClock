# FlipDotCircleClock

A CircuitPython-based flip dot clock with a mechanical minute hand, running on a Feather S2 microcontroller. Features WiFi time synchronization, OLED status display, and a web interface for remote monitoring and control.

## Features

- **Flip Dot Hour Display**: 4-column flip dot display shows the current hour (1-12)
- **Mechanical Minute Hand**: Stepper motor-driven minute hand with hall sensor homing
- **WiFi Time Sync**: Automatic time synchronization via Adafruit IO with timezone support
- **OLED Status Display**: 128x64 SH1107 display showing time, WiFi status, and IP address
- **Web Interface**: Browser-based dashboard for remote monitoring and control
- **Physical Buttons**: 3 buttons for manual time adjustment and display control
- **Battery-Backed RTC**: DS3231 real-time clock maintains time during power loss

## Hardware

### Microcontroller
- Adafruit Feather S2 (ESP32-S2)

### Components
| Component | Connection | Description |
|-----------|------------|-------------|
| Flip Dot Display | SPI (IO35, IO36, IO37, IO18) | 4-column flip dot matrix |
| Stepper Motor | IO5, IO6, IO12, IO14, IO17 | Minute hand drive |
| DS3231 RTC | I2C | Battery-backed timekeeping |
| SH1107 OLED | I2C (0x3C) | 128x64 status display |
| Relay | IO11 | 24V flipdot power control |
| Button A | IO1 | Display animation/reset |
| Button B | IO38 | +1 Hour |
| Button C | IO33 | +1 Minute |
| Hall Sensor | IO14 | Motor home position |
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

### 1. Install CircuitPython Libraries

Copy these libraries to the `lib/` folder on your CIRCUITPY drive:
- `adafruit_ds3231`
- `adafruit_displayio_sh1107`
- `adafruit_display_text`
- `adafruit_display_shapes`
- `adafruit_dotstar`
- `adafruit_fancyled`
- `adafruit_requests`
- `adafruit_httpserver`

### 2. Configure Credentials

Copy `secrets.py.example` to `secrets.py` and fill in your details:

```python
secrets = {
    "ssid": "YOUR_WIFI_SSID",
    "password": "YOUR_WIFI_PASSWORD",
    "timezone": "America/New_York",
    "aio_username": "YOUR_AIO_USERNAME",
    "aio_key": "YOUR_AIO_KEY",
}
```

Get free Adafruit IO credentials at: https://io.adafruit.com

### 3. Deploy

Copy `code.py` and `secrets.py` to your CIRCUITPY drive.

## Web Interface

Once connected to WiFi, the clock starts a web server. Access it at:
```
http://<ip-address>/
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
| `/home` | POST | Re-home the minute hand motor |
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

## Operation

### Startup Sequence
1. Initialize hardware (LEDs, I2C, RTC, buttons, OLED)
2. Blank display sequence (black → white → black)
3. Calibrate motor home position using hall sensor
4. Display current hour on flipdots
5. Position minute hand
6. Connect to WiFi and sync time
7. Start web server
8. Enter main loop

### Main Loop
- **Every second**: Update OLED time display, toggle heartbeat LED
- **Every minute**: Move minute hand to new position
- **Every hour**: Update flipdot hour display, re-home motor
- **Continuous**: Poll web server, check buttons, manage flipdot power

## Timezone Configuration

Supported timezones (set in `secrets.py`):

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
- Check SSID and password in `secrets.py`
- Ensure 2.4GHz network (ESP32-S2 doesn't support 5GHz)
- Check serial console for error messages

### Motor Not Homing
- Verify hall sensor connection (IO14)
- Check magnet position on minute hand
- Motor should detect magnet within one full rotation

### Flipdots Not Flipping
- Check 24V power supply
- Verify relay clicks when flipdot power enabled
- Check SPI connections

### Web Interface Not Loading
- Confirm WiFi connected (check OLED display)
- Try accessing `/status.json` directly
- Check serial console for server errors

## License

MIT License
