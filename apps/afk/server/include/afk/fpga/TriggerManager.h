#pragma once

namespace afk {

class ThreadSafeAfkFpga;

class TriggerManager {
public:
    explicit TriggerManager(ThreadSafeAfkFpga& fpga);

    // Program during startup, before serving requests. Reactions precede conditions;
    // each command waits for its ACK. Failure throws and leaves earlier commands
    // programmed.
    void ProgramTriggers();

private:
    ThreadSafeAfkFpga& fpga_;
};

} // namespace afk
