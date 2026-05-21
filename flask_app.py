import os
import sys
from datetime import datetime
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import google.generativeai as genai
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

app = Flask(__name__)
CORS(app)  # Allow CORS for all routes (important for cross-origin frontend communication)

# Load GEMINI API Key from Environment, fallback to working key
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "AIzaSyAkfuP2SmCG42jF6fzyiZPLuToy96xujNk")
OPENMETEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

def get_weather_description(weathercode: int) -> str:
    """Converts Open-Meteo weather code to a friendly Vietnamese description."""
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

@app.route('/')
@app.route('/chatbot')
def serve_chatbot():
    """Serves the standalone chatbot HTML page."""
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'weather_chat_demo.html')

@app.route('/api/health', methods=['GET'])
def health():
    """API Health Check Endpoint."""
    return jsonify({
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "service": "AI Weather Chatbot"
    })

@app.route('/api/weather_chat', methods=['POST'])
def weather_chat():
    """Main Chatbot Endpoint: queries weather and passes payload to Gemini AI."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "Payload JSON không hợp lệ hoặc rỗng."}), 400

        # Input Validation
        lat = data.get("lat")
        lon = data.get("lon")
        user_message = data.get("message")

        if lat is None or lon is None or not user_message:
            return jsonify({"status": "error", "message": "Thiếu các trường bắt buộc (lat, lon, message)."}), 400

        try:
            lat = float(lat)
            lon = float(lon)
        except ValueError:
            return jsonify({"status": "error", "message": "Tọa độ lat, lon phải là số thực."}), 400

        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return jsonify({"status": "error", "message": "Tọa độ lat hoặc lon nằm ngoài phạm vi địa lý."}), 400

        if not str(user_message).strip():
            return jsonify({"status": "error", "message": "Tin nhắn người dùng không được để trống."}), 400

        # Step 1: Fetch Weather Data from Open-Meteo
        print(f"📡 DEBUG: Gọi Open-Meteo API với tọa độ ({lat}, {lon})")
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
            "timezone": "auto"
        }
        
        response = requests.get(OPENMETEO_BASE_URL, params=params, timeout=15)
        response.raise_for_status()
        weather_raw = response.json()
        
        current = weather_raw.get("current", {})
        daily = weather_raw.get("daily", {})

        print("✅ DEBUG: Thành công lấy dữ liệu thời tiết")

        temp = current.get('temperature_2m', 'N/A')
        humidity = current.get('relative_humidity_2m', 'N/A')
        windspeed = current.get('wind_speed_10m', 'N/A')
        weathercode = current.get('weather_code', 0)
        
        temp_max = daily.get('temperature_2m_max', ['N/A'])[0] if daily.get('temperature_2m_max') else 'N/A'
        temp_min = daily.get('temperature_2m_min', ['N/A'])[0] if daily.get('temperature_2m_min') else 'N/A'
        rain_prob = daily.get('precipitation_probability_max', ['N/A'])[0] if daily.get('precipitation_probability_max') else 'N/A'
        weathercode_today = daily.get('weather_code', [0])[0] if daily.get('weather_code') else 0

        # Step 2: Build System Prompt for Gemini AI
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
        print(f"🤖 DEBUG: Prompt: [{len(system_prompt)} ký tự]")

        # Step 3: Invoke Gemini AI (with retries for robust handling of 429/503)
        import time
        genai_client = genai.Client(api_key=GEMINI_API_KEY)
        
        ai_text = None
        max_retries = 3
        retry_delay = 3
        
        for attempt in range(max_retries):
            try:
                ai_response = genai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=system_prompt
                )
                ai_text = ai_response.text
                break
            except Exception as ge:
                ge_str = str(ge).upper()
                if ("429" in ge_str or "503" in ge_str or "RESOURCE_EXHAUSTED" in ge_str or "UNAVAILABLE" in ge_str) and attempt < max_retries - 1:
                    print(f"⚠️ Warning: Gemini API returned temporary error ({ge}). Retrying in {retry_delay}s... (Attempt {attempt + 1}/{max_retries})")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise ge
        
        if ai_text is None:
            raise Exception("Không nhận được phản hồi từ Gemini AI sau các lượt thử.")
            
        print(f"✅ DEBUG: Gemini response received: {ai_text[:50].strip()}...")

        # Step 4: Return JSON response formatted for Frontend and Test Suite
        return jsonify({
            "status": "success",
            "ai_response": ai_text,
            "weather_data": {
                "current": {
                    "temperature": temp,
                    "humidity": humidity,
                    "windspeed": windspeed,
                    "weathercode": weathercode
                },
                "daily_forecast": [
                    {
                        "date": "Hôm nay",
                        "max_t": temp_max,
                        "min_t": temp_min,
                        "rain_prob": rain_prob,
                        "code": weathercode_today
                    }
                ]
            }
        })

    except requests.exceptions.RequestException as re:
        print(f"❌ DEBUG: Open-Meteo API Error: {re}")
        return jsonify({
            "status": "error",
            "message": f"Không thể kết nối hoặc truy vấn dữ liệu từ Open-Meteo API: {str(re)}"
        }), 502
    except Exception as e:
        print(f"❌ DEBUG: System Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Lỗi hệ thống trong backend: {str(e)}"
        }), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
