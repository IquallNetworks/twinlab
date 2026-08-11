# twinlab-client

Async Python client for the [Twinlab](https://github.com/IquallNetworks/twinlab) API.

Twinlab generates reproducible simulated network topologies from a declarative
[netlab](https://netlab.tools/) definition, deployed through
[Containerlab](https://containerlab.dev/). This package is the typed, asyncio client for its
HTTP/WebSocket API: lab lifecycle (create / author / deploy / destroy), configuration push,
declarative test suites, runtime control (power, logs, interfaces, netem impairment), live events
over SSE, an interactive node terminal, and the auth/RBAC surface (users, groups, roles, lab
grants).

The client implements the **v1.0 target contract** (`docs/twinlab_client_shape.py` in the Twinlab
repository). Every wire shape is a frozen dataclass; every method is a coroutine; any non-2xx
response raises `TwinlabApiError`.

## Install

```sh
uv add twinlab-client   # or: pip install twinlab-client
```

(Not yet published — install from the repository path.)

## Quickstart

```python
import asyncio

from twinlab_client import TwinlabClient


async def main() -> None:
    async with TwinlabClient("http://localhost:5173") as client:
        await client.login("admin", "...")

        # The lab name is its durable identity and a netlab identifier:
        # a leading letter, then letters/digits/dash/underscore, max 16.
        await client.create_lab("my-lab")
        await client.update_definition("my-lab", open("lab.yml").read())

        # Deploy is asynchronous: it returns a RUNNING job. wait_job polls it
        # to a terminal state and hands back the job, result and all.
        job = await client.deploy_lab("my-lab", configure=True)
        done = await client.wait_job("my-lab", job.id, timeout=900)
        print(done.status, done.result, done.error)

        for lab in await client.list_labs():
            print(lab.name, lab.status)


asyncio.run(main())
```

## License

Apache-2.0.
