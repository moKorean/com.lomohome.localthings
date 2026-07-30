"""The generic appliance driver.

The implementation lives in lib/appliance/driver.py so a per-appliance-type
driver can subclass it instead of copying it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2]))

from lib.appliance.driver import ApplianceDriver


class Driver(ApplianceDriver):
    """The generic driver, covering every appliance type the registry can route."""


homey_export = Driver
