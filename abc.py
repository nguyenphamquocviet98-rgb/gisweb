import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import ee
import folium
from folium.plugins import SideBySideLayers
import geemap.foliumap as geemap
import pandas as pd
import plotly.express as px
import streamlit as st
from streamlit_folium import st_folium


# =========================================================
# 1. CẤU HÌNH TRANG
# =========================================================
st.set_page_config(
    layout="wide",
    page_title="Hệ Thống Phân Tích GEE Tổng Lực",
    page_icon="🌍"
)


# =========================================================
# 2. CẤU HÌNH CHUNG
# =========================================================
CONFIG = {
    "project_id": "tphcm-470513",
    "admin_fc": "FAO/GAUL/2015/level1",
    "scale": 250,
    "years": [str(y) for y in range(2018, 2027)],
    "months": [f"{i:02d}" for i in range(1, 13)],
    "vis": {
        "NDVI": {
            "min": 1,
            "max": 4,
            "palette": ["#e74c3c", "#f1c40f", "#2ecc71", "#27ae60"],
        },
        "NDBI": {
            "min": 1,
            "max": 4,
            "palette": ["#27ae60", "#f1c40f", "#e67e22", "#c0392b"],
        },
        "LST": {
            "min": 1,
            "max": 4,
            "palette": ["#3498db", "#f1c40f", "#e67e22", "#e74c3c"],
        },
    },
    "class_labels": {
        "NDVI": ["Nước/Đất trống", "Đất thưa", "Thực vật bụi", "Rừng rậm"],
        "NDBI": ["Rừng/Nước", "Đất trống", "Đô thị thưa", "Đô thị nén"],
        "LST": ["Mát (<24°C)", "Bình thường (24-29°C)", "Nóng (29-34°C)", "Rất nóng (>34°C)"],
    },
    "threshold_labels": {
        "NDVI": ["< 0.00", "0.00 - 0.20", "0.20 - 0.50", ">= 0.50"],
        "NDBI": ["< -0.10", "-0.10 - 0.00", "0.00 - 0.20", ">= 0.20"],
        "LST": ["< 24°C", "24 - 29°C", "29 - 34°C", ">= 34°C"],
    },
}


