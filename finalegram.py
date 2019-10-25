#!/usr/bin/env python
#
# Libreria (e al momento anche "main()") che fornisce alcuni metodi al bot di @finalegram
# Nicola Rossello <rossellonicola@gmail.com>

from datetime import datetime
import telegram
import telegram.error
import telegram.ext
import requests
from bs4 import BeautifulSoup
import time
import os

import ast
from urllib3.exceptions import NewConnectionError
from _socket import gaierror
import inspect

#############################

# variables

url = "http://www.allertaliguria.gov.it/"

alertchars = ["G", "A", "R"]

caption_msg = "BOLLETTINO"  # TODO: complete caption/messages

messages = {1: "ATTENZIONE: ALLERTA METEO",
            2: "AGGIORNAMENTO:",
            3: "AGGIORNAMENTO: rischio diminuito",
            4: "AGGIORNAMENTO: rischio aumentato",
            5: "Allerta meteo Conclusa"}


#############################


def error_wrapper(f):
    # Error handling decorator

    def wrapper_details(e):
        # common log debug function

        rawmessage = "An exception of type {0} occurred.\n" \
                     "----------------> Arguments: {1!r}"
        log_err(str(rawmessage.format(type(e).__name__, e.args)))
        exit(1)

    # def print_argue(e):
    #     # common console debug function
    #
    #     rawmessage = "an exception of type {0} occurred. Arguments: {1!r}"
    #     message = rawmessage.format(type(e).__name__, e.args)
    #     print('[' + f.__name__ + ']: ' + message)
    #     exit(1)

    def loop(*args, **kwargs):
        try:
            return f(*args, **kwargs)  # run wrapped function

        except (ConnectionError, NewConnectionError,                    # Network Related Errors
                gaierror, requests.exceptions.ConnectionError) as e:
            if f.__name__ == 'fetcher':  # A common fetcher() error handling (quieting it)
                return False
            else:
                wrapper_details(e)

        except SyntaxError as e:  # Common identification error handling
            if f.__name__ == 'identification':
                log_err("SyntaxError in 'credentials.priv' file, exiting.")
                log("Syntax error in 'credentials.priv' file, exiting.")
                exit(1)
            else:
                wrapper_details(e)

        except FileNotFoundError as e:
            if f.__name__ == 'credentials':
                log_err("File 'credentials.priv' not found, exiting.")
                log("File 'credentials.priv' not found, exiting.")
                exit(1)
            elif f.__name__ == 'read_data':
                return False
            else:
                wrapper_details(e)

        except Exception as e:  # do not kill me
            wrapper_details(e)

    return loop


##############################

# site catching and handling methods


@error_wrapper
def fetcher():
    # simple site scraper

    return requests.get(url).text


@error_wrapper
def allertaliguria_is_down():
    # server downtime detector

    response = requests.get('https://updown.io/api/checks/eki2?api-key=ro-m3NkszsxhGf3dm2kDSgR')
    return response.json()['down']


def loopfetcher():
    # 5 tries loop fetcher

    countlist = ["1st", "2nd", "3rd", "4th", "5th"]
    counter = 0

    while True:

        fetched = fetcher()

        if not fetched:
            counter += 1
            log_err(countlist[counter - 1] + ' try gave no result.')
            if counter == 5:
                log_err('5 tries failed, checking updown')
                if allertaliguria_is_down():
                    log_err('allertaliguria.gov.it is down')
                    down_start = datetime.now()
                    while allertaliguria_is_down():
                        time.sleep(30)
                    total_down = datetime.now() - down_start
                    log_err('back up, downtime = ' + total_down.min + 'minutes')
                    counter = 0
                    continue
            time.sleep(30)
            continue
        else:
            return fetched


def soupper(raw):
    # site parser

    return BeautifulSoup(raw, "html.parser")


##############################

# site information extracting methods


def alertpic(soup):
    # geographic map image
    # eg:  http://www.allertaliguria.gov.it/img/mappe/V_V_V_V_V.png

    for image in soup.find_all("img"):
        if "AREA" not in image['src'] and "mappe" in image['src']:
            return url + image['src']


def alertchar(soup):
    # alert char
    # eg: 'G'

    for image in soup.find_all("img"):
        if "AREA" not in image['src'] and "mappe" in image['src']:
            return str(image['src'])[10]


def pdf_forecast_link(soup):
    # complete pdf forecast
    # eg: http://www.allertaliguria.gov.it/docs/vigilanza_41338.pdf

    for div in (soup.find_all('div', 'al-container right al-position-absolute '
                                     'al-position-bottom al-position-right hide-for-small')):
        return url + div.a['href']


