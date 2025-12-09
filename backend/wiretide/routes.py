"""API routes for device/agent flows."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Sequence

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status, Form
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import delete, func
from sqlmodel import Session, select

from .config import get_settings
from .db import get_session
from .models import ControllerSettings, Device, DeviceConfig, DeviceStatus
from .auth import (
    parse_basic_credentials,
    validate_session_token,
    verify_password,
    hash_password,
)
from .device_templates import (
    UNKNOWN_DEVICE_TYPE,
    VALID_TEMPLATE_TYPES,
    get_device_template,
    list_device_templates,
)
from .schemas import (
    ApproveRequest,
    ChangePasswordRequest,
    ClearConfigRequest,
    ConfigResponse,
    DeviceOut,
    DeviceStatusOut,
    DevicesListResponse,
    DeviceTemplateInfo,
    QueueConfigRequest,
    RegisterRequest,
    RegisterResponse,
    SettingsResponse,
    StatusReport,
    StatusResponse,
    TokenResponse,
    UpdatePolicyRequest,
    MonitoringToggleRequest,
)
from .services import (
    ensure_settings_seeded,
    find_device_by_hostname,
    get_device,
    get_settings_row,
    refresh_shared_token,
)

router = APIRouter()
DEVICE_CONFIG_LIMIT = 10
VALID_DEVICE_TYPES = set(VALID_TEMPLATE_TYPES) | {UNKNOWN_DEVICE_TYPE}
VALID_STATUS = {"waiting", "approved", "blocked"}
ALLOWED_TRANSITIONS = {
    "waiting": {"approved", "blocked"},
    "approved": {"blocked"},
    "blocked": set(),
}


def _enforce_transition(current: str, target: str) -> None:
    if target not in VALID_STATUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid target status",
        )
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transition {current} -> {target} not allowed",
        )

# Optional templates for basic server-rendered UI.
try:
    from fastapi.templating import Jinja2Templates
except Exception:  # pragma: no cover
    Jinja2Templates = None
try:
    import jinja2  # type: ignore
except Exception:  # pragma: no cover
    jinja2 = None

_base_path = Path(__file__).resolve().parent
_templates_dir = (_base_path.parent / get_settings().templates_dir).resolve()
templates = (
    Jinja2Templates(directory=str(_templates_dir))
    if Jinja2Templates and jinja2 is not None
    else None
)


def require_agent_token(
    x_shared_token: Optional[str] = Header(default=None, alias="X-Shared-Token"),
    session: Session = Depends(get_session),
) -> ControllerSettings:
    settings = get_settings_row(session)
    if not x_shared_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing shared token",
        )
    if x_shared_token != settings.shared_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid shared token",
        )
    return settings


def require_admin_token(
    x_admin_token: Optional[str] = Header(default=None, alias="X-Admin-Token"),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    request: Request = None,
) -> None:
    settings = get_settings()
    password_hash = settings.admin_password_hash
    if password_hash:
        header_token = x_admin_token or authorization
        cookie_token = request.cookies.get(settings.admin_cookie_name) if request else None

        def _valid_session(token: Optional[str]) -> bool:
            if not token:
                return False
            return validate_session_token(token, settings.admin_username, password_hash)

        if header_token:
            creds = parse_basic_credentials(header_token)
            if creds and creds[0] == settings.admin_username and verify_password(creds[1], password_hash):
                return
            if _valid_session(header_token):
                return
        if _valid_session(cookie_token):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin credentials",
        )
    if settings.admin_token is None:
        return
    cookie_token = request.cookies.get(settings.admin_cookie_name) if request else None
    token = x_admin_token or cookie_token
    if not token or token != settings.admin_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing admin token",
        )

def _persist_admin_hash(new_hash: str, settings) -> None:
    """Attempt to persist the new admin hash to the env file if writable."""
    if not settings.admin_env_path:
        return
    env_path = Path(settings.admin_env_path)
    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = env_path.with_suffix(".tmp")
        content = (
            f"WIRETIDE_ADMIN_USERNAME={settings.admin_username}\n"
            f"WIRETIDE_ADMIN_PASSWORD_HASH={new_hash}\n"
            "WIRETIDE_ADMIN_TOKEN=\n"
        )
        tmp_path.write_text(content)
        tmp_path.chmod(0o600)
        tmp_path.replace(env_path)
    except Exception as exc:  # pragma: no cover - best-effort persistence
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist new password hash: {exc}",
        )


def _serialize_device(device: Device, status_row: Optional[DeviceStatus]) -> DeviceOut:
    template_data = get_device_template(device.device_type)
    template_info = DeviceTemplateInfo(**template_data) if template_data else None
    return DeviceOut(
        id=device.id,
        hostname=device.hostname,
        description=device.description,
        device_type=device.device_type,
        status=device.status,
        approved=device.approved,
        last_seen=device.last_seen,
        ssh_enabled=device.ssh_enabled,
        ssh_fingerprint=device.ssh_fingerprint,
        agent_version=device.agent_version,
        agent_update_allowed=device.agent_update_allowed,
        ip_last=device.ip_last,
        created_at=device.created_at,
        template=template_info,
        status_row=DeviceStatusOut(
            dns_ok=status_row.dns_ok if status_row else None,
            ntp_ok=status_row.ntp_ok if status_row else None,
            firewall_profile_active=status_row.firewall_profile_active if status_row else None,
            security_log_samples=status_row.security_log_samples if status_row else None,
            clients=status_row.clients if status_row else None,
            updated_at=status_row.updated_at if status_row else None,
        )
        if status_row
        else None,
    )


@router.post("/register", response_model=RegisterResponse)
def register_device(
    payload: RegisterRequest,
    session: Session = Depends(get_session),
    _: ControllerSettings = Depends(require_agent_token),
) -> RegisterResponse:
    if payload.device_type and payload.device_type not in VALID_DEVICE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid device_type",
        )
    if payload.device_type == "unknown" and payload.device_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device type cannot be reset to unknown",
        )
    now = datetime.now(timezone.utc)
    device: Optional[Device] = None

    if payload.device_id is not None:
        device = get_device(session, payload.device_id)
    else:
        device = find_device_by_hostname(session, payload.hostname)

    if device:
        device.hostname = payload.hostname
        device.description = payload.description
        device.device_type = payload.device_type or device.device_type
        device.ssh_enabled = payload.ssh_enabled
        device.ssh_fingerprint = payload.ssh_fingerprint
        device.agent_version = payload.agent_version
        device.ip_last = payload.ip_address or device.ip_last
        device.last_seen = now
    else:
        device = Device(
            hostname=payload.hostname,
            description=payload.description,
            device_type=payload.device_type or "unknown",
            status="waiting",
            approved=False,
            ssh_enabled=payload.ssh_enabled,
            ssh_fingerprint=payload.ssh_fingerprint,
            agent_version=payload.agent_version,
            ip_last=payload.ip_address,
            last_seen=now,
        )
    session.add(device)
    session.commit()
    session.refresh(device)

    return RegisterResponse(
        device_id=device.id,
        status=device.status,
        approved=device.approved,
        device_type=device.device_type,
        shared_token_required=True,
    )


@router.post("/status", response_model=StatusResponse)
def update_status(
    payload: StatusReport,
    session: Session = Depends(get_session),
    _: ControllerSettings = Depends(require_agent_token),
) -> StatusResponse:
    now = datetime.now(timezone.utc)
    device = get_device(session, payload.device_id)

    # Upsert device fields that may change with status.
    if payload.ssh_enabled is not None:
        device.ssh_enabled = payload.ssh_enabled
    if payload.ssh_fingerprint:
        device.ssh_fingerprint = payload.ssh_fingerprint
    if payload.agent_version:
        device.agent_version = payload.agent_version
    device.last_seen = now
    session.add(device)

    existing_status = (
        session.exec(
            select(DeviceStatus).where(DeviceStatus.device_id == payload.device_id)
        ).first()
    )
    if existing_status:
        status_row = existing_status
    else:
        status_row = DeviceStatus(device_id=payload.device_id)

    if payload.dns_ok is not None:
        status_row.dns_ok = payload.dns_ok
    if payload.ntp_ok is not None:
        status_row.ntp_ok = payload.ntp_ok
    status_row.firewall_profile_active = payload.firewall_profile_active
    status_row.security_log_samples = payload.security_log_samples
    status_row.clients = payload.clients
    status_row.updated_at = now
    session.add(status_row)
    session.commit()

    return StatusResponse(last_seen=device.last_seen)


@router.get("/config", response_model=ConfigResponse)
def get_config(
    device_id: int,
    session: Session = Depends(get_session),
    _: ControllerSettings = Depends(require_agent_token),
) -> ConfigResponse:
    device = get_device(session, device_id)
    if not device.approved or device.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Device not approved",
        )

    statement = (
        select(DeviceConfig)
        .where(DeviceConfig.device_id == device_id)
        .order_by(DeviceConfig.created_at.desc())
    )
    config_row = session.exec(statement).first()
    if not config_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No pending config",
        )
    response = ConfigResponse(
        device_id=device.id,
        package=config_row.package,
        package_json=config_row.package_json,
        sha256=config_row.sha256,
        created_at=config_row.created_at,
    )
    # Pop the latest config once served to avoid re-delivery.
    session.delete(config_row)
    session.commit()
    return response


@router.get("/token/current", response_model=TokenResponse)
def current_token(session: Session = Depends(get_session)) -> TokenResponse:
    settings = ensure_settings_seeded(session)
    return TokenResponse(shared_token=settings.shared_token)


@router.get("/api/device-templates", response_model=List[DeviceTemplateInfo])
def list_device_templates_route(
    _: None = Depends(require_admin_token),
) -> List[DeviceTemplateInfo]:
    return list_device_templates()


@router.patch("/api/settings/monitoring", response_model=SettingsResponse)
def toggle_monitoring(
    payload: MonitoringToggleRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> SettingsResponse:
    settings = get_settings_row(session)
    settings.monitoring_api_enabled = payload.monitoring_api_enabled
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return SettingsResponse(
        shared_token=settings.shared_token,
        agent_update_policy=settings.agent_update_policy,
        agent_update_url=settings.agent_update_url,
        agent_min_version=settings.agent_min_version,
        monitoring_api_enabled=settings.monitoring_api_enabled,
        admin_username=get_settings().admin_username,
    )


@router.get("/api/settings", response_model=SettingsResponse)
def get_settings_view(
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> SettingsResponse:
    settings = ensure_settings_seeded(session)
    return SettingsResponse(
        shared_token=settings.shared_token,
        agent_update_policy=settings.agent_update_policy,
        agent_update_url=settings.agent_update_url,
        agent_min_version=settings.agent_min_version,
        monitoring_api_enabled=settings.monitoring_api_enabled,
        admin_username=get_settings().admin_username,
    )


@router.post("/api/settings/token/regenerate", response_model=TokenResponse)
def regenerate_shared_token(
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> TokenResponse:
    settings = refresh_shared_token(session)
    return TokenResponse(shared_token=settings.shared_token)


@router.patch("/api/settings/agent-update", response_model=SettingsResponse)
def update_agent_policy(
    payload: UpdatePolicyRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> SettingsResponse:
    if payload.agent_update_policy not in {"off", "per_device", "force_on"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid agent_update_policy",
        )
    settings = get_settings_row(session)
    settings.agent_update_policy = payload.agent_update_policy
    settings.agent_update_url = payload.agent_update_url
    settings.agent_min_version = payload.agent_min_version
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return SettingsResponse(
        shared_token=settings.shared_token,
        agent_update_policy=settings.agent_update_policy,
        agent_update_url=settings.agent_update_url,
        agent_min_version=settings.agent_min_version,
        monitoring_api_enabled=settings.monitoring_api_enabled,
        admin_username=get_settings().admin_username,
    )


@router.get("/api/devices", response_model=DevicesListResponse)
def list_devices(
    device_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> DevicesListResponse:
    if device_type and device_type not in VALID_DEVICE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid device_type filter",
        )
    if status and status not in VALID_STATUS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid status filter",
        )

    stmt = select(Device)
    if device_type:
        stmt = stmt.where(Device.device_type == device_type)
    if status:
        stmt = stmt.where(Device.status == status)
    if search:
        stmt = stmt.where(Device.hostname.contains(search))
    limited = stmt.offset(offset).limit(min(limit, 200))

    devices: Sequence[Device] = session.exec(limited).all()
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    device_ids = [d.id for d in devices]
    status_rows = (
        session.exec(
            select(DeviceStatus).where(DeviceStatus.device_id.in_(device_ids))
        ).all()
        if device_ids
        else []
    )
    status_map = {row.device_id: row for row in status_rows}
    items = [_serialize_device(dev, status_map.get(dev.id)) for dev in devices]
    return DevicesListResponse(items=items, total=total, limit=min(limit, 200), offset=offset)


@router.get("/api/devices/{device_id}", response_model=DeviceOut)
def get_device_detail(
    device_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> DeviceOut:
    device = get_device(session, device_id)
    status_row = (
        session.exec(
            select(DeviceStatus).where(DeviceStatus.device_id == device_id)
        ).first()
    )
    return _serialize_device(device, status_row)


@router.get("/devices", response_class=HTMLResponse)
def devices_page(
    request: Request,
    device_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
):
    if not templates:
        return HTMLResponse(
            content="Templates not available; ensure Jinja2 is installed.",
            status_code=501,
        )
    if device_type and device_type not in VALID_DEVICE_TYPES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid device_type filter")
    if status and status not in VALID_STATUS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status filter")

    stmt = select(Device)
    if device_type:
        stmt = stmt.where(Device.device_type == device_type)
    if status:
        stmt = stmt.where(Device.status == status)
    if search:
        stmt = stmt.where(Device.hostname.contains(search))
    limited = stmt.offset(offset).limit(min(limit, 200))

    devices = session.exec(limited).all()
    total = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    device_ids = [d.id for d in devices]
    status_rows = (
        session.exec(
            select(DeviceStatus).where(DeviceStatus.device_id.in_(device_ids))
        ).all()
        if device_ids
        else []
    )
    status_map = {row.device_id: row for row in status_rows}
    items = [_serialize_device(dev, status_map.get(dev.id)) for dev in devices]

    return templates.TemplateResponse(
        "devices.html",
        {
            "request": request,
            "items": items,
            "total": total,
            "limit": min(limit, 200),
            "offset": offset,
            "filters": {"device_type": device_type, "status": status, "search": search},
            "admin_session": True,
            "admin_username": get_settings().admin_username,
            "device_templates": list_device_templates(),
            "admin_has_password": bool(get_settings().admin_password_hash),
        },
    )


@router.get("/clients", response_class=HTMLResponse)
def clients_page(
    request: Request,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
):
    if not templates:
        return HTMLResponse(
            content="Templates not available; ensure Jinja2 is installed.",
            status_code=501,
        )
    devices = session.exec(select(Device)).all()
    device_map = {d.id: d for d in devices}
    statuses = session.exec(select(DeviceStatus)).all()

    clients_by_mac = {}
    for status_row in statuses:
        if not status_row.clients:
            continue
        device = device_map.get(status_row.device_id)
        for entry in status_row.clients:
            mac = (entry.get("mac") or "").lower()
            key = mac or f"row-{status_row.device_id}-{len(clients_by_mac)}"
            record = {
                "mac": mac or entry.get("host") or entry.get("hostname") or "unknown",
                "ip": entry.get("ip"),
                "host": entry.get("host") or entry.get("hostname"),
                "connection": "wifi" if entry.get("iface") or entry.get("ssid") else "lan",
                "ssid": entry.get("ssid"),
                "band": entry.get("band"),
                "device_name": device.hostname if device else f"device-{status_row.device_id}",
                "device_id": status_row.device_id,
                "updated_at": status_row.updated_at,
            }
            existing = clients_by_mac.get(key)
            if existing and existing.get("updated_at") and status_row.updated_at:
                if existing["updated_at"] >= status_row.updated_at:
                    continue
            clients_by_mac[key] = record

    rows = list(clients_by_mac.values())
    rows.sort(key=lambda r: (r.get("host") or r.get("mac") or "").lower())

    return templates.TemplateResponse(
        "clients.html",
        {
            "request": request,
            "clients": rows,
            "admin_session": True,
            "admin_username": get_settings().admin_username,
            "admin_has_password": bool(get_settings().admin_password_hash),
        },
    )


@router.post("/api/devices/approve", response_model=RegisterResponse)
def approve_device(
    payload: ApproveRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> RegisterResponse:
    if payload.device_type not in VALID_DEVICE_TYPES or payload.device_type == "unknown":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device type must be valid and not 'unknown' before approval",
        )
    device = get_device(session, payload.device_id)
    _enforce_transition(device.status, "approved")
    if not device.ssh_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device not reachable via SSH; approval blocked",
        )

    device.device_type = payload.device_type
    device.status = "approved"
    device.approved = True
    session.add(device)

    # Regenerate shared token to force agents to fetch a fresh token.
    refresh_shared_token(session)

    session.commit()
    session.refresh(device)
    return RegisterResponse(
        device_id=device.id,
        status=device.status,
        approved=device.approved,
        device_type=device.device_type,
        shared_token_required=True,
    )


@router.post("/api/devices/block", response_model=DeviceOut)
def block_device(
    device_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> DeviceOut:
    device = get_device(session, device_id)
    _enforce_transition(device.status, "blocked")
    device.status = "blocked"
    device.approved = False
    session.add(device)
    session.commit()
    status_row = (
        session.exec(select(DeviceStatus).where(DeviceStatus.device_id == device_id)).first()
    )
    return _serialize_device(device, status_row)


@router.delete("/api/devices/{device_id}")
def remove_device(
    device_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> dict:
    device = get_device(session, device_id)
    session.exec(delete(DeviceStatus).where(DeviceStatus.device_id == device_id))
    session.exec(delete(DeviceConfig).where(DeviceConfig.device_id == device_id))
    session.delete(device)
    session.commit()
    return {"removed": device_id}


@router.post("/api/queue-config", response_model=ConfigResponse)
def queue_config(
    payload: QueueConfigRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> ConfigResponse:
    device = get_device(session, payload.device_id)
    if not device.approved or device.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Device must be approved before queuing config",
        )

    # Enforce per-device limit by trimming oldest items.
    existing = (
        session.exec(
            select(DeviceConfig)
            .where(DeviceConfig.device_id == payload.device_id)
            .order_by(DeviceConfig.created_at.asc())
        ).all()
        or []
    )
    while len(existing) >= DEVICE_CONFIG_LIMIT:
        oldest = existing.pop(0)
        session.delete(oldest)

    canonical_json = json.dumps(payload.package_json, sort_keys=True, separators=(",", ":"))
    sha256 = hashlib.sha256(canonical_json.encode()).hexdigest()

    config_entry = DeviceConfig(
        device_id=payload.device_id,
        package=payload.package,
        package_json=payload.package_json,
        sha256=sha256,
    )
    session.add(config_entry)
    session.commit()
    session.refresh(config_entry)

    return ConfigResponse(
        device_id=config_entry.device_id,
        package=config_entry.package,
        package_json=config_entry.package_json,
        sha256=config_entry.sha256,
        created_at=config_entry.created_at,
    )


@router.post("/api/configs/clear")
def clear_configs(
    payload: ClearConfigRequest,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
) -> dict:
    get_device(session, payload.device_id)  # ensure device exists
    deleted = session.exec(
        select(DeviceConfig.id).where(DeviceConfig.device_id == payload.device_id)
    ).all()
    session.exec(delete(DeviceConfig).where(DeviceConfig.device_id == payload.device_id))
    session.commit()
    return {"deleted": len(deleted)}


@router.post("/api/admin/password-change")
def change_admin_password(
    payload: ChangePasswordRequest,
    request: Request,
    _: None = Depends(require_admin_token),
) -> dict:
    settings = get_settings()
    if not settings.admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password auth not enabled; set WIRETIDE_ADMIN_PASSWORD_HASH to use this endpoint.",
        )
    if not verify_password(payload.current_password, settings.admin_password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )
    if len(payload.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )
    new_hash = hash_password(payload.new_password)
    # Update in-memory settings so the new password is effective immediately.
    settings.admin_password_hash = new_hash

    # Attempt to persist to env file when possible.
    _persist_admin_hash(new_hash, settings)
    return {"status": "ok"}
@router.get("/devices/{device_id}", response_class=HTMLResponse)
def device_detail_page(
    request: Request,
    device_id: int,
    session: Session = Depends(get_session),
    _: None = Depends(require_admin_token),
):
    if not templates:
        return HTMLResponse(
            content="Templates not available; ensure Jinja2 is installed.",
            status_code=501,
        )
    device = get_device(session, device_id)
    status_row = (
        session.exec(
            select(DeviceStatus).where(DeviceStatus.device_id == device_id)
        ).first()
    )
    serialized = _serialize_device(device, status_row)
    device_json = serialized.model_dump()
    device_json_str = json.dumps(device_json, default=str, indent=2)
    is_router_like = device.device_type in {"router", "firewall"}
    is_ap_like = device.device_type == "access_point"
    return templates.TemplateResponse(
        "device_detail.html",
        {
            "request": request,
            "device": serialized,
            "device_json": device_json,
            "device_json_str": device_json_str,
            "admin_session": True,
            "is_router_like": is_router_like,
            "is_ap_like": is_ap_like,
            "admin_username": get_settings().admin_username,
            "admin_has_password": bool(get_settings().admin_password_hash),
        },
    )
