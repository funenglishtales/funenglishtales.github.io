#!/usr/bin/env bash
# Tải mô hình chạy offline cho Fun English Tales Word Practice (GitHub releases của k2-fsa/sherpa-onnx).
#   en   = máy NGHE giọng tiếng Anh (Parakeet)        — để khoá khớp chữ
#   vi   = máy NGHE giọng tiếng Việt (Zipformer)       — để khoá khớp chữ
#   tts  = máy NÓI tiếng Anh tự nhiên (Kokoro: Heart, Puck, Bella, Nova, Emma, George...) — chỉ cần khi tự tạo audio
# Dùng: bash setup_models.sh [en|vi|tts|all ...]   (mặc định: en vi). Có rồi thì bỏ qua.
set -e
WANT="${*:-en vi}"
DIR="${FET_MODELS:-$HOME/models}"
mkdir -p "$DIR"; cd "$DIR"
python3 -c "import sherpa_onnx" 2>/dev/null || pip install --break-system-packages -q sherpa-onnx
python3 -c "import soundfile" 2>/dev/null || pip install --break-system-packages -q soundfile
python3 -c "import onnxruntime" 2>/dev/null || pip install --break-system-packages -q onnxruntime
python3 -c "import scipy" 2>/dev/null || pip install --break-system-packages -q scipy
ASR=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models
TTS=https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models
get () {  # $1 = gốc tải, $2 = tên thư mục mô hình, $3 = file kiểm tra
  if [ -f "$2/$3" ]; then echo "ĐÃ CÓ: $2"; return; fi
  echo "ĐANG TẢI: $2 ..."
  curl -fsSL -m 1500 "$1/$2.tar.bz2" | tar xj
  [ -f "$2/$3" ] && echo "XONG: $2" || { echo "LỖI: không tải được $2"; exit 2; }
}
for w in $WANT; do
  case "$w" in
    en)  get $ASR sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8 tokens.txt ;;
    vi)  get $ASR sherpa-onnx-zipformer-vi-int8-2025-04-20 tokens.txt ;;
    tts) get $TTS kokoro-multi-lang-v1_0 voices.bin ;;
    all) get $ASR sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8 tokens.txt
         get $ASR sherpa-onnx-zipformer-vi-int8-2025-04-20 tokens.txt
         get $TTS kokoro-multi-lang-v1_0 voices.bin ;;
  esac
done
echo "MODELS_READY $DIR"
