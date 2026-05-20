-- Tạo Database (Nếu chưa có)
CREATE DATABASE GIS_Urban_Analysis;
GO

USE GIS_Urban_Analysis;
GO

-- =========================================
-- 1. BẢNG NGƯỜI DÙNG (USERS)
-- =========================================
-- Tối giản hệ thống phân quyền thành 2 nhóm: User phổ thông và Quản trị viên (Admin)
CREATE TABLE Users (
    UserID INT IDENTITY(1,1) PRIMARY KEY,
    Username VARCHAR(50) UNIQUE NOT NULL,
    PasswordHash VARCHAR(255) NOT NULL,
    FullName NVARCHAR(100),
    UserRole VARCHAR(20) DEFAULT 'User' CHECK (UserRole IN ('User', 'Admin')),
    IsActive BIT DEFAULT 1,
    CreatedAt DATETIME DEFAULT GETDATE()
);
GO

-- =========================================
-- 2. BẢNG BỘ NHỚ ĐỆM (ANALYSIS CACHE) - LÕI TỐI ƯU TỐC ĐỘ
-- =========================================
-- Nơi chứa kết quả đã tính toán. Thay vì để AI chạy mất 20 giây, 
-- nếu truy vấn trùng khớp, hệ thống sẽ móc dữ liệu từ đây ra trong 0.1 giây.
CREATE TABLE Analysis_Cache (
    CacheID INT IDENTITY(1,1) PRIMARY KEY,
    QueryHash VARCHAR(64) UNIQUE NOT NULL,    -- Mã băm (Hash) sinh ra từ việc ghép (Quốc gia + Tỉnh + Chỉ số + Năm)
    CountryName NVARCHAR(100) NOT NULL,
    SubRegions NVARCHAR(255) NOT NULL,        -- Các vùng đã chọn
    LayerIndex VARCHAR(20) NOT NULL,          -- NDBI, NDVI, LST
    AnalyzedYears VARCHAR(100) NOT NULL,      -- VD: "2022,2024,2026"
    
    -- Lưu toàn bộ biểu đồ, thông số tính toán thành chuỗi JSON
    StatsResultData NVARCHAR(MAX) NOT NULL,   
    
    -- Lưu báo cáo học thuật do Gemini viết
    GeminiReport NVARCHAR(MAX),               
    
    CreatedAt DATETIME DEFAULT GETDATE(),
    ExpirationDate DATETIME DEFAULT DATEADD(DAY, 30, GETDATE()) -- Dữ liệu lưu đệm 30 ngày để đảm bảo tính cập nhật
);
GO

-- =========================================
-- 3. BẢNG LỊCH SỬ TRA CỨU (SEARCH LOGS)
-- =========================================
-- Theo dõi hành vi người dùng, phục vụ thống kê quản trị.
CREATE TABLE Search_Logs (
    LogID INT IDENTITY(1,1) PRIMARY KEY,
    UserID INT, -- Có thể NULL nếu cho phép khách vãng lai (Guest) tra cứu
    CacheID INT NOT NULL,
    SearchTime DATETIME DEFAULT GETDATE(),
    
    CONSTRAINT FK_SearchLog_User FOREIGN KEY (UserID) REFERENCES Users(UserID),
    CONSTRAINT FK_SearchLog_Cache FOREIGN KEY (CacheID) REFERENCES Analysis_Cache(CacheID) ON DELETE CASCADE
);
GO

-- Thêm một tài khoản Admin mặc định để test
INSERT INTO Users (Username, PasswordHash, FullName, UserRole)
VALUES ('admin', 'hashed_password_here', N'Quản trị viên Hệ thống', 'Admin');
GO