"""The generic appliance device.

The implementation lives in lib/appliance/device.py so a per-appliance-type
driver can subclass it instead of copying it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from lib.appliance.device import ApplianceDevice


class Device(ApplianceDevice):
    """The generic driver's device: every appliance type the registry can route."""


homey_export = Device
