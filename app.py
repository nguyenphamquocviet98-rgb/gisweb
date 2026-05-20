"""
╔══════════════════════════════════════════════════════════════════════╗
║   URBAN DYNAMICS INTELLIGENCE PLATFORM  —  v2.0                     ║
║   Hệ thống Phân tích & Dự báo Biến động Đô thị Toàn cầu            ║
║   Powered by: GEE · Streamlit · Scikit-learn · Prophet · Gemini     ║
╚══════════════════════════════════════════════════════════════════════╝
"""

# ─── IMPORTS ─────────────────────────────────────────────────────────────────
import time, json, os, hashlib, pyodbc, requests
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
from prophet import Prophet
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from google import genai

# ─── PAGE CONFIG ─────────────────────────────────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="Urban Dynamics Intelligence Platform",
    page_icon="🌍",
    initial_sidebar_state="collapsed"
)

# ─── GLOBAL CONFIG ───────────────────────────────────────────────────────────
CONFIG = {
    "project_id": "tphcm-470513",
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

GEMINI_API_KEY = "AIzaSyCZ3kJj-oKw0oo1Sj9m4-Iezsf1cibynIQ"

# ─── DATABASE (SQL SERVER SMART CACHE) ───────────────────────────────────────
DB_SERVER = r'VIET'
DB_NAME   = 'GIS_Urban_Analysis'

def get_db_connection():
    try:
        conn_str = (f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                    f"SERVER={DB_SERVER};DATABASE={DB_NAME};Trusted_Connection=yes;")
        return pyodbc.connect(conn_str, timeout=3)
    except:
        return None

def get_query_hash(country, sub_regions, layer, month, years_multi):
    raw = f"{country}_{'|'.join(sorted(sub_regions))}_{layer}_{month}_{'|'.join(sorted(years_multi))}"
    return hashlib.sha256(raw.encode()).hexdigest()

def check_cache_in_db(query_hash):
    conn = get_db_connection()
    if not conn:
        return None
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT StatsResultData, GeminiReport FROM Analysis_Cache WHERE QueryHash = ?",
            (query_hash,)
        )
        row = cursor.fetchone()
        if row:
            return {"result": json.loads(row[0]), "gemini_report": row[1]}
        return None
    except:
        return None
    finally:
        if conn: conn.close()

