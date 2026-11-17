from types import SimpleNamespace
import unittest
from unittest.mock import patch

from camera_server import reconnect_camera


class ReconnectTests(unittest.TestCase):
    def test_old_camera_closes_before_replacement_starts(self):
        actions = []
        previous = SimpleNamespace(stopped=True,close=lambda:actions.append('close'))
        server = SimpleNamespace(camera=previous)
        replacement = SimpleNamespace(get_frame=lambda timeout:(b'jpeg',1))
        args = SimpleNamespace(ffmpeg='ffmpeg',device='camera',fps=10,width=1280)
        stopped = SimpleNamespace(wait=__import__('unittest').mock.Mock(side_effect=[False,True]))
        def create(*values):
            actions.append('open')
            self.assertEqual(actions,['close','open'])
            return replacement
        with patch('camera_server.Camera',side_effect=create):
            reconnect_camera(server,args,stopped)
        self.assertIs(server.camera,replacement)
