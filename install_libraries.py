#!/usr/bin/env python3
"""
CircuitPython Library Installer for FlipDotCircleClock

This script downloads and installs the required CircuitPython libraries
to the lib/ folder. Run this on your computer (not on CircuitPython).

Usage:
    python install_libraries.py [--drive DRIVE_PATH]

Requirements:
    pip install circup

Alternative manual installation:
    1. Download the Adafruit CircuitPython Bundle from:
       https://circuitpython.org/libraries
    2. Extract and copy the following to your CIRCUITPY/lib folder:
       - adafruit_ds3231.mpy
       - adafruit_displayio_sh1107.mpy
       - adafruit_display_text/ (folder)
       - adafruit_display_shapes/ (folder)
       - adafruit_dotstar.mpy (for Feather S2)
       - neopixel.mpy (for Feather S3)
       - adafruit_requests.mpy
       - adafruit_httpserver/ (folder)
       - adafruit_register/ (folder)
       - adafruit_bus_device/ (folder)
       - adafruit_connection_manager.mpy
"""

import subprocess
import sys
import os
import argparse


def check_circup():
    """Check if circup is installed."""
    try:
        subprocess.run([sys.executable, "-m", "circup", "--version"],
                      capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def install_circup():
    """Install circup via pip."""
    print("Installing circup...")
    subprocess.run([sys.executable, "-m", "pip", "install", "circup"], check=True)


def install_libraries(drive_path=None):
    """Install CircuitPython libraries using circup."""

    # Required libraries
    libraries = [
        "adafruit_ds3231",
        "adafruit_displayio_sh1107",
        "adafruit_display_text",
        "adafruit_display_shapes",
        "adafruit_dotstar",
        "neopixel",
        "adafruit_requests",
        "adafruit_httpserver",
    ]

    cmd = [sys.executable, "-m", "circup", "install"]

    if drive_path:
        cmd.extend(["--path", drive_path])

    cmd.extend(libraries)

    print(f"Installing libraries: {', '.join(libraries)}")
    print(f"Command: {' '.join(cmd)}")

    try:
        subprocess.run(cmd, check=True)
        print("\nLibraries installed successfully!")
        print("\nNote: circup automatically installs dependencies like:")
        print("  - adafruit_register")
        print("  - adafruit_bus_device")
        print("  - adafruit_connection_manager")
    except subprocess.CalledProcessError as e:
        print(f"\nError installing libraries: {e}")
        print("\nTry manual installation:")
        print("1. Download bundle from https://circuitpython.org/libraries")
        print("2. Copy libraries to your CIRCUITPY/lib folder")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Install CircuitPython libraries for FlipDotCircleClock"
    )
    parser.add_argument(
        "--drive", "-d",
        help="Path to CIRCUITPY drive (e.g., /Volumes/CIRCUITPY or D:)",
        default=None
    )
    args = parser.parse_args()

    print("FlipDotCircleClock Library Installer")
    print("=" * 40)

    # Check for circup
    if not check_circup():
        print("circup not found. Installing...")
        try:
            install_circup()
        except subprocess.CalledProcessError:
            print("Failed to install circup. Please install manually:")
            print("  pip install circup")
            sys.exit(1)

    # Install libraries
    if install_libraries(args.drive):
        print("\nSetup complete!")
        if not args.drive:
            print("\nNote: Libraries were installed to the auto-detected CIRCUITPY drive.")
            print("Use --drive to specify a different path if needed.")
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
