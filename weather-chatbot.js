/**
 * ==========================================
 * FRONTEND JAVASCRIPT - AI WEATHER CHATBOT
 * ==========================================
 * Chức năng: Giao diện chat thời tiết thông minh
 * - Gửi câu hỏi tới Backend AI
 * - Xử lý loading state
 * - Hiển thị response từ AI
 */

// =========================================================
// 1. CẤU HÌNH TOÀN CỤC
// =========================================================
const WEATHER_CHAT_CONFIG = {
    API_BASE_URL: "http://localhost:5000",  // URL Backend Flask
    CHAT_ENDPOINT: "/api/weather_chat",
    TIMEOUT: 30000  // Timeout 30 giây
};

let currentWeatherMarker = null;  // Marker hiện tại trên bản đồ
let isWaitingForResponse = false;  // Flag để ngăn gửi nhiều request cùng lúc


// =========================================================
// 2. HÀM HELPER - HIỂN THỊ LOADING ANIMATION
// =========================================================
function showChatLoading(chatContainer) {
    /**
     * Hiển thị tin nhắn "AI đang gõ..."
     * @param {HTMLElement} chatContainer - Container chứa chat
     */
    const loadingHTML = `
        <div class="chat-message ai-message loading-message" id="ai-loading">
            <div class="message-avatar">🤖</div>
            <div class="message-content">
                <div class="typing-indicator">
                    <span></span>
                    <span></span>
                    <span></span>
                </div>
                <span class="typing-text">AI đang phân tích...</span>
            </div>
        </div>
    `;
    chatContainer.insertAdjacentHTML("beforeend", loadingHTML);
    chatContainer.scrollTop = chatContainer.scrollHeight;  // Scroll xuống dưới cùng
}


// =========================================================
// 3. HÀM HELPER - XÓA LOADING MESSAGE
// =========================================================
function removeChatLoading() {
    /**
     * Xóa loading message khỏi chat
     */
    const loadingEl = document.getElementById("ai-loading");
    if (loadingEl) {
        loadingEl.remove();
    }
}


// =========================================================
// 4. HÀM HELPER - THÊM TIN NHẮN NGƯỜI DÙNG VÀO CHAT
// =========================================================
function addUserMessage(chatContainer, message) {
    /**
     * Thêm tin nhắn từ người dùng vào chat UI
     * @param {HTMLElement} chatContainer - Container chứa chat
     * @param {string} message - Nội dung tin nhắn
     */
    const userMessageHTML = `
        <div class="chat-message user-message">
            <div class="message-content">
                ${escapeHTML(message)}
            </div>
            <div class="message-avatar">👤</div>
        </div>
    `;
    chatContainer.insertAdjacentHTML("beforeend", userMessageHTML);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}


// =========================================================
// 5. HÀM HELPER - THÊM TIN NHẮN AI VÀO CHAT
// =========================================================
function addAIMessage(chatContainer, message) {
    /**
     * Thêm tin nhắn từ AI vào chat UI
     * @param {HTMLElement} chatContainer - Container chứa chat
     * @param {string} message - Nội dung tin nhắn từ AI
     */
    const aiMessageHTML = `
        <div class="chat-message ai-message">
            <div class="message-avatar">🤖</div>
            <div class="message-content">
                ${escapeHTML(message)}
            </div>
        </div>
    `;
    chatContainer.insertAdjacentHTML("beforeend", aiMessageHTML);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}


// =========================================================
// 6. HÀM HELPER - ESCAPE HTML (BẢO VỆ KHỎI XSS)
// =========================================================
function escapeHTML(text) {
    /**
     * Escape HTML characters để tránh XSS attack
     * @param {string} text - Text cần escape
     * @returns {string} - Text đã được escape
     */
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}


// =========================================================
// 7. HÀM HELPER - HIỂN THỊ LỖI TRONG CHAT
// =========================================================
function showChatError(chatContainer, errorMessage) {
    /**
     * Hiển thị tin nhắn lỗi trong chat
     * @param {HTMLElement} chatContainer - Container chứa chat
     * @param {string} errorMessage - Nội dung lỗi
     */
    const errorHTML = `
        <div class="chat-message error-message">
            <div class="message-avatar">❌</div>
            <div class="message-content">
                <strong>Lỗi:</strong> ${escapeHTML(errorMessage)}
            </div>
        </div>
    `;
    chatContainer.insertAdjacentHTML("beforeend", errorHTML);
    chatContainer.scrollTop = chatContainer.scrollHeight;
}


