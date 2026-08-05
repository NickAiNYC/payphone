import asyncio
import json
import websockets

RELAY_URL = "ws://localhost:8080"


async def main():
    print(f"Connecting to local Nostr relay at {RELAY_URL}...")
    async with websockets.connect(RELAY_URL) as websocket:
        # Subscribe to all Gift Wrap (Kind 13) events
        sub = ["REQ", "verify-sub", {"kinds": [13]}]
        await websocket.send(json.dumps(sub))
        print("Subscribed to all NIP-17 Gift Wraps (Kind 13). Listening...")

        async for message in websocket:
            try:
                msg = json.loads(message)
                if msg[0] == "EVENT":
                    event = msg[2]
                    print("\n" + "=" * 50)
                    print(f"EVENT ID: {event['id']}")
                    print(f"KIND: {event['kind']}")
                    print(f"SENDER (Throwaway): {event['pubkey']}")
                    print(f"CONTENT (Ciphertext):\n{event['content']}")
                    print("=" * 50)
            except Exception as e:
                print(f"Error reading message: {e}")


if __name__ == "__main__":
    asyncio.run(main())
