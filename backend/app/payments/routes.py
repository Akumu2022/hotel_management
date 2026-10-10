"""Daraja callbacks. Secret path token + optional source-IP allowlist; always answer 200 fast."""

import hmac

from fastapi import APIRouter, Request

from app.api.deps import Session
from app.core.errors import not_found
from app.payments import balance, collection, payouts
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
    if await collection.handle_stk_callback(session, body):
        from app.payments import hook

        req = await collection.request_for(session, body)
        if req is not None and req.status == "success":
            await hook.mark_order_paid(session, req.order_ref)
        elif req is not None and req.status == "review":
            await hook.stk_needs_review(session, req)
    await session.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/{token}/b2c/result")
async def b2c_result(token: str, request: Request, session: Session):
    if not _allowed(request, token):
        raise not_found()
    await payouts.handle_result(session, await request.json())
    await session.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/{token}/b2c/timeout")
async def b2c_timeout(token: str, request: Request, session: Session):
    if not _allowed(request, token):
        raise not_found()
    await payouts.handle_timeout(session, await request.json())
    await session.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/{token}/balance/result")
async def balance_result(token: str, request: Request, session: Session):
    if not _allowed(request, token):
        raise not_found()
    amount = balance.parse(await request.json())
    if amount is not None:
        balance.record(amount)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/{token}/balance/timeout")
async def balance_timeout(token: str, request: Request):
    if not _allowed(request, token):
        raise not_found()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/{token}/status/result")
async def status_result(token: str, request: Request, session: Session):
    if not _allowed(request, token):
        raise not_found()
    await payouts.handle_status_result(session, await request.json())
    await session.commit()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}


@router.post("/{token}/status/timeout")
async def status_timeout(token: str, request: Request):
    if not _allowed(request, token):
        raise not_found()
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
