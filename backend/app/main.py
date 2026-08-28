from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.database import AsyncSessionLocal, engine
from app.models import Base, Company, Customer, Driver, User, Vehicle
from app.routers.stt import router as stt_router
from app.routers.trip_drafts import router as trip_drafts_router
from app.routers.whatsapp import router as whatsapp_router

PRIVACY_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Freight AI Privacy Policy</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;line-height:1.5;color:#222}
h1{font-size:1.6rem}h2{font-size:1.15rem;margin-top:1.5rem}</style></head>
<body>
<h1>Freight AI — Privacy Policy</h1>
<p>Last updated: 28 August 2026</p>
<p>Freight AI Automation ("we") provides WhatsApp-assisted trip creation tools for transporters.</p>
<h2>Data we process</h2>
<ul>
<li>WhatsApp phone numbers of authorized dispatchers</li>
<li>Message content used to create freight trip drafts (origin, destination, vehicle, driver, customer, freight amount)</li>
<li>Technical logs needed to operate and secure the service</li>
</ul>
<h2>How we use data</h2>
<p>Data is used only to extract trip details, show a confirmation to the dispatcher, and create the trip record after human approval. We do not sell personal data.</p>
<h2>Storage</h2>
<p>Trip drafts, trips, and message event IDs are stored in our database for operational use and auditability.</p>
<h2>Sharing</h2>
<p>We use Meta WhatsApp Cloud API to receive and send messages, and may use OpenAI for text/voice understanding when configured. Providers process data under their terms to deliver the service.</p>
<h2>Contact</h2>
<p>For privacy questions, contact the app admin at the business WhatsApp number configured for this pilot.</p>
</body></html>
"""


async def seed_demo_data() -> None:
    async with AsyncSessionLocal() as session:
        existing = await session.execute(select(Company).limit(1))
        if existing.scalar_one_or_none():
            return

        company = Company(
            name="Demo Transport Co",
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

        session.add(
            User(
                company_id=company.id,
                phone="917206611897",
                name="Naman Malhan",
                role="owner",
            )
        )
        session.add(Vehicle(company_id=company.id, registration_no="HR55AB1234"))
        session.add(Driver(company_id=company.id, name="Rakesh"))
        session.add(Customer(company_id=company.id, name="ABC", aliases=["ABC party"]))
        await session.commit()


def create_app(*, enable_lifespan: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await seed_demo_data()
        yield
        await engine.dispose()

    app = FastAPI(
        title="Freight AI — Flow #1",
        description="WhatsApp trip creation with human confirmation",
        version="1.0.0",
        lifespan=lifespan if enable_lifespan else None,
    )
    app.include_router(trip_drafts_router)
    app.include_router(whatsapp_router)
    app.include_router(stt_router)

    @app.get("/health")
    async def health():
        return {"status": "ok", "flow": "whatsapp-trip-creation"}

    @app.get("/privacy", response_class=HTMLResponse)
    async def privacy_policy():
        """Public page for Meta App Review / Live mode privacy policy URL."""
        return PRIVACY_HTML

    @app.get("/data-deletion", response_class=HTMLResponse)
    async def data_deletion():
        """Public page for Meta 'User data deletion' URL requirement."""
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Freight AI Data Deletion</title>
<style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;line-height:1.5}</style>
</head><body>
<h1>User Data Deletion</h1>
<p>To request deletion of WhatsApp / trip data associated with your phone number, email the app admin with your WhatsApp number (country code included).</p>
<p>We will delete trip drafts, trips, and message event records linked to that number within 30 days, except where retention is required for legal/audit reasons.</p>
</body></html>"""

    return app


app = create_app()
