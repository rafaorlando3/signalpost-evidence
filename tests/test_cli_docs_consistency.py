"""CLI.md must describe the options and limits the shipped CLI enforces (DOC1-3).

Reads cli.py as source text/AST; it does not run the collector.
"""
import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = (ROOT / 'cli.py').read_text(encoding='utf-8')
DOC = (ROOT / 'CLI.md').read_text(encoding='utf-8')
README = (ROOT / 'README.md').read_text(encoding='utf-8')


def options():
    found = {}
    for node in ast.walk(ast.parse(CLI)):
        if (isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'add_argument'
                and node.args and isinstance(node.args[0], ast.Constant)):
            keywords = {k.arg: k.value for k in node.keywords}
            default = keywords.get('default')
            found[node.args[0].value] = default.value if isinstance(default, ast.Constant) else None
    return found


class CliDocumentation(unittest.TestCase):
    def test_every_cli_option_is_documented_in_the_option_table(self):
        table = '\n'.join(line for line in DOC.splitlines() if line.startswith('| `--'))
        missing = [name for name in options() if '`' + name not in table]
        self.assertEqual(missing, [])

    def test_public_discovery_defaults_match_the_parser(self):
        parsed = options()
        self.assertEqual(parsed['--public-jobs'], 'auto')
        self.assertEqual(parsed['--public-search'], 'off')
        self.assertRegex(DOC, r'`--public-jobs auto\\\|off` \| Default `auto`')
        self.assertRegex(DOC, r'`--public-search auto\\\|off` \| Default `off`')

    def test_worker_range_matches_validation(self):
        low, high = map(int, re.search(r'if not (\d+) <= args\.workers <= (\d+):', CLI).groups())
        self.assertEqual(options()['--workers'], 4)
        self.assertIn(f'| `--workers N` | Concurrent companies, {low}..{high}; default 4.', DOC)
        self.assertNotIn('1..8', DOC)
        self.assertIn(f'`--workers` accepts {low}..{high} (default 4)', README)

    def test_request_budget_text_matches_summary_constants(self):
        constants = dict(re.findall(r"'(request_budget_per_unique_company|base_request_budget_per_unique_company|"
                                    r"late_verified_portal_request_allowance)': (\d+)", CLI))
        self.assertEqual(constants, {'request_budget_per_unique_company': '24',
                                     'base_request_budget_per_unique_company': '20',
                                     'late_verified_portal_request_allowance': '4'})
        self.assertIn('base budget of 20 HTTP requests', DOC)
        self.assertIn('may add at most 4 requests, so a company never exceeds 24', DOC)
        self.assertNotIn('limits each distinct company observation to 20 HTTP requests', DOC)
        self.assertIn('hard ceiling 24', README)


if __name__ == '__main__':
    unittest.main()
