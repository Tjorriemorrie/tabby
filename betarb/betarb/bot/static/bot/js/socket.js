// Note that the path doesn't matter right now; any WebSocket
// connection gets bumped over to WebSocket consumers
socket = new WebSocket("ws://" + window.location.host);

socket.onmessage = function(e) {
    console.info(e.data);
    // $('#incoming').append('<p>' + e.data + '</p>');
};

socket.onopen = function() {
    // socket.send('init');
};

// Call onopen directly if socket is already open
if (socket.readyState == WebSocket.OPEN) socket.onopen();

