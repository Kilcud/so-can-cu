> **Bản chỉnh lý giao diện và báo cáo:** đọc `README_GIAO_DIEN.md` trước. Giao diện ưu tiên Nunito, dùng tông xanh lá đậm; mã nghiệp vụ v2 được giữ nguyên. Bản bàn giao không kèm tệp phông. Các phần bên dưới lưu hướng dẫn và kết quả của bản nền để đối chiếu; hướng dẫn v2 nằm trong `README_V2.md`.

# PHIÊN BẢN 2.0 — XEM README_V2.md TRƯỚC KHI CHẠY

Bản v2 nhập PDF/DOCX dùng `requirements-v2.txt`. Hai mô hình ngữ nghĩa/RAG cần Ollama riêng. Nội dung dưới đây là hướng dẫn và các phép thử **bản nền 1.0**, lưu để đối chiếu lịch sử.

# Sổ căn cứ

Bản mẫu có giao diện web, phục vụ tra cứu học liệu, gắn đoạn nguồn với luận điểm và kiểm tra căn cứ trích dẫn. Ứng dụng dùng Python 3.10 trở lên, thư viện chuẩn và SQLite; không cần cài gói `pip` để chạy. Một người sử dụng thao tác bằng trình duyệt trên chính máy khởi động chương trình.

## 1. Khởi động

Giải nén toàn bộ gói vào thư mục có quyền ghi. Giữ nguyên cấu trúc tệp, mở cửa sổ lệnh tại thư mục chứa `app.py` và kiểm tra phiên bản Python.

**Windows** có Python Launcher:

```bat
py -3 --version
start.bat
```

Có thể dùng `py -3 app.py` thay cho tệp khởi động. Nếu máy chỉ nhận lệnh `python`, kiểm tra `python --version` rồi dùng `python app.py`.

**macOS hoặc Linux** có lệnh `python3`:

```sh
python3 --version
sh start.sh
```

Có thể dùng trực tiếp `python3 app.py`. Mở **http://127.0.0.1:8765** bằng trình duyệt, giữ cửa sổ lệnh đang chạy; nhấn `Ctrl+C` tại cửa sổ đó để dừng. Không mở riêng `static/index.html`. Kết quả kèm gói được đo trên Linux, Python 3.12.14; hướng dẫn Windows/macOS chưa đồng nghĩa đã kiểm thử trên các hệ điều hành ấy.

## 2. Chọn kho dữ liệu và cổng

```sh
python3 app.py --data-dir "./du_lieu_rieng" --no-demo --port 8766
```

Trên Windows, thay `python3` bằng `py -3`. Khi đổi cổng, mở địa chỉ tương ứng, chẳng hạn `http://127.0.0.1:8766`.

| Tùy chọn | Ý nghĩa |
|---|---|
| `--data-dir PATH` | Thư mục chứa `so_can_cu.sqlite3`; mặc định là `local_data` cạnh chương trình. |
| `--no-demo` | Không nạp bộ mẫu; dùng với thư mục mới để bắt đầu kho trống. |
| `--port N` | Cổng từ 1 đến 65535; mặc định 8765. |
| `--quiet` | Ẩn nhật ký truy cập HTTP trong cửa sổ lệnh. |

`--no-demo` không xóa dữ liệu đã có. Giữ tùy chọn này trong các lần chạy kho riêng nếu không muốn chương trình nạp mẫu. Mỗi thư mục dữ liệu là một kho riêng; không chạy hai tiến trình trên cùng kho. Máy chủ luôn nghe tại `127.0.0.1`, không có tùy chọn mở dịch vụ ra mạng.

## 3. Thực hành chức năng

1. Tạo hồ sơ, ghi phạm vi và thêm luận điểm thuộc loại nhận định thực tế, phân tích hoặc đề xuất.
2. Tra cứu từ khóa có dấu hoặc không dấu; có thể giới hạn nguồn và trạng thái đã đối chiếu.
3. Mở đoạn để đọc nội dung, vị trí và xuất xứ; chọn đúng hồ sơ, luận điểm rồi gắn căn cứ. Đoạn trích phải khớp một phần liên tục của đoạn lưu sau khi chuẩn hóa khoảng trắng.
4. Đọc kết quả kiểm tra. Nhận định thực tế thiếu căn cứ là lỗi; phân tích thiếu căn cứ là cảnh báo; đề xuất có thể chưa gắn căn cứ.
5. Xuất HTML, Markdown hoặc JSON. Cảnh báo còn tồn tại được giữ trong tệp xuất.

Nguồn nhập mới ở trạng thái chưa đối chiếu. Tạo phiên bản mới giữ nội dung cũ, đưa nguồn về nháp và cảnh báo các căn cứ dùng bản trước. Đối chiếu bản mới không tự cập nhật căn cứ cũ: người viết phải đọc lại, gắn căn cứ phù hợp và quyết định bỏ liên kết cũ.

