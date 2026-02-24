import os
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

# absolute path to app/static (robust on Render)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../app
STATIC_DIR = os.path.join(BASE_DIR, "static")          # .../app/static

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/__ping")
def __ping():
    return {"ok": True, "where": "app/main.py", "static_dir": STATIC_DIR}

@app.get("/__staticcheck")
def __staticcheck():
    app_js = os.path.join(STATIC_DIR, "app.js")
    sw_js = os.path.join(STATIC_DIR, "sw.js")
    manifest = os.path.join(STATIC_DIR, "manifest.webmanifest")
    return JSONResponse({
        "static_dir": STATIC_DIR,
        "static_exists": os.path.isdir(STATIC_DIR),
        "app_js_exists": os.path.isfile(app_js),
        "sw_js_exists": os.path.isfile(sw_js),
        "manifest_exists": os.path.isfile(manifest),
        "static_files": sorted(os.listdir(STATIC_DIR)) if os.path.isdir(STATIC_DIR) else []
    })
