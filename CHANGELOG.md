# Changelog

## 1.1.3

- Sửa lỗi engine báo `no such option: --extract-flat` khi đọc kênh.
- Dùng tham số `--flat-playlist` tương thích với yt-dlp chính thức.
- Tự thử lại bằng chế độ đọc đầy đủ nếu engine cũ không hỗ trợ `--flat-playlist`.

## 1.1.2

- Sửa trình cập nhật có thể ghi đè nhầm một bản LinkGrab Studio khác trên máy.
- Khi không truyền đường dẫn, trình cập nhật sẽ yêu cầu chọn đúng thư mục chứa `LinkGrabStudio.exe`.
- Hiển thị rõ phiên bản 1.1.2 và chỉ dẫn mở chế độ Theo kênh.

## 1.1.1

- Sửa lỗi cú pháp dấu ngoặc kép trong trình cập nhật PowerShell.
- Chuyển thông báo của script sang ASCII để tương thích Windows PowerShell 5.1.
- Không thay đổi ứng dụng hoặc dữ liệu người dùng nếu cập nhật thất bại.

## 1.1.0

- Mở chế độ tải theo kênh cho YouTube, TikTok và Douyin.
- Lọc video trong khoảng 1 tuần đến 1 năm.
- Sắp xếp danh sách theo lượt xem cao nhất hoặc mới nhất.
- Thêm cột lượt xem, ngày đăng và link nguồn khi xem trước.
- Tự bỏ chọn video đã tải; ghi log và hiện hộp thoại khi phát hiện trùng.
- Lịch sử tải hiển thị URL nguồn đã lưu trong SQLite.
- Phát hành bằng gói cập nhật ZIP nhỏ có kiểm tra checksum, sao lưu và rollback.

## 1.0.0-preview.1

- Tạo giao diện desktop Windows tối theo bố cục tham khảo.
- Thêm nhận diện YouTube, TikTok và Douyin từ URL.
- Thêm xem trước thông tin video và playlist.
- Thêm tải MP4, MKV, MP3 và M4A với lựa chọn chất lượng.
- Thêm hàng đợi 1–4 luồng, mặc định 2 luồng.
- Thêm tiến trình, tốc độ, ETA, log và dừng tất cả.
- Thêm SQLite để lưu lịch sử và chống tải trùng.
- Thêm cookies.txt, phụ đề, thumbnail và metadata tùy chọn.
- Thêm build PyInstaller, Inno Setup và GitHub Actions cho Windows.
- Thêm cập nhật yt-dlp độc lập, xác minh SHA256 và rollback khi lỗi.
