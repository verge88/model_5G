"""Publication figures from audited measurements; theoretical values labelled."""
from pathlib import Path
import csv
import json
import os
os.environ.setdefault('MPLCONFIGDIR',str(Path(__file__).resolve().parents[1]/'tmp/matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from theory import stationary_share

R=Path(__file__).resolve().parents[1];E=R/'results/article-evaluation';O=R/'article/figures'
O.mkdir(parents=True,exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,
                     'axes.spines.right':False,'savefig.dpi':220,'pdf.fonttype':42})
def rows(name):
    p=E/name
    return list(csv.DictReader(p.open(encoding='utf-8'))) if p.exists() else []
def save(fig,name):
    for ext in ['png','svg','pdf']:fig.savefig(O/f'{name}.{ext}',bbox_inches='tight')
    plt.close(fig)

def main():
    pairs=[p for p in rows('paired-effects.csv') if p.get('comparable','True')=='True'];effects=rows('effect-summary.csv')
    fig,ax=plt.subplots(figsize=(6.7,4.2))
    rho=np.linspace(.05,.72,150)
    ax.plot(100*rho,[100*(stationary_share(float(r),.5)-1/3) for r in rho],
            color='#666666',linestyle='--',label='Стационарная модель')
    for policy,color,marker,offset in [('swrr','#146a86','o',-.8),('random','#c65b32','s',.8)]:
        ps=[p for p in pairs if p['policy']==policy]
        if not ps:continue
        ax.scatter([100*float(p['rho'])+offset for p in ps],[float(p['delta_pp']) for p in ps],
                   color=color,marker=marker,alpha=.55,s=22,label=policy+' — отдельные пары')
        for e in effects:
            if e['policy']!=policy:continue
            x=100*float(e['rho'])+offset;y=float(e['delta_pp'])
            ax.scatter([x],[y],color=color,marker=marker,s=70,edgecolor='white',zorder=4)
            if e['bootstrap_low']:
                ax.errorbar(x,y,yerr=[[y-float(e['bootstrap_low'])],[float(e['bootstrap_high'])-y]],
                            color=color,capsize=4,linewidth=1.5)
    ax.axhline(0,color='#aaaaaa',linewidth=.7)
    ax.set(xlabel='Общая операционная нагрузка, %',ylabel='Парное изменение доли SMF3, п.п.',
           title='Постоянное занижение нагрузки на 50%')
    ax.legend(fontsize=8);ax.grid(axis='y',alpha=.15)
    fig.text(.1,-.04,'Точки — измерения; линия — расчёт. Интервалы только при ≥3 парах.',fontsize=8)
    save(fig,'effect')
    ds=rows('detectors.csv')
    fig,axs=plt.subplots(1,2,figsize=(8.1,3.5),sharey=True)
    for ax,key,label,color in zip(axs,['empirical_fpr','empirical_pd'],['FPR на честных данных','Pd основной атаки'],['#76698d','#146a86']):
        valid=[d for d in ds if d[key]]
        ax.barh([d['model'] for d in valid],[float(d[key]) for d in valid],color=color)
        ax.set(xlim=(0,1),xlabel=label);ax.grid(axis='x',alpha=.15)
    axs[0].invert_yaxis();fig.tight_layout();save(fig,'detectors')
    audit=json.loads((E/'audit.json').read_text())
    valid=[r for r in audit['runs'] if r['eligible']]
    fig,axs=plt.subplots(1,2,figsize=(8.2,3.8))
    for ax,key,label in zip(axs,['compute_to_nrf','age_at_selection'],['Вычисление → NRF, мс','Возраст при выборе AMF, мс']):
        for q,style,color in [('median_ms','o','#146a86'),('p95_ms','s','#c65b32'),('p99_ms','^','#76698d')]:
            ax.plot(range(1,len(valid)+1),[r['propagation'][key][q] for r in valid],
                    marker=style,markersize=3,linewidth=.7,color=color,label={'median_ms':'p50','p95_ms':'p95','p99_ms':'p99'}[q])
        ax.set(xlabel='Номер пригодного прогона',ylabel=label);ax.legend(fontsize=8);ax.grid(alpha=.15)
    fig.tight_layout();save(fig,'timing')
    byrun=rows('detectors-by-run.csv')
    ctrl=next((r for r in valid if 'adaptive-counterfactual' in r['run']),None)
    if ctrl:
        fig,ax=plt.subplots(figsize=(6,4))
        for r in valid:
            if r['seed']!=801 or (r['residual_budget'] is None and r['capacity_reported']==100):continue
            ds=next((d for d in byrun if d['run']==r['run'] and d['model']=='residual'),None)
            if ds:
                x=100*(r['s3']-ctrl['s3']);y=float(ds['alarm_fraction'])
                capacity_attack=r['capacity_reported']!=100
                ax.scatter([x],[y],s=50,color='#c65b32' if capacity_attack else '#146a86',marker='s' if capacity_attack else 'o')
                label=('capacity=150' if r['residual_budget'] is None else 'b='+str(r['residual_budget']))
                if capacity_attack and r['residual_budget'] is not None:label+='; cap=150'
                ax.annotate(label,(x,y),xytext=(5,7),textcoords='offset points',fontsize=8)
        ax.set(xlabel='Изменение доли SMF3 к парному контролю, п.п.',ylabel='Доля окон с тревогой residual',ylim=(-.05,1.12))
        ax.grid(alpha=.15);save(fig,'adaptive')
    (O/'data-snapshot.json').write_text(json.dumps({'runs':[r['run'] for r in valid],'pairs':len(pairs)},indent=2))
    print('Figures saved:',O)
if __name__=='__main__':main()
