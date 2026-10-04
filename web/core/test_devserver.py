#!/usr/bin/env python3
"""Port-holder test for the web engine's dev-server manager — headless.

`serve` and `stop` free the tester port through kill_port(), which signals the
whole process GROUP of every pid pids_on_port() returns. So that lookup must
name the port's listener and nothing else: a browser with the app open holds a
connection to the port too, and treating it as a holder closed the developer's
browser on every (re)start.

The engine is loaded by path under its own module name with a stub `target`,
so it never collides with the mobile engine's `devserver` in one pytest run.

Run:  python3 web/core/test_devserver.py    (or `python3 -m pytest -q`)
"""
import importlib.util
import os
import shutil
import socket
import subprocess
import sys
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))


def _load_engine():
    stub = types.ModuleType("target")
    stub.TESTER_PORT = 0
    saved = sys.modules.get("target")
    sys.modules["target"] = stub
    try:
        spec = importlib.util.spec_from_file_location(
            "web_devserver", os.path.join(HERE, "devserver.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        if saved is None:
            del sys.modules["target"]
        else:
            sys.modules["target"] = saved
    return mod


devserver = _load_engine()


class PortHolderTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("lsof"), "needs lsof")
    def test_a_connected_client_is_not_a_port_holder(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        port = srv.getsockname()[1]
        client = subprocess.Popen(
            [sys.executable, "-c",
             "import socket, sys, time\n"
             "s = socket.create_connection(('127.0.0.1', int(sys.argv[1])))\n"
             "print('up', flush=True)\n"
             "time.sleep(60)", str(port)],
            stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(client.stdout.readline().strip(), "up")
            conn, _ = srv.accept()
            devserver.target.TESTER_PORT = port
            try:
                pids = devserver.pids_on_port()
            finally:
                conn.close()
            self.assertIn(os.getpid(), pids)
            self.assertNotIn(client.pid, pids)
        finally:
            client.kill()
            client.wait()
            client.stdout.close()
            srv.close()


if __name__ == "__main__":
    unittest.main()
