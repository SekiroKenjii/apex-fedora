"""Private, metadata-only Accounts/fprintd fixtures for the complete GTK dialog."""
import os
import sys
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib

DBusGMainLoop(set_as_default=True)
ADDRESS = os.environ['DBUS_SYSTEM_BUS_ADDRESS']
IFACE = 'net.reactivated.Fprint.Device'
PATH = '/net/reactivated/Fprint/Device/0'
COUNTS = {}
owner = None
delay = 0
fingerprint = None


class Properties(dbus.service.Object):
    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='s', out_signature='a{sv}')
    def GetAll(self, interface):
        return self.properties.get(interface, {})

    @dbus.service.method('org.freedesktop.DBus.Properties', in_signature='ss', out_signature='v')
    def Get(self, interface, name):
        return self.properties[interface][name]


class Accounts(Properties):
    def __init__(self, bus):
        super().__init__(bus, '/org/freedesktop/Accounts')
        self.properties = {'org.freedesktop.Accounts': {'HasNoUsers': False}}

    @dbus.service.method('org.freedesktop.Accounts', in_signature='', out_signature='ao')
    def ListCachedUsers(self):
        return ['/org/freedesktop/Accounts/User1000']

    @dbus.service.method('org.freedesktop.Accounts', in_signature='s', out_signature='o')
    def FindUserByName(self, name):
        assert name == 'builder'
        return '/org/freedesktop/Accounts/User1000'

    @dbus.service.method('org.freedesktop.Accounts', in_signature='x', out_signature='o')
    def FindUserById(self, uid):
        assert uid == os.getuid()
        return '/org/freedesktop/Accounts/User1000'


class User(Properties):
    def __init__(self, bus):
        super().__init__(bus, '/org/freedesktop/Accounts/User1000')
        self.properties = {'org.freedesktop.Accounts.User': {
            'Uid': dbus.UInt64(os.getuid()), 'UserName': 'builder', 'RealName': 'GTK test',
            'LocalAccount': True, 'SystemAccount': False, 'AccountType': dbus.Int32(0),
            'HomeDirectory': '/nonexistent', 'Shell': '/bin/bash', 'Locked': False,
            'PasswordMode': dbus.Int32(0), 'AutomaticLogin': False}}


def error(name):
    return dbus.exceptions.DBusException('fixture ' + name, name='net.reactivated.Fprint.Error.' + name)


class Fingerprint(Properties):
    def __init__(self):
        self.bus = dbus.bus.BusConnection(ADDRESS)
        self.name = dbus.service.BusName('net.reactivated.Fprint', self.bus)
        super().__init__(self.bus, PATH)
        self.properties = {IFACE: {'name': 'Virtual ELAN', 'scan-type': 'swipe',
                                  'num-enroll-stages': dbus.Int32(5)}}
        self.manager = Manager(self.bus)

    @dbus.service.method(IFACE, in_signature='s', out_signature='', sender_keyword='sender')
    def Claim(self, username, sender=None):
        global owner
        COUNTS['Claim'] = COUNTS.get('Claim', 0) + 1
        if owner is not None:
            COUNTS['AlreadyInUse'] = COUNTS.get('AlreadyInUse', 0) + 1
            raise error('AlreadyInUse')
        owner = sender

    @dbus.service.method(IFACE, in_signature='', out_signature='', sender_keyword='sender')
    def Release(self, sender=None):
        global owner
        if owner != sender:
            raise error('ClaimDevice')
        owner = None
        COUNTS['Release'] = COUNTS.get('Release', 0) + 1

    @dbus.service.method(IFACE, in_signature='s', out_signature='as')
    def ListEnrolledFingers(self, username):
        return []

    @dbus.service.method(IFACE, in_signature='s', out_signature='', sender_keyword='sender')
    def EnrollStart(self, finger, sender=None):
        if owner != sender:
            raise error('ClaimDevice')
        COUNTS['EnrollStart'] = COUNTS.get('EnrollStart', 0) + 1

    @dbus.service.method(IFACE, in_signature='', out_signature='', async_callbacks=('reply', 'fail'))
    def EnrollStop(self, reply, fail):
        COUNTS['EnrollStop'] = COUNTS.get('EnrollStop', 0) + 1
        if delay:
            GLib.timeout_add(delay, lambda: (reply(), False)[1])
        else:
            reply()

    @dbus.service.signal(IFACE, signature='sb')
    def EnrollStatus(self, status, done):
        pass


class Manager(dbus.service.Object):
    def __init__(self, bus):
        super().__init__(bus, '/net/reactivated/Fprint/Manager')

    @dbus.service.method('net.reactivated.Fprint.Manager', in_signature='', out_signature='ao')
    def GetDevices(self):
        return [PATH]


class Control(dbus.service.Object):
    @dbus.service.method('org.apex.FingerprintTest', in_signature='s', out_signature='u')
    def Count(self, method):
        return int(owner is not None) if method == 'Owners' else COUNTS.get(method, 0)

    @dbus.service.method('org.apex.FingerprintTest', in_signature='s', out_signature='')
    def Status(self, status):
        assert status == 'enroll-disconnected'
        fingerprint.EnrollStatus(status, True)

    @dbus.service.method('org.apex.FingerprintTest', in_signature='u', out_signature='')
    def DelayStop(self, milliseconds):
        global delay
        assert milliseconds <= 1000
        delay = int(milliseconds)

    @dbus.service.method('org.apex.FingerprintTest', in_signature='', out_signature='')
    def Replace(self):
        global owner
        fingerprint.bus.close()
        owner = None

        def replace():
            global fingerprint
            fingerprint = Fingerprint()
            return False
        GLib.timeout_add(300, replace)


def main():
    global fingerprint
    if (os.geteuid() == 0 or not os.path.isfile('/etc/apex-builder')
            or ADDRESS == 'unix:path=/run/dbus/system_bus_socket'):
        raise RuntimeError('Use an unprivileged private bus inside the builder')
    bus = dbus.bus.BusConnection(ADDRESS)
    accounts_name = dbus.service.BusName('org.freedesktop.Accounts', bus)
    control_name = dbus.service.BusName('org.apex.FingerprintTest', bus)
    accounts, user = Accounts(bus), User(bus)
    control = Control(bus, '/org/apex/FingerprintTest')
    fingerprint = Fingerprint()
    print('READY', flush=True)
    GLib.MainLoop().run()


if __name__ == '__main__':
    main()
