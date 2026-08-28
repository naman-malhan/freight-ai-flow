from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import DraftStatus, MessageDirection


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    # Which fields are required beyond MVP minimum
    required_fields_config: Mapped[dict] = mapped_column(
        JSON,
        default=lambda: {
            "origin": True,
            "destination": True,
            "pickup_date": True,
            "pickup_window": True,
            "customer_name": True,
            "freight_amount": True,
            "vehicle_number": False,
            "driver_name": False,
        },
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    users: Mapped[list["User"]] = relationship(back_populates="company")
    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="company")
    drivers: Mapped[list["Driver"]] = relationship(back_populates="company")
    customers: Mapped[list["Customer"]] = relationship(back_populates="company")
    trip_drafts: Mapped[list["TripDraft"]] = relationship(back_populates="company")
    trips: Mapped[list["Trip"]] = relationship(back_populates="company")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="dispatcher")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="users")

    __table_args__ = (UniqueConstraint("company_id", "phone", name="uq_users_company_phone"),)


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    registration_no: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="vehicles")

    __table_args__ = (UniqueConstraint("company_id", "registration_no", name="uq_vehicles_company_reg"),)


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="drivers")


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="customers")


class TripDraft(Base):
    __tablename__ = "trip_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    fields_json: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[DraftStatus] = mapped_column(Enum(DraftStatus), default=DraftStatus.NEW)
    source_message_id: Mapped[str | None] = mapped_column(String(128), index=True)
    missing_fields: Mapped[list] = mapped_column(JSON, default=list)
    confidence_json: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    company: Mapped["Company"] = relationship(back_populates="trip_drafts")
    user: Mapped["User | None"] = relationship()
    trip: Mapped["Trip | None"] = relationship(back_populates="draft", uselist=False)


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    draft_id: Mapped[int] = mapped_column(ForeignKey("trip_drafts.id"), unique=True, nullable=False)
    origin: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    pickup_date: Mapped[str] = mapped_column(String(32), nullable=False)
    pickup_window: Mapped[str | None] = mapped_column(String(64))
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    freight_amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"))
    vehicle_number: Mapped[str | None] = mapped_column(String(32))
    driver_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    company: Mapped["Company"] = relationship(back_populates="trips")
    draft: Mapped["TripDraft"] = relationship(back_populates="trip")


class MessageEvent(Base):
    __tablename__ = "message_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    message_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    direction: Mapped[MessageDirection] = mapped_column(Enum(MessageDirection), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    draft_id: Mapped[int | None] = mapped_column(ForeignKey("trip_drafts.id"))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
