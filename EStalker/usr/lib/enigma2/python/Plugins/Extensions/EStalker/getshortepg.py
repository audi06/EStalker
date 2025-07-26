#!/usr/bin/python
# -*- coding: utf-8 -*-

from twisted.internet import reactor
from twisted.web.client import Agent, readBody
from twisted.web.http_headers import Headers
import json
import sys
import gzip
import io
import hashlib

from . import estalker_globals as glob
from .utils import get_local_timezone

try:
    from twisted.web.client import BrowserLikePolicyForHTTPS
    contextFactory = BrowserLikePolicyForHTTPS()
except ImportError:
    from twisted.web.client import WebClientContextFactory
    contextFactory = WebClientContextFactory()


class EStalker_EPG_Short:
    def __init__(self, visible_ids, done_callback=None):
        self.done_callback = done_callback
        self.visible_ids = visible_ids
        self.epg_data = []
        self.responses_received = 0
        self.total_requests = len(visible_ids)
        self.agent = Agent(reactor, contextFactory=contextFactory)
        self.prepare()

    def prepare(self):
        timezone = get_local_timezone()
        token = glob.active_playlist["playlist_info"]["token"]
        domain = str(glob.active_playlist["playlist_info"].get("domain", "")).rstrip("/")
        mac = glob.active_playlist["playlist_info"].get("mac", "").upper()
        self.portal = glob.active_playlist["playlist_info"].get("portal", None)

        sn = hashlib.md5(mac.encode()).hexdigest().upper()[:13]
        adid = hashlib.md5((sn + mac).encode()).hexdigest()

        # Base headers
        base_headers = {
            b"Accept": [b"*/*"],
            b"User-Agent": [b"Mozilla/5.0 (QtEmbedded; U; Linux; C) AppleWebKit/533.3 (KHTML, like Gecko) MAG250 stbapp ver: 2 rev: 369 Safari/533.3"],
            b"Accept-Encoding": [b"gzip, deflate"],
            b"X-User-Agent": [b"Model: MAG254; Link: WiFi"],
            b"Connection": [b"close"],
            b"Pragma": [b"no-cache"],
            b"Cache-Control": [b"no-store, no-cache, must-revalidate"]
        }

        # Conditional headers
        host_headers = {
            b"Host": [domain.encode()],
            b"Cookie": [("mac={}; stb_lang=en; timezone={}; adid={}".format(mac, timezone, adid)).encode()]
        }

        merged_headers = base_headers.copy()
        merged_headers.update(host_headers)
        merged_headers[b"Authorization"] = [("Bearer " + token).encode()]

        self.headers = Headers(merged_headers)

        self.download_epgs()

    def download_epgs(self):
        for ch_id in self.visible_ids:
            url = self.portal + "?type=itv&action=get_short_epg&ch_id={}&limit=10&size=10".format(ch_id)
            d = self.agent.request(b'GET', url.encode(), self.headers)
            d.addCallback(lambda response, ch_id=ch_id: self.handle_response(response, ch_id))
            d.addErrback(self.handle_error)

    def handle_response(self, response, ch_id):
        if response.code != 200:
            self.responses_received += 1
            self.check_complete()
            return

        d = readBody(response)
        d.addCallback(lambda body: self.process_body(body, ch_id, response))

    def process_body(self, body, ch_id, response):
        try:
            encoding_headers = response.headers.getRawHeaders(b"Content-Encoding", [b""])
            encoding = encoding_headers[0].decode('utf-8').lower() if isinstance(encoding_headers[0], bytes) else encoding_headers[0].lower()

            if encoding == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(body)) as f:
                    data = f.read()
            else:
                data = body

            if sys.version_info[0] == 3:
                data = data.decode('utf-8')

            json_data = json.loads(data)

            epg_events = json_data.get("js", [])
            for event in epg_events:
                self.epg_data.append(event)

        except Exception:
            pass

        self.responses_received += 1
        self.check_complete()

    def check_complete(self):
        if self.responses_received >= self.total_requests:
            if self.done_callback:
                self.done_callback({"js": self.epg_data})

    def handle_error(self, failure):
        self.responses_received += 1
        self.check_complete()
