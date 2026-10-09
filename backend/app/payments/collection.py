"""STK Push collection: request, callback, query fallback. Money in goes to the one Paybill."""

from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments import outbox
from app.payments.adapter import ProviderError
from app.payments.config import get_payments_config
from app.payments.models import RawCallback, StkRequest
from app.payments.provider import get_provider


def callback_url() -> str:
    cfg = get_payments_config()
    base = cfg.daraja_callback_base.rstrip("/")
    return f"{base}/api/v1/payments/daraja/{cfg.daraja_callback_token}/stk"


async def start_stk(
    session: AsyncSession,
    *,
    order_ref: str,
    phone: str,
    amount: int,
    rider_fee: int = 0,
    hotel_id=None,
    hotel_share: int = 0,
    platform_fee: int = 0,
    provider=None,
) -> StkRequest:
    """One STK attempt for an order. A second attempt while one is live or paid is refused."""
    live = await session.scalar(
        select(StkRequest.id).where(
            StkRequest.order_ref == order_ref,
            StkRequest.status.in_(("created", "sent", "success")),
        )
    )
    if live:
        raise ValueError("a payment for this order is already in progress or done")
    req = StkRequest(
        order_ref=order_ref,
        phone=phone,
        amount=amount,
        rider_fee=rider_fee,
        hotel_id=hotel_id,
        hotel_share=hotel_share,
        platform_fee=platform_fee,
        status="created",
    )
    session.add(req)
    await session.flush()
    try:
        ok = await (provider or get_provider()).collect(
            phone=phone, amount=amount, account_ref=order_ref, callback_url=callback_url()
        )
    except ProviderError as e:
        req.status, req.result_desc = "failed", str(e)[:300]
        outbox.publish(
            session, "payment.failed", {"order_ref": order_ref, "reason": req.result_desc}
        )
    else:
        req.status = "sent"
        req.checkout_request_id = ok.checkout_request_id
        req.merchant_request_id = ok.merchant_request_id
    await session.flush()
    return req


async def store_callback(session: AsyncSession, kind: str, external_id: str, body: dict) -> bool:
    """Store the raw body once. False = duplicate (already stored)."""
    res = await session.execute(
        insert(RawCallback)
        .values(kind=kind, external_id=external_id, body=body)
        .on_conflict_do_nothing(index_elements=["kind", "external_id"])
        .returning(RawCallback.id)
    )
    return res.scalar() is not None


async def _settle(
    session: AsyncSession,
    checkout_id: str,
    code: int,
    desc: str,
    receipt: str | None,
    amount: int | None,
) -> bool:
    """Apply a result to a still-'sent' request, exactly once (row lock + conditional update)."""
    req = await session.scalar(
        select(StkRequest).where(StkRequest.checkout_request_id == checkout_id).with_for_update()
    )
    if req is None or req.status != "sent":
        return False
    if code == 0:
        # Wrong amount or no receipt: a person looks at it; nothing is auto-confirmed.
        bad = (amount is not None and amount != req.amount) or not receipt
        status = "review" if bad else "success"
    else:
        status = "cancelled" if code == 1032 else "failed"
    res = await session.execute(
        update(StkRequest)
        .where(StkRequest.id == req.id, StkRequest.status == "sent")
        .values(
            status=status,
            result_code=code,
            result_desc=desc[:300],
            receipt=receipt,
            updated_at=datetime.now(UTC),
        )
    )
    if res.rowcount != 1:
        return False
    if status == "success":
        # The money is now in the Paybill: hold each part of it against this order.
        from app.payments import service

        await service.request_collection(
            session,
            req.order_ref,
            req.rider_fee,
            hotel_id=req.hotel_id,
            hotel_share=req.hotel_share,
            platform_fee=req.platform_fee,
        )
    outbox.publish(
        session,
        "payment.confirmed" if status == "success" else "payment.failed",
        {"order_ref": req.order_ref, "amount": req.amount, "receipt": receipt, "status": status},
    )
    await session.flush()
    return True


async def handle_stk_callback(session: AsyncSession, body: dict) -> bool:
    """Daraja's STK result. Stores the raw body, then processes it. Duplicates are no-ops."""
    cb = body.get("Body", {}).get("stkCallback", {})
    checkout_id = cb.get("CheckoutRequestID")
    if not checkout_id:
        return False
    if not await store_callback(session, "stk", checkout_id, body):
        return False
    items = {i["Name"]: i.get("Value") for i in cb.get("CallbackMetadata", {}).get("Item", [])}
    amount = items.get("Amount")
    done = await _settle(
        session,
        checkout_id,
        int(cb.get("ResultCode", -1)),
        cb.get("ResultDesc", ""),
        items.get("MpesaReceiptNumber"),
        int(amount) if amount is not None else None,
    )
    await session.execute(
        update(RawCallback)
        .where(RawCallback.kind == "stk", RawCallback.external_id == checkout_id)
        .values(processed_at=datetime.now(UTC))
    )
    return done


async def query_stuck(session: AsyncSession, order_ref: str, provider=None) -> bool:
    """No callback in time: ask Daraja (STK Query) and settle from the answer. A success found
    this way has no receipt, so it goes to review rather than being auto-confirmed."""
    req = await session.scalar(
        select(StkRequest).where(StkRequest.order_ref == order_ref, StkRequest.status == "sent")
    )
    if req is None:
        return False
    st = await (provider or get_provider()).query_collection(req.checkout_request_id)
    if st.result_code is None:
        return False
    return await _settle(
        session, req.checkout_request_id, st.result_code, st.result_desc, st.receipt, None
    )
