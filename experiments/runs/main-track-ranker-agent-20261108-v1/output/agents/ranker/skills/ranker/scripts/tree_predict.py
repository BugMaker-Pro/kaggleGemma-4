"""Small dependency-free evaluator for exported numerical LightGBM trees."""
from __future__ import annotations
import math
import json
import base64
import zlib

def tree_score(tree, row):
    node=tree
    while 'leaf_value' not in node:
        if node.get('decision_type')!='<=':
            raise ValueError('Only numerical <= splits are supported')
        value=float(row[node['split_feature']])
        missing=math.isnan(value) or (node.get('missing_type')=='Zero' and value==0)
        go_left=node['default_left'] if missing else value<=float(node['threshold'])
        node=node['left_child' if go_left else 'right_child']
    return float(node['leaf_value'])

def ensemble_scores(models, rows):
    if not models:raise ValueError('No ranking models supplied')
    width=models[0]['max_feature_idx']+1
    if any(m['max_feature_idx']+1!=width for m in models) or any(len(row)!=width for row in rows):
        raise ValueError('Ranker feature width mismatch')
    result=[]
    for row in rows:
        result.append(sum(sum(tree_score(t['tree_structure'],row) for t in m['tree_info']) for m in models)/len(models))
    return result

def load_ranker(path):
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('format')=='zlib-json-v1':
        record=json.loads(zlib.decompress(base64.b85decode(record['payload'])))
    return record['models']
