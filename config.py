import os
from datetime import timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

BINOM_BASE    = os.getenv("BINOM_BASE", "").strip().rstrip("/")
BINOM_API_KEY = os.getenv("BINOM_API_KEY", "").strip()

TZ_OFFSET_HOURS  = int(os.getenv("TZ_OFFSET_HOURS", "3"))
PORT             = int(os.getenv("PORT", "8080"))
DPU_CACHE_TTL_SEC = int(os.getenv("DPU_CACHE_TTL_SEC", "300"))

APP_PREFIX = os.getenv("APP_PREFIX", "").strip().rstrip("/")


if not BINOM_BASE or not BINOM_API_KEY:
    raise SystemExit("Missing BINOM_BASE or BINOM_API_KEY in .env")

LOCAL_TZ = timezone(timedelta(hours=TZ_OFFSET_HOURS))