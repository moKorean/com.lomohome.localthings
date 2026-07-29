"""Registry primitives: how one OCF resource maps to one Homey capability.

The reference integration emits Home Assistant entities, which can carry dynamic
options and arbitrary units. Homey instead has a fixed capability per device with
enum values declared statically in the manifest, so the mapping here is
capability-centric: each Spec owns a Homey capability id, the resource it reads
from, and optionally how to write it back.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class Spec:
    """One Homey capability backed by one OCF resource.

    read:  (rep, resources) -> value, or None to leave the capability alone.
           Returning None matters — a resource that is a stub or missing a field
           must not clobber a good value with a wrong one.
    write: (value, rep) -> (path_segs, body) for the POST, or None for
           read-only capabilities.
    """

    capability: str
    href: str
    read: Callable[[dict, dict], Any]
    write: Optional[Callable[[Any, dict], tuple[list[str], dict]]] = None

    @property
    def writable(self) -> bool:
        return self.write is not None


@dataclass(frozen=True)
class Registry:
    """Everything needed to drive one appliance type."""

    name: str
    device_class: str  # Homey device class, e.g. 'thermostat'
    specs: tuple[Spec, ...]
    # Display names per language, used for the device's initial name. A Homey
    # device name is a plain user-editable string rather than an i18n object, so
    # the language has to be chosen when the device is created; the user can
    # rename it afterwards either way.
    titles: dict = None

    def title(self, language: str = "en") -> str:
        titles = self.titles or {}
        return titles.get((language or "en")[:2].lower()) or titles.get("en") or self.name

    def capabilities(self, resources: dict) -> list[str]:
        """Capability ids this device actually supports.

        Driven by which resources the appliance reported, so one generic driver
        can present only the controls a given unit really has.
        """
        seen = []
        for spec in self.specs:
            if spec.href in resources and spec.capability not in seen:
                seen.append(spec.capability)
        return seen

    def spec_for(self, capability: str) -> Optional[Spec]:
        for spec in self.specs:
            if spec.capability == capability:
                return spec
        return None


# --- shared field readers -------------------------------------------------


def as_float(value) -> Optional[float]:
    """Device fields are CBOR text strings far more often than numbers."""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def as_int(value) -> Optional[int]:
    parsed = as_float(value)
    return None if parsed is None else int(parsed)


def first_item(rep: dict) -> dict:
    """`x.com.samsung.da.items` is an array even where only one entry ever
    exists (temperature on every AC dump seen). Return entry id '0', else the
    first, else {}."""
    items = rep.get("x.com.samsung.da.items")
    if not isinstance(items, list) or not items:
        return {}
    for item in items:
        if isinstance(item, dict) and str(item.get("x.com.samsung.da.id")) == "0":
            return item
    return items[0] if isinstance(items[0], dict) else {}
