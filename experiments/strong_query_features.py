"""Gold-free extension of the historical sixteen-feature scorer to new candidates.

Original pool defines seeds and file statistics. Query for every feature is original issue.
"""
from __future__ import annotations
import math
from collections import defaultdict
from experiments.retrieve import BM25, document_text, tokenize
from experiments.query_pilot import stable_search
from experiments.symbols import python_symbols, resolve
from tools.features import FEATURES, PATH_RE, FRAME_RE, NGRAM, BODY_LINES, _match_file, _run_length


def candidate_features(issue, files, graph, anchor, wanted):
    """anchor contains ONLY ids/rows/files; no gold/labels accepted."""
    if set(anchor) != {'ids','rows','files'}:
        raise ValueError('Anchor accepts only IDs, feature rows and source paths')
    if len(wanted)!=len(set(wanted)) or any(n not in graph.nodes for n in wanted):
        raise ValueError('Invalid candidate IDs')
    nodes=graph.nodes
    docs={node_id:document_text(node) for node_id,node in nodes.items()}
    index=BM25(docs)
    metadata,_=stable_search(index,issue,len(nodes))
    scores={x['id']:x['score'] for x in metadata}
    positions={x['id']:i for i,x in enumerate(metadata,1)}
    pool=list(anchor['ids'])
    if len(pool)!=len(set(pool)) or any(n not in nodes for n in pool):
        raise ValueError('Original pool absent from reconstructed graph')
    anchor_rows=dict(zip(pool,anchor['rows']))
    # Normalize new metadata scores against the same original-query corpus maximum.
    top_score=metadata[0]['score'] if metadata else 1.0
    ranked=[(node_id,anchor_rows[node_id][0]*top_score) for node_id in pool]
    files_of={node_id:node.get('file','') for node_id,node in nodes.items()}
    repo_files={name for name in files if name.endswith('.py')}
    degrees_in: dict[str, int] = defaultdict(int)
    degrees_out: dict[str, int] = defaultdict(int)
    neighbours: dict[str, set[str]] = defaultdict(set)
    for edge in graph.edges:
        if edge.get("type") not in ("calls", "inherits"):
            continue
        source, target = edge.get("source"), edge.get("target")
        if not source or not target:
            continue
        degrees_out[source] += 1
        degrees_in[target] += 1
        neighbours[source].add(target)
        neighbours[target].add(source)

    seeds = set(pool[:5])
    near = set()
    for seed in seeds:
        near |= neighbours.get(seed, set())

    # issue-side signals
    issue_tokens = tokenize(issue)
    issue_set = set(issue_tokens)
    issue_grams = {tuple(issue_tokens[i:i + NGRAM])
                   for i in range(len(issue_tokens) - NGRAM + 1)}
    issue_norm = " ".join(issue.split())

    frame_symbols: set[str] = set()
    frame_files: set[str] = set()
    for raw_path, raw_line in FRAME_RE.findall(issue):
        matched = _match_file(raw_path, repo_files)
        if not matched:
            continue
        frame_files.add(matched)
        source = files.get(matched)
        symbol = resolve(python_symbols(source), int(raw_line)) if source else None
        if symbol is None:
            continue
        module = matched[:-3].replace("/", ".").replace(".__init__", "")
        node_id = f"{module}.{symbol.qualname}" if module else symbol.qualname
        if node_id in nodes:
            frame_symbols.add(node_id)

    named_files = {matched for matched in
                   (_match_file(raw, repo_files) for raw in PATH_RE.findall(issue)) if matched}

    path_df: dict[str, int] = defaultdict(int)
    path_tokens: dict[str, set[str]] = {}
    for name in repo_files:
        tokens = {token.lower() for token in tokenize(name.replace("/", " ").replace(".", " "))}
        path_tokens[name] = tokens
        for token in tokens:
            path_df[token] += 1
    limit = max(len(repo_files) // 20, 2)

    file_scores: dict[str, float] = defaultdict(float)
    file_sizes: dict[str, int] = defaultdict(int)
    for node_id, score in ranked:
        file_path = files_of.get(node_id, "")
        file_scores[file_path] = max(file_scores.get(file_path, 0.0), score)
        file_sizes[file_path] += 1

    line_cache: dict[str, list[str]] = {}

    rows = []
    for node_id in wanted:
        rank = positions.get(node_id, len(nodes)+1)
        score = scores.get(node_id, 0.0)
        node = nodes.get(node_id, {})
        file_path = files_of.get(node_id, "")
        lines = line_cache.get(file_path)
        if lines is None:
            lines = files.get(file_path, "").splitlines()
            line_cache[file_path] = lines
        start = max(node.get("lineno", 1) - 1, 0)
        end = min(node.get("end_lineno") or start + 1, start + BODY_LINES)
        body = "\n".join(lines[start:end])

        run = _run_length(issue_grams, issue_set, body)
        body_line = 0
        for line in body.splitlines():
            stripped = " ".join(line.split())
            if len(stripped) >= 15 and stripped in issue_norm:
                body_line = 1
                break

        tokens = path_tokens.get(file_path, set())
        overlap = sum(1.0 / (1.0 + math.log(path_df[token]))
                      for token in tokens & issue_set
                      if path_df[token] <= limit and len(token) > 2)

        rows.append([
            round(score / (top_score or 1.0), 4),
            round(1.0 / rank, 4),
            min(run, 40) / 40.0,
            float(body_line),
            float(bool(set(named_files) & {file_path})),
            round(overlap, 4),
            float(node_id in frame_symbols),
            float(file_path in frame_files),
            float(file_path in named_files),
            round(math.log1p(degrees_in.get(node_id, 0)), 4),
            round(math.log1p(degrees_out.get(node_id, 0)), 4),
            float(node_id in near and node_id not in seeds),
            round(file_scores.get(file_path, 0.0) / (top_score or 1.0), 4),
            round(math.log1p(file_sizes.get(file_path, 0)), 4),
            round(math.log1p(max((node.get("end_lineno") or 1) - (node.get("lineno") or 1), 1)), 4),
            round(math.log1p(len(tokenize(docs.get(node_id, "")))), 4),
        ])

    # Use the saved normalized BM25 score/rank for original candidates, including
    # historical rounding and tie order; other columns must independently reproduce.
    mismatches=[]
    for node_id,row in zip(wanted,rows):
        if node_id in anchor_rows:
            expected=anchor_rows[node_id]
            for column in range(2,len(FEATURES)):
                if abs(row[column]-expected[column])>1e-9:
                    mismatches.append({'id':node_id,'feature':FEATURES[column],
                                       'rebuilt':row[column],'saved':expected[column]})
            row[0],row[1]=expected[0],expected[1]
    if mismatches:
        raise ValueError(f'Historical feature reproduction failed: {mismatches[:3]}')
    return rows,{'metadata_matches':len(metadata),'existing_rows_verified':sum(n in anchor_rows for n in wanted),
                 'new_rows':sum(n not in anchor_rows for n in wanted),
                 'anchored_file_statistics':True,'anchored_graph_seeds':pool[:5]}
