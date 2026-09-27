"""Explicit local interchange format for frozen registry responses.

This is not a claim of compatibility with an unpublished organizer interface.
"""
import datetime as dt
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit


def registry_url(url):
    p=urlsplit(url)
    return p.scheme=='https' and p.netloc=='data.brreg.no'


class FrozenRegistry:
    def __init__(self,path):
        self.responses={}
        raw=Path(path).read_bytes();self.artifact_sha256=hashlib.sha256(raw).hexdigest()
        for line in raw.decode('utf-8').splitlines():
            if not line.strip():continue
            record=json.loads(line)
            url=record['requested_url'];text=record['text']
            if not registry_url(url) or not registry_url(record['url']):raise ValueError('Snapshot may contain only official registry URLs')
            if url in self.responses:raise ValueError('Duplicate registry URL in snapshot')
            timestamp=dt.datetime.fromisoformat(record['retrieved_at'].replace('Z','+00:00'))
            if timestamp.tzinfo is None:raise ValueError('Snapshot timestamp requires timezone')
            actual=hashlib.sha256(text.encode()).hexdigest()
            if actual!=record.get('retained_text_sha256',record['content_sha256']):raise ValueError('Snapshot text hash mismatch')
            if record.get('status')!='available' or record.get('status_code')!=200:raise ValueError('Snapshot must contain successful source responses')
            parsed=json.loads(text)
            if record.get('json',parsed)!=parsed:raise ValueError('Snapshot JSON differs from retained text')
            self.responses[url]={k:record[k] for k in ('requested_url','url','retrieved_at','content_sha256','text','status','status_code')}
            self.responses[url].update(json=parsed,source_mode='supplied_registry_snapshot',registry_snapshot_sha256=self.artifact_sha256)

    def lookup(self,url):
        record=self.responses.get(url)
        return dict(record) if record else None
