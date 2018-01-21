rm -rf /var/tmp/django_cache
docker run --rm -d --name reddy -p 6379:6379 redis
docker run --rm -d --name haas  -p 5672:5672 -p 15672:15672 --hostname haashost --link reddy:redis rabbitmq:management
sleep 4
docker ps
sleep 4
celery -A betarb worker -l info -B --scheduler django_celery_beat.schedulers:DatabaseScheduler
