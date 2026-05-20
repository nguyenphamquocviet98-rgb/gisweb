import time
import json
import os
import hashlib
import pyodbc
import requests 
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from datetime import datetime

import ee
import folium
from folium.plugins import SideBySideLayers, MeasureControl, MousePosition
import geemap.foliumap as geemap
import pandas as pd
import numpy as np
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

# =========================================================
# 1. CẤU HÌNH TRANG CHÍNH
# =========================================================
st.set_page_config(
    layout="wide",
    page_title="Hệ Thống Phân Tích Đô Thị Toàn Cầu",
    page_icon="🌍",
    initial_sidebar_state="collapsed"
)

# =========================================================
# 2. CẤU HÌNH CHUNG
# =========================================================
CONFIG = {
    "project_id":   "tphcm-470513", 
    "admin_l1":     "FAO/GAUL/2015/level1",   
    "scale":        250, 
    "years":        [str(y) for y in range(2018, 2027)], 
    "months":       [f"{i:02d}" for i in range(1, 13)],
    "vis": {
        "NDVI": {"min": 1, "max": 4, "palette": ["#f43f5e","#fbbf24","#34d399","#059669"]},
        "NDBI": {"min": 1, "max": 4, "palette": ["#10b981","#fbbf24","#f97316","#e11d48"]},
        "LST":  {"min": 1, "max": 4, "palette": ["#3b82f6","#fbbf24","#f97316","#e11d48"]},
    },
    "class_labels": {
        "NDVI": ["Nước/Đất trống","Đất thưa","Thực vật bụi","Rừng rậm"],
        "NDBI": ["Rừng/Nước","Đất trống","Đô thị thưa","Đô thị nén"],
        "LST":  ["Mát (<24°C)","Bình thường (24-29°C)","Nóng (29-34°C)","Rất nóng (>34°C)"],
    },
}

# =========================================================
# 3. KẾT NỐI DATABASE (SQL SERVER SMART CACHE)
# =========================================================
DB_SERVER = r'VIET' 
DB_NAME = 'GIS_Urban_Analysis'

def get_db_connection():
    try:
        conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={DB_SERVER};DATABASE={DB_NAME};Trusted_Connection=yes;"
        return pyodbc.connect(conn_str, timeout=3)
    except Exception as e:
        return None

def get_query_hash(country, sub_regions, layer, month, years_multi):
    raw_str = f"{country}_{'-'.join(sorted(sub_regions))}_{layer}_{month}_{'-'.join(sorted(years_multi))}"
    return hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

def check_cache_in_db(query_hash):
    conn = get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT StatsResultData, GeminiReport FROM Analysis_Cache WHERE QueryHash = ?", (query_hash,))
        row = cursor.fetchone()
        if row:
            return {"result": json.loads(row[0]), "gemini_report": row[1]}
        return None
    except: return None
    finally: 
        if conn: conn.close()

def save_cache_to_db(query_hash, params, stats_dict, gemini_report):
    conn = get_db_connection()
    if not conn: return
    try:
        cursor = conn.cursor()
        stats_json = json.dumps(stats_dict, ensure_ascii=False)
        sub_regs = ",".join(params.sub_regions) if params.sub_regions else "All"
        years_str = ",".join(params.years_multi)
        
        cursor.execute("""
            INSERT INTO Analysis_Cache (QueryHash, CountryName, SubRegions, LayerIndex, AnalyzedYears, StatsResultData, GeminiReport)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (query_hash, params.country, sub_regs, params.layer, years_str, stats_json, gemini_report))
        conn.commit()
    except Exception as e:
        print("Lỗi lưu DB:", e)
    finally: 
        if conn: conn.close()

# =========================================================
# 4. KHỞI TẠO GOOGLE EARTH ENGINE
# =========================================================
def init_gee():
    try:
        ee.Initialize(project=CONFIG["project_id"])
    except Exception as e:
        st.error(f"❌ Lỗi: Máy tính chưa kết nối với Google Earth Engine qua project {CONFIG['project_id']}")
        st.info("Vui lòng mở Terminal (CMD) và gõ lệnh: **earthengine authenticate**")
        st.stop()

init_gee()

# =========================================================
# 5. CSS — MODERN THEME
# =========================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');
:root { --primary: #4f46e5; --accent: #0ea5e9; --bg: #f8fafc; --surface: #ffffff; --border: #e2e8f0; --text: #1e293b; --muted: #64748b; --radius: 16px; }
html, body, [class*="css"] { font-family: 'Plus Jakarta Sans', sans-serif !important; }
body, html, .stApp { background: var(--bg) !important; color: var(--text) !important; font-size: 14px; }
div.block-container { padding: 1.5rem 2.5rem 2.5rem; max-width: 100%; }
section[data-testid="stSidebar"] { display: none !important; }

div[data-testid="stButton"] button { height: 3.2rem !important; font-size: 15px !important; font-weight: 700 !important; border-radius: 12px !important; transition: all 0.3s ease; background: var(--surface); color: var(--primary) !important; border: 1.5px solid #e0e7ff; }
div[data-testid="stButton"] button:hover { transform: translateY(-3px); border-color: var(--primary); box-shadow: 0 8px 20px rgba(79, 70, 229, 0.15) !important; }
div[data-testid="stButton"] button[kind="primary"] { background: linear-gradient(135deg, #4f46e5, #3b82f6) !important; border: none !important; color: white !important; box-shadow: 0 4px 15px rgba(79, 70, 229, 0.2); }

.stSelectbox label, .stMultiSelect label, .stSlider label, .stRadio label { font-size: 12px !important; font-weight: 700 !important; color: var(--text) !important; margin-bottom: 6px; letter-spacing: 0.3px; }
.stSelectbox > div > div, .stMultiSelect > div > div { background: var(--surface) !important; border: 1px solid var(--border) !important; border-radius: 10px !important; color: var(--text) !important; box-shadow: 0 2px 4px rgba(0,0,0,0.01); }
.stSelectbox > div > div:hover, .stMultiSelect > div > div:hover { border-color: var(--primary) !important; }

.main-title { display:flex; align-items:center; justify-content:space-between; background: transparent; padding: 10px 0 20px; border-bottom: 2px solid var(--border); margin-bottom: 25px; }
.main-title h1 { font-size: 26px !important; font-weight: 800 !important; color: var(--text) !important; margin:0 !important; letter-spacing: -0.5px; text-transform: uppercase; }
.main-title span { color: var(--primary); }

.section-header { font-size: 16px !important; font-weight: 800 !important; color: var(--text) !important; margin-bottom: 15px !important; display: flex; align-items: center; gap: 8px;}
.section-header::before { content:''; display:block; width:4px; height:18px; background:var(--primary); border-radius:4px; }

.kpi-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 16px;}
.kpi-card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 16px; transition: all 0.3s; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }
.kpi-card:hover { transform: translateY(-2px); box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05); border-color: #c7d2fe; }
.kpi-title { font-size: 11px !important; color: var(--muted) !important; text-transform: uppercase; font-weight: 700 !important; letter-spacing: 0.5px; margin-bottom: 4px; }
.kpi-value { font-size: 24px !important; font-weight: 800 !important; color: var(--text) !important; }

.ai-report { background: linear-gradient(145deg, #ffffff, #f8fafc); border: 1px solid #e2e8f0; border-radius: 16px; padding: 20px; margin-bottom: 20px; border-left: 5px solid var(--primary); box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); }

.map-toolbar { padding:10px 16px; border-radius:12px; font-size:14px !important; font-weight:600 !important; margin-bottom:15px; border: 1px solid #e0e7ff; background: #eef2ff; color: #3730a3; display: flex; justify-content: center; align-items: center; gap: 10px;}

button[data-baseweb="tab"] { font-size: 13px !important; font-weight: 600 !important; color: var(--muted) !important; background: transparent !important; padding: 10px 16px !important; border-radius: 30px !important; margin-right: 4px;}
button[data-baseweb="tab"][aria-selected="true"] { background: var(--text) !important; color: white !important; }

.leaflet-popup-content-wrapper { background: transparent !important; box-shadow: none !important; padding: 0 !important; overflow: hidden; }
.leaflet-popup-tip-container { display: none !important; }
</style>
""", unsafe_allow_html=True)

