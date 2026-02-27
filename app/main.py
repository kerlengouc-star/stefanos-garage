@app.post("/visits/{visit_id}/add_line")
def visit_add_line(
    visit_id: int,
    new_category: str = Form(""),
    new_item: str = Form(""),
    make_permanent: str = Form(""),  # "on" if checked
    db: Session = Depends(get_db),
):
    new_category = (new_category or "").strip()
    new_item = (new_item or "").strip()
    is_permanent = (make_permanent == "on")

    if not new_category or not new_item:
        return RedirectResponse(f"/visits/{visit_id}", status_code=302)

    visit = db.query(Visit).filter(Visit.id == visit_id).first()
    if not visit:
        return RedirectResponse("/", status_code=302)

    # ✅ Αν είναι "Μόνιμη" → μπαίνει και στο master checklist
    if is_permanent:
        exists = (
            db.query(ChecklistItem)
            .filter(ChecklistItem.category == new_category, ChecklistItem.name == new_item)
            .first()
        )
        if not exists:
            db.add(ChecklistItem(category=new_category, name=new_item))
            db.commit()

    # ✅ Πάντα μπαίνει στην τρέχουσα επίσκεψη (αν δεν υπάρχει ήδη)
    line_exists = (
        db.query(VisitChecklistLine)
        .filter(
            VisitChecklistLine.visit_id == visit_id,
            VisitChecklistLine.category == new_category,
            VisitChecklistLine.item_name == new_item,
        )
        .first()
    )
    if not line_exists:
        db.add(
            VisitChecklistLine(
                visit_id=visit_id,
                category=new_category,
                item_name=new_item,
                result="OK",
                notes="",
                parts_code="",
                parts_qty=0,
                exclude_from_print=False,
            )
        )
        db.commit()

    return RedirectResponse(f"/visits/{visit_id}", status_code=302)
