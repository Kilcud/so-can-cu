# Sổ căn cứ 2.0 — Hướng dẫn chạy và phạm vi sản phẩm

## 1. Khởi động trên máy cá nhân

Yêu cầu Python 3.10 trở lên. Mở Terminal trong thư mục `So_can_cu`.

```bash
python -m pip install -r requirements-v2.txt
python app.py
```

Windows có thể dùng `py -3 -m pip install -r requirements-v2.txt` và `py -3 app.py`. Trình duyệt: **http://127.0.0.1:8765**. Máy chủ chỉ lắng nghe địa chỉ 127.0.0.1. Muốn dùng kho trống: `python app.py --no-demo`. Dữ liệu được lưu ở `local_data/so_can_cu.sqlite3` trừ khi chọn `--data-dir`.

Không cần Ollama để dùng chức năng cũ, nhập PDF/DOCX/TXT và tra cứu từ khóa.

## 2. Bật tìm kiếm ngữ nghĩa và RAG bằng mô hình cục bộ

Cài **Ollama** từ https://ollama.com/ và khởi chạy Ollama trên máy. Sau đó tải hai mô hình (việc tải cần Internet lần đầu):

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5:3b
```

Các mô hình cần bộ nhớ và dung lượng lưu trữ đáng kể. Khi Ollama chạy ở `http://127.0.0.1:11434`, vào mục **Ngữ nghĩa & RAG**. Chọn **Embedding ngữ nghĩa** để xem mô hình truy hồi. Chọn **Tra cứu từ khóa** khi không có mô hình embedding nhưng muốn dùng sinh câu trả lời bằng Ollama; mô hình trả lời vẫn cần phải chạy. Không có mô hình, chương trình báo `MODEL_UNAVAILABLE`; **không âm thầm dùng tra cứu từ khóa và đặt tên là tra cứu ngữ nghĩa**.

Bản v2 gửi request tới Ollama qua loopback. Mã không chứa lệnh gọi dịch vụ AI đám mây. Cần bảo đảm Ollama trên máy cũng được cấu hình đúng; đây chưa phải giải pháp bảo vệ dữ liệu mật.

## 3. Luồng nhập học liệu

- Vào **Nhập PDF/Word** → chọn PDF có lớp chữ, DOCX, hoặc TXT UTF-8 tối đa 8 MiB.
- Nhập tên, đơn vị cung cấp → **Nhập tệp vào kho**. Hệ thống tách văn bản và chia đoạn, đánh dấu nguồn là **chưa đối chiếu**.
- Vào **Nguồn học liệu** → đọc lại các đoạn. Chỉ ghi nhận đối chiếu nếu kiểm tra được nguồn gốc và nội dung. Bản tóm lược không được coi là nguyên văn văn bản pháp luật.
- Nguồn đã đối chiếu được phép tìm kiếm mặc định và sử dụng để RAG. Hệ thống không tự xác minh hiệu lực pháp lý.

PDF quét ảnh không có lớp chữ sẽ báo `NO_TEXT_LAYER`. Word không có số trang ổn định; ứng dụng ghi **số đoạn Word** và **vị trí hàng bảng**, không bịa số trang. Tài liệu dài có thể được chia thành nhiều nguồn có hậu tố "phần n".

## 4. Luồng tài liệu công khai

Chỉ khi người dùng bấm nút đồng bộ, hệ thống mới tải **một URL cụ thể** thuộc danh sách miền HTTPS cho phép: `vbpl.vn`, `vanban.chinhphu.vn`, `chinhphu.vn`, `moet.gov.vn`, `mps.gov.vn`. Không có web crawler và không có cập nhật định kỳ; không tự đánh giá được văn bản còn hiệu lực. Một số trang có xác thực, mã hóa nội dung động hoặc chặn truy cập tự động sẽ không nhập được; khi đó tải văn bản từ trang chính thức bằng trình duyệt rồi nhập tệp.

Chỉ nhập tài liệu bạn có quyền sử dụng. Không đưa tài liệu thuộc bí mật nhà nước, dữ liệu cá nhân chưa được phép hoặc nội dung bị hạn chế vào bản trình diễn.

## 5. Quy trình hỏi đáp có căn cứ

(1) Câu hỏi → (2) tra cứu 5 đoạn đã đối chiếu → (3) cung cấp đoạn nguồn và số thứ tự cho mô hình Ollama → (4) kiểm tra ký hiệu `[1]`, `[2]` trong câu trả lời → (5) hiển thị câu trả lời cùng nguồn, vị trí, phiên bản và đoạn văn đã dùng.

**Lưu ý:** Phần mềm chỉ đối chiếu xem số nguồn được viện dẫn có tồn tại trong danh sách; chưa chứng minh tất cả các mệnh đề đều được nguồn hỗ trợ. Kết luận của mô hình có thể sai. Với câu hỏi pháp lý, phải đọc văn bản gốc và cập nhật hiệu lực bằng nguồn có thẩm quyền.

## 6. Những gì đã kiểm thử và chưa kiểm thử

Đã kiểm tra 76 ca tự động gồm 63 ca của bản trước và 13 ca mới. 13 ca mới kiểm tra nhận DOCX, TXT, chặn URL sai, PDF không có lớp chữ, giới hạn tệp, API, tìm kiếm embedding mô phỏng và kiểm tra ký hiệu nguồn trong mô hình sinh mô phỏng. Không có kết quả đo **chất lượng ngữ nghĩa/RAG trên Ollama thực tế** trong môi trường biên soạn này. Không khẳng định sản phẩm đã thí điểm tại Học viện.

Giao diện hai trang mới được kiểm tra bằng bản trình diễn DOM của chính mã giao diện, với dữ liệu bootstrap lấy từ máy chủ; đây **không phải** bằng chứng về luồng Ollama thực sự trên trình duyệt. Kiểm thử HTTP mới được chạy trực tiếp với máy chủ.

## 7. Chưa triển khai trong bản này

Quản trị nhiều tài khoản, phân quyền vai trò, đăng nhập SSO, mã hóa dữ liệu tại chỗ, lưu vết độc lập có chữ ký, kiểm soát tài liệu mật, OCR ảnh quét, lịch đồng bộ nguồn, đánh giá hiệu lực văn bản tự động, reranker học sâu, đo RAGAS và triển khai trên máy chủ tập trung.

## 8. Các tệp mã mới

- `intake_v2.py`: kiểm tra định dạng, đọc DOCX/PDF/TXT/HTML, chia đoạn, URL công khai.
- `ai_v2.py`: tích hợp Ollama embed/generate, truy hồi vector cosine, lời đáp có ký hiệu nguồn.
- `static/ui_v2.js`: hai trang web **Nhập PDF/Word** và **Ngữ nghĩa & RAG**.
- `tests/test_v2_features.py`: 13 trường hợp kiểm thử nâng cấp.
- `requirements-v2.txt`: thư viện đọc tài liệu.

**Bản cũ giữ nguyên**: các trang tra cứu từ khóa, nguồn, hồ sơ, nhật ký và sao lưu. Không xóa các dữ liệu đang lưu; thay đổi mã chạy trên thư mục dữ liệu cũ vẫn giữ schema SQLite v1.
