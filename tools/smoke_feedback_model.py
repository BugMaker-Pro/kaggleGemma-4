"""Disposable CPU smoke: random tiny model, never a research measurement."""
import argparse
import contextlib
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import torch
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast
from experiments.feedback_pilot import paired_requests
from experiments.query_pilot import TaskInput
from tools.run_feedback_pilot import freeze, generate, validate_responses

torch.set_num_threads(1)
with tempfile.TemporaryDirectory(prefix='feedback_model_smoke_',dir=Path(__file__).parent) as folder:
    root=Path(folder)
    model_dir=root/'random-fixture'
    raw=Tokenizer(WordLevel({'[UNK]':0,'[PAD]':1,'[EOS]':2,'query':3},unk_token='[UNK]'))
    raw.pre_tokenizer=Whitespace()
    tokenizer=PreTrainedTokenizerFast(tokenizer_object=raw,unk_token='[UNK]',pad_token='[PAD]',eos_token='[EOS]')
    tokenizer.chat_template='{% for message in messages %}{{ message["content"] }}{% endfor %}'
    tokenizer.save_pretrained(model_dir)
    model=GPT2LMHeadModel(GPT2Config(vocab_size=4,n_positions=1024,n_embd=16,n_layer=1,n_head=1,eos_token_id=2,pad_token_id=1,bos_token_id=2))
    model.save_pretrained(model_dir)
    requests=paired_requests(TaskInput('synthetic','o/r','abc','query'),[])
    args=argparse.Namespace(bundle=root,parent=root,model_dir=model_dir,out=root/'run',device='cpu',run_dir=root/'run')
    bundle={'manifest_sha256':'synthetic_bundle','primary':'synthetic only'}
    with patch('tools.run_feedback_pilot.load_bundle',return_value=(bundle,requests,[])),contextlib.redirect_stdout(io.StringIO()):
        freeze(args)
    m=json.loads((args.run_dir/'manifest.json').read_text(encoding='utf-8'))
    with patch('tools.run_feedback_pilot.load_run',return_value=(m,requests,[])),contextlib.redirect_stdout(io.StringIO()):
        generate(args)
    responses=[json.loads(x) for x in (args.run_dir/'responses.jsonl').read_text(encoding='utf-8').splitlines()]
    validate_responses(responses,requests,m)
    assert len(responses)==2
    assert all(r['output_tokens'] is not None for r in responses), responses
    print('Random CPU model loading, chat tokenization, generation and response accounting passed; no research results produced.')
