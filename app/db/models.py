from datetime import datetime

from sqlalchemy import JSON, ForeignKey, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Install(Base):
    __tablename__ = "installs"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(default="hubspot")
    hub_id: Mapped[str] = mapped_column(unique=True, index=True)
    access_token: Mapped[str]
    access_token_expires_at: Mapped[datetime]
    refresh_token: Mapped[str]
    scopes: Mapped[str] = mapped_column(default="")
    status: Mapped[str] = mapped_column(default="active")  # active | needs_reauth | revoked
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class _CrmObjectColumns:
    """Shared columns for contacts/companies/deals (not a table itself)."""

    id: Mapped[int] = mapped_column(primary_key=True)
    install_id: Mapped[int] = mapped_column(ForeignKey("installs.id"))
    hubspot_object_id: Mapped[str]
    properties: Mapped[dict] = mapped_column(JSON, default=dict)
    hs_created_at: Mapped[datetime | None]
    hs_updated_at: Mapped[datetime | None]
    archived: Mapped[bool] = mapped_column(default=False)
    synced_at: Mapped[datetime]


class Contact(Base, _CrmObjectColumns):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("install_id", "hubspot_object_id"),)

    email: Mapped[str | None] = mapped_column(index=True)
    firstname: Mapped[str | None]
    lastname: Mapped[str | None]
    lifecyclestage: Mapped[str | None]


class Company(Base, _CrmObjectColumns):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("install_id", "hubspot_object_id"),)

    name: Mapped[str | None]
    domain: Mapped[str | None] = mapped_column(index=True)


class Deal(Base, _CrmObjectColumns):
    __tablename__ = "deals"
    __table_args__ = (UniqueConstraint("install_id", "hubspot_object_id"),)

    dealname: Mapped[str | None]
    dealstage: Mapped[str | None] = mapped_column(index=True)
    amount: Mapped[str | None]
    pipeline: Mapped[str | None]


class Association(Base):
    __tablename__ = "associations"

    id: Mapped[int] = mapped_column(primary_key=True)
    install_id: Mapped[int] = mapped_column(ForeignKey("installs.id"))
    from_object_type: Mapped[str]
    from_hubspot_id: Mapped[str]
    to_object_type: Mapped[str]
    to_hubspot_id: Mapped[str]


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    install_id: Mapped[int | None] = mapped_column(ForeignKey("installs.id"))
    provider: Mapped[str] = mapped_column(default="hubspot")
    event_id: Mapped[str]
    subscription_type: Mapped[str]
    object_type: Mapped[str | None]  # contacts | companies | deals — resolved by the adapter
    object_id: Mapped[str]
    occurred_at: Mapped[datetime]
    payload: Mapped[dict] = mapped_column(JSON)
    signature_valid: Mapped[bool]
    processed_at: Mapped[datetime | None]
    processing_error: Mapped[str | None]
    received_at: Mapped[datetime]


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    install_id: Mapped[int] = mapped_column(ForeignKey("installs.id"))
    object_type: Mapped[str]
    status: Mapped[str] = mapped_column(default="running")
    records_fetched: Mapped[int] = mapped_column(default=0)
    records_upserted: Mapped[int] = mapped_column(default=0)
    records_failed: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    error_summary: Mapped[list | None] = mapped_column(JSON, default=None)
