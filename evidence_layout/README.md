# Bằng chứng của lần chỉnh lý giao diện

`test_results.json` và nhật ký kiểm thử ghi nhận 81/81 trường hợp đạt; năm ca mới nằm trong `tests/test_style_delivery.py`. Kết quả này không đánh giá mô hình ngôn ngữ thực.

`browser_results.json` ghi nhận 21/21 tình huống giao diện kế thừa. `screenshots/manifest.json` mô tả 40 ảnh chụp, đường dẫn và phạm vi sử dụng. `v2_ui_capture.json` ghi nhận việc nhập tệp DOCX bằng giao diện và lỗi thật khi chưa có Ollama; hai ảnh bổ sung là `41_v2_import.png` và `42_v2_rag_unavailable.png`.

Mã HTML, CSS và JavaScript được tải nguyên bản vào trình duyệt kiểm tra. Do hạn chế điều hướng mạng trong môi trường này, yêu cầu API được chuyển tiếp đến máy chủ cục bộ thật bằng công cụ QA; dữ liệu trả về không được sửa hoặc thay bằng kết quả dựng sẵn. Phương pháp này không kiểm tra đầy đủ điều hướng mạng hay chính sách an toàn của trình duyệt. Những kiểm tra HTTP độc lập có trong bộ unittest.

Phông sử dụng khi chụp là Comfortaa, theo cấu hình dự phòng; Nunito chưa được cài trong môi trường chụp. Không kèm tệp phông trong gói bàn giao. Công cụ `tools/setup_ui_font.py` là bước tải tùy chọn do người dùng chủ động thực hiện.

Chạy lại kiểm thử: `python tools/run_evidence.py --out evidence_layout --repeat 5`. Để tái lập ảnh, khởi động một kho trình diễn mới bằng app.py, chuẩn bị Playwright cùng Chromium rồi chạy `tools/browser_layout.cjs` và `tools/browser_layout_v2.cjs` với BASE_URL và CHROMIUM_EXECUTABLE phù hợp. Các thao tác trình diễn tạo dữ liệu, nên không chạy trên kho đang dùng cho công việc thật.