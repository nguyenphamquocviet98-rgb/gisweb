"""
Test script để kiểm tra Open-Meteo API
Chạy: python test_openmeteo.py
"""

import requests
import json

OPENMETEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Tọa độ Hà Nội
latitude = 21.0285
longitude = 105.8542

print("=" * 70)
print("🧪 TEST OPEN-METEO API")
print("=" * 70)
print(f"\n📍 Tọa độ: {latitude}, {longitude} (Hà Nội)")

# Tham số API Open-Meteo v1
params = {
    "latitude": latitude,
    "longitude": longitude,
    "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
    "timezone": "auto"
}

print(f"\n📤 Gửi request tới: {OPENMETEO_BASE_URL}")
print(f"📤 Params: {json.dumps(params, indent=2)}")

try:
    response = requests.get(OPENMETEO_BASE_URL, params=params, timeout=10)
    print(f"\n✅ Response Status: {response.status_code}")
    
    if response.status_code == 200:
        data = response.json()
        
        print(f"\n📥 Response Keys: {list(data.keys())}")
        print(f"\n📊 CURRENT DATA:")
        if 'current' in data:
            print(json.dumps(data['current'], indent=2))
        else:
            print("⚠️ 'current' key not found!")
            
        print(f"\n📈 DAILY DATA (Sample):")
        if 'daily' in data:
            daily = data['daily']
            print(f"  - Available keys: {list(daily.keys())}")
            print(f"  - Number of days: {len(daily.get('time', []))}")
            if 'time' in daily:
                print(f"  - First day: {daily['time'][0]}")
                print(f"  - First day temp_max: {daily['temperature_2m_max'][0]}")
        else:
            print("⚠️ 'daily' key not found!")
            
    else:
        print(f"❌ Lỗi: {response.status_code}")
        print(f"📝 Response: {response.text}")
        
except Exception as e:
    print(f"\n❌ Lỗi: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 70)
