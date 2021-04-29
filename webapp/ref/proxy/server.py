import socket
import ctypes
import enum
import json
import socks
import os
import time

from typing import Tuple, Optional
from threading import Lock, Thread
from flask import Flask, current_app
from werkzeug.local import LocalProxy
from types import SimpleNamespace
from select import select
from collections import namedtuple

from ref.model import Instance
from dataclasses import dataclass

log = LocalProxy(lambda: current_app.logger)

# Maximum message body size we accept.
MAX_MESSAGE_SIZE = 4096

# Number of bytes we try to read from a socket at once.
CHUNK_SIZE = 4096

# How often should a worker print connection related stats?
WORKER_STATS_INTERVAL = 120

class MessageType(enum.Enum):
    PROXY_REQUEST = 0
    SUCCESS = 50
    FAILURE = 51

class MessageHeader(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
            ('msg_type', ctypes.c_byte),
            ('len', ctypes.c_uint32.__ctype_be__)
        ]

    def __str__(self):
        return f'MessageHeader(msg_type: {self.msg_type}, len: {self.len})'

class SuccessMessage(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
            ('msg_type', ctypes.c_byte),
            ('len', ctypes.c_uint32.__ctype_be__)
        ]

    def __init__(self):
        self.msg_type = MessageType.SUCCESS.value
        self.len = 0

class ErrorMessage(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
            ('msg_type', ctypes.c_byte),
            ('len', ctypes.c_uint32.__ctype_be__)
        ]

    def __init__(self):
        self.msg_type = MessageType.FAILURE.value
        self.len = 0

