from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.websocket.manager import manager


router = APIRouter(tags=["WebSockets"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            message = await websocket.receive_json()
            await manager.broadcast("client_message", message)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