# =========================================================
# 3. CSS GIAO DIỆN
# =========================================================
st.markdown("""
<style>
div.block-container {padding-top: 1rem; padding-bottom: 1rem;}

.box-title {
    color: #1a5276;
    font-weight: bold;
    font-size: 15px;
    margin-top: 10px;
    text-transform: uppercase;
}

.report-card {
    background-color: #ebf5fb;
    border: 2px solid #1a5276;
    padding: 15px;
    border-radius: 8px;
    margin-bottom: 15px;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
}

.danger-title {
    color: #c0392b;
    font-weight: bold;
    font-size: 16px;
    margin-bottom: 10px;
    text-transform: uppercase;
    border-bottom: 2px solid #c0392b;
    padding-bottom: 5px;
}

.chart-box {
    border: 1px solid #e5e7e9;
    padding: 10px;
    border-radius: 8px;
    margin-bottom: 15px;
    background: white;
    box-shadow: 2px 2px 5px rgba(0,0,0,0.05);
}

.map-banner-cinema {
    background: linear-gradient(90deg, #0f2027, #203a43, #2c5364);
    color: white;
    padding: 10px 14px;
    border-radius: 10px;
    margin-bottom: 8px;
    font-weight: 700;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.map-banner-swipe {
    background: linear-gradient(90deg, #42275a, #734b6d);
    color: white;
    padding: 10px 14px;
    border-radius: 10px;
    margin-bottom: 8px;
    font-weight: 700;
    letter-spacing: 0.5px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
}

.kpi-card {
    background: white;
    border: 1px solid #dfe6e9;
    border-radius: 10px;
    padding: 10px;
    text-align: center;
    box-shadow: 1px 2px 6px rgba(0,0,0,0.05);
}

.kpi-title {
    font-size: 11px;
    color: #7f8c8d;
    text-transform: uppercase;
    margin-bottom: 6px;
}

.kpi-value {
    font-size: 18px;
    font-weight: 700;
    color: #1a5276;
}

div[data-baseweb="slider"] > div {
    padding-top: 0.2rem;
    padding-bottom: 0.2rem;
}

div[data-baseweb="slider"] [role="slider"] {
    box-shadow: 0 0 0 4px rgba(52, 152, 219, 0.15);
}

#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)


# =========================================================
# 4. MÔ HÌNH DỮ LIỆU
# =========================================================
@dataclass
class AnalysisParams:
    country: str
    provinces: List[str]
    layer: str
    year_base: str
    month: str
    years_multi: List[str]
    specific_id: Optional[str] = None


# =========================================================
# 5. SESSION STATE
# =========================================================
def init_session_state():
    defaults = {
        "image_options": {"Ghép quý liền mạch (Mặc định)": None},
        "analyzed": False,
        "params": None,
        "result": None,
        "display_year": None,
        "map_mode": "🎬 Xem từng năm",
        "compare_left_year": None,
        "compare_right_year": None,
        "timeline_index": 0,
        "play_animation": False,
        "play_speed": 1.0,
        "map_click_value": None,
        "last_map_bounds": None,
        "last_map_zoom": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()


# =========================================================
# 6. KHỞI TẠO GEE
# =========================================================
def init_gee():
    try:
        ee.Initialize(project=CONFIG["project_id"])
    except Exception as e:
        st.error(f"Lỗi khởi tạo Google Earth Engine: {e}")
        st.warning("Hãy chạy `earthengine authenticate` trong terminal.")
        st.stop()


init_gee()


# =========================================================
# 7. HÀM XỬ LÝ GEE
# =========================================================
def is_lst(layer: str) -> bool:
    return layer == "LST"


def get_collection_name(layer: str) -> str:
    return "LANDSAT/LC08/C02/T1_L2" if is_lst(layer) else "COPERNICUS/S2_SR_HARMONIZED"


def get_thresholds(layer: str) -> List[float]:
    if layer == "NDVI":
        return [0, 0.2, 0.5]
    if layer == "NDBI":
        return [-0.1, 0, 0.2]
    return [24, 29, 34]


def mask_s2(img: ee.Image) -> ee.Image:
    scl = img.select("SCL")
    mask = scl.neq(3).And(scl.neq(8)).And(scl.neq(9)).And(scl.neq(10)).And(scl.neq(11))
    return img.updateMask(mask).divide(10000).copyProperties(img, img.propertyNames())


def mask_l8(img: ee.Image) -> ee.Image:
    qa = img.select("QA_PIXEL")
    mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
    return img.updateMask(mask).copyProperties(img, img.propertyNames())


def get_roi(country: str, provinces: List[str]) -> ee.FeatureCollection:
    return (
        ee.FeatureCollection(CONFIG["admin_fc"])
        .filter(ee.Filter.eq("ADM0_NAME", country))
        .filter(ee.Filter.inList("ADM1_NAME", provinces))
    )


def get_image(
    geom: ee.Geometry,
    year: str,
    month: str,
    layer: str,
    specific_id: Optional[str] = None
) -> ee.Image:
    lst_mode = is_lst(layer)

    if specific_id:
        img = ee.Image(specific_id)
        img = mask_l8(img) if lst_mode else mask_s2(img)
    else:
        start = ee.Date.fromYMD(int(year), int(month), 1)
        end = start.advance(3, "month")
        col = ee.ImageCollection(get_collection_name(layer)).filterBounds(geom).filterDate(start, end)
        col = col.map(mask_l8 if lst_mode else mask_s2)
        img = col.median()

    img = ee.Image(img)

    if lst_mode:
        lst_c = img.select("ST_B10").multiply(0.00341802).add(149.0).subtract(273.15)
        return img.addBands(lst_c.rename("LST")).clip(geom)

    ndvi = img.normalizedDifference(["B8", "B4"]).rename("NDVI")
    ndbi = img.normalizedDifference(["B11", "B8"]).rename("NDBI")
    return img.addBands([ndvi, ndbi]).clip(geom)


def classify(img: ee.Image, layer: str) -> ee.Image:
    band = img.select(layer)
    t = get_thresholds(layer)

    return (
        ee.Image(1)
        .where(band.gte(t[0]).And(band.lt(t[1])), 2)
        .where(band.gte(t[1]).And(band.lt(t[2])), 3)
        .where(band.gte(t[2]), 4)
        .updateMask(band.mask())
        .rename("CLASS")
        .toInt()
    )


def get_pixel_value(img: ee.Image, layer: str, lat: float, lon: float, scale: int = 30) -> Optional[float]:
    try:
        point = ee.Geometry.Point([lon, lat])
        result = img.select(layer).reduceRegion(
            reducer=ee.Reducer.first(),
            geometry=point,
            scale=scale,
            maxPixels=1e13,
            bestEffort=True,
        ).getInfo()
        value = result.get(layer)
        return value if value is not None else None
    except Exception:
        return None


# =========================================================
# 8. CACHE
# =========================================================
@st.cache_data
def get_countries() -> List[str]:
    return (
        ee.FeatureCollection(CONFIG["admin_fc"])
        .aggregate_array("ADM0_NAME")
        .distinct()
        .sort()
        .getInfo()
    )


@st.cache_data
def get_provinces(country_name: str) -> List[str]:
    return (
        ee.FeatureCollection(CONFIG["admin_fc"])
        .filter(ee.Filter.eq("ADM0_NAME", country_name))
        .aggregate_array("ADM1_NAME")
        .distinct()
        .sort()
        .getInfo()
    )


@st.cache_data(show_spinner=False)
def search_best_images(country: str, provinces: Tuple[str, ...], year: str, month: str, layer: str) -> Dict[str, Optional[str]]:
    roi = get_roi(country, list(provinces))
    start_date = ee.Date.fromYMD(int(year), int(month), 1)
    cloud_prop = "CLOUD_COVER" if is_lst(layer) else "CLOUDY_PIXEL_PERCENTAGE"

    col = (
        ee.ImageCollection(get_collection_name(layer))
        .filterBounds(roi.geometry())
        .filterDate(start_date.advance(-15, "day"), start_date.advance(15, "day"))
        .sort(cloud_prop)
        .limit(10)
    )

    features = col.getInfo().get("features", [])
    options = {"Ghép quý liền mạch (Mặc định)": None}

    for f in features:
        image_id = f["id"]
        cloud_val = f["properties"].get(cloud_prop, 0)
        label = f"{image_id.split('/')[-1]} ({cloud_val:.1f}% mây)"
        options[label] = image_id

    if len(options) == 1:
        return {"Không có ảnh hợp lệ, dùng mặc định!": None}
    return options


# =========================================================
# 9. PHÂN TÍCH DỮ LIỆU
# =========================================================
def get_area_groups(classified_img: ee.Image, geom: ee.Geometry, scale: int) -> List[dict]:
    area_img = ee.Image.pixelArea().divide(10000).addBands(classified_img)
    result = area_img.reduceRegion(
        reducer=ee.Reducer.sum().group(groupField=1),
        geometry=geom,
        scale=scale * 2,
        maxPixels=1e13,
        tileScale=4,
        bestEffort=True,
    ).getInfo()
    return result.get("groups", [])


def extract_area(groups: List[dict], class_num: int) -> float:
    for g in groups or []:
        if int(g["group"]) == class_num:
            return g["sum"]
    return 0.0


def get_stats(img: ee.Image, layer: str, geom: ee.Geometry, scale: int) -> dict:
    return img.select(layer).reduceRegion(
        reducer=ee.Reducer.mean().combine(ee.Reducer.min(), sharedInputs=True).combine(ee.Reducer.max(), sharedInputs=True),
        geometry=geom,
        scale=scale * 2,
        maxPixels=1e13,
        tileScale=4,
        bestEffort=True,
    ).getInfo()


def get_histogram(img: ee.Image, layer: str, geom: ee.Geometry, scale: int) -> dict:
    return img.select(layer).reduceRegion(
        reducer=ee.Reducer.histogram(20),
        geometry=geom,
        scale=scale * 4,
        maxPixels=1e13,
        tileScale=4,
        bestEffort=True,
    ).getInfo().get(layer, {})


def analyze_region(params: AnalysisParams) -> dict:
    roi = get_roi(params.country, params.provinces)
    geom = roi.geometry()
    years = sorted(params.years_multi) if params.years_multi else [params.year_base]

    year_data = {}
    for year in years:
        specific_id = params.specific_id if year == params.year_base else None
        img = get_image(geom, year, params.month, params.layer, specific_id)
        cls = classify(img, params.layer).clip(geom)

        mean_val = img.select(params.layer).reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=geom,
            scale=CONFIG["scale"] * 4,
            maxPixels=1e13,
            tileScale=4,
            bestEffort=True,
        ).getInfo().get(params.layer)

        year_data[year] = {
            "image": img,
            "class": cls,
            "mean": mean_val,
        }

    first_y = years[0]
    last_y = years[-1]

    img_first = year_data[first_y]["image"]
    img_last = year_data[last_y]["image"]
    cls_first = year_data[first_y]["class"]
    cls_last = year_data[last_y]["class"]

    area_first = get_area_groups(cls_first, geom, CONFIG["scale"])
    area_last = get_area_groups(cls_last, geom, CONFIG["scale"])
    stats_last = get_stats(img_last, params.layer, geom, CONFIG["scale"])
    hist_last = get_histogram(img_last, params.layer, geom, CONFIG["scale"])

    trend_data = [
        {"Năm": y, "Trị số": year_data[y]["mean"]}
        for y in years
        if year_data[y]["mean"] is not None
    ]

    scatter_df = None
    if len(years) > 1:
        sample = (
            ee.Image.cat([
                img_first.select([params.layer], ["X"]),
                img_last.select([params.layer], ["Y"]),
            ])
            .sample(region=geom, scale=CONFIG["scale"] * 6, numPixels=500, dropNulls=True, tileScale=4)
            .getInfo()
        )
        feats = sample.get("features", [])
        if feats:
            scatter_df = pd.DataFrame([f["properties"] for f in feats])

    bar_data = []
    if len(params.provinces) > 1:
        for prov in params.provinces:
            p_geom = roi.filter(ee.Filter.eq("ADM1_NAME", prov)).geometry()
            p_mean = img_last.select(params.layer).reduceRegion(
                reducer=ee.Reducer.mean(),
                geometry=p_geom,
                scale=CONFIG["scale"] * 4,
                maxPixels=1e13,
                tileScale=4,
                bestEffort=True,
            ).getInfo().get(params.layer)

            if p_mean is not None:
                bar_data.append({"Khu vực": prov, "Trị số": p_mean})

    return {
        "roi": roi,
        "geom": geom,
        "years": years,
        "first_y": first_y,
        "last_y": last_y,
        "area_first": area_first,
        "area_last": area_last,
        "stats_last": stats_last,
        "hist_last": hist_last,
        "trend_data": trend_data,
        "scatter_df": scatter_df,
        "bar_data": bar_data,
        "year_data": year_data,
        "roi_names": ", ".join(params.provinces),
    }


# =========================================================
# 10. HỖ TRỢ BẢN ĐỒ
# =========================================================
def get_legend_info(layer: str):
    labels = CONFIG["class_labels"][layer]
    palette = CONFIG["vis"][layer]["palette"]
    thresholds = CONFIG["threshold_labels"][layer]
    legend_dict = {labels[i]: palette[i] for i in range(4)}
    return labels, palette, thresholds, legend_dict


def tao_ban_do_co_ban() -> folium.Map:
    ban_do = folium.Map(
        location=[16.0, 106.0],
        zoom_start=6,
        control_scale=True,
        zoom_control=True,
        tiles=None,
    )

    folium.TileLayer(
        tiles="OpenStreetMap",
        name="Bản đồ nền",
        overlay=False,
        control=True,
    ).add_to(ban_do)

    folium.TileLayer(
        tiles="Esri.WorldImagery",
        name="Ảnh vệ tinh",
        overlay=False,
        control=True,
        attr="Esri"
    ).add_to(ban_do)

    return ban_do


def them_ranh_gioi_hanh_chinh(ban_do: folium.Map, roi):
    ranh_gioi = geemap.ee_tile_layer(
        ee_object=ee.Image().paint(roi, 0, 3),
        vis_params={"palette": ["#ff0000"]},
        name="Ranh giới hành chính",
        shown=True,
        opacity=1.0,
    )
    ranh_gioi.add_to(ban_do)


def build_single_map(result: dict, layer: str, display_year: str) -> folium.Map:
    ban_do = tao_ban_do_co_ban()

    lop_phan_loai = geemap.ee_tile_layer(
        ee_object=result["year_data"][display_year]["class"],
        vis_params=CONFIG["vis"][layer],
        name=f"Phân loại {layer} ({display_year})",
        shown=True,
        opacity=1.0,
    )
    lop_phan_loai.add_to(ban_do)

    them_ranh_gioi_hanh_chinh(ban_do, result["roi"])

    try:
        tam = result["geom"].centroid(1).coordinates().getInfo()
        ban_do.location = [tam[1], tam[0]]
        ban_do.zoom_start = 8
    except Exception:
        pass

    folium.LayerControl(collapsed=False).add_to(ban_do)
    return ban_do


def build_swipe_map(result: dict, layer: str, left_year: str, right_year: str) -> folium.Map:
    ban_do = tao_ban_do_co_ban()

    lop_trai = geemap.ee_tile_layer(
        ee_object=result["year_data"][left_year]["class"],
        vis_params=CONFIG["vis"][layer],
        name=f"{layer} {left_year}",
        shown=True,
        opacity=1.0,
    )

    lop_phai = geemap.ee_tile_layer(
        ee_object=result["year_data"][right_year]["class"],
        vis_params=CONFIG["vis"][layer],
        name=f"{layer} {right_year}",
        shown=True,
        opacity=1.0,
    )

    lop_trai.add_to(ban_do)
    lop_phai.add_to(ban_do)

    SideBySideLayers(lop_trai, lop_phai).add_to(ban_do)

    them_ranh_gioi_hanh_chinh(ban_do, result["roi"])

    try:
        tam = result["geom"].centroid(1).coordinates().getInfo()
        ban_do.location = [tam[1], tam[0]]
        ban_do.zoom_start = 8
    except Exception:
        pass

    folium.LayerControl(collapsed=False).add_to(ban_do)
    return ban_do


def format_pixel_value(layer: str, value: Optional[float]) -> str:
    if value is None:
        return "Không có dữ liệu"
    if layer == "LST":
        return f"{value:.2f} °C"
    return f"{value:.4f}"


def build_export_html(map_obj) -> str:
    return map_obj.get_root().render()


# =========================================================
# 11. HỖ TRỢ BÁO CÁO
# =========================================================
def build_report_html(params: AnalysisParams, result: dict) -> str:
    first_y = result["first_y"]
    last_y = result["last_y"]
    stats_last = result["stats_last"]

    l_mean = stats_last.get(f"{params.layer}_mean", 0) or 0
    l_min = stats_last.get(f"{params.layer}_min", 0) or 0
    l_max = stats_last.get(f"{params.layer}_max", 0) or 0

    index_name = (
        "Mật độ Thực vật (NDVI)" if params.layer == "NDVI"
        else "Độ phủ Đô thị (NDBI)" if params.layer == "NDBI"
        else "Nhiệt độ Bề mặt (LST)"
    )

    layer_name = (
        "Thảm thực vật" if params.layer == "NDVI"
        else "Đất xây dựng đô thị" if params.layer == "NDBI"
        else "Vùng nhiệt độ cao"
    )

    html = f"<div class='report-card'><strong style='color:#1a5276; font-size:15px'>📍 KHU VỰC: {result['roi_names']}</strong><br><br>"

    if first_y == last_y:
        html += f"<strong style='color:#8e44ad;'>1. TÓM TẮT HIỆN TRẠNG ({last_y})</strong><br><br>"
        if l_mean == 0:
            html += "<span style='color:red'>⚠️ Dữ liệu lỗi hoặc mây che phủ 100%.</span>"
        else:
            mean_text = f"{l_mean:.2f} °C" if params.layer == "LST" else f"{l_mean:.3f}"
            range_text = f"{l_min:.1f}°C đến {l_max:.1f}°C" if params.layer == "LST" else f"{l_min:.3f} đến {l_max:.3f}"
            html += (
                f"Chỉ số <b>{index_name}</b> toàn khu vực đạt mức trung bình: "
                f"<b style='color:#c0392b; font-size:16px;'>{mean_text}</b>.<br>"
                f"Phân hóa không gian biến thiên trong khoảng từ {range_text}."
            )
    else:
        a_first_high = extract_area(result["area_first"], 3) + extract_area(result["area_first"], 4)
        a_last_high = extract_area(result["area_last"], 3) + extract_area(result["area_last"], 4)
        diff_ha = a_last_high - a_first_high

        html += f"<strong style='color:#8e44ad;'>1. PHÂN TÍCH BIẾN ĐỘNG ({first_y} ➔ {last_y})</strong><br><br>"

        if a_first_high == 0 and a_last_high == 0:
            html += "<span style='color:#e67e22'>⚠️ Mây che phủ diện rộng, không thể nội suy diện tích.</span>"
        else:
            pct = (abs(diff_ha) / a_first_high * 100) if a_first_high > 0 else 0
            act = "Mở rộng" if diff_ha > 0 else "Thu hẹp"
            speed = "nhanh chóng" if pct > 10 else "chậm"

            color = "#c0392b" if diff_ha > 0 else "#27ae60"
            if params.layer == "NDVI":
                color = "#27ae60" if diff_ha > 0 else "#c0392b"

            html += f"Quỹ diện tích <b>{layer_name}</b> ghi nhận sự thay đổi:<br>"
            html += f"• Năm {first_y}: {a_first_high:,.0f} ha<br>"
            html += f"• Năm {last_y}: {a_last_high:,.0f} ha<br><br>"
            html += (
                f"<span style='color:{color}; font-weight:bold'>"
                f"📌 KẾT LUẬN: Khu vực đang có xu hướng {act} {speed} quỹ diện tích {layer_name}. "
                f"Tổng mức biến động {abs(diff_ha):,.0f} ha ({pct:.1f}%)."
                f"</span>"
            )

    html += "</div>"
    return html


def build_auto_insight(params: AnalysisParams, result: dict) -> str:
    if result["first_y"] == result["last_y"]:
        return f"📌 Hiện đang xem {params.layer} của năm {result['last_y']}."
    a_first = extract_area(result["area_first"], 3) + extract_area(result["area_first"], 4)
    a_last = extract_area(result["area_last"], 3) + extract_area(result["area_last"], 4)
    diff = a_last - a_first
    pct = (abs(diff) / a_first * 100) if a_first > 0 else 0

    if params.layer == "NDVI":
        return (
            f"🌿 Thảm thực vật đang {'tăng' if diff > 0 else 'giảm'} {abs(diff):,.0f} ha "
            f"({pct:.1f}%) giữa {result['first_y']} và {result['last_y']}."
        )
    if params.layer == "NDBI":
        return (
            f"🏗️ Đất xây dựng đang {'mở rộng' if diff > 0 else 'thu hẹp'} {abs(diff):,.0f} ha "
            f"({pct:.1f}%) giữa {result['first_y']} và {result['last_y']}."
        )
    return (
        f"🔥 Vùng nhiệt độ cao đang {'mở rộng' if diff > 0 else 'thu hẹp'} {abs(diff):,.0f} ha "
        f"({pct:.1f}%) giữa {result['first_y']} và {result['last_y']}."
    )


# =========================================================
# 12. GIAO DIỆN CHÍNH
# =========================================================
col_control, col_map, col_report = st.columns([1.2, 2.8, 1.45], gap="small")

with col_control:
    with st.container(height=900, border=False):
        st.markdown("<h3 style='color:#1a5276;'>🌍 DASHBOARD PRO MAX ULTRA</h3>", unsafe_allow_html=True)

        with st.container(border=True):
            st.markdown("<div class='box-title'>1. CHỌN KHU VỰC NGHIÊN CỨU</div>", unsafe_allow_html=True)

            countries = get_countries()
            country = st.selectbox(
                "Quốc gia",
                countries,
                index=countries.index("Viet Nam") if "Viet Nam" in countries else 0
            )

            provinces = get_provinces(country)
            selected_provinces = st.multiselect(
                "Tỉnh / Tiểu bang",
                provinces,
                placeholder="Chọn khu vực..."
            )

        with st.container(border=True):
            st.markdown("<div class='box-title'>2. THÔNG SỐ ẢNH</div>", unsafe_allow_html=True)

            layer = st.selectbox("Chỉ số", ["NDVI", "NDBI", "LST"])
            c1, c2 = st.columns(2)
            year_base = c1.selectbox("Năm gốc", CONFIG["years"], index=CONFIG["years"].index("2023"))
            month = c2.selectbox("Tháng bắt đầu", CONFIG["months"], index=2)

            if st.button("🔎 Tải ảnh ít mây", use_container_width=True):
                if not selected_provinces:
                    st.warning("Vui lòng chọn khu vực trước.")
                else:
                    with st.spinner("Đang quét ảnh..."):
                        st.session_state["image_options"] = search_best_images(
                            country, tuple(selected_provinces), year_base, month, layer
                        )
                        st.success("Đã cập nhật danh sách ảnh.")

            selected_img_label = st.selectbox(
                "Nguồn dữ liệu",
                list(st.session_state["image_options"].keys())
            )
            specific_img_id = st.session_state["image_options"][selected_img_label]

        with st.container(border=True):
            st.markdown("<div class='box-title'>3. ĐA THỜI GIAN</div>", unsafe_allow_html=True)
            years_multi = st.multiselect(
                "Chọn năm so sánh",
                CONFIG["years"],
                default=["2023", "2024"]
            )

        run_btn = st.button("🚀 PHÂN TÍCH HỆ THỐNG", use_container_width=True, type="primary")

        if run_btn:
            if not selected_provinces:
                st.warning("⚠️ Hãy chọn ít nhất 1 tỉnh/bang.")
            else:
                params = AnalysisParams(
                    country=country,
                    provinces=selected_provinces,
                    layer=layer,
                    year_base=year_base,
                    month=month,
                    years_multi=years_multi,
                    specific_id=specific_img_id,
                )

                with st.spinner("Đang phân tích dữ liệu GEE..."):
                    try:
                        result = analyze_region(params)
                        st.session_state["params"] = params
                        st.session_state["result"] = result
                        st.session_state["analyzed"] = True
                        st.session_state["display_year"] = result["last_y"]
                        st.session_state["timeline_index"] = result["years"].index(result["last_y"])
                        st.session_state["compare_left_year"] = result["years"][0]
                        st.session_state["compare_right_year"] = result["years"][-1]
                        st.session_state["play_animation"] = False
                    except Exception as e:
                        st.session_state["analyzed"] = False
                        st.error(f"Lỗi phân tích: {e}")

        if st.session_state["analyzed"] and st.session_state["result"] is not None:
            result_years = st.session_state["result"]["years"]

            st.markdown("<div class='box-title'>4. CHẾ ĐỘ BẢN ĐỒ</div>", unsafe_allow_html=True)

            st.session_state["map_mode"] = st.radio(
                "Chế độ hiển thị",
                ["🎬 Xem từng năm", "🪞 So sánh kéo trái/phải"],
                index=0 if st.session_state["map_mode"] == "🎬 Xem từng năm" else 1,
                horizontal=False,
            )

            if st.session_state["map_mode"] == "🎬 Xem từng năm":
                st.markdown("<div class='box-title'>5. TIMELINE THEO NĂM</div>", unsafe_allow_html=True)

                current_index = st.session_state["timeline_index"]

                c_prev, c_next = st.columns(2)
                if c_prev.button("⏮️ Năm trước", use_container_width=True):
                    st.session_state["timeline_index"] = max(0, current_index - 1)
                    st.session_state["play_animation"] = False

                if c_next.button("⏭️ Năm sau", use_container_width=True):
                    st.session_state["timeline_index"] = min(len(result_years) - 1, current_index + 1)
                    st.session_state["play_animation"] = False

                st.session_state["timeline_index"] = st.slider(
                    "Timeline",
                    min_value=0,
                    max_value=len(result_years) - 1,
                    value=st.session_state["timeline_index"],
                    step=1,
                )

                st.session_state["display_year"] = result_years[st.session_state["timeline_index"]]
                st.caption(f"🎞️ Khung hiện tại: {st.session_state['display_year']}")

                c_play1, c_play2 = st.columns(2)
                if c_play1.button("▶️ Play", use_container_width=True):
                    st.session_state["play_animation"] = True
                if c_play2.button("⏹️ Stop", use_container_width=True):
                    st.session_state["play_animation"] = False

                st.session_state["play_speed"] = st.select_slider(
                    "Tốc độ",
                    options=[0.5, 1.0, 1.5, 2.0],
                    value=st.session_state["play_speed"],
                )

            else:
                st.markdown("<div class='box-title'>5. SO SÁNH 2 NĂM BẰNG THANH KÉO</div>", unsafe_allow_html=True)

                if st.session_state["compare_left_year"] not in result_years:
                    st.session_state["compare_left_year"] = result_years[0]
                if st.session_state["compare_right_year"] not in result_years:
                    st.session_state["compare_right_year"] = result_years[-1]

                st.session_state["compare_left_year"] = st.selectbox(
                    "Năm bên trái",
                    result_years,
                    index=result_years.index(st.session_state["compare_left_year"]),
                    key="left_year_select"
                )

                st.session_state["compare_right_year"] = st.selectbox(
                    "Năm bên phải",
                    result_years,
                    index=result_years.index(st.session_state["compare_right_year"]),
                    key="right_year_select"
                )

                if st.button("🔁 Đảo trái / phải", use_container_width=True):
                    left = st.session_state["compare_left_year"]
                    right = st.session_state["compare_right_year"]
                    st.session_state["compare_left_year"] = right
                    st.session_state["compare_right_year"] = left

                st.caption(
                    f"🪞 Đang so sánh {layer}: kéo thanh qua lại giữa năm "
                    f"{st.session_state['compare_left_year']} và {st.session_state['compare_right_year']}"
                )


# =========================================================
# 13. HIỂN THỊ BẢN ĐỒ
# =========================================================
current_map_obj = None

with col_map:
    if st.session_state["analyzed"] and st.session_state["result"] is not None:
        result = st.session_state["result"]
        params = st.session_state["params"]

        if st.session_state["map_mode"] == "🎬 Xem từng năm":
            current_map_obj = build_single_map(
                result=result,
                layer=params.layer,
                display_year=st.session_state["display_year"],
            )

            st.markdown(
                f"""
                <div class="map-banner-cinema">
                    🎬 CHẾ ĐỘ XEM TỪNG NĂM — {params.layer} / NĂM {st.session_state["display_year"]}
                </div>
                """,
                unsafe_allow_html=True
            )

            st.info(build_auto_insight(params, result))

        else:
            current_map_obj = build_swipe_map(
                result=result,
                layer=params.layer,
                left_year=st.session_state["compare_left_year"],
                right_year=st.session_state["compare_right_year"],
            )

            st.markdown(
                f"""
                <div class="map-banner-swipe">
                    🪞 CHẾ ĐỘ SO SÁNH KÉO TRÁI/PHẢI — {params.layer} / {st.session_state["compare_left_year"]} ↔ {st.session_state["compare_right_year"]}
                </div>
                """,
                unsafe_allow_html=True
            )

            st.warning(
                f"Đang hiển thị 2 lớp bản đồ {params.layer}: "
                f"bên trái là năm {st.session_state['compare_left_year']}, "
                f"bên phải là năm {st.session_state['compare_right_year']}."
            )

        map_state = st_folium(
            current_map_obj,
            width=None,
            height=900,
            returned_objects=["last_clicked", "bounds", "zoom"],
            key=f"main_map_{st.session_state['map_mode']}_{st.session_state.get('display_year')}_{st.session_state.get('compare_left_year')}_{st.session_state.get('compare_right_year')}"
        )

        if map_state and map_state.get("bounds"):
            st.session_state["last_map_bounds"] = map_state["bounds"]

        if map_state and map_state.get("zoom") is not None:
            st.session_state["last_map_zoom"] = map_state["zoom"]

        if map_state and map_state.get("last_clicked"):
            lat = map_state["last_clicked"]["lat"]
            lon = map_state["last_clicked"]["lng"]

            if st.session_state["map_mode"] == "🎬 Xem từng năm":
                img_for_click = result["year_data"][st.session_state["display_year"]]["image"]
            else:
                img_for_click = result["year_data"][st.session_state["compare_right_year"]]["image"]

            pixel_val = get_pixel_value(
                img=img_for_click,
                layer=params.layer,
                lat=lat,
                lon=lon,
                scale=30 if params.layer == "LST" else 10,
            )

            st.session_state["map_click_value"] = {
                "lat": lat,
                "lon": lon,
                "value": pixel_val,
            }

        if st.session_state["map_click_value"] is not None:
            c_a, c_b, c_c = st.columns(3)
            c_a.markdown(
                f"<div class='kpi-card'><div class='kpi-title'>Vĩ độ</div><div class='kpi-value'>{st.session_state['map_click_value']['lat']:.5f}</div></div>",
                unsafe_allow_html=True
            )
            c_b.markdown(
                f"<div class='kpi-card'><div class='kpi-title'>Kinh độ</div><div class='kpi-value'>{st.session_state['map_click_value']['lon']:.5f}</div></div>",
                unsafe_allow_html=True
            )
            c_c.markdown(
                f"<div class='kpi-card'><div class='kpi-title'>{params.layer}</div><div class='kpi-value'>{format_pixel_value(params.layer, st.session_state['map_click_value']['value'])}</div></div>",
                unsafe_allow_html=True
            )

        meta_cols = st.columns(2)
        if st.session_state["last_map_zoom"] is not None:
            meta_cols[0].caption(f"🔎 Mức zoom hiện tại: {st.session_state['last_map_zoom']}")
        if st.session_state["last_map_bounds"] is not None:
            meta_cols[1].caption("🧭 Đã ghi nhận khung nhìn hiện tại")

        if current_map_obj is not None:
            html_string = build_export_html(current_map_obj)
            export_name = (
                f"ban_do_{params.layer}_{st.session_state['display_year']}.html"
                if st.session_state["map_mode"] == "🎬 Xem từng năm"
                else f"ban_do_so_sanh_{params.layer}_{st.session_state['compare_left_year']}_{st.session_state['compare_right_year']}.html"
            )
            st.download_button(
                label="📥 Xuất bản đồ HTML",
                data=html_string,
                file_name=export_name,
                mime="text/html",
                use_container_width=True,
            )
    else:
        empty_map = folium.Map(location=[16.0, 106.0], zoom_start=6, control_scale=True)
        st_folium(empty_map, width=None, height=900, key="empty_map")


# =========================================================
# 14. HIỂN THỊ BÁO CÁO
# =========================================================
with col_report:
    with st.container(height=900, border=False):
        st.markdown("<div class='danger-title'>📰 BẢN TIN ĐÁNH GIÁ CHUYÊN SÂU</div>", unsafe_allow_html=True)

        if st.session_state["analyzed"] and st.session_state["result"] is not None:
            params = st.session_state["params"]
            result = st.session_state["result"]
            stats_last = result["stats_last"]

            st.markdown(build_report_html(params, result), unsafe_allow_html=True)

            mean_val = stats_last.get(f"{params.layer}_mean", 0) or 0
            min_val = stats_last.get(f"{params.layer}_min", 0) or 0
            max_val = stats_last.get(f"{params.layer}_max", 0) or 0

            k1, k2, k3 = st.columns(3)
            k1.markdown(
                f"<div class='kpi-card'><div class='kpi-title'>Mean</div><div class='kpi-value'>{format_pixel_value(params.layer, mean_val)}</div></div>",
                unsafe_allow_html=True
            )
            k2.markdown(
                f"<div class='kpi-card'><div class='kpi-title'>Min</div><div class='kpi-value'>{format_pixel_value(params.layer, min_val)}</div></div>",
                unsafe_allow_html=True
            )
            k3.markdown(
                f"<div class='kpi-card'><div class='kpi-title'>Max</div><div class='kpi-value'>{format_pixel_value(params.layer, max_val)}</div></div>",
                unsafe_allow_html=True
            )

            st.markdown("<div class='danger-title' style='font-size: 15px;'>📊 HỆ THỐNG BIỂU ĐỒ</div>", unsafe_allow_html=True)

            st.markdown("<div class='chart-box'><b>1. Xu hướng thời gian</b>", unsafe_allow_html=True)
            if result["trend_data"]:
                fig1 = px.line(pd.DataFrame(result["trend_data"]), x="Năm", y="Trị số", markers=True)
                fig1.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=220, xaxis_type="category")
                st.plotly_chart(fig1, use_container_width=True)
            else:
                st.warning("Không đủ dữ liệu.")
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown(f"<div class='chart-box'><b>2. Tần suất phân bổ ({result['last_y']})</b>", unsafe_allow_html=True)
            hist = result["hist_last"]
            if hist and "histogram" in hist and len(hist["histogram"]) > 0:
                counts = hist["histogram"]
                buckets = [hist["bucketMin"] + i * hist["bucketWidth"] for i in range(len(counts))]
                fig2 = px.bar(x=buckets, y=counts)
                fig2.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=220)
                st.plotly_chart(fig2, use_container_width=True)
            else:
                st.warning("Không thể tính histogram.")
            st.markdown("</div>", unsafe_allow_html=True)

            st.markdown(f"<div class='chart-box'><b>3. Cơ cấu phân loại ({result['last_y']})</b>", unsafe_allow_html=True)
            pie_data = []
            pie_colors = []

            for i in range(4):
                val = extract_area(result["area_last"], i + 1)
                if val > 0:
                    pie_data.append({
                        "Lớp": CONFIG["class_labels"][params.layer][i],
                        "Diện tích": val
                    })
                    pie_colors.append(CONFIG["vis"][params.layer]["palette"][i])

            if pie_data:
                fig3 = px.pie(
                    pd.DataFrame(pie_data),
                    names="Lớp",
                    values="Diện tích",
                    hole=0.4,
                    color="Lớp",
                    color_discrete_sequence=pie_colors
                )
                fig3.update_traces(textposition="inside", textinfo="percent")
                fig3.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=260)
                st.plotly_chart(fig3, use_container_width=True)
            else:
                st.warning("Dữ liệu phân loại rỗng.")
            st.markdown("</div>", unsafe_allow_html=True)

            if len(result["years"]) > 1:
                st.markdown(f"<div class='chart-box'><b>4. Tương quan không gian ({result['first_y']} vs {result['last_y']})</b>", unsafe_allow_html=True)
                if result["scatter_df"] is not None and not result["scatter_df"].empty:
                    fig4 = px.scatter(result["scatter_df"], x="X", y="Y", opacity=0.6, trendline="ols")
                    fig4.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=220)
                    st.plotly_chart(fig4, use_container_width=True)
                else:
                    st.warning("Không đủ dữ liệu tương quan.")
                st.markdown("</div>", unsafe_allow_html=True)

            if len(params.provinces) > 1:
                st.markdown("<div class='chart-box'><b>5. So sánh trung bình các khu vực</b>", unsafe_allow_html=True)
                if result["bar_data"]:
                    fig5 = px.bar(pd.DataFrame(result["bar_data"]), x="Khu vực", y="Trị số", text_auto=".3f")
                    fig5.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=260)
                    st.plotly_chart(fig5, use_container_width=True)
                else:
                    st.warning("Không có dữ liệu khu vực.")
                st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("👈 Chọn khu vực và bấm PHÂN TÍCH HỆ THỐNG.")


# =========================================================
# 15. VÒNG LẶP ANIMATION
# =========================================================
if (
    st.session_state["analyzed"]
    and st.session_state["result"] is not None
    and st.session_state["map_mode"] == "🎬 Xem từng năm"
    and st.session_state["play_animation"]
):
    years = st.session_state["result"]["years"]
    current_index = st.session_state["timeline_index"]

    time.sleep(max(0.15, 1.2 - (st.session_state["play_speed"] * 0.4)))

    if current_index < len(years) - 1:
        st.session_state["timeline_index"] = current_index + 1
    else:
        st.session_state["timeline_index"] = 0

    st.session_state["display_year"] = years[st.session_state["timeline_index"]]
    st.rerun()