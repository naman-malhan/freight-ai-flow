from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Customer, Driver, User, Vehicle


async def get_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    normalized = phone.strip().lstrip("+")
    result = await db.execute(select(User).where(User.phone == normalized, User.active.is_(True)))
    return result.scalar_one_or_none()


async def get_company(db: AsyncSession, company_id: int) -> Company | None:
    result = await db.execute(select(Company).where(Company.id == company_id))
    return result.scalar_one_or_none()


async def match_vehicle(db: AsyncSession, company_id: int, registration_no: str | None) -> Vehicle | None:
    if not registration_no:
        return None
    result = await db.execute(
        select(Vehicle).where(
            Vehicle.company_id == company_id,
            Vehicle.registration_no == registration_no,
            Vehicle.active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def match_driver(db: AsyncSession, company_id: int, name: str | None) -> Driver | None:
    if not name:
        return None
    result = await db.execute(
        select(Driver).where(
            Driver.company_id == company_id,
            Driver.name.ilike(name.strip()),
            Driver.active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def match_customer(db: AsyncSession, company_id: int, name: str | None) -> Customer | None:
    if not name:
        return None
    result = await db.execute(
        select(Customer).where(
            Customer.company_id == company_id,
            Customer.name.ilike(name.strip()),
        )
    )
    customer = result.scalar_one_or_none()
    if customer:
        return customer

    result = await db.execute(select(Customer).where(Customer.company_id == company_id))
    for candidate in result.scalars():
        aliases = candidate.aliases or []
        if any(alias.lower() == name.lower() for alias in aliases):
            return candidate
    return None
