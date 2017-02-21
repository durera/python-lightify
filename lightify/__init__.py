#!/usr/bin/python
#
# Copyright 2014 Mikael Magnusson
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

#
# WIP Python module for Osram lightify
# Communicates with a gateway connected to the same LAN via TCP port 4000
# using a binary protocol
#

import binascii
import socket
import struct
import logging

__version__ = '1.0.3'

MODULE = __name__
PORT = 4000

COMMAND_ALL_LIGHT_STATUS = 0x13
COMMAND_GROUP_LIST = 0x1e
COMMAND_GROUP_INFO = 0x26
COMMAND_LUMINANCE = 0x31
COMMAND_ONOFF = 0x32
COMMAND_TEMP = 0x33
COMMAND_COLOUR = 0x36
COMMAND_LIGHT_STATUS = 0x68

# Commands
# 13 all light status (returns list of light address, light status, light name)
# 1e group list (returns list of group id, and group name)
# 26 group status (returns group id, group name, and list of light addresses)
# 31 set group luminance
# 32 set group onoff
# 33 set group temp
# 36 set group colour
# 68 light status (returns light address and light status (?))


class Luminary(object):
    def __init__(self, conn, logger, name):
        self.__logger = logger
        self.__conn = conn
        self.__name = name

    def name(self):
        return self.__name

    def set_onoff(self, on):
        data = self.__conn.build_onoff(self, on)
        self.__conn.send(data)
        self.__conn.recv()

    def set_luminance(self, lum, time):
        data = self.__conn.build_luminance(self, lum, time)
        self.__conn.send(data)
        self.__conn.recv()

    def set_temperature(self, temp, time):
        data = self.__conn.build_temp(self, temp, time)
        self.__conn.send(data)
        self.__conn.recv()

    def set_rgb(self, r, g, b, time):
        data = self.__conn.build_colour(self, r, g, b, time)
        self.__conn.send(data)
        self.__conn.recv()


class Light(Luminary):
    def __init__(self, conn, logger, id, addr, type, name):
        super(Light, self).__init__(conn, logger, name)
        self.__logger = logger
        self.__conn = conn
        self.__id = id
        self.__addr = addr
        self.__type = type

    def id(self):
        return self.__id

    def addr(self):
        return self.__addr

    def mac(self):
        # Convert MAC Address - http://stackoverflow.com/a/11006780
        return '-'.join(format(self.__addr, 'x')[i:i+2] for i in range(0,16,2))

    def type(self):
        return self.__type

    def __str__(self):
        return "<light: %s>" % self.name()

    def update_status(self, fwVersion, online, groupId, status, luminance, temp, red, green, blue, alpha, name):
        self.__fwVersion = fwVersion
        self.__online = online
        self.__groupId = groupId
        self.__on = status
        self.__lum = luminance
        self.__temp = temp
        self.__r = red
        self.__g = green
        self.__b = blue
        self.__alpha = alpha
        self.__name = name

    def fwVersion(self):
        return self.__fwVersion
    
    def online(self):
        return self.__online

    def groupId(self):
        return self.__groupId

    def on(self):
        return self.__on

    def set_onoff(self, on):
        self.__on = on
        super(Light, self).set_onoff(on)
        if self.lum() == 0 and on != 0:
            self.__lum = 1  # This seems to be the default

    def lum(self):
        return self.__lum

    def set_luminance(self, lum, time):
        self.__lum = lum
        super(Light, self).set_luminance(lum, time)
        if lum > 0 and self.__on == 0:
            self.__on = 1
        elif lum == 0 and self.__on != 0:
            self.__on = 0

    def temp(self):
        return self.__temp

    def set_temperature(self, temp, time):
        self.__temp = temp
        super(Light, self).set_temperature(temp, time)

    def rgb(self):
        return (self.red(), self.green(), self.blue())

    def set_rgb(self, r, g, b, time):
        self.__r = r
        self.__g = g
        self.__b = b

        super(Light, self).set_rgb(r, g, b, time)

    def red(self):
        return self.__r

    def green(self):
        return self.__g

    def blue(self):
        return self.__b

    def alpha(self):
        return self.__alpha

    def build_command(self, command, data):
        return self.__conn.build_light_command(command, self, data)


class Group(Luminary):
    def __init__(self, conn, logger, idx, name):
        super(Group, self).__init__(conn, logger, name)
        self.__conn = conn
        self.__logger = logger
        self.__idx = idx
        self.__lights = []

    def idx(self):
        return self.__idx

    def lights(self):
        return self.__lights

    def set_lights(self, lights):
        self.__lights = lights

    def __str__(self):
        s = ""
        for light_addr in self.lights():
            if light_addr in self.__conn.lights():
                light = self.__conn.lights()[light_addr]
            else:
                light = "%x" % light_addr
            s = s + str(light) + " "

        return "<group: %s, lights: %s>" % (self.name(), s)

    def build_command(self, command, data):
        return self.__conn.build_command(command, self, data)