class ProxyWorker:

    def __init__(self, server: 'ProxyServer', socket: socket.socket, addr: Tuple[str, int]):
        self.server = server
        self.client_socket = socket
        self.addr = addr
        self.dst_socket: socket.socket = None
        self.thread = None
        self.last_stats_ts = time.monotonic()

    def _clean_up(self):
        self.client_socket.close()
        if self.dst_socket:
            self.dst_socket.close()

    def _recv_all(self, expected_len, timeout=10):
        assert expected_len > 0
        assert self.client_socket.getblocking()

        while True:
            self.client_socket.settimeout(timeout)

            # Read the header send by the client.
            data = bytearray()
            while True:
                try:
                    buf = self.client_socket.recv(expected_len - len(data))
                except TimeoutError:
                    log.debug('Client timed out...')
                    return None

                if len(buf) > 0:
                    data.extend(buf)
                else:
                    # Got EOF
                    if len(data) == expected_len:
                        return data
                    else:
                        log.debug(f'Got EOF after {len(data)} bytes, but expected {expected_len} bytes.')
                        return None

    def _handle_proxy_request(self, header: MessageHeader) -> Optional[Tuple[Instance, str, int]]:
        # Receive the rest of the message.
        if header.len > MAX_MESSAGE_SIZE:
            log.warning(f'Header len field value is to big!')
            return False

        # This is JSON, so now byte swapping required.
        request = self._recv_all(header.len)
        if request is None:
            return False

        # TODO: Check signature and unwrap the message.

        try:
            request = json.loads(request, object_hook=lambda d: SimpleNamespace(**d))
            log.debug(f'Got request: {request}')

            # Access all expected attributes, thus it is clear what caused the error
            # in case a call raises.
            msg_type = request.msg_type
            instance_id = int(request.instance_id)
            dst_ip = str(request.dst_ip)
            dst_port = int(request.dst_port)

            # Recheck the signed type
            if msg_type != MessageType.PROXY_REQUEST.name:
                log.warning(f'Outer and inner message type do not match!')
                return False

            return instance_id, dst_ip, dst_port

        except:
            log.warning(f'Received malformed message body', exc_info=True)
            return False


    def _connect_to_proxy(self, instance: Instance, dst_ip: str, dst_port: int) -> Optional[bool]:
        log.debug(f'Trying to establish proxy connection to dst_ip={dst_ip}, dst_port={dst_port}')
        socket_path = instance.entry_service.shared_folder + '/socks_proxy'

        try:
            # We must use `create_connection` to establish the connection since its the
            # only function of the patched `pysocks` library that supports proxing through
            # a unix domain socket.
            # https://github.com/nbars/PySocks/tree/hack_unix_domain_socket_file_support
            self.dst_socket = socks.create_connection((dst_ip, dst_port), timeout=30, proxy_type=socks.SOCKS5, proxy_addr=socket_path)
            self.dst_socket.setblocking(False)
        except Exception as e:
            log.debug(f'Failed to connect {dst_ip}:{dst_port}@{socket_path}. e={e}')
            return None

        return True

    def _proxy_forever(self):
        self.client_socket.setblocking(False)
        self.dst_socket.setblocking(False)

        client_fd = self.client_socket.fileno()
        dst_fd = self.dst_socket.fileno()

        fdname = {
            client_fd: 'client',
            dst_fd: 'dst_fd'
        }

        @dataclass
        class ConnectionState:
            fd: int
            data_received: bytearray
            eof: bool
            bytes_written: int = 0
            bytes_read: int = 0
            wakeups: int = 0
            start_ts: float = time.monotonic()

        client_state = ConnectionState(client_fd, bytearray(), False)
        dst_state = ConnectionState(dst_fd, bytearray(), False)

        def read(from_: ConnectionState):
            assert not from_.eof
            data = os.read(from_.fd, CHUNK_SIZE)
            if len(data) > 0:
                from_.bytes_read += len(data)
                from_.data_received.extend(data)
            else:
                from_.eof = True

        def write(to: ConnectionState, from_: ConnectionState):
            assert len(from_.data_received) > 0
            try:
                bytes_written = os.write(to.fd, from_.data_received)
            except BrokenPipeError:
                return False
            assert bytes_written >= 0
            to.bytes_written += bytes_written
            from_.data_received = from_.data_received[bytes_written:]
            return True

        def maybe_print_stats(state: ConnectionState):
            # TODO: User state structure for whole worker.

            if (time.monotonic() - self.last_stats_ts) > WORKER_STATS_INTERVAL:
                # Print the stats
                cname = self.client_socket.getpeername()
                dname = self.dst_socket.getpeername()

                send = state.bytes_written / 1024
                send_suff = 'KiB'
                recv = state.bytes_read / 1024
                recv_suff = 'KiB'

                if send >= 1024:
                    send = send / 1024
                    send_suff = 'MiB'
                    recv = recv
                    recv_suff = 'MiB'

                # TODO: Calculate this over a short period of time.
                wakeups_per_s = state.wakeups / (time.monotonic() - state.start_ts)

                msg = f'\n{cname} <--> {dname}\n  => Send: {send:.2f} {send_suff}\n  => Received: {recv:.2f} {recv_suff}'
                msg += f'\n  => {wakeups_per_s:.2f} Weakeups/s'
                log.info(msg)

                self.last_stats_ts = time.monotonic()

        while True:
            # We only wait for an fd to become writeable if we have data to write.
            write_set = set()
            if len(client_state.data_received) > 0:
                write_set.add(dst_state.fd)
            if len(dst_state.data_received) > 0:
                write_set.add(client_state.fd)
            write_set = list(write_set)

            # If the fd signaled EOF, we do not select them for reading anymore,
            # since there is no data we can receive anymore.
            read_set = set([client_state.fd, dst_state.fd])
            if client_state.eof:
                read_set.remove(client_state.fd)
            if dst_state.eof:
                read_set.remove(dst_state.fd)

            # Wait for some fd to get ready
            timeout = current_app.config['SSH_PROXY_CONNECTION_TIMEOUT']
            ready_read, ready_write, _ = select(read_set, write_set, [], timeout)
            if not len(ready_read) and not len(ready_write):
                log.debug(f'Timeout after {timeout} seconds.')
                break

            maybe_print_stats(client_state)

            if client_state.fd in ready_read or client_state.fd in ready_write:
                client_state.wakeups += 1

            if dst_state.fd in ready_read or dst_state.fd in ready_write:
                dst_state.wakeups += 1

            #ready_read_dbg = sorted([fdname[v] for v in ready_read])
            #ready_write_dbg = sorted([fdname[v] for v in ready_write])
            #log.debug(f'ready_read={ready_read_dbg}, ready_write={ready_write_dbg}')

            # Check if we have anything to read.
            if client_state.fd in ready_read:
                read(client_state)

            if dst_state.fd in ready_read:
                read(dst_state)

            # Check if we have anything to send.
            # We do not use the ready_write set here on purpose, since
            # we might received data in the `read` calls above. So,
            # we just try to send the data, and if the destination is not
            # ready, it will just reject the write (i.e., return 0).
            if len(dst_state.data_received) > 0:
                ret = write(client_state, dst_state)
                if not ret:
                    break

            if len(client_state.data_received) > 0:
                ret = write(dst_state, client_state)
                if not ret:
                    break


    def run(self, app: Flask):
        # TODO: Spawn thread and join?
        self.thread = Thread(target=self.__run1, args=[app])
        self.thread.start()

    def __run1(self, app):
        with app.app_context():
            try:
                self.__run2()
                log.debug(f'[{self.addr}] Terminating worker')
                self._clean_up()
            except:
                log.error(f'Unexpected error', exc_info=True)

    def __run2(self):
        # Receive the initial message
        self.client_socket.settimeout(30)

        # Read the header send by the client.
        log.debug(f'Receiving header...')
        header = self._recv_all(ctypes.sizeof(MessageHeader))
        if not header:
            return

        header = MessageHeader.from_buffer(header)
        log.debug(f'Got header={header}')

        if header.msg_type == MessageType.PROXY_REQUEST.value:
            log.debug(f'Got {MessageType.PROXY_REQUEST} request.')
            success = self._handle_proxy_request(header)
            if not success:
                # Hadling of the proxy request failed.
                return

            instance_id, dst_ip, dst_port = success

            # Check if we have an instance with the given ID.
            instance = Instance.get(instance_id)
            if not instance:
                log.warning(f'Got request for non existing instance.')
                return
            current_app.db.session.rollback()

            # log.debug(f'Request is for instance {instance}')
            success = self._connect_to_proxy(instance, dst_ip, dst_port)
            if success is None:
                self.client_socket.sendall(bytearray(ErrorMessage()))
                return

            self.client_socket.sendall(bytearray(SuccessMessage()))
            self._proxy_forever()

        else:
            log.warning(f'Unknown message {header.msg_type}')
            return