# =========================================================
# 6. DATA MODEL & SESSION STATE
# =========================================================
@dataclass
class AnalysisParams:
    country:     str
    sub_regions: List[str]
    layer:       str
    month:       str
    years_multi: List[str]

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
        "current_df_hist":     None 
    }
    for k, v in defaults.items():
        if k not in st.session_state: st.session_state[k] = v

init_session_state()

# =========================================================
# 7. GEE CORE FUNCTIONS 
# =========================================================
def is_lst(layer): return layer == "LST"
def get_collection_name(layer): return "LANDSAT/LC08/C02/T1_L2" if is_lst(layer) else "COPERNICUS/S2_SR_HARMONIZED"
def get_thresholds(layer): return [0, 0.2, 0.5] if layer == "NDVI" else ([-0.1, 0, 0.2] if layer == "NDBI" else [24, 29, 34])

def mask_s2(img): return img.updateMask(img.select("SCL").neq(3).And(img.select("SCL").neq(8)).And(img.select("SCL").neq(9)).And(img.select("SCL").neq(10)).And(img.select("SCL").neq(11))).divide(10000).copyProperties(img, img.propertyNames())
def mask_l8(img): qa = img.select("QA_PIXEL"); return img.updateMask(qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))).copyProperties(img, img.propertyNames())

@st.cache_data(ttl=86400, show_spinner=False)
def get_countries():
    try: return sorted(ee.FeatureCollection(CONFIG["admin_l1"]).aggregate_array("ADM0_NAME").distinct().sort().getInfo() or [])
    except: return ["Viet Nam"]

@st.cache_data(ttl=86400, show_spinner=False)
def get_sub_regions(country_name):
    try: return sorted(ee.FeatureCollection(CONFIG["admin_l1"]).filter(ee.Filter.eq("ADM0_NAME", country_name)).aggregate_array("ADM1_NAME").distinct().sort().getInfo() or [])
    except: return []

def get_dynamic_roi(country, sub_regions):
    fc = ee.FeatureCollection(CONFIG["admin_l1"]).filter(ee.Filter.eq("ADM0_NAME", country))
    if sub_regions: fc = fc.filter(ee.Filter.inList("ADM1_NAME", sub_regions))
    return fc

