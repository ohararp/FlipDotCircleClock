# boot.py - Runs before code.py at startup
# Makes filesystem writable to CircuitPython when USB is not connected

import storage
import supervisor

# If USB is not connected, make filesystem writable to CircuitPython
# This allows saving config.json from the web interface
if not supervisor.runtime.usb_connected:
    storage.remount("/", readonly=False)
    print("Filesystem: writable to CircuitPython")
else:
    print("Filesystem: writable to USB host")
