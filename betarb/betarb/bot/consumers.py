import logging

from channels import Group, Channel
from channels.sessions import channel_session

logger = logging.getLogger(__name__)


@channel_session
def ws_connect(message):
    """client connects"""
    room = message.content['path'].strip('/')
    message.channel_session['room'] = 'cats'
    logger.info(f'NEW ROOM = {room}')
    Group(f'chat-{room}').add(message.reply_channel)
    message.reply_channel.send({'accept': True})


@channel_session
def ws_disconnect(message):
    """client leaves"""
    Group(f'chat-{message.channel_session["room"]}').discard(message.reply_channel)


@channel_session
def ws_message(message):
    """Sends message to group"""
    Channel('chat-messages').send({
        'room': message.channel_session['room'],
        'message': message['text'],
    })


def msg_consumer(message):
    room = message.content['room']
    # save to django
    Group(f'chat-{room}').send({
        'text': message.content['message']
    })
