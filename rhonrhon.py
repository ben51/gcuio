#!/usr/bin/env python
 
import irc.client
import irc.bot
import re
import datetime
import json
import requests
from elasticsearch import Elasticsearch
from os.path import expanduser

exec(open(expanduser("~") + '/.rhonrhonrc').read())

es = Elasticsearch(es_nodes)

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
        pl = ev.arguments[0]
        if (re.search('[\[#]\ *nolog\ *[#\]]', pl, re.I)):
            return

        date, clock = datetime.datetime.utcnow().isoformat().split('T')
        clock = re.sub('\.[0-9]+', '', clock)
        channel = ev.target.replace('#', '')

        tags = []
        tagmatch = '\ #\ *([^#]+)\ *#\s*'
        tagsub = re.search(tagmatch, pl)
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
            'fulldate': datetime.datetime.utcnow().isoformat(),
            'date': date,
            'time': clock,
            'channel': channel,
            'server': serv.server,
            'nick': ev.source.nick,
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

    def do_cmd(self, serv, cmd):
        print(cmd)
        if cmd[0] == 'die':
            self.die(quit_message)
        if cmd[0] == 'join' and len(cmd) > 1:
            serv.join(cmd[1])
        if cmd[0] == 'part' and len(cmd) > 1:
            serv.part(cmd[1])

if __name__ == "__main__":
    Bot().start()
