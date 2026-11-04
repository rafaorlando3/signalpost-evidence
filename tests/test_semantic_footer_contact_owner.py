import unittest
from agent import Page,website_identity
from legal_name_identity import legal_name_identity
class SemanticFooterOwner(unittest.TestCase):
 DATA={'navn':'Example Builder AS','organisasjonsnummer':'810034882'}
 def proof(self,footer,title='Example Builder AS'):
  p=Page('<title>'+title+'</title><main><p>Our work and services.</p></main><footer>'+footer+'</footer>','https://example.no/')
  return legal_name_identity(self.DATA,[(p,{'url':p.url})],lambda pg:website_identity(self.DATA['organisasjonsnummer'],pg,self.DATA)!='conflict')
 def test_exact_footer_owner_phone_and_obfuscated_same_host_email(self):
  proof=self.proof('<p>Example Builder AS<br>Tlf. +47 990 81 880<br>Epost: firma(at)example.no</p>')
  self.assertIsNotNone(proof);self.assertEqual(proof['literal_same_host_mailbox'],'firma(at)example.no');self.assertNotIn('same_host_contact_email',proof)
 def test_plain_mailbox_with_complete_same_legal_brand(self):
  self.assertIsNotNone(self.proof('<p>Example Builder AS Tlf: 99081880 Epost: firma@example.no</p>'))
 def test_group_or_missing_legal_differentiator_is_insufficient(self):
  for title in ['Example Group','Example Builder Norway AS']:
   self.assertIsNone(self.proof('<p>Example Builder AS Tlf: 99081880 firma@example.no</p>',title))
 def test_other_domain_or_missing_phone_is_insufficient(self):
  for body in ['<p>Example Builder AS Tlf: 99081880 firma@other.no</p>','<p>Example Builder AS firma@example.no</p>']:
   self.assertIsNone(self.proof(body))
 def test_client_credit_other_id_and_missing_full_legal_owner_stay_rejected(self):
  for body in ['<div class="customer"><p>Example Builder AS Tlf: 99081880 firma@example.no</p></div>','<p>Other Owner AS Org.nr974760673</p><p>Example Builder AS Tlf: 99081880 firma@example.no</p>','<p>Example Builder Tlf: 99081880 firma@example.no</p>']:
   self.assertIsNone(self.proof(body))
