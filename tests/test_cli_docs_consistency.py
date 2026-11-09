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
DOCKERFILE = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
DOCKERIGNORE = (ROOT / '.dockerignore').read_text(encoding='utf-8')
LITERAL_DOCKERIGNORE_ALLOW_RE = re.compile(r'^!([A-Za-z0-9_.-]+)$')


def dockerignore_literal_allowlist(dockerignore_text=DOCKERIGNORE):
    rules = [
        raw.strip()
        for raw in dockerignore_text.splitlines()
        if raw.strip() and not raw.strip().startswith('#')
    ]
    if not rules or rules[0] != '*':
        raise ValueError('.dockerignore must start with a literal "*" deny-all rule')
    allowed = set()
    for rule in rules[1:]:
        match = LITERAL_DOCKERIGNORE_ALLOW_RE.match(rule)
        if not match:
            raise ValueError(f'Unsupported non-literal .dockerignore rule: {rule!r}')
        allowed.add(match.group(1))
    return allowed


def missing_dockerignore_allowlist_entries(copied_files, allowed_files=None):
    if allowed_files is None:
        allowed_files = dockerignore_literal_allowlist()
    return sorted(set(copied_files) - set(allowed_files))


def dockerfile_copied_files(dockerfile_text=DOCKERFILE):
    copied = []
    for raw_line in dockerfile_text.splitlines():
        line = raw_line.strip()
        if line.startswith('COPY '):
            copied.extend(line.split()[1:-1])
    return copied


def missing_dockerfile_local_imports(copied_files):
    copied_set = set(copied_files)
    local_modules = {path.stem for path in ROOT.glob('*.py')}
    missing = {}
    for filename in sorted(copied_set):
        if not filename.endswith('.py'):
            continue
        tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'), filename=filename)
        needed = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split('.')[0]
                    if root_mod in local_modules:
                        needed.add(f'{root_mod}.py')
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                root_mod = node.module.split('.')[0]
                if root_mod in local_modules:
                    needed.add(f'{root_mod}.py')
        absent = sorted(needed - copied_set)
        if absent:
            missing[filename] = absent
    return missing


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

    def test_dockerfile_copy_closes_over_all_top_level_and_lazy_local_imports(self):
        copied = dockerfile_copied_files()
        self.assertIn('contact_map_identity.py', copied)
        for required in ('cli.py', 'evaluator.py', 'agent.py', 'audit.py', 'organization_types.json'):
            self.assertIn(required, copied)
        for filename in copied:
            self.assertTrue((ROOT / filename).is_file(), filename)
        self.assertEqual(missing_dockerfile_local_imports(copied), {})
        without_contact_map = [name for name in copied if name != 'contact_map_identity.py']
        self.assertEqual(
            missing_dockerfile_local_imports(without_contact_map),
            {'agent.py': ['contact_map_identity.py'], 'audit.py': ['contact_map_identity.py']},
        )

    def test_copied_modules_do_not_hide_local_imports_behind_import_error_handlers(self):
        local_modules = {path.stem for path in ROOT.glob('*.py')}
        guarded_names = {'ImportError', 'ModuleNotFoundError', 'Exception', 'BaseException'}
        hidden_local_imports = []
        for filename in sorted(dockerfile_copied_files()):
            if not filename.endswith('.py'):
                continue
            tree = ast.parse((ROOT / filename).read_text(encoding='utf-8'), filename=filename)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try):
                    continue
                catches_import_error = any(
                    handler.type is None or any(
                        isinstance(sub, ast.Name) and sub.id in guarded_names
                        for sub in ast.walk(handler.type)
                    )
                    for handler in node.handlers
                )
                if not catches_import_error:
                    continue
                for stmt in node.body:
                    for inner in ast.walk(stmt):
                        if isinstance(inner, ast.Import):
                            for alias in inner.names:
                                root_mod = alias.name.split('.')[0]
                                if root_mod in local_modules:
                                    hidden_local_imports.append((filename, inner.lineno, root_mod))
                        elif isinstance(inner, ast.ImportFrom) and inner.level == 0 and inner.module:
                            root_mod = inner.module.split('.')[0]
                            if root_mod in local_modules:
                                hidden_local_imports.append((filename, inner.lineno, root_mod))
        self.assertEqual(hidden_local_imports, [])

    def test_dockerignore_allowlist_permits_every_dockerfile_copy_source(self):
        copied = dockerfile_copied_files()
        allowed = dockerignore_literal_allowlist()
        self.assertIn('Dockerfile', allowed)
        self.assertIn('contact_map_identity.py', allowed)
        self.assertEqual(missing_dockerignore_allowlist_entries(copied, allowed), [])
        without_contact_map = allowed - {'contact_map_identity.py'}
        self.assertEqual(
            missing_dockerignore_allowlist_entries(copied, without_contact_map),
            ['contact_map_identity.py'],
        )
        with self.assertRaises(ValueError):
            dockerignore_literal_allowlist('!Dockerfile\n')
        with self.assertRaises(ValueError):
            dockerignore_literal_allowlist('*\n!*.py\n')
        with self.assertRaises(ValueError):
            dockerignore_literal_allowlist('*\n!agent.py\nagent.py\n')


if __name__ == '__main__':
    unittest.main()
