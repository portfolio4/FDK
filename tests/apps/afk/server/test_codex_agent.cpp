// fake_codex_agent.cpp runs one hardcoded two-turn Codex conversation for
// this test, including initialization, thread creation, replies, and completion.
// Keep protocol details in that one fixture script rather than a test matrix.

#include <catch2/catch_all.hpp>

#include <afk/codex/CodexAgent.h>

#include <array>
#include <cstdint>
#include <string>
#include <thread>

TEST_CASE("CodexAgent runs a conversation across two turns", "[afk][codex][agent]") {
    afk::codex::CodexAgent agent("CodexAgent conversation test", AFK_FAKE_CODEX_AGENT_EXECUTABLE);

    struct Exchange {
        std::uint64_t id;
        std::string request;
        std::string response;
    };
    const std::array exchanges{
        Exchange{101, "Hello", "Hello! What would you like?"},
        Exchange{102, "One cheeseburger, please", R"({"messages":[{"type":"Cart.addItems","item_name":"Classic Cheeseburger","quantity":1}]})"},
    };

    for (const auto& exchange : exchanges) {
        CAPTURE(exchange.id, exchange.request);
        CHECK_FALSE(agent.HasPendingRequest());
        REQUIRE(agent.SendRequest(exchange.id, exchange.request));

        std::string response_text;
        bool completed = false;

        while (!completed) {
            const auto response = agent.PollResponse();
            INFO((response ? "" : response.error()));
            REQUIRE(response);

            if (!*response) {
                std::this_thread::yield();
                continue;
            }

            CHECK((**response).request_id == exchange.id);
            response_text += (**response).response;
            completed = (**response).turn_completed;
        }

        CHECK(response_text == exchange.response);
        CHECK_FALSE(agent.HasPendingRequest());
    }

    REQUIRE(agent.SendRequest(103, "Malformed protocol test"));
    while (true) {
        const auto response = agent.PollResponse();
        if (!response) {
            CHECK(response.error() == "Codex turn/start reply must contain a string turn ID.");
            break;
        }
        REQUIRE_FALSE(*response);
        std::this_thread::yield();
    }

    CHECK(agent.HasPendingRequest());
    agent.DiscardPendingResponse();
    CHECK_FALSE(agent.HasPendingRequest());
    REQUIRE(agent.SendRequest(104, "Fresh request"));
    std::string fresh_response;
    while (agent.HasPendingRequest()) {
        const auto response = agent.PollResponse();
        REQUIRE(response);
        if (*response) {
            CHECK((**response).request_id == 104);
            fresh_response += (**response).response;
        } else {
            std::this_thread::yield();
        }
    }
    CHECK(fresh_response == "Fresh reply");

    REQUIRE(agent.SendRequest(105,
        "the current customer is done. a new customer will arrive shortly. no response is required for this."));
    agent.DiscardPendingResponse();
    CHECK_FALSE(agent.HasPendingRequest());
}
