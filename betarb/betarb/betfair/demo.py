from .api import APP_CERT, APP_KEY_DEV, APP_URL_LOGIN, USERNAME, PASSWORD
import requests


s = requests.Session()
s.cert = APP_CERT
s.headers.update({'X-Application': APP_KEY_DEV})


def login():
    """login to betfair"""
    print(f'cert = {APP_CERT}')
    print(f'key = {APP_KEY_DEV}')
    data = {
        'username': USERNAME,
        'password': PASSWORD,
    }
    res = s.post(APP_URL_LOGIN, data,
                 headers={'Content-Type': 'application/x-www-form-urlencoded'},
                 cert=('client-2048.crt', 'client-2048.key'))
    res.raise_for_status()
    res = res.json()
    print(res)
