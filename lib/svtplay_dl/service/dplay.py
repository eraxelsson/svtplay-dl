# ex:ts=4:sw=4:sts=4:et
# -*- tab-width: 4; c-basic-offset: 4; indent-tabs-mode: nil -*-
from __future__ import absolute_import
import re
import os
import hashlib
import random

from svtplay_dl.service import Service
from svtplay_dl.fetcher.hls import hlsparse
from svtplay_dl.subtitle import subtitle
from svtplay_dl.utils.urllib import urlparse
from svtplay_dl.error import ServiceError
from svtplay_dl.utils import filenamify, is_py2
from svtplay_dl.log import log


class Dplay(Service):
    supported_domains = ['dplay.se', 'dplay.dk', "dplay.no"]

    def get(self):
        parse = urlparse(self.url)
        self.domain = re.search(r"(dplay\.\w\w)", parse.netloc).group(1)

        if not self._token():
            log.error("Something went wrong getting token for requests")

        url = "https://disco-api.{}/content{}".format(self.domain, parse.path)
        res = self.http.get(url, headers={"x-disco-client": "WEB:UNKNOWN:dplay-client:0.0.1"})
        janson = res.json()

        if self.options.output_auto:
            directory = os.path.dirname(self.options.output)
            self.options.service = "dplay"
            name = self._autoname(janson)
            if name is None:
                yield ServiceError("Cant find vid id for autonaming")
                return
            title = "{0}-{1}-{2}".format(name, janson["data"]["id"], self.options.service)
            if len(directory):
                self.options.output = os.path.join(directory, title)
            else:
                self.options.output = title

        api = "https://disco-api.{}/playback/videoPlaybackInfo/{}".format(self.domain, janson["data"]["id"])
        res = self.http.get(api)
        if res.status_code > 400:
            yield ServiceError("This video is geoblocked")
            return
        streams = hlsparse(self.options, self.http.request("get", res.json()["data"]["attributes"]["streaming"]["hls"]["url"]),
                           res.json()["data"]["attributes"]["streaming"]["hls"]["url"], httpobject=self.http)
        if streams:
            for n in list(streams.keys()):
                yield streams[n]

    def _autoname(self, jsondata):
        match = re.search('^([^/]+)/', jsondata["data"]["attributes"]["path"])
        show = match.group(1)
        season = jsondata["data"]["attributes"]["seasonNumber"]
        episode = jsondata["data"]["attributes"]["episodeNumber"]
        if is_py2:
            show = filenamify(show).encode("latin1")
        else:
            show = filenamify(show)
        return filenamify("{0}.s{1:02d}e{2:02d}".format(show, int(season), int(episode)))

    def find_all_episodes(self, options):
        parse = urlparse(self.url)
        self.domain = re.search(r"(dplay\.\w\w)", parse.netloc).group(1)

        match = re.search("^/(program|videos)/([^/]+)", parse.path)
        if not match:
            log.error("Can't find show name")
            return None

        if not self._token():
            log.error("Something went wrong getting token for requests")

        premium = False
        if self.options.username and self.options.password:
            premium = self.login()
            if not premium:
                log.warning("Wrong username/password.")

        url = "https://disco-api.{}/content/shows/{}".format(self.domain, match.group(2))
        res = self.http.get(url)
        programid = res.json()["data"]["id"]
        seasons = res.json()["data"]["attributes"]["seasonNumbers"]
        episodes = []
        for season in seasons:
            qyerystring = "include=primaryChannel,show&filter[videoType]=EPISODE&filter[show.id]={}&filter[seasonNumber]={}&" \
                          "page[size]=100&sort=seasonNumber,episodeNumber,-earliestPlayableStart".format(programid, season)
            res = self.http.get("https://disco-api.{}/content/videos?{}".format(self.domain, qyerystring))
            janson = res.json()
            for i in janson["data"]:
                if not premium and not "Free" in i["attributes"]["packages"]:
                    continue
                episodes.append("https://www.{}/videos/{}".format(self.domain, i["attributes"]["path"]))
        if len(episodes) == 0:
            log.error("Cant find any playable files")
        if options.all_last > 0:
            return episodes[:options.all_last]
        return episodes

    def login(self):
        url = "https://disco-api.{}/login".format(self.domain)
        login = {"credentials": {"username": self.options.username, "password": self.options.password}}
        res = self.http.post(url, json=login)
        if res.status_code > 400:
            return False
        return True

    def _token(self):
        # random device id for cookietoken
        deviceid = hashlib.sha256(bytes(int(random.random()*1000))).hexdigest()
        url = "https://disco-api.{}/token?realm={}&deviceId={}&shortlived=true".format(self.domain, self.domain.replace(".", ""), deviceid)
        res = self.http.get(url)
        if res.status_code > 400:
            return False
        return True
