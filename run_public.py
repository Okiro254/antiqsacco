import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
load_dotenv(ENV_FILE)

if not os.environ.get("SECRET_KEY"):
    secret = secrets.token_urlsafe(48)
    with ENV_FILE.open("a", encoding="utf-8") as env_file:
        if ENV_FILE.exists() and ENV_FILE.stat().st_size:
            env_file.write("\n")
        env_file.write(f"SECRET_KEY={secret}\nAPP_ENV=production\n")
    load_dotenv(ENV_FILE, override=True)

os.environ.setdefault("APP_ENV", "production")
if os.environ.get("APP_ENV", "").lower() != "production":
    raise SystemExit("Set APP_ENV=production in .env before using this launcher.")

from apscheduler.schedulers.background import BackgroundScheduler
from waitress import serve
from werkzeug.middleware.proxy_fix import ProxyFix

from app import app, run_monthly_automation

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
scheduler = BackgroundScheduler(timezone="Africa/Nairobi")
scheduler.add_job(
    run_monthly_automation,
    "cron",
    day=1,
    hour=1,
    minute=0,
    id="monthly-sacco-automation",
    replace_existing=True,
    max_instances=1,
)
scheduler.start()

try:
    print("Antiq Sacco production server listening on http://127.0.0.1:8080")
    print("Expose it only through an HTTPS tunnel protected by an identity access policy.")
    serve(app, host="127.0.0.1", port=8080, threads=8, channel_timeout=120)
finally:
    scheduler.shutdown(wait=False)
