## 🤖 AI Weather Chatbot - Setup & Usage Guide

### 📋 Tổng Quan Hệ Thống

Hệ thống này bao gồm:
- **Backend (Python Flask)**: Xử lý API Weather từ Open-Meteo + Gemini AI
- **Frontend (HTML/JS)**: Giao diện chat thời tiết + Leaflet Map
- **Demo**: File HTML hoàn chỉnh để test tất cả tính năng

---

### 🔧 SETUP BACKEND (Python)

#### **1. Cài đặt Dependencies**

```bash
cd "d:\app web"
pip install -r requirements_chatbot.txt
```

Nếu chạy trong virtual environment:
```bash
.venv\Scripts\activate  # Windows
pip install -r requirements_chatbot.txt
```

#### **2. Cấu hình API Key**

Tạo file `.env` ở thư mục gốc dự án và thêm biến môi trường:

```env
GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE
```

**Cách lấy Gemini API Key:**
1. Vào https://aistudio.google.com/apikey
2. Click "Create API key"
3. Copy key và paste vào file `.env`. Không commit `.env` lên GitHub.

#### **3. Chạy Server Flask**

```bash
python app.py
```

Nếu thành công, bạn sẽ thấy:
```
🚀 Khởi động AI Weather Chatbot Backend...
📍 Lắng nghe tại: http://localhost:5000
🌐 Endpoint: POST /api/weather_chat
 * Serving Flask app
 * Running on http://0.0.0.0:5000
```

---

### 🌐 SETUP FRONTEND (JavaScript)

#### **1. Các file cần thiết**

```
d:\app web\
├── app.py                    # Backend Flask
├── weather-chatbot.js        # Chatbot logic
└── weather_chat_demo.html    # Demo page
```

#### **2. Chạy Demo**

1. **Mở file HTML trực tiếp:**
   ```
   Nhấp đôi vào: weather_chat_demo.html
   ```

   Hoặc dùng VS Code:
   ```
   Chuột phải trên file → Open with Live Server
   ```

2. **URL sẽ là:**
   ```
   http://localhost:5500/weather_chat_demo.html
   (hoặc port khác tùy vào cấu hình)
   ```

#### **3. Kiểm tra API Status**

Sidebar bên phải sẽ hiển thị:
- ✅ **API Status**: Green = Backend online
- ❌ **Red**: Backend chưa chạy

---

### 🎯 SỬ DỤNG HỆ THỐNG

#### **Bước 1: Click vào Bản đồ**
```
Chọn một vị trí bất kỳ trên Leaflet Map
→ Sẽ xuất hiện 1 marker xanh
→ Sidebar sẽ hiển thị tọa độ
```

#### **Bước 2: Đặt Câu Hỏi**
```
Nhập: "Hôm nay trời thế nào?"
      "Có mưa không?"
      "Nhiệt độ hiện tại bao nhiêu độ?"
      "Gió mạnh không?"
```

#### **Bước 3: Nhấn Gửi**
```
Click button "Gửi" hoặc nhấn Enter
→ Message được gửi tới Backend
→ Backend lấy data từ Open-Meteo
→ Gemini AI xử lý + trả lời
→ Response hiển thị trong chat
```

---

### 🔄 LUỒNG XỬ LÝ CHI TIẾT

#### **Frontend → Backend:**
```json
POST /api/weather_chat

{
    "lat": 16.0,
    "lon": 106.0,
    "message": "Trời thế nào?"
}
```

#### **Backend (Bước A - Lấy Data):**
```
1. Nhận request từ Frontend
2. Gọi API Open-Meteo:
   https://api.open-meteo.com/v1/forecast?latitude=16.0&longitude=106.0&...
3. Trích xuất:
   - Nhiệt độ hiện tại
   - Độ ẩm
   - Sức gió
   - Dự báo hôm nay
4. Format data thành structured object
```

#### **Backend (Bước B - Gọi AI):**
```
1. Nhúng weather data vào system_prompt
2. Gọi Gemini API với:
   - model: "gemini-2.5-flash"
   - contents: system_prompt + user message
3. AI trả về câu trả lời tự nhiên, ngắn gọn
4. Backend trả response JSON cho Frontend
```

#### **Backend → Frontend:**
```json
HTTP 200 OK

{
    "status": "success",
    "ai_response": "🌤️ Hôm nay trời khá nắng với nhiệt độ hiện tại là 28°C...",
    "weather_data": {
        "current": {
            "temperature": 28,
            "humidity": 65,
            "windspeed": 5.5,
            ...
        },
        "daily_forecast": [...]
    }
}
```

---

### 🐛 TROUBLESHOOTING

#### **❌ Lỗi: "Không thể kết nối Backend"**
```
Giải pháp:
1. Kiểm tra Flask server có chạy không?
   python app.py

2. Kiểm tra port 5000 có bị chiếm không?
   netstat -ano | findstr :5000

3. Kiểm tra Firewall có block port 5000 không?
   Windows Defender Firewall → Allow Flask
```

