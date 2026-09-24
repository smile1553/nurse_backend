import asyncio
import ipaddress
import json
import socket
from typing import Optional, Set, Tuple


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


class _DiscoveryProtocol(asyncio.DatagramProtocol):
    def __init__(self, server_port: int) -> None:
        self._server_port = server_port
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._reply_tasks: Set[asyncio.Task] = set()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport  # type: ignore[assignment]

    def datagram_received(
        self, data: bytes, client_endpoint: Tuple[str, int]
    ) -> None:
        if data != DISCOVERY_REQUEST:
            return

        task = asyncio.create_task(self._reply(client_endpoint))
        self._reply_tasks.add(task)
        task.add_done_callback(self._reply_tasks.discard)

    def error_received(self, error: Exception) -> None:
        print(f"[discovery] socket error: {error}")

    def connection_lost(self, error: Optional[Exception]) -> None:
        self._transport = None
        if error is not None:
            print(f"[discovery] listener closed with error: {error}")

    async def stop(self) -> None:
        tasks = list(self._reply_tasks)
        self._reply_tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _reply(self, client_endpoint: Tuple[str, int]) -> None:
        client_ip = client_endpoint[0]
        loop = asyncio.get_running_loop()
        server_ip = await loop.run_in_executor(None, resolve_lan_ipv4, client_ip)
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

        transport = self._transport
        if transport is None or transport.is_closing():
            return

        try:
            transport.sendto(payload, client_endpoint)
        except OSError as error:
            print(f"[discovery] failed to reply to {client_endpoint}: {error}")


class DiscoveryService:
    def __init__(self, server_port: int) -> None:
        self._server_port = server_port
        self._transport: Optional[asyncio.DatagramTransport] = None
        self._protocol: Optional[_DiscoveryProtocol] = None

    async def start(self) -> None:
        if self._transport is not None and not self._transport.is_closing():
            return

        loop = asyncio.get_running_loop()
        try:
            transport, protocol = await loop.create_datagram_endpoint(
                lambda: _DiscoveryProtocol(self._server_port),
                local_addr=("0.0.0.0", DISCOVERY_PORT),
                family=socket.AF_INET,
            )
        except Exception as error:
            print(f"[discovery] failed to listen on UDP {DISCOVERY_PORT}: {error}")
            return

        self._transport = transport
        self._protocol = protocol
        print(f"[discovery] listening UDP 0.0.0.0:{DISCOVERY_PORT}")

    async def stop(self) -> None:
        transport = self._transport
        protocol = self._protocol
        self._transport = None
        self._protocol = None

        if transport is not None:
            transport.close()
        if protocol is not None:
            try:
                await protocol.stop()
            except Exception as error:
                print(f"[discovery] error while stopping: {error}")

        if transport is not None or protocol is not None:
            # Let the event loop deliver connection_lost and release the socket.
            await asyncio.sleep(0)
            print("[discovery] stopped")
