"""Seeded variable upstream TCP-chunk delay; dedicated to ML-v1."""
import argparse, asyncio, json, random, time

async def serve(low, high, seed):
    connections=0
    async def client(reader,writer):
        nonlocal connections
        connections+=1; connection=connections
        rng=random.Random(seed*100003+connection);upstream=None
        try:
            remote,upstream=await asyncio.open_connection('127.0.0.10',7777)
            async def copy(source,destination,delayed):
                while data:=await source.read(65536):
                    received=time.monotonic_ns();wait=rng.uniform(low,high) if delayed else 0
                    if wait:await asyncio.sleep(wait/1000)
                    destination.write(data);await destination.drain()
                    if delayed:print(json.dumps(dict(connection=connection,received_ns=received,
                        forwarded_ns=time.monotonic_ns(),scheduled_ms=wait,bytes=len(data))),flush=True)
            tasks=[asyncio.create_task(copy(reader,upstream,True)),asyncio.create_task(copy(remote,writer,False))]
            await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
        except (ConnectionError,OSError) as error:print(repr(error),flush=True)
        finally:
            writer.close()
            if upstream:upstream.close()
    server=await asyncio.start_server(client,'127.0.0.250',7777)
    async with server:await server.serve_forever()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--min-ms',type=float,required=True)
    p.add_argument('--max-ms',type=float,required=True);p.add_argument('--seed',type=int,required=True)
    a=p.parse_args();assert 0<=a.min_ms<=a.max_ms
    asyncio.run(serve(a.min_ms,a.max_ms,a.seed))
