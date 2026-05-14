# AI Food Kiosk

[Project Page](https://portfolio4.github.io/ai-kiosk.html)

## Runtime requirements

Running AI Food Kiosk requires a configured `codex` executable on `PATH`, a
microphone, and a browser supporting AudioWorklet and speech synthesis.

Download both models from Hugging Face and place them in
`apps/afk/whisper/models/` before building:

- Whisper: [ggml-base.en.bin](https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin)
- Silero VAD: [ggml-silero-v6.2.0.bin](https://huggingface.co/ggml-org/whisper-vad/resolve/main/ggml-silero-v6.2.0.bin)

The build copies them into `mount-afk/models/`.

## Build and run

Build and program the FPGA (Vivado must be on `PATH`):

```sh
python3 build.py --platform fpga --directory apps/afk/fpga --mode release
python3 run.py --platform fpga --directory apps/afk/fpga --mode release
```

Build and run the C++ server in release mode:

```sh
python3 build.py --platform host --target afk_host --mode release
python3 run.py --platform host --target afk_host --mode release -- build_release/host/mount-afk /dev/ttyUSB1
```

## How It Works

The user speaks into a microphone, and the frontend sends the audio to the server.

The server converts the audio bytes to text, then feeds the text into both an
LLM agent and an FPGA trigger matcher.

The LLM agent has a system prompt instructing it to act like a restaurant worker
and take orders. The LLM may take a few seconds to respond.

The FPGA trigger matcher is configured to match predefined ordering phrases
and can only return predefined responses. However, the FPGA responds
much faster than the LLM.

An arbitration algorithm accepts the first valid response for each request.
If the FPGA responds first, its action is applied and the LLM agent's later
response is suppressed. If the FPGA does not respond because its matcher
doesn't recognize the request, then the LLM agent's later response will be
sent to the user.


### Example 1

If the user says "Can I get a classic cheeseburger?", this will match against
an FPGA trigger "get a classic cheeseburger" and the FPGA will quickly
respond with "From the FPGA: One cheeseburger added". The LLM may also respond later with
"Okay, I added a cheeseburger to your order", but that response will be suppressed.

### Example 2

If the user says "What's my total bill?", this will not match against any
FPGA trigger (nor does the FPGA have logic to calculate the total bill
anyway). So the FPGA will not respond, and later the LLM will respond
with the user's total bill.

