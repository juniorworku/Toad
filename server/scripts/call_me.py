"""Places one real call now from Toad's AgentPhone number to OWNER_PHONE, then prints the
transcript. Costs AgentPhone credit and rings your phone.
Usage (repo root): .venv/bin/python server/scripts/call_me.py
"""

import asyncio

from _common import need, settings

from toad_server.phone import AgentPhone, CallRequest, mask


async def main() -> None:
    config = settings()
    need(config.agentphone_api_key.get_secret_value(), "AGENTPHONE_API_KEY")
    need(config.agentphone_number, "AGENTPHONE_NUMBER")
    need(config.owner_phone, "OWNER_PHONE")
    print(f"Calling {mask(config.owner_phone)} from {config.agentphone_number}…")
    phone = AgentPhone(config.agentphone_api_key.get_secret_value(), config.agentphone_number)
    result = await phone.call(
        CallRequest(
            to_number=config.owner_phone,
            initial_greeting=(
                "Hi, it's Toad, your AI desk buddy. I've got my own phone number now, so when "
                "you're away from your desk and a check-in comes due, I'll call you here. Is now "
                "a good time for a quick hello?"
            ),
            system_prompt=(
                "You are Toad, the user's AI desk buddy, which lives in an old phone on their "
                "desk. This is a first test call to show you can phone them when they're away "
                "from the desk. Explain that in a sentence if asked, answer briefly, and keep the "
                "call under a minute. Never pretend to be human. Say goodbye and end the call "
                "when done."
            ),
        )
    )
    print(f"Call {result.id}: {result.status}")
    for line in result.transcript:
        print(f"{'You ' if line.get('role') == 'user' else 'Toad'}: {line.get('content', '')}")


if __name__ == "__main__":
    asyncio.run(main())
