from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship

from .db import Base


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True, nullable=False)
    name = Column(String, index=True, nullable=False)

    # ✅ Μνήμη: default κωδικός εξαρτήματος για αυτό το item
    default_parts_code = Column(String, nullable=True)


class Visit(Base):
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, index=True)

    job_no = Column(String, nullable=True)

    date_in = Column(DateTime, nullable=True)
    date_out = Column(DateTime, nullable=True)

    plate_number = Column(String, nullable=True)
    vin = Column(String, nullable=True)
    model = Column(String, nullable=True)
    km = Column(String, nullable=True)

    customer_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)

    # ✅ Αυτό είναι που θες να γράφεις (label θα αλλάξει σε “Απαίτηση πελάτη”)
    customer_complaint = Column(Text, nullable=True)

    lines = relationship("VisitChecklistLine", back_populates="visit", cascade="all, delete-orphan")


class VisitChecklistLine(Base):
    __tablename__ = "visit_checklist_lines"

    id = Column(Integer, primary_key=True, index=True)
    visit_id = Column(Integer, ForeignKey("visits.id"), index=True, nullable=False)

    category = Column(String, nullable=True)
    item_name = Column(String, nullable=True)

    result = Column(String, nullable=True)  # OK / CHECK / REPAIR
    notes = Column(String, nullable=True)

    parts_code = Column(String, nullable=True)
    parts_qty = Column(Integer, nullable=False, default=0)

    exclude_from_print = Column(Boolean, nullable=False, default=False)

    visit = relationship("Visit", back_populates="lines")
