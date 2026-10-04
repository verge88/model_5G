"""Report only completed, audited new pairs, preserving the historical pilot snapshot."""
import csv,json,statistics
from assess_precision import assess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/main-v2-execution'

def main():
    state=json.loads((STATE/'ledger.json').read_text())
    completed=[r for r in state['results'] if r['eligible_pair']]
    old=list(csv.DictReader((ROOT/'results/article-evaluation/paired-effects.csv').open()))
    pilot={(r['policy'],float(r['rho']),int(r['seed'])):dict(r,provenance='historical pilot audit') for r in old if r['comparable']=='True'}
    new=[]
    for pair in completed:
        meta=pair['item'];records=[r['audit'] for r in pair['records']]
        honest=next(r for r in records if r['alpha']==0);attack=next(r for r in records if r['alpha']==.5)
        row=dict(policy=meta['policy'],rho=meta['rho'],seed=meta['seed'],honest_s3=honest['s3'],attack_s3=attack['s3'],
                 delta_pp=100*(attack['s3']-honest['s3']),honest_run=honest['run'],attack_run=attack['run'],
                 series_id=meta['series_id'],warmup=meta['warmup'],cycles=meta['cycles'],comparable=True,provenance='new strict audit')
        if meta['series_id']=='pilot-closeout-v2':pilot[meta['policy'],meta['rho'],meta['seed']]=row
        elif meta['series_id']=='main-v2':new.append(row)
    def write(name,rows):
        if not rows:return
        fields=list(dict.fromkeys(k for row in rows for k in row))
        with (STATE/name).open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    write('pilot-completed-pairs.csv',list(pilot.values()));write('main-completed-pairs.csv',new)
    precision=assess(new)
    (STATE/'precision-assessment.json').write_text(json.dumps(precision,indent=2))
    lines=['# Завершение основной серии','',
           f"Состояние: {state['status']}. Причина: {state.get('stop_reason') or 'выполняется'}.",'',
           (f"Общий лимит времени снят; учтено {state['active_seconds']/3600:.3f} часа завершённых пар/попыток."
            if state.get('budget_mode')=='unlimited' else
            f"Дополнительный бюджет: 12 часов; учтено {state['active_seconds']/3600:.3f} часа завершённых пар/попыток."),
           'Время незавершённых пар прибавляется после их остановки; текущий счётчик не является остатком бюджета.',
           f"Пилот: {len(pilot)}/18 сопоставимых пар. Первый этап основной серии: {len(new)}/30 пар.",'',
           '| Политика | Нагрузка | Пар основной серии | Среднее ΔS, п.п. |',
           '|---|---:|---:|---:|']
    for policy in ['swrr','random']:
        for rho in [.2,.5,.7]:
            rows=[r for r in new if r['policy']==policy and r['rho']==rho]
            value=f"{statistics.mean(r['delta_pp'] for r in rows):.3f}" if rows else '—'
            lines.append(f'| {policy} | {rho:.0%} | {len(rows)} | {value} |')
    lines+=['','Исторические 16 пилотных пар сохраняют исходный аудит. Добор проверяется новым строгим аудитом.',
            'Подготовительные опыты не входят в основную оценку. Короткие и длинные серии не объединяются.',
            'Незавершённые и технически неудачные опыты сохранены в ledger.json.']
    (ROOT/'article/MAIN_V2_STATUS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(pilot_pairs=len(pilot),main_pairs=len(new),completed_attempts=len(state['results']))))

if __name__=='__main__':
    main()
    # Only reports invoked by the legacy coordinator may take ownership.
    if (STATE/'budget-control.json').exists():
        from unlimited_handoff import maybe_handoff
        maybe_handoff()
