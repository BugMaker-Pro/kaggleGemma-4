"""Analyze the frozen graph-control factorial without treating seeds as tasks.

Repository-cluster intervals and exhaustive repository sign flips are the main
inference. Every randomized arm is averaged within task first. See the protocol.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from experiments.graph_controls import SEEDS
from tools.analyse import sign_test

REPRESENTATIONS=('metadata','body','dense')
FAMILIES=('base','real','file','rewired','rewired_pair')


def load(path):
    return [json.loads(line) for line in Path(path).open(encoding='utf-8') if line.strip()]


def value(row,representation,arm,metric='symbol'):
    arms=row['representations'][representation]['arms']
    if arm in ('rewired','rewired_pair'):
        return statistics.fmean(arms[f'{arm}_{seed}'][metric] for seed in SEEDS)
    return arms[arm][metric]


def holm(pvalues):
    ordered=sorted(pvalues,key=pvalues.get)
    adjusted={}
    running=0.0
    for i,key in enumerate(ordered):
        running=max(running,(len(ordered)-i)*pvalues[key])
        adjusted[key]=min(1.0,running)
    return adjusted


def paired_summary(differences,repositories,resamples=10000):
    import numpy as np
    grouped=defaultdict(list)
    for delta,repo in zip(differences,repositories):
        grouped[repo].append(delta)
    repos=sorted(grouped)
    sums=np.array([sum(grouped[repo]) for repo in repos])
    counts=np.array([len(grouped[repo]) for repo in repos])
    rng=np.random.default_rng(20261101)
    draws=rng.integers(0,len(repos),size=(resamples,len(repos)))
    boot=sums[draws].sum(axis=1)/counts[draws].sum(axis=1)
    lo,hi=np.quantile(boot,[0.025,0.975])
    # Whole-repository sign flips preserve all within-repository dependence.
    observed=abs(float(sums.sum()))
    exceed=sum(abs(sum(sign*total for sign,total in zip(signs,sums)))>=observed-1e-12
               for signs in itertools.product((-1,1),repeat=len(repos)))
    p=exceed/(2**len(repos))
    wins=sum(delta>1e-12 for delta in differences)
    losses=sum(delta < -1e-12 for delta in differences)
    return {'n':len(differences),'repositories':len(repos),
            'delta':statistics.fmean(differences),'cluster_ci95':[float(lo),float(hi)],
            'repository_signflip_p':p,'task_sign_p':sign_test(wins,losses),
            'wins':wins,'losses':losses,'ties':len(differences)-wins-losses,
            'positive_repositories':int((sums>1e-12).sum()),
            'per_repo':{repo:{'n':len(grouped[repo]),'delta':statistics.fmean(grouped[repo])}
                        for repo in repos}}


def summarize(rows):
    repositories=[row['repo'] for row in rows]
    arms={rep:{family:{metric:statistics.fmean(value(row,rep,family,metric) for row in rows)
                          for metric in ('symbol','file','gained','lost')}
               for family in FAMILIES} for rep in REPRESENTATIONS}
    primary={}
    topology={rep:[value(row,rep,'real')-value(row,rep,'rewired') for row in rows]
              for rep in REPRESENTATIONS}
    for rep in REPRESENTATIONS:
        primary[f'{rep}:real-rewired']=paired_summary(topology[rep],repositories)
    for rep in ('body','dense'):
        delta=[a-b for a,b in zip(topology[rep],topology['metadata'])]
        primary[f'interaction:{rep}-metadata']=paired_summary(delta,repositories)
    adjusted=holm({key:stats['repository_signflip_p'] for key,stats in primary.items()})
    for key,stats in primary.items():
        stats['holm_p']=adjusted[key]
    secondary={}
    for rep in REPRESENTATIONS:
        for baseline in ('base','file','rewired_pair'):
            delta=[value(row,rep,'real')-value(row,rep,baseline) for row in rows]
            secondary[f'{rep}:real-{baseline}']=paired_summary(delta,repositories)
    mobility={}
    for family in ('rewired','rewired_pair'):
        fractions=[statistics.fmean(x['changed_fraction'] for x in row['rewiring'][family]) for row in rows]
        mobile=[row for row,fraction in zip(rows,fractions) if fraction>=0.25]
        mobility[family]={
            'mean_changed_edge_fraction':statistics.fmean(fractions),
            'median_changed_edge_fraction':statistics.median(fractions),
            'no_final_edges_changed':sum(f==0 for f in fractions),
            'no_accepted_swap':sum(all(d['accepted']==0 for d in row['rewiring'][family]) for row in rows),
            'mobile_n':len(mobile),
            'seed_recalls':{rep:{str(seed):statistics.fmean(
                row['representations'][rep]['arms'][f'{family}_{seed}']['symbol'] for row in rows)
                for seed in SEEDS} for rep in REPRESENTATIONS},
            'reach_changed_tasks':{rep:sum(any(d['reach_changed'][rep]>0 for d in row['rewiring'][family])
                                        for row in rows) for rep in REPRESENTATIONS}}
        if mobile:
            mobility[family]['mobile_effects']={rep:paired_summary(
                [value(row,rep,'real')-value(row,rep,family) for row in mobile],
                [row['repo'] for row in mobile]) for rep in REPRESENTATIONS}
    return {'n':len(rows),'repositories':len(set(repositories)),'arms':arms,
            'primary':primary,'secondary':secondary,'mobility':mobility,
            'graph':{'zero_edge_tasks':sum(row['graph_edges']==0 for row in rows),
                     'median_edges':statistics.median(row['graph_edges'] for row in rows),
                     'pool_symbol_recall':statistics.fmean(row['pool_gold']/row['gold_total'] for row in rows)}}


def retained_seed_diagnostics(path, wanted):
    # Descriptive headroom only; not an additional significance test or a
    # selection criterion. It guards against calling seed saturation causal.
    collected={rep:defaultdict(list) for rep in REPRESENTATIONS}
    with Path(path).open(encoding='utf-8') as handle:
        for line in handle:
            if not line.strip():
                continue
            context=json.loads(line)
            if context['instance_id'] not in wanted:
                continue
            labels=context['labels'];total=context['gold_total'];pool_hits=sum(labels)
            for rep,order in context['orders'].items():
                seed_hits=sum(labels[i] for i in order[:5])
                base_hits=sum(labels[i] for i in order[:10])
                oracle=seed_hits+min(5,pool_hits-seed_hits)
                collected[rep]['seed_recall'].append(seed_hits/total)
                collected[rep]['remaining_slot_oracle'].append(oracle/total)
                collected[rep]['available_recall_gain'].append((oracle-base_hits)/total)
                collected[rep]['tasks_with_reordering_headroom'].append(int(oracle>base_hits))
    return {rep:{metric:(sum(values) if metric.startswith('tasks_') else statistics.fmean(values))
                 for metric,values in metrics.items()} for rep,metrics in collected.items()}


def fmt_effect(stats):
    lo,hi=stats['cluster_ci95']
    return f"{100*stats['delta']:+.2f} [{100*lo:+.2f}, {100*hi:+.2f}]"


def report(summary,path):
    full=summary['full']
    lines=['# 图拓扑对照与检索表示交互：实验结果', '',
           f"完整评估 **{full['n']} 个任务、{full['repositories']} 个仓库**。协议见 `docs/graph-control-protocol.md`。",
           '', '同一原始候选池、保留前五个种子、十个符号位置。随机图五个种子先在任务内平均。',
           '正文 BM25 使用全仓库语料统计，但只重排共同候选池；没有重新训练模型或扩大候选集。',
           'dense 是冻结编码器单独排序；不采用已包含图特征的 44.7% 融合排序器作为无图底座，以免循环比较。',
           '', '## 绝对召回率', '', '| 排序表示 | 干预 | 符号 recall@10 | 文件 recall@10 | 平均新增金标 | 平均丢失金标 |',
           '| --- | --- | ---: | ---: | ---: | ---: |']
    for rep in REPRESENTATIONS:
        for arm in FAMILIES:
            row=full['arms'][rep][arm]
            lines.append(f"| {rep} | {arm} | {row['symbol']:.4f} | {row['file']:.4f} | {row['gained']:.4f} | {row['lost']:.4f} |")
    if 'retained_seed_diagnostics' in summary:
        lines+=['','### 保留种子的剩余改善空间（事后描述，非新增检验）','',
                '| 表示 | 前五种子金标 recall | 保留种子后的 oracle@10 | 相对原排序最大可改善空间 | 仍可通过重排改善的任务 |',
                '| --- | ---: | ---: | ---: | ---: |']
        for rep,diag in summary['retained_seed_diagnostics'].items():
            lines.append(f"| {rep} | {diag['seed_recall']:.4f} | {diag['remaining_slot_oracle']:.4f} | {diag['available_recall_gain']:.4f} | {diag['tasks_with_reordering_headroom']} |")
        lines+=['','表示更强时，种子可能已包含更多答案；交互效应也可能受剩余改善空间影响。不能将交互直接归因为正文补偿了图信息。']
    lines+=['','## 预先指定的五个主要对比','',
            '效应与区间单位为百分点；区间为仓库 cluster bootstrap 的逐项区间（未作同时覆盖校正）。p 值为穷举仓库符号翻转，Holm 同时校正五项。',
            '', '| 对比 | 效应 [95% CI] | 仓库检验 p | Holm p | 任务胜/负 | 正向仓库数 |',
            '| --- | ---: | ---: | ---: | ---: | ---: |']
    for name,stats in full['primary'].items():
        lines.append(f"| {name} | {fmt_effect(stats)} | {stats['repository_signflip_p']:.4f} | {stats['holm_p']:.4f} | {stats['wins']}/{stats['losses']} | {stats['positive_repositories']}/{stats['repositories']} |")
    lines+=['','交互 =（新表示下真实图 − 随机图）−（metadata 下真实图 − 随机图）。负值表示条件拓扑优势缩小，不自动证明因果补偿机制。',
            '', '## 次要对比（探索性，不做主结论筛选）','',
            '| 对比 | 效应 [95% CI] | 仓库检验 p（未校正） | 任务胜/负 |',
            '| --- | ---: | ---: | ---: |']
    for name,stats in full['secondary'].items():
        lines.append(f"| {name} | {fmt_effect(stats)} | {stats['repository_signflip_p']:.4f} | {stats['wins']}/{stats['losses']} |")
    lines+=['','## 随机对照是否真正改变图','',
            f"共同候选图中位边数 {full['graph']['median_edges']}；{full['graph']['zero_edge_tasks']} 个任务没有候选池内边。",
            '', '| 对照 | 原始边被替换比例均值/中位数 | 完全没有接受交换的任务 | 最终边未变化的任务 | 替换比例 ≥25% 任务 |',
            '| --- | ---: | ---: | ---: | ---: |']
    for family,stats in full['mobility'].items():
        lines.append(f"| {family} | {stats['mean_changed_edge_fraction']:.3f}/{stats['median_changed_edge_fraction']:.3f} | {stats['no_accepted_swap']} | {stats['no_final_edges_changed']} | {stats['mobile_n']} |")
    for family,stats in full['mobility'].items():
        lines+=['',f'### {family} 的可移动子集（图属性筛选，探索性）','',
                '| 表示 | 真实图减对照 [95% CI]，百分点 | 五个随机种子的全量召回范围 | 至少一次种子可达集合变化的任务 |',
                '| --- | ---: | ---: | ---: |']
        for rep in REPRESENTATIONS:
            effects=stats.get('mobile_effects',{}).get(rep)
            recalls=list(stats['seed_recalls'][rep].values())
            lines.append(f"| {rep} | {fmt_effect(effects) if effects else '无可移动任务'} | {min(recalls):.4f}–{max(recalls):.4f} | {stats['reach_changed_tasks'][rep]} |")
    if 'lite' in summary:
        lines+=['','## Lite 描述性复核（属于全量，不独立）','',
                '| 表示 | 原排序 | 真实图 | 同文件 | 随机图 | 严格随机图 |',
                '| --- | ---: | ---: | ---: | ---: | ---: |']
        for rep in REPRESENTATIONS:
            cells=[f"{summary['lite']['arms'][rep][arm]['symbol']:.4f}" for arm in FAMILIES]
            lines.append('| '+rep+' | '+' | '.join(cells)+' |')
    sensitivity_path=ROOT/'data/graph_controls_tie_sensitivity.json'
    if sensitivity_path.exists():
        sensitivity=json.loads(sensitivity_path.read_text(encoding='utf-8'))
        lines+=['','## Dense 并列规则敏感性（事后审计发现，主协议未变）','',
                f"原协议保留 encoder 保存的候选顺序；历史融合脚本改为按四舍五入分数排序、候选索引打破并列。共有 {sensitivity['changed_order_tasks']} 个任务的完整顺序不同，{sensitivity['changed_top10_membership_tasks']} 个任务的前十成员不同，{sensitivity['changed_seed_membership_tasks']} 个任务的前五成员不同。",
                '', '只有 django__django-11019 的 dense 基线符号 recall 因边界并列而变化（0 对 1/3），因此全量主实验为 0.3659，历史规则为 0.3661。两种规则均完整报告，不替换主实验。',
                '', '| 主要对比（历史并列规则） | 效应，百分点 | Holm p |',
                '| --- | ---: | ---: |']
        for name,stats in sensitivity['full']['primary'].items():
            lines.append(f"| {name} | {100*stats['delta']:+.2f} | {stats['holm_p']:.4f} |")
        lines+=['', '这项敏感性检查没有改变五个主要对比的显著性判断。']
    lines+=['','## 推断边界','',
            '- 这些比较识别的是给定候选池与一跳排序规则下的条件效应。不能外推为多轮 agent 或图扩展的结论。',
            '- 随机交换保持每个节点的文件内/跨文件度数；严格版本还保持每个节点到各文件的度数。候选池外边不变。',
            '- 没有证明图交换链混合充分，也不声称均匀抽样。高度受限或不可移动的零差异不能证明拓扑不重要。',
            '- 同文件控制促进的候选数可能不同，不能仅凭它优于真实图就认定图没有独立信息。',
            '- 仓库符号翻转需要零假设下效果符号可交换/对称；十二个仓库仍限制泛化与精度。区间未对图随机种子的有限抽样做嵌套重采样；另列五种子的结果范围。',
            '- 本研究是在已探索的基准上新增对照，不是独立外部验证。所有主要比较与随机种子在新结果检查前固定。',
            '', '完整逐任务输出、投影上下文、输入哈希及各仓库效应分别保存于 `data/graph_controls*.jsonl`、manifest 和 summary JSON。']
    if summary['partial']:
        lines.insert(2, '**DEBUG: partial population; do not interpret as the planned full study.**\n')
    if (ROOT/'docs/figures/graph_controls.png').exists():
        lines.insert(4, '![Graph-control results](figures/graph_controls.png)\n')
    Path(path).write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--rows',default=str(ROOT/'data/graph_controls.jsonl'))
    parser.add_argument('--out',default=str(ROOT/'data/graph_controls_summary.json'))
    parser.add_argument('--report',default=str(ROOT/'docs/graph-control-results.md'))
    parser.add_argument('--allow-partial',action='store_true',help='debug only; do not use for publication')
    args=parser.parse_args(argv)
    rows=load(args.rows)
    ids=[row['instance_id'] for row in rows]
    expected={row['instance_id'] for row in load(ROOT/'data/features_full.jsonl')}
    if len(set(ids))!=len(ids) or (not args.allow_partial and set(ids)!=expected):
        raise ValueError('Duplicate rows or incomplete full population')
    lite_ids={row['instance_id'] for row in load(ROOT/'data/swebench_lite.jsonl')}
    def sha(path):
        h=hashlib.sha256()
        with Path(path).open('rb') as f:
            for block in iter(lambda:f.read(1024*1024),b''):
                h.update(block)
        return h.hexdigest()
    summary={'full':summarize(rows),'protocol':'docs/graph-control-protocol.md',
             'analysis_sha256':sha(__file__),'results_sha256':sha(args.rows),
             'partial':bool(args.allow_partial),'random_seeds':list(SEEDS)}
    context_path=Path(args.rows).with_name(Path(args.rows).stem+'_context.jsonl')
    summary['context_sha256']=sha(context_path)
    summary['retained_seed_diagnostics']=retained_seed_diagnostics(context_path,set(ids))
    lite=[row for row in rows if row['instance_id'] in lite_ids]
    if lite:
        summary['lite']=summarize(lite)
    Path(args.out).write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8')
    report(summary,args.report)
    print(f"full n={len(rows)}; wrote {args.out} and {args.report}")
    for name,stats in summary['full']['primary'].items():
        print(f"{name}: {fmt_effect(stats)} Holm p={stats['holm_p']:.4f}")
    return 0


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(main())
