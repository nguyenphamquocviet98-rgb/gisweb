"""
╔══════════════════════════════════════════════════════════════════════╗
║   URBAN DYNAMICS INTELLIGENCE PLATFORM  —  v2.0                     ║
║   Hệ thống Phân tích & Dự báo Biến động Đô thị Toàn cầu            ║
║   Powered by: GEE · Streamlit · Scikit-learn · Prophet · AI         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ─── IMPORTS ─────────────────────────────────────────────────────────────────
import time, json, os, hashlib, requests, html, re, random
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
os.environ.setdefault("USE_FOLIUM", "1")  # geemap: chọn folium backend trước khi import
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import ee
import folium
from folium.plugins import SideBySideLayers, MeasureControl, MousePosition
import geemap.foliumap as geemap
import pandas as pd
import numpy as np
from scipy import stats as scipy_stats          # FIX: thêm scipy cho KDE
from sklearn.linear_model import LinearRegression
from sklearn.metrics import r2_score
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
from prophet import Prophet
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from google import genai
try:
    from openai import OpenAI as OpenAIClient
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Nền tảng Phân tích Đô thị Thông minh",
    page_icon="🌍",
    initial_sidebar_state="collapsed"
)

# ─── EARTH ENGINE INITIALIZATION ───────────────────────────────────────────────
def get_streamlit_secret(name: str, default=None):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return default


def load_gee_service_account():
    try:
        if "gcp_service_account" in st.secrets:
            return dict(st.secrets["gcp_service_account"])
        if all(k in st.secrets for k in ("client_email", "private_key", "project_id")):
            return dict(st.secrets)
    except Exception:
        pass

    credentials_json = get_streamlit_secret("GEE_CREDENTIALS") or os.environ.get("GEE_CREDENTIALS", "")
    if credentials_json:
        try:
            return json.loads(str(credentials_json))
        except Exception:
            st.error("❌ `GEE_CREDENTIALS` không phải JSON hợp lệ.")
            return None

    return None


def initialize_earth_engine():
    """Initialize Google Earth Engine using Streamlit Secrets."""
    project_id = os.environ.get("GEE_PROJECT", "awesome-tube-470513-s5")

    service_account_info = load_gee_service_account()
    has_service_account = bool(service_account_info)

    if has_service_account:
        try:
            client_email = service_account_info.get("client_email")
            project_id = service_account_info.get("project_id", project_id)
            raw_private_key = str(service_account_info.get("private_key", ""))
            formatted_private_key = raw_private_key.replace("\\n", "\n").strip()

            if not project_id or not client_email or not formatted_private_key:
                st.error("❌ Streamlit Secrets thiếu `project_id`, `client_email` hoặc `private_key` trong `[gcp_service_account]`.")
                return False
            if "-----BEGIN PRIVATE KEY-----" not in formatted_private_key or "-----END PRIVATE KEY-----" not in formatted_private_key:
                st.error("❌ `private_key` trong Streamlit Secrets không đúng định dạng PEM.")
                st.info("Hãy dùng dạng nhiều dòng: `private_key = \"\"\"-----BEGIN PRIVATE KEY----- ... -----END PRIVATE KEY-----\"\"\"`.")
                return False

            credentials = ee.ServiceAccountCredentials(
                client_email,
                key_data=formatted_private_key,
            )
            ee.Initialize(credentials=credentials, project=project_id)
            st.success("✅ Earth Engine initialized (Service Account)")
            return True
        except Exception as e:
            st.error(f"❌ Earth Engine Service Account lỗi: {e}")
            st.info("Kiểm tra lại Streamlit Secrets: `project_id`, `client_email`, `private_key` và quyền Earth Engine của service account.")
            return False

    try:
        ee.Initialize(project=project_id)
        st.info("ℹ️ Earth Engine initialized (Local credentials)")
        return True
    except Exception as e:
        st.error(f"❌ Không khởi tạo được Google Earth Engine: {e}")
        st.info("Nếu chạy trên Streamlit Cloud, hãy cấu hình `[gcp_service_account]` trong Secrets. Nếu chạy local, chạy `earthengine authenticate`.")
        return False

# Initialize Earth Engine on app startup
ee_initialized = initialize_earth_engine()

# ─── GLOBAL CONFIG ───────────────────────────────────────────────────────────
CONFIG = {
    "project_id": os.environ.get("GEE_PROJECT", "awesome-tube-470513-s5"),
    "admin_l1":   "FAO/GAUL/2015/level1",
    "scale":      250,
    "years":      [str(y) for y in range(2018, 2027)],
    "months":     [f"{i:02d}" for i in range(1, 13)],
    "vis": {
        "NDVI": {"min": 1, "max": 4, "palette": ["#f43f5e", "#fbbf24", "#34d399", "#059669"]},
        "NDBI": {"min": 1, "max": 4, "palette": ["#10b981", "#fbbf24", "#f97316", "#e11d48"]},
        "LST":  {"min": 1, "max": 4, "palette": ["#3b82f6", "#fbbf24", "#f97316", "#e11d48"]},
    },
    "class_labels": {
        "NDVI": ["Nước/Đất trống", "Đất thưa", "Thực vật bụi", "Rừng rậm"],
        "NDBI": ["Rừng/Nước",      "Đất trống", "Đô thị thưa",  "Đô thị nén"],
        "LST":  ["Mát (<24°C)",    "Bình thường (24–29°C)", "Nóng (29–34°C)", "Rất nóng (>34°C)"],
    },
    # FIX: thêm metadata per-layer để logic status không bị cứng theo NDVI
    "layer_meta": {
        "NDVI": {"icon": "🌿", "color": "#10b981", "good_high": True,
                 "warn_low": 0.2, "warn_high": 0.4,
                 "env_context": "thực vật và mảng xanh đô thị"},
        "NDBI": {"icon": "🏢", "color": "#f97316", "good_high": False,
                 "warn_low": 0.1, "warn_high": 0.25,
                 "env_context": "mức độ bê tông hóa và không thấm nước"},
        "LST":  {"icon": "🌡️", "color": "#ef4444", "good_high": False,
                 "warn_low": 29.0, "warn_high": 34.0,
                 "env_context": "nhiệt độ bề mặt đất và cường độ đảo nhiệt đô thị"},
    },
}

# ─── GEMINI MULTI-KEY CONFIGURATION (KEY ROTATION) ───────────────────────────
def get_secret_or_env(name: str, default: str = "") -> str:
    """Read config from Streamlit Secrets first, then environment variables."""
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
        if "gemini" in st.secrets and name in st.secrets["gemini"]:
            return str(st.secrets["gemini"][name]).strip()
    except Exception:
        pass
    return os.environ.get(name, default).strip()


def load_gemini_keys() -> List[str]:
    keys = []
    for name in ("GEMINI_KEY_1", "GEMINI_KEY_2", "GEMINI_KEY_3", "GEMINI_KEY_4", "GEMINI_API_KEY"):
        key = get_secret_or_env(name)
        if key and key not in keys:
            keys.append(key)
    return keys


# Keys must be configured in Streamlit Secrets or local .env. Never hardcode them.
GEMINI_KEYS_POOL = load_gemini_keys()
GEMINI_API_KEY = GEMINI_KEYS_POOL[0] if GEMINI_KEYS_POOL else ""

# Biến toàn cục theo dõi xem đang dùng tới key thứ mấy trong danh sách
if "current_key_idx" not in st.session_state:
    st.session_state.current_key_idx = 0

# ─── OPENAI CONFIGURATION ───────────────────────────────────────────────────
def load_openai_key() -> str:
    """Load OpenAI API key from Streamlit Secrets or environment."""
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return str(st.secrets["OPENAI_API_KEY"]).strip()
        if "openai" in st.secrets and "api_key" in st.secrets["openai"]:
            return str(st.secrets["openai"]["api_key"]).strip()
    except Exception:
        pass
    return os.environ.get("OPENAI_API_KEY", "").strip()

OPENAI_API_KEY = load_openai_key() if OPENAI_AVAILABLE else ""


# ─── GOOGLE EARTH ENGINE INIT ────────────────────────────────────────────────
def init_gee():
    if ee_initialized:
        return
    st.stop()

init_gee()

# ─── CSS: GLASSMORPHISM + NASA DASHBOARD STYLE ───────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
  --primary:   #4f46e5;
  --primary-2: #6366f1;
  --accent:    #0891b2;
  --success:   #059669;
  --warning:   #d97706;
  --danger:    #dc2626;
  --bg:        #ffffff;
  --bg-2:      #f1f5f9;
  --surface:   #ffffff;
  --surface-2: #f8fafc;
  --border:    #e2e8f0;
  --text:      #0f172a;
  --muted:     #64748b;
  --radius:    14px;
  --glow:      0 0 0 3px rgba(79,70,229,0.12);
}

html, body, [class*="css"] {
  font-family: 'Space Grotesk', sans-serif !important;
  background: var(--bg) !important;
  color: var(--text) !important;
}

.stApp {
  background: var(--bg) !important;
}

div.block-container {
  padding: 0.8rem 1.2rem 1.6rem;
  max-width: 100%;
}

section[data-testid="stSidebar"] { display: none !important; }

/* ── Scrollbar ─────────────────────────────────── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--bg-2); }
::-webkit-scrollbar-thumb { background: var(--primary); border-radius: 99px; }

/* ── Selectbox / Multiselect ─────────────────── */
.stSelectbox label, .stMultiSelect label, .stSlider label, .stRadio label {
  font-size: 11px !important; font-weight: 600 !important;
  color: var(--muted) !important; text-transform: uppercase;
  letter-spacing: 0.6px; margin-bottom: 5px;
}
.stSelectbox > div > div, .stMultiSelect > div > div {
  background: var(--surface-2) !important;
  border: 1px solid var(--border) !important;
  border-radius: 10px !important;
  color: var(--text) !important;
}
.stSelectbox > div > div:hover, .stMultiSelect > div > div:hover {
  border-color: var(--primary) !important;
  box-shadow: var(--glow) !important;
}

/* ── Buttons ─────────────────────────────────── */
div[data-testid="stButton"] button {
  height: 3rem !important; font-size: 14px !important;
  font-weight: 700 !important; border-radius: 12px !important;
  transition: all 0.25s ease;
  background: var(--surface-2) !important;
  color: var(--primary-2) !important;
  border: 1px solid rgba(99,102,241,0.3) !important;
  letter-spacing: 0.3px;
}
div[data-testid="stButton"] button:hover {
  transform: translateY(-2px);
  border-color: var(--primary) !important;
  box-shadow: var(--glow) !important;
}
div[data-testid="stButton"] button[kind="primary"] {
  background: linear-gradient(135deg, #4f46e5, #7c3aed) !important;
  border: none !important; color: #fff !important;
  box-shadow: 0 4px 20px rgba(79,70,229,0.45) !important;
}
div[data-testid="stButton"] button[kind="primary"]:hover {
  box-shadow: 0 6px 30px rgba(79,70,229,0.6) !important;
}

/* ── Spinner / Info ──────────────────────────── */
.stSpinner > div { border-top-color: var(--primary) !important; }
.stAlert { border-radius: 12px !important; }
.stInfo { background: rgba(6,182,212,0.08) !important; border-color: var(--accent) !important; }
.stWarning { background: rgba(245,158,11,0.08) !important; }
.stError { background: rgba(239,68,68,0.1) !important; }

/* ── Main title ──────────────────────────────── */
.main-title {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 0 22px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 22px;
}
.main-title h1 {
  font-size: 22px !important; font-weight: 700 !important;
  color: var(--text) !important; margin: 0 !important;
  letter-spacing: -0.5px; text-transform: uppercase;
}
.main-title h1 span { color: var(--primary-2); }
.main-title .badge {
  font-size: 10px; font-weight: 700; letter-spacing: 1px;
  background: rgba(99,102,241,0.15); color: var(--primary-2);
  border: 1px solid rgba(99,102,241,0.3); padding: 4px 10px;
  border-radius: 99px; text-transform: uppercase;
}

/* ── Section headers ─────────────────────────── */
.section-header {
  font-size: 11px !important; font-weight: 700 !important;
  color: var(--muted) !important; margin-bottom: 14px !important;
  letter-spacing: 1.2px; text-transform: uppercase;
  display: flex; align-items: center; gap: 8px;
}
.section-header::before {
  content: ''; display: block; width: 3px; height: 14px;
  background: linear-gradient(180deg, var(--primary), var(--accent));
  border-radius: 4px;
}

/* ── KPI Grid ────────────────────────────────── */
.kpi-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 8px; margin-bottom: 12px; }
.kpi-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 10px 12px;
  transition: all 0.2s; position: relative; overflow: hidden;
}
.kpi-card::before {
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, var(--primary), var(--accent));
}
.kpi-card:hover {
  border-color: rgba(99,102,241,0.4);
  box-shadow: 0 4px 20px rgba(99,102,241,0.12);
  transform: translateY(-1px);
}
.kpi-title { font-size: 9.5px; color: var(--muted); text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 4px; }
.kpi-value { font-size: 19px; font-weight: 700; color: var(--text); font-family: 'JetBrains Mono', monospace; line-height: 1.1; }
.kpi-delta { font-size: 10.5px; font-weight: 600; margin-top: 3px; }
.kpi-delta.pos { color: var(--success); }
.kpi-delta.neg { color: var(--danger); }

/* ── AI Report ───────────────────────────────── */
.ai-report {
  background: linear-gradient(145deg, rgba(99,102,241,0.06), rgba(6,182,212,0.04));
  border: 1px solid rgba(99,102,241,0.2);
  border-radius: 14px; padding: 14px 16px;
  margin-bottom: 14px;
  border-left: 3px solid var(--primary);
  max-height: 260px;
  overflow-y: auto;
}
.ai-report-label {
  font-size: 10px; color: var(--primary-2); font-weight: 800;
  text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px;
  display: flex; align-items: center; gap: 6px;
  position: sticky; top: 0;
  background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(255,255,255,0.85));
  padding-bottom: 4px;
}
.ai-report-text {
  font-size: 12.5px; line-height: 1.65; color: #334155; text-align: justify;
}

/* Chat Assistant UI */
.chat-shell {
  border: 1px solid var(--border);
  border-radius: 12px;
  background: linear-gradient(180deg, #ffffff, #f8fafc);
  padding: 12px;
  margin-bottom: 12px;
}
.chat-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 10px;
}
.chat-title {
  font-size: 15px;
  line-height: 1.2;
  font-weight: 800;
  color: var(--text);
  margin: 0;
}
.chat-subtitle {
  font-size: 11px;
  line-height: 1.4;
  color: var(--muted);
  margin-top: 3px;
}
.chat-mode {
  font-size: 10px;
  font-weight: 800;
  color: var(--success);
  background: rgba(5,150,105,0.10);
  border: 1px solid rgba(5,150,105,0.20);
  border-radius: 999px;
  padding: 4px 8px;
  white-space: nowrap;
}
.chat-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}
.chat-chip {
  font-size: 10.5px;
  line-height: 1.2;
  color: #334155;
  background: #ffffff;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 5px 8px;
  max-width: 100%;
}
.chat-chip strong { color: var(--text); }
.chat-section-title {
  font-size: 10px;
  font-weight: 800;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.7px;
  margin: 10px 0 6px;
}
.chat-empty {
  border: 1px dashed #cbd5e1;
  background: #f8fafc;
  border-radius: 10px;
  padding: 10px 12px;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
  margin: 8px 0 10px;
}
.chat-empty strong { color: var(--text); }
.chat-divider {
  height: 1px;
  background: var(--border);
  margin: 12px 0 8px;
}
div[data-testid="stChatMessage"] {
  border-radius: 12px !important;
  border: 1px solid rgba(226,232,240,0.8) !important;
  background: #ffffff !important;
}
div[data-testid="stChatInput"] {
  border-top: 1px solid var(--border);
  padding-top: 8px;
}

/* ── Academic Analysis Boxes ─────────────────── */
.analysis-box {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; margin-top: 12px;
}
.analysis-row {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 8px 0; border-bottom: 1px solid var(--border);
  font-size: 12.5px; line-height: 1.6; color: #334155;
}
.analysis-row:last-child { border-bottom: none; }
.analysis-icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
.analysis-label { font-weight: 700; color: var(--text); margin-bottom: 2px; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }

/* ── Map toolbar ─────────────────────────────── */
.map-toolbar {
  padding: 9px 16px; border-radius: 10px; font-size: 13px;
  font-weight: 600; margin-bottom: 12px;
  border: 1px solid rgba(99,102,241,0.25);
  background: rgba(99,102,241,0.08); color: var(--primary-2);
  display: flex; justify-content: center; align-items: center; gap: 8px;
}

/* ── Tabs ────────────────────────────────────── */
button[data-baseweb="tab"] {
  font-size: 12px !important; font-weight: 600 !important;
  color: var(--muted) !important; background: transparent !important;
  padding: 8px 14px !important; border-radius: 30px !important;
  margin-right: 4px;
}
button[data-baseweb="tab"][aria-selected="true"] {
  background: rgba(99,102,241,0.15) !important; color: var(--primary-2) !important;
}

/* ── Containers ──────────────────────────────── */
div[data-testid="stVerticalBlock"] > div[data-testid="stVerticalBlock"] > div[data-testid="stContainer"] {
  background: var(--surface) !important; border-color: var(--border) !important;
  border-radius: var(--radius) !important; padding: 14px !important;
}

/* ── Leaflet Popup ───────────────────────────── */
.leaflet-popup-content-wrapper { background: transparent !important; box-shadow: none !important; padding: 0 !important; overflow: hidden; }
.leaflet-popup-tip-container { display: none !important; }
</style>
""", unsafe_allow_html=True)

# ─── PLOTLY DEFAULT THEME ─────────────────────────────────────────────────────
PD = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font_color="#334155",
    font_family="'Space Grotesk', sans-serif",
)

# ─── DATA MODEL ──────────────────────────────────────────────────────────────
@dataclass
class AnalysisParams:
    country:     str
    sub_regions: List[str]
    layer:       str
    month:       str
    years_multi: List[str]

    def cache_key(self) -> str:
        """FIX: cung cấp key hashable dùng cho @st.cache_data"""
        return (f"{self.country}_{'|'.join(sorted(self.sub_regions))}_"
                f"{self.layer}_{self.month}_{'|'.join(sorted(self.years_multi))}")

