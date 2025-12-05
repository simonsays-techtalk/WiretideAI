"""Database models for the Wiretide backend."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, SQLModel


class Device(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    hostname: str
    description: Optional[str] = Field(default=None)
    device_type: str = Field(default="unknown", description="router|switch|firewall|access_point|unknown")
    status: str = Field(default="waiting", description="waiting|approved|blocked")
    approved: bool = Field(default=False)
    last_seen: Optional[datetime] = Field(default=None)
    ssh_enabled: bool = Field(default=False)
    ssh_fingerprint: Optional[str] = Field(default=None)
    agent_version: Optional[str] = Field(default=None)
    agent_update_allowed: bool = Field(default=False)
    ip_last: Optional[str] = Field(default=None, description="last known IP address")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeviceStatus(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id")
    dns_ok: bool = Field(default=False)
    ntp_ok: bool = Field(default=False)
    firewall_profile_active: Optional[str] = Field(default=None)
    security_log_samples: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    clients: Optional[List[Dict[str, Any]]] = Field(
        default=None, sa_column=Column(JSON)
    )
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DeviceConfig(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id")
    package: str
    package_json: Dict[str, Any] = Field(sa_column=Column(JSON))
    sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ControllerSettings(SQLModel, table=True):
    id: int = Field(default=1, primary_key=True)
    shared_token: str
    agent_update_policy: str = Field(default="off", description="off|per_device|force_on")
    agent_update_url: Optional[str] = Field(default=None)
    agent_min_version: Optional[str] = Field(default=None)
    monitoring_api_enabled: bool = Field(default=False)
    wifi_domain_config: Optional[Dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