def save_cache_to_db(query_hash, params, stats_dict, gemini_report):
    conn = get_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        stats_json  = json.dumps(stats_dict, ensure_ascii=False)
        sub_regs    = ",".join(params.sub_regions) if params.sub_regions else "All"
        years_str   = ",".join(params.years_multi)
        cursor.execute(
            """INSERT INTO Analysis_Cache
               (QueryHash, CountryName, SubRegions, LayerIndex, AnalyzedYears, StatsResultData, GeminiReport)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (query_hash, params.country, sub_regs, params.layer, years_str, stats_json, gemini_report)
        )
        conn.commit()
    except Exception as e:
        print("Lỗi lưu DB:", e)
    finally:
        if conn: conn.close()

# ─── GOOGLE EARTH ENGINE INIT ────────────────────────────────────────────────
def init_gee():
    try:
        ee.Initialize(project=CONFIG["project_id"])
    except Exception as e:
        st.error(f"❌ Lỗi kết nối Google Earth Engine — project: {CONFIG['project_id']}")
        st.info("Mở Terminal và chạy: **earthengine authenticate**")
        st.stop()

init_gee()

# ─── CSS: GLASSMORPHISM + NASA DASHBOARD STYLE ───────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

:root {
  --primary:   #6366f1;
  --primary-2: #818cf8;
  --accent:    #06b6d4;
  --success:   #10b981;
  --warning:   #f59e0b;
  --danger:    #ef4444;
  --bg:        #070b14;
  --bg-2:      #0d1526;
  --surface:   rgba(255,255,255,0.045);
  --surface-2: rgba(255,255,255,0.08);
  --border:    rgba(255,255,255,0.09);
  --text:      #e2e8f0;
  --muted:     #64748b;
  --radius:    14px;
  --glow:      0 0 20px rgba(99,102,241,0.35);
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
  padding: 1.2rem 2rem 2.5rem;
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
.kpi-grid { display: grid; grid-template-columns: repeat(2,1fr); gap: 10px; margin-bottom: 16px; }
.kpi-card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px;
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
.kpi-title { font-size: 10px; color: var(--muted); text-transform: uppercase; font-weight: 700; letter-spacing: 0.6px; margin-bottom: 5px; }
.kpi-value { font-size: 22px; font-weight: 700; color: var(--text); font-family: 'JetBrains Mono', monospace; }
.kpi-delta { font-size: 11px; font-weight: 600; margin-top: 4px; }
.kpi-delta.pos { color: var(--success); }
.kpi-delta.neg { color: var(--danger); }

/* ── AI Report ───────────────────────────────── */
.ai-report {
  background: linear-gradient(145deg, rgba(99,102,241,0.06), rgba(6,182,212,0.04));
  border: 1px solid rgba(99,102,241,0.2);
  border-radius: 14px; padding: 18px 20px;
  margin-bottom: 18px;
  border-left: 3px solid var(--primary);
}
.ai-report-label {
  font-size: 10px; color: var(--primary-2); font-weight: 800;
  text-transform: uppercase; letter-spacing: 1px; margin-bottom: 10px;
  display: flex; align-items: center; gap: 6px;
}
.ai-report-text {
  font-size: 13.5px; line-height: 1.8; color: #94a3b8; text-align: justify;
}

/* ── Academic Analysis Boxes ─────────────────── */
.analysis-box {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; margin-top: 12px;
}
.analysis-row {
  display: flex; align-items: flex-start; gap: 10px;
  padding: 8px 0; border-bottom: 1px solid var(--border);
  font-size: 12.5px; line-height: 1.6; color: #94a3b8;
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
    font_color="#94a3b8",
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
        "pending_db_save":     False,
        "current_hash":        None,
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
    geom, roi   = base["geom"], base["roi"]
    first_y, last_y = base["first_y"], base["last_y"]
    year_data, years = base["year_data"], base["years"]

    trend_data = []
    for y in years:
        val = (year_data[y]["image"].select(params.layer)
               .reduceRegion(reducer=ee.Reducer.mean(), geometry=geom,
                             scale=CONFIG["scale"] * 4, maxPixels=1e13, tileScale=4, bestEffort=True)
               .getInfo().get(params.layer))
        if val is not None:
            trend_data.append({"Năm": y, "Trị số": val})

    bar_data = []
    if params.sub_regions and len(params.sub_regions) >= 2:
        for reg in params.sub_regions:
            val = (year_data[last_y]["image"].select(params.layer)
                   .reduceRegion(reducer=ee.Reducer.mean(),
                                 geometry=roi.filter(ee.Filter.eq("ADM1_NAME", reg)).geometry(),
                                 scale=CONFIG["scale"] * 2, maxPixels=1e13, tileScale=4, bestEffort=True)
                   .getInfo().get(params.layer))
            if val is not None:
                bar_data.append({"Khu vực": reg, "Trị số": val})

    return {
        "area_first":   get_area_groups(year_data[first_y]["class"], geom, CONFIG["scale"]),
        "area_last":    get_area_groups(year_data[last_y]["class"],  geom, CONFIG["scale"]),
        "stats_first":  get_stats(year_data[first_y]["image"], params.layer, geom, CONFIG["scale"]),
        "stats_last":   get_stats(year_data[last_y]["image"],  params.layer, geom, CONFIG["scale"]),
        "hist_last":    get_histogram(year_data[last_y]["image"], params.layer, geom, CONFIG["scale"]),
        "trend_data":   trend_data,
        "bar_data":     bar_data,
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
        cw  = res.get("current_weather", {})
        current_hum = res.get("hourly", {}).get("relative_humidity_2m", [0])[0]
        current = {"temp": cw.get("temperature"), "wind": cw.get("windspeed"),
                   "code": cw.get("weathercode"), "humidity": current_hum}
        daily = res.get("daily", {})
        forecast = []
        if daily and "time" in daily:
            for i in range(len(daily["time"])):
                dt = datetime.strptime(daily["time"][i], "%Y-%m-%d")
                forecast.append({
                    "date":      dt.strftime("%d/%m"),
                    "max_t":     daily["temperature_2m_max"][i],
                    "min_t":     daily["temperature_2m_min"][i],
                    "code":      daily["weathercode"][i],
                    "rain_prob": daily.get("precipitation_probability_max", [0] * 7)[i],
                })
        return {"current": current, "forecast": forecast}
    except:
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
    """FIX: dùng ee.FeatureCollection.map() để batch toàn bộ years trong 1 GEE call."""
    point = ee.Geometry.Point([lon, lat])

    def get_year_val(y_str):
        start  = ee.Date.fromYMD(ee.Number.parse(y_str), int(month), 1)
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
        vals = combined.reduceRegion(reducer=ee.Reducer.first(), geometry=point, scale=10)
        return ee.Feature(None, {"Năm": y_str, "NDVI": vals.get("NDVI"),
                                 "NDBI": vals.get("NDBI"), "LST": vals.get("LST")})

    try:
        fc = ee.FeatureCollection(ee.List(CONFIG["years"]).map(get_year_val))
        rows = fc.getInfo().get("features", [])
        return pd.DataFrame([{
            "Năm": f["properties"]["Năm"],
            "NDVI": f["properties"].get("NDVI"),
            "NDBI": f["properties"].get("NDBI"),
            "LST":  f["properties"].get("LST"),
        } for f in rows])
    except:
        return pd.DataFrame()

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

# ─── GEMINI AI REPORT ────────────────────────────────────────────────────────
def generate_gemini_report(layer, first_year, last_year, first_val, last_val, high_area, roi_name):
    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
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
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        return response.text
    except Exception as e:
        return f"Không thể kết nối Gemini AI: {e}"

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

# ─── MAP BUILDING ─────────────────────────────────────────────────────────────
def add_legend(m, layer):
    html = (f"<div style='position:fixed;bottom:36px;left:36px;z-index:9999;"
            f"background:rgba(7,11,20,0.9);backdrop-filter:blur(12px);"
            f"padding:14px 18px;border-radius:12px;border:1px solid rgba(255,255,255,0.1);"
            f"box-shadow:0 8px 25px rgba(0,0,0,0.4);'>"
            f"<div style='color:#e2e8f0;font-size:12px;font-weight:800;margin-bottom:8px;"
            f"text-transform:uppercase;letter-spacing:0.8px;'>Phân lớp {layer}</div>")
    for label, color in zip(CONFIG["class_labels"][layer], CONFIG["vis"][layer]["palette"]):
        html += (f"<div style='display:flex;align-items:center;margin-bottom:6px;'>"
                 f"<div style='background:{color};width:14px;height:14px;border-radius:3px;"
                 f"margin-right:10px;flex-shrink:0;'></div>"
                 f"<span style='font-size:12px;font-weight:500;color:#94a3b8;'>{label}</span></div>")
    m.get_root().html.add_child(folium.Element(html + "</div>"))

def add_background_mask(m, roi):
    geemap.ee_tile_layer(
        ee.Image(1).updateMask(ee.Image.constant(1).clip(roi).mask().Not()),
        {"palette": ["#0d1526"]}, "Lớp nền tối", True, 0.6
    ).add_to(m)

def base_map():
    m = folium.Map(
        location=st.session_state.get("map_center", [16.0, 106.0]),
        zoom_start=st.session_state.get("map_zoom", 6),
        control_scale=True, tiles=None,
    )
    folium.TileLayer("CartoDB.DarkMatter",    name="Dark Map",       overlay=False, control=True).add_to(m)
    folium.TileLayer("CartoDB.Positron",      name="Light Map",      overlay=False, control=True).add_to(m)
    folium.TileLayer("Esri.WorldImagery",     name="Ảnh vệ tinh",   overlay=False, control=True).add_to(m)
    MousePosition(position="bottomright", separator=" | ", prefix="Tọa độ:").add_to(m)
    return m

def center_map(m, result):
    try:
        bounds = result["geom"].bounds().coordinates().getInfo()[0]
        lats = [pt[1] for pt in bounds]; lons = [pt[0] for pt in bounds]
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    except:
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
    <div style="background:rgba(7,11,20,0.92);backdrop-filter:blur(12px);
         border:1px solid rgba(255,255,255,0.1);border-radius:14px;
         padding:16px;width:250px;color:white;font-family:'Space Grotesk',sans-serif;
         box-shadow:0 12px 30px rgba(0,0,0,0.5);">
      <div style="font-size:9px;color:#64748b;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px;">📍 Điểm định vị</div>
      <div style="font-size:12px;font-weight:600;color:#e2e8f0;line-height:1.4;margin-bottom:3px;">{addr[:50]}...</div>
      <div style="font-size:10px;color:#475569;margin-bottom:12px;padding-bottom:10px;border-bottom:1px solid rgba(255,255,255,0.07);">({lat:.4f}, {lon:.4f})</div>
      <div style="display:flex;justify-content:space-between;margin-bottom:7px;">
        <span style="font-size:11px;color:#10b981;font-weight:600;">🌿 NDVI</span>
        <span style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#f8fafc;">{v_ndvi}</span>
      </div>
      <div style="display:flex;justify-content:space-between;margin-bottom:7px;">
        <span style="font-size:11px;color:#f97316;font-weight:600;">🏢 NDBI</span>
        <span style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#f8fafc;">{v_ndbi}</span>
      </div>
      <div style="display:flex;justify-content:space-between;">
        <span style="font-size:11px;color:#ef4444;font-weight:600;">🌡️ LST</span>
        <span style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;color:#f8fafc;">{v_lst}</span>
      </div>
    </div>"""
    folium.Marker(
        location=[lat, lon],
        popup=folium.Popup(popup_html, max_width=300, show=True),
        icon=folium.Icon(color="red", icon="map-marker"),
    ).add_to(m)

def build_single_map(result, layer, display_year, click_info=None):
    m = base_map()
    add_background_mask(m, result["roi"])
    geemap.ee_tile_layer(result["year_data"][display_year]["class"],
                         CONFIG["vis"][layer], f"Phân loại {layer}", True, 0.9).add_to(m)
    geemap.ee_tile_layer(ee.Image().paint(result["roi"], 0, 2),
                         {"palette": ["#6366f1"]}, "Ranh giới", True, 1.0).add_to(m)
    add_legend(m, layer)
    if click_info:
        add_click_popup(m, click_info, layer)
    if st.session_state.get("force_zoom"):
        center_map(m, result)
    return m

def build_swipe_map(result, layer, left_year, right_year, click_info=None):
    m = base_map()
    add_background_mask(m, result["roi"])
    l = geemap.ee_tile_layer(result["year_data"][left_year]["class"],  CONFIG["vis"][layer], f"{layer} {left_year}",  True, 1.0)
    r = geemap.ee_tile_layer(result["year_data"][right_year]["class"], CONFIG["vis"][layer], f"{layer} {right_year}", True, 1.0)
    SideBySideLayers(l, r).add_to(m)
    geemap.ee_tile_layer(ee.Image().paint(result["roi"], 0, 2),
                         {"palette": ["#6366f1"]}, "Ranh giới", True, 1.0).add_to(m)
    add_legend(m, layer)
    if click_info:
        add_click_popup(m, click_info, layer)
    if st.session_state.get("force_zoom"):
        center_map(m, result)
    return m

def build_change_map(result, layer, left_year, right_year, click_info=None):
    m = base_map()
    add_background_mask(m, result["roi"])
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

    geemap.ee_tile_layer(change.clip(result["geom"]), vis,
                         f"Biến động {left_year}→{right_year}", True, 0.9).add_to(m)
    geemap.ee_tile_layer(ee.Image().paint(result["roi"], 0, 2),
                         {"palette": ["#6366f1"]}, "Ranh giới", True, 1.0).add_to(m)

    legend_html = f"""
    <div style="position:fixed;bottom:36px;left:36px;z-index:9999;
         background:rgba(7,11,20,0.92);backdrop-filter:blur(12px);
         padding:16px;border-radius:12px;border:1px solid rgba(255,255,255,0.1);">
      <div style="color:#e2e8f0;font-size:12px;font-weight:800;margin-bottom:10px;">📍 Dấu vết Biến động</div>
      <div style="color:#94a3b8;font-size:12px;font-weight:600;margin-bottom:6px;">{legend_neg}</div>
      <div style="color:#94a3b8;font-size:12px;font-weight:600;margin-bottom:6px;">⚪ Không đổi</div>
      <div style="color:#94a3b8;font-size:12px;font-weight:600;">{legend_pos}</div>
    </div>"""
    m.get_root().html.add_child(folium.Element(legend_html))
    if click_info:
        add_click_popup(m, click_info, layer)
    if st.session_state.get("force_zoom"):
        center_map(m, result)
    return m

# ─── CHART RENDERING FUNCTIONS ───────────────────────────────────────────────
def render_chart_weather(click_val):
    if not click_val or not click_val.get("weather"):
        st.info("📍 Click vào một điểm trên bản đồ để xem thông tin thời tiết thực tế.")
        return
    weather = click_val["weather"]
    w_curr  = weather["current"]
    w_fore  = weather["forecast"]
    st.markdown(f"**📍 Vị trí:** `{click_val.get('address','')}`")
    c1, c2, c3 = st.columns(3)
    c1.metric("🌡️ Nhiệt độ", f"{w_curr['temp']} °C")
    c2.metric("💨 Gió", f"{w_curr['wind']} km/h")
    c3.metric("💧 Độ ẩm", f"{w_curr.get('humidity','—')} %")
    if w_fore:
        st.markdown("<div style='font-size:12px;font-weight:700;color:#f59e0b;margin:12px 0 8px;'>Dự báo 7 ngày tới</div>", unsafe_allow_html=True)
        df_f = pd.DataFrame(w_fore)
        fig  = go.Figure()
        fig.add_trace(go.Scatter(x=df_f["date"], y=df_f["max_t"], mode="lines+markers+text",
                                  name="Cao nhất", line=dict(color="#ef4444", width=2),
                                  text=df_f["max_t"].apply(lambda x: f"{x:.0f}°"),
                                  textposition="top center", textfont=dict(size=10)))
        fig.add_trace(go.Scatter(x=df_f["date"], y=df_f["min_t"], mode="lines+markers+text",
                                  name="Thấp nhất", line=dict(color="#3b82f6", width=2),
                                  text=df_f["min_t"].apply(lambda x: f"{x:.0f}°"),
                                  textposition="bottom center", textfont=dict(size=10)))
        fig.update_layout(height=240, margin=dict(l=10,r=10,t=10,b=10),
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
                    line=dict(color="rgba(7,11,20,1)", width=2)),
        textposition="outside",
        textinfo="label+percent",
        textfont=dict(size=11),
        hovertemplate="<b>%{label}</b><br>%{value:,.0f} Ha<br>%{percent}<extra></extra>",
    ))
    fig.update_layout(
        height=290, margin=dict(l=30, r=30, t=20, b=10), showlegend=False,
        annotations=[dict(
            text=f"Tổng<br><b>{int(total):,} Ha</b>",
            x=0.5, y=0.5, font_size=13, font_color="#e2e8f0", showarrow=False,
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
            f"padding:4px 0;border-bottom:1px solid rgba(255,255,255,0.05);'>"
            f"<span style='color:#94a3b8;'>{d['Lớp']}</span>"
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

    if df_u is None or df_u.empty:
        st.info("📍 Click vào một điểm trên bản đồ để tải dữ liệu tương quan UHI.")
        return

    df_clean = df_u.dropna(subset=["NDVI", "LST", "NDBI"]).copy()
    if len(df_clean) < 3:
        st.warning("Cần ít nhất 3 điểm dữ liệu để phân tích UHI.")
        return

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
                       font=dict(size=11, color="#818cf8", family="JetBrains Mono"),
                       bgcolor="rgba(7,11,20,0.7)", borderpad=5)

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
        textposition="outside", textfont=dict(size=10, color="#94a3b8"),
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

# ─── MAIN UI LAYOUT ───────────────────────────────────────────────────────────
st.markdown(
    "<div class='main-title'>"
    "<h1>🌍 Hệ Thống Mô Phỏng & Trực Quan Hóa <span>Biến Động Đô Thị Hóa</span></h1>"
    "<span class='badge'>v2.0 · Gemini 2.5 · GEE</span>"
    "</div>",
    unsafe_allow_html=True,
)

col_ctrl, col_map, col_report = st.columns([1.2, 2.8, 1.5], gap="large")

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
            q_hash  = get_query_hash(country, selected_subregions, layer, month, years_multi)
            years_s = sorted(years_multi)

            base_obj    = build_base_objects(params)
            cached_data = check_cache_in_db(q_hash)

            if cached_data:
                st.toast("⚡ Tải từ Smart Cache trong < 0.1s", icon="⚡")
                final_result = {**base_obj, **cached_data["result"]}
                st.session_state.update({
                    "params": params, "result": final_result,
                    "cached_report": cached_data["gemini_report"],
                    "analyzed": True,
                    "display_year":    years_s[-1],
                    "compare_left":    years_s[0],
                    "compare_right":   years_s[-1],
                    "map_click_value": None, "last_clicked_coords": None,
                    "force_zoom": True, "pending_db_save": False,
                    "current_df_hist": None,
                })
            else:
                with st.spinner("⏳ Đang thu thập dữ liệu GEE & phân tích AI..."):
                    try:
                        stats        = compute_stats(params, base_obj)
                        final_result = {**base_obj, **stats}
                        st.session_state.update({
                            "params": params, "result": final_result,
                            "cached_report": None,
                            "analyzed": True,
                            "display_year":    years_s[-1],
                            "compare_left":    years_s[0],
                            "compare_right":   years_s[-1],
                            "map_click_value": None, "last_clicked_coords": None,
                            "force_zoom": True,
                            "current_hash":  q_hash,
                            "pending_db_save": True,
                            "current_df_hist": None,
                        })
                    except Exception as e:
                        st.error(f"Lỗi truy xuất GEE: {e}")

    st.markdown("""
    <a href="http://127.0.0.1:5500/weather_chat_demo.html" target="_blank" style="text-decoration:none;">
      <button style="width:100%;height:3rem;border-radius:12px;
        background:linear-gradient(135deg,#0891b2,#3b82f6);
        color:white;border:none;font-weight:700;font-size:14px;
        cursor:pointer;margin-top:8px;
        box-shadow:0 4px 15px rgba(8,145,178,0.35);">
        💬 HỎI ĐÁP AI THỜI TIẾT
      </button>
    </a>
    """, unsafe_allow_html=True)

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

        # ── Xử lý click trả về từ st_folium (lần rerun trước) ─────────────
        # FIX: chỉ đọc khi map_mode có st_folium, tránh đọc stale state từ timelapse
        if (map_mode != "🎞️ Chuyển động thời gian"
                and "main_map" in st.session_state
                and st.session_state["main_map"]):
            map_data = st.session_state["main_map"]
            if map_data.get("center"):
                st.session_state["map_center"] = [
                    map_data["center"]["lat"], map_data["center"]["lng"]
                ]
            if map_data.get("zoom"):
                st.session_state["map_zoom"] = map_data["zoom"]

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
                        address  = get_address_from_coords(lat_c, lon_c)
                        vals     = get_three_indices(lat_c, lon_c, query_year, params.month)
                        weather  = get_forecast_weather(lat_c, lon_c)
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
            st_folium(m, width=None, height=520, returned_objects=["last_clicked", "center", "zoom"], key="main_map")

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
                else:
                    m = build_change_map(result, params.layer,
                                         st.session_state["compare_left"],
                                         st.session_state["compare_right"], click_info)
                    st.markdown(f"<div class='map-toolbar'>📍 Biến động: {st.session_state['compare_left']} → {st.session_state['compare_right']}</div>", unsafe_allow_html=True)
                st_folium(m, width=None, height=520, returned_objects=["last_clicked", "center", "zoom"], key="main_map")

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
            with st.spinner("⏳ Đang tải chuỗi thời gian lịch sử..."):
                df_hist = get_full_history_at_point(
                    click_info["lat"], click_info["lon"], params.month
                ).dropna()
                st.session_state["current_df_hist"] = df_hist

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
        empty_m = folium.Map(location=[16.0, 106.0], zoom_start=5, tiles="CartoDB.DarkMatter")
        st_folium(empty_m, width=None, height=750)

# ════════ CỘT 3: BÁO CÁO + BIỂU ĐỒ ════════════════════════════════════════════
with col_report:
    st.markdown("<div class='section-header'>Thống kê & Phân tích</div>", unsafe_allow_html=True)

    if st.session_state["analyzed"] and st.session_state["result"] is not None:
        params      = st.session_state["params"]
        result      = st.session_state["result"]
        PD = dict(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
                  font_color="#94a3b8", font_family="'Space Grotesk',sans-serif")

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

        # ── Gemini AI report ─────────────────────────────────────────────
        if st.session_state.get("pending_db_save"):
            with st.spinner("🤖 Gemini AI đang phân tích..."):
                report = generate_gemini_report(
                    params.layer, first_y, last_y,
                    l_mean_first, l_mean_last, a_high, result["roi_names"]
                )
                st.session_state["cached_report"] = report
                stats_to_save = {k: result[k] for k in
                                 ["area_first", "area_last", "stats_first", "stats_last",
                                  "hist_last", "trend_data", "bar_data"]}
                save_cache_to_db(st.session_state["current_hash"], params, stats_to_save, report)
                st.session_state["pending_db_save"] = False

        if st.session_state.get("cached_report"):
            st.markdown(f"""
            <div class='ai-report'>
                <div class='ai-report-label'>🤖 Báo Cáo Chuyên Sâu — Gemini 2.5</div>
                <div class='ai-report-text'>{st.session_state['cached_report']}</div>
            </div>
            """, unsafe_allow_html=True)

        # ── Academic analysis box (auto-generated) ───────────────────────
        with st.expander("🔬 Phân tích Học thuật Tự động", expanded=False):
            analysis = auto_academic_analysis(
                params.layer, l_mean_first, l_mean_last, a_high, result["roi_names"]
            )
            render_analysis_box(analysis)

        # ── Chart tabs ───────────────────────────────────────────────────
        tab_labels = ["⛅ Thời tiết", "📈 Xu hướng", "📊 Mật độ",
                      "🥧 Cơ cấu", "🌡️ Đảo nhiệt", "🌐 So vùng", "📥 Tải Về"]
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
            "<div style='text-align:center;padding:60px 20px;color:#475569;"
            "background:rgba(255,255,255,0.03);border-radius:16px;"
            "border:1px dashed rgba(255,255,255,0.08);'>"
            "Hệ thống chưa có dữ liệu.<br>"
            "<span style='font-size:12px;'>Cấu hình thông số và nhấn 🚀 Khởi chạy.</span>"
            "</div>",
            unsafe_allow_html=True,
        )