# ─── SESSION STATE ────────────────────────────────────────────────────────────
def init_session_state():
    defaults = {
        "analyzed":            False,
        "params":              None,
        "result":              None,
        "cached_report":       None,
        "display_year":        None,
        "map_mode":            "🗺️ Bản đồ đơn",
        "compare_left":        None,
        "compare_right":       None,
        "map_click_value":     None,
        "last_clicked_coords": None,
        "map_center":          [16.0, 106.0],
        "map_zoom":            6,
        "force_zoom":          False,
        "current_df_hist":     None,
        "ai_trigger":          False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session_state()

# ─── GEE CORE FUNCTIONS ───────────────────────────────────────────────────────
def is_lst(layer): return layer == "LST"
def get_collection_name(layer): return "LANDSAT/LC08/C02/T1_L2" if is_lst(layer) else "COPERNICUS/S2_SR_HARMONIZED"
def get_thresholds(layer): return [0, 0.2, 0.5] if layer == "NDVI" else ([-0.1, 0, 0.2] if layer == "NDBI" else [24, 29, 34])

def mask_s2(img):
    scl = img.select("SCL")
    mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
    return img.updateMask(mask).divide(10000).copyProperties(img, img.propertyNames())

def mask_l8(img):
    qa = img.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return img.updateMask(mask).copyProperties(img, img.propertyNames())

@st.cache_data(ttl=86400, show_spinner=False)
def get_countries():
    try:
        return sorted(ee.FeatureCollection(CONFIG["admin_l1"]).aggregate_array("ADM0_NAME").distinct().sort().getInfo() or [])
    except:
        return ["Viet Nam"]

@st.cache_data(ttl=86400, show_spinner=False)
def get_sub_regions(country_name):
    try:
        return sorted(ee.FeatureCollection(CONFIG["admin_l1"])
                      .filter(ee.Filter.eq("ADM0_NAME", country_name))
                      .aggregate_array("ADM1_NAME").distinct().sort().getInfo() or [])
    except:
        return []

def get_dynamic_roi(country, sub_regions):
    fc = ee.FeatureCollection(CONFIG["admin_l1"]).filter(ee.Filter.eq("ADM0_NAME", country))
    if sub_regions:
        fc = fc.filter(ee.Filter.inList("ADM1_NAME", sub_regions))
    return fc

def get_image(geom, year, month, layer):
    lst_mode = is_lst(layer)
    start = ee.Date.fromYMD(int(year), int(month), 1)
    col = (ee.ImageCollection(get_collection_name(layer))
           .filterBounds(geom)
           .filterDate(start, start.advance(3, "month"))
           .map(mask_l8 if lst_mode else mask_s2))
    img = ee.Image(col.median())
    if lst_mode:
        return img.addBands(img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")).clip(geom)
    return img.addBands([img.normalizedDifference(["B8", "B4"]).rename("NDVI"),
                         img.normalizedDifference(["B11", "B8"]).rename("NDBI")]).clip(geom)

def classify_global(img, layer, geom=None, year=None, month=None):
    band = img.select(layer)
    t = get_thresholds(layer)
    return (ee.Image(1)
            .where(band.gte(t[0]).And(band.lt(t[1])), 2)
            .where(band.gte(t[1]).And(band.lt(t[2])), 3)
            .where(band.gte(t[2]), 4)
            .updateMask(band.mask())
            .rename("CLASS").toInt())

# ─── STATS COMPUTATION ────────────────────────────────────────────────────────
def get_area_groups(classified_img, geom, scale):
    return (ee.Image.pixelArea().divide(10000).addBands(classified_img)
            .reduceRegion(reducer=ee.Reducer.sum().group(groupField=1),
                          geometry=geom, scale=scale * 2,
                          maxPixels=1e13, tileScale=4, bestEffort=True)
            .getInfo().get("groups", []))

def extract_area(groups, class_num):
    return next((g["sum"] for g in (groups or []) if int(g["group"]) == class_num), 0.0)

def get_stats(img, layer, geom, scale):
    return (img.select(layer)
            .reduceRegion(reducer=ee.Reducer.mean()
                          .combine(ee.Reducer.min(), sharedInputs=True)
                          .combine(ee.Reducer.max(), sharedInputs=True),
                          geometry=geom, scale=scale * 2,
                          maxPixels=1e13, tileScale=4, bestEffort=True)
            .getInfo())

def get_histogram(img, layer, geom, scale):
    return (img.select(layer)
            .reduceRegion(reducer=ee.Reducer.histogram(20),
                          geometry=geom, scale=scale * 4,
                          maxPixels=1e13, tileScale=4, bestEffort=True)
            .getInfo().get(layer, {}))

def build_base_objects(params: AnalysisParams):
    roi  = get_dynamic_roi(params.country, params.sub_regions)
    geom = roi.geometry()
    years = sorted(params.years_multi)
    year_data = {}
    for year in years:
        img = get_image(geom, year, params.month, params.layer)
        year_data[year] = {
            "image": img,
            "class": classify_global(img, params.layer, geom, year, params.month).clip(geom),
        }
    return {
        "roi":       roi,
        "geom":      geom,
        "years":     years,
        "first_y":   years[0],
        "last_y":    years[-1],
        "year_data": year_data,
        "roi_names": " & ".join(params.sub_regions) if params.sub_regions else params.country,
    }

def compute_stats(params: AnalysisParams, base: dict):
    """
    OPT2: Gộp toàn bộ reduceRegion vào 1 ee.Dictionary.getInfo() duy nhất.
    Trước: 7+N+K calls tuần tự / song song. Sau: 1 server roundtrip.
    """
    geom, roi = base["geom"], base["roi"]
    first_y, last_y = base["first_y"], base["last_y"]
    year_data, years = base["year_data"], base["years"]
    layer = params.layer
    SCALE = CONFIG["scale"]

    def _trend_num(y):
        return (year_data[y]["image"].select(layer)
                .reduceRegion(reducer=ee.Reducer.mean(), geometry=geom,
                              scale=SCALE * 4, maxPixels=1e13, tileScale=4, bestEffort=True)
                .get(layer))

    def _bar_num(r):
        return (year_data[last_y]["image"].select(layer)
                .reduceRegion(reducer=ee.Reducer.mean(),
                              geometry=roi.filter(ee.Filter.eq("ADM1_NAME", r)).geometry(),
                              scale=SCALE * 2, maxPixels=1e13, tileScale=4, bestEffort=True)
                .get(layer))

    def _area_dict(class_img):
        return (ee.Image.pixelArea().divide(10000).addBands(class_img)
                .reduceRegion(reducer=ee.Reducer.sum().group(groupField=1),
                              geometry=geom, scale=SCALE * 2,
                              maxPixels=1e13, tileScale=4, bestEffort=True))

    def _stats_dict(img):
        return (img.select(layer)
                .reduceRegion(reducer=ee.Reducer.mean()
                              .combine(ee.Reducer.min(), sharedInputs=True)
                              .combine(ee.Reducer.max(), sharedInputs=True),
                              geometry=geom, scale=SCALE * 2,
                              maxPixels=1e13, tileScale=4, bestEffort=True))

    def _hist_dict(img):
        return (img.select(layer)
                .reduceRegion(reducer=ee.Reducer.histogram(20),
                              geometry=geom, scale=SCALE * 4,
                              maxPixels=1e13, tileScale=4, bestEffort=True))

    do_bar = bool(params.sub_regions) and len(params.sub_regions) >= 2
    bar_regs = params.sub_regions if do_bar else []

    # ⚡ Strategy 1: gộp tất cả vào 1 Dictionary.getInfo() — nhanh nhất nhưng có thể timeout
    # khi ROI lớn (toàn quốc). Strategy 2 (fallback): chia 7+N+K calls song song với ThreadPool.
    def _try_combined():
        payload = ee.Dictionary({
            "trends":      ee.List([_trend_num(y) for y in years]),
            "bars":        ee.List([_bar_num(r) for r in bar_regs]),
            "area_first":  _area_dict(year_data[first_y]["class"]),
            "area_last":   _area_dict(year_data[last_y]["class"]),
            "stats_first": _stats_dict(year_data[first_y]["image"]),
            "stats_last":  _stats_dict(year_data[last_y]["image"]),
            "hist_last":   _hist_dict(year_data[last_y]["image"]),
        })
        raw = payload.getInfo()
        trend_data = [{"Năm": y, "Trị số": v}
                      for y, v in zip(years, raw["trends"]) if v is not None]
        bar_data   = [{"Khu vực": r, "Trị số": v}
                      for r, v in zip(bar_regs, raw["bars"]) if v is not None]
        return {
            "area_first":  raw["area_first"].get("groups", []),
            "area_last":   raw["area_last"].get("groups", []),
            "stats_first": raw["stats_first"],
            "stats_last":  raw["stats_last"],
            "hist_last":   raw["hist_last"].get(layer, {}),
            "trend_data":  trend_data,
            "bar_data":    bar_data,
        }

    def _fallback_parallel():
        def _t(y):
            try: return y, _trend_num(y).getInfo()
            except Exception: return y, None
        def _b(r):
            try: return r, _bar_num(r).getInfo()
            except Exception: return r, None
        def _safe(fn):
            try: return fn.getInfo()
            except Exception: return {}
        with ThreadPoolExecutor(max_workers=12) as pool:
            fts = [pool.submit(_t, y) for y in years]
            fbs = [pool.submit(_b, r) for r in bar_regs]
            fA1 = pool.submit(_safe, _area_dict(year_data[first_y]["class"]))
            fA2 = pool.submit(_safe, _area_dict(year_data[last_y]["class"]))
            fS1 = pool.submit(_safe, _stats_dict(year_data[first_y]["image"]))
            fS2 = pool.submit(_safe, _stats_dict(year_data[last_y]["image"]))
            fH  = pool.submit(_safe, _hist_dict(year_data[last_y]["image"]))
            trend_data = [{"Năm": y, "Trị số": v} for y, v in (f.result() for f in fts) if v is not None]
            bar_data   = [{"Khu vực": r, "Trị số": v} for r, v in (f.result() for f in fbs) if v is not None]
            return {
                "area_first":  fA1.result().get("groups", []),
                "area_last":   fA2.result().get("groups", []),
                "stats_first": fS1.result(),
                "stats_last":  fS2.result(),
                "hist_last":   fH.result().get(layer, {}),
                "trend_data":  trend_data,
                "bar_data":    bar_data,
            }

    try:
        return _try_combined()
    except Exception as e:
        msg = str(e).lower()
        if "timed out" in msg or "timeout" in msg or "deadline" in msg or "memory" in msg:
            # ROI quá lớn → chia nhỏ chạy song song
            return _fallback_parallel()
        raise

@st.cache_data(ttl=3600, show_spinner=False)
def compute_stats_cached(country: str, sub_regions_tuple: tuple, layer: str,
                         month: str, years_tuple: tuple) -> dict:
    """
    OPT3: cache trong session Streamlit (RAM). Trả về stats đã serialize được.
    Khi user nhấn 🚀 lại cùng params → lấy ngay từ RAM, không gọi GEE / SQL.
    """
    p = AnalysisParams(country, list(sub_regions_tuple), layer, month, list(years_tuple))
    base = build_base_objects(p)
    return compute_stats(p, base)

# ─── AI FORECAST: LAND USE 2030/2035 ─────────────────────────────────────────
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_area_history(country: str, sub_regions_tuple: tuple,
                       layer: str, month: str) -> pd.DataFrame:
    """
    Fetch diện tích từng class qua TẤT CẢ CONFIG['years'] (2018-2026) song song.
    Cache 1h để Prophet refit không cần GEE lại.
    """
    p_full = AnalysisParams(country, list(sub_regions_tuple), layer, month,
                            list(CONFIG["years"]))
    base = build_base_objects(p_full)

    def _one_year(y):
        try:
            groups = get_area_groups(base["year_data"][y]["class"],
                                     base["geom"], CONFIG["scale"])
            return {"year": int(y),
                    "class_1": extract_area(groups, 1),
                    "class_2": extract_area(groups, 2),
                    "class_3": extract_area(groups, 3),
                    "class_4": extract_area(groups, 4)}
        except Exception:
            return {"year": int(y),
                    "class_1": None, "class_2": None,
                    "class_3": None, "class_4": None}

    with ThreadPoolExecutor(max_workers=min(9, len(CONFIG["years"]))) as pool:
        rows = list(pool.map(_one_year, CONFIG["years"]))
    return pd.DataFrame(rows).sort_values("year").reset_index(drop=True)


# ─── AI: URBAN RISK SCORE 0–100 ──────────────────────────────────────────────
def compute_risk_score(result: dict, params) -> dict:
    """
    Composite risk score 0–100, layer-aware.
    3 components:
      - Hiện trạng (40%): giá trị trung bình hiện tại có gần ngưỡng warn không
      - Xu hướng (35%): % biến động vs năm đầu, theo hướng "xấu"
      - Diện tích nguy cơ (25%): % diện tích nằm trong class 3+4
    """
    layer = params.layer
    meta = CONFIG["layer_meta"][layer]

    m_first = (result.get("stats_first") or {}).get(f"{layer}_mean") or 0
    m_last  = (result.get("stats_last")  or {}).get(f"{layer}_mean") or 0
    delta = m_last - m_first
    pct_change = (delta / abs(m_first) * 100) if m_first else 0

    # FIX: bad_classes phụ thuộc layer — NDVI thì class 1+2 mới là "xấu"
    bad_classes = {"NDVI": (1, 2), "NDBI": (3, 4), "LST": (3, 4)}[layer]
    area_last = result.get("area_last") or []
    total = sum(g["sum"] for g in area_last) if area_last else 0
    high_area = sum(g["sum"] for g in area_last if int(g["group"]) in bad_classes)
    high_pct = (high_area / total * 100) if total > 0 else 0

    # ── Component 1: Hiện trạng (0-100) — sigmoid-like để giữ độ phân giải ──
    warn_low, warn_high = meta["warn_low"], meta["warn_high"]
    if meta["good_high"]:  # NDVI: cao = tốt
        # m_last = warn_high (0.4) → 0 điểm; = 0 → 100 điểm; < 0 → 100 điểm
        current_score = max(0, min(100, (warn_high - m_last) / warn_high * 100))
    else:
        # NDBI/LST: dùng scale [warn_low - margin, warn_high]
        # NDBI: warn_low=0.1, warn_high=0.25. Margin trải xuống -0.2 để có discriminate
        # cho các city có mean ~ -0.1 đến 0
        scale_lo = warn_low - (warn_high - warn_low) * 2.0  # rộng hơn
        if m_last <= scale_lo:
            current_score = 0
        elif m_last >= warn_high:
            current_score = 100
        else:
            current_score = (m_last - scale_lo) / max(warn_high - scale_lo, 0.01) * 100

    # ── Component 2: Xu hướng (0-100) ────────────────
    if meta["good_high"]:
        delta_score = max(0, min(100, -pct_change))
    else:
        delta_score = max(0, min(100, pct_change))

    # ── Component 3: % diện tích nguy cơ (0-100) ────────────────
    area_score = min(100, high_pct * 2)  # 50% diện tích nằm class nguy cơ = 100

    # ── Tổng hợp ──────────────────────────────────────
    total_score = 0.40 * current_score + 0.35 * delta_score + 0.25 * area_score
    total_score = max(0, min(100, total_score))

    # ── Cluster (4 mức) ───────────────────────────────
    if total_score < 25:
        label, color = "An toàn",         "#059669"
    elif total_score < 50:
        label, color = "Cần theo dõi",    "#d97706"
    elif total_score < 75:
        label, color = "Cảnh báo",        "#dc2626"
    else:
        label, color = "Khẩn cấp",        "#7c2d12"

    return {
        "score": round(total_score, 1),
        "label": label,
        "color": color,
        "components": {
            "Hiện trạng":        round(current_score, 1),
            "Xu hướng biến động": round(delta_score, 1),
            "Diện tích nguy cơ":  round(area_score, 1),
        },
        "weights": {
            "Hiện trạng":         40,
            "Xu hướng biến động":  35,
            "Diện tích nguy cơ":   25,
        },
        "raw": {
            "current_value": m_last,
            "delta": delta,
            "pct_change": pct_change,
            "high_pct": high_pct,
            "high_area_ha": high_area,
        },
    }


@st.cache_data(ttl=3600, show_spinner=False)
def compute_per_region_risk(country: str, sub_regions_tuple: tuple,
                             layer: str, month: str,
                             years_tuple: tuple) -> list:
    """
    Tính risk score per-region khi user chọn ≥ 2 vùng.
    Parallel GEE calls cho first-year + last-year mean của mỗi vùng.
    """
    if len(sub_regions_tuple) < 2:
        return []
    p = AnalysisParams(country, list(sub_regions_tuple), layer, month, list(years_tuple))
    base = build_base_objects(p)
    years_sorted = sorted(years_tuple)
    first_y, last_y = years_sorted[0], years_sorted[-1]
    meta = CONFIG["layer_meta"][layer]

    def _region(reg):
        try:
            geom = base["roi"].filter(ee.Filter.eq("ADM1_NAME", reg)).geometry()
            m_first = (base["year_data"][first_y]["image"].select(layer)
                       .reduceRegion(reducer=ee.Reducer.mean(), geometry=geom,
                                     scale=CONFIG["scale"] * 4, maxPixels=1e13,
                                     tileScale=4, bestEffort=True).getInfo().get(layer))
            m_last = (base["year_data"][last_y]["image"].select(layer)
                      .reduceRegion(reducer=ee.Reducer.mean(), geometry=geom,
                                    scale=CONFIG["scale"] * 4, maxPixels=1e13,
                                    tileScale=4, bestEffort=True).getInfo().get(layer))
            if m_first is None or m_last is None:
                return None
            delta = m_last - m_first
            pct = (delta / abs(m_first) * 100) if m_first else 0
            warn_low, warn_high = meta["warn_low"], meta["warn_high"]
            if meta["good_high"]:
                cur = (warn_high - m_last) / max(warn_high, 0.01) * 100
                dlt = -pct
            else:
                scale_lo = warn_low - (warn_high - warn_low) * 2.0
                if m_last <= scale_lo:
                    cur = 0
                elif m_last >= warn_high:
                    cur = 100
                else:
                    cur = (m_last - scale_lo) / max(warn_high - scale_lo, 0.01) * 100
                dlt = pct
            cur = max(0, min(100, cur))
            dlt = max(0, min(100, dlt))
            score = 0.50 * cur + 0.50 * dlt    # bỏ component diện tích vì cần thêm GEE
            score = max(0, min(100, score))
            return {
                "region": reg,
                "score":  round(score, 1),
                "mean_first": m_first, "mean_last": m_last,
                "delta": delta, "pct_change": pct,
                "current_component": round(cur, 1),
                "delta_component":   round(dlt, 1),
            }
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=min(8, len(sub_regions_tuple))) as pool:
        rows = list(pool.map(_region, sub_regions_tuple))
    return [r for r in rows if r is not None]


def evaluate_prophet_series(years: list, values: list, test_size: int = 2) -> dict:
    """
    Đánh giá độ chính xác Prophet bằng train/test split.
    Train trên (n - test_size) năm đầu, test trên test_size năm cuối.
    Trả về dict {MAPE, RMSE, MAE, n_train, n_test} hoặc {} nếu không đủ data.
    """
    n = len(years)
    if n < 5 or test_size < 1 or test_size >= n - 2:
        return {}
    try:
        years_arr = list(years)
        vals_arr  = list(values)
        # Lọc None / NaN
        clean = [(y, v) for y, v in zip(years_arr, vals_arr) if v is not None and not pd.isna(v)]
        if len(clean) < 5:
            return {}
        years_arr = [c[0] for c in clean]
        vals_arr  = [c[1] for c in clean]

        train_years, test_years = years_arr[:-test_size], years_arr[-test_size:]
        train_vals,  test_vals  = vals_arr[:-test_size],  vals_arr[-test_size:]

        df_train = pd.DataFrame({
            "ds": pd.to_datetime([str(y) for y in train_years], format="%Y"),
            "y":  train_vals,
        })
        m = Prophet(yearly_seasonality=False, weekly_seasonality=False,
                    daily_seasonality=False, interval_width=0.85)
        m.fit(df_train)

        future = pd.DataFrame({
            "ds": pd.to_datetime([str(y) for y in test_years], format="%Y"),
        })
        fc = m.predict(future)
        y_pred = fc["yhat"].values
        y_true = np.array(test_vals, dtype=float)

        # Skip zero-y for MAPE
        nonzero = y_true != 0
        if nonzero.any():
            mape = float(np.mean(np.abs((y_true[nonzero] - y_pred[nonzero]) / y_true[nonzero])) * 100)
        else:
            mape = None
        rmse = float(np.sqrt(np.mean((y_true - y_pred) ** 2)))
        mae  = float(np.mean(np.abs(y_true - y_pred)))

        return {
            "MAPE":    mape,
            "RMSE":    rmse,
            "MAE":     mae,
            "n_train": len(train_years),
            "n_test":  len(test_years),
            "test_years":  test_years,
            "y_true":  list(y_true),
            "y_pred":  list(y_pred),
        }
    except Exception:
        return {}


def forecast_land_use(df_hist: pd.DataFrame,
                      target_years=(2030, 2035)) -> dict:
    """
    Prophet riêng cho từng class. Trả về:
      {2030: {class_1: ha, class_2: ha, ..., class_1_lo, class_1_hi, ...}, 2035: {...}}
    + 'series': dict {class_X: DataFrame(year, yhat, yhat_lower, yhat_upper)} cho line chart.
    """
    out = {y: {} for y in target_years}
    series = {}
    eval_metrics = {}
    last_hist_year = int(df_hist["year"].max())
    horizon_max = max(target_years)

    for cls in ["class_1", "class_2", "class_3", "class_4"]:
        sub = df_hist[["year", cls]].dropna()
        if len(sub) < 3:
            series[cls] = None
            continue

        # ── Backtest: train trên N-2, test trên 2 năm cuối ──────────
        eval_metrics[cls] = evaluate_prophet_series(
            years=sub["year"].tolist(),
            values=sub[cls].tolist(),
            test_size=2,
        )

        # ── Full fit + forecast tới horizon ─────────────────────────
        ds = pd.to_datetime(sub["year"].astype(str), format="%Y")
        df_p = pd.DataFrame({"ds": ds, "y": sub[cls].values})
        m = Prophet(yearly_seasonality=False, weekly_seasonality=False,
                    daily_seasonality=False, interval_width=0.85)
        m.fit(df_p)
        periods = horizon_max - last_hist_year
        future = m.make_future_dataframe(periods=periods, freq="YS")
        fc = m.predict(future)
        fc["year"] = fc["ds"].dt.year
        # Clip negative areas
        fc["yhat"]       = fc["yhat"].clip(lower=0)
        fc["yhat_lower"] = fc["yhat_lower"].clip(lower=0)
        fc["yhat_upper"] = fc["yhat_upper"].clip(lower=0)
        series[cls] = fc[["year", "yhat", "yhat_lower", "yhat_upper"]].copy()
        for y in target_years:
            row = fc[fc["year"] == y]
            if not row.empty:
                out[y][cls]            = float(row["yhat"].iloc[0])
                out[y][cls + "_lo"]    = float(row["yhat_lower"].iloc[0])
                out[y][cls + "_hi"]    = float(row["yhat_upper"].iloc[0])
    out["series"] = series
    out["eval_metrics"]   = eval_metrics
    out["last_hist_year"] = last_hist_year
    return out


def build_2035_scenario_summary(layer: str, labels: list, classes: list,
                                cur_row: pd.Series, fc: dict,
                                last_y: int, avg_mape: Optional[float] = None) -> dict:
    """Build a compact scenario layer for the 2035 forecast tab."""
    total_now = sum(float(cur_row.get(c) or 0) for c in classes)
    values_2035 = {c: float(fc.get(2035, {}).get(c) or 0) for c in classes}
    total_2035 = sum(values_2035.values())

    bad_classes = {
        "NDVI": ("class_1", "class_2"),
        "NDBI": ("class_3", "class_4"),
        "LST":  ("class_3", "class_4"),
    }[layer]
    good_classes = tuple(c for c in classes if c not in bad_classes)

    bad_now = sum(float(cur_row.get(c) or 0) for c in bad_classes)
    bad_2035 = sum(values_2035.get(c, 0) for c in bad_classes)
    good_now = sum(float(cur_row.get(c) or 0) for c in good_classes)
    good_2035 = sum(values_2035.get(c, 0) for c in good_classes)

    bad_delta = bad_2035 - bad_now
    bad_pct = (bad_delta / bad_now * 100) if bad_now > 0 else 0
    pressure_now = (bad_now / total_now * 100) if total_now > 0 else 0
    pressure_2035 = (bad_2035 / total_2035 * 100) if total_2035 > 0 else 0

    uncertainty = 0.0
    for c in bad_classes:
        lo = float(fc.get(2035, {}).get(c + "_lo") or values_2035.get(c, 0))
        hi = float(fc.get(2035, {}).get(c + "_hi") or values_2035.get(c, 0))
        uncertainty += max(0.0, hi - lo)
    uncertainty_pct = (uncertainty / total_2035 * 100) if total_2035 > 0 else 0

    if avg_mape is None:
        confidence_score = max(35, min(85, 80 - uncertainty_pct * 1.2))
    else:
        confidence_score = max(20, min(95, 100 - avg_mape * 1.8 - uncertainty_pct))
    if confidence_score >= 75:
        confidence_label, confidence_color = "Cao", "#059669"
    elif confidence_score >= 55:
        confidence_label, confidence_color = "Trung bình", "#d97706"
    else:
        confidence_label, confidence_color = "Thận trọng", "#dc2626"

    if layer == "NDVI":
        pressure_name = "suy giảm xanh"
        impact_text = "giảm năng lực điều hòa vi khí hậu và tăng rủi ro dòng chảy mặt"
        action_focus = "bảo vệ lõi xanh, phục hồi hành lang cây xanh và hạn chế chuyển đổi đất phủ xanh"
    elif layer == "NDBI":
        pressure_name = "bê tông hóa"
        impact_text = "tăng bề mặt không thấm nước, áp lực thoát nước và đảo nhiệt đô thị"
        action_focus = "kiểm soát mật độ xây dựng, tăng vật liệu thấm nước và hạ tầng xanh-xanh dương"
    else:
        pressure_name = "stress nhiệt"
        impact_text = "tăng stress nhiệt, giảm tiện nghi ngoài trời và tăng nhu cầu làm mát"
        action_focus = "tăng bóng mát, giảm vật liệu hấp thụ nhiệt và bổ sung không gian nước/cây xanh"

    cls_rows = []
    for c, lbl in zip(classes, labels):
        now = float(cur_row.get(c) or 0)
        fut = values_2035.get(c, 0)
        delta = fut - now
        cls_rows.append((lbl, c, now, fut, delta, (delta / now * 100) if now > 0 else 0))
    dominant = max(cls_rows, key=lambda r: abs(r[4])) if cls_rows else None

    green_2035 = bad_now + bad_delta * (0.55 if bad_delta > 0 else 0.75)
    stress_2035 = bad_2035 + max(abs(bad_delta), bad_2035 * 0.05) * 0.35
    green_2035 = max(0, min(total_2035, green_2035))
    stress_2035 = max(0, min(total_2035, stress_2035))

    return {
        "pressure_name": pressure_name,
        "pressure_now": pressure_now,
        "pressure_2035": pressure_2035,
        "bad_now": bad_now,
        "bad_2035": bad_2035,
        "bad_delta": bad_delta,
        "bad_pct": bad_pct,
        "good_delta": good_2035 - good_now,
        "uncertainty_pct": uncertainty_pct,
        "confidence_score": confidence_score,
        "confidence_label": confidence_label,
        "confidence_color": confidence_color,
        "dominant": dominant,
        "impact_text": impact_text,
        "action_focus": action_focus,
        "scenarios": [
            ("Cơ sở", bad_2035, "Giữ xu hướng lịch sử đến 2035"),
            ("Can thiệp xanh", green_2035, "Giảm tốc vùng rủi ro nhờ quy hoạch chủ động"),
            ("Chậm can thiệp", stress_2035, "Rủi ro tăng nếu mở rộng đô thị thiếu kiểm soát"),
        ],
        "horizon": 2035 - int(last_y),
    }

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────
def fmt_val(layer, v):
    if v is None:
        return "—"
    return f"{v:.2f} °C" if layer == "LST" else f"{v:.4f}"

def layer_status(layer, val):
    """FIX: tính status đúng per-layer, không hard-code theo NDVI logic."""
    if val is None:
        return "N/A", "#64748b"
    meta = CONFIG["layer_meta"][layer]
    if meta["good_high"]:
        # NDVI: high = good
        if val >= meta["warn_high"]:   return "Tốt",        "#10b981"
        if val <= meta["warn_low"]:    return "Cảnh báo",   "#ef4444"
        return "Trung bình", "#f59e0b"
    else:
        # NDBI / LST: low = good
        if val <= meta["warn_low"]:    return "Tốt",        "#10b981"
        if val >= meta["warn_high"]:   return "Cảnh báo",   "#ef4444"
        return "Trung bình", "#f59e0b"

# ─── GEOCODING & WEATHER ──────────────────────────────────────────────────────
def compute_trend_accuracy_summary(result: dict, layer: str) -> dict:
    trend = result.get("trend_data") or []
    years, values = [], []
    for row in trend:
        y = row.get("Năm")
        v = row.get("Trị số")
        if y is not None and v is not None and not pd.isna(v):
            years.append(int(y))
            values.append(float(v))
    metrics = evaluate_prophet_series(years, values, test_size=2)
    if not metrics:
        return {
            "available": False,
            "label": "Chưa đủ dữ liệu",
            "summary": "Chuỗi thời gian hiện tại chưa đủ tối thiểu 5 năm hợp lệ để backtest độ chính xác mô hình.",
        }

    mape = metrics.get("MAPE")
    rmse = metrics.get("RMSE")
    if mape is None:
        label = "Không tính được MAPE"
        note = "MAPE không khả dụng do dữ liệu kiểm thử có giá trị bằng 0."
    elif mape < 10:
        label = "Rất tốt"
        note = "Sai số phần trăm thấp, mô hình có độ ổn định cao trên tập kiểm thử."
    elif mape < 20:
        label = "Tốt"
        note = "Sai số ở mức chấp nhận tốt cho phân tích xu hướng viễn thám."
    elif mape < 35:
        label = "Trung bình"
        note = "Mô hình dùng được cho tham khảo xu hướng, nhưng cần thận trọng khi diễn giải dự báo."
    else:
        label = "Thấp"
        note = "Sai số cao, kết quả dự báo chỉ nên xem như tín hiệu tham khảo sơ bộ."

    mape_text = f"{mape:.2f}%" if mape is not None else "N/A"
    rmse_text = fmt_val(layer, rmse) if rmse is not None else "N/A"
    test_years = ", ".join(str(y) for y in metrics.get("test_years", []))
    return {
        "available": True,
        "label": label,
        "mape": mape,
        "rmse": rmse,
        "mape_text": mape_text,
        "rmse_text": rmse_text,
        "n_train": metrics.get("n_train"),
        "n_test": metrics.get("n_test"),
        "test_years": test_years,
        "summary": (
            f"Độ chính xác backtest của chuỗi {layer}: MAPE = {mape_text}, RMSE = {rmse_text}. "
            f"Mô hình được huấn luyện trên {metrics.get('n_train')} năm và kiểm thử trên "
            f"{metrics.get('n_test')} năm cuối ({test_years}). Đánh giá: {label}. {note}"
        ),
    }


@st.cache_data(ttl=86400, show_spinner=False)
def get_address_from_coords(lat, lon):
    try:
        geolocator = Nominatim(user_agent="urban_gis_v2")
        location = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, timeout=5)
        return location.address if location else "Không xác định"
    except:
        return "Không thể kết nối định vị"