// =========================================================
// 8. HÀM CHÍNH - GỬI CÂU HỎI THỜI TIẾT TỚI AI
// =========================================================
async function askWeatherAI(lat, lon, userQuestion, chatContainer) {
    /**
     * Gửi câu hỏi thời tiết tới Backend AI
     * 
     * @param {number} lat - Vĩ độ
     * @param {number} lon - Kinh độ
     * @param {string} userQuestion - Câu hỏi của người dùng
     * @param {HTMLElement} chatContainer - Container hiển thị chat
     * @returns {Promise<string>} - Response từ AI
     */
    
    // Kiểm tra nếu đang chờ response
    if (isWaitingForResponse) {
        console.warn("⏳ Vẫn đang chờ response từ AI, hãy chờ...");
        showChatError(chatContainer, "Vẫn đang xử lý câu hỏi trước đó. Vui lòng chờ!");
        return;
    }
    
    // Validate input
    if (!lat || !lon) {
        console.error("❌ Tọa độ không hợp lệ");
        showChatError(chatContainer, "Vui lòng chọn một điểm trên bản đồ trước!");
        return;
    }
    
    if (!userQuestion || userQuestion.trim() === "") {
        console.error("❌ Câu hỏi trống");
        showChatError(chatContainer, "Vui lòng nhập một câu hỏi!");
        return;
    }
    
    // Đặt flag
    isWaitingForResponse = true;
    
    try {
        // Hiển thị tin nhắn từ người dùng
        addUserMessage(chatContainer, userQuestion);
        
        // Hiển thị loading animation
        showChatLoading(chatContainer);
        
        console.log(`📤 Gửi câu hỏi: "${userQuestion}" từ tọa độ (${lat}, ${lon})`);
        
        // Tạo request payload
        const payload = {
            lat: parseFloat(lat),
            lon: parseFloat(lon),
            message: userQuestion.trim()
        };
        
        // Gọi API Backend
        const response = await fetch(
            `${WEATHER_CHAT_CONFIG.API_BASE_URL}${WEATHER_CHAT_CONFIG.CHAT_ENDPOINT}`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                body: JSON.stringify(payload),
                timeout: WEATHER_CHAT_CONFIG.TIMEOUT
            }
        );
        
        // Kiểm tra response status
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(
                errorData.message || 
                `API trả về lỗi ${response.status}: ${response.statusText}`
            );
        }
        
        // Parse response JSON
        const data = await response.json();
        
        // Kiểm tra status trong response
        if (data.status !== "success") {
            throw new Error(data.message || "API không trả về kết quả thành công");
        }
        
        // Xóa loading message
        removeChatLoading();
        
        // Lấy response từ AI
        const aiResponse = data.ai_response;
        console.log("📥 Nhận response từ AI:", aiResponse);
        
        // Hiển thị response từ AI trong chat
        addAIMessage(chatContainer, aiResponse);
        
        return aiResponse;
        
    } catch (error) {
        // Xóa loading message nếu có lỗi
        removeChatLoading();
        
        // Log lỗi chi tiết
        console.error("❌ Lỗi trong askWeatherAI:", error);
        
        // Xác định loại lỗi
        let errorMsg = "Có lỗi xảy ra";
        
        if (error.name === "TypeError" && error.message.includes("fetch")) {
            errorMsg = "Không thể kết nối tới Backend. Kiểm tra xem server đã chạy chưa?";
        } else if (error.message.includes("timeout")) {
            errorMsg = "Yêu cầu quá lâu. Vui lòng thử lại sau.";
        } else if (error.message.includes("API")) {
            errorMsg = error.message;
        } else {
            errorMsg = error.message || "Lỗi không xác định";
        }
        
        // Hiển thị lỗi trong chat
        showChatError(chatContainer, errorMsg);
        
    } finally {
        // Reset flag
        isWaitingForResponse = false;
    }
}


