import logging

from channels import Channel

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def meauw():
    """5 second test"""
    Channel('chat-messages').send({
        'room': 'cats',
        'message': 'auto celery',
    })
    logger.info('!@# MEAUW !@#')

