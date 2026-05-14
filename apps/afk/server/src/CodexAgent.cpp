#include <afk/codex/CodexAgent.h>

#include <format>
#include <stdexcept>
#include <thread>
#include <utility>

namespace afk::codex {

namespace {

nlohmann::json MakeInitializeRpc() {
    return {
        {"method", "initialize"},
        {"params", {
            {"clientInfo", {
                {"name", "codex_agent"},
                {"version", "0.1.0"}
            }}
        }}
    };
}

nlohmann::json MakeThreadStartRpc() {
    return {
        {"method", "thread/start"},
        {"params", {
            {"cwd", AFK_CODEX_CWD},
            {"sandbox", "read-only"},
            {"approvalPolicy", "never"},
            {"ephemeral", true}
        }}
    };
}

} // namespace

CodexAgent::CodexAgent(std::string system_prompt, std::string executable)
    : process_(std::move(system_prompt), std::move(executable)) {
    const auto started = process_.Start();
    if (!started) {
        throw std::runtime_error(started.error());
    }

    const auto initialized = BlockingInitializationRpc(MakeInitializeRpc());
    if (!initialized) {
        throw std::runtime_error(initialized.error());
    }

    const auto sent = process_.Send(Json{
        {"method", "initialized"},
        {"params", Json::object()}
    }.dump());
    if (!sent) {
        throw std::runtime_error(sent.error());
    }

    const auto thread = BlockingInitializationRpc(MakeThreadStartRpc());
    if (!thread) {
        throw std::runtime_error(thread.error());
    }

    thread_id_ = thread->at("thread").at("id").get<std::string>();
}

std::expected<CodexAgent::Json, std::string> CodexAgent::BlockingInitializationRpc(Json request) {
    const int id = next_id_++;
    request["id"] = id;
    const auto sent = process_.Send(request.dump());
    if (!sent) {
        return std::unexpected(sent.error());
    }

    const auto deadline = Clock::now() + std::chrono::seconds(10);
    while (Clock::now() < deadline) {
        auto response = process_.PollResponse();
        if (!response) {
            return std::unexpected(response.error());
        }

        if (!*response) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }

        const auto message = Json::parse(**response, nullptr, false);
        if (!message.is_object()) {
            return std::unexpected("Codex returned an invalid protocol message.");
        }

        if (!message.contains("method") && message.value("id", Json()) == id) {
            if (message.contains("error")) {
                return std::unexpected(std::format("Codex: {}", message["error"].dump()));
            }

            if (!message.contains("result")) {
                return std::unexpected("Codex initialization reply is missing result.");
            }
            return message["result"];
        }
    }

    return std::unexpected("Codex initialization timed out.");
}

std::expected<void, std::string> CodexAgent::SendRequest(std::uint64_t request_id, const std::string& request) {
    if (request.empty()) {
        return std::unexpected("Request cannot be empty.");
    }

    if (pending_) {
        return std::unexpected("Codex agent already has an active request.");
    }

    auto sent = process_.Send(Json{
        {"id", request_id},
        {"method", "turn/start"},
        {"params", {
            {"threadId", thread_id_},
            {"input", Json::array({
                {
                    {"type", "text"},
                    {"text", request}
                }
            })}
        }}
    }.dump());
    if (sent) {
        pending_ = Pending{request_id, {}};
    }

    return sent;
}

void CodexAgent::DiscardPendingResponse() {
    pending_.reset();
}

std::expected<std::optional<CodexAgent::Response>, std::string> CodexAgent::PollResponse() {
    if (!pending_) {
        return std::nullopt;
    }

    auto response = process_.PollResponse();
    if (!response) {
        return std::unexpected(response.error());
    }

    if (!*response) {
        return std::nullopt;
    }

    const auto message = Json::parse(**response, nullptr, false);
    if (!message.is_object()) {
        return std::unexpected("Codex returned an invalid protocol message.");
    }

    const auto params = message.value("params", Json::object());
    if (!params.is_object()) {
        return std::unexpected("Codex protocol params must be an object.");
    }
    if (params.contains("threadId") && !params["threadId"].is_string()) {
        return std::unexpected("Codex protocol threadId must be a string.");
    }
    if (params.contains("threadId") && params["threadId"] != thread_id_) {
        return std::nullopt;
    }

    if (!message.contains("method")) {
        if (message.value("id", Json()) != pending_->request_id) {
            return std::nullopt;
        }

        if (message.contains("error")) {
            // A matching RPC error rejects turn/start; no turn was accepted.
            pending_.reset();
            return std::unexpected(std::format("Codex: {}", message["error"].dump()));
        }

        if (!message.contains("result") || !message["result"].is_object()
            || !message["result"].contains("turn") || !message["result"]["turn"].is_object()
            || !message["result"]["turn"].contains("id")
            || !message["result"]["turn"]["id"].is_string()) {
            return std::unexpected("Codex turn/start reply must contain a string turn ID.");
        }
        pending_->turn_id = message["result"]["turn"]["id"].get<std::string>();
        return std::nullopt;
    }

    // Only the matching RPC reply establishes the pending turn ID. Drop all
    // notifications until then, including notifications from discarded turns.
    if (pending_->turn_id.empty()) {
        return std::nullopt;
    }

    if (!message["method"].is_string()) {
        return std::unexpected("Codex protocol method must be a string.");
    }
    const auto method = message["method"].get<std::string>();
    std::string turn_id;
    if (method == "turn/started" || method == "turn/completed") {
        const auto turn = params.value("turn", Json::object());
        if (!turn.is_object() || (turn.contains("id") && !turn["id"].is_string())) {
            return std::unexpected("Codex protocol turn must be an object with a string ID.");
        }
        turn_id = turn.value("id", std::string{});
    } else {
        if (params.contains("turnId") && !params["turnId"].is_string()) {
            return std::unexpected("Codex protocol turnId must be a string.");
        }
        turn_id = params.value("turnId", std::string{});
    }
    if (turn_id != pending_->turn_id) {
        return std::nullopt;
    }

    if (message.contains("error")) {
        return std::unexpected(std::format("Codex: {}", message["error"].dump()));
    }

    if (method == "error") {
        // Runtime errors do not finish the turn; keep polling for completion.
        if (!params.contains("error")) {
            return std::unexpected("Codex error notification is missing error.");
        }
        return std::unexpected(std::format("Codex: {}", params["error"].dump()));
    }

    if (method == "item/completed") {
        if (!params.contains("item") || !params["item"].is_object()) {
            return std::unexpected("Codex item/completed notification must contain an item object.");
        }
        const auto& item = params["item"];
        if (item.contains("type") && !item["type"].is_string()) {
            return std::unexpected("Codex item type must be a string.");
        }
        if (item.value("type", "") != "agentMessage" || item.value("phase", Json()) == "commentary") {
            return std::nullopt;
        }

        if (!item.contains("text") || !item["text"].is_string()) {
            return std::unexpected("Codex agentMessage must contain string text.");
        }
        return Response{pending_->request_id, item["text"].get<std::string>(), false};
    }

    if (method == "turn/completed") {
        const auto& turn = params["turn"];
        if (turn.contains("status") && !turn["status"].is_string()) {
            return std::unexpected("Codex turn status must be a string.");
        }
        const auto request_id = pending_->request_id;
        pending_.reset();
        if (turn.value("status", "") != "completed") {
            return std::unexpected(std::format("Codex turn {}: {}", turn.value("status", "failed"),
                turn.value("error", Json()).dump()));
        }

        return Response{request_id, {}, true};
    }

    return std::nullopt;
}

} // namespace afk::codex
