import asyncio, socket

DISCOVERY_PORT = 9450
DISCOVERY_QUERY = b"EMO_SERVER?"


def get_host_ip(target_ip: str = None):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 針對提問端計算本機可達 IP，避免回到 127.0.0.1
        peer = target_ip or "8.8.8.8"
        s.connect((peer, 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = None
    finally:
        s.close()
    return ip


async def udp_discovery_server(http_port=8000):
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", DISCOVERY_PORT))
    sock.setblocking(False)
    print(f"[discovery] listening UDP 0.0.0.0:{DISCOVERY_PORT}")

    while True:
        try:
            data, addr = await loop.sock_recvfrom(sock, 1024)
            if data.strip() != DISCOVERY_QUERY:
                continue

            ip = get_host_ip(addr[0]) or get_host_ip()
            if not ip or ip.startswith("127."):
                print(f"[discovery] skip reply: unresolved host ip for requester={addr}")
                continue

            reply = f"EMO_SERVER:http://{ip}:{http_port}".encode("utf-8")
            await loop.sock_sendto(sock, reply, addr)
        except Exception:
            await asyncio.sleep(0.1)
