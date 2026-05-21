"""
Test script để kiểm tra toàn bộ flow: Open-Meteo → Gemini AI
Chạy: python test_full_flow.py
"""

import os
import requests
import json
import sys
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

OPENMETEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyAkfuP2SmCG42jF6fzyiZPLuToy96xujNk")

def get_weather_description(weathercode: int) -> str:
    """Chuyển đổi weather code thành mô tả tiếng Việt"""
    weather_descriptions = {
        0: "Trời nắng",
        1: "Trời hầu như quang đãng",
        2: "Trời mây từng phần",
        3: "Trời nhiều mây",
        45: "Sương mù",
        48: "Sương mù lạnh",
        51: "Mưa nhỏ",
        53: "Mưa vừa",
        55: "Mưa to",
        61: "Mưa nhỏ",
        63: "Mưa vừa",
        65: "Mưa to",
        71: "Tuyết nhỏ",
        73: "Tuyết vừa",
        75: "Tuyết to",
        77: "Hạt tuyết",
        80: "Mưa nhỏ",
        81: "Mưa vừa",
        82: "Mưa to",
        85: "Tuyết nhỏ",
        86: "Tuyết to",
        95: "Giông bão",
        96: "Giông bão kèm mưa đá nhỏ",
        99: "Giông bão kèm mưa đá to"
    }
    return weather_descriptions.get(weathercode, "Không rõ")

# Test tọa độ Hà Nội
latitude = 21.0285
longitude = 105.8542
user_message = "Hôm nay thời tiết thế nào?"

print("=" * 70)
print("🧪 TEST FULL FLOW: Open-Meteo → Gemini AI")
print("=" * 70)
print(f"\n📍 Tọa độ: {latitude}, {longitude}")
print(f"💬 Câu hỏi: {user_message}")

try:
    # Bước 1: Lấy dữ liệu thời tiết
    print("\n" + "=" * 70)
    print("BƯỚC 1: Gọi Open-Meteo API")
    print("=" * 70)
    
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        "timezone": "auto"
    }
    
    response = requests.get(OPENMETEO_BASE_URL, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    current = data.get("current", {})
    daily = data.get("daily", {})
    
    print(f"✅ Thành công lấy dữ liệu thời tiết")
    print(f"📊 Current: {current}")
    print(f"📈 Daily (first day): {dict(list(daily.items())[0:5])}")
    
    # Bước 2: Xây dựng prompt
    print("\n" + "=" * 70)
    print("BƯỚC 2: Xây dựng Prompt cho Gemini AI")
    print("=" * 70)
    
    temp = current.get('temperature_2m', 'N/A')
    humidity = current.get('relative_humidity_2m', 'N/A')
    windspeed = current.get('wind_speed_10m', 'N/A')
    weathercode = current.get('weather_code', 0)
    
    temp_max = daily['temperature_2m_max'][0] if daily.get('temperature_2m_max') else 'N/A'
    temp_min = daily['temperature_2m_min'][0] if daily.get('temperature_2m_min') else 'N/A'
    rain_prob = daily['precipitation_probability_max'][0] if daily.get('precipitation_probability_max') else 'N/A'
    
    system_prompt = f"""Bạn là một chuyên gia dự báo thời tiết thông minh.
Hãy trả lời câu hỏi của người dùng dựa CHÍNH XÁC trên các dữ liệu thời tiết sau:

📊 THỜI TIẾT HIỆN TẠI:
- Nhiệt độ: {temp}°C
- Độ ẩm: {humidity}%
- Sức gió: {windspeed} km/h
- Tình trạng: {get_weather_description(weathercode)}

📈 DỰ BÁO NGÀY HÔM NAY:
- Nhiệt độ cao nhất: {temp_max}°C
- Nhiệt độ thấp nhất: {temp_min}°C
- Xác suất mưa: {rain_prob}%

HƯỚNG DẪN TRẢ LỜI:
1. Trả lời ngắn gọn (2-3 câu), tự nhiên, không để người dùng chờ lâu.
2. Dùng tiếng Việt, tránh các ký tự lạ.
3. Luôn trích dẫn con số cụ thể từ dữ liệu trên (không bịa).
4. Nếu câu hỏi không liên quan đến thời tiết, hãy lịch sự từ chối.
5. Thêm emoji phù hợp để câu trả lời sinh động hơn.

Câu hỏi từ người dùng: {user_message}
"""
    
    print(f"📝 Prompt đã xây dựng ({len(system_prompt)} ký tự)")
    print(f"\n{system_prompt}")
    
    # Bước 3: Gọi Gemini AI
    print("\n" + "=" * 70)
    print("BƯỚC 3: Gọi Gemini AI")
    print("=" * 70)
    
    genai_client = genai.Client(api_key=GEMINI_API_KEY)
    
    print("⏳ Chờ Gemini AI phản hồi...")
    ai_response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=system_prompt
    )
    
    print(f"\n✅ Nhận phản hồi từ Gemini AI")
    print(f"🤖 Phản hồi:\n{ai_response.text}")
    
except Exception as e:
    print(f"\n❌ Lỗi: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