class Lightify:
    def __init__(self, host):
        self.__logger = logging.getLogger(MODULE)
        self.__logger.addHandler(logging.NullHandler())
        self.__logger.info("Logging %s", MODULE)

        self.__seq = 1
        self.__groups = {}
        self.__lights = {}

        self.__sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.__sock.connect((host, PORT))

    def groups(self):
        """Dict from group name to Group object."""
        return self.__groups

    def lights(self):
        """Dict from light addr to Light object."""
        return self.__lights

    def light_byname(self, name):
        self.__logger.debug(len(self.lights()))

        for light in self.lights().itervalues():
            if light.name() == name:
                return light

        return None

    def next_seq(self):
        self.__seq = self.__seq + 1
        return self.__seq

    def build_global_command(self, command, data):
        length = 6 + len(data)
        try:
            result = struct.pack(
                "<H6B",
                length,
                0x02,
                command,
                0,
                0,
                0x7,
                self.next_seq()
            ) + data
        except TypeError:
            # Decode using cp437 for python3. This is not UTF-8
            result = struct.pack(
                "<H6B",
                length,
                0x02,
                command,
                0,
                0,
                0x7,
                self.next_seq()
            ) + data.decode('cp437')

        return result

    def build_basic_command(self, flag, command, group_or_light, data):
        length = 14 + len(data)
        try:
            result = struct.pack(
                "<H6B",
                length,
                flag,
                command,
                0,
                0,
                0x7,
                self.next_seq()
            ) + group_or_light + data
        except TypeError:
            # Decode using cp437 for python3. This is not UTF-8
            result = struct.pack(
                "<H6B",
                length,
                flag,
                command,
                0,
                0,
                0x7,
                self.next_seq()
            ) + group_or_light + data.decode('cp437')

        return result

    def build_command(self, command, group, data):
        # length = 14 + len(data)

        return self.build_basic_command(
            0x02,
            command,
            struct.pack("<8B", group.idx(), 0, 0, 0, 0, 0, 0, 0),
            data)

    def build_light_command(self, command, light, data):
        # length = 6 + 8 + len(data)

        return self.build_basic_command(
            0x00,
            command,
            struct.pack("<Q", light.addr()),
            data
        )

    def build_onoff(self, item, on):
        return item.build_command(COMMAND_ONOFF, struct.pack("<B", on))

    def build_temp(self, item, temp, time):
        return item.build_command(COMMAND_TEMP, struct.pack("<HH", temp, time))

    def build_luminance(self, item, luminance, time):
        return item.build_command(
            COMMAND_LUMINANCE,
            struct.pack("<BH", luminance, time)
        )

    def build_colour(self, item, red, green, blue, time):
        return item.build_command(
            COMMAND_COLOUR,
            struct.pack("<BBBBH", red, green, blue, 0xff, time)
        )

    def build_group_info(self, group):
        return self.build_command(COMMAND_GROUP_INFO, group, "")

    def build_all_light_status(self, flag):
        return self.build_global_command(
            COMMAND_ALL_LIGHT_STATUS,
            struct.pack("<B", flag)
        )

    def build_light_status(self, light):
        return light.build_command(COMMAND_LIGHT_STATUS, "")

    def build_group_list(self):
        return self.build_global_command(COMMAND_GROUP_LIST, "")

    def group_list(self):
        groups = {}
        data = self.build_group_list()
        self.send(data)
        data = self.recv()
        (num,) = struct.unpack("<H", data[7:9])
        self.__logger.debug('Num %d', num)

        for i in range(0, num):
            pos = 9+i*18
            payload = data[pos:pos+18]

            (idx, name) = struct.unpack("<H16s", payload)
            name = name.replace('\0', "")

            groups[idx] = name
            self.__logger.debug("Idx %d: '%s'", idx, name)

        return groups

    def update_group_list(self):
        lst = self.group_list()
        groups = {}

        for (idx, name) in lst.iteritems():
            group = Group(self, self.__logger, idx, name)
            group.set_lights(self.group_info(group))

            groups[name] = group

        self.__groups = groups

    def group_info(self, group):
        lights = []
        data = self.build_group_info(group)
        self.send(data)
        data = self.recv()
        payload = data[7:]
        (idx, name, num) = struct.unpack("<H16sB", payload[:19])
        name = name.replace('\0', "")
        self.__logger.debug("Idx %d: '%s' %d", idx, name, num)
        for i in range(0, num):
            pos = 7 + 19 + i * 8
            payload = data[pos:pos+8]
            (addr,) = struct.unpack("<Q", payload[:8])
            self.__logger.debug("%d: %x", i, addr)

            lights.append(addr)

        # self.read_light_status(addr)
        return lights

    def send(self, data):
        self.__logger.debug('sending "%s"', binascii.hexlify(data))
        return self.__sock.sendall(data)

    def recv(self):
        lengthsize = 2
        data = self.__sock.recv(lengthsize)
        (length,) = struct.unpack("<H", data[:lengthsize])

        self.__logger.debug(len(data))
        string = ""
        expected = length + 2 - len(data)
        self.__logger.debug("Length %d", length)
        self.__logger.debug("Expected %d", expected)

        while expected > 0:
            self.__logger.debug(
                'received "%d %s"',
                length,
                binascii.hexlify(data)
            )
            data = self.__sock.recv(expected)
            expected = expected - len(data)
            try:
                string = string + data
            except TypeError:
                # Decode using cp437 for python3. This is not UTF-8
                string = string + data.decode('cp437')
        self.__logger.debug('received "%s"', string)
        return data

    def update_light_status(self, light):
        data = self.build_light_status(light)
        self.send(data)
        data = self.recv()
        return

        (on, lum, temp, r, g, b, h) = struct.unpack("<27x2BH4B16x", data)
        self.__logger.debug(
            'status: %0x %0x %d %0x %0x %0x %0x', on, lum, temp, r, g, b, h)
        self.__logger.debug('onoff: %d', on)
        self.__logger.debug('temp:  %d', temp)
        self.__logger.debug('lum:   %d', lum)
        self.__logger.debug('red:   %d', r)
        self.__logger.debug('green: %d', g)
        self.__logger.debug('blue:  %d', b)
        return (on, lum, temp, r, g, b)

    def update_all_light_status(self):
        data = self.build_all_light_status(1)
        self.send(data)
        data = self.recv()
        # Unsigned short (H), little endian (<) .. indicates how many rows there are to process
        (num,) = struct.unpack("<H", data[7:9])

        self.__logger.debug('num: %d', num)

        old_lights = self.__lights
        new_lights = {}

        status_len = 50
        for i in range(0, num):
            pos = 9 + i * status_len
            payload = data[pos:pos+status_len]
            
            # ID - unsigned short (2)
            (id,) = struct.unpack("<H", payload[0:2])
            
            # MAC - unsigned long (8)
            (mac,) = struct.unpack("<Q16", payload[2:10])
            
            # Convert MAC Address - http://stackoverflow.com/a/11006780
            macFriendly = '-'.join(format(mac, 'x')[i:i+2] for i in range(0,16,2))
            
            # Type - unsigned char (1)
            (type,) = struct.unpack("<B", payload[10:11])

            # Firmware Version - unsigned int, big endian (1)
            (fwVersion,) = struct.unpack(">I", payload[11:15])
            
            # Online status - unsigned char (1)
            (online,) = struct.unpack("<B", payload[15:16])

            # Group Id - unsigned short (2)
            (groupId,) = struct.unpack("<H", payload[16:18])
            
            # Status - unsigned char (1)
            (status,) = struct.unpack("<B", payload[18:19])
            
            # Brightness, Temperature - unsigned char (1), unsigned short (2)
            (brightness,temp) = struct.unpack("<BH", payload[19:22])

            # Red, Green, Blue, Alpha - unsigned char (1), unsigned char (1), unsigned char (1), unsigned char (1)
            (red, green, blue, alpha) = struct.unpack("<BBBB", payload[22:26])

            name = payload[26:42]
            try:
                name = name.replace('\0', "")
            except TypeError:
                # Decode using cp437 for python3. This is not UTF-8
                name = name.decode('cp437').replace('\0', "")
            
            # No idea what this part of the payload is
            (unknown,) = struct.unpack("<Q", payload[42:50])
            
            self.__logger.debug("id = %s" % id)
            self.__logger.debug("mac = %s" % mac)
            self.__logger.debug("mac friendly = %s" % macFriendly)
            self.__logger.debug("type = %s" % type)
            self.__logger.debug("fw = %s" % fwVersion)
            self.__logger.debug("online = %s" % online)
            self.__logger.debug("groupId = %s" % groupId)
            self.__logger.debug("status = %s" % status)
            self.__logger.debug("brightness = %s" % brightness)
            self.__logger.debug("temp = %s" % temp)
            self.__logger.debug("red green blue = %s %s %s" % (red, green, blue))
            self.__logger.debug("alpha = %s" % alpha)
            self.__logger.debug("name = %s" % name)
            self.__logger.debug("unknown = %s" % unknown)
            
            self.__logger.debug('light: %s %s', macFriendly, name)
            if mac in old_lights:
                light = old_lights[mac]
            else:
                light = Light(self, self.__logger, id, mac, type, name)

            light.update_status(fwVersion, online, groupId, status, brightness, temp, red, green, blue, alpha, name)
            new_lights[mac] = light
        # return (on, lum, temp, r, g, b)

        self.__lights = new_lights
