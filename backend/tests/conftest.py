import asyncio
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import create_app
from app.models import Company, Customer, Driver, User, Vehicle

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
test_app = create_app(enable_lifespan=False)


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as session:
        company = Company(
            name="Test Co",
            timezone="Asia/Kolkata",
            required_fields_config={
                "origin": True,
                "destination": True,
                "pickup_date": True,
                "pickup_window": False,
                "customer_name": True,
                "freight_amount": True,
                "vehicle_number": False,
                "driver_name": False,
            },
        )
        session.add(company)
        await session.flush()
        session.add(User(company_id=company.id, phone="919876543210", name="Owner", role="owner"))
        session.add(Vehicle(company_id=company.id, registration_no="HR55AB1234"))
        session.add(Driver(company_id=company.id, name="Rakesh"))
        session.add(Customer(company_id=company.id, name="ABC", aliases=["ABC party"]))
        await session.commit()

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    test_app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    test_app.dependency_overrides.clear()
