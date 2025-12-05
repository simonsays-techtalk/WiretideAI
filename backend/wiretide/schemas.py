"""Pydantic/SQLModel schemas for API I/O."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field as PydanticField


class RegisterRequest(BaseModel):
    hostname: str
    description: Optional[str] = None
    device_type: Optional[str] = "unknown"
    ssh_enabled: bool = False
    ssh_fingerprint: Optional[str] = None
    agent_version: Optional[str] = None
    device_id: Optional[int] = PydanticField(
        default=None, description="Existing device_id if known; otherwise a new device is created."
    )
    ip_address: Optional[str] = PydanticField(default=None, description="Last known IP for this device.")


class RegisterResponse(BaseModel):
    device_id: int
    status: str
    approved: bool
    device_type: str
    shared_token_required: bool = True


class StatusReport(BaseModel):
    device_id: int
    dns_ok: Optional[bool] = None
    ntp_ok: Optional[bool] = None
    firewall_profile_active: Optional[str] = None
    security_log_samples: Optional[Dict[str, Any]] = None
    clients: Optional[List[Dict[str, Any]]] = None
    ssh_enabled: Optional[bool] = None
    ssh_fingerprint: Optional[str] = None
    agent_version: Optional[str] = None


class StatusResponse(BaseModel):
    status: str = "ok"
    last_seen: datetime


class ConfigRequest(BaseModel):
    device_id: int


class ConfigResponse(BaseModel):
    device_id: int
    package: str
    package_json: Dict[str, Any]
    sha256: str
    created_at: datetime


class QueueConfigRequest(BaseModel):
    device_id: int
    package: str
    package_json: Dict[str, Any]


class ApproveRequest(BaseModel):
    device_id: int
    device_type: str


class TokenResponse(BaseModel):
    shared_token: str


class DeviceStatusOut(BaseModel):
    dns_ok: Optional[bool] = None
    ntp_ok: Optional[bool] = None
    firewall_profile_active: Optional[str] = None
    security_log_samples: Optional[Dict[str, Any]] = None
    clients: Optional[List[Dict[str, Any]]] = None
    updated_at: Optional[datetime] = None


class DeviceOut(BaseModel):
    id: int
    hostname: str
    description: Optional[str] = None
    device_type: str
    status: str
    approved: bool
    last_seen: Optional[datetime] = None
    ssh_enabled: bool
    ssh_fingerprint: Optional[str] = None
    agent_version: Optional[str] = None
    agent_update_allowed: bool
    ip_last: Optional[str] = None
    created_at: datetime
    status_row: Optional[DeviceStatusOut] = None


class DevicesListResponse(BaseModel):
    items: List[DeviceOut]
    total: int
    limit: int
    offset: int


class SettingsResponse(BaseModel):
    shared_token: str
    agent_update_policy: str
    agent_update_url: Optional[str] = None
    agent_min_version: Optional[str] = None
    monitoring_api_enabled: bool


class UpdatePolicyRequest(BaseModel):
    agent_update_policy: str
    agent_update_url: Optional[str] = None
    agent_min_version: Optional[str] = None


class MonitoringToggleRequest(BaseModel):
    monitoring_api_enabled: bool


class ClearConfigRequest(BaseModel):
    device_id: int