@st.cache_data(ttl=1800, show_spinner=False)
def get_forecast_weather(lat, lon):
    try:
        url = (f"https://api.open-meteo.com/v1/forecast"
               f"?latitude={lat}&longitude={lon}"
               f"&current_weather=true"
               f"&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max"
               f"&hourly=relative_humidity_2m&timezone=auto")
        res = requests.get(url, timeout=5).json()
        cw = res.get("current_weather", {})
        humidity_values = res.get("hourly", {}).get("relative_humidity_2m", [])
        current_hum = humidity_values[0] if humidity_values else None
        current = {
            "temp": cw.get("temperature"),
            "wind": cw.get("windspeed"),
            "code": cw.get("weathercode"),
            "humidity": current_hum,
        }
        daily = res.get("daily", {})
        forecast = []
        if not cw and not daily:
            return None
        if daily and "time" in daily:
            n = len(daily["time"])
            max_t = daily.get("temperature_2m_max", [])
            min_t = daily.get("temperature_2m_min", [])
            weathercode = daily.get("weathercode", [])
            rain_prob = daily.get("precipitation_probability_max", [])
            for i in range(n):
                dt = datetime.strptime(daily["time"][i], "%Y-%m-%d")
                forecast.append({
                    "date": dt.strftime("%d/%m"),
                    "max_t": max_t[i] if i < len(max_t) else None,
                    "min_t": min_t[i] if i < len(min_t) else None,
                    "code": weathercode[i] if i < len(weathercode) else None,
                    "rain_prob": rain_prob[i] if i < len(rain_prob) else None,
                })
        return {"current": current, "forecast": forecast}
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_three_indices(lat, lon, year, month):
    point  = ee.Geometry.Point([lon, lat])
    start  = ee.Date.fromYMD(int(year), int(month), 1)
    img_s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
              .filterBounds(point).filterDate(start, start.advance(3, "month"))
              .map(mask_s2).median())
    img_l8 = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
              .filterBounds(point).filterDate(start, start.advance(3, "month"))
              .map(mask_l8).median())
    combined = ee.Image().addBands([
        img_s2.normalizedDifference(["B8", "B4"]).rename("NDVI"),
        img_s2.normalizedDifference(["B11", "B8"]).rename("NDBI"),
        img_l8.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST"),
    ])
    try:
        vals = combined.reduceRegion(reducer=ee.Reducer.first(), geometry=point, scale=10).getInfo()
        return {"NDVI": vals.get("NDVI"), "NDBI": vals.get("NDBI"), "LST": vals.get("LST")}
    except:
        return {"NDVI": None, "NDBI": None, "LST": None}

@st.cache_data(ttl=3600, show_spinner=False)
def get_full_history_at_point(lat, lon, month):
    """
    Batch toàn bộ years trong 1 GEE call.
    FIX: chống fail toàn batch khi 1 năm bị thiếu ảnh — chuyển sang per-year parallel với try/except.
    """
    point = ee.Geometry.Point([lon, lat])
    start_radius = point.buffer(30)  # buffer 30m để chắc chắn có pixel khi reduceRegion

    def _fetch_year(y_str):
        try:
            start = ee.Date.fromYMD(int(y_str), int(month), 1)
            img_s2 = (ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED")
                      .filterBounds(point).filterDate(start, start.advance(3, "month"))
                      .map(mask_s2).median())
            img_l8 = (ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                      .filterBounds(point).filterDate(start, start.advance(3, "month"))
                      .map(mask_l8).median())
            ndvi = img_s2.normalizedDifference(["B8", "B4"]).rename("NDVI")
            ndbi = img_s2.normalizedDifference(["B11", "B8"]).rename("NDBI")
            lst  = (img_l8.select("ST_B10").multiply(0.00341802)
                          .add(149.0).subtract(273.15).rename("LST"))
            combined = ee.Image.cat([ndvi, ndbi, lst])
            vals = combined.reduceRegion(reducer=ee.Reducer.mean(),
                                         geometry=start_radius, scale=30,
                                         maxPixels=1e9, bestEffort=True).getInfo()
            return {"Năm": y_str,
                    "NDVI": vals.get("NDVI"),
                    "NDBI": vals.get("NDBI"),
                    "LST":  vals.get("LST")}
        except Exception:
            return {"Năm": y_str, "NDVI": None, "NDBI": None, "LST": None}

    with ThreadPoolExecutor(max_workers=min(9, len(CONFIG["years"]))) as pool:
        rows = list(pool.map(_fetch_year, CONFIG["years"]))
    return pd.DataFrame(rows)

# ─── TIMELAPSE (FIX: không dùng AnalysisParams để tránh cache crash) ─────────
@st.cache_data(ttl=86400, show_spinner=False)
def generate_timelapse_url(
    cache_key: str,          # FIX: dùng string key thay vì AnalysisParams
    years_tuple: tuple,
    month: str,
    layer: str,
    geom_coords: tuple,      # FIX: tuple thay vì list để hashable
):
    """
    FIX BUG: hàm gốc nhận AnalysisParams không hashable → @st.cache_data crash.
    Giải pháp: nhận primitive types, build EE objects bên trong hàm.
    """
    try:
        geom   = ee.Geometry.Polygon(list(geom_coords))
        images = []
        for y in years_tuple:
            img = get_image(geom, y, month, layer)
            classified = classify_global(img, layer, geom, y, month)
            vis_img = (classified
                       .visualize(**CONFIG["vis"][layer])
                       .set("system:time_start",
                            ee.Date.fromYMD(int(y), int(month), 1).millis()))
            images.append(vis_img)
        gif_url = (ee.ImageCollection.fromImages(images)
                   .getVideoThumbURL({
                       "dimensions": 600,
                       "framesPerSecond": 1.5,
                       "region": geom,
                       "format": "gif",
                   }))
        return gif_url
    except Exception as e:
        return None

# ─── AI PROVIDER ABSTRACTION ────────────────────────────────────────────────
class AIProvider:
    """Base class for AI providers."""
    def generate(self, prompt: str, system_instruction: str = None) -> Tuple[str, str]:
        """Return (response_text, provider_name)."""
        raise NotImplementedError

class GeminiProvider(AIProvider):
    """Gemini AI provider with key rotation."""
    def generate(self, prompt: str, system_instruction: str = None) -> Tuple[str, str]:
        total_keys = len(GEMINI_KEYS_POOL)
        if total_keys == 0:
            raise RuntimeError("Chưa cấu hình Gemini API key.")
        
        last_err = None
        for attempt in range(total_keys):
            idx = (st.session_state.current_key_idx + attempt) % total_keys
            current_key = GEMINI_KEYS_POOL[idx]
            
            try:
                client = genai.Client(api_key=current_key)
                config_params = {}
                if system_instruction:
                    config_params["system_instruction"] = system_instruction
                
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=genai.types.GenerateContentConfig(**config_params) if config_params else None,
                )
                
                if response and response.text:
                    st.session_state.current_key_idx = idx
                    return response.text, "Gemini"
            except Exception as e:
                last_err = e
                err_msg = str(e).lower()
                if any(x in err_msg for x in ["429", "quota", "resource_exhausted", "invalid"]):
                    continue
                raise
        
        raise RuntimeError(f"Gemini API failed: {last_err}")

class OpenAIProvider(AIProvider):
    """OpenAI ChatGPT provider."""
    def generate(self, prompt: str, system_instruction: str = None) -> Tuple[str, str]:
        if not OPENAI_AVAILABLE or not OPENAI_API_KEY:
            raise RuntimeError("OpenAI không khả dụng hoặc chưa cấu hình.")
        
        client = OpenAIClient(api_key=OPENAI_API_KEY)
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})
        
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=800
        )
        
        return response.choices[0].message.content, "OpenAI"

# ─── GEMINI AI REPORT ────────────────────────────────────────────────────────
GEMINI_MODELS = ["gemini-2.5-flash", "gemini-2.0-flash"]
AI_PROVIDERS = {
    "gemini": GeminiProvider(),
    "openai": OpenAIProvider() if OPENAI_AVAILABLE else None,
}
def generate_local_report(layer, first_year, last_year, first_val, last_val, high_area, roi_name, reason=None): # This function is kept for fallback
    meta = CONFIG["layer_meta"][layer]
    delta = (last_val or 0) - (first_val or 0)
    abs_delta = abs(delta)
    pct_delta = (delta / abs(first_val) * 100) if first_val not in (None, 0) else None
    direction = "tăng" if delta > 0 else "giảm" if delta < 0 else "gần như không đổi"
    status, _ = layer_status(layer, last_val)
    good_context = "tích cực" if (delta >= 0) == meta["good_high"] else "bất lợi và cần theo dõi chặt chẽ"
    reason_text = f" Chế độ tạo báo cáo tức thì đang được dùng: {reason}." if reason else ""
    risk_level = "cao" if status == "Cảnh báo" else "trung bình" if status == "Trung bình" else "thấp"
    intensity = "mạnh" if abs_delta >= 0.15 else "vừa" if abs_delta >= 0.05 else "nhẹ"
    pct_text = f", tương đương {pct_delta:+.1f}%" if pct_delta is not None else ""

    if layer == "NDVI":
        indicator_meaning = "sức khỏe thảm thực vật, độ phủ xanh và khả năng điều hòa vi khí hậu"
        adverse_scenario = (
            "Nếu xu hướng suy giảm tiếp diễn, khu vực có nguy cơ mất thêm mảng xanh chức năng, "
            "tăng dòng chảy mặt và giảm khả năng hấp thụ nhiệt."
        )
        priority_actions = (
            "ưu tiên bảo vệ các lõi xanh hiện hữu, phục hồi hành lang cây xanh, tăng cây bóng mát "
            "trên các trục giao thông và kiểm soát chuyển đổi đất xanh sang bề mặt cứng"
        )
    elif layer == "NDBI":
        indicator_meaning = "mức độ xây dựng, bê tông hóa và áp lực bề mặt không thấm nước"
        adverse_scenario = (
            "Nếu NDBI tiếp tục tăng, rủi ro chính là lan rộng bề mặt xây dựng, suy giảm thấm nước, "
            "gia tăng đảo nhiệt và áp lực thoát nước đô thị."
        )
        priority_actions = (
            "kiểm soát mật độ xây dựng, bổ sung hạ tầng xanh-xanh dương, dùng vật liệu thấm nước "
            "và khoanh vùng các điểm nóng bê tông hóa để giám sát"
        )
    else:
        indicator_meaning = "nhiệt độ bề mặt đất và cường độ đảo nhiệt đô thị"
        adverse_scenario = (
            "Nếu LST duy trì ở mức cao, khu vực có nguy cơ gia tăng stress nhiệt, giảm tiện nghi vi khí hậu "
            "và tăng nhu cầu năng lượng làm mát."
        )
        priority_actions = (
            "tăng che phủ cây xanh, giảm bề mặt hấp thụ nhiệt, bổ sung mặt nước/hạ tầng xanh "
            "và ưu tiên can thiệp tại các vùng nóng liên tục"
        )

    return (
        f"Đánh giá chuyên gia tức thì cho {roi_name}: chỉ số {layer} phản ánh {indicator_meaning}. "
        f"Trong giai đoạn {first_year}-{last_year}, giá trị trung bình {direction} từ {fmt_val(layer, first_val)} "
        f"đến {fmt_val(layer, last_val)}, biến động {delta:+.3f}{pct_text}; cường độ biến động được xếp mức {intensity}. "
        f"Trạng thái năm cuối là {status}, mức rủi ro tổng hợp {risk_level}, và xu hướng hiện được đánh giá là {good_context} "
        f"đối với quản lý đô thị. Diện tích nhóm nguy cơ cao đạt khoảng {high_area:,.0f} ha, cần được xem là vùng ưu tiên "
        f"cho kiểm tra thực địa, đối chiếu quy hoạch sử dụng đất và giám sát ảnh vệ tinh định kỳ. {adverse_scenario} "
        f"Kịch bản hành động khuyến nghị là {priority_actions}. Về ra quyết định, kết quả này nên được dùng như lớp cảnh báo "
        f"sớm có căn cứ định lượng: ưu tiên khu vực có rủi ro cao, kiểm tra nguyên nhân tại hiện trường, sau đó lượng hóa hiệu quả "
        f"can thiệp qua cùng chỉ số {layer} trong các kỳ tiếp theo.{reason_text}"
    )

def call_ai_with_retry(prompt: str, system_instruction: str = None, max_retries: int = 3) -> Tuple[str, str, bool]:
    """
    Gọi AI provider với retry logic (exponential backoff).
    Return: (text, provider_name, is_ai_generated)
    Fallback chain: Gemini → OpenAI → Local generation
    """
    providers_order = ["gemini"]
    if OPENAI_AVAILABLE and OPENAI_API_KEY:
        providers_order.append("openai")
    
    for provider_name in providers_order:
        for attempt in range(max_retries):
            try:
                provider = AI_PROVIDERS.get(provider_name)
                if not provider:
                    continue
                
                text, used_provider = provider.generate(prompt, system_instruction)
                print(f"✅ {used_provider} success on attempt {attempt + 1}")
                return text, used_provider, True
            
            except Exception as e:
                err_msg = str(e).lower()
                wait_time = (2 ** attempt) + random.uniform(0, 1)  # exponential backoff
                
                is_transient = any(x in err_msg for x in ["503", "unavailable", "deadline_exceeded", "timeout"])
                if is_transient and attempt < max_retries - 1:
                    print(f"⏳ {provider_name} transient error, retrying in {wait_time:.1f}s...")
                    time.sleep(wait_time)
                    continue
                
                print(f"❌ {provider_name} failed: {e}")
                break
    
    # All AI providers failed
    return None, "Local", False

@st.cache_data(ttl=3600)
def get_cached_ai_report(layer: str, roi_name: str, first_year: int, last_year: int, 
                        first_val: float, last_val: float, high_area: float) -> Tuple[str, str, bool]:
    """
    Cached AI report generation (1 hour TTL).
    """
    meta = CONFIG["layer_meta"][layer]
    prompt = (
        f"Viết 1 đoạn báo cáo khoa học (khoảng 160 chữ, tiếng Việt) về {roi_name} "
        f"trong giai đoạn {first_year}–{last_year}. "
        f"Chỉ số viễn thám {layer} ({meta['env_context']}) thay đổi từ {first_val:.3f} sang {last_val:.3f}. "
        f"Diện tích vùng nguy cơ cao: {high_area:,.0f} Ha. "
        f"Viết theo phong cách học thuật: nêu xu hướng, phân tích nguyên nhân, "
        f"cảnh báo môi trường cụ thể, đề xuất quy hoạch đô thị bền vững. "
        f"Không dùng gạch đầu dòng. Không dùng Markdown."
    )
    
    text, provider, is_ai = call_ai_with_retry(
        prompt=prompt,
        system_instruction="You are an expert in Urban Dynamics and Remote Sensing. Provide responses in Vietnamese.",
        max_retries=3
    )
    
    return text, provider, is_ai


def generate_gemini_report(layer, first_year, last_year, first_val, last_val, high_area, roi_name):
    """
    Tạo báo cáo với fallback chain:
    1. Gemini (primary) → OpenAI (secondary) → Local generation (fallback)
    """
    ai_report_mode = str(get_streamlit_secret("AI_REPORT_MODE", os.environ.get("AI_REPORT_MODE", "instant"))).strip().lower()
    if ai_report_mode in ("instant", "local", "offline", ""):
        st.session_state.last_report_provider = "Expert System"
        st.session_state.last_report_is_ai = False
        return generate_local_report(
            layer, first_year, last_year, first_val, last_val, high_area, roi_name,
            "không chờ API để đảm bảo báo cáo hiển thị ngay và chỉ dùng số liệu đã tính trong hệ thống"
        )

    report_text, provider_used, is_ai_generated = get_cached_ai_report(
        layer, roi_name, first_year, last_year, first_val, last_val, high_area
    )
    
    # AI providers failed, use local generation
    if not is_ai_generated:
        report_text = generate_local_report(
            layer, first_year, last_year, first_val, last_val, high_area, roi_name,
            f"Tất cả AI providers không khả dụng. Sử dụng báo cáo hệ thống."
        )
        # Store status in session for UI feedback
        st.session_state.last_report_provider = "Local (System)"
        st.session_state.last_report_is_ai = False
    else:
        # AI provider succeeded
        st.session_state.last_report_provider = provider_used
        st.session_state.last_report_is_ai = True
    
    return report_text

# ─── AI CHATBOT — context-rich Q&A ───────────────────────────────────────────
def _build_chat_context(lat, lon, address, params, result, weather):
    parts = [f"📍 Vị trí: {address or 'không rõ'} ({lat:.4f}, {lon:.4f})"]

    if weather and weather.get("current"):
        w = weather["current"]
        parts.append("\n🌤️ Thời tiết hiện tại:")
        parts.append(f"  • Nhiệt độ: {w.get('temp','?')}°C")
        parts.append(f"  • Gió:     {w.get('wind','?')} km/h")
        parts.append(f"  • Độ ẩm:   {w.get('humidity','?')}%")

    if weather and weather.get("forecast"):
        fcs = weather["forecast"][:7]
        if fcs:
            parts.append("\n📅 Dự báo 7 ngày tới:")
            for f in fcs:
                parts.append(
                    f"  • {f['date']}: {f.get('min_t','?')}°C–{f.get('max_t','?')}°C, "
                    f"mưa {f.get('rain_prob','?')}%"
                )

    if params:
        parts.append(f"\n📊 Phân tích GIS đang chạy:")
        parts.append(f"  • Quốc gia: {params.country}")
        if params.sub_regions:
            parts.append(f"  • Vùng:     {', '.join(params.sub_regions)}")
        parts.append(f"  • Chỉ số:   {params.layer}")
        parts.append(f"  • Tháng:    {params.month}")
        parts.append(f"  • Các năm:  {', '.join(params.years_multi)}")

    if result:
        stats_last = result.get("stats_last") or {}
        stats_first = result.get("stats_first") or {}
        m_last = stats_last.get(f"{params.layer}_mean") if params else None
        m_first = stats_first.get(f"{params.layer}_mean") if params else None
        if m_first is not None and m_last is not None:
            parts.append(f"\n📈 Số liệu chính ({params.layer}):")
            parts.append(f"  • Năm {result.get('first_y','?')} mean: {m_first:.4f}")
            parts.append(f"  • Năm {result.get('last_y','?')} mean: {m_last:.4f}")
            parts.append(f"  • Δ = {m_last - m_first:+.4f}")
        # Trend list
        td = result.get("trend_data") or []
        if td:
            tline = ", ".join(f"{r['Năm']}={r['Trị số']:.3f}" for r in td)
            parts.append(f"  • Chuỗi xu hướng: {tline}")
        # Region bar data
        bd = result.get("bar_data") or []
        if bd:
            parts.append(f"\n🌐 So sánh vùng (mean năm cuối):")
            for r in bd:
                parts.append(f"  • {r['Khu vực']}: {r['Trị số']:.3f}")

    # Click-point indices
    if address and params:
        # Click point có dữ liệu NDVI/NDBI/LST trong click_info
        ci = st.session_state.get("map_click_value") or {}
        if any(ci.get(k) is not None for k in ("NDVI","NDBI","LST")):
            parts.append(f"\n📍 Chỉ số tại điểm click:")
            for k in ("NDVI","NDBI","LST"):
                v = ci.get(k)
                if v is not None:
                    suffix = " °C" if k == "LST" else ""
                    parts.append(f"  • {k}: {v:.4f}{suffix}")

    return "\n".join(parts)


def get_chat_suggested_questions(params=None, result=None, has_click: bool = False) -> list:
    layer = params.layer if params else "chỉ số"
    questions = [
        f"Tóm tắt {layer}",
        f"Xu hướng {layer}",
        "So sánh vùng",
        "Rủi ro cao nhất",
        "Dự báo 2035",
        "Khuyến nghị quy hoạch",
    ]
    if has_click:
        questions.insert(0, "Điểm vừa click")
        questions.insert(1, "Thời tiết tuần tới")
    return questions[:8]


