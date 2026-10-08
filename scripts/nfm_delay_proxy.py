"""Isolated SMF3 TCP forwarder. Delays upstream chunks, preserves byte order."""
import argparse,asyncio,time,json

async def serve(port,delay):
    async def client(reader,writer):
        upstream=None
        try:
            remote,upstream=await asyncio.open_connection('127.0.0.10',7777)
            async def copy(source,destination,wait):
                while data:=await source.read(65536):
                    received=time.monotonic_ns()
                    if wait:await asyncio.sleep(wait)
                    destination.write(data);await destination.drain()
                    if wait:print(json.dumps(dict(received_ns=received,forwarded_ns=time.monotonic_ns(),bytes=len(data))),flush=True)
            tasks=[asyncio.create_task(copy(reader,upstream,delay)),asyncio.create_task(copy(remote,writer,0))]
            await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        except (ConnectionError,OSError) as error:print(repr(error),flush=True)
        finally:
            writer.close()
            if upstream:upstream.close()
    server=await asyncio.start_server(client,'127.0.0.250',port)
    async with server:await server.serve_forever()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--delay-ms',type=float,required=True);a=p.parse_args()
    asyncio.run(serve(7777,a.delay_ms/1000))
