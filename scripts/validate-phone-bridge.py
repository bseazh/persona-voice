"""Server-only real SIP/LiveKit integration test. No SIM recipient is dialed."""
import json
from pathlib import Path
import socket
import subprocess
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
def cli(command):
    return subprocess.run(['sudo','asterisk','-rx',command],check=True,capture_output=True,text=True).stdout
def sql(statement):
    return subprocess.run(['sudo','-u','postgres','psql','-d','persona_consult','-v','ON_ERROR_STOP=1','-At'],input=statement,check=True,capture_output=True,text=True).stdout.strip()

def main():
    assert not cli('core show channels concise').strip(),'A call is active'
    assert sql("SELECT count(*) FROM consult_sessions WHERE mode='phone' AND status='active'")=='0','A phone consultation is active'
    call_id=str(uuid.uuid4())
    sql("INSERT INTO consult_sessions(id,title,template,mode,voice_state,phone_state) VALUES('"+call_id+"','SIP桥接技术验收（未拨打手机）','{\"id\":\"sleep-v1\",\"title\":\"睡眠与生活习惯调研\",\"version\":1}','phone','dialing','internal_test')")
    result=subprocess.run(['sudo','cat','/etc/persona-phone-console.env'],check=True,capture_output=True,text=True)
    config=dict(line.split('=',1) for line in result.stdout.splitlines() if '=' in line)
    with socket.create_connection(('127.0.0.1',5038),timeout=5) as sock:
        stream=sock.makefile('rwb');stream.readline()
        def action(lines):
            stream.write(('\r\n'.join(lines)+'\r\n\r\n').encode());stream.flush();reply=[]
            while True:
                line=stream.readline()
                if not line:raise RuntimeError('AMI disconnected')
                if line==b'\r\n':
                    if reply:break
                    continue
                reply.append(line.decode().strip())
            assert 'Response: Success' in reply,'AMI action rejected'
        action(['Action: Login','Username: persona-console','Secret: '+config['PHONE_AMI_PASSWORD'],'Events: off'])
        action(['Action: Originate','Channel: Local/s@livekit-ai-smoke/n','Context: livekit-ai','Exten: s','Priority: 1',
                'Variable: __CONSULTATION_ID='+call_id,'CallerID: 1000','Timeout: 35000','Async: true'])
    print('Internal SIP integration started: '+call_id,flush=True)
    for _ in range(35):
        row=json.loads(sql("SELECT json_build_object('id',s.id,'status',s.status,'room',s.room_name,'report',s.report_status,'messages',(SELECT count(*) FROM consult_messages WHERE session_id=s.id)) FROM consult_sessions s WHERE id='"+call_id+"'"))
        if row['status']=='closed' and row['report']=='ready':break
        time.sleep(2)
    print(json.dumps(row,ensure_ascii=False))
    assert row['room'] and row['room'].startswith('sim-ai-') and row['messages']>0,'SIP correlation or Agent transcript failed'
    assert row['status']=='closed','Internal test not archived; inspect this exact call before next test'

if __name__=='__main__':main()
