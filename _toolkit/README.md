# Fun English Tales · Word Practice toolkit

Bộ công cụ tạo trang luyện từ vựng cho từng tập (https://funenglishtales.github.io/epNN/).
Dùng cùng skill "fun-english-tales-word-practice". Không chứa mật khẩu hay dữ liệu riêng tư.

- wp.py              — lệnh chính: prepare → (content.json) → build → test
- aligner.py         — khớp chữ với giọng bằng máy nhận dạng giọng nói offline (sherpa-onnx)
- setup_models.sh    — tải mô hình nghe (en) và đọc (tts) từ GitHub releases k2-fsa/sherpa-onnx
- page_template.html — giao diện trang Word Practice
- home_template.html — giao diện trang chủ (danh sách các tập)
