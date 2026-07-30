"""The appliance driver and device, shared so per-type drivers can subclass them.

These import `homey`, which only exists inside the app container, so nothing here
is importable from the tests — that is why lib/__init__.py does not pull them in
and why the driver integrity checks parse them instead.
"""
