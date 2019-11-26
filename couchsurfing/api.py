from math import ceil

import requests
import hmac
from hashlib import sha1
import json

try:
    from urllib.parse import urlencode
except ImportError:
    # python2
    from urllib import urlencode

HEADERS = {
                "Accept": "application/json",
                "X-CS-Url-Signature": None,
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": "en;q=1",
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": """Dalvik/2.1.0 (Linux; U; Android 5.0.1;"""
                              """ Android SDK built for x86 Build/LSX66B) Couchsurfing"""
                              """/android/20141121013910661/Couchsurfing/3.0.1/ee6a1da"""
            }


class AuthError(Exception):
    """
    Authentication error
    """

    def __init__(self, arg):
        print('AuthError: ' + str(arg))


class RequestError(Exception):
    """
    Request error
    """
    pass


class Api(object):
    """ Base API class
    >>> api = Api("nzoakhvi@sharklasers.com", "qwerty")
    >>> api.uid
    1003669205
    >>> api.get_profile() # doctest: +ELLIPSIS
    {...}
    >>> api.get_profile_by_id('1003669205') # doctest: +ELLIPSIS
    {...}
    >>> api.get_friendlist('1003669205') # doctest: +ELLIPSIS
    {...}
    >>> api.get_references('1003669205', 'surf') # doctest: +ELLIPSIS
    {...}
    >>> api = Api("foo", "bar") # doctest: +IGNORE_EXCEPTION_DETAIL
    Traceback (most recent call last):
    ...
    AuthError
    """

    def get_url_signature(self, *msgs):
        msgs = ''.join(msg for msg in msgs if msg)
        if self.uid:
            key = '{}.{}'.format(self.private_key, self.uid)
        else:
            key = self.private_key
        return hmac.new(key.encode("utf-8"),
                        msgs.encode("utf-8"),
                        sha1).hexdigest()

    def __init__(self, username=None, password=None,
                 uid=None, access_token=None):
        self.api_url = "https://hapi.couchsurfing.com"
        self.private_key = "v3#!R3v44y3ZsJykkb$E@CG#XreXeGCh"

        self.uid = uid
        self._access_token = access_token
        self._session = requests.Session()
        if uid and access_token:
            self.uid = uid
            self._access_token = access_token

        else:
            assert (username and password)
            login_payload = {"actionType": "manual_login",
                             "credentials": {"authToken": password,
                                             "email": username}}

            signature = self.get_url_signature("/api/v3/sessions",
                                               json.dumps(login_payload))

            HEADERS['X-CS-Url-Signature'] = signature
            r = self._session.post(f'{self.api_url}/api/v3/sessions',
                                   headers = HEADERS,
                                   data=json.dumps(login_payload))

            if "sessionUser" not in r.json():
                raise AuthError(r.json())
            r.raise_for_status()
            self.uid = int(r.json()["sessionUser"]["id"])
            self._access_token = r.json()["sessionUser"]["accessToken"]

    def api_request(self, path, method='GET', params=None):
        assert self._access_token
        data = None
        if method != 'GET':
            data = json.dumps(params)
            params = None
        prepared = requests.Request(method.upper(),
                                    self.api_url + path,
                                    self._session.headers,
                                    params=params,
                                    data=data).prepare()

        signature = self.get_url_signature(prepared.path_url, data)
        prepared.headers['X-CS-Url-Signature'] = signature
        prepared.headers['X-Access-Token'] = self._access_token
        r = self._session.send(prepared)

        if r.status_code != 200:
            raise RequestError(r.text or r.reason)

        return r.json()

    def paginate_request(self, url, params, per_page=20, result_fn=None):
        page = 1
        pages = None
        params['perPage'] = per_page
        result_fn = result_fn or (lambda x: x['results'])
        while True:
            params['page'] = page
            result = self.api_request(url, params=params)
            if not pages:
                pages = float('inf')
                result_count = result.get('resultsCount')
                if result_count:
                    pages = ceil(result_count / per_page)
            result = result_fn(result)
            assert result, 'Pass "result_fn"'
            yield from result
            if page >= pages or len(result) < per_page:
                break
            page += 1

    def get_friendlist(self, uid=None):
        """
        Ask for friendlist for specific user
        """
        uid = uid or self.uid
        url = f'/api/v3.1/users/{uid}/friendList/friends'
        params = {'includeMeta': False}

        yield from self.paginate_request(url, params, result_fn=lambda x: x['friends'])

    def get_profile(self, uid=None):
        """
        Ask for specific user's profile
        """
        uid = str(uid or self.uid)

        return self.api_request(f'/api/v3/users/{uid}')

    def get_events(self, latlng):
        url = "/api/v3.2/events/search"
        params = {'latLng': latlng}

        yield from self.paginate_request(url, params, result_fn=lambda x: x)

    def get_visits(self, lat, lon):
        url = '/api/v3.2/visits/search'
        params = {'latLng': '{},{}'.format(lat, lon)}

        yield from self.paginate_request(url, params)

    def get_hosts(self, place_name, radius=10,  # todo use paginate_requests()
                  perpage=100, place_id=None, sort='best_match',
                  couch_status="yes,maybe",
                  filters=None):
        """
        Optionally pass filters as a dict with possible values:
            sleepingArrangements='privateRoom', minGuestsWelcome=2
            maxAge=100, minAge=18, hasReferences=1,
            gender=female, fluentLanguages="ukr,deu", isVerified=1,
            keyword="some-keyword"
        """
        params = {
            'page': 1,
            'perPage': perpage,
            'placeDescription': place_name,
            'placeId': place_id,
            'radius': radius,
            'sort': sort,
            'couchStatus': couch_status,
        }
        if filters:
            params.update(filters)
        query = urlencode(params)
        path = "/api/v3.2/users/search?%s" % query

        return self.api_request(path)

    def get_references(self, uid=None, type=None):
        """
        Ask for references

        type -- surf, host, other_and_friend
        """
        assert type in ['surf', 'host', 'other_and_friend']
        uid = uid or self.uid
        url = f'/api/v3/users/{uid}/references'
        params = {'relationshipType': type,
                  'includeReferenceMeta': True}

        yield from self.paginate_request(url, params)

    def join_hangouts(self, lat=None, lon=None):

        url = '/api/v3.1/hangouts/joined'
        params = {'includePastHangouts': True,
                  'latLng': '{},{}'.format(lat, lon)}

        yield from self.paginate_request(url, params, result_fn=lambda x: x['items'])

    def get_hangouts(self, lat=None, lon=None):
        path = "/api/v3.1/hangouts/search?perPage=" + str(25) + \
               "&lat=" + lat + "&lng=" + lon

        return self.api_request(path)

    def get_hangouts_new(self, lat=None, lon=None):
        url = "/api/v3.1/hangouts/search"
        params = {'lat': lat,
                  'lng': lon}

        return self.api_request(url, params=params)

    def request_hangout(self, id):
        path = "/api/v3.1/hangouts/requests"
        data = {
            "status": "pending",
            "type": "userStatus",
            "typeId": str(id)
        }

        return self.api_request(path, 'POST', params=data)

    def accept_hangout_request(self, id):
        path = "/api/v3.1/hangouts/requests" + str(id)
        path = "/api/v3.1/hangouts/requests"
        data = {
            "id": str(id),
            "status": "accept"
        }

        return self.api_request(path, 'put', data)


if __name__ == "__main__":

    # a = Api(uid='1264664', access_token='6df7f9944d35201cb6c2a75182cade0f')
    # r = list(a.get_friendlist())
    # r = list(a.get_visits2('55.823682', '37.559692'))
    # r = a.get_hangouts_new('55.823682', '37.559692')
    # r = a.request_hangout(r['items'][0]['id'])
    # r = a.accept_hangout_request(r['items'][0]['id'])
    # r = a.get_profile('2009856905')
    pass