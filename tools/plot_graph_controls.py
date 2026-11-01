"""Render the completed graph-control study from its audited summary JSON."""
from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))


def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    summary=json.loads((ROOT/'data/graph_controls_summary.json').read_text(encoding='utf-8'))
    if summary['partial'] or summary['full']['n']!=2232:
        raise ValueError('Figure requires the complete pre-specified population')
    data=summary['full']
    colors={'metadata':'#4c647a','body':'#d18a35','dense':'#23897c'}
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                         'axes.spines.right':False,'axes.titleweight':'bold'})
    fig,axes=plt.subplots(1,2,figsize=(12.8,4.7),gridspec_kw={'width_ratios':[1,1.25]},layout='constrained')
    families=['base','real','file','rewired','rewired_pair']
    x=np.arange(len(families))
    for i,rep in enumerate(colors):
        values=[100*data['arms'][rep][arm]['symbol'] for arm in families]
        axes[0].bar(x+(i-1)*0.24,values,width=.23,color=colors[rep],label=rep)
    axes[0].set_xticks(x,['Base','Real\ngraph','Same\nfile','Rewired','Rewired\nfile-pair'])
    axes[0].set_ylabel('Symbol recall@10 (%)')
    axes[0].set_title('Same candidates, three base rankings')
    axes[0].legend(frameon=False,ncol=3,fontsize=9,loc='upper left')
    axes[0].set_ylim(0,max(100*v['symbol'] for rep in data['arms'].values() for v in rep.values())+8)
    names=list(data['primary'])
    labels=['Metadata: real − rewired','Body: real − rewired','Dense: real − rewired',
            'Interaction: body − metadata','Interaction: dense − metadata']
    for i,key in enumerate(names):
        stats=data['primary'][key];mean=100*stats['delta'];lo,hi=[100*v for v in stats['cluster_ci95']]
        color=colors[key.split(':')[0]] if not key.startswith('interaction') else '#444444'
        significant=stats['holm_p']<.05
        axes[1].plot([lo,hi],[i,i],color=color,lw=2)
        axes[1].plot(mean,i,'o',color=color,markerfacecolor=color if significant else 'white',ms=7)
    axes[1].set_yticks(range(len(names)),labels)
    axes[1].invert_yaxis();axes[1].axvline(0,color='#aaaaaa',ls='--',lw=1)
    axes[1].set_xlabel('Paired change in percentage points (repository-cluster 95% CI)')
    axes[1].set_title('Five planned topology contrasts')
    axes[1].text(.01,-.20,'Filled point: Holm-adjusted repository sign-flip p < 0.05.\nFive random seeds averaged within each task.',
                 transform=axes[1].transAxes,fontsize=8.5,va='top',color='#555555')
    fig.suptitle('Graph controls on 2,232 SWE-bench tasks · ten symbol slots · five retained seeds',fontsize=12)
    target=ROOT/'docs/figures/graph_controls.png';target.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(target,dpi=180,bbox_inches='tight')
    print(target)
    return 0


if __name__=='__main__':
    raise SystemExit(main())
