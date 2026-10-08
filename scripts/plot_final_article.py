"""Figures from the frozen article tables; equations rendered separately."""
import csv,json,re
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'article/figures/final20261007';OUT.mkdir(exist_ok=True)
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})

def save(fig,name):
    fig.savefig(OUT/(name+'.png'),dpi=240,bbox_inches='tight')
    fig.savefig(OUT/(name+'.svg'),bbox_inches='tight');plt.close(fig)

effects=list(csv.DictReader((ROOT/'results/article-final-20261007/effects.csv').open()))
fig,ax=plt.subplots(figsize=(7,3.2))
for policy,color,offset,marker in [('swrr','#156a8a',-.65,'o'),('random','#c36c2f',.65,'s')]:
    rows=sorted([r for r in effects if r['policy']==policy],key=lambda r:float(r['rho']))
    x=[float(r['rho'])*100+offset for r in rows];y=[float(r['delta_pp']) for r in rows]
    ax.errorbar(x,y,yerr=[[v-float(r['bootstrap_low']) for v,r in zip(y,rows)],
                         [float(r['bootstrap_high'])-v for v,r in zip(y,rows)]],fmt=marker+'-',color=color,capsize=4,label='SWRR' if policy=='swrr' else 'Случайный')
rows=sorted([r for r in effects if r['policy']=='swrr'],key=lambda r:float(r['rho']))
ax.plot([float(r['rho'])*100 for r in rows],[float(r['theory_delta_pp']) for r in rows],'k--',label='Модель',linewidth=1)
ax.set(xlabel='Общая операционная нагрузка, %',ylabel='Изменение доли SMF3, п.п.',xticks=[20,50,70],ylim=(0,11))
ax.grid(axis='y',alpha=.2);ax.legend(frameon=False,ncol=3,loc='upper left');save(fig,'effect')

rows=list(csv.DictReader((ROOT/'results/article-final-20261007/detector-comparison.csv').open()))
fig,ax=plt.subplots(figsize=(7,3.1));scenarios=['honest-burst','honest-delay','honest-combined']
for policy,color,offset in [('swrr','#156a8a',-.17),('random','#c36c2f',.17)]:
    values=[100*float(next(r for r in rows if r['stage']=='delay-burst-v1' and r['scenario']==s and r['policy']==policy)['mean_alarm_fraction']) for s in scenarios]
    bars=ax.bar([i+offset for i in range(3)],values,.32,color=color,label='SWRR' if policy=='swrr' else 'Случайный')
    ax.bar_label(bars,labels=[f'{v:.1f}%' for v in values],padding=3,fontsize=9)
ax.set(xticks=range(3),xticklabels=['Изменение нагрузки','Задержка','Оба фактора'],ylabel='Честные окна с тревогой, %',ylim=(0,118))
ax.legend(frameon=False,ncol=2,loc='upper left');ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True);save(fig,'delay_failure')

e=json.loads((ROOT/'results/timeaware-v1/evaluation.json').read_text())
fig,axes=plt.subplots(1,2,figsize=(7,3.2),sharey=True)
for ax,prefix,title in zip(axes,['honest','attack'],['Честные запуски','Атака 25%']):
    rows=[r for r in e['by_run'] if r['item']['stage'].startswith(prefix)]
    for j,(key,label,color) in enumerate([('baseline_alarms','Текущее\nсостояние','#c36c2f'),('alarms','История\n500 мс','#156a8a')]):
        vals=[100*r[key]/r['windows'] for r in rows]
        ax.scatter([j+(i-(len(vals)-1)/2)*.025 for i in range(len(vals))],vals,c=color,s=25,alpha=.7,zorder=3)
        ax.plot([j-.19,j+.19],[sum(vals)/len(vals)]*2,c='black',linewidth=1.2)
    ax.set(title=title,xticks=[0,1],xticklabels=['Текущее\nсостояние','История\n500 мс'],ylim=(-5,106),xlim=(-.5,1.5))
    ax.grid(axis='y',alpha=.2)
axes[0].set_ylabel('Окна с тревогой, %');fig.tight_layout();save(fig,'validation')

text=(ROOT/'article/ARTICLE_FINAL_20261007.md').read_text(encoding='utf-8')
index={}
for i,formula in enumerate(re.findall(r'^\$\$(.*?)\$\$$',text,re.M)):
    fig=plt.figure(figsize=(8,.55));fig.text(.5,.5,'$'+formula+'$',ha='center',va='center',fontsize=13)
    path=OUT/f'equation-{i}.png';fig.savefig(path,dpi=250,bbox_inches='tight',pad_inches=.05);plt.close(fig)
    index[formula]=str(path)
(OUT/'equations.json').write_text(json.dumps(index,indent=2))
print(OUT)
