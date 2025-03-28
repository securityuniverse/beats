import socket
import ssl
import unittest
import pytest

from filebeat import BaseTest
from os import path

NUMBER_OF_EVENTS = 2

CURRENT_PATH = path.dirname(__file__)
CERTPATH = path.abspath(path.join(CURRENT_PATH, "config/certificates"))


# Self signed certificate used without mutual and failing scenario.
CERTIFICATE1 = path.join(CERTPATH, "beats1.crt")
KEY1 = path.join(CERTPATH, "beats1.key")

CERTIFICATE2 = path.join(CERTPATH, "beats2.crt")
KEY2 = path.join(CERTPATH, "beats2.key")


# Valid self signed certificate used for mutual auth.
CACERT = path.join(CERTPATH, "cacert.crt")

CLIENT1 = path.join(CERTPATH, "client1.crt")
CLIENTKEY1 = path.join(CERTPATH, "client1.key")

CLIENT2 = path.join(CERTPATH, "client2.crt")
CLIENTKEY2 = path.join(CERTPATH, "client2.key")


class Test(BaseTest):
    """
    Test filebeat TCP input with TLS
    """

    def test_tcp_over_tls_and_verify_valid_server_without_mutual_auth(self):
        """
        Test filebeat TCP with TLS with valid cacert without client auth.
        """
        input_raw = """
- type: tcp
  host: "{host}:{port}"
  enabled: true
  ssl.certificate_authorities: {cacert}
  ssl.certificate: {certificate}
  ssl.key: {key}
  ssl.client_authentication: optional
"""
        config = {
            "host": "127.0.0.1",
            "port": 8080,
            "cacert": CERTIFICATE1,
            "certificate": CERTIFICATE1,
            "key": KEY1
        }

        input_raw = input_raw.format(**config)

        self.render_config_template(
            input_raw=input_raw,
            inputs=False,
        )

        filebeat = self.start_beat()
        self.addCleanup(filebeat.kill_and_wait)

        self.wait_until(lambda: self.log_contains(
            "Start accepting connections"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=CERTIFICATE1)
        context.options = ssl.CERT_REQUIRED
        context.check_hostname = False

        tls = context.wrap_socket(sock, do_handshake_on_connect=True)
        tls.connect((config.get('host'), config.get('port')))

        for n in range(0, NUMBER_OF_EVENTS):
            tls.send(bytes("Hello World: " + str(n) + "\n", "utf-8"))

        self.wait_until(lambda: self.output_count(
            lambda x: x >= NUMBER_OF_EVENTS))

        filebeat.check_kill_and_wait()

        output = self.read_output()

        self.assert_output(output)

        sock.close()

    def test_tcp_over_tls_and_verify_invalid_server_without_mutual_auth(self):
        """
        Test filebeat TCP with TLS with an invalid cacert and not requiring mutual auth.
        """
        input_raw = """
- type: tcp
  host: "{host}:{port}"
  enabled: true
  ssl.certificate_authorities: {cacert}
  ssl.certificate: {certificate}
  ssl.key: {key}
  ssl.client_authentication: optional
"""
        config = {
            "host": "127.0.0.1",
            "port": 8080,
            "cacert": CERTIFICATE1,
            "certificate": CERTIFICATE1,
            "key": KEY1
        }

        input_raw = input_raw.format(**config)

        self.render_config_template(
            input_raw=input_raw,
            inputs=False,
        )

        filebeat = self.start_beat()
        self.addCleanup(filebeat.kill_and_wait)

        self.wait_until(lambda: self.log_contains(
            "Start accepting connections"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP
        context = ssl.create_default_context()
        context.load_verify_locations(capath=CERTIFICATE2)
        context.options = ssl.CERT_REQUIRED
        context.check_hostname = False

        tls = context.wrap_socket(sock, do_handshake_on_connect=True, server_hostname=None)
        with pytest.raises(ssl.SSLError):
            tls.connect((config.get('host'), config.get('port')))

        sock.close()

    def test_tcp_over_tls_mutual_auth_fails(self):
        """
        Test filebeat TCP with TLS with default setting to enforce client auth, with bad client certificates
        """
        input_raw = """
- type: tcp
  host: "{host}:{port}"
  enabled: true
  ssl.certificate_authorities: {cacert}
  ssl.certificate: {certificate}
  ssl.key: {key}
"""
        config = {
            "host": "127.0.0.1",
            "port": 8080,
            "cacert": CERTIFICATE1,
            "certificate": CERTIFICATE1,
            "key": KEY1
        }

        input_raw = input_raw.format(**config)

        self.render_config_template(
            input_raw=input_raw,
            inputs=False,
        )

        filebeat = self.start_beat()
        self.addCleanup(filebeat.kill_and_wait)

        self.wait_until(lambda: self.log_contains(
            "Start accepting connections"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        context = ssl.create_default_context()
        context.load_verify_locations(capath=CERTIFICATE1)
        context.options = ssl.CERT_REQUIRED
        context.check_hostname = False

        tls = context.wrap_socket(sock, do_handshake_on_connect=True, server_hostname=None)

        with pytest.raises(ssl.SSLError):
            tls.connect((config.get('host'), config.get('port')))
            # In TLS 1.3 authentication failures are not detected by the initial
            # connection and handshake. For the client to detect that authentication
            # has failed (at least in python) it must wait for a server response
            # so that the failure can be reported as an exception when it arrives.
            tls.recv(1)

        sock.close()

    def test_tcp_over_tls_mutual_auth_succeed(self):
        """
        Test filebeat TCP with TLS when enforcing client auth with good client certificates.
        """
        input_raw = """
- type: tcp
  host: "{host}:{port}"
  enabled: true
  ssl.certificate_authorities: {cacert}
  ssl.certificate: {certificate}
  ssl.key: {key}
  ssl.client_authentication: required
"""
        config = {
            "host": "127.0.0.1",
            "port": 8080,
            "cacert": CACERT,
            "certificate": CLIENT1,
            "key": CLIENTKEY1,
        }

        input_raw = input_raw.format(**config)

        self.render_config_template(
            input_raw=input_raw,
            inputs=False,
        )

        filebeat = self.start_beat()
        self.addCleanup(filebeat.kill_and_wait)

        self.wait_until(lambda: self.log_contains(
            "Start accepting connections"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(CACERT)
        context.load_cert_chain(certfile=CLIENT2, keyfile=CLIENTKEY2)
        context.check_hostname = False

        tls = context.wrap_socket(sock, server_side=False)

        tls.connect((config.get('host'), config.get('port')))

        for n in range(0, NUMBER_OF_EVENTS):
            tls.send(bytes("Hello World: " + str(n) + "\n", "utf-8"))

        self.wait_until(lambda: self.output_count(
            lambda x: x >= NUMBER_OF_EVENTS))

        filebeat.check_kill_and_wait()

        output = self.read_output()

        self.assert_output(output)

        sock.close()

    def test_tcp_tls_with_a_plain_text_socket(self):
        """
        Test filebeat TCP with TLS with a plain text connection.
        """
        input_raw = """
- type: tcp
  host: "{host}:{port}"
  enabled: true
  ssl.certificate_authorities: {cacert}
  ssl.certificate: {certificate}
  ssl.key: {key}
  ssl.client_authentication: required
"""
        config = {
            "host": "127.0.0.1",
            "port": 8080,
            "cacert": CERTIFICATE1,
            "certificate": CERTIFICATE1,
            "key": KEY1
        }

        input_raw = input_raw.format(**config)

        self.render_config_template(
            input_raw=input_raw,
            inputs=False,
        )

        filebeat = self.start_beat()
        self.addCleanup(filebeat.kill_and_wait)

        self.wait_until(lambda: self.log_contains(
            "Start accepting connections"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)  # TCP
        sock.connect((config.get('host'), config.get('port')))

        # The TLS handshake will close the connection, resulting in a broken pipe.
        # no events should be written on disk.
        with pytest.raises(IOError):
            for n in range(0, 100000):
                sock.send(bytes("Hello World: " + str(n) + "\n", "utf-8"))

        filebeat.check_kill_and_wait()

        assert path.isfile(path.join(self.working_dir, "output/" + self.beat_name)) is False

        sock.close()

    def assert_output(self, output):
        assert len(output) == 2
        assert output[0]["input.type"] == "tcp"

    def test_tcp_over_tls_mutual_auth_rfc6587_framing(self):
        """
        Test filebeat TCP with TLS when enforcing client auth with good client certificates and rfc6587 framing.
        """
        input_raw = """
- type: tcp
  host: "{host}:{port}"
  enabled: true
  framing: rfc6587
  ssl.certificate_authorities: {cacert}
  ssl.certificate: {certificate}
  ssl.key: {key}
  ssl.client_authentication: required
"""
        config = {
            "host": "127.0.0.1",
            "port": 8080,
            "cacert": CACERT,
            "certificate": CLIENT1,
            "key": CLIENTKEY1,
        }

        input_raw = input_raw.format(**config)

        self.render_config_template(
            input_raw=input_raw,
            inputs=False,
        )

        filebeat = self.start_beat()
        self.addCleanup(filebeat.kill_and_wait)

        self.wait_until(lambda: self.log_contains(
            "Start accepting connections"))

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(CACERT)
        context.load_cert_chain(certfile=CLIENT2, keyfile=CLIENTKEY2)
        context.check_hostname = False

        tls = context.wrap_socket(sock)

        tls.connect((config.get('host'), config.get('port')))

        for n in range(0, NUMBER_OF_EVENTS):
            tls.send(bytes("14 Hello World: " + str(n), "utf-8"))

        self.wait_until(lambda: self.output_count(
            lambda x: x >= NUMBER_OF_EVENTS))

        filebeat.check_kill_and_wait()

        output = self.read_output()

        self.assert_output(output)

        sock.close()
