"""Provider-independent routing and conservative end-command recognition."""
import re


def explicit_end(text):
    # Full utterances only: quoted, negated, conditional or explanatory mentions
    # are not commands. In particular, never search for a bare substring 再见.
    text=re.sub(r'[\s，,。.!！?？；;]', '', text).lower()
    command=(r'(?:'
        r'(?:请|麻烦你|帮我)?(?:挂断|挂掉|结束)(?:电话|通话|本次通话|这次通话)'
        r'|(?:今天|这次)?(?:就)?(?:先)?聊到这里(?:吧|了)?'
        r'|(?:今天|这次)(?:就)?(?:先)?到这里(?:吧|了)?'
        r'|(?:那)?(?:就)?(?:先)?这样(?:吧|了)?(?:再见|拜拜|拜)'
        r'|再见|拜拜|不聊了|现在不方便|我先忙了)(?:吧|了)?')
    return bool(re.fullmatch(r'(?:嗯|呃|好的|好|那|那就)*'+command+
        r'(?:(?:谢谢|好的|那)?'+command+r'){0,2}(?:谢谢)?',text))


class ResponseRouter:
    """Make a beta response stream single-generation for LiveKit's GA engine.

    Response IDs, not arrival order alone, own every output event. Cancelled or
    superseded output is never forwarded into the next response's channels.
    """
    def __init__(self,audit=None):
        self.active=None
        self.items=set()
        self.cancelling=False
        self.muted=False
        self.audit=audit or (lambda *args:None)

    def cancel(self):
        if not self.active or self.cancelling:return False
        self.cancelling=True
        return True

    def feed(self,event):
        kind=event['type']
        if kind=='response.created':
            response_id=event['response']['id']
            if response_id==self.active:return []
            before=[]
            if self.active:
                before=[{'type':'response.done','response':{'id':self.active,
                    'status':'cancelled','output':[]}}]
                self.audit('response_superseded',{'response_id':self.active,'next_response_id':response_id})
            self.active=None if self.muted else response_id
            self.items=set()
            self.cancelling=False
            return before if self.muted else before+[event]
        if not kind.startswith('response.'):return [event]
        response_id=event.get('response_id') or event.get('response',{}).get('id')
        if not self.active or response_id!=self.active:
            self.audit('late_response_dropped',{'type':kind,'response_id':response_id})
            return []
        if kind=='response.done':
            self.active=None
            self.items=set()
            return [event]
        if (self.cancelling or self.muted) and kind.endswith('.delta'):
            return []
        if kind=='response.output_item.added':
            item_id=event['item']['id']
            if item_id in self.items:return []
            self.items.add(item_id)
        if kind=='response.output_item.done' and event['item'].get('type')=='message':
            if event['item']['id'] not in self.items:
                # Qwen can finish an unannounced item during cancellation. It has
                # no consumer/channels in LiveKit, so there is nothing to close.
                self.audit('unannounced_item_done',{'response_id':response_id,'item_id':event['item']['id']})
                return []
        return [event]
