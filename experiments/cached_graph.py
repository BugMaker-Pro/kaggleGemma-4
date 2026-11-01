"""Content-cached implementation of the existing AST graph and body documents.

Only file-local parsing/tokenization is cached. Name resolution is redone against
every snapshot's full node set; no graph or label is borrowed across commits.
Default module_root/keep_text behavior only. Checked against build_graph.
"""
from __future__ import annotations

import ast
import hashlib
import math
import warnings
from collections import Counter

from experiments import buildgraph as original
from experiments.retrieve import document_text, tokenize
from experiments.symbols import python_symbols


class CachedBuilder:
    def __init__(self):
        self.entries = {}
        self.repo = None

    def file_record(self, path, source):
        if source is None:
            return None, False
        fingerprint = hashlib.sha256(source.encode('utf-8')).digest()
        previous = self.entries.get(path)
        if previous and previous[0] == fingerprint:
            return previous[1], True
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', SyntaxWarning)
                tree = ast.parse(source)
        except (SyntaxError, ValueError):
            self.entries[path] = (fingerprint, None)
            return None, False
        module = original.module_of(path)
        symbols = python_symbols(source, tree)
        definitions = original._def_index(tree)
        local = original.Graph()
        lines = source.splitlines()
        if module:
            local.add_node(module, module.rsplit('.',1)[-1], 'module', path, 1,
                           len(lines), '', original._doc(tree), None)
        references = []
        definition_edges = []
        for symbol in symbols:
            node_id = f'{module}.{symbol.qualname}' if module else symbol.qualname
            ast_node = definitions.get((symbol.name, symbol.lineno))
            local.add_node(node_id, symbol.name, symbol.kind, path, symbol.lineno, symbol.end_lineno,
                           original._signature(ast_node, source) if ast_node is not None else symbol.name,
                           original._doc(ast_node) if ast_node is not None else '', None)
            definition_edges.append((node_id.rsplit('.',1)[0], node_id))
            if ast_node is None:
                continue
            if isinstance(ast_node, ast.ClassDef):
                for base in ast_node.bases:
                    dotted = original._dotted(base)
                    if dotted:
                        references.append((node_id,dotted,original.EDGE_INHERITS))
            for call in original._calls_in(ast_node):
                dotted = original._dotted(call.func)
                if dotted:
                    references.append((node_id,dotted,original.EDGE_CALLS))
        counts = {}
        for node_id,node in local.nodes.items():
            start=max(node.get('lineno',1)-1,0)
            end=min(node.get('end_lineno') or start+1,start+80)
            text=document_text(node)+'\n'+'\n'.join(lines[start:end])
            tf=Counter(tokenize(text))
            counts[node_id]=(sum(tf.values()),tf)
        record={'module':module,'nodes':local.nodes,'defines':definition_edges,
                'aliases':original._imports(tree,module),'references':references,'counts':counts}
        self.entries[path]=(fingerprint,record)
        return record,False

    def build(self, files, repo):
        if repo != self.repo:
            self.entries.clear()
            self.repo=repo
        parsed=[]
        hits=0
        for path in sorted(files):
            record,hit=self.file_record(path,files[path])
            hits+=hit
            if record is not None:
                parsed.append(record)
        graph=original.Graph()
        counts={}
        for record in parsed:
            for node_id,node in record['nodes'].items():
                if node_id in graph.nodes:
                    continue
                graph.nodes[node_id]=node
                graph.by_leaf.setdefault(node['name'],[]).append(node_id)
                counts[node_id]=record['counts'][node_id]
        for record in parsed:
            for source,target in record['defines']:
                if target in graph.nodes:
                    graph.add_edge(source,target,original.EDGE_DEFINES,original.R_LOCAL)
        modules={record['module'] for record in parsed}
        node_ids=set(graph.nodes)
        for record in parsed:
            module,aliases=record['module'],record['aliases']
            for target in aliases.values():
                if target in node_ids or target in modules:
                    why=original.R_IMPORT
                elif original._is_stdlib(target):
                    why=original.R_EXTERNAL
                else:
                    why=original.R_UNRESOLVED
                graph.add_edge(module,target,original.EDGE_IMPORTS,why)
            for source,dotted,kind in record['references']:
                target,why=original._resolve(dotted,module,aliases,modules,graph.by_leaf,node_ids)
                graph.add_edge(source,target,kind,why)
        # Drop removed paths; unchanged paths keep content-addressed descriptors.
        for path in set(self.entries)-files.keys():
            del self.entries[path]
        return graph,counts,{'files':len(files),'cache_hits':hits,'parsed':len(parsed)}


def cached_body_scores(counts, query, wanted, k1=1.2,b=0.75):
    terms=sorted(set(tokenize(query)))
    df=Counter()
    total_length=0
    for length,tf in counts.values():
        total_length+=length
        df.update(term for term in terms if term in tf)
    n=len(counts)
    avgdl=total_length/n if n else 1.0
    idf={term:math.log(1+(n-df[term]+0.5)/(df[term]+0.5)) for term in terms}
    scores=[]
    for name in wanted:
        length,tf=counts[name]
        value=0.0
        for term in terms:
            frequency=tf.get(term,0)
            if frequency:
                value+=idf[term]*frequency*(k1+1)/(frequency+k1*(1-b+b*length/(avgdl or 1)))
        scores.append(value)
    return scores