## 4. Hiểu đúng dữ liệu mẫu

Kho ban đầu có **5 nguồn, 24 đoạn**: ba nguồn là học liệu **tóm lược** văn bản công khai; hai nguồn là nội dung thực hành tự biên soạn. Nhãn nguyên văn của học liệu tự biên soạn chỉ nói về chữ đã lưu, không biến nội dung ấy thành văn bản pháp luật. Phải mở bản gốc khi cần trích quy định chính xác. Hồ sơ mẫu có nhận định cố ý thiếu căn cứ để thử cảnh báo; đó không phải số liệu hiệu quả triển khai tại Học viện.

## 5. Thành phần gói

| Đường dẫn | Nội dung |
|---|---|
| `app.py`, `store.py` | Máy chủ HTTP, nghiệp vụ, SQLite. |
| `static/` | HTML, CSS, JavaScript của giao diện. |
| `data/` | Nguồn mẫu và hai bộ truy vấn đánh giá. |
| `tests/` | Kiểm thử nghiệp vụ và hợp đồng HTTP. |
| `tools/verify_backup.py` | Kiểm tra bản sao ZIP. |
| `tools/run_evidence.py` | Chạy kiểm thử, ghi kết quả đo. |
| `tools/browser_evidence.cjs` | Tái tạo luồng trình duyệt và ảnh chụp. |
| `docs/`, `evidence/` | Thuyết minh, hợp đồng API và bằng chứng kiểm tra. |
| `provenance/final_source_hashes.json` | SHA-256 của các tệp nguồn ổn định. |

`local_data/` được tạo khi chạy mặc định; dữ liệu người dùng không phải mã nguồn của sản phẩm.

## 6. Chạy kiểm thử

Tại thư mục chứa `app.py`:

```sh
python3 -m unittest discover -s tests -v
python3 tools/run_evidence.py --out evidence_rerun
```

Bộ thử có **43 ca nghiệp vụ và 20 ca HTTP**, tổng cộng 63. Kết quả bàn giao ghi tại `evidence/test_results.json`; bộ 30 truy vấn phát triển và 12 truy vấn giữ riêng được báo cáo riêng, không gộp thành chứng nhận chất lượng tìm kiếm nói chung. Các phép thử Python dùng thư mục dữ liệu tạm.

Thử trình duyệt là bước tùy chọn, cần Node.js, gói Playwright và Chromium ngoài ứng dụng. Sau khi chuẩn bị các thành phần đó, chạy `node tools/browser_evidence.cjs` với một máy chủ dùng **kho trình diễn riêng**. Script nhận `BASE_URL` và `CHROMIUM_EXECUTABLE`, tạo dữ liệu thử, ghi vào `evidence/`. Không cần các thành phần này để sử dụng sản phẩm hằng ngày.

## 7. Sao lưu và phục hồi

Vào **Nhật ký → Tải bản sao lưu**. ZIP gồm `so_can_cu.sqlite3`, `manifest.json`, `README.txt`. Giả sử tệp tải về được đặt tên `ban_sao.zip`:

```sh
python3 tools/verify_backup.py "ban_sao.zip"
```

Chỉ tiếp tục khi kết quả có `"valid": true` và lệnh kết thúc thành công. Công cụ kiểm tra thành phần, kích thước, SHA-256, SQLite, khóa ngoại và chuỗi nhật ký; bản kê không có chữ ký số.

Phục hồi vào **thư mục mới**, không ghi đè kho đang dùng:

```sh
mkdir phuc_hoi_01
python3 -m zipfile -e "ban_sao.zip" "phuc_hoi_01"
python3 app.py --data-dir "./phuc_hoi_01" --no-demo --port 8766
```

Đối chiếu nguồn, hồ sơ, luận điểm, căn cứ và cảnh báo trước khi tiếp tục công việc. Giữ nguyên kho cũ và ZIP. Không sao chép riêng tệp SQLite đang hoạt động để thay cho chức năng sao lưu.

## 8. Giới hạn và xử lý sự cố

Đây là bản mẫu một người dùng, chưa có tài khoản, phân quyền tập thể, OCR, nhập PDF tự động, mô hình ngôn ngữ hoặc xác định tự động tính đúng của nhận định. Tự đối chiếu không phải phê duyệt độc lập. Chuỗi băm hỗ trợ phát hiện bất nhất; người toàn quyền trên máy vẫn có thể sửa dữ liệu và dấu vết.

Nếu cổng bận, đổi `--port`. Nếu không mở được trang, kiểm tra cửa sổ chạy và địa chỉ. Nếu yêu cầu báo lỗi sau khi gửi, mở lại hồ sơ trước khi thử tạo lại để tránh bản trùng. Khi báo lỗi, ghi phiên bản Python, hệ điều hành, thao tác và mã lỗi; giữ bản sao dữ liệu liên quan.
