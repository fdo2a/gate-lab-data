#!/usr/bin/env python3
"""보호된 자료 스냅샷을 만든다 (시험용).

  collect.py --market us --date 2026-11-16 --src-git <bare> --commit <sha> [--kind initial|revision|correction]
             [--invalidates 1] [--note 글] [--real auctions]

스냅샷은 snapshots/<market>/<date>/v<N>/ 에 **덧붙이기만** 한다(있는 판은 덮어쓰지 않는다).
파일마다 해시·출처·받은 시각을 manifest.json 에 남기고, index.json 에 판 목록을 남긴다.

시험 저장소에서는 운영 저장소의 그 날짜 커밋을 원천의 **대역**으로 쓴다(source 가 `standin:` 으로 시작).
--real auctions 는 고정 사본의 실제 수집기를 돌려 TreasuryDirect 에서 직접 받고, 대역과 같은지 견준다.
"""
import argparse, datetime as dt, hashlib, json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
OPERATING = 'github.com/fdo2a/fdo2a.github.io'


def git(src, *a):
    return subprocess.run(['git', '--git-dir', src, *a], capture_output=True, check=True).stdout


def now():
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def tree(src, commit):
    out = {}
    for ent in git(src, 'ls-tree', '-r', '-z', commit).decode('utf-8', 'surrogateescape').split('\0'):
        if ent:
            meta, path = ent.split('\t', 1)
            mode, typ, sha = meta.split()
            if typ == 'blob' and mode in ('100644', '100755'):
                out[path] = sha
    return out


def committed_at(src, commit, path):
    """원천 저장소에서 그 파일이 마지막으로 바뀐 시각 = 수집 작업이 그 내용을 적은 때."""
    try:
        s = git(src, 'log', '-1', '--format=%cI', commit, '--', path).decode().strip()
        return dt.datetime.fromisoformat(s).astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ') if s else None
    except Exception:
        return None


def as_of(rel, raw):
    if not rel.endswith('.json'):
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    if isinstance(doc, dict):
        for k in ('report_date', 'date'):
            if isinstance(doc.get(k), str):
                return doc[k]
    return None


