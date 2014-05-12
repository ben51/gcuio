import os
import re
import sys
import base64
import hashlib
import requests
import datetime
from flask import Flask, render_template, request, url_for, json, Response
from werkzeug.contrib.atom import AtomFeed
from elasticsearch import Elasticsearch

app = Flask(__name__, instance_path=os.getcwd())  # latter needed by uwsgi
es = Elasticsearch()

nlines = 25
es_idx = 'rhonrhon'
channel = 'gcu'
status_url = 'http://status.gcu.io/nginx_status'  # that URL is not resolvable

ircline_style = {
    'div': 'ircline',
    'time': 'btn btn-sm btn-default',
    'date': 'btn btn-sm btn-default',
    'nick': 'btn btn-sm btn-success',
    'tonick': 'btn btn-sm btn-info',
    'tags': 'btn btn-sm btn-warning'
}

# match ISO format - datetime.datetime.utcnow().isoformat()
# i.e. 2014-04-30T18:22:42.596996
isodaterx = '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+$'


def _res_sort(res):
    '''
    Sort results given by ES using the 'sort' field
    '''
    return sorted(res['hits']['hits'], key=lambda getkey: getkey['sort'][0])


def _get_body(t, k, d):
    fd = ''
    if d:
        fd = '_date'

    ircbody = {'size': nlines, 'sort': [{'fulldate': {'order': 'desc'}}]}
    ircbody_date = {
        'query': {
            'range': {'fulldate': {k: d}}
        },
        'sort': [{'fulldate': {'order': 'desc'}}],
        'size': nlines
    }
    urlbody = {
        'query': {
            'match': {'urls': 'http https www'}
        },
        'sort': [{'fulldate': {'order': 'desc'}}],
        'size': nlines
    }
    urlbody_date = {
        'query': {
            'bool': {
                'must': [
                    {'match': {'urls': 'http https www'}},
                    {'range': {'fulldate': {k: d}}},
                ],
            },
        },
        'sort': [{'fulldate': {'order': 'desc'}}],
        'size': nlines,
    }

    func = '{0}body{1}'.format(t, fd)

    try:
        ret = locals()[func]
    except:
        ret = None
    return ret


@app.route('/get_last', methods=['GET'])
def get_last(arg_t=None):
    '''
    AJAX resource, retrieves latest type lines, or since 'fromdate'

    example:

    curl http://localhost:5000/get_last?t=irc
    curl http://localhost:5000/get_last?t=url&d=2014-04-22T15:07:10.278682
    '''

    allow_t = ['irc', 'url']
    allow_k = ['from', 'to']
    d = request.args.get('d')
    t = request.args.get('t')
    k = request.args.get('k')

    if arg_t is not None:
        t = arg_t

    if not k:
        k = 'from'

    rep = []
    if t in allow_t and k in allow_k:
        if d and not re.search(isodaterx, d):
            d = ''

        s_body = _get_body(t, k, d)

        try:  # catch anything to ES
            res = es.search(index=es_idx, doc_type=channel, body=s_body)
            if k == 'from':
                rep = _res_sort(res)
            else:  # if fetching items to a date, we will prepend them as-is
                rep = res['hits']['hits']

        except:
            pass

    # unknown type
    return Response(json.dumps(rep), mimetype='application/json')


@app.route('/search', methods=['GET'])
def search():
    rep = {'total': 0, 'hits': []}

    # no query
    if not request.args.get('q'):
        return json.dumps(rep)

    if request.args.get('f') and request.args.get('f').isdigit():
        f = request.args.get('f')
    else:
        f = 0

    q = request.args.get('q')

    if len(q) < 4:  # avoid short searches
        return json.dumps(rep)

    # alias to make grrrreg happy
    q = q.replace('tag:', 'tags:')

    s_body = {
        'query': {
            'query_string': {
                'query': q,
                'default_operator': 'and',
                'allow_leading_wildcard': 'false',
                'analyze_wildcard': 'true'
            },
        },
        'from': f,
        'size': nlines,
        'sort': [{'fulldate': {'order': 'desc'}}]
    }

    try:
        res = es.search(index=es_idx, doc_type=channel, body=s_body)

        rep = res['hits']
    except:
        pass

    return Response(json.dumps(rep), mimetype='application/json')


@app.route('/chaninfos', methods=['GET'])
def chaninfos():
    rep = {'total': 0, 'hits': []}

    s_body = {'size': 1, 'sort': [{'date': {'order': 'desc'}}]}
    doc_type = '{0}_infos'.format(channel)

    try:
        res = es.search(index=es_idx, doc_type=doc_type, body=s_body)
        rep = res['hits']['hits'][0]['_source']
    except:
        pass

    return Response(json.dumps(rep), mimetype='application/json')


@app.route('/short_url', methods=['GET'])
def short_url():
    '''
    URL shortener, idea taken from
    https://github.com/pyr/url-shortener/blob/master/url_shortener/shorten.py

    XXX: not sure what to do with this
    '''

    if not request.args.get('u'):
        return json.dumps({})

    url = request.args.get('u')

    x = hashlib.md5()
    x.update(url.encode('utf-8'))
    s = base64.b64encode(x.digest()[-4:]).decode('utf-8')
    s = s.replace('=', '').replace('/', '_')

    return Response(json.dumps({url: s}))


@app.route('/status', methods=['GET'])
def status():
    '''
    Retrieve nginx stub_status
    '''
    ret = {}
    r = requests.get(status_url)
    if r.status_code == 200:
        a = re.sub('\n.+', '', r.text.lower()).strip().split(': ')
        ret = {a[0].replace(' ', '_'): a[1]}

    return Response(json.dumps(ret))


@app.route('/atomfeed', methods=['GET'])
def atomfeed():
    t = request.args.get('t')
    if not t:
        t = 'url'

    print(t)
    r = get_last(t)
    if not r.status_code == 200 and len(r.response) > 0:
        return {}

    j = json.loads(r.response[0])

    if len(j) < 1:
        return {}

    feed = AtomFeed('Liens recents',
                    feed_url=request.url, url=request.url_root,
                    subtitle="Les liens (presque) SFW de GCU-Squad!")
    for item in j:
        post = item['_source']
        for url in post['urls']:
            datefmt = '%Y-%m-%dT%H:%M:%S.%f'
            pubdate = datetime.datetime.strptime(post['fulldate'], datefmt)
            update = pubdate
            if post['tags']:
                line = '{0} #{1}#'.format(post['line'], ','.join(post['tags']))
            else:
                line = post['line']
            feed.add(title=line, title_type='text', url=url,
                     author=post['nick'], published=pubdate, updated=update)
    return feed.get_response()


@app.route('/fonts/<path:filename>')
def fonts(filename):
    return app.send_static_file(os.path.join('fonts', filename))


@app.route('/images/<path:filename>')
def images(filename):
    print(os.path.join('images', filename))
    return app.send_static_file(os.path.join('images', filename))


@app.route('/')
def home():

    return render_template('gerard.js',
                           ircline_style=ircline_style, nlines=nlines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == '-d':
        app.run(host='0.0.0.0', port=5080, debug=True)
    else:
        app.run(host='0.0.0.0', port=5080)
