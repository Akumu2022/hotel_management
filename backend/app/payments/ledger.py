"""Append-only wallet ledger. Idempotent: a repeated idem_key is a no-op, never a double credit."""

import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.payments.models import WalletEntry


class InsufficientFunds(Exception):
    pass


async def lock_party(session: AsyncSession, party_type: str, party_id: uuid.UUID | None) -> None:
    """Serialise movements of one party's money until the transaction ends."""
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"),
        {"k": f"wallet:{party_type}:{party_id}"},
    )


async def balance(
    session: AsyncSession, party_type: str, party_id: uuid.UUID | None, bucket: str, *, shadow: bool
) -> int:
    q = select(func.coalesce(func.sum(WalletEntry.amount), 0)).where(
        WalletEntry.party_type == party_type,
        WalletEntry.bucket == bucket,
        WalletEntry.shadow == shadow,
        WalletEntry.party_id.is_(None) if party_id is None else WalletEntry.party_id == party_id,
    )
    return int(await session.scalar(q))


async def move(
    session: AsyncSession,
    *,
    idem_key: str,
    party_type: str,
    party_id: uuid.UUID | None,
    src: str | None,
    dst: str | None,
    amount: int,
    kind: str,
    order_ref: str | None,
    shadow: bool,
) -> bool:
    """Move `amount` from bucket `src` to `dst` (None = money entering/leaving the module).
    Returns False if this idem_key was already applied. Raises InsufficientFunds rather than
    let any bucket go negative."""
    if amount <= 0:
        raise ValueError("amount must be positive")
    await lock_party(session, party_type, party_id)
    keys = [f"{idem_key}:out", f"{idem_key}:in"]
    if await session.scalar(select(WalletEntry.id).where(WalletEntry.idem_key.in_(keys)).limit(1)):
        return False
    if src and await balance(session, party_type, party_id, src, shadow=shadow) < amount:
        raise InsufficientFunds(f"{party_type} {party_id} has less than {amount} in {src}")
    group = uuid.uuid4()
    legs = []
    if src:
        legs.append((src, -amount, keys[0]))
    if dst:
        legs.append((dst, amount, keys[1]))
    for bucket, signed, key in legs:
        session.add(
            WalletEntry(
                idem_key=key,
                group_id=group,
                party_type=party_type,
                party_id=party_id,
                bucket=bucket,
                amount=signed,
                kind=kind,
                order_ref=order_ref,
                shadow=shadow,
            )
        )
    await session.flush()
    return True
