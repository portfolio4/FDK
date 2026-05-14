#pragma once

#include <array>
#include <cstddef>
#include <deque>
#include <expected>
#include <filesystem>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

struct whisper_context;
struct whisper_vad_context;

namespace afk::whisper {

struct StreamResult {
    // Current utterance, which may change as more audio arrives.
    std::string tentative_text;
    // Only text newly committed during this call; never repeats earlier commits.
    std::string committed_text;
};

// Stateful, single-owner transcription of mono 16 kHz little-endian PCM16.
// Calls run inference synchronously; use a worker before attaching to dialogue.
// Model paths are explicit. Construction may throw; stream/finish report inference
// failures through std::expected and reset stream state so it can be reused.
class WhisperSTT {
public:
    WhisperSTT(const std::filesystem::path& model, const std::filesystem::path& vad_model);
    ~WhisperSTT() = default;

    WhisperSTT(const WhisperSTT&) = delete;
    WhisperSTT& operator=(const WhisperSTT&) = delete;

    std::expected<StreamResult, std::string> stream(std::string_view audio_bytes);
    std::expected<StreamResult, std::string> finish();
    void reset();

private:
    static constexpr std::size_t frame_samples = 512;

    std::expected<std::string, std::string> transcribe();
    void clear_utterance();
    std::expected<void, std::string> process_frame(
        const std::array<float, frame_samples>& frame, StreamResult& result, bool update_tentative);
    std::expected<void, std::string> drain(StreamResult& result, bool update_tentative);

    std::unique_ptr<::whisper_context, void (*)(::whisper_context*)> model;
    std::unique_ptr<::whisper_vad_context, void (*)(::whisper_vad_context*)> vad;
    std::deque<float> pending;
    std::deque<float> preroll;
    std::vector<float> vad_history;
    std::vector<float> utterance;
    std::string tentative;
    std::size_t speech_samples = 0;
    std::size_t silence_samples = 0;
    std::size_t last_transcription_samples = 0;
    int pending_byte = -1;
    int threads;
};

} // namespace afk::whisper
