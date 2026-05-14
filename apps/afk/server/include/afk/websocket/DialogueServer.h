#pragma once

#include <afk/dialogue/DialogueSession.h>
#include <ixwebsocket/IXWebSocketServer.h>

#include <map>
#include <memory>
#include <mutex>

namespace afk::ws {

// Owns the borrowed client adapters until their connection closes. The session
// must outlive this server. Stop joins callbacks before releasing the adapters.
// Call Start/Stop from the control thread, never from a connection callback.
class DialogueServer {
public:
    DialogueServer(dialogue::DialogueSession& session, const std::string& host, int port);
    ~DialogueServer();
    void Start();
    void Stop();

private:
    void OnMessage(const std::string& id, ix::WebSocket& socket,
                   const ix::WebSocketMessagePtr& message);

    class SocketClient final : public dialogue::Client
    {
    public:
        explicit SocketClient(ix::WebSocket& socket) : socket_(socket) {}

        void Send(const std::string& text) override {
            socket_.sendText(text);
        }

        void Close(std::uint16_t code, const std::string& reason) override {
            socket_.close(code, reason);
        }
    private:
        ix::WebSocket& socket_;
    };

    dialogue::DialogueSession& session_;
    std::mutex mutex_;
    std::map<std::string, std::unique_ptr<SocketClient>> clients_;
    ix::WebSocketServer server_;
    bool started_ = false;
};

} // namespace afk::ws
