"""Copy the selected official CLI config into ignored runtime env, without printing it.

--emit is for a direct encrypted SSH pipe to --receive only; never log its output.
"""
import argparse
import json
import os
from pathlib import Path
import sys
from dotenv import set_key

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--emit',action='store_true')
parser.add_argument('--receive',action='store_true')
args=parser.parse_args()
if args.receive:
    data=json.load(sys.stdin)
else:
    data=json.loads((Path.home()/'.openviking/ovcli.conf.persona-voice-procurement').read_text())
if data.get('url')!='https://api.vikingdb.cn-beijing.volces.com/openviking':
    raise ValueError('Unexpected service URL')
if not isinstance(data.get('api_key'),str) or not data['api_key']:
    raise ValueError('Missing key')
if args.emit:
    json.dump(data,sys.stdout)
else:
    target=ROOT/'.env'
    for key,value in {'OPENVIKING_API_KEY':data['api_key'],
                      'OPENVIKING_PROCUREMENT_URI':'viking://resources/persona_voice_procurement_demo'}.items():
        set_key(str(target),key,value)
    os.chmod(target,0o600)
    print('OpenViking runtime configuration saved; credentials not displayed.')