#### **❌ Lỗi: "API Open-Meteo timeout"**
```
Giải pháp:
1. Kiểm tra internet connection
2. Thử gọi API trực tiếp:
   https://api.open-meteo.com/v1/forecast?latitude=16&longitude=106&current_weather=true

3. Tăng timeout trong app.py từ 10 lên 20 giây:
   response = requests.get(OPENMETEO_BASE_URL, params=params, timeout=20)
```

#### **❌ Lỗi: "Invalid Gemini API Key"**
```
Giải pháp:
1. Kiểm tra API key trong app.py
2. Lấy key mới từ: https://aistudio.google.com/apikey
3. Đảm bảo key không có khoảng trống
4. Đảm bảo billing account active
```

#### **❌ Chat không load, hoặc loading mãi**
```
Giải pháp:
1. Kiểm tra DevTools (F12) → Console tab
2. Xem error message
3. Nếu lỗi CORS, kiểm tra Flask app có `CORS(app)` không
4. Nếu lỗi timeout, tăng timeout trong weather-chatbot.js:
   TIMEOUT: 60000  // 60 giây
```

---

### 📝 CUSTOMIZATION

#### **1. Thay đổi System Prompt**
File: `app.py`, hàm `call_gemini_weather_ai()`

```python
system_prompt = f"""Bạn là một chuyên gia thời tiết...
[Thay đổi đoạn này theo yêu cầu của bạn]
"""
```

#### **2. Thêm Thêm Weather Parameters**
File: `app.py`, hàm `get_weather_data()`

```python
params = {
    "latitude": latitude,
    "longitude": longitude,
    "current_weather": True,
    "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,...",
    # Thêm thêm parameters từ Open-Meteo docs
}
```

#### **3. Thay đổi UI Chat**
File: `weather-chatbot.js`, hàm `initWeatherChatUI()`

```javascript
// Thay đổi CSS inline hoặc thêm stylesheet riêng
```

---

### 🚀 DEPLOYMENT (Cho Production)

#### **1. Sử dụng Gunicorn (thay vì Flask dev server)**
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

#### **2. Sử dụng Docker (tùy chọn)**
```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements_chatbot.txt .
RUN pip install -r requirements_chatbot.txt
COPY . .
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:5000", "app:app"]
```

#### **3. Deploy lên Cloud (Render, Railway, Heroku)**
```
Quy trình tương tự deployment Flask thông thường
```

---

### 📊 API Endpoints

#### **POST /api/weather_chat**
```
Mô tả: Chat với AI về thời tiết
Payload:
{
    "lat": float (-90 to 90),
    "lon": float (-180 to 180),
    "message": string (max 500 chars)
}

Response:
{
    "status": "success" | "error",
    "ai_response": string,
    "weather_data": object (optional)
}
```

#### **GET /api/health**
```
Mô tả: Kiểm tra trạng thái API
Response:
{
    "status": "ok",
    "timestamp": "2026-05-18T...",
    "service": "AI Weather Chatbot"
}
```

---

### 📚 Công Nghệ Sử Dụng

| Thành Phần | Công Nghệ | Phiên Bản |
|-----------|-----------|----------|
| Backend | Flask | 3.0.0 |
| AI Model | Gemini 2.5 Flash | Latest |
| Weather API | Open-Meteo | Free |
| Frontend | HTML5 + Vanilla JS | - |
| Map | Leaflet.js | 1.9.4 |
| CORS | Flask-CORS | 4.0.0 |

---

### 🎓 Học Thêm

- **Open-Meteo API**: https://open-meteo.com/en/docs
- **Gemini API**: https://ai.google.dev/docs
- **Leaflet Map**: https://leafletjs.com/
- **Flask**: https://flask.palletsprojects.com/

---

### ✅ Checklist Trước Deploy

- [ ] API Key Gemini đã setup
- [ ] Backend chạy ok (kiểm tra /api/health)
- [ ] Frontend load đúng URL
- [ ] Click map → marker hiển thị
- [ ] Chat gửi message → nhận response AI
- [ ] Không có lỗi CORS
- [ ] Error handling hoạt động
- [ ] Timeout xử lý đúng

---

### 💡 Ghi Chú

- **Rate Limit**: Google Gemini có giới hạn requests/phút
- **Cost**: Open-Meteo free, Gemini có free tier
- **Security**: Không hardcode API key vào production (dùng environment variables)
- **Performance**: Có thể cache weather data trong 30 phút để giảm API calls

---

### 📞 Support

Nếu có vấn đề, kiểm tra:
1. Console log trong browser (F12)
2. Server log trong terminal
3. Status indicator trong sidebar
4. Network tab để xem request/response

Chúc bạn thành công! 🚀
