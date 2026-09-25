# LinkGrab Studio 1.4

Ứng dụng Windows giao diện tiếng Việt để xem trước và tải video từ YouTube,
TikTok, Douyin, Facebook và Instagram bằng cách dán một hoặc nhiều đường link.

## Tính năng hiện có

- Tự nhận diện và loại bỏ link trùng.
- Tải trực tiếp video, Reels và bài đăng video công khai từ Facebook/Instagram.
- Xem trước tiêu đề, kênh và thời lượng.
- Tải MP4/MKV hoặc tách MP3/M4A.
- Chọn chất lượng từ 480p đến 4K hoặc tốt nhất.
- Tải playlist theo lựa chọn rõ ràng.
- Dán link kênh YouTube/TikTok/Douyin và lấy danh sách video.
- Lọc video trong 1 tuần, 1 tháng, 3 tháng, 6 tháng hoặc 1 năm.
- Tìm video YouTube hoặc Douyin theo từ khóa, chọn 1–300 kết quả và xếp hạng theo lượt xem, độ mới hoặc độ liên quan.
- Tự dịch từ khóa Douyin sang tiếng Trung giản thể/phồn thể và hiển thị bản dịch trong nhật ký.
- Sắp xếp theo lượt xem cao nhất hoặc video mới nhất.
- Hiển thị lượt xem, ngày đăng và link nguồn trong danh sách xem trước.
- Hàng đợi tối đa bốn luồng, mặc định hai luồng.
- Tiến trình, tốc độ, ETA và nhật ký hoạt động.
- Chống tải trùng bằng SQLite; video trùng được bỏ chọn, nhưng có thể chọn “Tải lại” để ghi lại file khi cần.
- Lịch sử tải lưu link nguồn và mở nhanh thư mục kết quả.
- Hỗ trợ cookies.txt cho nội dung Douyin/Facebook/Instagram mà tài khoản được phép xem.
- Lưu cookies riêng theo nền tảng và tự chọn đúng file khi xử lý danh sách link hỗn hợp.
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

## Tạo gói cập nhật ZIP 1.1 trên Windows

1. Cài Python 3.12 trên máy build.
2. Chạy `build\build_windows.ps1 -SkipInstaller`.
3. Chạy `build\make_update_patch.ps1 -Version "1.1.0"`.
4. Gói cập nhật nhỏ nằm tại `dist\LinkGrabStudio_Update_1.1.0.zip`.

Hoặc chạy workflow **Build LinkGrab 1.1 Update** trên GitHub. Workflow chỉ tạo
gói cập nhật ZIP và checksum, không tạo lại bộ cài đầy đủ.

## Cập nhật từ bản 1.0

Giải nén toàn bộ `LinkGrabStudio_Update_1.1.0.zip`, đóng ứng dụng rồi chạy
`CapNhat_1.1.cmd`. Trình cập nhật kiểm tra SHA-256, sao lưu file chương trình cũ
và tự khôi phục nếu thay thế thất bại. Lịch sử và thiết lập người dùng được giữ nguyên.

## Dữ liệu người dùng

Cấu hình, lịch sử và log được lưu trong `%LOCALAPPDATA%\LinkGrabStudio`. Video
được lưu vào thư mục người dùng chọn. Cập nhật hoặc cài đè không xóa lịch sử.

## Phạm vi sử dụng

Chỉ tải nội dung mà người dùng sở hữu hoặc được phép tải. Ứng dụng không phá
DRM, không lưu mật khẩu và không tự động đăng nội dung lên nền tảng.
