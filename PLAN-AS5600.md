# Plan: Add AS5600 Magnetic Rotary Encoder (Level 4 + Hall Sensor Backup)

## Overview
Add AS5600 12-bit magnetic rotary encoder for closed-loop position control, keeping hall sensor as safety backup.

## Design Decision: PID vs Simple Closed-Loop

**Recommendation: Simple closed-loop (NOT full PID)**

### Why PID is Overkill for This Application

| Factor | Your Clock | When PID Needed |
|--------|------------|-----------------|
| Motion frequency | 1x per minute | Continuous/high-speed |
| Load | Very light | Heavy/variable loads |
| Speed | ~13 steps/min avg | High velocity moves |
| Disturbances | None | External forces |
| Precision needed | ~1 step (0.45°) | Sub-step accuracy |

### Simple Closed-Loop Algorithm
```
target = minute_to_angle(current_minute)
while |target - actual| > tolerance:
    direction = sign(target - actual)
    step(direction)
    actual = read_AS5600()
```

This works because:
1. Steppers are deterministic - each step moves a fixed amount
2. No overshoot at low speeds
3. No integral windup concerns
4. No derivative needed (not fighting momentum)

### What AS5600 Provides (Without PID Complexity)
- **Lost step recovery**: If we miss steps, next move corrects
- **Absolute position**: Always know where we are
- **Stall detection**: If angle doesn't change after stepping
- **Eliminates calibration drift**: No accumulated error over time

## Current Setup
- **Motor**: Stepper with 800 steps/revolution (STEPS = 800)
- **Position tracking**: `stepNow` variable (0-799), relative counting from home
- **Homing**: Hall sensor detects magnet, finds center via edge detection
- **I2C devices**: DS3231 RTC (0x68), SH1107 OLED (0x3C)
- **AS5600 address**: 0x36 (no conflict)

## Hardware Requirements
- AS5600 breakout board connected to I2C (SDA, SCL, 3.3V, GND)
- Diametrically magnetized magnet on motor shaft (6mm diameter recommended)
- Magnet positioned ~1-3mm from AS5600 sensor face
- Hall sensor remains connected for backup/safety

## Primary Goal: Eliminate Calibration

The current system requires manual calibration because:
1. Hall sensor homing finds magnet center (not necessarily 12:00)
2. Mechanical tolerances cause offset
3. We nudge and save offset to NVM

**With AS5600, we eliminate this by:**
1. One-time setup: Position hand at 12:00, record AS5600 reading
2. Store this as "zero reference" in NVM (or program AS5600 ZPOS register)
3. All future positioning is relative to this absolute reference
4. No drift, no accumulated error, no re-calibration needed

## Zero Reference: Layered Approach

### Layer 1: Initial Setup (One-Time)
1. Manually position minute hand exactly at 12:00
2. Read AS5600 raw value (e.g., 2847)
3. Store this as `as5600_zero` in NVM
4. All positions calculated relative to this zero

### Layer 2: Runtime Positioning
```python
def get_current_minute():
    raw = read_as5600()
    # Subtract zero reference, wrap to 0-4095
    adjusted = (raw - as5600_zero) % 4096
    # Convert to minute (0-59)
    return int((adjusted / 4096.0) * 60) % 60
```

### Layer 3: Optional - Program AS5600 ZPOS (Advanced)
The AS5600 has a programmable zero position register (ZPOS).
If we write our zero reference to ZPOS, the chip itself reports adjusted angles.
- Advantage: Zero reference survives power cycles (stored in AS5600)
- Note: Requires burning OTP or using external EEPROM mode

### Layer 4: Hall Sensor Fallback
If AS5600 fails or reports invalid data:
1. Fall back to hall sensor homing
2. Use stored NVM calibration offset
3. Revert to step counting

## Key Changes

### Before (Open-Loop Step Counting)
```
RTC time → Hall sensor home → Count steps from 0 → Hope we're there
Problems: Homing offset, accumulated step errors, drift over time
```

### After (Closed-Loop Position Feedback)
```
RTC time → Read AS5600 → Move until angle matches target
Benefits: Absolute position, self-correcting, no drift
```

## The Big Picture: Why This Solves Your Homing Problem

**Current Issue:**
```
Hall sensor detects magnet → Find "center" → But center ≠ 12:00
→ Need to nudge → Save offset → Still drifts over time
```

