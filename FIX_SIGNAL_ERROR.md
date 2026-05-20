## ⚠️ FIX: ValueError - signal only works in main thread

### 🎯 Vấn đề

Khi chạy `app.py` qua Streamlit, bạn gặp lỗi:
```
ValueError: signal only works in main thread of the main interpreter
```

### 🔍 Nguyên Nhân

- Flask's development server sử dụng signal handlers (`signal.SIGTERM`)
- Signal handlers chỉ làm việc trong main thread
- Streamlit chạy user code trong separate thread
- **Conflict!** → ValueError

### ✅ Giải Pháp

**Chạy Flask và Streamlit trong 2 terminal RIÊNG BIỆT**

```
┌─────────────────────────────────────┐
│      Terminal 1 (Flask Backend)     │
│      python run_flask.py            │
│      → Lắng nghe port 5000          │
└─────────────────────────────────────┘
           ↑
           │ (HTTP requests)
           ↓
┌─────────────────────────────────────┐
│   Terminal 2 (Streamlit Frontend)   │
│   streamlit run abc.py              │
│   → Lắng nghe port 8501             │
└─────────────────────────────────────┘
```

---

## 🚀 Setup Đúng Cách (Step-by-Step)

### **1️⃣ Terminal 1 - Chạy Flask Backend**

```bash
cd "d:\app web"
python run_flask.py
```

**Kết quả mong đợi:**
```
======================================================================
  🚀 Khởi động AI Weather Chatbot Backend
======================================================================

📍 Server đang lắng nghe tại:
   • Local:   http://localhost:5000
   • Network: http://0.0.0.0:5000

🌐 API Endpoint:
   • POST /api/weather_chat
   • GET /api/health

⚠️  Chế độ: DEBUG MODE (dev server)
🔄 Auto-reload khi file thay đổi

======================================================================
 * Serving Flask app 'app'
 * Running on http://0.0.0.0:5000
```

✅ **Giữ terminal này mở!** Đừng đóng nó.

---

### **2️⃣ Terminal 2 - Chạy Streamlit Frontend (abc.py)**

Mở **terminal khác** và chạy:

```bash
cd "d:\app web"
streamlit run abc.py
```

**Kết quả mong đợi:**
```
  You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.x.x:8501
```

✅ **Streamlit sẽ tự mở trình duyệt** hoặc click link trên.

---

### **3️⃣ Terminal 3 (Tùy chọn) - Test Frontend Weather Chat**

Mở **terminal thứ 3**:

```bash
cd "d:\app web"
python test_weather_api.py
```

Để kiểm tra xem API có hoạt động không.

---

## 📊 Tóm Tắt Cấu Hình

| Thành Phần | Port | Terminal | Lệnh | URL |
|-----------|------|----------|------|-----|
| **Flask Backend** | 5000 | Terminal 1 | `python run_flask.py` | http://localhost:5000 |
| **Streamlit Frontend (abc.py)** | 8501 | Terminal 2 | `streamlit run abc.py` | http://localhost:8501 |
| **HTML Demo (optional)** | 5500 | Terminal 3 | `Live Server` | http://localhost:5500/weather_chat_demo.html |

---

## ✨ Workflow

```
User opens Streamlit (abc.py)
    ↓
User clicks on map → position selected
    ↓
User types question in chat
    ↓
Frontend JavaScript sends POST request
    ↓
Flask Backend receives request
    ↓
Flask calls Open-Meteo API → Get weather data
    ↓
Flask calls Gemini AI with weather data
    ↓
AI generates response
    ↓
Flask returns JSON response
    ↓
Frontend displays AI response in chat
```

---

## 🐛 Troubleshooting

### **❌ Lỗi: "Không thể kết nối Flask Backend"**

**Giải pháp:**
```bash
# 1. Kiểm tra Flask server có chạy chưa
# Terminal 1 phải có dòng: * Running on http://0.0.0.0:5000

# 2. Nếu port 5000 bị chiếm, thay đổi port
# Mở run_flask.py, thay:
app.run(debug=True, host='0.0.0.0', port=8000)  # Đổi 5000 → 8000

# 3. Update JavaScript để dùng port mới
# Trong weather-chatbot.js, thay:
API_BASE_URL: "http://localhost:8000"
```

### **❌ Lỗi: "Streamlit port 8501 đã được dùng"**

```bash
# Chạy Streamlit trên port khác
streamlit run abc.py --server.port 8502
```

### **❌ Flask không tự-reload khi chỉnh code**

```bash
# Kiểm tra Flask có debug mode không?
# run_flask.py phải có: debug=True

# Nếu vẫn không hoạt động, restart:
# Terminal 1: Ctrl+C
# Chạy lại: python run_flask.py
```

---

## 💡 Production Setup (Deploy)

Khi deploy production, **KHÔNG dùng `debug=True`**:

```bash
# Dùng Gunicorn thay vì Flask dev server
pip install gunicorn

# Chạy với 4 workers
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

Lợi ích:
- Không sử dụng signal handlers
- Multi-worker (xử lý nhiều requests)
- Ổn định hơn

---

## 📝 File Changes

**Thay đổi từ phiên bản trước:**

| File | Thay đổi |
|------|----------|
| `app.py` | Bỏ `if __name__ == '__main__': app.run()` |
| `run_flask.py` | **NEW** - Để chạy Flask riêng |
| `weather-chatbot.js` | Không thay đổi |
| `weather_chat_demo.html` | Không thay đổi |
| `README_WEATHER_CHATBOT.md` | **UPDATE** - Thêm hướng dẫn 2 terminal |

---

## ✅ Checklist Trước Chạy

- [ ] Flask Backend chạy trong Terminal 1
  ```bash
  python run_flask.py
  ```
  
- [ ] Streamlit Frontend chạy trong Terminal 2
  ```bash
  streamlit run abc.py
  ```

- [ ] Check Flask status: `http://localhost:5000/api/health` → ✅ 200 OK

- [ ] Open Streamlit: `http://localhost:8501` 

- [ ] Chat Widget load thành công (hoặc dùng demo HTML)

- [ ] Click map → Marker hiển thị

- [ ] Gửi message → AI responds

---

## 🎓 Tại Sao Cấu Hình Này?

| Lý Do | Chi Tiết |
|------|---------|
| **Separation of Concerns** | Backend & Frontend chạy độc lập |
| **Easy Development** | Thay đổi frontend không cần restart backend |
| **Better Error Isolation** | Lỗi ở một side không ảnh hưởng side khác |
| **Scalability** | Có thể deploy frontend & backend riêng |
| **Signal Safety** | Flask không cần signal handlers trong dev mode phức tạp |

---

## 🚀 Tiếp Theo

Sau khi setup xong:

1. ✅ Test Weather Chat API: `python test_weather_api.py`
2. ✅ Thêm tính năng (caching, history, etc.)
3. ✅ Deploy lên cloud (Render, Railway, Vercel)
4. ✅ Thêm database persistence
5. ✅ Thêm user authentication

Chúc bạn thành công! 🎉
