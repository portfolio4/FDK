#include <afk/fpga/TriggerManager.h>

#include <afk/fpga/ThreadSafeAfkFpga.h>
#include <afk/fpga/Message.h>
#include <afk/util/NormalizedFpgaText.h>

#include <array>
#include <cstdint>
#include <cstring>
#include <format>
#include <stdexcept>
#include <string_view>

namespace afk {

namespace {

constexpr std::array<std::string_view, 4> reactions{
    R"({"messages":[{"type":"Cart.addItems","item_name":"Classic Cheeseburger","quantity":1},{"type":"Conversation.addSystemMessage","msg":"From the FPGA: One cheeseburger added"}]})",
    R"({"messages":[{"type":"Cart.addItems","item_name":"Sprite","quantity":1},{"type":"Conversation.addSystemMessage","msg":"From the FPGA: One sprite added"}]})",
    R"({"messages":[{"type":"Cart.addItems","item_name":"Bottled Water","quantity":1},{"type":"Conversation.addSystemMessage","msg":"From the FPGA: One bottled water added"}]})",
    R"({"messages":[{"type":"Cart.removeItems","item_name":"Sprite","quantity":1},{"type":"Conversation.addSystemMessage","msg":"From the FPGA: One sprite removed"}]})"
};

struct Condition {
    std::string_view pattern;
    std::uint8_t reaction_id;
};

constexpr std::array<Condition, 8> conditions{{
    {"get a classic cheeseburger", 0},
    {"get a sprite", 1},
    {"remove the sprite", 3},
    {"get a bottled water", 2},

    {"get one classic cheeseburger", 0},
    {"get the classic cheeseburger", 0},
    {"have one classic cheeseburger", 0},
    {"have a classic cheeseburger", 0},
}};

static_assert([] {
    for (const auto reaction : reactions) {
        if (reaction.size() > MAX_REACTION_PAYLOAD_SIZE) return false;
    }
    return true;
}());

} // namespace

TriggerManager::TriggerManager(ThreadSafeAfkFpga& fpga) : fpga_(fpga) {}

void TriggerManager::ProgramTriggers() {
    for (std::size_t id = 0; id < reactions.size(); ++id) {
        ProgramReaction reaction{
            .reaction_id = static_cast<std::uint8_t>(id),
            .reaction_len = static_cast<std::uint8_t>(reactions[id].size())
        };
        std::memcpy(reaction.payload, reactions[id].data(), reactions[id].size());

        if (const auto result = fpga_.program_reaction(reaction); !result) {
            throw std::runtime_error(std::format("ProgramReaction {} failed: {}", id, result.error().text()));
        }
    }

    for (std::size_t id = 0; id < conditions.size(); ++id) {
        const auto& configured = conditions[id];
        const auto pattern = afk::normalize_fpga_text(configured.pattern);
        if (pattern.size() > MAX_CONDITION_MSG_SIZE) {
            throw std::length_error(std::format(
                "Normalized FPGA trigger pattern exceeds {} bytes", MAX_CONDITION_MSG_SIZE));
        }

        ProgramCondition condition{
            .condition_id = static_cast<std::uint8_t>(id),
            .reaction_id = configured.reaction_id,
            .pattern_len = static_cast<std::uint8_t>(pattern.size())
        };
        std::memcpy(condition.payload, pattern.data(), pattern.size());

        if (const auto result = fpga_.program_condition(condition); !result) {
            throw std::runtime_error(std::format("ProgramCondition {} failed: {}", id, result.error().text()));
        }
    }
}

} // namespace afk
