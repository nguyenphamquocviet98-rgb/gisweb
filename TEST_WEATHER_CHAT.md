## 🧪 HƯỚNG DẪN TEST WEATHER CHAT

### ✅ Vấn đề Đã Fix

1. **CORS & Endpoint Issues** 
   - Sửa endpoint URL từ `/api/chat` → `/api/weather_chat`
   - Cấu hình CORS đúng để handle OPTIONS preflight requests
   - Thêm `@cross_origin()` decorator trên endpoints

2. **Open-Meteo API Data Issue**
   - Cập nhật từ Open-Meteo API v0.1 (cũ) → v1 (hiện tại)
   - Sửa tên parameters: `current_weather: True` → `current: "..."`
   - Sửa tên field: `windspeed` → `wind_speed_10m`, `weathercode` → `weather_code`
   - Thêm debug logging để track requests

3. **Response Key Mismatch**
   - Frontend cập nhật để lấy `data.ai_response` đúng

### 🚀 Test Steps

#### Terminal 1: Khởi động Flask Backend
```bash
cd "d:\app web"
python run_flask.py
```

Kết quả mong đợi:
```
======================================================================
  🚀 Khởi động AI Weather Chatbot Backend
======================================================================
📍 Server đang lắng nghe tại:
   • Local:   http://localhost:5000
   • Network: http://0.0.0.0:5000
 * Running on http://127.0.0.1:5000
 * Debugger is active!
```

#### Terminal 2: Khởi động Streamlit Frontend
```bash
cd "d:\app web"
streamlit run abc.py
```

Kết quả mong đợi:
```
  You can now view your Streamlit app in your browser.
  Local URL: http://localhost:8501
```

#### Test Weather Chat

1. **Bấm nút "💬 HỎI ĐÁP AI THỜI TIẾT"**
   - Nên mở page HTML standalone mới
   - Hoặc mở trực tiếp: http://127.0.0.1:5500/weather_chat_demo.html

2. **Chọn vị trí trên bản đồ**
   - Click bất kỳ điểm nào trên bản đồ
   - Marker sẽ hiện lên

3. **Gõ câu hỏi**
   - Ví dụ: "Hôm nay thời tiết thế nào?"
   - Hoặc: "Có mưa không?"

4. **Bấm Send hoặc Enter**
   - Bot sẽ phân tích dữ liệu thời tiết từ Open-Meteo
   - Gọi Gemini AI để tạo response
   - Trả lời trong 2-3 giây

#### ✅ Expected Response
```
Chào bạn! Hiện tại trời đang mưa vừa với nhiệt độ 30.0°C. 
Hôm nay, dự báo sẽ tiếp tục mưa cả ngày với xác suất mưa 100%, 
nhiệt độ cao nhất đạt 30.1°C và thấp nhất 25.2°C. 
Bạn nhớ mang theo ô khi ra ngoài nhé! ☔️🌧️
```

### 🔍 Debug Logs

Khi gửi câu hỏi, kiểm tra Terminal 1 (Flask) sẽ thấy:

```
📡 DEBUG: Gọi Open-Meteo API với tọa độ (21.0285, 105.8542)
📡 DEBUG: Response Status Code: 200
✅ DEBUG: Thành công lấy dữ liệu thời tiết
🤖 DEBUG: Prompt: [693 ký tự]
✅ DEBUG: Gemini response received: Chào bạn! Hiện tại...
```

### 📊 Tệp Test Có Sẵn

Nếu muốn test từng component riêng:

1. **Test Open-Meteo API:**
   ```bash
   python test_openmeteo.py
   ```

2. **Test Full Flow (Open-Meteo → Gemini):**
   ```bash
   python test_full_flow.py
   ```

### ⚠️ Common Issues & Solutions

**Problem:** Status báo "Offline"
- **Solution:** Flask server chưa chạy. Chạy `python run_flask.py` trong terminal 1

**Problem:** Lỗi "Vui lòng kiểm tra lại Backend"
- **Solution:** Kiểm tra Flask logs (Terminal 1) xem có lỗi gì
- Thử bấm nút "🔄 Kiểm tra kết nối" hoặc refresh page

**Problem:** Bot trả lời "Dữ liệu không đầy đủ"
- **Solution:** Kiểm tra tọa độ có hợp lệ không (-90 đến 90 cho lat, -180 đến 180 cho lon)

**Problem:** Quá chậm (> 5 giây)
- **Solution:** Có thể mạng bị chậm. Thử lại

### 📝 Lưu Ý

- Weather Chat độc lập với Streamlit app
- Có thể mở weather_chat_demo.html trực tiếp hoặc qua nút trong Streamlit
- Tất cả data là real-time từ Open-Meteo API (không cache)
- Gemini AI response phụ thuộc vào API quota

### ✨ Hoàn Thành!

Nếu các bước trên hoạt động tốt ✅, tức là:
- ✅ CORS hoạt động
- ✅ Open-Meteo API integration đúng
- ✅ Gemini AI trả lời đúng
- ✅ Response format khớp giữa backend & frontend

Bạn đã sẵn sàng sử dụng Weather Chat! 🎉
