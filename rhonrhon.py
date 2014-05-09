#!/usr/bin/env python

import os
import irc.client
import irc.bot
import re
import datetime
import json
from elasticsearch import Elasticsearch
from threading import Thread
from twython import TwythonStreamer

# ~/.rhonrhonrc example
#
# server = "chat.freenode.net"
# port = 6667
# channels = [ '#mychan' ]
# nickname = "mynick"
# nickpass = "my pass"
# realname = "Me, really"
# quit_message = "Seeya"
# 
# es_nodes = [{'host': 'localhost'}]
# es_idx = "my_index"
# 
# auth = {'opnick': 'supersecret'}
# 
# APP_KEY = "twitter_app_api_key"
# APP_SECRET = "twitter_app_api_secret"
# OAUTH_TOKEN = "twitter_oauth_token"
# OAUTH_TOKEN_SECRET = "twitter_oauth_token_secret"
# 
# twichans = { '#mychan': 'MyTrack', '#otherchan': 'AnotherTrack' }

exec(open(os.path.expanduser("~") + '/.rhonrhonrc').read())

es = Elasticsearch(es_nodes)

# Lazy global
tweetrelay = True

class TwiStreamer(TwythonStreamer):
    ircbot = None
    def on_success(self, data):
        if 'text' in data:
            if self.ircbot is None:
                print(data['text'].encode('utf-8'))
            elif tweetrelay is True and data['retweeted'] == False:
                for k in twichans:
                    # found matching text
                    if re.search(twichans[k], data['text']):
                        s = data['user']['screen_name']
                        n = data['user']['name']
                        out = '<@{0} ({1})> {2}'.format(s, n, data['text'])

                        self.ircbot.privmsg(k, out)

    def on_error(self, status_code, data):
        print(status_code, data)

class CustomLineBuffer(irc.client.LineBuffer):
    def lines(self):
        ld = []
        for line in super(CustomLineBuffer, self).lines():
            try:
                ld.append(line.decode('utf-8', errors='strict'))
            except UnicodeDecodeError:
                ld.append(line.decode('iso-8859-15', errors='replace'))
        return iter(ld)

class Bot(irc.bot.SingleServerIRCBot):
    def __init__(self):
        self.auth = []
        self.t = None # Twitter thread
        self.stream = None

        irc.client.ServerConnection.buffer_class = CustomLineBuffer
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port)],
                                           nickname, realname)

    def on_privnotice(self, serv, ev):
        print("notice: {0}".format(ev.arguments[0]))
        source = ev.source.nick
        if source and source.lower() == 'nickserv':
            if re.search('identify', ev.arguments[0], re.I):
                self.connection.privmsg(source, 'identify {0}'.format(nickpass))
            if re.search('identified', ev.arguments[0], re.I):
                self.chanjoin(serv)

    def chanjoin(self, serv):
        for chan in channels:
            print("joining {0}".format(chan))
            serv.join(chan)

    def on_kick(self, serv, ev):
        self.chanjoin(serv)

    def on_pubmsg(self, serv, ev):
        nick = ev.source.nick
        full_date = datetime.datetime.utcnow()
        pl = ev.arguments[0]

        if (re.search('[\[#]\ *nolog\ *[#\]]', pl, re.I)) or 'nolog' in nick:
            return

        date, clock = full_date.isoformat().split('T')
        clock = re.sub('\.[0-9]+', '', clock)
        channel = ev.target.replace('#', '')

        tags = []
        tagmatch = '#\ *([^#]+)\ *#\s*'
        tagsub = re.search('\ ' + tagmatch, pl)
        if tagsub:
            tags = tagsub.group(1).replace(' ', '').split(',')
            pl = re.sub(tagmatch, '', pl)

        urls = re.findall('(https?://[^\s]+)', pl)

        has_nick = False
        tonick = []
        tomatch = '^\ *([^:]+)\ *:\ *'
        tosub = re.search(tomatch, pl)
        if tosub and not re.search('https?', tosub.group(1)):
            for t in tosub.group(1).replace(' ', '').split(','):
                for ch in self.channels.keys():
                    if self.channels[ch].has_user(t) and ch == '#' + channel:
                        tonick.append(t)
                        has_nick = True

            if has_nick:
                pl = re.sub(tomatch, '', pl)

        data = {
            'fulldate': full_date.isoformat(),
            'date': date,
            'time': clock,
            'channel': channel,
            'server': serv.server,
            'nick': nick,
            'tonick': tonick,
            'tags': tags,
            'urls': urls,
            'line': pl
        }
        try:
            print("dumping {0} to {1}/{2}".format(data, es_idx, channel))
        except UnicodeEncodeError:
            print("Your charset does not permit to dump that dataset.")

        r = es.index(index=es_idx, doc_type=channel, body=json.dumps(data))
        print(r)

    def on_privmsg(self, serv, ev):
        pl = ev.arguments[0]
        s = pl.split(' ')
        if not ev.source.nick in auth.keys():
            return
        if len(s) > 1 and s[0] == 'auth' and s[1] == auth[ev.source.nick]:
            self.auth.append(ev.source.nick)
            serv.notice(ev.source.nick, 'You are now authenticated')
        if not ev.source.nick in self.auth:
            return
        self.do_cmd(serv, s)

    def start_track(self, serv):
        self.stream = TwiStreamer(APP_KEY, APP_SECRET,
                                  OAUTH_TOKEN, OAUTH_TOKEN_SECRET)
        self.stream.ircbot = serv
        target = ','.join(twichans.values())
        self.stream.statuses.filter(track = target)

    def do_cmd(self, serv, cmd):
        global tweetrelay
        print(cmd)
        if cmd[0] == 'die':
            self.die(quit_message)
        if cmd[0] == 'join' and len(cmd) > 1:
            serv.join(cmd[1])
        if cmd[0] == 'part' and len(cmd) > 1:
            serv.part(cmd[1])
        if cmd[0] == 'twitter' and len(cmd) > 1:
            if cmd[1] == 'on':
                if self.t is None:
                    self.t = Thread(target = self.start_track, args = (serv,))
                    self.t.daemon = True
                    self.t.start()

                tweetrelay = True
            # shut twitter relay's mouth
            if cmd[1] == 'off' and self.t is not None:
                tweetrelay = False

if __name__ == "__main__":
    Bot().start()
