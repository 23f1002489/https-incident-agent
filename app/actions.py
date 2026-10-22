"""Fixed demo action registry. No LLM-generated commands are executed."""
import asyncio
from datetime import datetime, timezone
from pydantic import BaseModel, ConfigDict, Field


def now():
    return datetime.now(timezone.utc).isoformat()


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    investigation_id: str
    action_type: str
    parameters: dict = Field(default_factory=dict)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    approver: str = Field(min_length=2, max_length=100)
    decision: str  # approved or rejected


# Explicit permitted actions, demo-only; no network writes or infrastructure mutations.
ACTION_REGISTRY = {'record_manual_escalation': {}, 'capture_evidence_snapshot': {}}


def validate_action(action_type, parameters):
    if action_type not in ACTION_REGISTRY:
        raise ValueError('Action not in the permitted demo registry')
    if parameters != {}:
        raise ValueError('Demo actions do not accept parameters')


async def execute_demo_action(action_type, incident_id, diagnostics):
    """Return actual local action results; never claim to remediate a remote service."""
    await asyncio.sleep(0)
    if action_type == 'record_manual_escalation':
        return {'success': True, 'operation': 'record_manual_escalation',
                'message': 'Local escalation record created; no external notification sent',
                'incident_id': incident_id, 'executed_at': now()}
    if action_type == 'capture_evidence_snapshot':
        return {'success': True, 'operation': 'capture_evidence_snapshot',
                'message': 'Captured stored diagnostic identifiers; no new probe performed',
                'diagnostic_ids': [d['id'] for d in diagnostics], 'executed_at': now()}
    raise ValueError('Unsupported action')
