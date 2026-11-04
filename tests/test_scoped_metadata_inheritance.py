import unittest

class ScopedMetadataInheritance(unittest.TestCase):
    def observe(self,child_description):
        from test_agent import R5Precision
        h=R5Precision();generic='Example plans sustainable cities. Engineers and architects deliver services across all countries.'
        own='Example Services Bergen delivers local building services to customers in Bergen and the surrounding region.'
        root='<title>Example Norway</title><meta name="description" content="'+generic+'"><nav><a href="/services/bergen">Example Services Bergen</a></nav><footer>Example Norway AS Storgata 3, 0001 Oslo</footer>'
        child='<title>Example Norway</title><meta name="description" content="'+child_description+'"><main><h1>Example Services Bergen</h1><p>'+own+'</p><p>Example Services Bergen AS Storgata 3, 0001 Oslo</p></main><footer>Example Norway AS Storgata 3, 0001 Oslo</footer>'
        data={'organisasjonsnummer':h.ORG,'navn':'EXAMPLE SERVICES BERGEN AS','hjemmeside':h.HOME,'forretningsadresse':{'adresse':['Storgata 3'],'postnummer':'0001'}}
        return h.observe({h.HOME:root,h.HOME+'services/bergen':child},data),generic,own
    def test_copied_parent_metadata_falls_back_to_visible_own_paragraph(self):
        generic='Example plans sustainable cities. Engineers and architects deliver services across all countries.'
        row,_,own=self.observe(generic);site=next(c for c in row['claims'] if c['field']=='website.verified_url');desc=next(c for c in row['claims'] if c['field']=='website.description')
        self.assertTrue(site['value'].endswith('/services/bergen'));self.assertEqual(desc['value'],own)
    def test_unique_scoped_description_is_preserved(self):
        own='Example Services Bergen delivers local building services to customers in Bergen and the surrounding region.'
        row,_,_=self.observe(own);self.assertEqual(next(c for c in row['claims'] if c['field']=='website.description')['value'],own)
if __name__=='__main__':unittest.main()
