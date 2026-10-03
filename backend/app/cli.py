"""Admin commands.

    python -m app.cli create-superadmin --name "Jane" --phone 0712345678
(the password is prompted, or read from SUPERADMIN_PASSWORD when not interactive)
"""

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.phone import normalize_phone
from app.core.security import hash_password
from app.models import User
from app.services import audit


async def create_superadmin(name: str, phone: str, password: str) -> None:
    phone = normalize_phone(phone)
    async with SessionLocal() as session:
        existing = await session.execute(select(User).where(User.phone == phone))
        if existing.scalar_one_or_none() is not None:
            sys.exit(f"A user with phone {phone} already exists")
        user = User(
            role="super_admin", name=name, phone=phone, password_hash=hash_password(password)
        )
        session.add(user)
        await session.flush()
        await audit.log(
            session,
            actor_id=None,
            action="user.create",
            target_type="user",
            target_id=user.id,
            details={"role": "super_admin", "via": "cli"},
        )
        await session.commit()
    print(f"Created super admin {name} ({phone})")


async def _seed_demo() -> None:
    from app.demo import STAFF_PASSWORD, seed

    async with SessionLocal() as session:
        created = await seed(session)
    print(f"Created: {', '.join(created) or 'nothing (already seeded)'}")
    print(
        "Hotel admin logins: Noor Cafe 0722000101, Jadelica 0722000202, Sawan 0722000303,"
        f" The Hood 0722222222, Siri-Tamu 0722000505, Tuutis 0722000606; password {STAFF_PASSWORD}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-superadmin")
    p.add_argument("--name", required=True)
    p.add_argument("--phone", required=True)
    sub.add_parser("seed-demo", help="Demo hotels and menus for local testing")
    args = parser.parse_args()

    if args.command == "seed-demo":
        asyncio.run(_seed_demo())
        return

    if args.command == "create-superadmin":
        password = os.environ.get("SUPERADMIN_PASSWORD") or getpass.getpass("Password: ")
        if len(password) < 8:
            sys.exit("Password must be at least 8 characters")
        asyncio.run(create_superadmin(args.name, args.phone, password))


if __name__ == "__main__":
    main()
