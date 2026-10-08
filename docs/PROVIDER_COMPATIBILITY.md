# Provider feasibility

Checked October 8, 2026 with the OpenAI Docs skill.

The official [voice WebSocket guide](https://developers.openai.com/api/docs/guides/voice-websockets/) documents the same `/v1/live/sessions` endpoint, startup/started handshake and 24 kHz PCM format used by Desku. It includes Python SDK guidance. The official [Agents API quickstart](https://developers.openai.com/api/docs/guides/agents-api/quickstart/) documents Python's `beta.agents.sessions` API and persistent session continuation. These references support a Python port without replacing the architecture with a different voice API or a local agent SDK.

The adapters now use the documented client delegation events and saved-agent required actions. OpenAI Python SDK 3.26.1 is locked; its real client is exercised against a mock HTTP/SSE transport, and the voice adapter is exercised against a loopback WebSocket provider. No live provider request was made. Account access, speech quality and device integration remain unverified. Default mode is the labeled diagnostic fake.
