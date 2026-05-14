// Codex protocol emulation for test_codex_agent.cpp's hardcoded conversation.
#include <nlohmann/json.hpp>

#include <array>
#include <iostream>
#include <stdexcept>
#include <string>

using Json = nlohmann::json;

namespace {

Json read_conversation_request(const std::string& method) {
    std::string line;
    if (!std::getline(std::cin, line)) {
        throw std::runtime_error("Conversation ended before " + method);
    }

    const auto request = Json::parse(line);
    if (request.at("method") != method) {
        throw std::runtime_error("Expected conversation method " + method);
    }

    return request;
}

void send_conversation_message(const Json& message) {
    std::cout << message.dump() << '\n' << std::flush;
}

void run_codex_conversation() {
    const auto initialize = read_conversation_request("initialize");
    send_conversation_message({{"id", initialize.at("id")}, {"result", Json::object()}});

    read_conversation_request("initialized");
    const auto thread = read_conversation_request("thread/start");
    const auto& thread_params = thread.at("params");
    if (thread_params.at("sandbox") != "read-only" || thread_params.at("approvalPolicy") != "never"
        || thread_params.at("ephemeral") != true) {
        throw std::runtime_error("Unexpected conversation thread configuration");
    }

    send_conversation_message({
        {"id", thread.at("id")}, {"result", {{"thread", {{"id", "conversation-thread"}}}}}
    });

    struct Exchange {
        std::string request;
        std::string response;
    };
    const std::array exchanges{
        Exchange{"Hello", "Hello! What would you like?"},
        Exchange{"One cheeseburger, please", R"({"messages":[{"type":"Cart.addItems","item_name":"Classic Cheeseburger","quantity":1}]})"},
    };

    int turn_number = 0;
    for (const auto& exchange : exchanges) {
        const auto request = read_conversation_request("turn/start");
        const auto& params = request.at("params");
        if (params.at("threadId") != "conversation-thread"
            || params.at("input").at(0).at("type") != "text"
            || params.at("input").at(0).at("text") != exchange.request) {
            throw std::runtime_error("Unexpected conversation request");
        }

        const auto turn_id = "conversation-turn-" + std::to_string(++turn_number);
        send_conversation_message({
            {"id", request.at("id")}, {"result", {{"turn", {{"id", turn_id}}}}}
        });
        send_conversation_message({
            {"method", "item/completed"}, {"params", {
                {"threadId", "conversation-thread"}, {"turnId", turn_id},
                {"item", {{"type", "agentMessage"}, {"phase", "final_answer"}, {"text", exchange.response}}}
            }}
        });
        send_conversation_message({
            {"method", "turn/completed"}, {"params", {
                {"threadId", "conversation-thread"}, {"turn", {{"id", turn_id}, {"status", "completed"}}}
            }}
        });
    }

    const auto malformed_request = read_conversation_request("turn/start");
    send_conversation_message({{"id", malformed_request.at("id")}, {"result", nullptr}});

    const auto fresh_request = read_conversation_request("turn/start");
    send_conversation_message({
        {"id", malformed_request.at("id")}, {"result", {{"turn", {{"id", "discarded-turn"}}}}}
    });
    send_conversation_message({
        {"id", fresh_request.at("id")}, {"result", {{"turn", {{"id", "fresh-turn"}}}}}
    });
    send_conversation_message({
        {"method", "item/completed"}, {"params", {
            {"turnId", "discarded-turn"}, {"item", {{"type", "agentMessage"}, {"text", "Stale reply"}}}
        }}
    });
    send_conversation_message({
        {"method", "item/completed"}, {"params", {
            {"turnId", "fresh-turn"}, {"item", {{"type", "agentMessage"}, {"text", "Fresh reply"}}}
        }}
    });
    send_conversation_message({
        {"method", "turn/completed"},
        {"params", {{"turn", {{"id", "fresh-turn"}, {"status", "completed"}}}}}
    });

    const auto handoff = read_conversation_request("turn/start");
    if (handoff.at("params").at("threadId") != "conversation-thread"
        || handoff.at("params").at("input").at(0).at("text") !=
            "the current customer is done. a new customer will arrive shortly. no response is required for this.") {
        throw std::runtime_error("Expected the original customer handoff prompt on the same thread");
    }
    send_conversation_message({
        {"id", handoff.at("id")}, {"result", {{"turn", {{"id", "handoff-turn"}}}}}
    });
}

} // namespace

int main() {
    try {
        run_codex_conversation();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
