"""Separate client-side Earth connection: localhost TCP -> verified TLS host.

Run explicitly outside BeamNG. This is a network bridge, not a generator or an
auto-executing mod. Credentials stay in the normal Earth handshake, not CLI args.
"""
import argparse
import asyncio
import ssl

BUFFER = 64 * 1024


class Bridge:
    def __init__(self, host, port, context, max_connections=2):
        self.host, self.port, self.context = host, port, context
        self.max_connections = max_connections
        self.active = 0
        self.tasks = set()
        self.finished = asyncio.Event()

    async def accept(self, reader, writer):
        if self.active >= self.max_connections:
            writer.close()
            await writer.wait_closed()
            return
        self.active += 1
        upstream = None
        pumps = []
        self.tasks.add(asyncio.current_task())
        try:
            remote_reader, upstream = await asyncio.wait_for(asyncio.open_connection(
                self.host,self.port,ssl=self.context,server_hostname=self.host),10)

            async def copy(source, target):
                while True:
                    data = await source.read(BUFFER)
                    if not data:
                        return
                    target.write(data)
                    await target.drain()

            pumps = [asyncio.create_task(copy(reader,upstream)),asyncio.create_task(copy(remote_reader,writer))]
            done, _ = await asyncio.wait(pumps,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError,asyncio.TimeoutError,ConnectionError):
            # Never log packet contents, the authentication token or arbitrary remote text.
            print('Earth bridge: connection failed/closed; check host, port and TLS certificate.',flush=True)
        finally:
            for task in pumps:
                task.cancel()
            if pumps:
                await asyncio.gather(*pumps,return_exceptions=True)
            for connection in (upstream,writer):
                if connection:
                    connection.close()
                    try:
                        await connection.wait_closed()
                    except (OSError,ConnectionError):
                        pass
            self.active -= 1
            self.tasks.discard(asyncio.current_task())
            self.finished.set()

    async def close(self):
        tasks = list(self.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)


async def run(args):
    context = ssl.create_default_context(cafile=args.ca_file)
    bridge = Bridge(args.host,args.port,context)
    # Only the local game can connect. The remote host cannot instruct us to run commands/files.
    listener = await asyncio.start_server(bridge.accept,'127.0.0.1',args.local_port,limit=BUFFER)
    print(f'Earth bridge listening on 127.0.0.1:{args.local_port}; generation stays on the host.',flush=True)
    try:
        async with listener:
            if args.once:
                await bridge.finished.wait()
            else:
                await listener.serve_forever()
    finally:
        await bridge.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host',required=True,help='Earth host matching the TLS certificate')
    parser.add_argument('--port',type=int,default=47613)
    parser.add_argument('--local-port',type=int,default=47614)
    parser.add_argument('--ca-file',help='optional trusted CA for a private server certificate')
    parser.add_argument('--once',action='store_true',help='exit after the first connection ends (diagnostics)')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 or not 1 <= args.local_port <= 65535:
        parser.error('ports must be between 1 and 65535')
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
