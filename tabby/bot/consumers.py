import json
import logging

from channels import Group, Channel
from channels.sessions import channel_session


logger = logging.getLogger(__name__)


@channel_session
def ws_connect(message):
    """client connects"""
    Group('clients').add(message.reply_channel)
    message.reply_channel.send({'accept': True})


@channel_session
def ws_disconnect(message):
    """client leaves"""
    Group('clients').discard(message.reply_channel)


@channel_session
def ws_message(message):
    """Receiving a message from a client"""
    if message['text'] == 'init':
        pass
    else:
        Group('races').send({
            'type': 'other',
            'text': f'Unknown text: {message["text"]}',
        })


def msg_races(message):
    """Sends message to group"""
    Group('clients').send({
        'text': json.dumps({
            'channel': 'races',
            'type': message.content['type'],
            'races': message.content['races'],
        }, default=str)
    })
