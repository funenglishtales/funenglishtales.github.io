# Fun English Tales · Word Practice toolkit

Tools that build the vocabulary practice page for each episode (https://funenglishtales.github.io/epNN/).
No passwords or private data.

- wp.py              — main command: prepare → (content.json) → build → test
- aligner.py         — aligns text with speech using an offline speech recognizer (sherpa-onnx)
- setup_models.sh    — downloads the recognizer (en) and TTS (tts) models from GitHub releases k2-fsa/sherpa-onnx
- page_template.html — Word Practice page layout
- home_template.html — home page layout (episode list)
