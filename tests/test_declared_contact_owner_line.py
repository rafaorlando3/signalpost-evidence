import unittest
from agent import Page,website_identity
from legal_name_identity import legal_name_identity
class DeclaredContactOwnerLine(unittest.TestCase):
 DATA={'navn':'Example Creative AS','organisasjonsnummer':'810034882','hjemmeside':'www.example.no'}
 def proof(self,body,data=None):
  data=data or self.DATA;p=Page('<title>Example Creative - Hjem</title>'+body,'https://www.example.no/')
  return legal_name_identity(data,[(p,{'url':p.url})],lambda pg:website_identity(data['organisasjonsnummer'],pg,data)!='conflict')
 def test_full_legal_contact_line_with_obfuscated_email_is_sufficient(self):
  proof=self.proof('<div><p>Example Creative as • Anna Example • tel: 930 06 376 • [email protected]</p></div>')
  self.assertEqual(proof['literal_contact_phone'],'930 06 376');self.assertEqual(proof['registered_domain_match'],'example.no')
 def test_declared_domain_is_required(self):
  data={**self.DATA};data.pop('hjemmeside')
  self.assertIsNone(self.proof('<p>Example Creative AS • phone: 93006376</p>',data))
 def test_other_legal_number_remains_a_veto(self):
  self.assertIsNone(self.proof('<p>Other Owner AS Org.nr. 974760673</p><p>Example Creative AS • phone: 93006376</p>'))
 def test_bare_brand_and_ordinary_as_sentence_are_insufficient(self):
  for body in ['<p>Example Creative • phone: 93006376</p>','<p>Example Creative as you know it • phone: 93006376</p>']:
   self.assertIsNone(self.proof(body))
 def test_customer_and_provider_credit_are_not_owner_lines(self):
  for cls in ['customer','agency','site-credit']:
   self.assertIsNone(self.proof('<div class="'+cls+'"><p>Example Creative AS • phone: 93006376</p></div>'))