def answer_basic_data_question(user_message: str, lat: float, lon: float,
                               address: str, params, result, weather) -> Optional[str]:
    """Fast deterministic answers for common data questions, before calling external AI."""
    if not params or not result:
        return None

    msg = (user_message or "").lower()
    stats_last = result.get("stats_last") or {}
    stats_first = result.get("stats_first") or {}
    first_y, last_y = result.get("first_y", "?"), result.get("last_y", "?")
    layer = params.layer
    m_last = stats_last.get(f"{layer}_mean")
    m_first = stats_first.get(f"{layer}_mean")
    area_last = result.get("area_last") or []
    bad_classes = {"NDVI": (1, 2), "NDBI": (3, 4), "LST": (3, 4)}[layer]
    total_area = sum(float(g.get("sum") or 0) for g in area_last)
    risk_area = sum(float(g.get("sum") or 0) for g in area_last if int(g.get("group", 0)) in bad_classes)
    risk_pct = (risk_area / total_area * 100) if total_area > 0 else 0

    def trend_sentence():
        if m_first is None or m_last is None:
            return "Chuỗi số liệu chưa đủ để tính xu hướng trung bình."
        delta = m_last - m_first
        pct = (delta / abs(m_first) * 100) if m_first else None
        direction = "tăng" if delta > 0 else "giảm" if delta < 0 else "gần như không đổi"
        status, _ = layer_status(layer, m_last)
        pct_text = f", tương đương {pct:+.1f}%" if pct is not None else ""
        return (
            f"{layer} trung bình {direction} từ {fmt_val(layer, m_first)} năm {first_y} "
            f"đến {fmt_val(layer, m_last)} năm {last_y} (Δ={delta:+.4f}{pct_text}). "
            f"Trạng thái hiện tại: {status}."
        )

    if any(k in msg for k in ("tóm tắt", "tong quan", "tổng quan", "khái quát", "data", "dữ liệu", "du lieu")):
        roi = result.get("roi_names", params.country)
        return (
            f"📌 Tổng quan {roi}: {trend_sentence()} "
            f"Diện tích nhóm rủi ro theo {layer} hiện khoảng {risk_area:,.0f} ha, chiếm {risk_pct:.1f}% vùng phân tích. "
            f"Dữ liệu đang dùng tháng {params.month}, giai đoạn {first_y}-{last_y}."
        )

    if any(k in msg for k in ("xu hướng", "xu huong", "tăng", "giảm", "trend", "so với")):
        return f"📈 {trend_sentence()}"

    if any(k in msg for k in ("so sánh", "so sanh", "vùng nào", "vung nao", "cao nhất", "thấp nhất", "rủi ro cao")):
        bd = result.get("bar_data") or []
        valid = [r for r in bd if r.get("Trị số") is not None]
        if not valid:
            return "Cần chọn từ 2 vùng trở lên để so sánh theo vùng."
        high = max(valid, key=lambda r: r["Trị số"])
        low = min(valid, key=lambda r: r["Trị số"])
        return (
            f"🌐 So sánh vùng theo {layer}: {high.get('Khu vực')} cao nhất ({high.get('Trị số'):.3f}), "
            f"{low.get('Khu vực')} thấp nhất ({low.get('Trị số'):.3f}). "
            f"Với NDVI, giá trị cao thường tốt hơn; với NDBI/LST, giá trị cao thường cần theo dõi hơn."
        )

    if any(k in msg for k in ("thời tiết", "thoi tiet", "mưa", "mua", "gió", "gio", "nhiệt", "weather")):
        if not weather or not weather.get("current"):
            return None
        w = weather["current"]
        text = (
            f"⛅ Hiện tại khoảng {w.get('temp', '?')}°C, gió {w.get('wind', '?')} km/h, "
            f"độ ẩm {w.get('humidity', '?')}% tại {address or f'{lat:.4f}, {lon:.4f}'}."
        )
        fc = weather.get("forecast") or []
        rainy = [d for d in fc[:7] if (d.get("rain_prob") or 0) >= 50]
        if rainy:
            days = ", ".join(f"{d.get('date')} ({d.get('rain_prob')}%)" for d in rainy[:3])
            text += f" Khả năng mưa đáng chú ý: {days}."
        else:
            text += " 7 ngày tới chưa thấy ngày nào có xác suất mưa vượt 50%."
        return text

    if any(k in msg for k in ("2035", "dự báo", "du bao", "dự đoán", "du doan", "tương lai")):
        return (
            f"🔮 Dự báo 2035 nằm trong tab Dự báo 2035. Cách đọc nhanh: vùng rủi ro hiện là "
            f"{risk_area:,.0f} ha ({risk_pct:.1f}%); nếu xu hướng {layer} bất lợi tiếp diễn, cần ưu tiên "
            f"khoanh vùng can thiệp từ giai đoạn 2027-2030 rồi đo hiệu quả đến 2035."
        )

    if any(k in msg for k in ("khuyến nghị", "khuyen nghi", "giải pháp", "giai phap", "quy hoạch", "ưu tiên", "uu tien")):
        if layer == "NDVI":
            action = "bảo vệ lõi xanh, tăng cây bóng mát, phục hồi hành lang sinh thái và hạn chế chuyển đổi đất xanh."
        elif layer == "NDBI":
            action = "kiểm soát mật độ xây dựng, tăng bề mặt thấm nước, bổ sung hạ tầng xanh-xanh dương và giám sát điểm bê tông hóa."
        else:
            action = "tăng che phủ cây xanh, giảm vật liệu hấp thụ nhiệt, bổ sung mặt nước và ưu tiên vùng nóng liên tục."
        return f"🧭 Khuyến nghị theo {layer}: {action} Ưu tiên trước các khu có diện tích rủi ro cao ({risk_area:,.0f} ha)."

    click = st.session_state.get("map_click_value") or {}
    if click and any(k in msg for k in ("click", "điểm", "diem", "tọa độ", "toa do", "ở đây", "o day")):
        vals = []
        for k in ("NDVI", "NDBI", "LST"):
            v = click.get(k)
            if v is not None:
                suffix = "°C" if k == "LST" else ""
                vals.append(f"{k}={v:.3f}{suffix}")
        if vals:
            return f"📍 Điểm đã click tại {address or f'{lat:.4f}, {lon:.4f}'} có " + ", ".join(vals) + "."

    return None


def ai_chat_reply(user_message: str, lat: float, lon: float,
                  address: str, params, result, weather) -> str:
    """
    AI chat reply với fallback chain: Gemini → OpenAI → Local generation.
    Có retry + exponential backoff như generate_gemini_report.
    """
    basic_reply = answer_basic_data_question(user_message, lat, lon, address, params, result, weather)
    if basic_reply:
        return basic_reply

    context = _build_chat_context(lat, lon, address, params, result, weather)
    prompt = f"""Bạn là chuyên gia GIS môi trường & thời tiết của hệ thống Urban Dynamics Intelligence Platform.

DỮ LIỆU THỰC TẾ (từ Earth Engine + Open-Meteo):
{context}

NGUYÊN TẮC TRẢ LỜI:
1. Trả lời ngắn gọn 2-5 câu, tự nhiên, tiếng Việt.
2. Trích NGUYÊN VĂN con số từ DỮ LIỆU trên — không bịa, không làm tròn quá mức.
3. Nếu câu hỏi không liên quan môi trường/khí hậu/đô thị/GIS/thời tiết → lịch sự từ chối: "Xin lỗi, tôi chỉ tư vấn về môi trường, đô thị và thời tiết tại địa điểm này."
4. Dùng 1-2 emoji nhẹ. KHÔNG dùng tiêu đề markdown (#), KHÔNG dùng bullet (-) trừ khi liệt kê ≥3 mục.

Câu hỏi từ người dùng:
{user_message}
"""
    
    # Try AI providers with fallback chain
    ai_response, provider_used, is_ai = call_ai_with_retry(
        prompt=prompt,
        system_instruction="You are an expert in GIS, environment, and weather. Respond in Vietnamese.",
        max_retries=3
    )
    
    if is_ai and ai_response:
        return ai_response.strip()
    
    # All AI providers failed, use local fallback
    return local_chat_reply(user_message, lat, lon, address, params, result, weather, 
                           f"Tất cả AI providers không khả dụng (Gemini + OpenAI)")


def local_chat_reply(user_message: str, lat: float, lon: float,
                     address: str, params, result, weather, reason: str = "") -> str:
    """Fallback chat that works without Gemini, using only computed app data."""
    msg = (user_message or "").lower()
    lines = []
    prefix = "Mình trả lời bằng bộ phân tích nội bộ vì Gemini đang lỗi hoặc hết quota."
    if reason:
        prefix += f" Lý do: {reason}."
    lines.append(prefix)

    if address:
        lines.append(f"Vị trí đang xét là {address} ({lat:.4f}, {lon:.4f}).")

    if weather and weather.get("current") and any(k in msg for k in ("thời tiết", "mưa", "nhiệt", "gió", "ẩm", "weather")):
        w = weather["current"]
        lines.append(
            f"Thời tiết hiện tại: khoảng {w.get('temp', '?')}°C, gió {w.get('wind', '?')} km/h, "
            f"độ ẩm {w.get('humidity', '?')}%."
        )
        fc = weather.get("forecast") or []
        if fc:
            rainy = [d for d in fc[:7] if (d.get("rain_prob") or 0) >= 50]
            if rainy:
                days = ", ".join(f"{d.get('date')} ({d.get('rain_prob')}%)" for d in rainy[:3])
                lines.append(f"Trong 7 ngày tới có khả năng mưa đáng chú ý vào: {days}.")
            else:
                lines.append("Dự báo 7 ngày tới chưa thấy ngày nào có xác suất mưa vượt 50%.")

    if result and params:
        stats_last = result.get("stats_last") or {}
        stats_first = result.get("stats_first") or {}
        first_y, last_y = result.get("first_y", "?"), result.get("last_y", "?")
        m_last = stats_last.get(f"{params.layer}_mean")
        m_first = stats_first.get(f"{params.layer}_mean")
        if m_first is not None and m_last is not None:
            delta = m_last - m_first
            direction = "tăng" if delta > 0 else "giảm" if delta < 0 else "gần như không đổi"
            status, _ = layer_status(params.layer, m_last)
            lines.append(
                f"Về {params.layer}, giá trị trung bình {direction} từ {fmt_val(params.layer, m_first)} "
                f"năm {first_y} lên {fmt_val(params.layer, m_last)} năm {last_y} (Δ={delta:+.4f}); "
                f"đánh giá hiện tại: {status}."
            )
            if any(k in msg for k in ("đô thị", "xây dựng", "bê tông", "ndbi")) and params.layer != "NDBI":
                lines.append("Nếu muốn đánh giá đô thị hóa trực tiếp hơn, hãy chạy thêm lớp NDBI vì NDBI nhạy với bề mặt xây dựng.")
            if any(k in msg for k in ("cây", "xanh", "trồng", "ndvi")):
                lines.append("Nếu khu vực có NDVI thấp hoặc LST cao, ưu tiên tăng cây xanh, bóng mát và bề mặt thấm nước.")
            if any(k in msg for k in ("nóng", "đảo nhiệt", "lst", "nhiệt")):
                lines.append("Nếu LST cao, cần theo dõi đảo nhiệt đô thị, đặc biệt ở các vùng bề mặt bê tông dày và ít cây xanh.")

        bd = result.get("bar_data") or []
        if bd and any(k in msg for k in ("so sánh", "vùng nào", "cao nhất", "thấp nhất")):
            valid = [r for r in bd if r.get("Trị số") is not None]
            if valid:
                high = max(valid, key=lambda r: r["Trị số"])
                low = min(valid, key=lambda r: r["Trị số"])
                lines.append(
                    f"So sánh vùng: {high.get('Khu vực')} đang cao nhất ({high.get('Trị số'):.3f}), "
                    f"còn {low.get('Khu vực')} thấp nhất ({low.get('Trị số'):.3f})."
                )

    if len(lines) == 1:
        lines.append("Bạn hãy chạy phân tích hoặc click một điểm trên bản đồ để mình có thêm dữ liệu thời tiết, NDVI, NDBI và LST để trả lời cụ thể hơn.")

    return " ".join(lines)


# ─── ACADEMIC AUTO-ANALYSIS ──────────────────────────────────────────────────
def auto_academic_analysis(layer, first_val, last_val, high_area, roi_name):
    """
    Sinh nhận xét học thuật tự động dựa trên ngưỡng chuẩn từng chỉ số.
    Trả về dict với 5 chiều phân tích.
    """
    delta    = last_val - first_val if (first_val and last_val) else 0
    pct      = (delta / first_val * 100) if first_val and first_val != 0 else 0
    trend_vn = "tăng" if delta > 0 else "giảm"
    meta     = CONFIG["layer_meta"][layer]
    icon     = meta["icon"]

    if layer == "NDVI":
        tech = (f"Chỉ số NDVI (Normalized Difference Vegetation Index) phản ánh mật độ quang hợp "
                f"của thực vật. Khu vực {roi_name} ghi nhận NDVI {trend_vn} "
                f"{abs(pct):.1f}% trong giai đoạn phân tích (Δ = {delta:+.3f}). "
                f"Giá trị NDVI < 0.2 đặc trưng cho đất trống/bê tông; > 0.5 là rừng rậm.")
        plain = (f"Thực phủ xanh {'đang suy giảm' if delta < 0 else 'đang phục hồi'}. "
                 f"Giá trị hiện tại {last_val:.3f} {'thấp' if last_val < 0.3 else 'trung bình'} "
                 f"so với ngưỡng lành mạnh (> 0.4).")
        significance = ("Suy giảm NDVI liên quan trực tiếp đến mở rộng không gian đô thị, "
                        "thu hẹp diện tích cây xanh, ảnh hưởng đến vi khí hậu và chất lượng không khí."
                        if delta < 0 else
                        "Tăng NDVI cho thấy mảng xanh đô thị được cải thiện, "
                        "góp phần giảm nhiệt độ bề mặt và tăng khả năng hấp thụ CO₂.")
        warning = ("⚠️ CẢNH BÁO: Nếu xu hướng suy giảm thực vật tiếp diễn, "
                   "nguy cơ mất cân bằng sinh thái đô thị, gia tăng hiệu ứng đảo nhiệt "
                   f"và giảm chất lượng không khí tại {roi_name}."
                   if delta < -0.05 else
                   "ℹ️ Tình trạng thực vật tương đối ổn định hoặc cải thiện. "
                   "Cần duy trì và mở rộng diện tích cây xanh.")
        recommend = ("📌 Khuyến nghị: Quy hoạch 30% diện tích đô thị là mảng xanh, "
                     "áp dụng mái xanh (green roof), hành lang sinh thái và vành đai cây xanh "
                     "xung quanh khu công nghiệp.")

    elif layer == "NDBI":
        tech = (f"Chỉ số NDBI (Normalized Difference Built-up Index) định lượng mức độ bê tông hóa. "
                f"NDBI {trend_vn} {abs(pct):.1f}% tại {roi_name} (Δ = {delta:+.3f}). "
                f"Giá trị NDBI > 0.2 chỉ ra mật độ xây dựng cao, > 0.4 là lõi đô thị nén.")
        plain = (f"Diện tích xây dựng và bê tông hóa {'đang mở rộng nhanh' if delta > 0 else 'đang giảm nhẹ'}. "
                 f"NDBI hiện tại {last_val:.3f} {'cao' if last_val > 0.2 else 'thấp-trung bình'}.")
        significance = ("Tăng NDBI phản ánh quá trình đô thị hóa, mở rộng khu dân cư và công nghiệp. "
                        "Bề mặt không thấm nước tăng dẫn đến ngập úng đô thị và gia tăng dòng chảy."
                        if delta > 0 else
                        "Giảm NDBI có thể liên quan đến tái xanh hóa hoặc thay đổi sử dụng đất.")
        warning = ("🚨 CẢNH BÁO: Tốc độ bê tông hóa nhanh sẽ làm tăng nguy cơ ngập lụt đô thị, "
                   "ô nhiễm nguồn nước và gia tăng nhiệt độ bề mặt (UHI)."
                   if delta > 0.05 else
                   "ℹ️ Mức độ đô thị hóa đang được kiểm soát hoặc tăng trưởng chậm.")
        recommend = ("📌 Khuyến nghị: Quy hoạch tỷ lệ phủ xanh tối thiểu 25%, "
                     "thiết kế vỉa hè thấm nước, hành lang thoát nước xanh và "
                     "giới hạn hệ số sử dụng đất (FAR) ở khu vực nguy cơ cao.")

    else:  # LST
        tech = (f"Chỉ số LST (Land Surface Temperature) phản ánh nhiệt độ bề mặt vật lý. "
                f"LST {trend_vn} {abs(pct):.1f}% tại {roi_name} (Δ = {delta:+.2f}°C). "
                f"Ngưỡng nguy hiểm: LST > 34°C (vùng đảo nhiệt cực đoan), "
                f"diện tích vùng nóng hiện nay: {high_area:,.0f} Ha.")
        plain = (f"Nhiệt độ bề mặt {'đang tăng lên' if delta > 0 else 'đang giảm nhẹ'}. "
                 f"Nhiệt độ trung bình {last_val:.2f}°C "
                 f"{'vượt ngưỡng an toàn 34°C' if last_val > 34 else 'trong mức kiểm soát'}.")
        significance = ("Gia tăng LST là dấu hiệu rõ ràng của Hiệu ứng Đảo nhiệt Đô thị (UHI). "
                        "Nhiệt độ bề mặt cao làm tăng tiêu thụ năng lượng điều hòa không khí, "
                        "ảnh hưởng sức khỏe cộng đồng và thay đổi vi khí hậu đô thị."
                        if delta > 0 else
                        "Giảm LST cho thấy nỗ lực xanh hóa hoặc thay đổi cấu trúc bề mặt.")
        warning = ("🚨 CẢNH BÁO: Khu vực đang có dấu hiệu đảo nhiệt đô thị (UHI). "
                   f"Diện tích bị ảnh hưởng (>29°C): {high_area:,.0f} Ha. "
                   "Nguy cơ sức khỏe cộng đồng cao nếu không có biện pháp can thiệp."
                   if delta > 1.0 or last_val > 30 else
                   "ℹ️ Nhiệt độ bề mặt tương đối ổn định. Theo dõi chặt trong mùa khô.")
        recommend = ("📌 Khuyến nghị: Tăng tỷ lệ mảng xanh và mặt nước đô thị, "
                     "sử dụng vật liệu phản xạ nhiệt cho mái nhà và đường phố, "
                     "quy hoạch hành lang gió tự nhiên và thiết kế cảnh quan nước.")

    return {
        "technical":       tech,
        "plain":           plain,
        "significance":    significance,
        "warning":         warning,
        "recommendation":  recommend,
    }

def render_analysis_box(analysis: dict):
    """Render academic analysis box với 5 chiều."""
    rows = [
        ("📐", "Phân tích kỹ thuật",       analysis["technical"]),
        ("💡", "Giải thích dễ hiểu",        analysis["plain"]),
        ("🌍", "Ý nghĩa thực tế",          analysis["significance"]),
        ("⚠️", "Cảnh báo môi trường",       analysis["warning"]),
        ("🏙️", "Đề xuất quy hoạch",        analysis["recommendation"]),
    ]
    html_rows = ""
    for icon, label, text in rows:
        html_rows += f"""
        <div class='analysis-row'>
            <span class='analysis-icon'>{icon}</span>
            <div><div class='analysis-label'>{label}</div>{text}</div>
        </div>"""
    st.markdown(f"<div class='analysis-box'>{html_rows}</div>", unsafe_allow_html=True)

def safe_filename(text: str, fallback: str = "bao-cao") -> str:
    """Tạo tên file an toàn cho nút tải xuống."""
    value = re.sub(r"[^\w\-]+", "_", str(text or ""), flags=re.UNICODE).strip("_")
    return value[:80] or fallback

def build_beautiful_report_html(
    params,
    result: dict,
    analysis: dict,
    ai_report: str,
    first_y,
    last_y,
    l_mean_first,
    l_mean_last,
    delta_mean,
    a_high,
    status,
    color_st,
) -> str:
    """Dựng báo cáo HTML tự chứa, có thể mở bằng trình duyệt hoặc in ra PDF."""
    meta = CONFIG["layer_meta"][params.layer]
    esc = lambda v: html.escape(str(v if v is not None else ""))
    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")
    roi = result.get("roi_names", "")
    accuracy = compute_trend_accuracy_summary(result, params.layer)

    trend_rows = ""
    for row in result.get("trend_data", []):
        trend_rows += (
            f"<tr><td>{esc(row.get('Năm', ''))}</td>"
            f"<td>{fmt_val(params.layer, row.get('Trị số'))}</td></tr>"
        )

    class_rows = ""
    labels = CONFIG["class_labels"][params.layer]
    palette = CONFIG["vis"][params.layer]["palette"]
    for idx, label in enumerate(labels, start=1):
        first_area = extract_area(result.get("area_first"), idx)
        last_area = extract_area(result.get("area_last"), idx)
        delta_area = last_area - first_area
        class_rows += f"""
        <tr>
            <td><span class="swatch" style="background:{palette[idx - 1]}"></span>{esc(label)}</td>
            <td>{first_area:,.0f}</td>
            <td>{last_area:,.0f}</td>
            <td class="{'pos' if delta_area >= 0 else 'neg'}">{delta_area:+,.0f}</td>
        </tr>"""

    region_rows = ""
    for row in result.get("bar_data", []):
        region_rows += (
            f"<tr><td>{esc(row.get('Khu vực', ''))}</td>"
            f"<td>{fmt_val(params.layer, row.get('Trị số'))}</td></tr>"
        )

    analysis_rows = "".join(
        f"<section><h2>{label}</h2><p>{esc(analysis[key])}</p></section>"
        for key, label in [
            ("technical", "Phân tích kỹ thuật"),
            ("plain", "Diễn giải dễ hiểu"),
            ("significance", "Ý nghĩa thực tế"),
            ("warning", "Cảnh báo môi trường"),
            ("recommendation", "Đề xuất quy hoạch"),
        ]
    )
    ai_section = (
        f"<section><h2>Báo cáo AI Gemini</h2><p>{esc(ai_report)}</p></section>"
        if ai_report else ""
    )
    accuracy_section = (
        f"<section><h2>Độ chính xác mô hình</h2><p>{esc(accuracy['summary'])}</p></section>"
    )

    return f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Báo cáo {esc(params.layer)} - {esc(roi)}</title>