**With AS5600:**
```
Minute hand IS the position sensor
AS5600 directly measures where the hand points
No homing needed for positioning (only for initial setup)
```

The fundamental shift: Instead of "home then count steps", we just "read where we are and move to target".

## Files to Modify
- `code.py` - AS5600 driver, closed-loop motion, homing changes
- `index.html` - Display AS5600 angle and position error

---

## Implementation

### 1. AS5600 Driver Functions (code.py ~line 240)

```python
# AS5600 I2C Address and Registers
AS5600_ADDR = 0x36
AS5600_RAW_ANGLE = 0x0C  # 12-bit raw angle (0-4095)
AS5600_STATUS = 0x0B     # Magnet status register
AS5600_ZPOS = 0x01       # Zero position register (programmable)

as5600_available = False  # Set True after successful init

def init_as5600(i2c):
    """Initialize AS5600 and verify magnet detected."""
    global as5600_available
    try:
        # Read status register to check magnet
        buf = bytearray(1)
        i2c.writeto_then_readfrom(AS5600_ADDR, bytes([AS5600_STATUS]), buf)
        status = buf[0]
        md = (status >> 5) & 1  # Magnet detected bit
        ml = (status >> 4) & 1  # Magnet too weak
        mh = (status >> 3) & 1  # Magnet too strong

        if md:
            as5600_available = True
            print("AS5600 initialized - magnet detected")
            if ml: print("  Warning: magnet too weak")
            if mh: print("  Warning: magnet too strong")
            return True
        else:
            print("AS5600: No magnet detected!")
            return False
    except Exception as e:
        print("AS5600 init failed:", e)
        return False

def read_as5600_raw(i2c):
    """Read raw angle (0-4095 for 360°). Returns -1 on error."""
    if not as5600_available:
        return -1
    try:
        buf = bytearray(2)
        i2c.writeto_then_readfrom(AS5600_ADDR, bytes([AS5600_RAW_ANGLE]), buf)
        return ((buf[0] & 0x0F) << 8) | buf[1]
    except:
        return -1

def as5600_to_degrees(raw):
    """Convert raw to degrees (0.0-359.9)."""
    if raw < 0: return -1
    return (raw / 4096.0) * 360.0

def as5600_to_minute(raw):
    """Convert raw angle to minute (0-59)."""
    if raw < 0: return -1
    return int((raw / 4096.0) * 60) % 60

def minute_to_as5600(minute):
    """Convert minute (0-59) to target AS5600 raw value."""
    return int((minute / 60.0) * 4096) % 4096
```

### 2. Closed-Loop Move Function (code.py ~line 630)

```python
def moveToAngle(target_raw, timeout_steps=1000):
    """Move motor until AS5600 reads target angle. Returns True on success."""
    if not as5600_available:
        print("AS5600 not available, falling back to step count")
        return False

    TOLERANCE = 5  # ~0.4° tolerance (5/4096 * 360)

    en.value = motorEnabled
    steps_taken = 0

    while steps_taken < timeout_steps:
        current = read_as5600_raw(i2c)
        if current < 0:
            print("AS5600 read error during move")
            return False

        # Calculate shortest path (handle wrap-around)
        diff = target_raw - current
        if diff > 2048:
            diff -= 4096
        elif diff < -2048:
            diff += 4096

        if abs(diff) <= TOLERANCE:
            print("Target reached in %d steps" % steps_taken)
            return True

        # Move one step in correct direction
        direction = 1 if diff > 0 else 0
        oneStep(direction, 0.002)
        steps_taken += 1

    print("Timeout: failed to reach target after %d steps" % timeout_steps)
    return False
```

### 3. Modified minUpdate (code.py ~line 810)

```python
def minUpdate():
    """Update minute hand using AS5600 closed-loop positioning."""
    t = rtc.datetime
    target_minute = t.tm_min

    if as5600_available:
        # Closed-loop: move to target angle
        target_raw = minute_to_as5600(target_minute)
        if moveToAngle(target_raw):
            global stepNow
            stepNow = int((target_raw / 4096.0) * STEPS) % STEPS
            return
        # Fall through to open-loop if closed-loop fails

    # Open-loop fallback (original step counting)
    minSteps = int(round(target_minute / 60.0 * STEPS)) % STEPS
    diff = (minSteps - stepNow) % STEPS
    if diff > STEPS // 2:
        diff -= STEPS
    # ... rest of original logic
```

