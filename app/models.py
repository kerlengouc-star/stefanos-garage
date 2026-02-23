from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from .db import Base



class ChecklistCategory(Base):
    __tablename__ = "checklist_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True, nullable=False)


class ChecklistItem(Base):
    __tablename__ = "checklist_items"

    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, index=True, nullable=False)
    name = Column(String, index=True, nullable=False)


class PartMemory(Base):
    """
    ✅ Μνήμη κωδικού εξαρτήματος ΑΝΑ ΜΟΝΤΕΛΟ + (category + item_name)

    Παράδειγμα:
    model_key="range rover", category="Φρένα", item_name="Στοπερ μπροστα" -> parts_code="1234"
    """
    __tablename__ = "part_memories"

    id = Column(Integer, primary_key=True, index=True)
    model_key = Column(String, index=True, nullable=False)
    category = Column(String, index=True, nullable=False)
    item_name = Column(String, index=True, nullable=False)

    parts_code = Column(String, nullable=False)

    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Visit(Base):
    __tablename__ = "visits"

    id = Column(Integer, primary_key=True, index=True)


    date_in = Column(DateTime, nullable=True)
    date_out = Column(DateTime, nullable=True)

    plate_number = Column(String, nullable=True)
    vin = Column(String, nullable=True)
    model = Column(String, nullable=True)
    km = Column(String, nullable=True)

    customer_name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)

    customer_complaint = Column(Text, nullable=True)

    # Γενικές σημειώσεις (χρήσιμο για εκτυπώσεις/ιστορικό)
    # Στο UI/handlers γίνεται χρήση του visit.notes_general, οπότε πρέπει να υπάρχει και στη βάση.
    notes_general = Column(Text, nullable=True)

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