#!/usr/bin/env python

class BuiltInTimer():
    sunrise = 0xA1
    sunset = 0xA2

    @staticmethod
    def valid(byte_value):
        return byte_value == BuiltInTimer.sunrise or byte_value == BuiltInTimer.sunset

    @staticmethod
    def valtostr(pattern):
        for key, value in list(BuiltInTimer.__dict__.items()):
            if type(value) is int and value == pattern:
                return key.replace("_", " ").title()
        return None
