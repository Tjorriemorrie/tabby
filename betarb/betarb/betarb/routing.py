from channels.routing import route
from bot.consumers import ws_message, ws_connect, ws_disconnect, msg_races

channel_routing = [
    route('websocket.connect', ws_connect),
    route('websocket.disconnect', ws_disconnect),
    route('websocket.receive', ws_message),
    route('race-messages', msg_races)
]
