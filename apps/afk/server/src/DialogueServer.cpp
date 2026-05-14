#include <afk/websocket/DialogueServer.h>

#include <ixwebsocket/IXConnectionState.h>
#include <ixwebsocket/IXNetSystem.h>

#include <stdexcept>
#include <utility>

namespace afk::ws {

DialogueServer::DialogueServer(dialogue::DialogueSession& session, const std::string& host, int port)
    : session_(session), server_(port, host) {
    if (!ix::initNetSystem()) {
        throw std::runtime_error("Cannot initialize WebSocket networking");
    }
    server_.disablePerMessageDeflate();
    server_.setOnConnectionCallback([this](auto connection, auto state) {
        if (const auto socket = connection.lock()) {
            socket->setOnMessageCallback([this, connection, state](const ix::WebSocketMessagePtr& message) {
                if (const auto client = connection.lock()) {
                    OnMessage(state->getId(), *client, message);
                }
            });
        }
    });
}

void DialogueServer::OnMessage(const std::string& id, ix::WebSocket& socket,
                               const ix::WebSocketMessagePtr& message) {
    std::lock_guard lock(mutex_);
    if (message->type == ix::WebSocketMessageType::Open) {
        if (message->openInfo.uri != "/ws") {
            socket.close(1008, "WebSocket endpoint is /ws");
            return;
        }
        auto client = std::make_unique<SocketClient>(socket);
        if (session_.Open(id, client.get())) {
            clients_.emplace(id, std::move(client));
        }
    } else if (message->type == ix::WebSocketMessageType::Close
               || message->type == ix::WebSocketMessageType::Error) {
        session_.Close(id);
        clients_.erase(id);
    } else if (message->type == ix::WebSocketMessageType::Message && clients_.contains(id)) {
        if (message->binary) {
            session_.OnAudio(id, message->str);
        } else {
            session_.OnText(id, message->str, dialogue::Clock::now());
        }
    }
}

DialogueServer::~DialogueServer() {
    Stop();
    ix::uninitNetSystem();
}

void DialogueServer::Start() {
    if (started_) {
        return;
    }

    const auto [listening, error] = server_.listen();
    if (!listening) {
        throw std::runtime_error(error);
    }

    server_.start();
    started_ = true;
}

void DialogueServer::Stop() {
    // Never hold either service mutex while IX joins connection workers.
    if (started_) {
        server_.stop();
        started_ = false;
    }

    std::lock_guard lock(mutex_);
    for (const auto& [id, client] : clients_) {
        session_.Close(id);
    }
    clients_.clear();
}

} // namespace afk::ws
