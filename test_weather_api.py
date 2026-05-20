"""
==========================================
TEST SCRIPT - AI WEATHER CHATBOT
==========================================
Dùng để test Backend mà không cần Frontend HTML
Chạy: python test_weather_api.py
"""

import requests
import json
import time
import sys
from datetime import datetime

# Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

# Cấu hình
API_BASE_URL = "http://localhost:5000"
API_ENDPOINT = "/api/weather_chat"

# Danh sách test cases
TEST_CASES = [
    {
        "name": "Test 1: Hỏi về thời tiết hiện tại (Hà Nội)",
        "lat": 21.0285,
        "lon": 105.8542,
        "message": "Hôm nay trời thế nào?"
    },
    {
        "name": "Test 2: Hỏi về nhiệt độ (Sài Gòn)",
        "lat": 10.7769,
        "lon": 106.6972,
        "message": "Nhiệt độ hiện tại bao nhiêu độ?"
    },
    {
        "name": "Test 3: Hỏi về xác suất mưa (Đà Nẵng)",
        "lat": 16.0670,
        "lon": 108.2272,
        "message": "Hôm nay có mưa không?"
    },
    {
        "name": "Test 4: Hỏi về sức gió (Cần Thơ)",
        "lat": 10.0282,
        "lon": 105.7865,
        "message": "Gió mạnh không bạn?"
    },
    {
        "name": "Test 5: Câu hỏi không liên quan (Hà Nội)",
        "lat": 21.0285,
        "lon": 105.8542,
        "message": "Hôm nay là ngày bao nhiêu?"
    }
]


def print_header(text):
    """In header với formatting"""
    print("\n" + "="*70)
    print(f"  {text}")
    print("="*70)


def print_success(text):
    """In text màu xanh"""
    print(f"✅ {text}")


def print_error(text):
    """In text màu đỏ"""
    print(f"❌ {text}")


def print_warning(text):
    """In text màu vàng"""
    print(f"⚠️  {text}")


def print_info(text):
    """In text màu xanh dương"""
    print(f"ℹ️  {text}")


