"""Bounded evaluator entrypoint. Kills a stalled collector and preserves terminal output order."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


def stop(process):
    if process.poll() is None:
        try:
            if os.name == 'posix':
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def collect(command, staged_output, rows, timeout, log, previous=None, paid_search=False):
    started = time.monotonic()
    with open(log, 'w') as stream:
        process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT,
                                   start_new_session=(os.name == 'posix'))
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            stop(process)
        except BaseException:
            stop(process)
            raise
    results = []
    if Path(staged_output).exists():
        for line in Path(staged_output).read_text(errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                break  # A killed writer can leave one incomplete last line.
            index = len(results)
            if (index >= len(rows) or row.get('organisation_number') != str(rows[index]['organisation_number'])
                    or row.get('run', {}).get('terminal_status') not in ('completed', 'failed')):
                break  # Preserve only the matching, complete prefix.
            results.append(row)
    preserved = len(results)
    reason = 'collector wall-clock deadline exceeded' if timed_out else f'collector output incomplete or invalid (exit {process.returncode})'
    for row in rows[preserved:]:
        org = str(row['organisation_number'])
        prior = (previous or {}).get(org)
        results.append({'organisation_number':org, 'claims':[], 'evidence':[], 'changes':[],
                        'errors':[{'reason':reason}], 'source_snapshots':[], 'previous_snapshot':prior,
                        'refresh':{'mode':'collector_failed', 'changed_fields':[], 'cache_declared':True},
                        'synthesis':[], 'run':{'terminal_status':'failed',
                        'completed_at':dt.datetime.now(dt.timezone.utc).isoformat()},
                        'operations':{'requests':20, 'requests_are_upper_bound':True,
                                      'cache_hits':0, 'cache_hits_unavailable':True,
                                      'third_party_cost_usd':None if paid_search else 0}})
    report = {'wall_clock_timeout':timed_out, 'collector_exit':process.returncode,
              'preserved_outputs':preserved, 'synthesized_failures':len(results)-preserved,
              'runtime_seconds':round(time.monotonic()-started, 3), 'timeout_seconds':timeout,
              'note':'Interrupted-company request counts are conservative upper bounds, not observed usage.'}
    return results, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timeout-seconds', type=float, default=2400)
    parser.add_argument('collector_args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if not 0 < args.timeout_seconds <= 2600:
        parser.error('timeout must be positive and at most 2600 seconds, leaving evaluator shutdown time')
    flags = args.collector_args
    if flags and flags[0] == '--':
        flags = flags[1:]
    paths = argparse.ArgumentParser(add_help=False)
    paths.add_argument('--input',required=True); paths.add_argument('--output',required=True)
    paths.add_argument('--previous'); paths.add_argument('--search',default='none')
    files, _ = paths.parse_known_args(flags)
    rows = [json.loads(x) for x in Path(files.input).read_text().splitlines() if x.strip()]
    prior = {r['organisation_number']:r for r in (json.loads(x) for x in Path(files.previous).read_text().splitlines() if x.strip())} if files.previous else {}
    output = Path(files.output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.signalpost-run-',dir=output.parent) as temporary:
        staged = Path(temporary)/'output.jsonl'
        # argparse accepts the last occurrence; never let a partial collector
        # overwrite an existing completed output artifact.
        command = [sys.executable, str(Path(__file__).with_name('agent.py')), *flags, '--output', str(staged)]
        results, report = collect(command, staged, rows, args.timeout_seconds,
                                  output.with_suffix('.collector.log'), prior, files.search == 'tavily')
        complete = Path(temporary)/'complete.jsonl'
        complete.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n' for r in results))
        complete.replace(output)
        source_report = staged.with_suffix('.report.json')
        target_report = output.with_suffix('.report.json')
        if source_report.exists():
            target_report.write_bytes(source_report.read_bytes())
        else:
            target_report.write_text(json.dumps({'inputs':len(rows),'outputs':len(results),
                'failed':sum(r['run']['terminal_status']=='failed' for r in results),
                'requests':sum(r['operations']['requests'] for r in results),
                'requests_include_upper_bounds':bool(report['synthesized_failures']),
                'official_score':None,'guard':report},indent=2)+'\n')
    output.with_suffix('.guard.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 2 if report['synthesized_failures'] or report['wall_clock_timeout'] or report['collector_exit'] != 0 else 0


if __name__ == '__main__':
    raise SystemExit(main())