class ProxyServer:

    def __init__(self, app: Flask):
        self.app = app
        self.lock = Lock()
        self.workers: list['ProxyWorker'] = []
        self.port = app.config['SSH_PROXY_LISTEN_PORT']

    def loop(self):
        log.info(f'Starting SSH Proxy on port {self.port}.')

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        # Bind to port 8001 on all interfaces.
        sock.bind(('', self.port))
        sock.listen(current_app.config['SSH_PROXY_BACKLOG_SIZE'])

        # Lets start to accept new connections
        while True:
            con, addr = sock.accept()
            # FIXME: Check if port forwarding is enabled.


            # FIXME: Remove worker if terminated
            # FIXME: Limit number of workers.
            with self.lock:
                worker = ProxyWorker(self, con, addr)
                self.workers.append(worker)
                log.debug(f'Spawing new worker (total={len(self.workers)})')
                worker.run(self.app)

def server_loop(app: Flask):
    with app.app_context():
        server = ProxyServer(app)
        server.loop()



    """
    Message types (FIXME: Signed):
    {
        "type": REQUEST_PROXING_TO
        "args": {
            "instance_id": u64,
            "dst_ip": str,
            "dst_por": str
        }
    }

    {
        "type": "RESULT",
        "args": {
            "success:" bool,
            "log_msg": str
        }
    }
     -> If success == True -> this socket is from now on proxing all traffic to
     the desired target.
    """

