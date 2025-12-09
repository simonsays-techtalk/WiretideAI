"""Device template metadata for approval-time UI and backend helpers."""

from typing import Any, Dict, List, Sequence

UNKNOWN_DEVICE_TYPE = "unknown"

DEVICE_TEMPLATES: Sequence[Dict[str, Any]] = [
    {
        "device_type": "router",
        "label": "Router",
        "description": "WAN router/firewall device with DHCP/NAT; no WiFi controls.",
        "features": {
            "wifi": False,
            "firewall": True,
            "dhcp": True,
            "switch": True,
            "vpn": True,
        },
    },
    {
        "device_type": "access_point",
        "label": "Access Point",
        "description": "Wireless access point focused on SSID/channel/roaming settings.",
        "features": {
            "wifi": True,
            "firewall": False,
            "dhcp": False,
            "switch": False,
            "roaming": True,
        },
    },
    {
        "device_type": "switch",
        "label": "Network Switch",
        "description": "Layer-2 switch (optionally PoE) without WiFi or NAT.",
        "features": {
            "wifi": False,
            "firewall": False,
            "dhcp": False,
            "switch": True,
            "poe": True,
        },
    },
    {
        "device_type": "firewall",
        "label": "Firewall Appliance",
        "description": "Dedicated firewall appliance with deep packet control.",
        "features": {
            "wifi": False,
            "firewall": True,
            "dhcp": False,
            "ids": True,
            "vpn": True,
        },
    },
]

_TEMPLATE_MAP = {entry["device_type"]: entry for entry in DEVICE_TEMPLATES}
VALID_TEMPLATE_TYPES = tuple(_TEMPLATE_MAP.keys())


def list_device_templates() -> List[Dict[str, Any]]:
    """Return a copy of all available device templates."""
    return [entry.copy() for entry in DEVICE_TEMPLATES]


def get_device_template(device_type: str) -> Dict[str, Any] | None:
    """Return metadata for the given device_type, or None if unknown."""
    template = _TEMPLATE_MAP.get(device_type)
    return template.copy() if template else None