def real_auctions(date, market_data):
    """고정 사본의 실제 수집기로 TreasuryDirect 에서 직접 받는다."""
    tmp = tempfile.mkdtemp(prefix='real-')
    open(os.path.join(tmp, 'market_data.json'), 'wb').write(market_data)
    p = subprocess.run([sys.executable, os.path.join(HERE, 'pinned', 'scripts', 'build_auctions.py'),
                        '--datadir', tmp, '--date', date], capture_output=True, text=True, timeout=300)
    print('real collector:', p.returncode, (p.stdout + p.stderr).strip().splitlines()[-1:] )
    path = os.path.join(tmp, 'auctions.json')
    if not os.path.isfile(path):
        return None
    return open(path, 'rb').read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--market', required=True, choices=('us', 'kr'))
    ap.add_argument('--date', required=True)
    ap.add_argument('--src-git', required=True)
    ap.add_argument('--commit', required=True)
    ap.add_argument('--kind', default='initial', choices=('initial', 'revision', 'correction'))
    ap.add_argument('--invalidates', type=int, action='append', default=[])
    ap.add_argument('--note', default='')
    ap.add_argument('--real', action='append', default=[])
    ap.add_argument('--root', default=os.path.join(HERE, 'snapshots'))
    a = ap.parse_args()

    lay = json.load(open(os.path.join(HERE, 'layout', a.market + '.json'), encoding='utf-8'))
    base = os.path.join(a.root, a.market, a.date)
    idx_path = os.path.join(base, 'index.json')
    idx = json.load(open(idx_path, encoding='utf-8')) if os.path.isfile(idx_path) else {'format': 'snapshot-index/1', 'market': a.market, 'date': a.date, 'versions': []}
    v = len(idx['versions']) + 1
    vdir = os.path.join(base, 'v%d' % v)
    if os.path.exists(vdir):
        print('REFUSED: %s already exists — snapshots are append-only' % os.path.relpath(vdir, HERE))
        return 3
    if a.kind == 'initial' and idx['versions']:
        print('REFUSED: an initial snapshot already exists — add a revision or a correction instead')
        return 3
    known = {x['v'] for x in idx['versions']}
    if any(i not in known for i in a.invalidates) or (a.invalidates and a.kind != 'correction'):
        print('REFUSED: --invalidates needs kind=correction and existing versions')
        return 3

    t = tree(a.src_git, a.commit)
    want = {}
    for dst, srcp in lay['files']:
        srcp, dst = srcp.format(date=a.date), dst.format(date=a.date)
        if srcp in t:
            want[dst] = srcp
    for dst, prefix in lay['trees']:
        for p in t:
            if p.startswith(prefix) and p not in lay['exclude']:
                want.setdefault(dst + p[len(prefix):], p)
    files = []
    fetched = now()
    for dst in sorted(want):
        srcp = want[dst]
        raw = git(a.src_git, 'cat-file', 'blob', t[srcp])
        ent = {'path': dst, 'source': 'standin:%s@%s:%s' % (OPERATING, a.commit, srcp),
               'source_committed_at': committed_at(a.src_git, a.commit, srcp), 'fetched_at': fetched}
        # 원천과 맞춰 봤는가 — 보호된 곳에 있다는 것과 원천과 같다는 것은 다른 사실이다
        ent['source_verified'] = {'status': 'not_verified', 'why': '운영 저장소 커밋을 대역으로 받았다 — 원천과 대조하지 않았다'}
        if dst == 'datadir/auctions.json' and 'auctions' in a.real:
            md = git(a.src_git, 'cat-file', 'blob', t['data/market_data.json'])
            real = real_auctions(a.date, md)
            if real is None:
                print('REFUSED: the real collector produced nothing')
                return 4
            x, y = json.loads(real), json.loads(raw)
            x.pop('generated', None), y.pop('generated', None)
            ent.update(source='https://www.treasurydirect.gov/TA_WS/securities/ (pinned build_auctions.py, direct fetch)',
                       source_committed_at=None, fetched_at=now(),
                       xcheck={'against': 'standin:%s@%s:%s' % (OPERATING, a.commit, srcp), 'ignored': ['generated'], 'equal': x == y})
            ent['source_verified'] = {'status': 'matched' if x == y else 'mismatch', 'why': '원천에서 직접 받아 대역과 견줬다(generated 제외) — 이 한 번의 비교에 한한다'}
            raw = real
        ent.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), as_of=as_of(dst, raw))
        out = os.path.join(vdir, 'files', dst)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, 'wb').write(raw)
        files.append(ent)
    man = {'format': 'snapshot/1', 'market': a.market, 'date': a.date, 'version': v, 'kind': a.kind,
           'invalidates': a.invalidates, 'note': a.note, 'created_at': now(),
           'collector': {'run': os.environ.get('GITHUB_RUN_ID'), 'sha': os.environ.get('GITHUB_SHA'), 'repo': os.environ.get('GITHUB_REPOSITORY')},
           'files': files}
    raw = json.dumps(man, ensure_ascii=False, indent=1, sort_keys=True).encode()
    open(os.path.join(vdir, 'manifest.json'), 'wb').write(raw)
    idx['versions'].append({'v': v, 'kind': a.kind, 'invalidates': a.invalidates, 'created_at': man['created_at'],
                            'manifest_sha256': hashlib.sha256(raw).hexdigest(), 'note': a.note})
    os.makedirs(base, exist_ok=True)
    open(idx_path, 'w', encoding='utf-8').write(json.dumps(idx, ensure_ascii=False, indent=1, sort_keys=True) + '\n')
    print('snapshot %s/%s v%d (%s): %d files' % (a.market, a.date, v, a.kind, len(files)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
