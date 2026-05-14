#include <afk/whisper/WhisperSTT.h>

#include <whisper.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdio>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

namespace afk::whisper {

namespace {

constexpr std::size_t vad_history_samples = 16'384;
constexpr std::size_t preroll_samples = 3'200;
constexpr std::size_t minimum_speech_samples = 4'000;
constexpr std::size_t silence_samples_to_commit = 9'600;
constexpr std::size_t tentative_interval_samples = 16'000;
constexpr std::size_t maximum_utterance_samples = 15 * WHISPER_SAMPLE_RATE;

std::string trim(std::string text) {
    const auto nonspace = [](unsigned char ch) { return !std::isspace(ch); };

    text.erase(text.begin(), std::find_if(text.begin(), text.end(), nonspace));
    text.erase(std::find_if(text.rbegin(), text.rend(), nonspace).base(), text.end());

    return text;
}

void append_committed(std::string& destination, const std::string& text) {
    if (text.empty()) {
        return;
    }

    if (!destination.empty()) {
        destination += ' ';
    }

    destination += text;
}

} // namespace

WhisperSTT::WhisperSTT(const std::filesystem::path& model_path, const std::filesystem::path& vad_path)
    : model(nullptr, whisper_free),
      vad(nullptr, whisper_vad_free),
      threads(static_cast<int>(
          std::max(1u, std::min(4u, std::thread::hardware_concurrency())))) {
    if (!std::filesystem::is_regular_file(model_path)) {
        throw std::runtime_error("Whisper model not found: " + model_path.string());
    }

    if (!std::filesystem::is_regular_file(vad_path)) {
        throw std::runtime_error("VAD model not found: " + vad_path.string());
    }

    // Avoid VAD's per-frame informational logs drowning out transcription.
    whisper_log_set([](ggml_log_level level, const char* text, void*) {
        if (level >= GGML_LOG_LEVEL_WARN) {
            std::fputs(text, stderr);
        }
    }, nullptr);

    auto model_params = whisper_context_default_params();
    model_params.use_gpu = false;
    model.reset(whisper_init_from_file_with_params(model_path.string().c_str(), model_params));
    if (!model) {
        throw std::runtime_error("Cannot load Whisper model: " + model_path.string());
    }

    auto vad_params = whisper_vad_default_context_params();
    vad_params.use_gpu = false;
    vad_params.n_threads = 1;
    vad.reset(whisper_vad_init_from_file_with_params(vad_path.string().c_str(), vad_params));
    if (!vad) {
        throw std::runtime_error("Cannot load VAD model: " + vad_path.string());
    }
}

std::expected<std::string, std::string> WhisperSTT::transcribe() {
    if (speech_samples < minimum_speech_samples) {
        return std::string{};
    }

    auto params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads = threads;
    params.language = "en";
    params.no_context = true;
    params.no_timestamps = true;
    params.single_segment = true;

    params.print_progress = false;
    params.print_realtime = false;
    params.print_timestamps = false;

    params.suppress_nst = true;
    params.temperature_inc = 0.0f;

    std::vector<float> padded;
    const float* samples = utterance.data();
    int sample_count = static_cast<int>(utterance.size());

    if (sample_count < WHISPER_SAMPLE_RATE) {
        padded = utterance;
        padded.resize(WHISPER_SAMPLE_RATE, 0.0f);
        samples = padded.data();
        sample_count = static_cast<int>(padded.size());
    }

    if (whisper_full(model.get(), params, samples, sample_count) != 0) {
        return std::unexpected("Whisper transcription failed.");
    }

    std::string text;
    for (int index = 0; index < whisper_full_n_segments(model.get()); ++index) {
        text += whisper_full_get_segment_text(model.get(), index);
    }

    return trim(std::move(text));
}

void WhisperSTT::clear_utterance() {
    utterance.clear();
    tentative.clear();

    speech_samples = 0;
    silence_samples = 0;
    last_transcription_samples = 0;
}

std::expected<void, std::string> WhisperSTT::process_frame(
    const std::array<float, frame_samples>& frame, StreamResult& result, bool update_tentative) {
    // This whisper.cpp release resets VAD state per call. Supply rolling
    // history so the final probability retains context from preceding audio.
    vad_history.insert(vad_history.end(), frame.begin(), frame.end());
    if (vad_history.size() > vad_history_samples) {
        vad_history.erase(vad_history.begin(), vad_history.begin() + frame_samples);
    }

    if (!whisper_vad_detect_speech(vad.get(), vad_history.data(), static_cast<int>(vad_history.size()))) {
        return std::unexpected("VAD inference failed.");
    }

    const int count = whisper_vad_n_probs(vad.get());
    if (count == 0) {
        return std::unexpected("VAD returned no speech probabilities.");
    }

    const float probability = whisper_vad_probs(vad.get())[count - 1];
    const bool speech = probability >= (utterance.empty() ? 0.5f : 0.35f);

    if (speech) {
        if (utterance.empty()) {
            utterance.assign(preroll.begin(), preroll.end());
        }

        utterance.insert(utterance.end(), frame.begin(), frame.end());
        speech_samples += frame_samples;
        silence_samples = 0;
    } else if (!utterance.empty()) {
        utterance.insert(utterance.end(), frame.begin(), frame.end());
        silence_samples += frame_samples;
    }

    preroll.insert(preroll.end(), frame.begin(), frame.end());
    while (preroll.size() > preroll_samples) {
        preroll.pop_front();
    }

    if (!utterance.empty() && (silence_samples >= silence_samples_to_commit
                              || utterance.size() >= maximum_utterance_samples)) {
        const auto text = transcribe();
        if (!text) {
            return std::unexpected(text.error());
        }

        append_committed(result.committed_text, *text);
        clear_utterance();
    } else if (update_tentative && speech_samples >= minimum_speech_samples
               && utterance.size() - last_transcription_samples >= tentative_interval_samples) {
        auto text = transcribe();
        if (!text) {
            return std::unexpected(text.error());
        }

        tentative = std::move(*text);
        last_transcription_samples = utterance.size();
    }

    return {};
}

std::expected<void, std::string> WhisperSTT::drain(StreamResult& result, bool update_tentative) {
    while (pending.size() >= frame_samples) {
        std::array<float, frame_samples> frame;
        for (float& sample : frame) {
            sample = pending.front();
            pending.pop_front();
        }

        const auto processed = process_frame(frame, result, update_tentative);
        if (!processed) {
            return std::unexpected(processed.error());
        }
    }

    return {};
}

void WhisperSTT::reset() {
    clear_utterance();

    pending.clear();
    preroll.clear();
    vad_history.clear();
    pending_byte = -1;
}

std::expected<StreamResult, std::string> WhisperSTT::stream(std::string_view audio_bytes) {
    StreamResult result;

    for (const unsigned char byte : audio_bytes) {
        if (pending_byte < 0) {
            pending_byte = byte;
        } else {
            const int value = pending_byte | (static_cast<int>(byte) << 8);
            const int signed_value = value >= 0x8000 ? value - 0x10000 : value;

            pending.push_back(static_cast<float>(signed_value) / 32768.0f);
            pending_byte = -1;

            // Bound buffering even if a client sends a large WebSocket message.
            if (pending.size() == frame_samples) {
                const auto drained = drain(result, true);
                if (!drained) {
                    reset();
                    return std::unexpected(drained.error());
                }
            }
        }
    }

    result.tentative_text = tentative;
    return result;
}

std::expected<StreamResult, std::string> WhisperSTT::finish() {
    StreamResult result;

    if (!pending.empty()) {
        pending.resize(frame_samples, 0.0f);
        const auto drained = drain(result, false);
        if (!drained) {
            reset();
            return std::unexpected(drained.error());
        }
    }

    const auto text = transcribe();
    reset();

    if (!text) {
        return std::unexpected(text.error());
    }

    append_committed(result.committed_text, *text);
    return result;
}

} // namespace afk::whisper
