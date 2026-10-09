"""Daraja callbacks. Secret path token + optional source-IP allowlist; always answer 200 fast."""

import hmac

from fastapi import APIRouter, Request

from app.api.deps import Session
from app.core.errors import not_found
from app.payments import collection
from app.payments.config import get_payments_config

router = APIRouter(prefix="/payments/daraja", tags=["payments"])


def _allowed(request: Request, token: str) -> bool:
    cfg = get_payments_config()
    if not cfg.payments_enabled or not cfg.daraja_callback_token:
        return False
    if not hmac.compare_digest(token, cfg.daraja_callback_token):
        return False
    ips = [i.strip() for i in cfg.daraja_allowed_ips.split(",") if i.strip()]
    return not ips or (request.client is not None and request.client.host in ips)


@router.post("/{token}/stk")
async def stk_callback(token: str, request: Request, session: Session):
    if not _allowed(request, token):
        raise not_found()
    body = await request.json()
    await collection.handle_stk_callback(session, body)
    await session.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
