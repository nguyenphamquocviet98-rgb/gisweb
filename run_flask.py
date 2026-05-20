"""
==========================================
RUN FLASK SERVER
==========================================
File riêng để khởi động Flask Backend
Chạy: python run_flask.py

⚠️ QUAN TRỌNG: Chạy cái này trong terminal RIÊNG, 
   KHÔNG chạy qua Streamlit!
"""

import os
import sys
from pathlib import Path

# Reconfigure stdout/stderr to UTF-8 to prevent encoding crashes on Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

from flask import Flask, request, jsonify
from flask_cors import CORS  # Thêm dòng này


# Thêm project directory vào Python path
sys.path.insert(0, str(Path(__file__).parent))
# Import Flask app
from flask_app import app
CORS(app)  # Thêm dòng này để cho phép Frontend kết nối vào

def main():
    """Khởi động Flask server"""
    print("\n" + "="*70)
    print("  🚀 Khởi động AI Weather Chatbot Backend")
    print("="*70)
    print("\n📍 Server đang lắng nghe tại:")
    print("   • Local:   http://localhost:5000")
    print("   • Network: http://0.0.0.0:5000")
    print("\n🌐 API Endpoint:")
    print("   • POST /api/weather_chat")
    print("   • GET /api/health")
    print("\n⚠️  Chế độ: DEBUG MODE (dev server)")
    print("🔄 Auto-reload khi file thay đổi")
    print("💡 Tắt debug mode: Sửa debug=True → debug=False")
    print("\n" + "="*70 + "\n")
    
    # Chạy Flask app
    # debug=True: Auto-reload + detailed errors
    # host='0.0.0.0': Cho phép kết nối từ máy tính khác
    # port=5000: Port mặc định
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        use_reloader=True  # Auto-reload khi code thay đổi
    )


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⛔ Server bị dừng bởi người dùng (Ctrl+C)")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Lỗi: {e}")
        sys.exit(1)
