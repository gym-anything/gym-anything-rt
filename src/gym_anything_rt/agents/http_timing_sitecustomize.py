"""Client-side timings for Python requests to this attempt's HTTP endpoint."""
import http.client
import json
import os
import time
from urllib.parse import urlsplit


_endpoint = urlsplit(os.environ.get('GATEWAY_URL', ''))
_request = http.client.HTTPConnection.request
_response = http.client.HTTPConnection.getresponse
_read = http.client.HTTPResponse.read


def request(self, method, url, body=None, headers=None, *, encode_chunked=False):
    matched = self.host == _endpoint.hostname and self.port == _endpoint.port
    self._wcb_timing = None
    if matched:
        command = None
        try:
            command = json.loads(json.loads(body)['command'])
        except (ValueError, TypeError, KeyError):
            pass
        self._wcb_timing = (time.perf_counter_ns(), time.time_ns(), command)
    return _request(self, method, url, body, headers or {}, encode_chunked=encode_chunked)


def response(self):
    result = _response(self)
    result._wcb_timing = getattr(self, '_wcb_timing', None)
    result._wcb_bytes = 0
    return result


def read(self, amt=None):
    result = _read(self, amt)
    finished = time.perf_counter_ns()
    timing = getattr(self, '_wcb_timing', None)
    if timing is not None:
        self._wcb_bytes += len(result)
        if amt is None or self.isclosed() or self.length == 0:
            self._wcb_timing = None
            started, wall, command = timing
            record = dict(started_wall_ns=wall, total_ms=(finished-started)/1e6,
                          response_bytes=self._wcb_bytes, status=self.status,
                          command=command, pid=os.getpid(),
                          metric='HTTP request start to complete response body received')
            with open('/logs/http-client-timing.jsonl', 'a') as stream:
                stream.write(json.dumps(record) + '\n')
    return result


if _endpoint.hostname and _endpoint.port:
    http.client.HTTPConnection.request = request
    http.client.HTTPConnection.getresponse = response
    http.client.HTTPResponse.read = read