// =========================================================
// 9. KHỞI TẠO CHAT UI (MẪU CÓ THỂ DÙNG)
// =========================================================
function initWeatherChatUI() {
    /**
     * Khởi tạo giao diện chat thời tiết (nếu chưa có)
     * Tạo HTML container cho chat
     */
    
    // Kiểm tra xem chat container đã tồn tại chưa
    if (document.getElementById("weather-chat-container")) {
        console.log("✅ Chat container đã tồn tại");
        return;
    }
    
    // Tạo HTML structure cho chat
    const chatHTML = `
        <div id="weather-chat-container" class="weather-chat-widget" style="
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 380px;
            height: 500px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.15);
            display: flex;
            flex-direction: column;
            z-index: 999;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        ">
            <!-- Header -->
            <div style="
                background: linear-gradient(135deg, #4f46e5, #3b82f6);
                color: white;
                padding: 16px 20px;
                border-radius: 16px 16px 0 0;
                font-weight: 700;
                display: flex;
                justify-content: space-between;
                align-items: center;
            ">
                <span>🤖 AI Thời Tiết Thông Minh</span>
                <button onclick="toggleWeatherChat()" style="
                    background: rgba(255,255,255,0.2);
                    border: none;
                    color: white;
                    cursor: pointer;
                    font-size: 18px;
                    padding: 4px 8px;
                    border-radius: 6px;
                    transition: background 0.2s;
                " onmouseover="this.style.background='rgba(255,255,255,0.3)'" onmouseout="this.style.background='rgba(255,255,255,0.2)'">
                    ✕
                </button>
            </div>
            
            <!-- Chat Messages Area -->
            <div id="weather-chat-messages" style="
                flex: 1;
                overflow-y: auto;
                padding: 16px;
                background: #f8fafc;
                border-bottom: 1px solid #e2e8f0;
            ">
                <div class="chat-message ai-message" style="
                    display: flex;
                    gap: 10px;
                    margin-bottom: 12px;
                    animation: slideIn 0.3s ease;
                ">
                    <div style="font-size: 20px;">🤖</div>
                    <div style="
                        background: white;
                        padding: 10px 14px;
                        border-radius: 12px;
                        border-left: 3px solid #4f46e5;
                        font-size: 13px;
                        line-height: 1.5;
                        color: #475569;
                    ">
                        👋 Xin chào! Tôi là AI chuyên gia thời tiết. Hãy click vào một điểm trên bản đồ và đặt câu hỏi về thời tiết tại đó!
                    </div>
                </div>
            </div>
            
            <!-- Input Area -->
            <div style="padding: 12px; background: white; border-radius: 0 0 16px 16px;">
                <div style="display: flex; gap: 8px;">
                    <input 
                        id="weather-chat-input"
                        type="text" 
                        placeholder="Hôm nay trời thế nào? Có mưa không?..."
                        style="
                            flex: 1;
                            border: 1px solid #e2e8f0;
                            border-radius: 10px;
                            padding: 10px 14px;
                            font-size: 13px;
                            outline: none;
                            transition: border-color 0.2s;
                        "
                        onkeypress="event.key === 'Enter' && sendWeatherMessage()"
                        onfocus="this.style.borderColor='#4f46e5'"
                        onblur="this.style.borderColor='#e2e8f0'"
                    />
                    <button 
                        onclick="sendWeatherMessage()"
                        style="
                            background: linear-gradient(135deg, #4f46e5, #3b82f6);
                            color: white;
                            border: none;
                            border-radius: 10px;
                            padding: 10px 16px;
                            cursor: pointer;
                            font-weight: 600;
                            font-size: 14px;
                            transition: opacity 0.2s;
                        "
                        onmouseover="this.style.opacity='0.9'"
                        onmouseout="this.style.opacity='1'"
                    >
                        Gửi
                    </button>
                </div>
            </div>
        </div>
        
        <style>
            @keyframes slideIn {
                from {
                    opacity: 0;
                    transform: translateY(10px);
                }
                to {
                    opacity: 1;
                    transform: translateY(0);
                }
            }
            
            .chat-message {
                animation: slideIn 0.3s ease;
            }
            
            .typing-indicator span {
                display: inline-block;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                background: #4f46e5;
                margin-right: 4px;
                animation: typing 1.4s infinite;
            }
            
            .typing-indicator span:nth-child(2) {
                animation-delay: 0.2s;
            }
            
            .typing-indicator span:nth-child(3) {
                animation-delay: 0.4s;
            }
            
            @keyframes typing {
                0%, 60%, 100% {
                    opacity: 0.5;
                }
                30% {
                    opacity: 1;
                }
            }
            
            #weather-chat-messages::-webkit-scrollbar {
                width: 6px;
            }
            
            #weather-chat-messages::-webkit-scrollbar-track {
                background: #f1f5f9;
                border-radius: 10px;
            }
            
            #weather-chat-messages::-webkit-scrollbar-thumb {
                background: #cbd5e1;
                border-radius: 10px;
            }
            
            #weather-chat-messages::-webkit-scrollbar-thumb:hover {
                background: #94a3b8;
            }
        </style>
    `;
    
    // Thêm vào body
    document.body.insertAdjacentHTML("beforeend", chatHTML);
    console.log("✅ Chat UI đã được khởi tạo");
}


