"""Domain services for Wiretide backend."""

import secrets
from typing import Optional

from fastapi import HTTPException, status
from sqlmodel import Session, select

from .models import ControllerSettings, Device


def ensure_settings_seeded(session: Session) -> ControllerSettings:
    settings = session.get(ControllerSettings, 1)
    if settings is None:
        settings = ControllerSettings(
            id=1,
            shared_token=_generate_token(),
            agent_update_policy="off",
            monitoring_api_enabled=False,
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def get_settings_row(session: Session) -> ControllerSettings:
    settings = session.get(ControllerSettings, 1)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Controller settings not initialized",
        )
    return settings


def refresh_shared_token(session: Session) -> ControllerSettings:
    settings = get_settings_row(session)
    settings.shared_token = _generate_token()
    session.add(settings)
    session.commit()
    session.refresh(settings)
    return settings


def get_device(session: Session, device_id: int) -> Device:
    device = session.get(Device, device_id)
    if device is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    return device


def find_device_by_hostname(session: Session, hostname: str) -> Optional[Device]:
    statement = select(Device).where(Device.hostname == hostname)
    return session.exec(statement).first()


def _generate_token(length: int = 32) -> str:
    # token_urlsafe gives ~4/3 * n bytes; default yields ~43 chars.
    return secrets.token_urlsafe(length)