"""
    socket_path = instance.entry_service.shared_folder + '/socks_proxy'
    # t = threading.Thread(target=_proxy_worker_loop, args=[current_app._get_current_object(), q, socket_path, dst_ip, dst_port, client_fd])
    # t.start()
    # t.join()

    _proxy_worker_loop(current_app._get_current_object(), q, socket_path, dst_ip, dst_port, client_fd)

    return error_response("Error bla")

def _proxy_worker_loop(app, ipc_queue, socket_path, dst_ip, dst_port, client_fd):
    dst_socket = None

    try:
        # We must use `create_connection` to establish the connection since its the
        # only function of the patched `pysocks` library that supports proxing through
        # a unix domain socket.
        # https://github.com/nbars/PySocks/tree/hack_unix_domain_socket_file_support
        dst_socket = socks.create_connection((dst_ip, dst_port), timeout=30, proxy_type=socks.SOCKS5, proxy_addr=socket_path)
        dst_socket.setblocking(False)
    except Exception as e:
        with app.app_context():
            log.info(f'Failed to connect {dst_ip}:{dst_port}@{socket_path}. e={e}')
        ipc_queue.put(False)
        os.close(client_fd)
        return

    # Buffers for data send by ether side
    c_to_dst = Queue()
    dst_to_c = Queue()

    # The fds of the sockets used for select/epoll
    dst_fd = dst_socket.fileno()

    # client_socket = socket.fromfd(client_fd, socket.AF_INET, socket.SOCK_STREAM)
    # client_socket.setblocking(False)

    client_eof = False
    dst_eof = False

    try:
        while True:
            write_fd_set = set()
            if not c_to_dst.empty():
                write_fd_set.add(dst_fd)
            if not dst_to_c.empty():
                write_fd_set.add(client_fd)

            # FIXME: Limit amount of data send?
            # FIXME: Make timeout configurable.

            with app.app_context():
                log.debug(f'rset={[client_fd, dst_fd]}')
            rread, rwrite, _  = select.select([client_fd, dst_fd], list(write_fd_set), [], 60)
            if not rread and not rwrite:
                with app.app_context():
                    log.debug('Timeout reached!')
                break

            with app.app_context():
                log.debug(f'rread={rread}, rwrite={rwrite}')

            # Handle readable fds
            if client_fd in rread:
                data = os.read(client_fd, 1024)
                with app.app_context():
                    log.debug(f'Reading len(data)={len(data)} bytes from client.')
                if data:
                    for b in data:
                        c_to_dst.put(b)
                else:
                    client_eof = True

            if dst_fd in rread:
                data = os.read(dst_fd, 1024)
                with app.app_context():
                    log.debug(f'Reading len(data)={len(data)} bytes from dst.')
                if data:
                    for b in data:
                        dst_to_c.put(b)
                else:
                    dst_eof = True

            data_written = False

            # Handle writeable fds
            # FIXME: Use bytearrays instead of send byte by byte.
            if client_fd in rwrite and not dst_to_c.empty():
                b = dst_to_c.get()
                if b != 'EOF':
                    ret = os.write(client_fd, bytes([b]))
                    data_written = True
                    if ret <= 0:
                        # Failed
                        raise Exception('Failed to write data.')

            if dst_fd in rwrite and not c_to_dst.empty():
                b = c_to_dst.get()
                if b != 'EOF':
                    ret = os.write(dst_fd, bytes([b]))
                    data_written = True
                    if ret <= 0:
                        # Failed
                        raise Exception('Failed to write data.')

            if not data_written and (client_eof or dst_eof):
                # Terminate this session if one side indicated eof
                # and we did not send any data.
                break


    except:
        with app.app_context():
            log.debug('Error', exc_info=True)

    os.close(client_fd)
    os.close(dst_fd)

    ipc_queue.put(True)
"""