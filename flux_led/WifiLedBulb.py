#!/usr/bin/env python

import threading
import colorsys
import socket
from flux_led.Utils import Utils
from flux_led.PresetPattern import PresetPattern
from flux_led.BuiltInTimer import BuiltInTimer
import logging
import time
import datetime
from flux_led.LedTimer import LedTimer
from flux_led.Utils import Utils

from flux_led.DeviceCommands import *

class WifiLedBulb():
    def __init__(self, ipaddr, port=5577, timeout=5):
        self.ipaddr = ipaddr
        self.port = port
        self.timeout = timeout

        self.protocol = None
        self.rgbwcapable = False
        self.rgbwprotocol = False

        self.raw_state = None
        self._is_on = False
        self._mode = None
        self._socket = None
        self._lock = threading.Lock()
        self._query_len = 0
        self._use_csum = True

        self.connect(2)
        self.update_state()


    @property
    def is_on(self):
        return self._is_on

    @property
    def mode(self):
        return self._mode

    @property
    def warm_white(self):
        if self.protocol == 'LEDENET':
            return self.raw_state[9]
        else:
            return 0

    @property
    def cold_white(self):
        if self.protocol == 'LEDENET':
            return self.raw_state[11]
        else:
            return 0

    @property
    def brightness(self):
        """Return current brightness 0-255.

        For warm white return current led level. For RGB
        calculate the HSV and return the 'value'.
        """
        if self.mode == "ww":
            return int(self.raw_state[9])
        else:
            _, _, v = colorsys.rgb_to_hsv(*self.getRgb())
            return v

    def connect(self, retry=0):
        self.close()
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.ipaddr, self.port))
        except socket.error:
            if retry < 1:
                return
            self.connect(max(retry-1, 0))

    def close(self):
        if self._socket is None:
            return
        try:
            self._socket.close()
        except socket.error:
            pass

    def _determineMode(self, ww_level, pattern_code):
        mode = "unknown"
        if pattern_code in [ 0x61, 0x62]:
            if self.rgbwcapable:
                mode = "color"
            elif ww_level != 0:
                mode = "ww"
            else:
                mode = "color"
        elif pattern_code == 0x60:
            mode = "custom"
        elif pattern_code == 0x41:
            mode = "color"
        elif pattern_code == 0x00:
            mode = "color"
        elif PresetPattern.valid(pattern_code):
            mode = "preset"
        elif BuiltInTimer.valid(pattern_code):
            mode = BuiltInTimer.valtostr(pattern_code)
        return mode

 
    def _determine_query_len(self, retry = 2):

        # determine the type of protocol based of first 2 bytes.
        self._send_msg(bytearray(COMMAND_GET_STATE))
        rx = self._read_msg(2)
        # if any response is recieved, use the default protocol
        if len(rx) == 2:
            self._query_len = 14
            return
        # if no response from default received, next try the original protocol
        self._send_msg(bytearray([0xef, 0x01, 0x77]))
        rx = self._read_msg(2)
        if rx[1] == 0x01:
            self.protocol = 'LEDENET_ORIGINAL'
            self._use_csum = False
            self._query_len = 11
            return
        else:
            self._use_csum = True
        if rx == None and retry > 0:
            self._determine_query_len(max(retry -1,0))
        
 
    def query_state(self, retry=2, led_type = None):
        if self._query_len == 0:
            self._determine_query_len()
            
        # default value
        msg = bytearray(COMMAND_GET_STATE)
        # alternative for original protocol
        if self.protocol == 'LEDENET_ORIGINAL' or led_type == 'LEDENET_ORIGINAL':
            msg =  bytearray([0xef, 0x01, 0x77])
            led_type = 'LEDENET_ORIGINAL'

        try:
            logging.debug("Connecting to device")
            self.connect()

            logging.debug("Sending query_state command: " + msg.hex() )
            self._send_msg(msg)
            rx = self._read_msg(self._query_len)
            logging.debug("Received query_state response: " + rx.hex() )
        except socket.error:
            if retry < 1:
                self._is_on = False
                return
            self.connect()
            return self.query_state(max(retry-1, 0), led_type)
        if rx is None or len(rx) < self._query_len:
            if retry < 1:
                self._is_on = False
                return rx
            return self.query_state(max(retry-1, 0), led_type)
        
        return rx


    def update_state(self, retry=2 ):
        rx = self.query_state(retry)

        if rx is None or len(rx) < self._query_len:
            self._is_on = False
            return
      
        # typical response:
        #pos  0  1  2  3  4  5  6  7  8  9 10
        #    66 01 24 39 21 0a ff 00 00 01 99
        #     |  |  |  |  |  |  |  |  |  |  |
        #     |  |  |  |  |  |  |  |  |  |  checksum
        #     |  |  |  |  |  |  |  |  |  warmwhite
        #     |  |  |  |  |  |  |  |  blue
        #     |  |  |  |  |  |  |  green 
        #     |  |  |  |  |  |  red
        #     |  |  |  |  |  speed: 0f = highest f0 is lowest
        #     |  |  |  |  <don't know yet>
        #     |  |  |  preset pattern             
        #     |  |  off(23)/on(24)
        #     |  type
        #     msg head
        #        

        # response from a 5-channel LEDENET controller:
        #pos  0  1  2  3  4  5  6  7  8  9 10 11 12 13
        #    81 25 23 61 21 06 38 05 06 f9 01 00 0f 9d
        #     |  |  |  |  |  |  |  |  |  |  |  |  |  |
        #     |  |  |  |  |  |  |  |  |  |  |  |  |  checksum
        #     |  |  |  |  |  |  |  |  |  |  |  |  color mode (f0 colors were set, 0f whites, 00 all were set)
        #     |  |  |  |  |  |  |  |  |  |  |  cold-white
        #     |  |  |  |  |  |  |  |  |  |  <don't know yet>
        #     |  |  |  |  |  |  |  |  |  warmwhite
        #     |  |  |  |  |  |  |  |  blue
        #     |  |  |  |  |  |  |  green
        #     |  |  |  |  |  |  red
        #     |  |  |  |  |  speed: 0f = highest f0 is lowest
        #     |  |  |  |  <don't know yet>
        #     |  |  |  preset pattern
        #     |  |  off(23)/on(24)
        #     |  type
        #     msg head
        #

        # Devices that don't require a separate rgb/w bit
        if (rx[1] == 0x04 or
            rx[1] == 0x33 or
            rx[1] == 0x81):
            self.rgbwprotocol = True

        # Devices that actually support rgbw
        if (rx[1] == 0x04 or
            rx[1] == 0x25 or
            rx[1] == 0x33 or
            rx[1] == 0x81 or
            rx[1] == 0x44):
            self.rgbwcapable = True

        # Devices that use an 8-byte protocol
        if (rx[1] == 0x25 or
            rx[1] == 0x27 or
            rx[1] == 0x35 or
            rx[1] == 0xa1):
            self.protocol = "LEDENET"

        # Devices that use the original LEDENET protocol
        if rx[1] == 0x01:
            self.protocol = "LEDENET_ORIGINAL"
            self._use_csum = False

        pattern = rx[3]
        ww_level = rx[9]
        mode = self._determineMode(ww_level, pattern)
        if mode == "unknown":
            if retry < 1:
                return
            self.update_state(max(retry-1, 0))
            return
        power_state = rx[2]

        if power_state == 0x23:
            self._is_on = True
        elif power_state == 0x24:
            self._is_on = False
        self.raw_state = rx
        self._mode = mode

    def __str__(self):
        rx = self.raw_state
        mode = self.mode

        pattern = rx[3]
        ww_level = rx[9]
        power_state = rx[2]
        power_str = "Unknown power state"

        if power_state == 0x23:
            power_str = "ON "
        elif power_state == 0x24:
            power_str = "OFF "

        delay = rx[5]
        speed = Utils.delayToSpeed(delay)
        if mode == "color":
            if (power_state == 0x23):
                red = rx[6]
                green = rx[7]
                blue = rx[8]
                mode_str = "Color: {}".format((red, green, blue))
                if self.rgbwcapable:
                    mode_str += " White: {}".format(rx[9])
                else:
                    mode_str += " Brightness: {}".format(self.brightness)
            else:
                mode_str = ""
        elif mode == "ww":
            mode_str = "Warm White: {}%".format(Utils.byteToPercent(ww_level))
        elif mode == "preset":
            pat = PresetPattern.valtostr(pattern)
            mode_str = "Pattern: {} (Speed {}%)".format(pat, speed)
        elif mode == "custom":
            mode_str = "Custom pattern (Speed {}%)".format(speed)
        elif BuiltInTimer.valid(pattern):
            mode_str = BuiltInTimer.valtostr(pattern)
        else:
            mode_str = "Unknown mode 0x{:x}".format(pattern)
        if pattern == 0x62:
            mode_str += " (tmp)"
        mode_str += " raw state: "
        for _r in rx:
          mode_str += str(_r) + ","
        return "{} [{}]".format(power_str, mode_str)


    def _change_state(self, retry, turn_on = True):

        if self.protocol == 'LEDENET_ORIGINAL':
            msg_on =  bytearray([0xcc, 0x23, 0x33])
            msg_off =  bytearray([0xcc, 0x24, 0x33])
        else:
            msg_on = bytearray(COMMAND_POWER_ON)
            msg_off = bytearray(COMMAND_POWER_OFF)

        if turn_on:
            msg = msg_on
        else:
            msg = msg_off

        try:
            self._send_msg(msg)
        except socket.error:
            if retry > 0:
                self.connect()
                self._change_state(max(retry-1, 0), turn_on)
                return
            self._is_on = False


    def turnOn(self, retry=2):
        self._is_on = True
        self._change_state(retry, turn_on = True)

    def turnOff(self, retry=2):
        self._is_on = False
        self._change_state(retry, turn_on = False)


    def isOn(self):
        return self.is_on

    def getWarmWhite255(self):
        if self.mode != "ww":
            return 255
        return self.brightness

    def setWarmWhite(self, level, persist=True, retry=2):
        self.setWarmWhite255(Utils.percentToByte(level), persist, retry)

    def setWarmWhite255(self, level, persist=True, retry=2):
        self.setRgbw(w=level, persist=persist, brightness=None, retry=retry)

    def setColdWhite(self, level, persist=True, retry=2):
        self.setColdWhite255(Utils.percentToByte(level), persist, retry)

    def setColdWhite255(self, level, persist=True, retry=2):
        self.setRgbw(persist=persist, brightness=None, retry=retry, w2=level)

    def setWhiteTemperature(self, temperature, brightness, persist=True,
                            retry=2):
        # Assume output temperature of between 2700 and 6500 Kelvin, and scale
        # the warm and cold LEDs linearly to provide that
        temperature = max(temperature-2700, 0)
        warm = 255 * (1 - (temperature/3800))
        cold = min(255 * temperature/3800, 255)
        warm *= brightness/255
        cold *= brightness/255
        self.setRgbw(w=warm, w2=cold, persist=persist, retry=retry)

    def getRgbw(self):
        if self.mode != "color":
            return (255, 255, 255, 255)
        red = self.raw_state[6]
        green = self.raw_state[7]
        blue = self.raw_state[8]
        white = self.raw_state[9]
        return (red, green, blue, white)
    
    def getRgbww(self):
        if self.mode != "color":
            return (255, 255, 255, 255, 255)
        red = self.raw_state[6]
        green = self.raw_state[7]
        blue = self.raw_state[8]
        white = self.raw_state[9]
        white2 = self.raw_state[11]
        return (red, green, blue, white, white2)

    def getSpeed(self):
        delay = self.raw_state[5]
        speed = Utils.delayToSpeed(delay)
        return speed

    def setRgbw(self, r=None, g=None, b=None, w=None, persist=True,
                brightness=None, retry=2, w2=None):

        if (r or g or b) and (w or w2) and not self.rgbwcapable:
            print("RGBW command sent to non-RGBW device")
            raise Exception

        # sample message for original LEDENET protocol (w/o checksum at end)
        #  0  1  2  3  4
        # 56 90 fa 77 aa
        #  |  |  |  |  |
        #  |  |  |  |  terminator
        #  |  |  |  blue
        #  |  |  green
        #  |  red
        #  head

        
        # sample message for 8-byte protocols (w/ checksum at end)
        #  0  1  2  3  4  5  6
        # 31 90 fa 77 00 00 0f
        #  |  |  |  |  |  |  |
        #  |  |  |  |  |  |  terminator
        #  |  |  |  |  |  write mask / white2 (see below)
        #  |  |  |  |  white
        #  |  |  |  blue
        #  |  |  green
        #  |  red
        #  persistence (31 for true / 41 for false)
        #
        # byte 5 can have different values depending on the type
        # of device:
        # For devices that support 2 types of white value (warm and cold
        # white) this value is the cold white value. These use the LEDENET
        # protocol. If a second value is not given, reuse the first white value.
        #
        # For devices that cannot set both rbg and white values at the same time
        # (including devices that only support white) this value
        # specifies if this command is to set white value (0f) or the rgb
        # value (f0). 
        #
        # For all other rgb and rgbw devices, the value is 00

        # sample message for 9-byte LEDENET protocol (w/ checksum at end)
        #  0  1  2  3  4  5  6  7
        # 31 bc c1 ff 00 00 f0 0f
        #  |  |  |  |  |  |  |  |
        #  |  |  |  |  |  |  |  terminator
        #  |  |  |  |  |  |  write mode (f0 colors, 0f whites, 00 colors & whites)
        #  |  |  |  |  |  cold white
        #  |  |  |  |  warm white
        #  |  |  |  blue
        #  |  |  green
        #  |  red
        #  persistence (31 for true / 41 for false)
        #

        if brightness != None:
            (r, g, b) = self._calculateBrightness((r, g, b), brightness)

        # The original LEDENET protocol
        if self.protocol == 'LEDENET_ORIGINAL':
            msg = bytearray([0x56])
            msg.append(int(r))
            msg.append(int(g))
            msg.append(int(b))
            msg.append(0xaa)
        else:
            # all other devices

            #assemble the message
            if persist:
                msg = bytearray(COMMAND_SET_COLOR)
            else:
                msg = bytearray(COMMAND_SET_MUSICCOLOR)

            if r is not None:
                msg.append(int(r))
            else:
                msg.append(int(0))
            if g is not None:
                msg.append(int(g))
            else:
                msg.append(int(0))
            if b is not None:
                msg.append(int(b))
            else:
                msg.append(int(0))
            if w is not None:
                msg.append(int(w))
            else:
                msg.append(int(0))

            if self.protocol == "LEDENET":
                # LEDENET devices support two white outputs for cold and warm. We set
                # the second one here - if we're only setting a single white value,
                # we set the second output to be the same as the first
                if w2 is not None:
                    msg.append(int(w2))
                elif w is not None:
                    msg.append(int(w))
                else:
                    msg.append(0)

            # write mask, default to writing color and whites simultaneously
            write_mask = 0x00
            # rgbwprotocol devices always overwrite both color & whites
            if not self.rgbwprotocol:
                if w is None and w2 is None:
                    # Mask out whites
                    write_mask |= 0xf0
                elif r is None and g is None and b is None:
                    # Mask out colors
                    write_mask |= 0x0f

            msg.append(write_mask)

            # Message terminator
            msg.append(0x0f)

        # send the message
        try:
            self._send_msg(msg)
        except socket.error:
            if retry:
                self.connect()
                self.setRgbw(r,g,b,w, persist=persist, brightness=brightness,
                             retry=max(retry-1, 0), w2=w2)

    def getRgb(self):
        if self.mode != "color":
            return (255, 255, 255)
        red = self.raw_state[6]
        green = self.raw_state[7]
        blue = self.raw_state[8]
        return (red, green, blue)

    def setRgb(self, r,g,b, persist=True, brightness=None, retry=2):
        self.setRgbw(r, g, b, persist=persist, brightness=brightness,
                     retry=retry)

    def _calculateBrightness(self, rgb, level):
        r = rgb[0]
        g = rgb[1]
        b = rgb[2]
        hsv = colorsys.rgb_to_hsv(r, g, b)
        return colorsys.hsv_to_rgb(hsv[0], hsv[1], level)

    def _send_msg(self, bytes):
        # calculate checksum of byte array and add to end
        if self._use_csum:
            csum = sum(bytes) & 0xFF
            bytes.append(csum)
        with self._lock:
            self._socket.send(bytes)

    def _read_msg(self, expected):
        remaining = expected
        rx = bytearray()
        begin = time.time()
        while remaining > 0:
            if time.time() - begin > self.timeout:
                break
            try:
                with self._lock:
                    self._socket.setblocking(0)
                    chunk = self._socket.recv(remaining)
                    if chunk:
                        begin = time.time()
                    remaining -= len(chunk)
                    rx.extend(chunk)
            except socket.error:
                pass
            finally:
                self._socket.setblocking(1)
        return rx

    def getClock(self):
        msg = bytearray(COMMAND_GET_TIME)
        self._send_msg(msg)
        rx = self._read_msg(12)
        if len(rx) != 12:
            return
        year =  rx[3] + 2000
        month = rx[4]
        date = rx[5]
        hour = rx[6]
        minute = rx[7]
        second = rx[8]
        #dayofweek = rx[9]
        try:
            dt = datetime.datetime(year,month,date,hour,minute,second)
        except:
            dt = None
        return dt

    def setClock(self):
        msg = bytearray(COMMAND_SET_TIME)
        now = datetime.datetime.now()
        msg.append(now.year-2000)
        msg.append(now.month)
        msg.append(now.day)
        msg.append(now.hour)
        msg.append(now.minute)
        msg.append(now.second)
        msg.append(now.isoweekday()) # day of week
        msg.append(0x00)
        msg.append(0x0f)
        self._send_msg(msg)

    def setProtocol(self, protocol):
        self.protocol = protocol.upper()

    def setPresetPattern(self, pattern, speed):

        PresetPattern.valtostr(pattern)
        if not PresetPattern.valid(pattern):
            #print "Pattern must be between 0x25 and 0x38"
            raise Exception

        delay = Utils.speedToDelay(speed)
        
        pattern_set_msg = bytearray(COMMAND_SET_MODE)
        pattern_set_msg.append(pattern)
        pattern_set_msg.append(delay)
        pattern_set_msg.append(0x0f)

        self._send_msg(pattern_set_msg)

    def getTimers(self):
        msg = bytearray([0x22, 0x2a, 0x2b, 0x0f])
        self._send_msg(msg)
        resp_len = 88
        rx = self._read_msg(resp_len)
        if len(rx) != resp_len:
            print("response too short!")
            raise Exception

        #Utils.dump_data(rx)
        start = 2
        timer_list = []
        #pass in the 14-byte timer structs
        for i in range(6):
          timer_bytes = rx[start:][:14]
          timer = LedTimer(timer_bytes)
          timer_list.append(timer)
          start += 14

        return timer_list

    def sendTimers(self, timer_list):
        # remove inactive or expired timers from list
        for t in timer_list:
            if not t.isActive() or t.isExpired():
                timer_list.remove(t)

        # truncate if more than 6
        if len(timer_list) > 6:
            print("too many timers, truncating list")
            del timer_list[6:]

        # pad list to 6 with inactive timers
        if len(timer_list) != 6:
            for i in range(6-len(timer_list)):
                timer_list.append(LedTimer())

        msg_start = bytearray([0x21])
        msg_end = bytearray([0x00, 0xf0])
        msg = bytearray()

        # build message
        msg.extend(msg_start)
        for t in timer_list:
            msg.extend(t.toBytes())
        msg.extend(msg_end)
        self._send_msg(msg)

        # not sure what the resp is, prob some sort of ack?
        rx = self._read_msg(1)
        rx = self._read_msg(3)

    def setCustomPattern(self, rgb_list, speed, transition_type):
        # truncate if more than 16
        if len(rgb_list) > 16:
            print("too many colors, truncating list")
            del rgb_list[16:]

        # quit if too few
        if len(rgb_list) == 0:
            print("no colors, aborting")
            return

        msg = bytearray()

        first_color = True
        for rgb in rgb_list:
            if first_color:
                lead_byte = 0x51
                first_color = False
            else:
                lead_byte = 0
            r,g,b = rgb
            msg.extend(bytearray([lead_byte, r,g,b]))

        # pad out empty slots
        if len(rgb_list) != 16:
            for i in range(16-len(rgb_list)):
                msg.extend(bytearray([0, 1, 2, 3]))

        msg.append(0x00)
        msg.append(Utils.speedToDelay(speed))

        if transition_type =="gradual":
            msg.append(0x3a)
        elif transition_type =="jump":
            msg.append(0x3b)
        elif transition_type =="strobe":
            msg.append(0x3c)
        else:
            #unknown transition string: using 'gradual'
            msg.append(0x3a)
        msg.append(0xff)
        msg.append(0x0f)

        self._send_msg(msg)

    def refreshState(self):
        return self.update_state()

