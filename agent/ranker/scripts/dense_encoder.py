"""Original BGE CLS inference or explicit per-row INT8 deployment weights.

No network downloads are permitted. Quantization is an inference deployment
variant; this module never represents its scores as the original saved scores.
"""
from __future__ import annotations
import base64
import io
import json
import os
from pathlib import Path

PREFIX='Represent this query for retrieving code: '

def load_encoder(assets: Path, original: Path|None=None):
    import numpy as np
    import torch
    from transformers import AutoConfig,AutoModel,AutoTokenizer
    torch.set_num_threads(min(2,os.cpu_count() or 1))
    location=original if original is not None else assets/'encoder'
    tokenizer=AutoTokenizer.from_pretrained(location,local_files_only=True)
    if original is not None:
        model=AutoModel.from_pretrained(location,local_files_only=True,torch_dtype=torch.float32)
        precision='original-fp32-cpu'
    else:
        config=AutoConfig.from_pretrained(location,local_files_only=True)
        model=AutoModel.from_config(config)
        metadata=json.loads((location/'quantization.json').read_text(encoding='utf-8'))
        payload=base64.b85decode((location/'weights-int8.txt').read_bytes())
        arrays=np.load(io.BytesIO(payload),allow_pickle=False)
        state={}
        for record in metadata['tensors']:
            value=arrays[record['key']]
            if record['quantized']:
                value=value.astype(np.float32)*arrays[record['scale_key']]
            state[record['name']]=torch.from_numpy(value.copy())
        # Older BERT checkpoints serialize this deterministic non-persistent buffer.
        if 'embeddings.position_ids' in state and 'embeddings.position_ids' not in model.state_dict():
            positions=state.pop('embeddings.position_ids')
            if not torch.equal(positions,torch.arange(config.max_position_embeddings).unsqueeze(0)):
                raise ValueError('Unexpected serialized BERT position IDs')
        model.load_state_dict(state,strict=True)
        precision='per-row-int8-dequantized-fp32-cpu'
    return tokenizer,model.eval(),precision

def dense_scores(issue,documents,assets,original=None,batch_size=8):
    import torch
    tokenizer,model,precision=load_encoder(assets,original)
    def encode(texts):
        batches=[]
        for start in range(0,len(texts),batch_size):
            tokens=tokenizer(texts[start:start+batch_size],padding=True,truncation=True,max_length=512,return_tensors='pt')
            with torch.inference_mode():values=model(**tokens).last_hidden_state[:,0]
            batches.append(torch.nn.functional.normalize(values.float(),dim=-1))
        return torch.cat(batches)
    query=encode([PREFIX+issue[:1200]])
    embeddings=encode(documents)
    scores=(embeddings@query.T).squeeze(-1).tolist()
    return [round(float(value),4) for value in scores],precision
