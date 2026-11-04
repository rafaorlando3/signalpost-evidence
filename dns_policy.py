"""Run-local ordinary DNS reuse and spacing; never changes resolver or trust.

All addresses returned here still pass safe_url's public-IP validation. Positive
answers are pinned only for a short TTL; permanent negative answers are cached
briefly, temporary EAI_AGAIN may retry once. No DNS server/IP rotation.
"""
import collections,socket,threading,time

class RunResolver:
    def __init__(self,*,ttl=30,negative_ttl=5,interval=.05,clock=None,sleep=None,lookup=None):
        self.ttl=ttl;self.negative_ttl=negative_ttl;self.interval=interval
        self.clock=clock or time.monotonic;self.sleep=sleep or time.sleep;self.lookup=lookup or socket.getaddrinfo
        self.lock=threading.Lock();self.host_locks=collections.defaultdict(threading.Lock)
        self.cache={};self.next_start=0;self.counts=collections.Counter()
    def resolve(self,host,port,deadline=None):
        key=(host,port)
        with self.lock:guard=self.host_locks[key]
        with guard:
            with self.lock:
                old=self.cache.get(key)
                if old and old[0]>self.clock():
                    self.counts['cache_hits']+=1
                    if isinstance(old[1],dict):raise socket.gaierror(old[1]['dns_error_errno'],'cached permanent DNS failure')
                    return list(old[1])
            for attempt in range(2):
                with self.lock:
                    now=self.clock();pause=max(0,self.next_start-now)
                    if deadline is not None and pause>=deadline-now:raise TimeoutError('DNS start exceeds remaining company deadline')
                    self.next_start=now+pause+self.interval
                if pause:self.sleep(pause)
                try:
                    with self.lock:self.counts['lookups']+=1
                    answer=self.lookup(host,port,type=socket.SOCK_STREAM)
                except socket.gaierror as error:
                    temporary=error.errno==socket.EAI_AGAIN
                    with self.lock:self.counts['temporary_errors' if temporary else 'other_dns_errors']+=1
                    if temporary and attempt==0 and (deadline is None or deadline-self.clock()>.3):
                        with self.lock:self.counts['retries']+=1
                        self.sleep(.25);continue
                    # Never cache exception/traceback objects: they retain caller frames
                    # and whole company responses until the run ends.
                    if not temporary:self._store(key,{'dns_error_errno':error.errno},self.negative_ttl)
                    raise
                self._store(key,tuple(answer),self.ttl);return list(answer)
    def _store(self,key,value,ttl):
        with self.lock:
            if len(self.cache)>=4096:
                now=self.clock();self.cache={k:v for k,v in self.cache.items() if v[0]>now}
                if len(self.cache)>=4096:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(self.clock()+ttl,value)
    def summary(self):
        with self.lock:return {**self.counts,'ttl_seconds':self.ttl,'negative_ttl_seconds':self.negative_ttl,'minimum_lookup_spacing_seconds':self.interval,'temporary_retry_limit':1,'resolver':'ordinary system getaddrinfo; unchanged'}
