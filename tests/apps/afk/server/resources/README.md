`jfk.wav` is the public speech sample distributed with whisper.cpp v1.8.3:
https://github.com/ggml-org/whisper.cpp/blob/v1.8.3/samples/jfk.wav

Downloaded from:
https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.8.3/samples/jfk.wav

It is mono, 16 kHz, signed 16-bit PCM. The model test streams the first four
seconds in fragmented chunks, then adds silence. It checks for the word
"fellow" rather than requiring an exact transcript.

SHA-256: `59dfb9a4acb36fe2a2affc14bacbee2920ff435cb13cc314a08c13f66ba7860e`.
