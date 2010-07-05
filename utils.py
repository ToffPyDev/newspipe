#! /usr/local/bin/python
#-*- coding: utf-8 -*-

__author__ = "Cedric Bonhomme"
__version__ = "$Revision: 0.8 $"
__date__ = "$Date: 2010/07/05 $"
__copyright__ = "Copyright (c) 2010 Cedric Bonhomme"
__license__ = "GPLv3"

IMPORT_ERROR = []

import re
try:
    import pylab
except:
    IMPORT_ERROR.append("pylab")
import string
import hashlib
import sqlite3
import operator
import urlparse

import smtplib
from email.mime.text import MIMEText

import urllib2
from BeautifulSoup import BeautifulSoup

from datetime import datetime
from string import punctuation
from collections import defaultdict
from collections import OrderedDict

from StringIO import StringIO

try:
    from oice.langdet import langdet
    from oice.langdet import streams
    from oice.langdet import languages
except:
    IMPORT_ERROR.append("oice")

import threading
LOCKER = threading.Lock()

import os
import ConfigParser
config = ConfigParser.RawConfigParser()
config.read("./cfg/pyAggr3g470r.cfg")
path = config.get('global','path')
sqlite_base = os.path.abspath(config.get('global', 'sqlitebase'))
mail_from = config.get('mail','mail_from')
mail_to = config.get('mail','mail_to')
smtp_server = config.get('mail','smtp')
username =  config.get('mail','username')
password =  config.get('mail','password')


def detect_language(text):
    """
    Detect the language of a text.
    English, French or other (not detected).
    """
    text = text.strip()
    try:
        text_stream = streams.Stream(StringIO(text))
        lang = langdet.LanguageDetector.detect(text_stream)
    except:
        return 'other'
    if lang == languages.french:
        return 'french'.encode('utf-8')
    elif lang == languages.english:
        return 'english'.encode('utf-8')
    else:
        return 'other'

def remove_html_tags(data):
    """
    Remove HTML tags for the search.
    """
    p = re.compile(r'<[^<]*?/?>')
    q = re.compile(r'&#[0-9]+;')
    return p.sub('', q.sub('', data))

def top_words(dic_articles, n=10, size=5):
    """
    Return the n most frequent words in a list.
    """
    words = {}
    articles_content = ""
    for rss_feed_id in dic_articles.keys():
        for article in dic_articles[rss_feed_id]:
            articles_content += remove_html_tags(article[4].encode('utf-8'))

    words_gen = [word for word in articles_content.split() if len(word) > size]
    words_gen = [word.strip(punctuation).lower() for word in words_gen]

    words = defaultdict(int)
    for word in words_gen:
        words[word] += 1
    top_words = sorted(words.iteritems(),
                key=lambda(word, count): (-count, word))[:n]
    return top_words

def tag_cloud(tags):
    """
    Generates a tags cloud.
    """
    tags.sort(key=operator.itemgetter(0))
    return ' '.join([('<font size="%d"><a href="/q/?querystring=%s">%s</a></font>\n' % \
                    (min(1 + count * 7 / max([tag[1] for tag in tags]), 7), word, word)) \
                        for (word, count) in tags])

def create_histogram(words, file_name="./var/histogram.png"):
    """
    Create a histogram.
    """
    if "pylab" in IMPORT_ERROR:
        return
    length = 10
    ind = pylab.arange(length) # abscissa
    width = 0.35 # bars width

    w = [elem[0] for elem in words]
    count = [int(elem[1]) for elem in words]

    max_count = max(count)  # maximal weight

    p = pylab.bar(ind, count, width, color='r')

    pylab.ylabel("Count")
    pylab.title("Most frequent words")
    pylab.xticks(ind + (width / 2), range(1, len(w)+1))
    pylab.xlim(-width, len(ind))

    # changing the ordinate scale according to the max.
    if max_count <= 100:
        pylab.ylim(0, max_count + 5)
        pylab.yticks(pylab.arange(0, max_count + 5, 5))
    elif max_count <= 200:
        pylab.ylim(0, max_count + 10)
        pylab.yticks(pylab.arange(0, max_count + 10, 10))
    elif max_count <= 600:
        pylab.ylim(0, max_count + 25)
        pylab.yticks(pylab.arange(0, max_count + 25, 25))
    elif max_count <= 800:
        pylab.ylim(0, max_count + 50)
        pylab.yticks(pylab.arange(0, max_count + 50, 50))

    pylab.savefig(file_name, dpi = 80)
    pylab.close()

def send_mail(mfrom, mto, feed_title, message):
    """Send the warning via mail
    """
    mail = MIMEText(message)
    mail['From'] = mfrom
    mail['To'] = mto
    mail['Subject'] = '[pyAggr3g470r] News from ' + feed_title
    #email['Text'] = message

    server = smtplib.SMTP(smtp_server)
    server.login(username, password)
    server.sendmail(mfrom, \
                    mto, \
                    mail.as_string())
    server.quit()

def string_to_datetime(stringtime):
    """
    Convert a string to datetime.
    """
    date, time = stringtime.split(' ')
    year, month, day = date.split('-')
    hour, minute, second = time.split(':')
    return datetime(year=int(year), month=int(month), day=int(day), \
        hour=int(hour), minute=int(minute), second=int(second))

