#include <afk/dialogue/DialogueSession.h>

#include <afk/util/NormalizedFpgaText.h>
#include <fdk/log/Log.h>

#include <fstream>
#include <format>
#include <iterator>
#include <limits>
#include <stdexcept>
#include <utility>

namespace afk::dialogue {

namespace {

using Json = nlohmann::json;
constexpr std::uint16_t CODE_TRY_AGAIN_LATER = 1013;

std::optional<Json> StrToJson(const std::string& text) {
    auto response = Json::parse(text, nullptr, false);
    if (!response.is_object() || !response.contains("messages") || !response["messages"].is_array()) {
        return std::nullopt;
    }
    for (const auto& message : response["messages"]) {
        if (!message.is_object() || !message.contains("type") || !message["type"].is_string()) {
            return std::nullopt;
        }
    }
    return response["messages"];
}

Json MakeJsonReply(const std::string& type, const std::string& text) {
    return Json::array({{{"type", type}, {"msg", text}}});
}

} // namespace

DialogueSession::DialogueSession(AgentBackend& agent, FpgaBackend& fpga,
                                 SpeechBackend& speech, Options options)
    : agent_(agent), fpga_(fpga), speech_(speech), options_(options) {
    if (options_.pause_interval <= Clock::duration::zero() || !options_.max_queued_requests) {
        throw std::invalid_argument("Dialogue limits must be positive");
    }
}

std::string DialogueSession::Token() const {
    return std::format("{}:{}", *connection_id_, speech_generation_);
}

std::optional<std::string> DialogueSession::CurrentSession() {
    std::lock_guard lock(mutex_);
    if (!connection_id_) {
        return std::nullopt;
    }
    return Token();
}

std::expected<void, std::string> DialogueSession::Open(std::string connection_id, Client* client) {
    std::lock_guard lock(mutex_);
    if (!client) {
        return std::unexpected("A client is required");
    }

    if (connection_id_) {
        client->Close(CODE_TRY_AGAIN_LATER, "Only one kiosk conversation is allowed");
        return std::unexpected("Only one kiosk conversation is allowed");
    }

    connection_id_ = std::move(connection_id);
    client_ = client;
    ++speech_generation_;
    speech_.Reset(Token());
    return {};
}

void DialogueSession::Close(const std::string& connection_id) {
    std::lock_guard lock(mutex_);
    if (connection_id_ != connection_id) {
        return;
    }

    FinishCustomer();
    connection_id_.reset();
    client_ = nullptr;
}

void DialogueSession::Send(const Json& messages) {
    if (connection_id_) {
        client_->Send(Json{{"messages", messages}}.dump());
    }
}

void DialogueSession::SendError() {
    Send(MakeJsonReply("Conversation.addSystemMessage", "I couldn't process that. Please try again."));
}

void DialogueSession::OnText(const std::string& connection_id, const std::string& text, Time) {
    std::lock_guard lock(mutex_);
    if (connection_id_ != connection_id) {
        return;
    }

    const auto control = Json::parse(text, nullptr, false);
    if (!control.is_object()) {
        SendError();
        return;
    }

    if (control.value("type", Json()) == "request" && control.contains("text") && control["text"].is_string()) {
        auto request = control["text"].get<std::string>();
        if (request.empty() || queued_requests_.size() >= options_.max_queued_requests) {
            SendError();
            return;
        }
        queued_requests_.push_back(Request{.request_id = next_request_id_++, .text = std::move(request)});
    } else if (control.value("type", Json()) == "done_ordering") {
        FinishCustomer();
        const auto request_id = next_request_id_++;
        if (!agent_.Send(request_id,
                "the current customer is done. a new customer will arrive shortly. no response is required for this.")) {
            LOG_ERR("Failed to send customer handoff {} to agent", request_id);
        }
        agent_.DiscardPendingResponse();
        Send(Json::array({{{"type", "Cart.clear"}}}));
    } else {
        SendError();
    }
}

void DialogueSession::OnAudio(const std::string& connection_id, const std::string& bytes) {
    std::lock_guard lock(mutex_);
    if (connection_id_ == connection_id) {
        speech_.Audio(Token(), bytes);
    }
}

void DialogueSession::PollSpeech(Time now) {
    const auto transcription = speech_.Poll();
    if (!connection_id_ || !transcription || transcription->session != Token()) {
        return;
    }

    if (!transcription->tentative.empty()) {
        LOG_INFO("Tentative text: {}", transcription->tentative);
    }

    if (!transcription->committed.empty()) {
        LOG_INFO("Committed text: {}", transcription->committed);

        if (!transcript_.empty()) {
            transcript_ += ' ';
        }
        transcript_ += transcription->committed;
        pause_deadline_ = now + options_.pause_interval;
    }

    if (!transcription->committed.empty() || !transcription->tentative.empty()) {
        auto text = transcript_;
        if (transcription->committed.empty() && !transcription->tentative.empty()) {
            if (!text.empty()) {
                text += ' ';
            }
            text += transcription->tentative;
        }
        Send(MakeJsonReply("Conversation.setPendingUserMessage", text));
    }
}

void DialogueSession::FlushTranscript() {
    if (transcript_.empty()) {
        return;
    }

    Send(Json::array({{{"type", "Conversation.commitPendingUserMessage"}}}));
    auto text = std::exchange(transcript_, {});
    if (queued_requests_.size() < options_.max_queued_requests) {
        queued_requests_.push_back(Request{.request_id = next_request_id_++, .text = std::move(text)});
    } else {
        SendError();
    }
}

void DialogueSession::FinishCustomer() {
    transcript_.clear();
    pause_deadline_ = {};
    queued_requests_.clear();
    active_request_.reset();
    agent_.DiscardPendingResponse();
    ++speech_generation_;
    speech_.Reset(Token());
}

void DialogueSession::CheckIfRequestCompleted() {
    while (!active_request_ && !queued_requests_.empty()) {
        active_request_ = std::move(queued_requests_.front());
        queued_requests_.pop_front();
        const auto& current = *active_request_;
        const bool sent_to_agent = agent_.Send(current.request_id, current.text);
        if (!sent_to_agent) {
            LOG_ERR("Failed to send request {} to agent", current.request_id);
        }

        bool sent_to_fpga = false;

        const auto normalized = normalize_fpga_text(current.text);
        if (normalized.size() <= std::numeric_limits<std::uint16_t>::max()) {
            sent_to_fpga = fpga_.Send(current.request_id, normalized);
            if (!sent_to_fpga) {
                LOG_ERR("Failed to send request {} to FPGA", current.request_id);
            }
        }

        if (!sent_to_agent && !sent_to_fpga) {
            SendError();
            active_request_.reset();
        }
    }
}

void DialogueSession::Reply(const Json& messages) {
    active_request_.reset();
    agent_.DiscardPendingResponse();
    Send(messages);
}

void DialogueSession::PollAgent() {
    const auto result = agent_.Poll();
    if (!result) {
        return;
    }

    const auto& response = *result;
    LOG_INFO("Agent response: request_id={} turn_completed={} text={}",
             response.request_id, response.turn_completed, response.response);

    if (!active_request_ || response.request_id != active_request_->request_id || response.response.empty()) {
        return;
    }

    if (const auto messages = StrToJson(response.response)) {
        Reply(*messages);
    }
}

void DialogueSession::PollFpga() {
    // Drain stale packets even while idle, without monopolizing the caller.
    for (int count = 0; count < 8; ++count) {
        const auto reaction = fpga_.Poll();
        if (!reaction) {
            break;
        }

        LOG_INFO("FPGA response: request_id={} text={}", reaction->request_id, reaction->text);

        if (!active_request_ || reaction->request_id != active_request_->request_id) {
            continue;
        }

        const auto messages = StrToJson(reaction->text);
        if (messages) {
            Reply(*messages);
        }
    }
}

void DialogueSession::Poll(Time now) {
    std::lock_guard lock(mutex_);
    PollSpeech(now);
    if (connection_id_ && !transcript_.empty() && now >= pause_deadline_) {
        FlushTranscript();
    }

    PollAgent(); // Preserve agent-first behavior if both backends are ready.
    PollFpga();
    CheckIfRequestCompleted();
}

std::expected<std::string, std::string> DialogueSession::MakeSystemPrompt(
    const std::filesystem::path& prompt, const std::filesystem::path& menu) {
    const auto read = [](const auto& path) -> std::expected<std::string, std::string> {
        std::ifstream file(path);
        if (!file) {
            return std::unexpected(std::format("Cannot read kiosk resource: {}", path.string()));
        }
        return std::string(std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>());
    };
    const auto prompt_text = read(prompt);
    if (!prompt_text) {
        return std::unexpected(prompt_text.error());
    }
    const auto menu_text = read(menu);
    if (!menu_text) {
        return std::unexpected(menu_text.error());
    }
    return std::format("{}\n\n<menu_html source=\"frontend/kiosk.html\">\n{}\n</menu_html>\n",
                       *prompt_text, *menu_text);
}

} // namespace afk::dialogue
