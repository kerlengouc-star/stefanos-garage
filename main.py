from app.main import app

@app.get("/__ping_root")
def __ping_root():
    return {"ok": True, "where": "root main.py"}
