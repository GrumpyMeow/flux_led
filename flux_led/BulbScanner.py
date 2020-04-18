#!/usr/bin/env python

import socket
import time
import logging

DISCOVERY_PORT = 48899
DISCOVERY_MSG = "HF-A11ASSISTHREAD"

INFOFIELD_IPADDR = 'ipaddr'
INFOFIELD_ID = 'id'
INFOFIELD_MODEL = 'model'


class  BulbScanner():
    def __init__(self):
        self.found_bulbs = []

    def getBulbInfoByID(self, id):
        for b in self.found_bulbs:
            if b['id'] == id:
                return b
        return b

    def getBulbInfo(self):
        return self.found_bulbs

    def scan(self, timeout=10):

        sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        sock.bind(('', DISCOVERY_PORT))
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        msg = DISCOVERY_MSG.encode('ascii')

        # set the time at which we will quit the search
        quit_time = time.time() + timeout

        response_list = []
        # outer loop for query send
        while True:
            if time.time() > quit_time:
                break

            # send out a broadcast query
            logging.debug("Sending out a broadcast query")
            sock.sendto(msg, ('<broadcast>', DISCOVERY_PORT))

            # inner loop waiting for responses
            while True:

                sock.settimeout(1)
                try:
                    data, addr = sock.recvfrom(64)
                except socket.timeout:
                    data = None
                    if time.time() > quit_time:
                        break

                if data is None:
                    continue
                if  data == msg:
                    continue

                data = data.decode('ascii')
                data_split = data.split(',')
                if len(data_split) < 3:
                    logging.warn("Invalid response: " + data)
                    continue
                else:
                    logging.debug("Received response: " + data)
                    
                item = dict()
                item[INFOFIELD_IPADDR] = data_split[0]
                item[INFOFIELD_ID] = data_split[1]
                item[INFOFIELD_MODEL] = data_split[2]
                response_list.append(item)

        self.found_bulbs = response_list
        return response_list

