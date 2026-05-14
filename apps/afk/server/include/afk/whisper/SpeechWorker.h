#pragma once

#include <afk/dialogue/Backends.h>
#include <afk/whisper/WhisperSTT.h>

#include <condition_variable>
#include <deque>
#include <mutex>
#include <thread>

namespace afk::whisper {

// WhisperSTT is owned by the caller and must outlive this worker. Only the
// worker calls it. Reset invalidates queued and in-flight results immediately.
class SpeechWorker final : public dialogue::SpeechBackend {
public:
    explicit SpeechWorker(WhisperSTT& whisper_stt, std::size_t max_audio_bytes = 1024 * 1024);
    ~SpeechWorker();

    void Audio(const std::string& session, const std::string& bytes) override;
    void Reset(const std::string& session) override;
    std::optional<dialogue::Transcription> Poll() override;

private:
    void Run(std::stop_token stop);
    void ResetLocked(const std::string& session);

    WhisperSTT& whisper_stt_;
    const std::size_t max_audio_bytes_;
    std::mutex mutex_;
    std::condition_variable changed_;
    std::string session_;
    std::uint64_t generation_ = 0;

    bool reset_pending_ = false;
    std::size_t queued_bytes_ = 0;
    std::deque<std::string> audio_;
    std::deque<dialogue::Transcription> results_;

    std::jthread worker_;
};

} // namespace afk::whisper
