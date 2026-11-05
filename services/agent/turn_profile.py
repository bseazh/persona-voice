"""Versioned local endpointing profiles; never manufacture ASR final transcripts."""
import os

PROFILES = {
    'baseline': {'vad_silence': 0.5, 'endpoint_min': 0.45, 'endpoint_max': 1.5},
    'local-fast-v1': {'vad_silence': 0.35, 'endpoint_min': 0.30, 'endpoint_max': 1.5},
}

def turn_profile():
    # Two phone trials found no demonstrated benefit; keep the experiment opt-in.
    name = os.getenv('VOICE_TURN_PROFILE', 'baseline')
    if name not in PROFILES:
        raise ValueError('VOICE_TURN_PROFILE must be baseline or local-fast-v1')
    return {'name': name, **PROFILES[name]}
