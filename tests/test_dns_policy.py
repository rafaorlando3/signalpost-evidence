import socket,unittest
from agent import safe_url
from dns_policy import RunResolver

class DNSPolicy(unittest.TestCase):
    def setup_resolver(self,lookup):
        self.t=0
        def sleep(s):self.t+=s
        return RunResolver(clock=lambda:self.t,sleep=sleep,lookup=lookup)
    def answer(self,ip='8.8.8.8'):return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]
    def test_cache_expires_and_uses_same_system_lookup_arguments(self):
        calls=[]
        def lookup(*a,**k):calls.append((a,k));return self.answer()
        r=self.setup_resolver(lookup);safe_url('https://example.test/',resolver=r);safe_url('https://example.test/other',resolver=r)
        self.assertEqual(len(calls),1);self.assertEqual(calls[0],(('example.test',443),{'type':socket.SOCK_STREAM}))
        self.t=31;safe_url('https://example.test/',resolver=r);self.assertEqual(len(calls),2)
    def test_one_transient_retry_and_persistent_error_is_not_allowed(self):
        calls=[]
        def lookup(*a,**k):
            calls.append(1)
            if len(calls)==1:raise socket.gaierror(socket.EAI_AGAIN,'temporary')
            return self.answer()
        r=self.setup_resolver(lookup);self.assertTrue(r.resolve('example.test',443));self.assertEqual(r.summary()['retries'],1)
        def failure(*a,**k):raise socket.gaierror(socket.EAI_AGAIN,'temporary')
        r=self.setup_resolver(failure)
        with self.assertRaises(socket.gaierror):safe_url('https://example.test',resolver=r)
        self.assertEqual(r.summary()['lookups'],2)
    def test_permanent_negative_is_briefly_cached_and_never_retried(self):
        def failure(*a,**k):raise socket.gaierror(socket.EAI_NONAME,'not found')
        r=self.setup_resolver(failure)
        for _ in range(2):
            with self.assertRaises(socket.gaierror):r.resolve('example.test',443)
        self.assertEqual(r.summary()['lookups'],1);self.assertNotIn('retries',r.summary())
        self.t=6
        with self.assertRaises(socket.gaierror):r.resolve('example.test',443)
        self.assertEqual(r.summary()['lookups'],2)
    def test_every_cached_answer_still_undergoes_public_ip_validation(self):
        r=self.setup_resolver(lambda *a,**k:self.answer('127.0.0.1'))
        for _ in range(2):
            with self.assertRaisesRegex(ValueError,'Non-public'):safe_url('https://example.test',resolver=r)
        self.assertEqual(r.summary()['lookups'],1)
    def test_spacing_and_retry_cannot_spend_remaining_deadline(self):
        r=self.setup_resolver(lambda *a,**k:self.answer());r.resolve('one.test',443)
        with self.assertRaises(TimeoutError):r.resolve('two.test',443,deadline=.01)
        self.assertEqual(r.summary()['lookups'],1)


class DNSCacheLifetime(unittest.TestCase):
    def test_negative_cache_does_not_retain_the_calling_company(self):
        import gc,weakref
        def failure(*a,**k):raise socket.gaierror(socket.EAI_NONAME,'not found')
        resolver=RunResolver(lookup=failure,interval=0)
        class Company:
            def run(self):resolver.resolve('missing-company.test',443)
        company=Company();reference=weakref.ref(company)
        try:company.run()
        except socket.gaierror:pass
        del company;gc.collect()
        self.assertIsNone(reference())
        with self.assertRaises(socket.gaierror):resolver.resolve('missing-company.test',443)
        self.assertEqual(resolver.summary()['lookups'],1)
