import ast
import unittest

from embodied_demo import MicroPythonSession


class FakePort:
    def __init__(self, response):
        self.response = response
        self.data = bytearray()
        self.writes = []

    @property
    def in_waiting(self):
        return len(self.data)

    def write(self, data):
        self.writes.append(data)
        call = ast.parse(data.decode().strip()).body[0].value
        marker = ast.literal_eval(call.args[0])
        if self.response is not None:
            self.data.extend((marker+' '+repr(self.response)+'\r\n').encode())

    def read(self, count):
        result = self.data[:count]
        del self.data[:count]
        return result


class DemoProtocolTests(unittest.TestCase):
    def session(self, response):
        session = MicroPythonSession.__new__(MicroPythonSession)
        session.port = FakePort(response)
        session.record = lambda *args,**kwargs: None
        session.failed = False
        return session

    def test_string_chip_id_and_dictionary_feedback(self):
        for value in ('70af092aeee8',{'command_counts':{1:[307,287,297],2:[307,307,307]}},True):
            session = self.session(value)
            self.assertEqual(session.rpc('d.status()'),value)

    def test_timeout_prevents_further_writes(self):
        session = self.session(None)
        with self.assertRaises(TimeoutError):
            session.rpc('d.status()',timeout=.001)
        with self.assertRaises(RuntimeError):
            session.rpc('d.run_segment((307,287,297),(307,307,307))')
        self.assertEqual(len(session.port.writes),1)
