#include <afk/whisper/SpeechWorker.h>
#include <fdk/log/Log.h>

#include <stdexcept>
#include <utility>

namespace afk::whisper {

SpeechWorker::SpeechWorker(WhisperSTT& whisper_stt, std::size_t max_audio_bytes)
    : whisper_stt_(whisper_stt), max_audio_bytes_(max_audio_bytes) {
    if (!max_audio_bytes_) {
        throw std::invalid_argument("Speech worker requires a positive queue limit");
    }

    worker_ = std::jthread([this](std::stop_token stop) { Run(stop); });
}

SpeechWorker::~SpeechWorker() {
    {
        std::lock_guard lock(mutex_);
        worker_.request_stop();
    }

    changed_.notify_all();
    worker_.join();
}

void SpeechWorker::ResetLocked(const std::string& session) {
    session_ = session;
    ++generation_;

    audio_.clear();
    results_.clear();
    queued_bytes_ = 0;
    reset_pending_ = true;

    changed_.notify_one();
}

void SpeechWorker::Reset(const std::string& session) {
    std::lock_guard lock(mutex_);
    ResetLocked(session);
}

void SpeechWorker::Audio(const std::string& session, const std::string& bytes) {
    std::lock_guard lock(mutex_);

    if (session != session_ || bytes.empty()) {
        return;
    }

    // Losing audio invalidates the whole utterance rather than splicing samples.
    // Bound command overhead as well as payload memory.
    if (bytes.size() > max_audio_bytes_ - queued_bytes_ || audio_.size() >= 256) {
        ResetLocked(session);
        return;
    }

    queued_bytes_ += bytes.size();
    audio_.push_back(bytes);

    changed_.notify_one();
}

std::optional<dialogue::Transcription> SpeechWorker::Poll() {
    std::lock_guard lock(mutex_);

    if (results_.empty()) {
        return std::nullopt;
    }

    auto result = std::move(results_.front());
    results_.pop_front();

    return result;
}

void SpeechWorker::Run(std::stop_token stop) {
    while (!stop.stop_requested()) {
        std::uint64_t generation = 0;
        std::string session;
        bool reset = false;
        std::string bytes;

        {
            std::unique_lock lock(mutex_);
            changed_.wait(lock, [&] {
                return stop.stop_requested() || reset_pending_ || !audio_.empty();
            });

            if (stop.stop_requested()) {
                return;
            }

            generation = generation_;
            session = session_;
            reset = std::exchange(reset_pending_, false);

            if (!reset) {
                bytes = std::move(audio_.front());
                audio_.pop_front();
                queued_bytes_ -= bytes.size();
            }
        }

        if (reset) {
            whisper_stt_.reset();
            continue;
        }

        // Whisper STT inference could take a long time, so we do this outside
        // the lock so other things can pass in more audio, or poll
        auto result = whisper_stt_.stream(bytes);

        {
            std::lock_guard lock(mutex_);

            if (generation != generation_) {
                continue;
            }

            if (!result) {
                LOG_ERR("Speech inference failed: {}", result.error());
                ResetLocked(session);
            } else if (!result->tentative_text.empty() || !result->committed_text.empty()) {
                if (results_.size() >= 256) {
                    ResetLocked(session);
                } else {
                    results_.push_back({session, std::move(result->tentative_text),
                                       std::move(result->committed_text)});
                }
            }
        }
    }
}

} // namespace afk::whisper
