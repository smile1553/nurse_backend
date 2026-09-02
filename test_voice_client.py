import argparse
import asyncio
import json
import time
import uuid

import sounddevice as sd
import websockets


async def stream_microphone(url: str, seconds: float, sample_rate: int, blocksize: int, device: int | None) -> None:
    request_id = uuid.uuid4().hex[:12]
    queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    dropped_chunks = 0

    def enqueue(chunk: bytes) -> None:
        nonlocal dropped_chunks
        try:
            queue.put_nowait(chunk)
        except asyncio.QueueFull:
            dropped_chunks += 1

    def audio_callback(indata, frames, callback_time, status) -> None:
        if status:
            print(f"[mic] {status}")
        loop.call_soon_threadsafe(enqueue, bytes(indata))

    async def send_audio(ws) -> None:
        while not stop_event.is_set() or not queue.empty():
            try:
                chunk = await asyncio.wait_for(queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            await ws.send(chunk)

    async with websockets.connect(url, max_size=2 * 1024 * 1024) as ws:
        await ws.send(json.dumps({
            "type": "start_utterance",
            "sampleRate": sample_rate,
            "requestId": request_id,
        }))

        ready = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        print("[server]", json.dumps(ready, ensure_ascii=False))
        if ready.get("type") == "error":
            return

        sender = asyncio.create_task(send_audio(ws))
        print(f"[record] speak now for {seconds:.1f}s ...")
        started = time.perf_counter()

        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="int16",
            blocksize=blocksize,
            device=device,
            callback=audio_callback,
        ):
            await asyncio.sleep(seconds)

        stop_event.set()
        await sender

        await ws.send(json.dumps({
            "type": "end_utterance",
            "requestId": request_id,
        }))

        print(f"[record] sent {time.perf_counter() - started:.2f}s audio, dropped_chunks={dropped_chunks}")

        while True:
            msg = await asyncio.wait_for(ws.recv(), timeout=20)
            data = json.loads(msg)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            if data.get("type") in {"emotion_result", "error"}:
                break


def main() -> None:
    parser = argparse.ArgumentParser(description="Send local microphone audio to /voice and print emotion JSON.")
    parser.add_argument("--url", default="ws://127.0.0.1:8000/voice")
    parser.add_argument("--seconds", type=float, default=4.0)
    parser.add_argument("--sample-rate", type=int, default=16000)
    parser.add_argument("--blocksize", type=int, default=1024)
    parser.add_argument("--device", type=int, default=None, help="Input device id from sounddevice query_devices().")
    args = parser.parse_args()

    asyncio.run(stream_microphone(args.url, args.seconds, args.sample_rate, args.blocksize, args.device))


if __name__ == "__main__":
    main()
