# Sổ căn cứ 2.0 - bản chỉnh lý giao diện

Bản này thay đổi hình thức giao diện, cách ghi tài liệu hướng dẫn và ảnh chụp. Cơ chế nghiệp vụ, kho dữ liệu và tích hợp Ollama của phiên bản 2.0 được giữ nguyên.

## Khởi chạy

Cài các phụ thuộc trong requirements-v2.txt rồi chạy app.py. Trình duyệt mở http://127.0.0.1:8765. Xem README_V2.md để cài mô hình và cấu hình các chức năng nâng cấp. Không xóa local_data của bản đang dùng; sao lưu trước khi thay mã nguồn.

## Phông chữ tròn và tiếng Việt

Giao diện ưu tiên Nunito. Khi máy chưa cài phông này, chương trình chọn Comfortaa, Segoe UI hoặc Arial đang có trên máy. Gói mã nguồn không kèm tệp phông. Để có cùng hình thức Nunito trên các máy, chạy lệnh tùy chọn sau khi được phép kết nối Internet:

```bash
python3 tools/setup_ui_font.py --yes
```

Trên Windows dùng `py -3 tools/setup_ui_font.py --yes`. Công cụ chỉ tải phông và giấy phép từ kho Google Fonts, không gửi học liệu. Sau đó tải lại trang; các lần sử dụng tiếp theo đọc phông tại máy, không gọi CDN. Khi không có mạng, bỏ qua bước này; chương trình vẫn hoạt động với phông thay thế.

## Màu sắc

Màu chính là xanh lá đậm #006B3C, thanh điều hướng #083E2D, nền #F5F8F5. Đây là bảng màu thiết kế theo yêu cầu, không phải tuyên bố về bộ nhận diện đã được Học viện phê duyệt. Màu đỏ và vàng chỉ dùng cho lỗi, cảnh báo. Các biến nằm ở đầu static/styles.css.

## Phạm vi bằng chứng

Lần chỉnh lý chạy lại toàn bộ 76 phép thử nghiệp vụ và tích hợp của v2, bổ sung năm phép thử tài nguyên giao diện; 81/81 ca đạt. Kết quả và điều kiện thực hiện nằm tại evidence_layout/test_results.json. Dữ liệu, kết quả và ảnh trong evidence/ và evidence_v2/ được giữ như bằng chứng lịch sử, không tự thay bằng kết quả của lần chỉnh lý.

Chuỗi 21 tình huống thao tác giao diện kế thừa đạt; 40 ảnh được chụp lại, bổ sung hai ảnh về nhập tài liệu và thông báo Ollama chưa sẵn sàng. Môi trường chụp hạn chế điều hướng mạng trực tiếp của trình duyệt, vì vậy công cụ QA tải mã giao diện nguyên bản và chuyển tiếp yêu cầu API đến máy chủ cục bộ thực, rồi trả nguyên kết quả cho giao diện. Không coi đây là kiểm thử đầy đủ điều hướng mạng hoặc chính sách bảo mật của trình duyệt. Phông hiển thị trong ảnh là Comfortaa theo cơ chế dự phòng; sau khi người dùng cài Nunito, nét chữ sẽ theo phông ưu tiên.

Phản hồi embedding và sinh văn bản trong các ca tự động vẫn được mô phỏng. Ảnh RAG thể hiện đúng lỗi MODEL_UNAVAILABLE khi Ollama không hoạt động, không dựng một câu trả lời giả. Chưa có kết quả đánh giá chất lượng mô hình thực hoặc thí điểm tại Học viện.