def get_image(geom, year, month, layer):
    lst_mode = is_lst(layer); start = ee.Date.fromYMD(int(year), int(month), 1)
    img = ee.Image(ee.ImageCollection(get_collection_name(layer)).filterBounds(geom).filterDate(start, start.advance(3, "month")).map(mask_l8 if lst_mode else mask_s2).median())
    if lst_mode: return img.addBands(img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")).clip(geom)
    return img.addBands([img.normalizedDifference(["B8","B4"]).rename("NDVI"), img.normalizedDifference(["B11","B8"]).rename("NDBI")]).clip(geom)

def classify_global(img, layer, geom=None, year=None, month=None):
    band = img.select(layer)
    t = get_thresholds(layer)
    return ee.Image(1).where(band.gte(t[0]).And(band.lt(t[1])), 2).where(band.gte(t[1]).And(band.lt(t[2])), 3).where(band.gte(t[2]), 4).updateMask(band.mask()).rename("CLASS").toInt()

# =========================================================
# 8. TÁCH BIỆT XỬ LÝ (NHANH: OBJECTS / CHẬM: STATS)
# =========================================================
def get_area_groups(classified_img, geom, scale): return ee.Image.pixelArea().divide(10000).addBands(classified_img).reduceRegion(reducer=ee.Reducer.sum().group(groupField=1), geometry=geom, scale=scale*2, maxPixels=1e13, tileScale=4, bestEffort=True).getInfo().get("groups", [])
def extract_area(groups, class_num): return next((g["sum"] for g in groups or [] if int(g["group"]) == class_num), 0.0)
def get_stats(img, layer, geom, scale): return img.select(layer).reduceRegion(reducer=ee.Reducer.mean().combine(ee.Reducer.min(), sharedInputs=True).combine(ee.Reducer.max(), sharedInputs=True), geometry=geom, scale=scale*2, maxPixels=1e13, tileScale=4, bestEffort=True).getInfo()
def get_histogram(img, layer, geom, scale): return img.select(layer).reduceRegion(reducer=ee.Reducer.histogram(20), geometry=geom, scale=scale*4, maxPixels=1e13, tileScale=4, bestEffort=True).getInfo().get(layer, {})

def build_base_objects(params: AnalysisParams):
    roi = get_dynamic_roi(params.country, params.sub_regions); geom = roi.geometry()
    years = sorted(params.years_multi); year_data = {}
    for year in years:
        img = get_image(geom, year, params.month, params.layer)
        year_data[year] = {
            "image": img, 
            "class": classify_global(img, params.layer, geom, year, params.month).clip(geom)
        }
    return {"roi": roi, "geom": geom, "years": years, "first_y": years[0], "last_y": years[-1], "year_data": year_data, "roi_names": " & ".join(params.sub_regions) if params.sub_regions else params.country}

def compute_stats(params: AnalysisParams, base: dict):
    geom, roi, first_y, last_y, year_data, years = base["geom"], base["roi"], base["first_y"], base["last_y"], base["year_data"], base["years"]
    
    trend_data = []
    for y in years:
        mean_val = year_data[y]["image"].select(params.layer).reduceRegion(reducer=ee.Reducer.mean(), geometry=geom, scale=CONFIG["scale"]*4, maxPixels=1e13, tileScale=4, bestEffort=True).getInfo().get(params.layer)
        if mean_val is not None: trend_data.append({"Năm": y, "Trị số": mean_val})
        
    bar_data = []
    if params.sub_regions and len(params.sub_regions) >= 2:
        for reg in params.sub_regions:
            val = year_data[last_y]["image"].select(params.layer).reduceRegion(reducer=ee.Reducer.mean(), geometry=roi.filter(ee.Filter.eq("ADM1_NAME", reg)).geometry(), scale=CONFIG["scale"]*2, maxPixels=1e13, tileScale=4, bestEffort=True).getInfo().get(params.layer)
            if val is not None: bar_data.append({"Khu vực": reg, "Trị số": val})

    return {
        "area_first": get_area_groups(year_data[first_y]["class"], geom, CONFIG["scale"]), 
        "area_last": get_area_groups(year_data[last_y]["class"],  geom, CONFIG["scale"]),
        "stats_first": get_stats(year_data[first_y]["image"], params.layer, geom, CONFIG["scale"]), 
        "stats_last": get_stats(year_data[last_y]["image"], params.layer, geom, CONFIG["scale"]),
        "hist_last": get_histogram(year_data[last_y]["image"], params.layer, geom, CONFIG["scale"]),
        "trend_data": trend_data, "bar_data": bar_data
    }

def fmt_val(layer, v): return "—" if v is None else (f"{v:.2f} °C" if layer=="LST" else f"{v:.4f}")

@st.cache_data(ttl=86400, show_spinner=False)
def get_address_from_coords(lat, lon):
    try:
        geolocator = Nominatim(user_agent="vietnam_gis_app")
        location = geolocator.reverse(f"{lat}, {lon}", exactly_one=True, timeout=5)
        if location: return location.address
        return "Không xác định được địa điểm"
    except: return "Không thể kết nối máy chủ định vị"

@st.cache_data(ttl=1800, show_spinner=False) 
def get_forecast_weather(lat, lon):
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&daily=temperature_2m_max,temperature_2m_min,weathercode,precipitation_probability_max&hourly=relative_humidity_2m&timezone=auto"
        res = requests.get(url, timeout=5).json()
        
        cw = res.get("current_weather", {})
        current_humidity = res.get("hourly", {}).get("relative_humidity_2m", [0])[0]
        
        current = {
            "temp": cw.get("temperature"), 
            "wind": cw.get("windspeed"), 
            "code": cw.get("weathercode"),
            "humidity": current_humidity
        }
        
        daily = res.get("daily", {})
        forecast = []
        if daily and "time" in daily:
            for i in range(len(daily["time"])):
                date_str = daily["time"][i]
                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                friendly_date = date_obj.strftime("%d/%m")
                forecast.append({
                    "date": friendly_date,
                    "max_t": daily["temperature_2m_max"][i],
                    "min_t": daily["temperature_2m_min"][i],
                    "code": daily["weathercode"][i],
                    "rain_prob": daily.get("precipitation_probability_max", [0]*7)[i]
                })
        return {"current": current, "forecast": forecast}
    except:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_three_indices(lat, lon, year, month):
    point = ee.Geometry.Point([lon, lat]); start = ee.Date.fromYMD(int(year), int(month), 1)
    col_s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(point).filterDate(start, start.advance(3, "month"))
    img_s2 = col_s2.map(mask_s2).median()
    col_l8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(point).filterDate(start, start.advance(3, "month"))
    img_l8 = col_l8.map(mask_l8).median()
    combined = ee.Image().addBands([img_s2.normalizedDifference(["B8","B4"]).rename("NDVI"), img_s2.normalizedDifference(["B11","B8"]).rename("NDBI"), img_l8.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")])
    try: vals = combined.reduceRegion(reducer=ee.Reducer.first(), geometry=point, scale=10).getInfo(); return {"NDVI": vals.get("NDVI"), "NDBI": vals.get("NDBI"), "LST": vals.get("LST")}
    except: return {"NDVI": None, "NDBI": None, "LST": None}

@st.cache_data(ttl=3600, show_spinner=False)
def get_full_history_at_point(lat, lon, month):
    point = ee.Geometry.Point([lon, lat])
    def get_year_val(y_str):
        start = ee.Date.fromYMD(ee.Number.parse(y_str), int(month), 1)
        img_s2 = ee.ImageCollection("COPERNICUS/S2_SR_HARMONIZED").filterBounds(point).filterDate(start, start.advance(3, "month")).map(mask_s2).median()
        img_l8 = ee.ImageCollection("LANDSAT/LC08/C02/T1_L2").filterBounds(point).filterDate(start, start.advance(3, "month")).map(mask_l8).median()
        vals = ee.Image().addBands([img_s2.normalizedDifference(["B8","B4"]).rename("NDVI"), img_s2.normalizedDifference(["B11","B8"]).rename("NDBI"), img_l8.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15).rename("LST")]).reduceRegion(reducer=ee.Reducer.first(), geometry=point, scale=10)
        return ee.Feature(None, {'Năm': y_str, 'NDVI': vals.get('NDVI'), 'NDBI': vals.get('NDBI'), 'LST': vals.get('LST')})
    try: return pd.DataFrame([{"Năm": f['properties']['Năm'], "NDVI": f['properties'].get('NDVI'), "NDBI": f['properties'].get('NDBI'), "LST": f['properties'].get('LST')} for f in ee.FeatureCollection(ee.List(CONFIG["years"]).map(get_year_val)).getInfo().get('features', [])])
    except: return pd.DataFrame()

@st.cache_data(ttl=86400, show_spinner=False)
def generate_timelapse_url(params: AnalysisParams, geom_dict):
    try:
        geom = ee.Geometry.Polygon(geom_dict); images = []
        for y in params.years_multi:
            img = get_image(geom, y, params.month, params.layer)
            images.append(classify_global(img, params.layer, geom, y, params.month).visualize(**CONFIG["vis"][params.layer]).set('system:time_start', ee.Date.fromYMD(int(y), int(params.month), 1).millis()))
        return ee.ImageCollection.fromImages(images).getVideoThumbURL({'dimensions': 600, 'framesPerSecond': 1.5, 'region': geom, 'format': 'gif'})
    except: return None

# =========================================================
# 9. BẢN ĐỒ VÀ HIỆU ỨNG POPUP 
# =========================================================
def add_legend(m, layer):
    html = f'''<div style="position:fixed;bottom:36px;left:36px;z-index:9999;background:#ffffff;padding:16px 20px;border-radius:14px;border:1px solid #e2e8f0;box-shadow:0 8px 25px rgba(0,0,0,.08);"><div style="color:#1e293b;font-size:14px;font-weight:800;margin-bottom:10px;text-transform:uppercase;">Phân lớp {layer}</div>'''
    for label, color in zip(CONFIG["class_labels"][layer], CONFIG["vis"][layer]["palette"]): html += f'''<div style="display:flex;align-items:center;margin-bottom:8px;"><div style="background:{color};width:16px;height:16px;border-radius:4px;margin-right:12px;flex-shrink:0;"></div><span style="font-size:13px;font-weight:600;color:#64748b;">{label}</span></div>'''
    m.get_root().html.add_child(folium.Element(html + '</div>'))

def add_background_mask(m, roi): geemap.ee_tile_layer(ee.Image(1).updateMask(ee.Image.constant(1).clip(roi).mask().Not()), {'palette': ['#cbd5e1']}, "Lớp nền xám", True, 0.55).add_to(m)

def base_map():
    m = folium.Map(location=st.session_state.get("map_center", [16.0, 106.0]), zoom_start=st.session_state.get("map_zoom", 6), control_scale=True, tiles=None)
    folium.TileLayer("CartoDB.Positron", name="Bản đồ nền sáng", overlay=False, control=True).add_to(m); folium.TileLayer("Esri.WorldImagery", name="Ảnh vệ tinh", overlay=False, control=True).add_to(m); MousePosition(position='bottomright', separator=' | ', prefix='Tọa độ:').add_to(m)
    return m

def center_map(m, result):
    try: bounds = result["geom"].bounds().coordinates().getInfo()[0]; m.fit_bounds([[min([pt[1] for pt in bounds]), min([pt[0] for pt in bounds])], [max([pt[1] for pt in bounds]), max([pt[0] for pt in bounds])]])
    except: pass

def add_click_popup(m, click_info):
    if click_info:
        lat, lon = click_info["lat"], click_info["lon"]
        address = click_info.get("address", "Đang cập nhật vị trí...")
        popup_html = f"""<div style="background: rgba(15, 23, 42, 0.85); backdrop-filter: blur(8px); border: 1px solid rgba(255,255,255,0.1); border-radius: 12px; padding: 15px; width: 240px; color: white; font-family: 'Plus Jakarta Sans', sans-serif; box-shadow: 0 10px 25px rgba(0,0,0,0.3);"><div style="font-size: 10px; color: #94a3b8; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 3px;">📍 Điểm định vị</div><div style="font-size: 12px; font-weight: 600; color: #e2e8f0; margin-bottom: 2px; line-height: 1.4;">{address}</div><div style="font-size: 10px; color: #64748b; margin-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px;">({lat:.4f}, {lon:.4f})</div><div style="display: flex; justify-content: space-between; margin-bottom: 6px;"><span style="font-size: 12px; color: #10b981; font-weight: 600;">🌿 NDVI (Vệ tinh)</span><span style="font-size: 13px; font-weight: 700; color: #f8fafc;">{fmt_val("NDVI", click_info["NDVI"])}</span></div><div style="display: flex; justify-content: space-between; margin-bottom: 6px;"><span style="font-size: 12px; color: #f59e0b; font-weight: 600;">🏢 NDBI (Bê tông)</span><span style="font-size: 13px; font-weight: 700; color: #f8fafc;">{fmt_val("NDBI", click_info["NDBI"])}</span></div><div style="display: flex; justify-content: space-between;"><span style="font-size: 12px; color: #ef4444; font-weight: 600;">🌡️ LST (Bề mặt)</span><span style="font-size: 13px; font-weight: 700; color: #f8fafc;">{fmt_val("LST", click_info["LST"])}</span></div></div>"""
        folium.Marker(location=[lat, lon], popup=folium.Popup(popup_html, max_width=300, show=True), icon=folium.Icon(color="red", icon="map-marker")).add_to(m)

def build_single_map(result, layer, display_year, click_info=None):
    m = base_map(); add_background_mask(m, result["roi"])
    geemap.ee_tile_layer(result["year_data"][display_year]["class"], CONFIG["vis"][layer], f"Phân loại {layer}", True, 0.9).add_to(m)
    geemap.ee_tile_layer(ee.Image().paint(result["roi"], 0, 2), {"palette": ["#4f46e5"]}, "Ranh giới", True, 1.0).add_to(m); add_legend(m, layer)
    if click_info: add_click_popup(m, click_info)
    if st.session_state.get("force_zoom"): center_map(m, result)
    return m

def build_swipe_map(result, layer, left_year, right_year, click_info=None):
    m = base_map(); add_background_mask(m, result["roi"])
    l = geemap.ee_tile_layer(result["year_data"][left_year]["class"],  CONFIG["vis"][layer], f"{layer} {left_year}",  True, 1.0)
    r = geemap.ee_tile_layer(result["year_data"][right_year]["class"], CONFIG["vis"][layer], f"{layer} {right_year}", True, 1.0)
    SideBySideLayers(l, r).add_to(m); geemap.ee_tile_layer(ee.Image().paint(result["roi"], 0, 2), {"palette": ["#4f46e5"]}, "Ranh giới", True, 1.0).add_to(m); add_legend(m, layer)
    if click_info: add_click_popup(m, click_info)
    if st.session_state.get("force_zoom"): center_map(m, result)
    return m

def build_change_map(result, layer, left_year, right_year, click_info=None):
    m = base_map(); add_background_mask(m, result["roi"])
    change = result["year_data"][right_year]["image"].select(layer).subtract(result["year_data"][left_year]["image"].select(layer))
    vis = {"min": -0.2, "max": 0.2, "palette": ["#ef4444", "#ffffff", "#10b981"]}
    if layer == "LST": vis = {"min": -3, "max": 3, "palette": ["#3b82f6", "#ffffff", "#ef4444"]} 
    elif layer == "NDBI": vis = {"min": -0.15, "max": 0.15, "palette": ["#10b981", "#ffffff", "#ef4444"]}
    geemap.ee_tile_layer(change.clip(result["geom"]), vis, f"Biến động {left_year} -> {right_year}", True, 0.9).add_to(m); geemap.ee_tile_layer(ee.Image().paint(result["roi"], 0, 2), {"palette": ["#4f46e5"]}, "Ranh giới", True, 1.0).add_to(m)
    html = f'''<div style="position:fixed;bottom:36px;left:36px;z-index:9999;background:#ffffff;padding:16px;border-radius:14px;border:1px solid #e2e8f0;box-shadow:0 8px 25px rgba(0,0,0,.08);"><div style="font-weight:800;border-bottom:1px solid #e2e8f0;padding-bottom:8px;margin-bottom:10px;">📉 Dấu vết Biến động</div><div style="color:#ef4444;font-weight:700;">🔴 Suy giảm</div><div style="color:#64748b;font-weight:700;">⚪ Không đổi</div><div style="color:#10b981;font-weight:700;">🟢 Tăng lên</div></div>'''
    if layer == "LST": html = html.replace("🔴 Suy giảm", "🔵 Giảm nhiệt").replace("🟢 Tăng lên", "🔴 Tăng nhiệt")
    elif layer == "NDBI": html = html.replace("🔴 Suy giảm", "🟢 Giảm Đô thị").replace("🟢 Tăng lên", "🔴 Tăng Bê tông")
    m.get_root().html.add_child(folium.Element(html))
    if click_info: add_click_popup(m, click_info)
    if st.session_state.get("force_zoom"): center_map(m, result)
    return m

# =========================================================
# 10. GIAO DIỆN & LOGIC ĐIỀU KHIỂN
# =========================================================
st.markdown("<div class='main-title'><h1>🌍 hệ thống mô phỏng và trực quan hóa <span>biến động đô thị hóa</span></h1></div>", unsafe_allow_html=True)
col_ctrl, col_map, col_report = st.columns([1.2, 2.8, 1.5], gap="large")

# ════════ CỘT 1: ĐIỀU KHIỂN ════════
with col_ctrl:
    with st.container(border=False):
        st.markdown("<div class='section-header'>Thiết lập Không gian</div>", unsafe_allow_html=True)
        with st.container(border=True):
            countries = get_countries()
            country = st.selectbox("Quốc gia", countries, index=countries.index("Viet Nam") if "Viet Nam" in countries else 0)
            selected_subregions = st.multiselect("Vùng quan trắc (Bỏ trống = Quét toàn quốc)", get_sub_regions(country), placeholder="Nhấn để chọn Tỉnh/Thành/Bang...")
                        
        st.markdown("<br><div class='section-header'>Tham số Thu thập</div>", unsafe_allow_html=True)
        with st.container(border=True):
            layer = st.selectbox("Chỉ số Viễn thám", ["NDBI", "LST", "NDVI"]) 
            month = st.selectbox("Tháng đồng bộ", CONFIG["months"], index=2)
            years_multi = st.multiselect("Các năm phân tích", CONFIG["years"], default=["2022","2024","2026"])

        st.markdown("<br>", unsafe_allow_html=True)
        
        if st.button("🚀 KHỞI CHẠY HỆ THỐNG", use_container_width=True, type="primary"):
            if len(years_multi) == 0: 
                st.warning("⚠️ Chọn ít nhất 1 năm!")
            else:
                params = AnalysisParams(country, selected_subregions, layer, month, years_multi)
                q_hash = get_query_hash(country, selected_subregions, layer, month, years_multi)
                
                base_obj = build_base_objects(params)
                cached_data = check_cache_in_db(q_hash)
                
                if cached_data:
                    st.toast("⚡ Đã tải dữ liệu từ CSDL (Smart Cache) trong 0.1 giây!", icon="⚡")
                    final_result = {**base_obj, **cached_data["result"]}
                    
                    st.session_state.update({
                        "params": params, 
                        "result": final_result, 
                        "cached_report": cached_data["gemini_report"], 
                        "analyzed": True, 
                        "display_year": sorted(years_multi)[-1], 
                        "map_click_value": None, 
                        "last_clicked_coords": None, 
                        "compare_left": sorted(years_multi)[0], 
                        "compare_right": sorted(years_multi)[-1], 
                        "force_zoom": True,
                        "pending_db_save": False
                    })
                else:
                    with st.spinner("⏳ Dữ liệu mới. Đang thu thập và chạy AI Phân tích..."):
                        try:
                            stats = compute_stats(params, base_obj)
                            final_result = {**base_obj, **stats}
                            
                            st.session_state.update({
                                "params": params, 
                                "result": final_result, 
                                "cached_report": None, 
                                "analyzed": True, 
                                "display_year": sorted(years_multi)[-1], 
                                "map_click_value": None, 
                                "last_clicked_coords": None, 
                                "compare_left": sorted(years_multi)[0], 
                                "compare_right": sorted(years_multi)[-1], 
                                "force_zoom": True,
                                "current_hash": q_hash,
                                "pending_db_save": True 
                            })
                        except Exception as e: st.error(f"Lỗi truy xuất: {e}")
# =========================================================
        # NÚT 2: TRỢ LÝ AI THỜI TIẾT (Được căn chỉnh cùng kích thước)
        # =========================================================
        st.markdown("""
        <a href="http://127.0.0.1:5500/weather_chat_demo.html" target="_blank" style="text-decoration:none;">
            <button style="width:100%; height:3.2rem; border-radius:12px; background: linear-gradient(135deg, #0ea5e9, #3b82f6); color:white; border:none; font-weight:bold; font-size:15px; cursor:pointer; margin-top: 8px; box-shadow: 0 4px 15px rgba(14, 165, 233, 0.3); transition: all 0.3s ease;">
                💬 HỎI ĐÁP AI THỜI TIẾT
            </button>
        </a>
        """, unsafe_allow_html=True)
# ════════ CỘT 2: BẢN ĐỒ & CHUỖI THỜI GIAN ════════
with col_map:
    if st.session_state["analyzed"] and st.session_state["result"] is not None:
        result = st.session_state["result"]; params = st.session_state["params"]

        c_mode1, c_mode2 = st.columns([1.5, 1])
        map_mode = c_mode1.radio("Chế độ", ["🗺️ Bản đồ đơn", "🪞 Trượt so sánh", "📍 Dấu vết biến động", "🎞️ Chuyển động thời gian"], horizontal=True, label_visibility="collapsed")
        st.session_state["map_mode"] = map_mode

        if "main_map" in st.session_state and st.session_state["main_map"]:
            map_data = st.session_state["main_map"]
            if map_data.get("center"): st.session_state["map_center"] = [map_data["center"]["lat"], map_data["center"]["lng"]]
            if map_data.get("zoom"): st.session_state["map_zoom"] = map_data["zoom"]
            
            if map_data.get("last_clicked") and map_mode != "🎞️ Chuyển động thời gian":
                lat, lon = map_data["last_clicked"]["lat"], map_data["last_clicked"]["lng"]
                if st.session_state.get("last_clicked_coords") != (lat, lon):
                    st.session_state["last_clicked_coords"] = (lat, lon)
                    query_year = st.session_state["display_year"] if map_mode == "🗺️ Bản đồ đơn" else st.session_state["compare_right"]
                    with st.spinner("⏳ Đang thu thập dữ liệu thời tiết (Hiện tại & 7 Ngày tới)..."):
                        address = get_address_from_coords(lat, lon)
                        vals = get_three_indices(lat, lon, query_year, params.month)
                        weather_data = get_forecast_weather(lat, lon)
                        
                        st.session_state["map_click_value"] = {
                            "lat": lat, "lon": lon, "address": address, 
                            "NDVI": vals["NDVI"], "NDBI": vals["NDBI"], "LST": vals["LST"],
                            "weather": weather_data 
                        }
                    st.rerun()

        click_info = st.session_state.get("map_click_value")

        if map_mode == "🗺️ Bản đồ đơn":
            st.session_state["display_year"] = c_mode2.selectbox("Năm", result["years"], index=result["years"].index(st.session_state["display_year"]), label_visibility="collapsed")
            m = build_single_map(result, params.layer, st.session_state["display_year"], click_info)
            st.markdown(f"<div class='map-toolbar'>🗺️ Lớp phủ {params.layer} năm {st.session_state['display_year']} </div>", unsafe_allow_html=True)
            st_folium(m, width=None, height=520, returned_objects=["last_clicked", "center", "zoom"], key="main_map")
            
        elif map_mode in ["🪞 Trượt so sánh", "📍 Dấu vết biến động"]: 
            if len(result["years"]) < 2: st.warning("⚠️ Yêu cầu chọn từ 2 năm trở lên!")
            else:
                cl, cr = c_mode2.columns(2)
                st.session_state["compare_left"] = cl.selectbox("Năm gốc", result["years"], index=result["years"].index(st.session_state["compare_left"]), label_visibility="collapsed")
                st.session_state["compare_right"] = cr.selectbox("Năm so sánh", result["years"], index=result["years"].index(st.session_state["compare_right"]), label_visibility="collapsed")
                if map_mode == "🪞 Trượt so sánh":
                    m = build_swipe_map(result, params.layer, st.session_state["compare_left"], st.session_state["compare_right"], click_info)
                    st.markdown(f"<div class='map-toolbar'>🪞 So sánh trực tiếp: {st.session_state['compare_left']} ←|→ {st.session_state['compare_right']}</div>", unsafe_allow_html=True)
                else:
                    m = build_change_map(result, params.layer, st.session_state["compare_left"], st.session_state["compare_right"], click_info)
                    st.markdown(f"<div class='map-toolbar'>📍 Phân tích biến động: {st.session_state['compare_left']} → {st.session_state['compare_right']}</div>", unsafe_allow_html=True)
                st_folium(m, width=None, height=520, returned_objects=["last_clicked", "center", "zoom"], key="main_map")

        elif map_mode == "🎞️ Chuyển động thời gian":
            st.markdown("<div class='map-toolbar'>🎞️ Đang thiết lập video ảnh động...</div>", unsafe_allow_html=True)
            bounds = result["geom"].bounds().coordinates().getInfo()[0]
            with st.spinner("⏳ Đang kết xuất video..."):
                gif_url = generate_timelapse_url(params, bounds)
                if gif_url: st.markdown(f"<div style='text-align:center;'><img src='{gif_url}' width='100%' style='border-radius:12px; box-shadow:0 10px 25px rgba(0,0,0,0.1);'></div>", unsafe_allow_html=True)
                else: st.error("Khu vực quá lớn hoặc xảy ra lỗi.")

        if st.session_state.get("force_zoom"): st.session_state["force_zoom"] = False

        if click_info and map_mode != "🎞️ Chuyển động thời gian":
            cv = click_info; c_info, c_btn = st.columns([5, 1])
            c_info.markdown(f"**📍 Tại:** `{cv['address']}`")
            if c_btn.button("✖ Xóa", use_container_width=True): 
                st.session_state["map_click_value"] = None
                st.session_state["last_clicked_coords"] = None
                st.session_state["current_df_hist"] = None
                st.rerun()

            with st.spinner("⏳ Đang tải chuỗi thời gian..."):
                df_hist = get_full_history_at_point(cv["lat"], cv["lon"], params.month).dropna()
                st.session_state["current_df_hist"] = df_hist 
                
                if not df_hist.empty:
                    fig_hist = make_subplots(specs=[[{"secondary_y": True}]])
                    fig_hist.add_trace(go.Scatter(x=df_hist["Năm"], y=df_hist["NDVI"], name="🌿 NDVI", line=dict(color="#10b981", width=3)), secondary_y=False)
                    fig_hist.add_trace(go.Scatter(x=df_hist["Năm"], y=df_hist["NDBI"], name="🏢 NDBI", line=dict(color="#f97316", width=3)), secondary_y=False)
                    fig_hist.add_trace(go.Scatter(x=df_hist["Năm"], y=df_hist["LST"], name="🌡️ LST (°C)", line=dict(color="#e11d48", width=3, dash='dot')), secondary_y=True)
                    fig_hist.update_layout(hovermode="x unified", height=260, margin=dict(l=10,r=10,t=10,b=10), plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", legend=dict(orientation="h", y=1.05))
                    st.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar":False})
            
    else:
        st_folium(folium.Map(location=[16.0,106.0], zoom_start=6, tiles="CartoDB.Positron"), width=None, height=750)

# ════════ CỘT 3: BÁO CÁO (GRID & SMART AI CACHE) ════════
with col_report:
    with st.container(border=False):
        st.markdown("<div class='section-header'>Thống kê Chỉ số</div>", unsafe_allow_html=True)

        if st.session_state["analyzed"] and st.session_state["result"] is not None:
            params = st.session_state["params"]; result = st.session_state["result"]
            stats_first = result.get("stats_first", {}); stats_last = result["stats_last"]
            PD = dict(plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)", font_color="#1e293b", font_family="'Plus Jakarta Sans', sans-serif")

            first_y, last_y = result["first_y"], result["last_y"]
            l_mean_first = stats_first.get(f"{params.layer}_mean",0) or 0
            l_mean_last = stats_last.get(f"{params.layer}_mean",0) or 0
            a_l = extract_area(result["area_last"],3) + extract_area(result["area_last"],4)
            status = "Tốt" if l_mean_last > 0.4 else ("Cảnh báo" if l_mean_last < 0.2 else "Trung bình")
            color_st = "#059669" if status == "Tốt" else ("#e11d48" if status == "Cảnh báo" else "#f97316")
            main_color = "#4f46e5"

            st.markdown(f"""
                <div class='kpi-grid'>
                    <div class='kpi-card'><div class='kpi-title'>Diện tích cấp cao</div><div class='kpi-value'>{a_l:,.0f} <span style='font-size:12px;color:#64748b;'>Ha</span></div></div>
                    <div class='kpi-card'><div class='kpi-title'>Đánh giá chung</div><div class='kpi-value' style='color:{color_st};'>{status}</div></div>
                    <div class='kpi-card'><div class='kpi-title'>{params.layer} Hiện tại</div><div class='kpi-value' style='color:var(--primary);'>{fmt_val(params.layer,l_mean_last)}</div></div>
                    <div class='kpi-card'><div class='kpi-title'>{params.layer} Khởi điểm</div><div class='kpi-value' style='color:#64748b;'>{fmt_val(params.layer,l_mean_first)}</div></div>
                </div>
            """, unsafe_allow_html=True)

            if status == "Cảnh báo":
                st.error(f"🚨 CẢNH BÁO MÔI TRƯỜNG: Chỉ số trung bình {params.layer} đang ở mức rủi ro tại khu vực này. Cần có biện pháp quy hoạch hoặc theo dõi chặt chẽ!")

            API_KEY = "AIzaSyCZ3kJj-oKw0oo1Sj9m4-Iezsf1cibynIQ" 
            
            def generate_gemini_report(layer, first_year, last_year, first_val, last_val, high_area, roi_name):
                try:
                    client = genai.Client(api_key=API_KEY)
                    prompt = f"Viết 1 đoạn báo cáo học thuật (150 chữ) về {roi_name} ({first_year}-{last_year}). Chỉ số {layer} đổi từ {first_val:.3f} sang {last_val:.3f}. Vùng rủi ro: {high_area:,.0f} Ha. Cảnh báo môi trường và đề xuất vĩ mô. Không dùng gạch đầu dòng."
                    response = client.models.generate_content(model='gemini-2.5-flash', contents=prompt)
                    return response.text
                except Exception as e: return f"Lỗi gọi AI: {e}"

            if st.session_state.get("pending_db_save"):
                with st.spinner("🤖 AI đang phân tích dữ liệu lần đầu..."):
                    academic_report = generate_gemini_report(params.layer, first_y, last_y, l_mean_first, l_mean_last, a_l, result["roi_names"])
                    st.session_state["cached_report"] = academic_report
                    stats_to_save = {k: result[k] for k in ["area_first", "area_last", "stats_first", "stats_last", "hist_last", "trend_data", "bar_data"]}
                    save_cache_to_db(st.session_state["current_hash"], params, stats_to_save, academic_report)
                    st.session_state["pending_db_save"] = False 

            st.markdown(f"""
            <div class='ai-report'>
                <div style='font-size:12px; color:var(--primary); font-weight:800; text-transform:uppercase; margin-bottom:10px;'>🤖 Báo Cáo Chuyên Sâu (Gemini 2.5)</div>
                <div style='font-size:14.5px; line-height:1.75; color:#334155; text-align: justify;'>{st.session_state.get("cached_report", "...")}</div>
            </div>
            """, unsafe_allow_html=True)

            tabs = st.tabs(["⛅ Thời tiết", "📈 Xu hướng", "📊 Mật độ", "🥧 Cơ cấu", "🌡️ Đảo nhiệt", "📥 Tải Về"])
            
            with tabs[0]:
                if st.session_state.get("map_click_value") and st.session_state["map_click_value"].get("weather"):
                    weather_data = st.session_state["map_click_value"]["weather"]
                    w_curr = weather_data["current"]
                    w_fore = weather_data["forecast"]
                    
                    st.markdown(f"**Vị trí:** `{st.session_state['map_click_value']['address']}`")
                    st.markdown("<div style='font-size:13px; font-weight:700; margin-bottom:10px; color:#0ea5e9;'>Thời tiết Hiện tại</div>", unsafe_allow_html=True)
                    w_col1, w_col2, w_col3 = st.columns(3)
                    w_col1.metric("Nhiệt độ", f"{w_curr['temp']} °C")
                    w_col2.metric("Gió", f"{w_curr['wind']} km/h")
                    w_col3.metric("Độ ẩm", f"{w_curr.get('humidity', '--')} %")
                    
                    st.markdown("---")
                    st.markdown("<div style='font-size:13px; font-weight:700; margin-bottom:10px; color:#f59e0b;'>Dự báo 7 ngày tới</div>", unsafe_allow_html=True)
                    if w_fore:
                        df_fore = pd.DataFrame(w_fore)
                        fig_fore = go.Figure()
                        fig_fore.add_trace(go.Scatter(x=df_fore["date"], y=df_fore["max_t"], mode='lines+markers+text', name='Cao nhất', line=dict(color="#ef4444", width=2), text=df_fore["max_t"].apply(lambda x: f"{x:.1f}°"), textposition="top center"))
                        fig_fore.add_trace(go.Scatter(x=df_fore["date"], y=df_fore["min_t"], mode='lines+markers+text', name='Thấp nhất', line=dict(color="#3b82f6", width=2), text=df_fore["min_t"].apply(lambda x: f"{x:.1f}°"), textposition="bottom center"))
                        fig_fore.update_layout(height=250, margin=dict(l=10,r=10,t=10,b=10), xaxis_type="category", legend=dict(orientation="h", y=1.15), **PD)
                        fig_fore.update_yaxes(showticklabels=False, showgrid=False)
                        st.plotly_chart(fig_fore, use_container_width=True, config={"displayModeBar":False})
                        
                else:
                    st.info("📍 Vui lòng Click vào một điểm trên bản đồ để xem thông tin thời tiết thực tế tại khu vực đó.")

            with tabs[1]: 
                if result["trend_data"] and len(result["trend_data"]) >= 3:
                    try:
                        df_t = pd.DataFrame(result["trend_data"])
                        df_prophet = df_t.rename(columns={"Năm": "ds", "Trị số": "y"})
                        df_prophet['ds'] = pd.to_datetime(df_prophet['ds'], format='%Y')
                        m = Prophet(yearly_seasonality=False, weekly_seasonality=False, daily_seasonality=False); m.fit(df_prophet)
                        forecast = m.predict(m.make_future_dataframe(periods=4, freq='YS'))
                        forecast['Năm'] = forecast['ds'].dt.strftime('%Y')
                        
                        fig1 = go.Figure()
                        fig1.add_trace(go.Scatter(x=df_t["Năm"], y=df_t["Trị số"], mode='lines+markers+text', name='Thực tế', line=dict(color="#4f46e5", width=3), text=df_t["Trị số"].apply(lambda x: f"{x:.3f}"), textposition="top center"))
                        df_future = forecast[forecast['ds'] > df_prophet['ds'].max()]
                        fig1.add_trace(go.Scatter(x=df_future["Năm"], y=df_future["yhat"], mode='lines+markers+text', name='✨ Dự báo', line=dict(color="#f97316", width=3, dash='dash'), text=df_future["yhat"].apply(lambda x: f"{x:.3f}"), textposition="top center"))
                        fig1.update_layout(height=280, margin=dict(l=10,r=10,t=30,b=10), xaxis_type="category", legend=dict(orientation="h", y=1.1), **PD)
                        st.plotly_chart(fig1, use_container_width=True, config={"displayModeBar":False})
                        
                        # --- THÊM NHẬN XÉT ĐỘNG CHO TAB 1 ---
                        start_val = df_t.iloc[0]["Trị số"]
                        end_val = df_t.iloc[-1]["Trị số"]
                        trend_stt = "tăng lên" if end_val > start_val else "giảm đi"
                        st.info(f"📝 **Nhận xét nhanh:** Nhìn vào biểu đồ, có thể thấy chỉ số {params.layer} trung bình đang có xu hướng **{trend_stt}** qua các năm (từ {start_val:.3f} thay đổi thành {end_val:.3f}).")
                    except: pass
                else: st.info("Chọn >= 3 năm để AI dự báo.")

            with tabs[2]:
                hist = result["hist_last"]
                if hist and "histogram" in hist:
                    counts = hist["histogram"]; buckets = [hist["bucketMin"] + i*hist["bucketWidth"] for i in range(len(counts))]
                    fig2 = px.bar(x=buckets, y=counts, color_discrete_sequence=[main_color])
                    fig2.add_vline(x=l_mean_last, line_dash="dash", line_color="#f97316", annotation_text="Trung bình")
                    fig2.update_layout(height=260, margin=dict(l=10,r=10,t=10,b=10), **PD)
                    st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar":False})
                    
                    # --- THÊM NHẬN XÉT ĐỘNG CHO TAB 2 ---
                    st.info(f"📝 **Nhận xét nhanh:** Phần lớn diện tích khu vực đang tập trung và xoay quanh mức giá trị **{l_mean_last:.2f}**. Các cột biểu đồ càng cao chứng tỏ mức độ đó chiếm diện tích càng lớn trên bản đồ.")

            with tabs[3]:
                pie_data = [{"Lớp": CONFIG["class_labels"][params.layer][i], "Ha": extract_area(result["area_last"], i+1), "Màu": CONFIG["vis"][params.layer]["palette"][i]} for i in range(4) if extract_area(result["area_last"], i+1) > 0]
                if pie_data:
                    fig3 = go.Figure(go.Pie(labels=[d["Lớp"] for d in pie_data], values=[d["Ha"] for d in pie_data], hole=0.6, marker=dict(colors=[d["Màu"] for d in pie_data])))
                    fig3.update_traces(textposition='outside', textinfo='label+percent')
                    fig3.update_layout(height=280, margin=dict(l=30,r=30,t=20,b=10), showlegend=False, annotations=[dict(text=f'Tổng<br>{int(sum([d["Ha"] for d in pie_data])):,} Ha', x=0.5, y=0.5, font_size=13, showarrow=False)], **PD)
                    st.plotly_chart(fig3, use_container_width=True, config={"displayModeBar":False})
                    
                    # --- THÊM NHẬN XÉT ĐỘNG CHO TAB 3 ---
                    max_slice = max(pie_data, key=lambda x: x["Ha"])
                    st.info(f"📝 **Nhận xét nhanh:** Hiện trạng **{max_slice['Lớp']}** đang chiếm ưu thế lớn nhất trong toàn bộ khu vực, với tổng diện tích lên tới khoảng **{max_slice['Ha']:,.0f} Ha**.")

            with tabs[4]:
                if st.session_state.get("current_df_hist") is not None and not st.session_state["current_df_hist"].empty:
                    df_u = st.session_state["current_df_hist"]
                    st.markdown("<div style='font-size:13px; font-weight:700; margin-bottom:10px;'>Tương quan Thực vật (NDVI) & Nhiệt độ (LST)</div>", unsafe_allow_html=True)
                    
                    # 1. Vẽ biểu đồ với Plotly
                    fig_uhi = px.scatter(df_u, x="NDVI", y="LST", color="Năm", size="NDBI", hover_data=["Năm", "NDVI", "LST", "NDBI"], trendline="ols")
                    fig_uhi.update_layout(height=280, margin=dict(l=10,r=10,t=10,b=10), **PD)
                    st.plotly_chart(fig_uhi, use_container_width=True, config={"displayModeBar":False})
                    
                    # 2. Ứng dụng Scikit-learn để phân tích Hồi quy tuyến tính
                    try:
                        X = df_u[['NDVI']].values
                        y = df_u['LST'].values
                        
                        model = LinearRegression()
                        model.fit(X, y)
                        
                        y_pred = model.predict(X)
                        r2 = r2_score(y, y_pred)
                        coef = model.coef_[0]
                        
                        st.info(f"""
                        📝 **Phân tích mô hình học máy (Scikit-learn):** - **Phương trình tương quan:** `LST = {coef:.2f} * NDVI + {model.intercept_:.2f}`
                        - **Độ tin cậy của mô hình (R²):** `{r2:.2f}` 
                        - **Kết luận:** {'Mô hình có độ tin cậy cao' if r2 > 0.5 else 'Dữ liệu phân tán khá rộng'}. Hệ số góc `{coef:.2f}` cho thấy khi diện tích thực vật (NDVI) tăng lên, nhiệt độ bề mặt (LST) có xu hướng {'giảm đi' if coef < 0 else 'tăng lên'}, minh chứng rõ rệt cho hiệu ứng Đảo nhiệt đô thị (UHI).
                        """)
                    except Exception as e:
                        st.warning("Cần thêm dữ liệu để chạy mô hình Machine Learning.")
                else:
                    st.info("📍 Hãy click vào 1 điểm trên bản đồ để tải dữ liệu tương quan UHI (Urban Heat Island).")

            with tabs[5]:
                st.download_button("📄 Tải số liệu (CSV)", data=pd.DataFrame(result["trend_data"]).to_csv(index=False).encode('utf-8-sig'), file_name=f"Data_{result['roi_names']}.csv", mime="text/csv", use_container_width=True)
                
                if st.session_state.get("cached_report"):
                    st.download_button("📝 Tải Báo Cáo AI (TXT)", data=st.session_state["cached_report"].encode('utf-8'), file_name=f"BaoCao_AI_{result['roi_names']}.txt", mime="text/plain", use_container_width=True)
                
                try:
                    url_tif = result["year_data"][last_y]["image"].select(params.layer).getDownloadURL({'scale': CONFIG["scale"], 'region': result['geom']})
                    st.markdown(f"<a href='{url_tif}' target='_blank' style='text-decoration:none;'><button style='width:100%; padding:10px; border-radius:10px; background:var(--primary); color:white; border:none; font-weight:bold; margin-top:10px;'>🗺️ Tải Bản đồ {last_y} (GeoTIFF)</button></a>", unsafe_allow_html=True)
                except: pass

        else:
            st.markdown("<div style='text-align:center; padding:50px 20px; color:#94A3B8; background:#ffffff; border-radius:16px; border:1px dashed #cbd5e1;'>Hệ thống chưa có dữ liệu.<br>Vui lòng ấn Khởi chạy.</div>", unsafe_allow_html=True)