def alert_eta(soup):
    # alert issuing timestamp list
    # eta[0] date DD/MM/YYYY
    # eta[1] time hh:mm

    raw = []
    for section in (soup.find_all('section')):
        if not isinstance(section.h2, type(None)):
            raw.append(section.h2.string)
    return list((" ".join(raw[0].split())).replace('Messaggio del', "").replace('ore ', '')[1:].split(" "))


# TODO: add start/end alert hours parsing from url

##############################
# data compare methods


def alert_finder(soup):
    # alert finder

    # 0 = no updates / no active alert
    # 1 = new alert
    # 2 = alert update, same grade
    # 3 = alert update, grade lowered
    # 4 = alert update, grade raised
    # 5 = alert ended

    char = alertchar(soup)
    storedchar = read_data("char")
    storedtime = read_data("time")

    if char in alertchars:  # an alert is detected

        if not storedchar:  # a new alert (no previous records)
            log('found alert.')
            store_data(soup)
            return 1

        if storedchar:  # alert already in progress, analizing cases
            if alertchars.index(char) < alertchars.index(storedchar):  # an update who lowers alert grade
                log('found alert updates, grade lowered.')
                store_data(soup)
                return 3
            if alertchars.index(char) > alertchars.index(storedchar):  # an update who raises alert grade
                log('found alert updates, grade raised.')
                store_data(soup)
                return 4
            if char == storedchar:  # same grade, looking for time updates
                if storedtime == alert_eta(soup)[1]:  # no updates
                    return 0
                else:  # an update with same grade
                    log('found alert updates, same grade.')
                    store_data(soup)
                    return 2

    else:
        if storedchar:  # alert ended
            log('alert ended.')
            return 5
        return 0  # no alerts


##############################

# data store methods


def log(text):
    # logger

    data = str(datetime.now().strftime("%d/%m/%Y, %H:%M:%S.%f") + ':')
    caller = str('[' + inspect.stack()[1].function + ']')

    with open("finalegram.log", "a+") as database:
        database.write(str(data + caller + str(text) + '\n'))


def log_err(text):
    # error logger

    data = str(datetime.now().strftime("%d/%m/%Y, %H:%M:%S.%f") + ':')
    caller = str('[' + inspect.stack()[1].function + ']')

    with open("finalegram.err.log", "a+") as database:
        database.write(str(data + caller + str(text) + '\n'))


def store_data(soup):
    # store last fetched alert data

    with open("last_alert_time.txt", "w") as lastalert:
        lastalert.write(str(alert_eta(soup)[1]))

    with open("last_alert_char.txt", "w") as lastalert:
        lastalert.write(str(alertchar(soup)))


@error_wrapper
def read_data(kind):
    # read last fetched alert data

    if kind == "time":
        with open("last_alert_time.txt", "r") as alertfile:
            read = alertfile.read()
            return read

    if kind == "char":
        with open("last_alert_char.txt", "r") as alertfile:
            read = alertfile.read()
        return read


def clean_data():

    os.remove("last_alert_time.txt")
    os.remove("last_alert_char.txt")


##############################

# Telegram API methods

@error_wrapper
def notify_text(sender, recipient, text):
    # text notification

    telegram.Bot(sender).send_message(chat_id=recipient,
                                      text=text)


@error_wrapper
def notify_photo_link(sender, recipient, photo, caption, buttontext, link):
    # photo with a link button notification

    query = telegram.InlineKeyboardButton(buttontext, link)
    reply_markup = telegram.InlineKeyboardMarkup([[query]])
    telegram.Bot(sender).send_photo(chat_id=recipient,
                                    photo=photo,
                                    caption=caption,
                                    parse_mode='Markdown',
                                    reply_markup=reply_markup)


##############################


# identification

@error_wrapper
def credentials():
    # read credentials from file

    with open('credentials.priv', 'r') as c:
        creds = c.read()
        return ast.literal_eval(creds)


token = credentials()['token']
publicchatid = credentials()['publicchatid']
privatechatid = credentials()['privatechatid']

#############################
# main

log('##########################################')
log_err('##########################################')


def main():
    log('Started')
    notify_text(token, privatechatid, "bot avviato")
    while True:
        raw = loopfetcher()
        soup = soupper(raw)
        alert_id = alert_finder(soup)
        if alert_id:
            message = messages[alert_id]
            if alert_id < 5:
                notify_photo_link(token, publicchatid, alertpic(soup), message, caption_msg, pdf_forecast_link(soup))
            else:
                notify_text(token, publicchatid, message)
                clean_data()
        time.sleep(30)


main()
