"""Create the loopback-only inbound trunk and named voice Agent dispatch."""
import asyncio
import os
from pathlib import Path
from dotenv import load_dotenv
from livekit import api

load_dotenv(Path(__file__).resolve().parents[1] / '.env')

async def main():
    async with api.LiveKitAPI() as client:
        trunks = await client.sip.list_inbound_trunk(api.ListSIPInboundTrunkRequest())
        matches = [t for t in trunks.items if t.name == 'persona-asterisk-local']
        if matches:
            trunk = matches[0]
            assert list(trunk.allowed_addresses) == ['127.0.0.1/32']
            assert list(trunk.numbers) == ['9000']
        else:
            trunk = await client.sip.create_inbound_trunk(api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(name='persona-asterisk-local', numbers=['9000'], allowed_addresses=['127.0.0.1/32']),
            ))
        rules = await client.sip.list_dispatch_rule(api.ListSIPDispatchRuleRequest())
        matches = [r for r in rules.items if r.name == 'persona-sim-ai']
        if matches:
            rule = matches[0]
            assert list(rule.trunk_ids) == [trunk.sip_trunk_id]
        else:
            rule = await client.sip.create_dispatch_rule(api.CreateSIPDispatchRuleRequest(
                name='persona-sim-ai', trunk_ids=[trunk.sip_trunk_id],
                rule=api.SIPDispatchRule(dispatch_rule_individual=api.SIPDispatchRuleIndividual(room_prefix='sim-ai-')),
                room_config=api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=os.getenv('LIVEKIT_AGENT_NAME', 'persona-voice-agent'))]),
            ))
        print('Trunk:', trunk.sip_trunk_id, 'Dispatch:', rule.sip_dispatch_rule_id)

if __name__ == '__main__':
    asyncio.run(main())
