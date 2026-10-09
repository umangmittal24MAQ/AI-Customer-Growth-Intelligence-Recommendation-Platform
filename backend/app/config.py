"""Traject backend configuration: MAQ-hosted IndiaAI Qwen only."""
import os
from dotenv import load_dotenv
load_dotenv()

LLM_PROVIDER = "indiaai"
INDIAAI_API_KEY = os.getenv("INDIAAI_API_KEY", "").strip()
INDIAAI_BASE_URL = os.getenv("INDIAAI_BASE_URL", "").rstrip("/")
INDIAAI_MODEL = os.getenv("INDIAAI_MODEL", "qwen-3.8-27b")
LLM_MODEL = INDIAAI_MODEL
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "traject.db"))
USAGE_TREND_THRESHOLD_PCT = 10.0
STORAGE_UTILIZATION_THRESHOLD_PCT = 80.0
TICKET_LOOKBACK_DAYS = 60
RENEWAL_WINDOW_DAYS = 90