// =========================================================
// 10. HÀM GỬI CHAT MESSAGE
// =========================================================
function sendWeatherMessage() {
    /**
     * Lấy input từ text field và gửi câu hỏi
     */
    const input = document.getElementById("weather-chat-input");
    const userQuestion = input.value.trim();
    
    if (!userQuestion) {
        console.warn("⚠️ Câu hỏi trống");
        return;
    }
    
    // Lấy tọa độ từ marker hiện tại (giả sử marker đã được set)
    if (!currentWeatherMarker) {
        alert("❌ Vui lòng click vào một điểm trên bản đồ trước!");
        return;
    }
    
    const {lat, lng} = currentWeatherMarker.getLatLng();
    const chatContainer = document.getElementById("weather-chat-messages");
    
    // Gọi hàm chính
    askWeatherAI(lat, lng, userQuestion, chatContainer);
    
    // Clear input
    input.value = "";
    input.focus();
}


// =========================================================
// 11. HÀM TOGGLE CHAT WIDGET
// =========================================================
function toggleWeatherChat() {
    /**
     * Toggle hiển thị/ẩn chat widget
     */
    const chatContainer = document.getElementById("weather-chat-container");
    if (chatContainer) {
        chatContainer.style.display = 
            chatContainer.style.display === "none" ? "flex" : "none";
    }
}


// =========================================================
// 12. HÀM INTEGRATION VỚI LEAFLET MAP
// =========================================================
function setupWeatherChatIntegration(map) {
    /**
     * Tích hợp Weather Chat vào Leaflet map
     * Khi người dùng click vào map, lưu marker
     * 
     * @param {L.Map} map - Leaflet map object
     */
    
    map.on("click", function(e) {
        const {lat, lng} = e.latlng;
        
        // Xóa marker cũ nếu có
        if (currentWeatherMarker) {
            map.removeLayer(currentWeatherMarker);
        }
        
        // Tạo marker mới
        currentWeatherMarker = L.circleMarker(
            [lat, lng],
            {
                radius: 8,
                fillColor: "#4f46e5",
                color: "#fff",
                weight: 3,
                opacity: 1,
                fillOpacity: 0.8,
                title: `📍 ${lat.toFixed(4)}, ${lng.toFixed(4)}`
            }
        ).addTo(map);
        
        // Thêm popup
        currentWeatherMarker.bindPopup(
            `📍 <strong>Vị trí được chọn</strong><br/>
             Vĩ độ: ${lat.toFixed(4)}<br/>
             Kinh độ: ${lng.toFixed(4)}<br/>
             <small>Hãy hỏi AI về thời tiết tại đây!</small>`
        ).openPopup();
        
        console.log(`📍 Marker được set tại: (${lat}, ${lng})`);
    });
    
    console.log("✅ Weather Chat đã được tích hợp với Leaflet map");
}


// =========================================================
// 13. AUTO-INIT WHEN DOCUMENT IS READY
// =========================================================
document.addEventListener("DOMContentLoaded", function() {
    console.log("🚀 Khởi tạo AI Weather Chatbot Frontend...");
    initWeatherChatUI();
    console.log("✅ Frontend sẵn sàng. Hãy gọi setupWeatherChatIntegration(map) để tích hợp với Leaflet!");
});


// =========================================================
// 14. EXPORT FUNCTIONS (NẾU DÙNG MODULE)
// =========================================================
// Nếu dùng ES modules:
// export { askWeatherAI, initWeatherChatUI, setupWeatherChatIntegration };
