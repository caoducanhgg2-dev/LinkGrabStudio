# Changelog

## 1.4.0

- Thêm nhận diện và tải video/Reels từ Facebook và Instagram.
- Hỗ trợ dán nhiều link Facebook/Instagram, xem trước rồi chọn video cần tải.
- Dùng chung lựa chọn chất lượng, định dạng, hàng đợi và tiến trình tải hiện có.
- Chuẩn hóa link chia sẻ và bỏ tham số theo dõi nhưng vẫn giữ ID video cần thiết.
- Mở rộng chống trùng riêng cho Facebook và Instagram.
- Hỗ trợ cookies.txt cho bài đăng mà tài khoản người dùng được phép xem.
- Thêm cookies riêng cho Douyin, Facebook và Instagram; app tự chọn theo từng link.
- Giữ file cookies chung làm phương án dự phòng và tương thích cài đặt phiên bản cũ.
- Giữ nguyên YouTube, TikTok, Douyin, lịch sử, cài đặt, backup và rollback.

## 1.3.6

- Thu gọn thanh chọn chế độ và rút ngắn chiều cao ô nhập từ khóa/link.
- Tự ẩn toàn bộ bộ chọn sau khi đọc xong video để bảng hiển thị nhiều dòng hơn.
- Thêm nút Hiện bộ chọn/Thu gọn bộ chọn ngay trên danh sách video.
- Thêm nút Thêm đã chọn cạnh bảng để vẫn thao tác được khi bộ chọn đang ẩn.
- Giảm chiều cao nhật ký hoạt động, ưu tiên không gian cho danh sách video.
- Giữ nguyên lịch sử, cookies, cài đặt, chống trùng, backup và rollback.

## 1.3.5

- Thiết kế lại khu vực link nguồn trong danh sách xem trước để không còn bị cắt khó đọc.
- Bảng hiển thị URL rút gọn; di chuột lên link để xem URL đầy đủ.
- Thêm thanh link nguồn đầy đủ theo video đang chọn, hỗ trợ chọn và sao chép trực tiếp.
- Thêm nút Sao chép, Mở link và thao tác nhấp đúp vào cột Link nguồn.
- Tiếp tục giữ nguyên lịch sử tải, cài đặt, chống trùng, backup và rollback của updater.

## 1.3.4

- Sửa lỗi Chrome/Edge vẫn chạy nền và khóa cơ sở dữ liệu cookies.
- Khi phát hiện khóa, app hỏi xác nhận trước khi đóng đúng trình duyệt đã chọn.
- Sau khi đóng trình duyệt, app tự thử lấy đăng nhập Douyin lại, không cần mở Task Manager.
- Thêm mã lỗi riêng cho khóa trình duyệt, lỗi DPAPI, cookies hết hạn và chưa đăng nhập.
- Giữ nguyên cookies cũ nếu lần làm mới thất bại; tiếp tục giữ lịch sử và chống trùng.

## 1.3.3

- Thêm đăng nhập Douyin ngay trong trang Cài đặt bằng phiên Chrome hoặc Edge.
- App tự lấy cookies từ hồ sơ trình duyệt gần nhất; không cần xuất cookies.txt thủ công.
- Thêm trạng thái `Đã đăng nhập Douyin`, `Cookies hết hạn` và hướng dẫn đăng nhập lại.
- Thêm nút Mở Douyin để đăng nhập, Kiểm tra đăng nhập và Làm mới cookies.
- Không lưu mật khẩu Douyin; phiên được lưu cục bộ trong thư mục dữ liệu ứng dụng.
- Giữ nguyên lịch sử tải, cài đặt, chống trùng, backup và rollback của updater.

## 1.3.2

- Sửa lỗi bản Windows báo `No module named expat; use SimpleXMLTreeBuilder instead` khi tìm video Douyin.
- Loại bỏ hoàn toàn phụ thuộc bộ phân tích XML/pyexpat khỏi chức năng dò URL Douyin.
- Đọc trực tiếp URL video từ phản hồi tìm kiếm nhẹ, giữ nguyên dịch từ khóa, bộ lọc và chống trùng.
- Tiếp tục phát hành dưới dạng ZIP cập nhật nhỏ, giữ lịch sử tải và cài đặt người dùng.

## 1.3.1

- Sửa lỗi tìm kiếm Douyin báo `Link này chưa được hỗ trợ`.
- Không còn đưa trang `/search/` của Douyin trực tiếp cho yt-dlp.
- Tìm URL video Douyin thật qua chỉ mục web, sau đó dùng yt-dlp đọc metadata từng video.
- Giữ dịch từ khóa Trung giản thể/phồn thể, lọc thời gian, xếp hạng và chống trùng.
- Hiển thị thông báo riêng khi không tìm thấy URL hoặc khi metadata cần cookies Douyin.

## 1.3.0

- Thêm tìm kiếm video Douyin theo từ khóa trong chế độ Theo từ khóa.
- Tự dịch từ khóa sang tiếng Trung giản thể hoặc phồn thể; Douyin mặc định dùng giản thể.
- Ghi từ khóa gốc và từ khóa sau dịch trong nhật ký hoạt động.
- Video đã tải vẫn tự bỏ chọn, nhưng có thể tích chọn lại để tải lại khi cần.
- Khi thêm video trùng, app hỏi rõ Bỏ qua hoặc Tải lại; tải lại buộc ghi đè file cũ.
- Giữ nguyên lịch sử tải, link nguồn, lọc thời gian, xếp hạng và hàng đợi hiện có.

## 1.2.0

- Thêm chế độ tìm video YouTube theo từ khóa, ví dụ `mukbang`.
- Chọn từ 1 đến 300 kết quả và tìm rộng tối đa 500 video để xếp hạng.
- Sắp xếp theo nhiều lượt xem nhất, mới nhất hoặc liên quan nhất.
- Lọc không giới hạn hoặc trong 1 tuần, 1 tháng, 3 tháng, 6 tháng và 1 năm.
- Giữ nguyên xem trước, link nguồn, lịch sử tải và tự bỏ chọn video trùng.

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
