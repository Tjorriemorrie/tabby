// Note that the path doesn't matter right now; any WebSocket
// connection gets bumped over to WebSocket consumers
socket = new WebSocket("ws://" + window.location.host + "/cats");

socket.onmessage = function(e) {
    $('body').append('<p>' + e.data + '</p>');
};

socket.onopen = function() {
    socket.send("mewauw");
};

// Call onopen directly if socket is already open
if (socket.readyState == WebSocket.OPEN) socket.onopen();