def compare(stringtime1, stringtime2):
    """
    Compare two dates in the format 'yyyy-mm-dd hh:mm:ss'.
    """
    datetime1 = string_to_datetime(stringtime1)
    datetime2 = string_to_datetime(stringtime2)
    if datetime1 < datetime2:
        return -1
    elif datetime1 > datetime2:
        return 1
    return 0

def add_feed(feed_url):
    """
    Add the URL feed_url in the file feed.lst.
    """
    if os.path.exists("./var/feed.lst"):
        for line in open("./var/feed.lst", "r"):
            if feed_url in line:
                return False
    with open("./var/feed.lst", "a") as f:
        f.write(feed_url + "\n")
    return True

def remove_feed(feed_url):
    """
    Remove a feed from the file feed.lst and from the SQLite base.
    """
    feeds = []
    # Remove the URL from the file feed.lst
    if os.path.exists("./var/feed.lst"):
        for line in open("./var/feed.lst", "r"):
            if feed_url not in line:
                feeds.append(line.replace("\n", ""))
        with open("./var/feed.lst", "w") as f:
            f.write("\n".join(feeds) + "\n")
        # Remove articles from this feed from the SQLite base.
        try:
            conn = sqlite3.connect(sqlite_base, isolation_level = None)
            c = conn.cursor()
            c.execute("DELETE FROM feeds WHERE feed_link='" + feed_url +"'")
            c.execute("DELETE FROM articles WHERE feed_link='" + feed_url +"'")
            conn.commit()
            c.close()
        except:
            pass

def search_feed(url):
    """
    Search a feed in a HTML page.
    """
    soup = None
    try:
        page = urllib2.urlopen(url)
        soup = BeautifulSoup(page)
    except:
        return None
    feed_links = soup('link', type='application/atom+xml')
    feed_links.extend(soup('link', type='application/rss+xml'))
    for feed_link in feed_links:
        if url not in feed_link['href']:
            return urlparse.urljoin(url, feed_link['href'])
        return feed_link['href']
    return None

def create_base():
    """
    Create the base if not exists.
    """
    sqlite3.register_adapter(str, lambda s : s.decode('utf-8'))
    conn = sqlite3.connect(sqlite_base, isolation_level = None)
    c = conn.cursor()
    c.execute('''create table if not exists feeds
                (feed_title text, feed_site_link text, \
                feed_link text PRIMARY KEY, feed_image_link text,
                mail text)''')
    c.execute('''create table if not exists articles
                (article_date text, article_title text, \
                article_link text PRIMARY KEY, article_description text, \
                article_readed text, feed_link text, like text)''')
    conn.commit()
    c.close()

def load_feed():
    """
    Load feeds and articles in a dictionary.
    """
    LOCKER.acquire()
    list_of_feeds = []
    list_of_articles = []
    try:
        conn = sqlite3.connect(sqlite_base, isolation_level = None)
        c = conn.cursor()
        list_of_feeds = c.execute("SELECT * FROM feeds").fetchall()
    except:
        pass

    # articles[feed_id] = (article_id, article_date, article_title,
    #               article_link, article_description, article_readed,
    #               article_language, like)
    # feeds[feed_id] = (nb_article, nb_article_unreaded, feed_image,
    #               feed_title, feed_link, feed_site_link, mail)
    articles, feeds = {}, OrderedDict()
    if list_of_feeds != []:
        sha1_hash = hashlib.sha1()
        # Case-insensitive sorting
        tupleList = [(x[0].lower(), x) for x in list_of_feeds]
        tupleList.sort(key=operator.itemgetter(0))

        for feed in [x[1] for x in tupleList]:
            list_of_articles = c.execute(\
                    "SELECT * FROM articles WHERE feed_link='" + \
                    feed[2] + "'").fetchall()

            sha1_hash.update(feed[2].encode('utf-8'))
            feed_id = sha1_hash.hexdigest()

            if list_of_articles != []:
                for article in list_of_articles:
                    sha1_hash.update(article[2].encode('utf-8'))
                    article_id = sha1_hash.hexdigest()

                    if "oice" not in IMPORT_ERROR:
                        if article[3] != "":
                            language = detect_language(remove_html_tags(article[3][:80]).encode('utf-8') + \
                                                remove_html_tags(article[1]).encode('utf-8'))
                        else:
                            language = detect_language(remove_html_tags(article[1]).encode('utf-8'))
                    else:
                        language = "IMPORT_ERROR"

                    article_list = [article_id, article[0], article[1], \
                        article[2], article[3], article[4], language, article[6]]

                    if feed_id not in articles:
                        articles[feed_id] = [article_list]
                    else:
                        articles[feed_id].append(article_list)


                # sort articles by date for each feeds
                for rss_feed_id in articles.keys():
                    articles[rss_feed_id].sort(lambda x,y: compare(y[1], x[1]))

                feeds[feed_id] = (len(articles[feed_id]), \
                                len([article for article in articles[feed_id] \
                                    if article[5]=="0"]), \
                                feed[3], feed[0], feed[2], feed[1] , feed[4]\
                                )

        c.close()
        LOCKER.release()
        return (articles, feeds)
    LOCKER.release()
    return (articles, feeds)