### 4. Modified Homing (code.py ~line 650)

```python
def findExactHome(delay):
    """Home using hall sensor, then calibrate AS5600 zero position."""
    # ... existing hall sensor edge detection ...

    stepNow = 0

    # Apply NVM offset
    offset = load_home_offset_nvm()
    if offset != 0:
        # ... apply offset ...

    # Record AS5600 position at 12 o'clock for reference
    if as5600_available:
        home_raw = read_as5600_raw(i2c)
        print("AS5600 at home: %d (%.1f°)" % (home_raw, as5600_to_degrees(home_raw)))
        # Store this as the zero reference for closed-loop moves
        global as5600_home_offset
        as5600_home_offset = home_raw
```

### 5. Status JSON Update (code.py ~line 1335)

Add to status response:
```python
"as5600_available": as5600_available,
"as5600_raw": read_as5600_raw(i2c) if as5600_available else -1,
"as5600_degrees": as5600_to_degrees(read_as5600_raw(i2c)) if as5600_available else -1,
"as5600_minute": as5600_to_minute(read_as5600_raw(i2c)) if as5600_available else -1,
```

### 6. Web UI Update (index.html)

Add to Motor & Display section:
```html
<div class="k">AS5600 Angle</div><div class="v" id="as5600Angle">...</div>
<div class="k">AS5600 Minute</div><div class="v" id="as5600Min">...</div>
```

Update refreshStatus():
```javascript
setText('as5600Angle', d.as5600_available ? d.as5600_degrees.toFixed(1) + '°' : 'N/A');
setText('as5600Min', d.as5600_available ? d.as5600_minute : 'N/A');
```

### 7. Initialization (code.py ~line 1530)

After I2C setup:
```python
i2c = setupI2C()
rtc = setupRTC(i2c)
init_as5600(i2c)  # Add this line
```

---

## Safety: Hall Sensor Backup

The hall sensor remains for:
1. **Fallback** - If AS5600 fails/disconnects, revert to hall sensor + step counting
2. **Sanity check** - Verify AS5600 reading makes sense (magnet in range)
3. **Legacy mode** - System works without AS5600 if not installed

**Note:** With AS5600, hall sensor is NOT needed for normal homing. We just read the absolute position.

## Edge Cases and Considerations

### What If the Magnet Moves?
If the magnet shifts on the shaft, AS5600 zero reference becomes invalid.
- **Detection:** Positions will be consistently off by the shift amount
- **Fix:** Re-run one-time zero calibration (position at 12:00, save reading)
- **Prevention:** Secure magnet with adhesive or set screw

### What If AS5600 Reports Invalid Data?
- Check magnet status register (MD, ML, MH bits)
- If no magnet detected: fall back to hall sensor mode
- If magnet too weak/strong: warn but continue (usually still works)

### Power Cycle Behavior
- AS5600 is absolute - knows position immediately on power-up
- No homing sequence needed (unless AS5600 unavailable)
- Minute hand doesn't move during boot - already in correct position

### 12:00 Crossing (Wrap-Around)
When minute hand goes from 59 to 0:
- AS5600 raw value wraps around zero reference
- Code must handle: `(raw - zero_ref) % 4096`
- Same logic as current stepNow wrap-around

### Step Loss Detection (Bonus)
With AS5600, we can detect if motor stalls:
```python
before = read_as5600()
step(direction)
after = read_as5600()
if abs(after - before) < expected_change:
    print("Warning: possible step loss or stall")
```

---

## Verification Steps

1. **Hardware test**: Connect AS5600, run I2C scan to confirm 0x36 detected
2. **Magnet test**: Check AS5600 status register for magnet detection
3. **Angle test**: Manually rotate motor, verify angle changes smoothly 0-360°
4. **Home test**: Run homing, verify AS5600 reads ~0° at 12 o'clock
5. **Move test**: Call minUpdate(), verify hand moves to correct minute via closed-loop
6. **Fallback test**: Disconnect AS5600, verify falls back to step counting

---

## Future Enhancements (Optional)
- Program AS5600 ZPOS register to set hardware zero at 12 o'clock
- Add position error display (expected vs actual)
- Implement stall detection (motor stepping but angle not changing)
