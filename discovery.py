import asyncio
import ipaddress
import json
import socket
from typing import Optional, Tuple


DISCOVERY_PORT = 25566
DISCOVERY_REQUEST = b"DISCOVER_MY_SERVER"
SERVER_NAME = "NursingVRServer"
PROTOCOL_VERSION = 1


def _is_usable_lan_ipv4(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False

    return (
        ip.version == 4
        and not ip.is_loopback
        and not ip.is_unspecified
        and not ip.is_link_local
        and not ip.is_multicast
    )


def resolve_lan_ipv4(client_ip: str) -> Optional[str]:
    """Return the local IPv4 Windows would use to reach this client."""
    route_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # UDP connect performs route selection without sending a packet. Using the
        # requester's address makes the OS prefer the interface on the same LAN.
        route_socket.connect((client_ip, DISCOVERY_PORT))
        address = route_socket.getsockname()[0]
        if _is_usable_lan_ipv4(address):
            return address
    except OSError:
        pass
    finally:
        route_socket.close()

    # Fallback for unusual routing configurations. Prefer a private address and
    # never return loopback, 0.0.0.0, or link-local addresses.
    try:
        candidates = {
            info[4][0]
            for info in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET, socket.SOCK_DGRAM
            )
            if info[4]
        }
    except OSError:
        return None

    usable = [address for address in candidates if _is_usable_lan_ipv4(address)]
    private = [
        address for address in usable if ipaddress.ip_address(address).is_private
    ]
    return next(iter(sorted(private or usable)), None)


class DiscoveryService:
    def __init__(self, server_port: int) -> None:
        self._server_port = server_port
        self._socket: Optional[socket.socket] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return

        listener = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            listener.bind(("0.0.0.0", DISCOVERY_PORT))
            listener.setblocking(False)
        except OSError as error:
            listener.close()
            print(f"[discovery] failed to listen on UDP {DISCOVERY_PORT}: {error}")
            return

        self._socket = listener
        self._task = asyncio.create_task(
            self._listen(), name="udp-server-discovery"
        )
        print(f"[discovery] listening UDP 0.0.0.0:{DISCOVERY_PORT}")

    async def stop(self) -> None:
        task = self._task
        listener = self._socket
        self._task = None
        self._socket = None

        if task is not None:
            task.cancel()
        if listener is not None:
            listener.close()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as error:
                print(f"[discovery] error while stopping: {error}")

        if task is not None or listener is not None:
            print("[discovery] stopped")

    async def _listen(self) -> None:
        listener = self._socket
        if listener is None:
            return

        loop = asyncio.get_running_loop()
        while True:
            try:
                data, client_endpoint = await loop.sock_recvfrom(listener, 1024)
                if data != DISCOVERY_REQUEST:
                    continue
                await self._reply(loop, listener, client_endpoint)
            except asyncio.CancelledError:
                raise
            except OSError as error:
                if self._socket is None:
                    return
                print(f"[discovery] socket error: {error}")
                await asyncio.sleep(0.1)
            except Exception as error:
                print(f"[discovery] unexpected error: {error}")
                await asyncio.sleep(0.1)

    async def _reply(
        self,
        loop: asyncio.AbstractEventLoop,
        listener: socket.socket,
        client_endpoint: Tuple[str, int],
    ) -> None:
        client_ip = client_endpoint[0]
        server_ip = resolve_lan_ipv4(client_ip)
        if server_ip is None:
            print(
                "[discovery] reply skipped: no usable LAN IPv4 "
                f"for client {client_endpoint}"
            )
            return

        response = {
            "serverName": SERVER_NAME,
            "ip": server_ip,
            "port": self._server_port,
            "protocolVersion": PROTOCOL_VERSION,
        }
        payload = json.dumps(
            response, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

        try:
            await loop.sock_sendto(listener, payload, client_endpoint)
        except OSError as error:
            print(f"[discovery] failed to reply to {client_endpoint}: {error}")