def check_api_health():
    """Kiểm tra trạng thái API"""
    print_header("KIỂM TRA API HEALTH")
    
    try:
        print_info(f"Gọi: GET {API_BASE_URL}/api/health")
        response = requests.get(
            f"{API_BASE_URL}/api/health",
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            print_success("API đang hoạt động bình thường")
            print(f"  Status: {data.get('status')}")
            print(f"  Service: {data.get('service')}")
            print(f"  Timestamp: {data.get('timestamp')}")
            return True
        else:
            print_error(f"API trả về status {response.status_code}")
            return False
            
    except requests.exceptions.ConnectionError:
        print_error("❌ Không thể kết nối tới Backend")
        print_warning("Kiểm tra xem Flask server đã chạy chưa?")
        print_info("Chạy lệnh: python app.py")
        return False
    except Exception as e:
        print_error(f"Lỗi: {e}")
        return False


def test_weather_chat(test_case):
    """Test một test case"""
    print_header(test_case["name"])
    
    # In thông tin request
    print("📤 REQUEST:")
    print(f"  Method: POST /api/weather_chat")
    print(f"  Latitude: {test_case['lat']}")
    print(f"  Longitude: {test_case['lon']}")
    print(f"  Message: \"{test_case['message']}\"")
    
    try:
        # Gọi API
        start_time = time.time()
        
        response = requests.post(
            f"{API_BASE_URL}{API_ENDPOINT}",
            json={
                "lat": test_case["lat"],
                "lon": test_case["lon"],
                "message": test_case["message"]
            },
            headers={"Content-Type": "application/json"},
            timeout=60  # 60 giây timeout
        )
        
        elapsed_time = time.time() - start_time
        
        # Kiểm tra status code
        if response.status_code != 200:
            print_error(f"HTTP {response.status_code}")
            try:
                error_data = response.json()
                print(f"  Error: {error_data.get('message')}")
            except:
                print(f"  Response: {response.text}")
            return False
        
        # Parse response
        data = response.json()
        
        # Kiểm tra status trong response
        if data.get("status") != "success":
            print_error(f"Status: {data.get('status')}")
            print(f"  Message: {data.get('message')}")
            return False
        
        # In response thành công
        print_success(f"Response nhận được trong {elapsed_time:.2f}s")
        
        print("\n📥 RESPONSE:")
        print(f"  Status: {data.get('status')}")
        print(f"\n  🤖 AI Response:")
        
        # In response từ AI với formatting
        ai_response = data.get('ai_response', '')
        for line in ai_response.split('\n'):
            print(f"     {line}")
        
        # In weather data (nếu có)
        if data.get('weather_data'):
            weather = data['weather_data']['current']
            print(f"\n  📊 Weather Data:")
            print(f"     Temperature: {weather.get('temperature')}°C")
            print(f"     Humidity: {weather.get('humidity')}%")
            print(f"     Windspeed: {weather.get('windspeed')} km/h")
        
        return True
        
    except requests.exceptions.Timeout:
        print_error("Request timeout (>60s)")
        print_warning("API có thể đang bận hoặc Gemini API chậm")
        return False
    except requests.exceptions.ConnectionError:
        print_error("Không thể kết nối tới Backend")
        return False
    except json.JSONDecodeError:
        print_error("Response không phải JSON hợp lệ")
        print(f"  Response: {response.text[:200]}")
        return False
    except Exception as e:
        print_error(f"Lỗi không mong muốn: {e}")
        return False


def test_invalid_inputs():
    """Test các input không hợp lệ"""
    print_header("TEST INVALID INPUTS")
    
    invalid_cases = [
        {
            "name": "Test: Tọa độ ngoài phạm vi",
            "lat": 95.0,  # Ngoài -90 to 90
            "lon": 106.0,
            "message": "Test"
        },
        {
            "name": "Test: Kinh độ ngoài phạm vi",
            "lat": 21.0,
            "lon": 200.0,  # Ngoài -180 to 180
            "message": "Test"
        },
        {
            "name": "Test: Message rỗng",
            "lat": 21.0,
            "lon": 105.0,
            "message": ""
        },
        {
            "name": "Test: Thiếu lat parameter",
            "data": {"lon": 105.0, "message": "Test"}
        }
    ]
    
    for case in invalid_cases:
        print_info(f"\n{case['name']}")
        
        if "data" in case:
            payload = case["data"]
        else:
            payload = {
                "lat": case["lat"],
                "lon": case["lon"],
                "message": case["message"]
            }
        
        try:
            response = requests.post(
                f"{API_BASE_URL}{API_ENDPOINT}",
                json=payload,
                timeout=10
            )
            
            if response.status_code != 200:
                print_success(f"Backend đúng cách reject (HTTP {response.status_code})")
                try:
                    error_data = response.json()
                    print(f"  Error message: {error_data.get('message')}")
                except:
                    pass
            else:
                print_warning("Backend không reject input không hợp lệ")
                
        except Exception as e:
            print_error(f"Lỗi: {e}")


def run_all_tests():
    """Chạy tất cả tests"""
    print("\n")
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║      🤖 AI WEATHER CHATBOT - BACKEND TEST SUITE                   ║")
    print("║      Test Backend Flask + Gemini AI Integration                   ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    
    # Step 1: Kiểm tra health
    if not check_api_health():
        print_warning("\n⚠️  Không thể tiếp tục test vì Backend không hoạt động")
        return
    
    # Step 2: Test weather chat
    passed = 0
    failed = 0
    
    print("\n")
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  TEST WEATHER CHAT FUNCTIONALITY                                  ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    
    for test_case in TEST_CASES:
        if test_weather_chat(test_case):
            passed += 1
        else:
            failed += 1
        
        # Delay giữa các requests để tránh rate limit (Gemini Free tier 15 RPM)
        if test_case != TEST_CASES[-1]:
            time.sleep(5)
    
    # Step 3: Test invalid inputs
    print("\n")
    print("╔════════════════════════════════════════════════════════════════════╗")
    print("║  TEST ERROR HANDLING & VALIDATION                                 ║")
    print("╚════════════════════════════════════════════════════════════════════╝")
    
    test_invalid_inputs()
    
    # Summary
    print_header("TÓRA TẮT KẾT QUẢ TEST")
    print(f"Total tests: {len(TEST_CASES)}")
    print_success(f"Passed: {passed}")
    if failed > 0:
        print_error(f"Failed: {failed}")
    
    print("\n✨ Test suite hoàn tất!\n")


if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\n\n⚠️  Test suite bị dừng bởi người dùng")
    except Exception as e:
        print(f"\n\n❌ Lỗi không mong muốn: {e}")