<style>
  :root {{ --primary:#4f46e5; --accent:#0891b2; --text:#0f172a; --muted:#64748b; --border:#e2e8f0; --soft:#f8fafc; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#eef2f7; color:var(--text); font-family:Arial, Helvetica, sans-serif; line-height:1.6; }}
  .page {{ width:min(1080px, 100%); margin:28px auto; background:#fff; border:1px solid var(--border); box-shadow:0 24px 70px rgba(15,23,42,.12); }}
  .hero {{ padding:36px 42px 30px; color:white; background:linear-gradient(135deg,#1e293b,#4f46e5 55%,#0891b2); }}
  .eyebrow {{ font-size:12px; letter-spacing:1.6px; text-transform:uppercase; opacity:.86; font-weight:700; }}
  h1 {{ margin:12px 0 8px; font-size:34px; line-height:1.15; letter-spacing:0; }}
  .subtitle {{ margin:0; max-width:760px; opacity:.96; color:#f8fafc; }}
  .hero p {{ color:#f8fafc; }}
  .meta {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:26px; }}
  .meta div {{ border:1px solid rgba(255,255,255,.22); background:rgba(255,255,255,.12); border-radius:8px; padding:12px; }}
  .label {{ display:block; color:#64748b; font-size:11px; text-transform:uppercase; font-weight:700; letter-spacing:.7px; }}
  .hero .label {{ color:#dbeafe; }}
  .value {{ display:block; margin-top:4px; font-size:17px; font-weight:800; }}
  main {{ padding:30px 42px 42px; }}
  .kpis {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin-bottom:24px; }}
  .kpi {{ border:1px solid var(--border); border-top:4px solid var(--primary); border-radius:8px; padding:14px; background:var(--soft); }}
  .kpi b {{ display:block; margin-top:8px; font-size:24px; line-height:1.2; }}
  h2 {{ margin:26px 0 10px; font-size:18px; color:#1e293b; border-bottom:1px solid var(--border); padding-bottom:8px; }}
  p {{ margin:0 0 12px; color:#334155; text-align:justify; }}
  table {{ width:100%; border-collapse:collapse; margin:10px 0 18px; font-size:14px; }}
  th {{ background:#f1f5f9; color:#334155; text-align:left; font-size:12px; text-transform:uppercase; letter-spacing:.5px; }}
  th, td {{ border:1px solid var(--border); padding:10px 12px; vertical-align:top; }}
  .swatch {{ display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:8px; vertical-align:-1px; }}
  .pos {{ color:#059669; font-weight:700; }}
  .neg {{ color:#dc2626; font-weight:700; }}
  footer {{ padding:18px 42px; background:#f8fafc; border-top:1px solid var(--border); color:var(--muted); font-size:12px; }}
  @media print {{ body {{ background:white; }} .page {{ margin:0; width:100%; box-shadow:none; border:none; }} }}
  @media (max-width:760px) {{ .meta, .kpis {{ grid-template-columns:1fr 1fr; }} .hero, main, footer {{ padding-left:20px; padding-right:20px; }} h1 {{ font-size:26px; }} }}
</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="eyebrow">Urban Dynamics Intelligence Platform</div>
    <h1>Báo cáo phân tích {esc(params.layer)} - {esc(roi)}</h1>
    <p class="subtitle">Báo cáo tổng hợp chỉ số viễn thám, biến động diện tích phân lớp và khuyến nghị quy hoạch đô thị bền vững.</p>
    <div class="meta">
      <div><span class="label">Quốc gia</span><span class="value">{esc(params.country)}</span></div>
      <div><span class="label">Khu vực</span><span class="value">{esc(roi)}</span></div>
      <div><span class="label">Giai đoạn</span><span class="value">{esc(first_y)} - {esc(last_y)}</span></div>
      <div><span class="label">Tháng phân tích</span><span class="value">{esc(params.month)}</span></div>
    </div>
  </header>
  <main>
    <div class="kpis">
      <div class="kpi"><span class="label">Khởi điểm</span><b>{fmt_val(params.layer, l_mean_first)}</b></div>
      <div class="kpi"><span class="label">Hiện tại</span><b style="color:{meta['color']}">{fmt_val(params.layer, l_mean_last)}</b></div>
      <div class="kpi"><span class="label">Biến động</span><b class="{'pos' if delta_mean >= 0 else 'neg'}">{delta_mean:+.4f}</b></div>
      <div class="kpi"><span class="label">Đánh giá</span><b style="color:{color_st}">{esc(status)}</b></div>
    </div>
    <section>
      <h2>Tóm tắt thống kê</h2>
      <table>
        <tr><th>Chỉ tiêu</th><th>Giá trị</th></tr>
        <tr><td>Chỉ số phân tích</td><td>{esc(params.layer)} - {esc(meta['env_context'])}</td></tr>
        <tr><td>Diện tích nguy cơ cao</td><td>{a_high:,.0f} Ha</td></tr>
        <tr><td>Độ chính xác</td><td>{esc(accuracy['label'])}</td></tr>
        <tr><td>Thời điểm xuất báo cáo</td><td>{generated_at}</td></tr>
      </table>
    </section>
    {ai_section}
    {accuracy_section}
    {analysis_rows}
    <section>
      <h2>Xu hướng theo thời gian</h2>
      <table><tr><th>Năm</th><th>{esc(params.layer)}</th></tr>{trend_rows or '<tr><td colspan="2">Không có dữ liệu</td></tr>'}</table>
    </section>
    <section>
      <h2>Cơ cấu diện tích phân lớp</h2>
      <table><tr><th>Lớp</th><th>{esc(first_y)} (Ha)</th><th>{esc(last_y)} (Ha)</th><th>Biến động (Ha)</th></tr>{class_rows}</table>
    </section>
    <section>
      <h2>So sánh vùng</h2>
      <table><tr><th>Khu vực</th><th>Giá trị</th></tr>{region_rows or '<tr><td colspan="2">Không có dữ liệu so sánh vùng</td></tr>'}</table>
    </section>
  </main>
  <footer>Báo cáo được tạo tự động từ dữ liệu Google Earth Engine và mô hình phân tích trong ứng dụng.</footer>
</div>
</body>
</html>"""


def build_pdf_report(
    params,
    result: dict,
    analysis: dict,
    ai_report: str,
    first_y,
    last_y,
    l_mean_first,
    l_mean_last,
    delta_mean,
    a_high,
    status,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_name = "Helvetica"
    bold_font = "Helvetica-Bold"
    font_candidates = [
        (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        ("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"),
    ]
    for regular_path, bold_path in font_candidates:
        if os.path.exists(regular_path):
            try:
                pdfmetrics.registerFont(TTFont("AppUnicode", regular_path))
                font_name = "AppUnicode"
                if os.path.exists(bold_path):
                    pdfmetrics.registerFont(TTFont("AppUnicodeBold", bold_path))
                    bold_font = "AppUnicodeBold"
                else:
                    bold_font = "AppUnicode"
                break
            except Exception:
                pass

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.5 * cm, rightMargin=1.5 * cm,
        topMargin=1.4 * cm, bottomMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportTitle", fontName=bold_font, fontSize=18, leading=23, alignment=TA_CENTER, textColor=colors.HexColor("#1e293b"), spaceAfter=12))
    styles.add(ParagraphStyle(name="SectionTitle", fontName=bold_font, fontSize=12.5, leading=16, textColor=colors.HexColor("#4f46e5"), spaceBefore=12, spaceAfter=7))
    styles.add(ParagraphStyle(name="BodyVi", fontName=font_name, fontSize=9.5, leading=14, alignment=TA_JUSTIFY, textColor=colors.HexColor("#334155")))
    styles.add(ParagraphStyle(name="SmallVi", fontName=font_name, fontSize=8.5, leading=12, textColor=colors.HexColor("#475569")))

    def p(text, style="BodyVi"):
        safe = html.escape(str(text if text is not None else "")).replace("\n", "<br/>")
        return Paragraph(safe, styles[style])

    def small_table(rows, widths=None):
        table = Table([[p(c, "SmallVi") for c in row] for row in rows], colWidths=widths)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eef2ff")),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        return table

    roi = result.get("roi_names", "")
    meta = CONFIG["layer_meta"][params.layer]
    accuracy = compute_trend_accuracy_summary(result, params.layer)
    story = [
        Paragraph(f"Báo cáo phân tích {params.layer} - {roi}", styles["ReportTitle"]),
        small_table([
            ["Quốc gia", params.country],
            ["Khu vực", roi],
            ["Giai đoạn", f"{first_y} - {last_y}"],
            ["Tháng phân tích", params.month],
            ["Chỉ số", f"{params.layer} - {meta['env_context']}"],
        ], widths=[4.0 * cm, 13.0 * cm]),
        Spacer(1, 10),
        small_table([
            ["Chỉ tiêu", "Giá trị"],
            ["Giá trị khởi điểm", fmt_val(params.layer, l_mean_first)],
            ["Giá trị hiện tại", fmt_val(params.layer, l_mean_last)],
            ["Biến động trung bình", f"{delta_mean:+.4f}"],
            ["Diện tích nguy cơ", f"{a_high:,.0f} Ha"],
            ["Đánh giá", status],
            ["Độ chính xác", accuracy["label"]],
        ], widths=[6.0 * cm, 11.0 * cm]),
    ]

    if ai_report:
        story += [Paragraph("Báo cáo chuyên sâu", styles["SectionTitle"]), p(ai_report)]

    story += [Paragraph("Độ chính xác mô hình", styles["SectionTitle"]), p(accuracy["summary"])]

    for key, label in [
        ("technical", "Phân tích kỹ thuật"),
        ("plain", "Diễn giải dễ hiểu"),
        ("significance", "Ý nghĩa thực tế"),
        ("warning", "Cảnh báo môi trường"),
        ("recommendation", "Đề xuất quy hoạch"),
    ]:
        if analysis.get(key):
            story += [Paragraph(label, styles["SectionTitle"]), p(analysis[key])]

    trend_rows = [["Năm", params.layer]]
    for row in result.get("trend_data", []):
        trend_rows.append([row.get("Năm", ""), fmt_val(params.layer, row.get("Trị số"))])
    if len(trend_rows) > 1:
        story += [Paragraph("Xu hướng theo thời gian", styles["SectionTitle"]), small_table(trend_rows)]

    doc.build(story)
    return buf.getvalue()

# ─── MAP BUILDING ─────────────────────────────────────────────────────────────
def add_legend(m, layer):
    html = (f"<div style='position:fixed;bottom:36px;left:36px;z-index:9999;"
            f"background:rgba(255,255,255,0.96);backdrop-filter:blur(12px);"
            f"padding:14px 18px;border-radius:12px;border:1px solid rgba(0,0,0,0.08);"
            f"box-shadow:0 8px 25px rgba(15,23,42,0.12);'>"
            f"<div style='color:#0f172a;font-size:12px;font-weight:800;margin-bottom:8px;"
            f"text-transform:uppercase;letter-spacing:0.8px;'>Phân lớp {layer}</div>")
    for label, color in zip(CONFIG["class_labels"][layer], CONFIG["vis"][layer]["palette"]):
        html += (f"<div style='display:flex;align-items:center;margin-bottom:6px;'>"
                 f"<div style='background:{color};width:14px;height:14px;border-radius:3px;"
                 f"margin-right:10px;flex-shrink:0;'></div>"
                 f"<span style='font-size:12px;font-weight:500;color:#334155;'>{label}</span></div>")
    m.get_root().html.add_child(folium.Element(html + "</div>"))

def _resolve_tile_url(image, vis_params):
    """Server call: trả về URL template tile của 1 EE image+vis."""
    if vis_params:
        mid = ee.data.getMapId({"image": image.visualize(**vis_params)})
    else:
        mid = ee.data.getMapId({"image": image})
    return mid["tile_fetcher"].url_format

def parallel_add_ee_layers(m, specs):
    """
    OPT1: gọi getMapId() song song cho tất cả layer thay vì tuần tự.
    specs: list of dict(image, vis, name, visible=True, opacity=1.0).
    """
    def _resolve(spec):
        return _resolve_tile_url(spec["image"], spec.get("vis") or {})
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(specs)))) as pool:
        urls = list(pool.map(_resolve, specs))
    out_layers = []
    for spec, url in zip(specs, urls):
        tl = folium.raster_layers.TileLayer(
            tiles=url, attr="Google Earth Engine",
            name=spec["name"], overlay=True, control=True,
            show=spec.get("visible", True),
            opacity=spec.get("opacity", 1.0),
            max_zoom=24,
        )
        if m is not None:
            tl.add_to(m)
        out_layers.append(tl)
    return out_layers

def _mask_spec(roi):
    return {
        "image":   ee.Image(1).updateMask(ee.Image.constant(1).clip(roi).mask().Not()),
        "vis":     {"palette": ["#cbd5e1"]},
        "name":    "Lớp nền",
        "visible": True,
        "opacity": 0.45,
    }

def _boundary_spec(roi):
    return {
        "image":   ee.Image().paint(roi, 0, 2),
        "vis":     {"palette": ["#4f46e5"]},
        "name":    "Ranh giới",
        "visible": True,
        "opacity": 1.0,
    }

def base_map():
    m = folium.Map(
        location=st.session_state.get("map_center", [16.0, 106.0]),
        zoom_start=st.session_state.get("map_zoom", 6),
        control_scale=True, tiles=None,
    )
    folium.TileLayer("CartoDB.Positron",      name="Light Map",      overlay=False, control=True).add_to(m)
    folium.TileLayer("CartoDB.DarkMatter",    name="Dark Map",       overlay=False, control=True).add_to(m)
    folium.TileLayer("Esri.WorldImagery",     name="Ảnh vệ tinh",   overlay=False, control=True).add_to(m)
    MousePosition(position="bottomright", separator=" | ", prefix="Tọa độ:").add_to(m)
    return m

def _compute_roi_view(geom):
    """Lấy bounds ROI 1 lần để cache vào session_state, dùng cho mọi map rebuild."""
    try:
        coords = geom.bounds().coordinates().getInfo()[0]
        lats = [pt[1] for pt in coords]
        lons = [pt[0] for pt in coords]
        bbox = [[min(lats), min(lons)], [max(lats), max(lons)]]
        center = [(min(lats) + max(lats)) / 2, (min(lons) + max(lons)) / 2]
        span = max(max(lats) - min(lats), max(lons) - min(lons))
        # estimate zoom từ span (°)
        if   span > 30:  zoom = 3
        elif span > 15:  zoom = 4
        elif span > 7:   zoom = 5
        elif span > 3.5: zoom = 6
        elif span > 1.8: zoom = 7
        elif span > 0.9: zoom = 8
        elif span > 0.45:zoom = 9
        elif span > 0.2: zoom = 10
        elif span > 0.1: zoom = 11
        else:            zoom = 12
        return center, zoom, bbox
    except Exception:
        return [16.0, 106.0], 6, None

def center_map(m, result):
    """Fit chính xác vào bounds đã cache."""
    bbox = st.session_state.get("map_bounds")
    if bbox:
        try:
            m.fit_bounds(bbox)
        except Exception:
            pass

def add_click_popup(m, click_info, layer):
    """FIX: fmt_val được gọi trong hàm, không nằm trong f-string của outer scope."""
    if not click_info:
        return
    lat  = click_info["lat"]
    lon  = click_info["lon"]
    addr = click_info.get("address", "Đang cập nhật...")
    v_ndvi = fmt_val("NDVI", click_info.get("NDVI"))
    v_ndbi = fmt_val("NDBI", click_info.get("NDBI"))
    v_lst  = fmt_val("LST",  click_info.get("LST"))

    popup_html = f"""
    <div style="background:rgba(255,255,255,0.98);backdrop-filter:blur(12px);
         border:1px solid rgba(0,0,0,0.08);border-radius:14px;
         padding:16px;width:250px;color:#0f172a;font-family:'Space Grotesk',sans-serif;
         box-shadow:0 12px 30px rgba(15,23,42,0.15);">
      <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;">📍 Điểm định vị</div>
      <div style="font-size:12px;font-weight:600;color:#0f172a;line-height:1.4;margin-bottom:3px;">{addr[:50]}...</div>
      <div style="font-size:10px;color:#64748b;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid rgba(0,0,0,0.06);">({lat:.4f}, {lon:.4f})</div>
      <div style="display:flex;justify-content:space-between;margin-bottom:7px;">
        <span style="font-size:11px;color:#059669;font-weight:600;">🌿 NDVI</span>
        <span style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#0f172a;">{v_ndvi}</span>
      </div>
      <div style="display:flex;justify-content:space-between;margin-bottom:7px;">
        <span style="font-size:11px;color:#ea580c;font-weight:600;">🏢 NDBI</span>
        <span style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#0f172a;">{v_ndbi}</span>
      </div>
      <div style="display:flex;justify-content:space-between;">
        <span style="font-size:11px;color:#dc2626;font-weight:600;">🌡️ LST</span>
        <span style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#0f172a;">{v_lst}</span>
      </div>
    </div>"""
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html, max_width=300, show=True),
        icon=folium.Icon(color="red", icon="map-marker"),
    ).add_to(m)

def build_single_map(result, layer, display_year, click_info=None):
    m = base_map()
    parallel_add_ee_layers(m, [
        _mask_spec(result["roi"]),
        {"image": result["year_data"][display_year]["class"],
         "vis":   CONFIG["vis"][layer],
         "name":  f"Phân loại {layer}", "visible": True, "opacity": 0.9},
        _boundary_spec(result["roi"]),
    ])
    add_legend(m, layer)
    if click_info:
        add_click_popup(m, click_info, layer)
    center_map(m, result)
    return m

def build_swipe_map(result, layer, left_year, right_year, click_info=None):
    m = base_map()
    # OPT1: resolve 4 tile URL song song
    mask_tl, left_tl, right_tl, bound_tl = parallel_add_ee_layers(None, [
        _mask_spec(result["roi"]),
        {"image": result["year_data"][left_year]["class"],
         "vis":   CONFIG["vis"][layer],
         "name":  f"{layer} {left_year}",  "visible": True, "opacity": 1.0},
        {"image": result["year_data"][right_year]["class"],
         "vis":   CONFIG["vis"][layer],
         "name":  f"{layer} {right_year}", "visible": True, "opacity": 1.0},
        _boundary_spec(result["roi"]),
    ])
    # FIX: SideBySideLayers cần 2 layer trái/phải được add_to(m) TRƯỚC để JS có biến tham chiếu
    mask_tl.add_to(m)
    left_tl.add_to(m)
    right_tl.add_to(m)
    SideBySideLayers(left_tl, right_tl).add_to(m)
    bound_tl.add_to(m)
    add_legend(m, layer)
    if click_info:
        add_click_popup(m, click_info, layer)
    center_map(m, result)
    return m

def build_change_map(result, layer, left_year, right_year, click_info=None):
    m = base_map()
    change = (result["year_data"][right_year]["image"].select(layer)
              .subtract(result["year_data"][left_year]["image"].select(layer)))

    if layer == "NDVI":
        vis = {"min": -0.3, "max": 0.3, "palette": ["#dc2626", "#ffffff", "#059669"]}
        legend_neg, legend_pos = "🔴 Giảm thực vật", "🟢 Tăng thực vật"
    elif layer == "NDBI":
        vis = {"min": -0.2, "max": 0.2, "palette": ["#059669", "#ffffff", "#dc2626"]}
        legend_neg, legend_pos = "🟢 Giảm bê tông", "🔴 Tăng đô thị hóa"
    else:
        vis = {"min": -4, "max": 4, "palette": ["#2563eb", "#ffffff", "#dc2626"]}
        legend_neg, legend_pos = "🔵 Giảm nhiệt", "🔴 Tăng nhiệt"

    parallel_add_ee_layers(m, [
        _mask_spec(result["roi"]),
        {"image": change.clip(result["geom"]), "vis": vis,
         "name":  f"Biến động {left_year}→{right_year}", "visible": True, "opacity": 0.9},
        _boundary_spec(result["roi"]),
    ])

    legend_html = f"""
    <div style="position:fixed;bottom:36px;left:36px;z-index:9999;
         background:rgba(255,255,255,0.96);backdrop-filter:blur(12px);
         padding:16px;border-radius:12px;border:1px solid rgba(0,0,0,0.08);
         box-shadow:0 8px 25px rgba(15,23,42,0.12);">
      <div style="color:#0f172a;font-size:12px;font-weight:800;margin-bottom:10px;">📍 Dấu vết Biến động</div>
      <div style="color:#334155;font-size:12px;font-weight:600;margin-bottom:6px;">{legend_neg}</div>
      <div style="color:#334155;font-size:12px;font-weight:600;margin-bottom:6px;">⚪ Không đổi</div>
      <div style="color:#334155;font-size:12px;font-weight:600;">{legend_pos}</div>
    </div>"""
    m.get_root().html.add_child(folium.Element(legend_html))
    if click_info:
        add_click_popup(m, click_info, layer)
    center_map(m, result)
    return m

# ─── CHART RENDERING FUNCTIONS ───────────────────────────────────────────────
def render_chart_weather(click_val):
    if not click_val or not isinstance(click_val.get("weather"), dict):
        st.info("📍 Click vào một điểm trên bản đồ để xem thông tin thời tiết thực tế.")
        return
    weather = click_val["weather"]
    w_curr = weather.get("current", {})
    w_fore = weather.get("forecast") or []

    st.markdown(f"**📍 Vị trí:** `{click_val.get('address','')}`")
    c1, c2, c3 = st.columns(3)
    temp = w_curr.get("temp")
    wind = w_curr.get("wind")
    hum = w_curr.get("humidity")
    c1.metric("🌡️ Nhiệt độ", f"{temp if temp is not None else '—'} °C")
    c2.metric("💨 Gió", f"{wind if wind is not None else '—'} km/h")
    c3.metric("💧 Độ ẩm", f"{hum if hum is not None else '—'} %")

    if not w_fore:
        st.info("Không có dữ liệu dự báo 7 ngày từ Open-Meteo.")
        return

    st.markdown("<div style='font-size:12px;font-weight:700;color:#f59e0b;margin:12px 0 8px;'>Dự báo 7 ngày tới</div>", unsafe_allow_html=True)
    df_f = pd.DataFrame(w_fore)
    if df_f.empty:
        st.info("Không có dữ liệu dự báo 7 ngày.")
        return

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_f["date"], y=df_f["max_t"],
        mode="lines+markers+text",
        name="Cao nhất",
        line=dict(color="#ef4444", width=2),
        text=df_f["max_t"].apply(lambda x: f"{x:.0f}°" if x is not None else "—"),
        textposition="top center", textfont=dict(size=10),
    ))
    fig.add_trace(go.Scatter(
        x=df_f["date"], y=df_f["min_t"],
        mode="lines+markers+text",
        name="Thấp nhất",
        line=dict(color="#3b82f6", width=2),
        text=df_f["min_t"].apply(lambda x: f"{x:.0f}°" if x is not None else "—"),
        textposition="bottom center", textfont=dict(size=10),
    ))
    fig.update_layout(height=240, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis_type="category", legend=dict(orientation="h", y=1.12), **PD)
    fig.update_yaxes(showticklabels=False, showgrid=False)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def render_chart_trend(result, params):
    """FIX: Thêm confidence interval + cải thiện Prophet chart."""
    if not result["trend_data"] or len(result["trend_data"]) < 3:
        st.info("Chọn ≥ 3 năm để AI dự báo xu hướng.")
        return

    try:
        df_t = pd.DataFrame(result["trend_data"])
        df_p = df_t.rename(columns={"Năm": "ds", "Trị số": "y"})
        df_p["ds"] = pd.to_datetime(df_p["ds"], format="%Y")

        # ── Backtest: nếu ≥ 5 năm, đánh giá MAPE/RMSE bằng train/test split ──
        eval_m = evaluate_prophet_series(
            years=df_t["Năm"].tolist(),
            values=df_t["Trị số"].tolist(),
            test_size=2,
        )
        if eval_m:
            mape = eval_m.get("MAPE")
            rmse = eval_m.get("RMSE")
            if mape is not None:
                if mape < 5:
                    tier_label, tier_color = "Rất chính xác", "#059669"
                elif mape < 15:
                    tier_label, tier_color = "Chính xác", "#0891b2"
                elif mape < 30:
                    tier_label, tier_color = "Chấp nhận được", "#d97706"
                else:
                    tier_label, tier_color = "Sai số cao", "#dc2626"
            else:
                tier_label, tier_color = "—", "#64748b"

            test_yrs = " · ".join(str(y) for y in eval_m.get("test_years", []))
            mape_str = f"{mape:.2f}%" if mape is not None else "—"
            rmse_str = f"{rmse:.4f}" if rmse is not None else "—"
            st.markdown(
                f"<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:10px;'>"
                f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;'>"
                f"    <div style='font-size:9px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;'>MAPE Backtest</div>"
                f"    <div style='font-size:17px;font-weight:700;color:{tier_color};font-family:JetBrains Mono;'>{mape_str}</div>"
                f"    <div style='font-size:9.5px;color:{tier_color};font-weight:600;'>{tier_label}</div>"
                f"  </div>"
                f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;'>"
                f"    <div style='font-size:9px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;'>RMSE</div>"
                f"    <div style='font-size:17px;font-weight:700;color:#334155;font-family:JetBrains Mono;'>{rmse_str}</div>"
                f"    <div style='font-size:9.5px;color:#64748b;font-weight:600;'>Đơn vị {params.layer}</div>"
                f"  </div>"
                f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;'>"
                f"    <div style='font-size:9px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;'>Phương pháp</div>"
                f"    <div style='font-size:11.5px;font-weight:700;color:#334155;line-height:1.3;'>Train {eval_m.get('n_train')} năm</div>"
                f"    <div style='font-size:9.5px;color:#64748b;font-weight:600;'>Test {eval_m.get('n_test')}: {test_yrs}</div>"
                f"  </div>"
                f"</div>",
                unsafe_allow_html=True,
            )

        m = Prophet(yearly_seasonality=False, weekly_seasonality=False,
                    daily_seasonality=False, interval_width=0.95)
        m.fit(df_p)
        future   = m.make_future_dataframe(periods=5, freq="YS")
        forecast = m.predict(future)
        forecast["Năm"] = forecast["ds"].dt.strftime("%Y")
        df_fut = forecast[forecast["ds"] > df_p["ds"].max()].copy()

        fig = go.Figure()

        # Confidence interval cho dự báo
        fig.add_trace(go.Scatter(
            x=list(df_fut["Năm"]) + list(df_fut["Năm"])[::-1],
            y=list(df_fut["yhat_upper"]) + list(df_fut["yhat_lower"])[::-1],
            fill="toself", fillcolor="rgba(249,115,22,0.12)",
            line=dict(color="rgba(0,0,0,0)"),
            name="95% CI", showlegend=True,
        ))

        # Historical
        fig.add_trace(go.Scatter(
            x=df_t["Năm"], y=df_t["Trị số"],
            mode="lines+markers+text", name="📊 Thực tế",
            line=dict(color="#6366f1", width=3),
            marker=dict(size=7, color="#6366f1"),
            text=df_t["Trị số"].apply(lambda x: f"{x:.3f}"),
            textposition="top center", textfont=dict(size=9, color="#818cf8"),
        ))

        # Forecast line
        fig.add_trace(go.Scatter(
            x=df_fut["Năm"], y=df_fut["yhat"],
            mode="lines+markers+text", name="✨ Dự báo 5 năm",
            line=dict(color="#f97316", width=3, dash="dash"),
            marker=dict(size=7, color="#f97316"),
            text=df_fut["yhat"].apply(lambda x: f"{x:.3f}"),
            textposition="top center", textfont=dict(size=9, color="#f97316"),
        ))

        fig.update_layout(height=280, margin=dict(l=10,r=10,t=30,b=10),
                          xaxis_type="category",
                          legend=dict(orientation="h", y=1.12, font_size=11), **PD)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        start_val = df_t.iloc[0]["Trị số"]
        end_val   = df_t.iloc[-1]["Trị số"]
        trend_str = "tăng" if end_val > start_val else "giảm"
        delta_abs = abs(end_val - start_val)
        delta_pct = delta_abs / abs(start_val) * 100 if start_val != 0 else 0
        next_forecast = df_fut.iloc[0]["yhat"] if not df_fut.empty else None

        comment = (f"**📈 Xu hướng:** Chỉ số **{params.layer}** có xu hướng **{trend_str}** "
                   f"qua các năm (Δ = {end_val - start_val:+.3f}, tương đương {delta_pct:.1f}%). "
                   f"Mô hình Prophet dự báo năm kế tiếp sẽ đạt "
                   f"**{next_forecast:.3f}** ± {df_fut.iloc[0]['yhat_upper'] - df_fut.iloc[0]['yhat']:.3f} "
                   f"(khoảng tin cậy 95%)."
                   if next_forecast else f"Xu hướng: **{trend_str}** ({delta_pct:.1f}%).")
        st.info(comment)

    except Exception as e:
        st.warning(f"Lỗi dự báo Prophet: {e}")


def render_chart_histogram(result, params, l_mean_last):
    """FIX: Thêm KDE curve bằng scipy.stats.gaussian_kde."""
    hist = result["hist_last"]
    if not hist or "histogram" not in hist:
        st.info("Không có dữ liệu histogram.")
        return

    counts  = hist["histogram"]
    buckets = [hist["bucketMin"] + i * hist["bucketWidth"] for i in range(len(counts))]

    meta  = CONFIG["layer_meta"][params.layer]
    color = meta["color"]

    # Reconstruct approximate distribution for KDE
    samples = []
    for b, c in zip(buckets, counts):
        if c > 0:
            samples.extend([b] * int(c))

    fig = go.Figure()

    # Bars
    fig.add_trace(go.Bar(
        x=buckets, y=counts, name="Phân bố",
        marker_color=color, marker_opacity=0.7,
        marker_line_color="rgba(0,0,0,0)",
    ))

    # KDE curve
    if len(samples) >= 5:
        try:
            kde  = scipy_stats.gaussian_kde(samples, bw_method=0.4)
            xs   = np.linspace(min(buckets), max(buckets), 200)
            ys   = kde(xs) * sum(counts) * hist["bucketWidth"]
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", name="KDE",
                line=dict(color="#f8fafc", width=2.5),
            ))
        except:
            pass

    # Mean line
    fig.add_vline(x=l_mean_last, line_dash="dash", line_color="#f59e0b", line_width=2,
                  annotation_text=f"μ = {l_mean_last:.2f}", annotation_font_size=11,
                  annotation_font_color="#f59e0b")

    fig.update_layout(height=260, margin=dict(l=10,r=10,t=10,b=10),
                      bargap=0.05, legend=dict(orientation="h", y=1.1, font_size=11), **PD)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Statistical commentary
    mean_v = l_mean_last
    std_v  = np.std(samples) if samples else 0
    skew   = scipy_stats.skew(samples) if len(samples) >= 5 else 0
    skew_str = "phân bố lệch phải (nhiều vùng có giá trị cao)" if skew > 0.5 else \
               ("phân bố lệch trái (nhiều vùng có giá trị thấp)" if skew < -0.5 else "phân bố đối xứng")

    st.info(f"📊 **Phân tích phân bố:** Trung bình μ = **{mean_v:.3f}**, "
            f"Độ lệch chuẩn σ = **{std_v:.3f}**. "
            f"Biểu đồ cho thấy {skew_str}. "
            f"Khoảng 68% diện tích khu vực nằm trong [{mean_v-std_v:.3f}, {mean_v+std_v:.3f}].")


def render_chart_pie(result, params):
    """FIX: Cải thiện pie chart với delta so năm đầu."""
    pie_data = []
    for i in range(4):
        area_last  = extract_area(result["area_last"], i + 1)
        area_first = extract_area(result.get("area_first", []), i + 1)
        if area_last > 0:
            pie_data.append({
                "Lớp":      CONFIG["class_labels"][params.layer][i],
                "Ha":       area_last,
                "Ha_first": area_first,
                "Màu":      CONFIG["vis"][params.layer]["palette"][i],
                "Delta":    area_last - area_first,
            })

    if not pie_data:
        st.info("Không có dữ liệu diện tích.")
        return

    total    = sum(d["Ha"] for d in pie_data)
    max_slice = max(pie_data, key=lambda x: x["Ha"])

    fig = go.Figure(go.Pie(
        labels=[d["Lớp"] for d in pie_data],
        values=[d["Ha"]  for d in pie_data],
        hole=0.62,
        marker=dict(colors=[d["Màu"] for d in pie_data],
                    line=dict(color="#ffffff", width=2)),
        textposition="outside",
        textinfo="label+percent",
        textfont=dict(size=11),
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} Ha<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        height=290, margin=dict(l=30, r=30, t=20, b=10), showlegend=False,
        annotations=[dict(
            text=f"Tổng<br><b>{int(total):,} Ha</b>",
            x=0.5, y=0.5, font_size=13, font_color="#0f172a", showarrow=False,
        )],
        **PD,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # Delta table
    st.markdown("<div style='font-size:11px;font-weight:700;color:#64748b;margin:8px 0 6px;text-transform:uppercase;letter-spacing:0.5px;'>Biến động diện tích so với năm đầu</div>", unsafe_allow_html=True)
    for d in pie_data:
        arrow = "▲" if d["Delta"] > 0 else ("▼" if d["Delta"] < 0 else "—")
        color = "#10b981" if d["Delta"] < 0 else "#ef4444" if d["Delta"] > 0 else "#64748b"
        # Đảo chiều màu: với NDVI tăng là tốt, NDBI/LST tăng là xấu
        if params.layer == "NDVI":
            color = "#10b981" if d["Delta"] > 0 else "#ef4444" if d["Delta"] < 0 else "#64748b"
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;font-size:12px;"
            f"padding:4px 0;border-bottom:1px solid rgba(0,0,0,0.06);'>"
            f"<span style='color:#334155;'>{d['Lớp']}</span>"
            f"<span style='color:{color};font-weight:700;font-family:monospace;'>"
            f"{arrow} {abs(d['Delta']):,.0f} Ha</span></div>",
            unsafe_allow_html=True,
        )

    st.info(f"📊 **Hiện trạng:** **{max_slice['Lớp']}** chiếm ưu thế "
            f"(**{max_slice['Ha']:,.0f} Ha**, {max_slice['Ha']/total*100:.1f}% tổng diện tích). "
            f"Biến động lớn nhất: {max(pie_data, key=lambda x: abs(x['Delta']))['Lớp']} "
            f"({max(pie_data, key=lambda x: abs(x['Delta']))['Delta']:+,.0f} Ha).")


def render_chart_uhi(result, params):
    """
    FIX HOÀN TOÀN:
    - Bỏ trendline='ols' (yêu cầu statsmodels)
    - Dùng sklearn LinearRegression trực tiếp
    - Thêm R², equation, confidence band
    - Scatter đẹp với gradient màu theo năm
    """
    df_u = st.session_state.get("current_df_hist")

    if df_u is None:
        st.info("📍 Click vào một điểm trên bản đồ để tải dữ liệu tương quan UHI.")
        return
    if df_u.empty:
        st.warning("⚠️ Không lấy được dữ liệu lịch sử tại điểm này. Hãy click lại điểm khác hoặc bấm 🚀 KHỞI CHẠY để fetch lại.")
        return

    # FIX: chỉ cần NDVI + LST cho hồi quy UHI. NDBI dùng làm marker size là tùy chọn.
    df_clean = df_u.dropna(subset=["NDVI", "LST"]).copy()
    if len(df_clean) < 3:
        st.warning(
            f"Cần ≥ 3 năm có đủ NDVI+LST để phân tích UHI tại điểm này. "
            f"Hiện chỉ có {len(df_clean)} năm (mây che / Landsat thiếu band ST_B10). "
            f"Hãy thử click một điểm khác hoặc đổi tháng đồng bộ."
        )
        return
    # NDBI có thể NaN — dùng 0 làm marker size fallback
    df_clean["NDBI"] = df_clean["NDBI"].fillna(0)

    # ── Sklearn regression ────────────────────────────────
    X_arr    = df_clean["NDVI"].values.reshape(-1, 1)
    y_arr    = df_clean["LST"].values
    model    = LinearRegression()
    model.fit(X_arr, y_arr)
    y_pred   = model.predict(X_arr)
    r2       = r2_score(y_arr, y_pred)
    coef     = model.coef_[0]
    intercept = model.intercept_

    # Trendline range
    x_line = np.linspace(df_clean["NDVI"].min(), df_clean["NDVI"].max(), 100)
    y_line = model.predict(x_line.reshape(-1, 1))

    # Confidence interval (95%) via residual std
    residuals = y_arr - y_pred
    std_err   = np.std(residuals)
    y_upper   = y_line + 1.96 * std_err
    y_lower   = y_line - 1.96 * std_err

    # ── Plotly figure ────────────────────────────────────
    fig = go.Figure()

    # CI band
    fig.add_trace(go.Scatter(
        x=list(x_line) + list(x_line[::-1]),
        y=list(y_upper) + list(y_lower[::-1]),
        fill="toself", fillcolor="rgba(99,102,241,0.1)",
        line=dict(color="rgba(0,0,0,0)"),
        name="CI 95%", showlegend=True,
    ))

    # Regression line
    fig.add_trace(go.Scatter(
        x=x_line, y=y_line, mode="lines", name="Hồi quy tuyến tính",
        line=dict(color="#6366f1", width=2.5, dash="dot"),
    ))

    # Scatter points colored by year
    colorscale = px.colors.sequential.Plasma
    years_list = sorted(df_clean["Năm"].unique())
    for i, yr in enumerate(years_list):
        sub = df_clean[df_clean["Năm"] == yr]
        c   = colorscale[int(i / max(len(years_list) - 1, 1) * (len(colorscale) - 1))]
        fig.add_trace(go.Scatter(
            x=sub["NDVI"], y=sub["LST"],
            mode="markers", name=str(yr),
            marker=dict(size=sub["NDBI"].abs() * 50 + 8,
                        color=c, opacity=0.85,
                        line=dict(color="rgba(255,255,255,0.2)", width=1)),
            hovertemplate=(f"<b>{yr}</b><br>NDVI: %{{x:.3f}}<br>"
                           f"LST: %{{y:.2f}}°C<br>NDBI: %{{customdata:.3f}}<extra></extra>"),
            customdata=sub["NDBI"],
        ))

    eq_label = (f"LST = {coef:.2f}·NDVI + {intercept:.2f}   |   R² = {r2:.3f}")
    fig.add_annotation(x=0.02, y=0.96, xref="paper", yref="paper",
                       text=eq_label, showarrow=False,
                       font=dict(size=11, color="#4f46e5", family="JetBrains Mono"),
                       bgcolor="rgba(248,250,252,0.92)", borderpad=5,
                       bordercolor="#e2e8f0", borderwidth=1)

    fig.update_layout(
        height=290, margin=dict(l=10,r=10,t=10,b=10),
        xaxis_title="NDVI (Chỉ số Thực vật)",
        yaxis_title="LST (°C)",
        legend=dict(orientation="h", y=1.12, font_size=10),
        **PD,
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Academic ML commentary ────────────────────────────
    trust = "cao (mô hình đáng tin cậy)" if r2 > 0.6 else \
            ("trung bình" if r2 > 0.35 else "thấp (dữ liệu phân tán rộng)")
    direction = "nghịch chiều (NDVI tăng → LST giảm, giảm đảo nhiệt)" \
                if coef < 0 else "thuận chiều (bất thường — cần kiểm tra dữ liệu)"

    st.info(
        f"**🤖 Phân tích ML (Scikit-learn LinearRegression):**\n\n"
        f"- **Phương trình:** `LST = {coef:.3f} × NDVI + {intercept:.3f}`\n"
        f"- **R² = {r2:.3f}** — Độ tin cậy **{trust}**\n"
        f"- **Mối quan hệ:** {direction}\n"
        f"- **Kết luận UHI:** Khi NDVI tăng 0.1 đơn vị, LST thay đổi "
        f"**{coef * 0.1:+.2f}°C** — {'minh chứng hiệu ứng đảo nhiệt đô thị' if coef < 0 else 'cần phân tích thêm'}."
    )


@st.fragment
def render_chart_chat(result, params):
    """
    Tab Hỏi AI: chat native Streamlit, isolated fragment.
    Context: vị trí điểm click + thời tiết + phân tích hiện tại.
    """
    if "chat_history" not in st.session_state:
        st.session_state["chat_history"] = []

    # Xác định vị trí context
    click = st.session_state.get("map_click_value")
    if click:
        lat, lon = click["lat"], click["lon"]
        address  = click.get("address", "")
        loc_label = f"📍 {address[:80] if address else 'Điểm đã click'}"
        loc_color = "#059669"
    elif result:
        bbox = st.session_state.get("map_bounds")
        if bbox:
            lat = (bbox[0][0] + bbox[1][0]) / 2
            lon = (bbox[0][1] + bbox[1][1]) / 2
        else:
            lat, lon = 16.0, 106.0
        address = result.get("roi_names", "")
        loc_label = f"🎯 Trung tâm {address} ({lat:.3f}, {lon:.3f})"
        loc_color = "#6366f1"
    else:
        lat, lon = 16.0, 106.0
        address = ""
        loc_label = "🌏 Mặc định: trung tâm Việt Nam"
        loc_color = "#94a3b8"

    # Header + data context
    context_place = html.escape(address[:96] if address else "Vùng đang phân tích")
    layer_label = html.escape(params.layer if params else "N/A")
    period_label = html.escape(
        f"{result.get('first_y', '?')}-{result.get('last_y', '?')}" if result else "Chưa có"
    )
    month_label = html.escape(str(params.month if params else "N/A"))
    source_label = "Điểm click" if click else "ROI trung tâm"
    st.markdown(
        f"""
        <div class="chat-shell">
          <div class="chat-top">
            <div>
              <div class="chat-title">Trợ lý dữ liệu GIS</div>
              <div class="chat-subtitle">Hỏi nhanh theo số liệu đang hiển thị. Các câu cơ bản trả lời tức thì, không chờ API.</div>
            </div>
            <div class="chat-mode">DATA MODE</div>
          </div>
          <div class="chat-chip-row">
            <span class="chat-chip"><strong>Vị trí</strong> · {context_place}</span>
            <span class="chat-chip"><strong>Nguồn</strong> · {source_label}</span>
            <span class="chat-chip"><strong>Lớp</strong> · {layer_label}</span>
            <span class="chat-chip"><strong>Giai đoạn</strong> · {period_label}</span>
            <span class="chat-chip"><strong>Tháng</strong> · {month_label}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    clear_col, spacer_col = st.columns([1, 5])
    with clear_col:
        if st.button("Xoá chat", key="chat_clear", use_container_width=True,
                     help="Xoá lịch sử chat"):
            st.session_state["chat_history"] = []
            st.rerun(scope="fragment")

    if not st.session_state["chat_history"]:
        st.markdown(
            "<div class='chat-empty'><strong>Bắt đầu bằng câu hỏi nhanh bên dưới.</strong> "
            "Bạn có thể hỏi về xu hướng, vùng rủi ro, dự báo 2035, thời tiết hoặc khuyến nghị quy hoạch.</div>",
            unsafe_allow_html=True,
        )

    quick_prompt = None
    suggestions = get_chat_suggested_questions(params, result, has_click=bool(click))
    st.markdown("<div class='chat-section-title'>Câu hỏi nhanh</div>", unsafe_allow_html=True)
    q_cols = st.columns(2)
    for i, question in enumerate(suggestions):
        if q_cols[i % 2].button(question, key=f"quick_chat_{i}", use_container_width=True):
            quick_prompt = question

    st.markdown("<div class='chat-divider'></div>", unsafe_allow_html=True)

    # Render lịch sử
    for msg in st.session_state["chat_history"]:
        avatar = "👤" if msg["role"] == "user" else "◎"
        with st.chat_message(msg["role"], avatar=avatar):
            st.markdown(msg["content"])

    # Input
    user_input = st.chat_input(
        "Nhập câu hỏi về dữ liệu, xu hướng, rủi ro, dự báo 2035...",
        key="chat_input_main",
    )
    if quick_prompt:
        user_input = quick_prompt

    if user_input:
        st.session_state["chat_history"].append(
            {"role": "user", "content": user_input}
        )
        with st.chat_message("user", avatar="👤"):
            st.markdown(user_input)

        with st.chat_message("assistant", avatar="◎"):
            with st.spinner("Đang đọc dữ liệu đang hiển thị..."):
                # Lấy weather (cache 30min đã có sẵn)
                try:
                    weather = get_forecast_weather(lat, lon)
                except Exception:
                    weather = None
                reply = ai_chat_reply(
                    user_input, lat, lon, address, params, result, weather
                )
            st.markdown(reply)

        st.session_state["chat_history"].append(
            {"role": "assistant", "content": reply}
        )


def render_chart_risk(result, params):
    """
    Urban Risk Score 0–100: gauge + components breakdown + per-region ranking.
    """
    risk = compute_risk_score(result, params)

    # ── 1. Gauge chart ────────────────────────────────────────────────
    gauge = go.Figure(go.Indicator(
        mode="gauge+number",
        value=risk["score"],
        number={"font": {"size": 36, "color": risk["color"]},
                "suffix": "/100"},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1, "tickcolor": "#94a3b8",
                     "tickfont": {"size": 10, "color": "#64748b"}},
            "bar": {"color": risk["color"], "thickness": 0.25},
            "bgcolor": "rgba(0,0,0,0)",
            "steps": [
                {"range": [0, 25],   "color": "rgba(5,150,105,0.18)"},
                {"range": [25, 50],  "color": "rgba(217,119,6,0.18)"},
                {"range": [50, 75],  "color": "rgba(220,38,38,0.18)"},
                {"range": [75, 100], "color": "rgba(124,45,18,0.22)"},
            ],
            "threshold": {
                "line": {"color": risk["color"], "width": 4},
                "thickness": 0.85, "value": risk["score"],
            },
        },
        title={"text": f"<b style='color:{risk['color']}'>{risk['label']}</b>",
               "font": {"size": 14}},
    ))
    gauge.update_layout(height=240, margin=dict(l=20, r=20, t=40, b=10), **PD)
    st.plotly_chart(gauge, use_container_width=True, config={"displayModeBar": False})

    # ── 2. Components breakdown ────────────────────────────────────────
    st.markdown("<div style='font-size:11px;font-weight:700;color:#64748b;"
                "margin:6px 0 6px;text-transform:uppercase;letter-spacing:0.5px;'>"
                "Phân tách 3 thành phần</div>", unsafe_allow_html=True)

    comps = list(risk["components"].items())
    weights = risk["weights"]
    comp_labels = [c[0] for c in comps]
    comp_values = [c[1] for c in comps]
    comp_weighted = [comp_values[i] * weights[comp_labels[i]] / 100 for i in range(3)]

    comp_fig = go.Figure()
    comp_fig.add_trace(go.Bar(
        x=comp_values, y=comp_labels, orientation="h",
        marker_color=["#6366f1", "#0891b2", "#d97706"],
        marker_opacity=0.85,
        text=[f"{v:.0f}/100 (w={weights[comp_labels[i]]}%)" for i, v in enumerate(comp_values)],
        textposition="outside", textfont=dict(size=10, color="#334155"),
        hovertemplate="<b>%{y}</b><br>Điểm: %{x:.1f}<br>"
                      f"Đóng góp: %{{customdata:.1f}} điểm<extra></extra>",
        customdata=comp_weighted,
    ))
    comp_fig.update_layout(height=160, margin=dict(l=10, r=80, t=10, b=10),
                           xaxis=dict(range=[0, 110], showgrid=False),
                           **PD)
    st.plotly_chart(comp_fig, use_container_width=True, config={"displayModeBar": False})

    # ── 3. Detailed reasoning ─────────────────────────────────────────
    layer = params.layer
    meta = CONFIG["layer_meta"][layer]
    raw = risk["raw"]
    direction = ("giảm" if raw["delta"] < 0 else "tăng")
    bad_dir = ("giảm" if meta["good_high"] else "tăng")
    is_worsening = direction == bad_dir
    trend_emoji = "📉" if (meta["good_high"] and raw["delta"] < 0) or (not meta["good_high"] and raw["delta"] > 0) else "📈"

    st.markdown(f"""
    <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px;
                padding:10px 12px; font-size:12px; line-height:1.6; color:#334155;
                margin-top:6px;">
      <b>{trend_emoji} Diễn giải:</b><br>
      • Giá trị {layer} hiện tại: <b>{fmt_val(layer, raw["current_value"])}</b><br>
      • Biến động: <b>{raw["delta"]:+.4f}</b> ({raw["pct_change"]:+.1f}%) — xu hướng
        <b style="color:{'#dc2626' if is_worsening else '#059669'}">{direction}</b>
        ({'xấu đi' if is_worsening else 'tích cực'})<br>
      • % diện tích nằm trong vùng nguy cơ (class 3-4):
        <b>{raw["high_pct"]:.1f}%</b> ({raw["high_area_ha"]:,.0f} Ha)
    </div>
    """, unsafe_allow_html=True)

    # ── 4. Per-region ranking nếu user chọn ≥ 2 vùng ────────────────────
    if params.sub_regions and len(params.sub_regions) >= 2:
        st.markdown("<div style='font-size:11px;font-weight:700;color:#64748b;"
                    "margin:14px 0 6px;text-transform:uppercase;letter-spacing:0.5px;'>"
                    "Xếp hạng rủi ro theo vùng</div>", unsafe_allow_html=True)
        with st.spinner("⏳ Đang tính điểm rủi ro cho từng vùng..."):
            try:
                regions = compute_per_region_risk(
                    params.country,
                    tuple(sorted(params.sub_regions)),
                    params.layer,
                    params.month,
                    tuple(sorted(params.years_multi)),
                )
            except Exception as e:
                st.warning(f"Không tính được dữ liệu từng vùng: {e}")
                regions = []

        if not regions:
            st.info("Không có dữ liệu cho từng vùng.")
            return

        # Sort by score desc
        regions.sort(key=lambda r: r["score"], reverse=True)

        # Bar chart
        df_r = pd.DataFrame(regions)
        bar_colors = []
        for s in df_r["score"]:
            if s < 25:   bar_colors.append("#059669")
            elif s < 50: bar_colors.append("#d97706")
            elif s < 75: bar_colors.append("#dc2626")
            else:        bar_colors.append("#7c2d12")
        rank_fig = go.Figure(go.Bar(
            x=df_r["score"], y=df_r["region"], orientation="h",
            marker_color=bar_colors, marker_opacity=0.9,
            text=df_r["score"].apply(lambda v: f"{v:.1f}"),
            textposition="outside", textfont=dict(size=11, color="#334155"),
            hovertemplate="<b>%{y}</b><br>Điểm Rủi Ro: %{x:.1f}<br>"
                          "%{customdata}<extra></extra>",
            customdata=[f"Δ {r['pct_change']:+.1f}% — Hiện trạng {r['current_component']:.0f} | "
                        f"Xu hướng {r['delta_component']:.0f}"
                        for r in regions],
        ))
        rank_fig.update_layout(
            height=max(150, len(regions) * 32),
            margin=dict(l=10, r=80, t=10, b=10),
            xaxis=dict(range=[0, 110], title="Điểm Rủi Ro (0-100)",
                       title_font_size=10, showgrid=False),
            **PD,
        )
        st.plotly_chart(rank_fig, use_container_width=True, config={"displayModeBar": False})

        # Top + bottom
        top = regions[0]
        bot = regions[-1]
        st.info(f"🚨 **Rủi ro cao nhất:** {top['region']} (điểm **{top['score']}/100**, "
                f"Δ {top['pct_change']:+.1f}%). "
                f"✅ **An toàn nhất:** {bot['region']} (điểm **{bot['score']}/100**, "
                f"Δ {bot['pct_change']:+.1f}%).")


def render_chart_forecast(result, params):
    """
    Tab Dự báo: Prophet AI dự đoán diện tích từng class đến 2030 & 2035.
    Hiển thị line chart history+forecast với CI band + 3 pie chart so sánh
    + bảng delta + cảnh báo môi trường tự động.
    """
    if params.country != result.get("_forecast_country", params.country) or \
       not params.sub_regions:
        pass  # dùng country alone vẫn OK

    with st.spinner("⏳ Đang tải lịch sử 9 năm + huấn luyện mô hình Prophet cho 4 lớp..."):
        try:
            df_hist = fetch_area_history(
                params.country,
                tuple(sorted(params.sub_regions)),
                params.layer,
                params.month,
            )
        except Exception as e:
            st.error(f"Lỗi tải lịch sử: {e}")
            return
        if df_hist.empty or df_hist[["class_1","class_2","class_3","class_4"]].dropna(how="all").empty:
            st.warning("Không lấy được lịch sử để dự báo.")
            return
        try:
            fc = forecast_land_use(df_hist, target_years=(2030, 2035))
        except Exception as e:
            st.error(f"Lỗi Prophet: {e}")
            return

    labels = CONFIG["class_labels"][params.layer]
    colors = CONFIG["vis"][params.layer]["palette"]
    classes = ["class_1", "class_2", "class_3", "class_4"]
    last_y = fc["last_hist_year"]

    # ── 0. Đánh giá độ chính xác mô hình Prophet (backtest) ────────────────
    eval_m = fc.get("eval_metrics", {})
    valid_evals = {c: m for c, m in eval_m.items() if m}
    avg_mape = None
    avg_rmse = None
    if valid_evals:
        # Trung bình MAPE qua các lớp có metric hợp lệ
        mape_vals = [m["MAPE"] for m in valid_evals.values() if m.get("MAPE") is not None]
        rmse_vals = [m["RMSE"] for m in valid_evals.values() if m.get("RMSE") is not None]
        avg_mape  = float(np.mean(mape_vals)) if mape_vals else None
        avg_rmse  = float(np.mean(rmse_vals)) if rmse_vals else None
        sample    = next(iter(valid_evals.values()))
        n_train, n_test = sample.get("n_train"), sample.get("n_test")
        test_yrs_str = " · ".join(str(y) for y in sample.get("test_years", []))

        # Đánh giá chất lượng theo ngưỡng MAPE
        if avg_mape is None:
            tier_label, tier_color = "N/A", "#64748b"
        elif avg_mape < 10:
            tier_label, tier_color = "Rất tốt", "#059669"
        elif avg_mape < 20:
            tier_label, tier_color = "Tốt", "#0891b2"
        elif avg_mape < 35:
            tier_label, tier_color = "Chấp nhận được", "#d97706"
        else:
            tier_label, tier_color = "Cần cải thiện", "#dc2626"

        st.markdown(
            f"<div style='font-size:11px;font-weight:700;color:#64748b;"
            f"margin:2px 0 6px;text-transform:uppercase;letter-spacing:0.5px;'>"
            f"📐 Độ chính xác mô hình Prophet (Backtest)</div>",
            unsafe_allow_html=True,
        )
        mape_str = f"{avg_mape:.1f}%" if avg_mape is not None else "—"
        rmse_str = f"{avg_rmse:,.0f} Ha" if avg_rmse is not None else "—"
        st.markdown(
            f"<div style='display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:14px;'>"
            f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;'>"
            f"    <div style='font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;'>MAPE trung bình</div>"
            f"    <div style='font-size:20px;font-weight:700;color:{tier_color};font-family:JetBrains Mono;'>{mape_str}</div>"
            f"    <div style='font-size:10px;color:{tier_color};font-weight:600;'>{tier_label}</div>"
            f"  </div>"
            f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;'>"
            f"    <div style='font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;'>RMSE trung bình</div>"
            f"    <div style='font-size:20px;font-weight:700;color:#334155;font-family:JetBrains Mono;'>{rmse_str}</div>"
            f"    <div style='font-size:10px;color:#64748b;font-weight:600;'>Sai số tuyệt đối</div>"
            f"  </div>"
            f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;'>"
            f"    <div style='font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;'>Phương pháp</div>"
            f"    <div style='font-size:13px;font-weight:700;color:#334155;'>Train {n_train} năm</div>"
            f"    <div style='font-size:10px;color:#64748b;font-weight:600;'>Test {n_test} năm: {test_yrs_str}</div>"
            f"  </div>"
            f"</div>",
            unsafe_allow_html=True,
        )

        # Bảng chi tiết MAPE/RMSE từng lớp
        with st.expander("📋 Chi tiết sai số từng lớp đất", expanded=False):
            rows = []
            for cls, lbl in zip(classes, labels):
                m = eval_m.get(cls) or {}
                rows.append({
                    "Lớp đất":  lbl,
                    "MAPE (%)": f"{m['MAPE']:.2f}" if m.get("MAPE") is not None else "—",
                    "RMSE (Ha)": f"{m['RMSE']:,.0f}" if m.get("RMSE") is not None else "—",
                    "MAE (Ha)":  f"{m['MAE']:,.0f}"  if m.get("MAE")  is not None else "—",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.caption(
                "💡 **MAPE** (Mean Absolute Percentage Error) — sai số trung bình theo %. "
                "Càng thấp càng tốt: <10% rất tốt, 10-20% tốt, 20-35% chấp nhận, >35% kém.  \n"
                "💡 **RMSE** (Root Mean Squared Error) — sai số tuyệt đối theo Ha, phạt mạnh các điểm lệch lớn."
            )
    else:
        st.caption("ℹ️ Chưa đủ dữ liệu để backtest mô hình (cần ≥ 5 năm có data hợp lệ).")

    # ── 1. Line chart history + forecast với CI band ────────────────────────
    fig = go.Figure()
    for cls, lbl, color in zip(classes, labels, colors):
        s = fc["series"].get(cls)
        if s is None:
            continue
        s_hist = s[s["year"] <= last_y]
        s_fut  = s[s["year"] >= last_y]
        # CI band cho phần forecast
        fig.add_trace(go.Scatter(
            x=list(s_fut["year"]) + list(s_fut["year"])[::-1],
            y=list(s_fut["yhat_upper"]) + list(s_fut["yhat_lower"])[::-1],
            fill="toself", fillcolor=f"rgba({int(color[1:3],16)},{int(color[3:5],16)},{int(color[5:7],16)},0.10)",
            line=dict(color="rgba(0,0,0,0)"),
            name=f"{lbl} CI", showlegend=False, hoverinfo="skip",
        ))
        # Lịch sử (đường liền)
        fig.add_trace(go.Scatter(
            x=s_hist["year"], y=s_hist["yhat"],
            mode="lines+markers", name=f"{lbl}",
            line=dict(color=color, width=2.5),
            marker=dict(size=6, color=color),
            hovertemplate=f"<b>{lbl}</b><br>%{{x}}: %{{y:,.0f}} Ha<extra></extra>",
        ))
        # Forecast (đường đứt)
        fig.add_trace(go.Scatter(
            x=s_fut["year"], y=s_fut["yhat"],
            mode="lines+markers", name=f"{lbl} dự báo",
            line=dict(color=color, width=2, dash="dash"),
            marker=dict(size=6, color=color, symbol="diamond"),
            showlegend=False,
            hovertemplate=f"<b>{lbl}</b><br>%{{x}} (dự báo): %{{y:,.0f}} Ha<extra></extra>",
        ))

    fig.add_vline(x=last_y, line_dash="dot", line_color="#94a3b8",
                  annotation_text=f"→ Dự báo từ {last_y+1}",
                  annotation_position="top right",
                  annotation_font_size=10, annotation_font_color="#64748b")

    fig.update_layout(height=320, margin=dict(l=10, r=10, t=20, b=10),
                      xaxis_title="Năm", yaxis_title="Diện tích (Ha)",
                      legend=dict(orientation="h", y=1.12, font_size=10),
                      hovermode="x unified", **PD)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── 2. Pie chart 3 năm so sánh (hiện tại / 2030 / 2035) ─────────────────
    st.markdown("<div style='font-size:11px;font-weight:700;color:#64748b;margin:14px 0 6px;text-transform:uppercase;letter-spacing:0.5px;'>Cơ cấu đất đai theo thời gian</div>", unsafe_allow_html=True)

    cur_row = df_hist[df_hist["year"] == last_y].iloc[0]
    snapshots = [
        (f"Năm {last_y}", {c: cur_row[c] for c in classes}),
        ("Dự báo 2030", {c: fc.get(2030, {}).get(c) for c in classes}),
        ("Dự báo 2035", {c: fc.get(2035, {}).get(c) for c in classes}),
    ]
    cols = st.columns(3)
    for col, (title, data) in zip(cols, snapshots):
        with col:
            values = [data.get(c) or 0 for c in classes]
            if sum(values) == 0:
                col.info(f"_{title}_\n\nThiếu dữ liệu")
                continue
            pie = go.Figure(go.Pie(
                labels=labels, values=values, hole=0.55,
                marker=dict(colors=colors, line=dict(color="#ffffff", width=1.5)),
                textinfo="percent", textfont=dict(size=9),
                hovertemplate="<b>%{label}</b><br>%{value:,.0f} Ha<br>%{percent}<extra></extra>",
            ))
            pie.update_layout(
                height=180, margin=dict(l=5, r=5, t=25, b=5), showlegend=False,
                title=dict(text=title, font_size=11, x=0.5,
                           font_color="#475569"),
                annotations=[dict(text=f"{int(sum(values)):,}<br>Ha",
                                  x=0.5, y=0.5, font_size=10,
                                  font_color="#0f172a", showarrow=False)],
                **PD,
            )
            col.plotly_chart(pie, use_container_width=True,
                             config={"displayModeBar": False})

    # ── 2b. Scenario cockpit 2035 ─────────────────────────────────────────
    scenario = build_2035_scenario_summary(
        params.layer, labels, classes, cur_row, fc, last_y, avg_mape
    )
    pressure_delta = scenario["pressure_2035"] - scenario["pressure_now"]
    dominant = scenario.get("dominant")
    dom_text = "Ổn định"
    if dominant:
        dom_text = f"{dominant[0]} {dominant[5]:+.1f}%"

    st.markdown(
        "<div style='font-size:11px;font-weight:700;color:#64748b;margin:14px 0 6px;"
        "text-transform:uppercase;letter-spacing:0.5px;'>Bảng điều khiển kịch bản 2035</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-bottom:12px;'>"
        f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;'>"
        f"    <div style='font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;'>Áp lực {scenario['pressure_name']}</div>"
        f"    <div style='font-size:20px;font-weight:800;color:#0f172a;font-family:JetBrains Mono;'>{scenario['pressure_2035']:.1f}%</div>"
        f"    <div style='font-size:10px;color:{'#dc2626' if pressure_delta > 0 else '#059669'};font-weight:700;'>{pressure_delta:+.1f} điểm % vs {last_y}</div>"
        f"  </div>"
        f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;'>"
        f"    <div style='font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;'>Vùng rủi ro 2035</div>"
        f"    <div style='font-size:20px;font-weight:800;color:#dc2626;font-family:JetBrains Mono;'>{scenario['bad_2035']:,.0f}</div>"
        f"    <div style='font-size:10px;color:#64748b;font-weight:700;'>Ha, {scenario['bad_pct']:+.1f}% vs {last_y}</div>"
        f"  </div>"
        f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;'>"
        f"    <div style='font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;'>Độ tin cậy</div>"
        f"    <div style='font-size:20px;font-weight:800;color:{scenario['confidence_color']};font-family:JetBrains Mono;'>{scenario['confidence_score']:.0f}/100</div>"
        f"    <div style='font-size:10px;color:{scenario['confidence_color']};font-weight:700;'>{scenario['confidence_label']} · CI {scenario['uncertainty_pct']:.1f}% diện tích</div>"
        f"  </div>"
        f"  <div style='background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;'>"
        f"    <div style='font-size:10px;color:#64748b;font-weight:700;text-transform:uppercase;'>Chuyển dịch lớn nhất</div>"
        f"    <div style='font-size:13px;font-weight:800;color:#0f172a;line-height:1.25;'>{dom_text}</div>"
        f"    <div style='font-size:10px;color:#64748b;font-weight:700;'>Horizon {scenario['horizon']} năm</div>"
        f"  </div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    scen_cols = st.columns(3)
    scen_colors = ["#0891b2", "#059669", "#dc2626"]
    total_2035 = max(sum(float(fc.get(2035, {}).get(c) or 0) for c in classes), 1)
    for col, item, color in zip(scen_cols, scenario["scenarios"], scen_colors):
        title, value, note = item
        pct_total = value / total_2035 * 100
        col.markdown(
            f"<div style='background:#ffffff;border:1px solid #e2e8f0;border-left:4px solid {color};"
            f"border-radius:8px;padding:10px 12px;min-height:96px;'>"
            f"<div style='font-size:12px;font-weight:800;color:#0f172a;'>{title}</div>"
            f"<div style='font-size:22px;font-weight:800;color:{color};font-family:JetBrains Mono;'>{value:,.0f} Ha</div>"
            f"<div style='font-size:10px;color:#64748b;font-weight:700;'>{pct_total:.1f}% tổng diện tích</div>"
            f"<div style='font-size:11px;color:#475569;line-height:1.35;margin-top:4px;'>{note}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.info(
        f"🧭 **Kịch bản chuyên gia:** đến 2035, áp lực {scenario['pressure_name']} có thể dẫn tới "
        f"{scenario['impact_text']}. Trọng tâm can thiệp nên là {scenario['action_focus']}. "
        f"Giai đoạn 2027-2030 nên dùng để khoanh vùng ưu tiên; giai đoạn 2031-2035 dùng để đo hiệu quả và điều chỉnh quy hoạch."
    )

    # ── 3. Bảng delta + cảnh báo ──────────────────────────────────────────
    st.markdown("<div style='font-size:11px;font-weight:700;color:#64748b;margin:10px 0 6px;text-transform:uppercase;letter-spacing:0.5px;'>Biến động dự báo 2035 vs " + str(last_y) + "</div>", unsafe_allow_html=True)

    insights = []
    for cls, lbl in zip(classes, labels):
        cur = cur_row[cls] or 0
        fut = fc.get(2035, {}).get(cls)
        if fut is None:
            continue
        delta = fut - cur
        pct = (delta / cur * 100) if cur > 0 else 0
        arrow = "▲" if delta > 0 else "▼"
        # màu phụ thuộc class+layer: với NDVI rừng tăng = tốt, với NDBI đô thị tăng = xấu
        good_for_delta_positive = {
            "NDVI": [False, False, True, True],   # nước/trống tăng=xấu; rừng tăng=tốt
            "NDBI": [True, True, False, False],   # rừng/trống tăng=tốt; đô thị tăng=xấu
            "LST":  [True, True, False, False],   # mát tăng=tốt; nóng tăng=xấu
        }
        idx = classes.index(cls)
        is_good = good_for_delta_positive[params.layer][idx] == (delta > 0)
        color = "#059669" if is_good else "#dc2626"
        st.markdown(
            f"<div style='display:flex;justify-content:space-between;"
            f"font-size:12px;padding:4px 0;border-bottom:1px solid rgba(0,0,0,0.06);'>"
            f"<span style='color:#334155;'>{lbl}</span>"
            f"<span style='color:{color};font-weight:700;font-family:monospace;'>"
            f"{arrow} {abs(int(delta)):,} Ha ({pct:+.1f}%)</span></div>",
            unsafe_allow_html=True,
        )
        if abs(pct) > 10:
            insights.append((lbl, delta, pct, is_good))

    # ── 4. Auto insight ──────────────────────────────────────────
    if insights:
        worst = max(insights, key=lambda x: 0 if x[3] else abs(x[2]))
        if not worst[3]:  # is bad
            st.error(f"🚨 **Cảnh báo:** {worst[0]} dự kiến biến động "
                     f"{worst[2]:+.1f}% ({worst[1]:+,.0f} Ha) vào 2035. "
                     f"Cần chính sách quy hoạch ngay từ {last_y+1}.")
        else:
            st.success(f"✅ Xu hướng tích cực: {worst[0]} dự kiến {worst[2]:+.1f}% vào 2035.")
    else:
        st.info("ℹ️ Dự báo Prophet cho thấy cơ cấu đất đai khá ổn định đến 2035 (biến động < 10%).")


def render_chart_bar_region(result, params):
    """Hiển thị bar chart so sánh giữa các vùng — FIX: tính năng gốc bị bỏ sót hoàn toàn."""
    bar_data = result.get("bar_data", [])
    if not bar_data or len(bar_data) < 2:
        st.info("Chọn ≥ 2 vùng để so sánh.")
        return

    df_b = pd.DataFrame(bar_data).sort_values("Trị số", ascending=True)
    meta = CONFIG["layer_meta"][params.layer]
    colors = ["#10b981" if v >= df_b["Trị số"].median() else "#ef4444"
              for v in df_b["Trị số"]] if not meta["good_high"] else \
             ["#10b981" if v >= df_b["Trị số"].median() else "#ef4444"
              for v in df_b["Trị số"]]

    fig = go.Figure(go.Bar(
        x=df_b["Trị số"], y=df_b["Khu vực"],
        orientation="h",
        marker_color=[meta["color"]] * len(df_b),
        marker_opacity=0.85,
        text=df_b["Trị số"].apply(lambda v: fmt_val(params.layer, v)),
        textposition="outside", textfont=dict(size=10, color="#334155"),
        hovertemplate="<b>%{y}</b><br>%{x:.3f}<extra></extra>",
    ))
    fig.update_layout(height=max(200, len(df_b) * 38),
                      margin=dict(l=10,r=60,t=10,b=10), **PD)
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    best  = df_b.iloc[-1]
    worst = df_b.iloc[0]
    st.info(f"📊 **So sánh vùng năm {result['last_y']}:** "
            f"**{best['Khu vực']}** có {params.layer} cao nhất ({fmt_val(params.layer, best['Trị số'])}); "
            f"**{worst['Khu vực']}** thấp nhất ({fmt_val(params.layer, worst['Trị số'])}).")


# ─── AI FEATURE: KMEANS CLUSTERING THEO VÙNG ─────────────────────────────────
def compute_region_multilayer_means(country: str, sub_regions: list, month: str, year: str) -> pd.DataFrame:
    """
    Fetch song song NDVI / NDBI / LST (mean) cho từng sub_region trong năm chỉ định.
    Trả về DataFrame: [Khu vực, NDVI, NDBI, LST].
    """
    if not sub_regions or len(sub_regions) < 2:
        return pd.DataFrame()

    roi = get_dynamic_roi(country, sub_regions)
    geom = roi.geometry()
    images = {L: get_image(geom, year, month, L) for L in ("NDVI", "NDBI", "LST")}
    SCALE = CONFIG["scale"]

    def _fetch(region: str, layer_name: str):
        try:
            sub_geom = roi.filter(ee.Filter.eq("ADM1_NAME", region)).geometry()
            v = (images[layer_name].select(layer_name)
                 .reduceRegion(reducer=ee.Reducer.mean(), geometry=sub_geom,
                               scale=SCALE * 4, maxPixels=1e13,
                               tileScale=4, bestEffort=True)
                 .get(layer_name).getInfo())
            return v
        except Exception:
            return None

    rows = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {(r, L): pool.submit(_fetch, r, L)
                for r in sub_regions for L in ("NDVI", "NDBI", "LST")}
        for r in sub_regions:
            rows.append({
                "Khu vực": r,
                "NDVI": futs[(r, "NDVI")].result(),
                "NDBI": futs[(r, "NDBI")].result(),
                "LST":  futs[(r, "LST")].result(),
            })
    return pd.DataFrame(rows).dropna().reset_index(drop=True)


def render_chart_clustering(result, params):
    """KMeans clustering: phân nhóm các vùng theo (NDVI, NDBI, LST)."""
    st.markdown("**🧭 Phân cụm AI — KMeans (NDVI · NDBI · LST)**")
    st.caption("Mô hình ML không giám sát tự động phân loại các vùng đang chọn "
               "thành các nhóm đô thị tương đồng dựa trên 3 chỉ số viễn thám.")

    if not params.sub_regions or len(params.sub_regions) < 2:
        st.info("ℹ️ Chọn **≥ 2 vùng quan trắc** ở cột bên trái để bật phân cụm AI.")
        return

    last_y = result.get("last_y") or sorted(params.years_multi)[-1]
    cache_key = ("cluster_data_"
                 f"{params.country}_{'_'.join(sorted(params.sub_regions))}_{params.month}_{last_y}")

    if st.button("🔍 Chạy phân cụm AI", use_container_width=True, key="cluster_run_btn"):
        with st.spinner("Đang tải NDVI/NDBI/LST cho từng vùng từ Earth Engine..."):
            try:
                df = compute_region_multilayer_means(
                    params.country, params.sub_regions, params.month, last_y
                )
                st.session_state[cache_key] = df
            except Exception as e:
                st.error(f"❌ Lỗi khi tải dữ liệu: {e}")
                return

    df = st.session_state.get(cache_key)
    if df is None:
        st.caption("⬆️ Bấm nút trên để tính phân cụm.")
        return
    if df.empty or len(df) < 3:
        st.warning("⚠️ Cần ≥ 3 vùng có dữ liệu hợp lệ để KMeans (k=3). Chọn thêm vùng và thử lại.")
        return

    # ── Train KMeans ────────────────────────────────────────────
    X = df[["NDVI", "NDBI", "LST"]].values
    X_scaled = StandardScaler().fit_transform(X)
    k = min(3, len(df))
    km = KMeans(n_clusters=k, random_state=42, n_init=10).fit(X_scaled)
    df = df.copy()
    df["Cụm"] = km.labels_

    # ── Auto-label clusters theo đặc trưng centroid ─────────────
    centroids_z = pd.DataFrame(km.cluster_centers_, columns=["NDVI_z", "NDBI_z", "LST_z"])

    def _name_cluster(row):
        if row["NDVI_z"] > 0 and row["LST_z"] < 0:
            return "🌳 Đô thị xanh & mát"
        if row["NDBI_z"] > 0 and row["LST_z"] > 0:
            return "🏙️ Đô thị nóng & bê tông"
        if row["NDVI_z"] < 0 and row["LST_z"] > 0:
            return "🔥 Đất trống khô & nóng"
        if row["NDVI_z"] > 0 and row["NDBI_z"] < 0:
            return "🌾 Nông nghiệp / nông thôn"
        return "⚖️ Trung tính"

    cluster_names = {i: _name_cluster(centroids_z.iloc[i]) for i in range(k)}
    df["Nhãn cụm"] = df["Cụm"].map(cluster_names)

    # ── 3D scatter Plotly ───────────────────────────────────────
    fig = px.scatter_3d(
        df, x="NDVI", y="NDBI", z="LST",
        color="Nhãn cụm", text="Khu vực", height=440,
        color_discrete_sequence=px.colors.qualitative.Set2,
    )
    fig.update_traces(marker=dict(size=9, line=dict(width=1, color="white")))
    fig.update_layout(margin=dict(l=0, r=0, t=10, b=0),
                      scene=dict(xaxis_title="NDVI (thực vật)",
                                 yaxis_title="NDBI (đô thị hóa)",
                                 zaxis_title="LST (nhiệt °C)"),
                      legend=dict(orientation="h", y=-0.05))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Bảng kết quả ────────────────────────────────────────────
    df_display = df[["Khu vực", "NDVI", "NDBI", "LST", "Nhãn cụm"]].copy()
    df_display["NDVI"] = df_display["NDVI"].round(3)
    df_display["NDBI"] = df_display["NDBI"].round(3)
    df_display["LST"]  = df_display["LST"].round(2)
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    # ── Tổng kết theo cụm ───────────────────────────────────────
    summary = df.groupby("Nhãn cụm").agg(
        SoVung=("Khu vực", "count"),
        NDVI_TB=("NDVI", "mean"),
        NDBI_TB=("NDBI", "mean"),
        LST_TB=("LST", "mean"),
    ).round(3).reset_index()
    st.markdown("**📋 Đặc trưng từng cụm:**")
    st.dataframe(summary, use_container_width=True, hide_index=True)

    # ── Nhận xét tự động ────────────────────────────────────────
    hottest = df.loc[df["LST"].idxmax()]
    coolest = df.loc[df["LST"].idxmin()]
    st.info(f"🎯 **Tóm tắt:** Vùng **{hottest['Khu vực']}** nóng nhất ({hottest['LST']:.1f}°C, "
            f"nhóm *{hottest['Nhãn cụm']}*); vùng **{coolest['Khu vực']}** mát nhất "
            f"({coolest['LST']:.1f}°C, nhóm *{coolest['Nhãn cụm']}*).")


# ─── MAIN UI LAYOUT ───────────────────────────────────────────────────────────
st.markdown(
    "<div class='main-title'>"
    "<h1>🌍 Hệ Thống Mô Phỏng & Trực Quan Hóa <span>Biến Động Đô Thị Hóa</span></h1>"
    "<span class='badge'>v2.0 · Gemini 2.5 · GEE</span>"
    "</div>",
    unsafe_allow_html=True,
)

col_ctrl, col_map, col_report = st.columns([1.0, 2.4, 1.8], gap="medium")

# ════════ CỘT 1: ĐIỀU KHIỂN ════════════════════════════════════════════════════
with col_ctrl:
    st.markdown("<div class='section-header'>Thiết lập Không gian</div>", unsafe_allow_html=True)
    with st.container(border=True):
        countries = get_countries()
        default_idx = countries.index("Viet Nam") if "Viet Nam" in countries else 0
        country = st.selectbox("Quốc gia", countries, index=default_idx)
        selected_subregions = st.multiselect(
            "Vùng quan trắc (bỏ trống = toàn quốc)",
            get_sub_regions(country),
            placeholder="Nhấn để chọn Tỉnh/Thành/Bang...",
        )

    st.markdown("<br><div class='section-header'>Tham số Thu thập</div>", unsafe_allow_html=True)
    with st.container(border=True):
        layer      = st.selectbox("Chỉ số Viễn thám", ["NDBI", "LST", "NDVI"])
        month      = st.selectbox("Tháng đồng bộ", CONFIG["months"], index=2)
        years_multi = st.multiselect("Các năm phân tích", CONFIG["years"],
                                     default=["2021", "2023", "2025"])

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 KHỞI CHẠY HỆ THỐNG", use_container_width=True, type="primary"):
        if not years_multi:
            st.warning("⚠️ Chọn ít nhất 1 năm!")
        else:
            params  = AnalysisParams(country, selected_subregions, layer, month, years_multi)
            years_s = sorted(years_multi)

            base_obj = build_base_objects(params)
            _center, _zoom, _bbox = _compute_roi_view(base_obj["geom"])
            st.session_state["map_center"] = _center
            st.session_state["map_zoom"]   = _zoom
            st.session_state["map_bounds"] = _bbox

            with st.spinner("⏳ Đang thu thập dữ liệu từ GEE..."):
                try:
                    # Dùng @st.cache_data để cache RAM (thay cho Supabase)
                    stats = compute_stats_cached(
                        params.country,
                        tuple(sorted(params.sub_regions)),
                        params.layer,
                        params.month,
                        tuple(sorted(params.years_multi)),
                    )
                    final_result = {**base_obj, **stats}
                    st.session_state.update({
                        "params": params, "result": final_result,
                        "cached_report": None,
                        "ai_trigger": False,
                        "analyzed": True,
                        "display_year": years_s[-1],
                        "compare_left": years_s[0],
                        "compare_right": years_s[-1],
                        "map_click_value": None,
                        "last_clicked_coords": None,
                        "force_zoom": True,
                    })
                except Exception as e:
                    st.error(f"Lỗi truy xuất GEE: {e}")

    st.markdown(
        "<div style='margin-top:8px;padding:10px 12px;"
        "background:linear-gradient(135deg,rgba(8,145,178,0.08),rgba(59,130,246,0.08));"
        "border-left:3px solid #0891b2;border-radius:10px;"
        "font-size:12px;color:#475569;line-height:1.5;'>"
        "💬 <b>Hỏi AI</b> đã tích hợp vào tab <b>\"💬 Hỏi AI\"</b> ở cột phải. "
        "Click một điểm trên bản đồ → mở tab để chat về thời tiết & môi trường."
        "</div>",
        unsafe_allow_html=True,
    )

# ════════ CỘT 2: BẢN ĐỒ ════════════════════════════════════════════════════════
with col_map:
    if st.session_state["analyzed"] and st.session_state["result"] is not None:
        result = st.session_state["result"]
        params = st.session_state["params"]

        # FIX: đảm bảo compare_left/right luôn có giá trị hợp lệ
        if st.session_state["compare_left"] not in result["years"]:
            st.session_state["compare_left"] = result["years"][0]
        if st.session_state["compare_right"] not in result["years"]:
            st.session_state["compare_right"] = result["years"][-1]

        c_mode1, c_mode2 = st.columns([1.5, 1])
        map_mode = c_mode1.radio(
            "Chế độ bản đồ",
            ["🗺️ Bản đồ đơn", "🪞 Trượt so sánh", "📍 Dấu vết biến động", "🎞️ Chuyển động thời gian"],
            horizontal=True, label_visibility="collapsed",
        )
        st.session_state["map_mode"] = map_mode

        # ── Xử lý click trả về từ st_folium (chỉ last_clicked, không track center/zoom) ─
        _map_key_by_mode = {
            "🗺️ Bản đồ đơn":         "map_single",
            "🪞 Trượt so sánh":      "map_swipe",
            "📍 Dấu vết biến động":  "map_change",
        }
        _active_map_key = _map_key_by_mode.get(map_mode)
        if (_active_map_key
                and _active_map_key in st.session_state
                and st.session_state[_active_map_key]):
            map_data = st.session_state[_active_map_key]
            last_clicked = map_data.get("last_clicked")
            if last_clicked:
                lat_c, lon_c = last_clicked["lat"], last_clicked["lng"]
                prev = st.session_state.get("last_clicked_coords")
                if prev is None or (lat_c, lon_c) != prev:
                    st.session_state["last_clicked_coords"] = (lat_c, lon_c)
                    query_year = (st.session_state["display_year"]
                                  if map_mode == "🗺️ Bản đồ đơn"
                                  else st.session_state["compare_right"])
                    with st.spinner("⏳ Đang thu thập dữ liệu điểm..."):
                        # OPT: gọi 3 API song song (Nominatim, GEE, Open-Meteo) thay vì nối tiếp
                        with ThreadPoolExecutor(max_workers=3) as _pool:
                            _fa = _pool.submit(get_address_from_coords, lat_c, lon_c)
                            _fv = _pool.submit(get_three_indices, lat_c, lon_c, query_year, params.month)
                            _fw = _pool.submit(get_forecast_weather, lat_c, lon_c)
                            address, vals, weather = _fa.result(), _fv.result(), _fw.result()
                        st.session_state["map_click_value"] = {
                            "lat": lat_c, "lon": lon_c,
                            "address": address,
                            "NDVI": vals["NDVI"], "NDBI": vals["NDBI"], "LST": vals["LST"],
                            "weather": weather,
                        }
                    st.rerun()

        click_info = st.session_state.get("map_click_value")

        # ── Render bản đồ theo mode ────────────────────────────────────────
        if map_mode == "🗺️ Bản đồ đơn":
            # FIX: display_year fallback
            disp_year = st.session_state["display_year"] or result["years"][-1]
            if disp_year not in result["years"]:
                disp_year = result["years"][-1]
            st.session_state["display_year"] = c_mode2.selectbox(
                "Năm", result["years"],
                index=result["years"].index(disp_year),
                label_visibility="collapsed",
            )
            m = build_single_map(result, params.layer, st.session_state["display_year"], click_info)
            st.markdown(f"<div class='map-toolbar'>🗺️ Lớp phủ {params.layer} — Năm {st.session_state['display_year']}</div>", unsafe_allow_html=True)
            st_folium(m, width=None, height=520, returned_objects=["last_clicked"], key="map_single")

        elif map_mode in ("🪞 Trượt so sánh", "📍 Dấu vết biến động"):
            if len(result["years"]) < 2:
                st.warning("⚠️ Cần chọn từ 2 năm trở lên.")
            else:
                cl, cr = c_mode2.columns(2)
                st.session_state["compare_left"]  = cl.selectbox(
                    "Năm gốc", result["years"],
                    index=result["years"].index(st.session_state["compare_left"]),
                    label_visibility="collapsed",
                )
                st.session_state["compare_right"] = cr.selectbox(
                    "Năm so sánh", result["years"],
                    index=result["years"].index(st.session_state["compare_right"]),
                    label_visibility="collapsed",
                )
                if map_mode == "🪞 Trượt so sánh":
                    m = build_swipe_map(result, params.layer,
                                        st.session_state["compare_left"],
                                        st.session_state["compare_right"], click_info)
                    st.markdown(f"<div class='map-toolbar'>🪞 So sánh: {st.session_state['compare_left']} ←|→ {st.session_state['compare_right']}</div>", unsafe_allow_html=True)
                    st_folium(m, width=None, height=520, returned_objects=["last_clicked"], key="map_swipe")
                else:
                    m = build_change_map(result, params.layer,
                                         st.session_state["compare_left"],
                                         st.session_state["compare_right"], click_info)
                    st.markdown(f"<div class='map-toolbar'>📍 Biến động: {st.session_state['compare_left']} → {st.session_state['compare_right']}</div>", unsafe_allow_html=True)
                    st_folium(m, width=None, height=520, returned_objects=["last_clicked"], key="map_change")

        elif map_mode == "🎞️ Chuyển động thời gian":
            st.markdown("<div class='map-toolbar'>🎞️ Đang thiết lập Timelapse...</div>", unsafe_allow_html=True)
            with st.spinner("⏳ Đang kết xuất GIF từ GEE... (có thể mất 30–60 giây)"):
                try:
                    bounds = result["geom"].bounds().coordinates().getInfo()[0]
                    # FIX: truyền tuple thay vì AnalysisParams để cache hoạt động
                    gif_url = generate_timelapse_url(
                        cache_key    = params.cache_key(),
                        years_tuple  = tuple(sorted(params.years_multi)),
                        month        = params.month,
                        layer        = params.layer,
                        geom_coords  = tuple(tuple(p) for p in bounds),
                    )
                    if gif_url:
                        # Thêm year overlay
                        years_label = " → ".join(sorted(params.years_multi))
                        st.markdown(
                            f"<div style='text-align:center;'>"
                            f"<img src='{gif_url}' width='100%' "
                            f"style='border-radius:14px;box-shadow:0 10px 30px rgba(0,0,0,0.4);'/>"
                            f"<div style='font-size:11px;color:#64748b;margin-top:8px;'>"
                            f"📅 Timeline: {years_label}</div>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                    else:
                        # Fallback: manual year frame selector
                        st.warning("⚠️ GIF URL không khả dụng. Dùng chế độ xem tuần tự thay thế.")
                        sel_y = st.select_slider("⏯️ Chọn năm", options=result["years"])
                        m = build_single_map(result, params.layer, sel_y, click_info)
                        st_folium(m, width=None, height=420, returned_objects=[], key="timelapse_map")
                except Exception as e:
                    st.error(f"Lỗi timelapse: {e}")

        if st.session_state.get("force_zoom"):
            st.session_state["force_zoom"] = False

        # ── Xóa điểm click ────────────────────────────────────────────────
        if click_info and map_mode != "🎞️ Chuyển động thời gian":
            c_info, c_btn = st.columns([5, 1])
            c_info.markdown(f"**📍** `{click_info.get('address','')[:60]}`")
            if c_btn.button("✖ Xóa", use_container_width=True):
                st.session_state["map_click_value"]     = None
                st.session_state["last_clicked_coords"] = None
                st.session_state["current_df_hist"]     = None
                st.rerun()

        # ── Time series điểm click ────────────────────────────────────────
        if click_info and map_mode != "🎞️ Chuyển động thời gian":
            hist_key = (round(click_info["lat"], 4), round(click_info["lon"], 4), params.month)
            df_hist = st.session_state.get("current_df_hist")
            _need_fetch = (
                st.session_state.get("current_df_hist_key") != hist_key
                or df_hist is None
                or (hasattr(df_hist, "empty") and df_hist.empty)
            )
            if _need_fetch:
                with st.spinner("⏳ Đang tải chuỗi thời gian lịch sử..."):
                    df_hist = get_full_history_at_point(
                        click_info["lat"], click_info["lon"], params.month
                    )
                    st.session_state["current_df_hist"] = df_hist
                    st.session_state["current_df_hist_key"] = hist_key

                if not df_hist.empty:
                    fig_ts = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_ts.add_trace(go.Scatter(x=df_hist["Năm"], y=df_hist["NDVI"],
                                                 name="🌿 NDVI", line=dict(color="#10b981", width=2.5)),
                                      secondary_y=False)
                    fig_ts.add_trace(go.Scatter(x=df_hist["Năm"], y=df_hist["NDBI"],
                                                 name="🏢 NDBI", line=dict(color="#f97316", width=2.5)),
                                      secondary_y=False)
                    fig_ts.add_trace(go.Scatter(x=df_hist["Năm"], y=df_hist["LST"],
                                                 name="🌡️ LST (°C)",
                                                 line=dict(color="#ef4444", width=2.5, dash="dot")),
                                      secondary_y=True)
                    fig_ts.update_layout(
                        hovermode="x unified", height=245,
                        margin=dict(l=10,r=10,t=10,b=10),
                        legend=dict(orientation="h", y=1.05, font_size=10),
                        **PD,
                    )
                    fig_ts.update_yaxes(title_text="NDVI / NDBI", secondary_y=False, title_font_size=10)
                    fig_ts.update_yaxes(title_text="LST (°C)", secondary_y=True, title_font_size=10)
                    st.plotly_chart(fig_ts, use_container_width=True, config={"displayModeBar": False})

    else:
        # Default map khi chưa phân tích
        empty_m = folium.Map(location=[16.0, 106.0], zoom_start=5, tiles="CartoDB.Positron")
        st_folium(empty_m, width=None, height=750, key="empty_map", returned_objects=[])

# ════════ CỘT 3: BÁO CÁO + BIỂU ĐỒ ════════════════════════════════════════════
with col_report:
    st.markdown("<div class='section-header'>Thống kê & Phân tích</div>", unsafe_allow_html=True)

    if st.session_state["analyzed"] and st.session_state["result"] is not None:
        params      = st.session_state["params"]
        result      = st.session_state["result"]
        PD = dict(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                  font_color="#334155", font_family="'Space Grotesk',sans-serif")

        first_y, last_y = result["first_y"], result["last_y"]
        stats_first = result.get("stats_first", {})
        stats_last  = result["stats_last"]

        l_mean_first = stats_first.get(f"{params.layer}_mean", 0) or 0
        l_mean_last  = stats_last.get(f"{params.layer}_mean",  0) or 0
        delta_mean   = l_mean_last - l_mean_first

        # FIX: status logic per-layer
        status, color_st = layer_status(params.layer, l_mean_last)
        meta = CONFIG["layer_meta"][params.layer]

        # Diện tích cấp cao (class 3+4 = nguy cơ)
        a_high = extract_area(result["area_last"], 3) + extract_area(result["area_last"], 4)

        delta_sign  = "+" if delta_mean >= 0 else ""
        delta_class = "pos" if (delta_mean >= 0) == meta["good_high"] else "neg"

        st.markdown(f"""
        <div class='kpi-grid'>
            <div class='kpi-card'>
                <div class='kpi-title'>{meta['icon']} {params.layer} Hiện tại</div>
                <div class='kpi-value' style='color:{meta["color"]};'>{fmt_val(params.layer, l_mean_last)}</div>
                <div class='kpi-delta {delta_class}'>{delta_sign}{delta_mean:.3f} vs {first_y}</div>
            </div>
            <div class='kpi-card'>
                <div class='kpi-title'>🏁 Đánh giá Chung</div>
                <div class='kpi-value' style='color:{color_st};'>{status}</div>
                <div class='kpi-delta' style='color:#64748b;'>Năm {last_y}</div>
            </div>
            <div class='kpi-card'>
                <div class='kpi-title'>📐 Diện tích Nguy cơ</div>
                <div class='kpi-value'>{a_high:,.0f}<span style='font-size:11px;color:#64748b;'> Ha</span></div>
                <div class='kpi-delta neg'>Cần giám sát</div>
            </div>
            <div class='kpi-card'>
                <div class='kpi-title'>📅 {params.layer} Khởi điểm</div>
                <div class='kpi-value' style='color:#64748b;'>{fmt_val(params.layer, l_mean_first)}</div>
                <div class='kpi-delta' style='color:#64748b;'>Năm {first_y}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        if status == "Cảnh báo":
            st.error(f"🚨 Chỉ số {params.layer} đang ở mức nguy hiểm tại {result['roi_names']}!")

        # ── AI report (fragment, không block UI chính) ────────────
        @st.fragment
        def _ai_report_fragment():
            cached = st.session_state.get("cached_report")
            ai_trigger = st.session_state.get("ai_trigger", False)

            if cached:
                st.markdown(f"<div class='ai-report'><div class='ai-report-text'>{cached}</div></div>", unsafe_allow_html=True)
                
                # Show provider status
                provider = st.session_state.get("last_report_provider", "Unknown")
                is_ai = st.session_state.get("last_report_is_ai", False)
                
                if is_ai:
                    status_icon = "✅"
                    status_msg = f"{status_icon} Báo cáo được tạo bởi AI: **{provider}**"
                    st.success(status_msg, icon="🤖")
                else:
                    status_msg = f"✅ Báo cáo chuyên gia tức thì: **{provider}**"
                    st.success(status_msg)
                return

            if not ai_trigger:
                if st.button("🤖 Sinh báo cáo chuyên gia tức thì", use_container_width=True, key="btn_gen_ai"):
                    st.session_state["ai_trigger"] = True
                else:
                    return

            with st.spinner("🤖 Đang dựng báo cáo từ số liệu phân tích..."):
                report = generate_gemini_report(params.layer, first_y, last_y, l_mean_first, l_mean_last, a_high, result["roi_names"])
                st.session_state["cached_report"] = report

        _ai_report_fragment()


        with st.expander("🔬 Phân tích Học thuật Tự động", expanded=False):
            analysis = auto_academic_analysis(
                params.layer, l_mean_first, l_mean_last, a_high, result["roi_names"]
            )
            render_analysis_box(analysis)

        with st.expander("📐 Độ chính xác mô hình", expanded=False):
            accuracy = compute_trend_accuracy_summary(result, params.layer)
            if accuracy.get("available"):
                c_acc1, c_acc2, c_acc3 = st.columns(3)
                c_acc1.metric("MAPE", accuracy["mape_text"])
                c_acc2.metric("RMSE", accuracy["rmse_text"])
                c_acc3.metric("Đánh giá", accuracy["label"])
            st.info(accuracy["summary"])

        # ── Chart tabs ───────────────────────────────────────────────────
        tab_labels = ["⛅ Thời tiết", "📈 Xu hướng", "📊 Mật độ",
                      "🥧 Cơ cấu", "🌡️ Đảo nhiệt", "🌐 So vùng",
                      "🔮 Dự báo 2035", "🎯 Điểm Rủi Ro",
                      "🧭 Phân cụm AI", "💬 Hỏi AI", "📥 Tải Về"]
        tabs = st.tabs(tab_labels)

        with tabs[0]:
            render_chart_weather(st.session_state.get("map_click_value"))

        with tabs[1]:
            render_chart_trend(result, params)

        with tabs[2]:
            render_chart_histogram(result, params, l_mean_last)

        with tabs[3]:
            render_chart_pie(result, params)

        with tabs[4]:
            render_chart_uhi(result, params)

        with tabs[5]:
            # FIX: Tab "So vùng" trước đây hoàn toàn bị bỏ sót
            render_chart_bar_region(result, params)

        with tabs[6]:
            render_chart_forecast(result, params)

        with tabs[7]:
            render_chart_risk(result, params)

        with tabs[8]:
            render_chart_clustering(result, params)

        with tabs[9]:
            render_chart_chat(result, params)

        with tabs[10]:
            st.markdown("<div style='font-size:12px;color:#64748b;margin-bottom:10px;'>Xuất dữ liệu phân tích</div>", unsafe_allow_html=True)

            if result["trend_data"]:
                csv_data = pd.DataFrame(result["trend_data"]).to_csv(index=False).encode("utf-8-sig")
                st.download_button("📄 CSV — Xu hướng thời gian", data=csv_data,
                                   file_name=f"Trend_{result['roi_names']}_{params.layer}.csv",
                                   mime="text/csv", use_container_width=True)

            if st.session_state.get("cached_report"):
                st.download_button("📝 TXT — Báo cáo AI",
                                   data=st.session_state["cached_report"].encode("utf-8"),
                                   file_name=f"Report_AI_{result['roi_names']}.txt",
                                   mime="text/plain", use_container_width=True)

            # Analysis export
            analysis_dict = auto_academic_analysis(
                params.layer, l_mean_first, l_mean_last, a_high, result["roi_names"]
            )
            accuracy_dict = compute_trend_accuracy_summary(result, params.layer)
            try:
                pdf_bytes = build_pdf_report(
                    params=params,
                    result=result,
                    analysis=analysis_dict,
                    ai_report=st.session_state.get("cached_report") or "",
                    first_y=first_y,
                    last_y=last_y,
                    l_mean_first=l_mean_first,
                    l_mean_last=l_mean_last,
                    delta_mean=delta_mean,
                    a_high=a_high,
                    status=status,
                )
                st.download_button("📄 PDF — Báo cáo tổng hợp",
                                   data=pdf_bytes,
                                   file_name=f"Bao_cao_{result['roi_names']}_{params.layer}.pdf",
                                   mime="application/pdf", use_container_width=True)
            except Exception as e:
                st.warning(f"Không thể tạo PDF: {e}")

            html_report = build_beautiful_report_html(
                params=params,
                result=result,
                analysis=analysis_dict,
                ai_report=st.session_state.get("cached_report") or "",
                first_y=first_y,
                last_y=last_y,
                l_mean_first=l_mean_first,
                l_mean_last=l_mean_last,
                delta_mean=delta_mean,
                a_high=a_high,
                status=status,
                color_st=color_st,
            )
            st.download_button("🌐 HTML — Báo cáo đầy đủ",
                               data=html_report.encode("utf-8"),
                               file_name=f"Bao_cao_{result['roi_names']}_{params.layer}.html",
                               mime="text/html", use_container_width=True)

            full_text = (
                f"=== Phân tích Học thuật: {params.layer} — {result['roi_names']} ===\n\n"
                + "\n\n".join([f"[{k.upper()}]\n{v}" for k, v in analysis_dict.items()])
                + f"\n\n=== Số liệu thống kê ===\n"
                + f"Năm phân tích: {first_y} – {last_y}\n"
                + f"{params.layer} khởi điểm: {fmt_val(params.layer, l_mean_first)}\n"
                + f"{params.layer} hiện tại:  {fmt_val(params.layer, l_mean_last)}\n"
                + f"Biến động: {delta_mean:+.4f}\n"
                + f"Diện tích nguy cơ: {a_high:,.0f} Ha\n"
                + f"Đánh giá: {status}\n"
                + f"\n=== Độ chính xác mô hình ===\n{accuracy_dict['summary']}\n"
            )
            st.download_button("🔬 TXT — Phân tích Học thuật",
                               data=full_text.encode("utf-8"),
                               file_name=f"Academic_{result['roi_names']}_{params.layer}.txt",
                               mime="text/plain", use_container_width=True)

            try:
                url_tif = (result["year_data"][last_y]["image"]
                           .select(params.layer)
                           .getDownloadURL({"scale": CONFIG["scale"], "region": result["geom"]}))
                st.markdown(
                    f"<a href='{url_tif}' target='_blank' style='text-decoration:none;'>"
                    f"<button style='width:100%;padding:10px;border-radius:10px;"
                    f"background:linear-gradient(135deg,#4f46e5,#7c3aed);"
                    f"color:white;border:none;font-weight:700;margin-top:8px;cursor:pointer;'>"
                    f"🗺️ GeoTIFF — Bản đồ {last_y}</button></a>",
                    unsafe_allow_html=True,
                )
            except:
                pass

    else:
        st.markdown(
            "<div style='text-align:center;padding:60px 20px;color:#64748b;"
            "background:#f8fafc;border-radius:16px;"
            "border:1px dashed #cbd5e1;'>"
            "Hệ thống chưa có dữ liệu.<br>"
            "<span style='font-size:12px;'>Cấu hình thông số và nhấn 🚀 Khởi chạy.</span>"
            "</div>",
            unsafe_allow_html=True,
        )
