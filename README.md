# temporal-xmemory-events-agent

Long-running agents on [Temporal](https://temporal.io) that research AI conferences, meetups and other
events on the internet and keep everything they learn, and everything they are doing, in
[xmemory](https://xmemory.ai).

Two agents share the work through memory. A Discovery agent finds events and writes each new one to the
events memory as unprocessed. A Processor agent takes unprocessed events, crawls their pages, stores the
details and marks them processed. Both agents run on the OpenAI Agents SDK; every model call, web fetch and
memory operation is a durable Temporal activity.

The rest of this README is written as the pieces land.
