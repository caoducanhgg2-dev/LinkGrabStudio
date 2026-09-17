# LinkGrab Studio 1.0 Preview

Ứng dụng Windows giao diện tiếng Việt để xem trước và tải video từ YouTube,
TikTok và Douyin bằng cách dán một hoặc nhiều đường link.

## Tính năng hiện có

- Tự nhận diện và loại bỏ link trùng.
- Xem trước tiêu đề, kênh và thời lượng.
- Tải MP4/MKV hoặc tách MP3/M4A.
- Chọn chất lượng từ 480p đến 4K hoặc tốt nhất.
- Tải playlist theo lựa chọn rõ ràng.
- Hàng đợi tối đa bốn luồng, mặc định hai luồng.
- Tiến trình, tốc độ, ETA và nhật ký hoạt động.
- Chống tải trùng bằng SQLite.
- Lịch sử tải và mở nhanh thư mục kết quả.
- Hỗ trợ cookies.txt cho nội dung tài khoản được phép xem.
- Dừng an toàn, thử tiếp tục file dở bằng khả năng resume của yt-dlp.

## Chạy mã nguồn để phát triển

Yêu cầu Python 3.12:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
.\build\bootstrap_tools.ps1
python run_app.py
```

Người dùng cuối không cần thực hiện các lệnh này. Bản Setup đã đóng gói Python,
yt-dlp, FFmpeg và Deno.

## Tạo Setup.exe trên Windows

1. Cài Python 3.12 và Inno Setup 6 trên máy build.
2. Chạy `build\build_windows.ps1`.
3. File cài đặt nằm trong `dist\installer`.

Hoặc đưa dự án lên GitHub và chạy workflow **Build Windows Installer**. Workflow
sẽ tạo Setup.exe, bản portable ZIP và SHA256SUMS.

## Dữ liệu người dùng

Cấu hình, lịch sử và log được lưu trong `%LOCALAPPDATA%\LinkGrabStudio`. Video
được lưu vào thư mục người dùng chọn. Cập nhật hoặc cài đè không xóa lịch sử.

## Phạm vi sử dụng

Chỉ tải nội dung mà người dùng sở hữu hoặc được phép tải. Ứng dụng không phá
DRM, không lưu mật khẩu và không tự động đăng nội dung lên nền tảng.

