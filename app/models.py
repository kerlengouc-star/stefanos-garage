from sqlalchemy import Column, Integer, String, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import relationship

from .db import Base


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False, index=True)


class Visit(Base):
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, index=True)

    job_no = Column(String(100), nullable=True, index=True)

    date_in = Column(DateTime, nullable=True)
    date_out = Column(DateTime, nullable=True)

    plate_number = Column(String(50), nullable=True, index=True)
    vin = Column(String(80), nullable=True, index=True)

    customer_name = Column(String(200), nullable=True, index=True)
    phone = Column(String(80), nullable=True, index=True)
    email = Column(String(200), nullable=True, index=True)

    model = Column(String(200), nullable=True, index=True)
    km = Column(String(50), nullable=True)

    customer_complaint = Column(Text, nullable=True)
    notes_general = Column(Text, nullable=True)

    total_parts = Column(String(50), nullable=True)
    total_labor = Column(String(50), nullable=True)
    total_amount = Column(String(50), nullable=True)

    status = Column(String(50), nullable=True)

    lines = relationship(
        "VisitChecklistLine",
        back_populates="visit",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class VisitChecklistLine(Base):
    __tablename__ = "visit_checklist_lines"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id", ondelete="CASCADE"), nullable=False, index=True)

    category = Column(String(255), nullable=False, index=True)
    item_name = Column(String(255), nullable=False, index=True)

    # OK / CHECK / REPAIR
    result = Column(String(20), nullable=False, default="OK")

    notes = Column(Text, nullable=True)

    # ✅ Parts
    parts_code = Column(String(120), nullable=True)
    parts_qty = Column(Integer, nullable=False, default=0)

    # ✅ print/pdf exclude
    exclude_from_print = Column(Boolean, nullable=False, default=False)

    visit = relationship("Visit", back_populates="lines")
