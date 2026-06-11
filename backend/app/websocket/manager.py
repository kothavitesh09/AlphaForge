from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self.connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self.connections.discard(websocket)

    async def broadcast(self, event: str, payload: dict) -> None:
        disconnected = []
        for connection in self.connections:
            try:
                await connection.send_json({"event": event, "payload": payload})
            except RuntimeError:
                disconnected.append(connection)
        for connection in disconnected:
            self.disconnect(connection)


manager = WebSocketManager()
