"""Read-only ledger monitor; writes a separate Markdown progress file."""
import argparse
import datetime as dt
import json
import os
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'results/delay-burst-v1'
OUTPUT=ROOT/'article/EXPERIMENT_PROGRESS.md'
TZ=dt.timezone(dt.timedelta(hours=5))
LABELS={'honest-delay':'Без атаки, задержка 200 мс',
        'attack-delay':'Атака 25%, задержка 200 мс',
        'honest-burst':'Без атаки, изменение нагрузки',
        'attack-burst':'Атака 25%, изменение нагрузки',
        'honest-combined':'Без атаки, задержка и изменение нагрузки',
        'attack-combined':'Атака 25%, задержка и изменение нагрузки'}

def stamp(value):
    return dt.datetime.fromtimestamp(value,TZ).strftime('%d.%m.%Y %H:%M:%S')

def update():
    state=json.loads((STATE/'ledger.json').read_text())
    plan=json.loads((STATE/'plan.json').read_text())['items']
    now=time.time();age=max(0,now-state['updated_at'])
    passed=[item for item in plan if any(r['item']==item and r['eligible'] for r in state['results'])]
    active=state.get('in_flight',[])
    errors=[r for r in state['results'] if not r['eligible']]
    status={'running':'Выполняется','complete':'Завершён','paused':'Приостановлен',
            'failed':'Остановлен из-за ошибки','recovered':'Восстановлен, ожидает запуска'}.get(state['status'],state['status'])
    if state['status']=='running' and age>120:
        status='Нет свежих данных от контроллера — выполнение требует проверки'
    lines=['# Прогресс эксперимента', '',
           f'Файл обновлён: **{stamp(now)}** (Екатеринбург, UTC+5).',
           f'Последняя запись контроллера: **{stamp(state["updated_at"])}**, {round(age)} с назад.', '',
           f'**Состояние: {status}.**', '',
           f'Завершено и проверено: **{len(passed)} / {len(plan)} ({100*len(passed)/len(plan):.1f}%)**.',
           f'Не завершено: **{len(plan)-len(passed)}**. Активных по журналу: **{len(active)}**.',
           f'Неуспешных попыток в журнале: **{len(errors)}**.', '',
           '## Текущие запуски', '',
           '| Исполнитель | Сценарий | Алгоритм | Seed |',
           '|---|---|---|---|']
    for entry in active:
        item=entry['item']
        lines.append(f"| {entry['worker']} | {LABELS.get(item['stage'],item['stage'])} | {item['policy']} | {item['seed']} |")
    if not active:lines.append('| — | Нет активных запусков в журнале | — | — |')
    lines+=['','## Все запуски','','| № | Сценарий | Алгоритм | Seed | Состояние |','|---|---|---|---|---|']
    for index,item in enumerate(plan,1):
        if item in passed:mark='Готов, проверен'
        elif any(e['item']==item for e in active):mark='В работе' if age<=120 else 'Устаревшая запись «в работе»'
        elif any(e['item']==item for e in errors):mark='Ошибка; требуется разбор'
        else:mark='Ожидает'
        lines.append(f"| {index} | {LABELS.get(item['stage'],item['stage'])} | {item['policy']} | {item['seed']} | {mark} |")
    if state.get('error'):lines+=['','Последняя ошибка: `'+str(state['error']).replace('`','')+'`.']
    lines+=['','Обновление каждые 30 секунд, пока серия выполняется. После завершения, паузы или ошибки сохраняется итоговый снимок.',
            'Монитор читает журнал контроллера и не управляет экспериментом. При отсутствии обновлений более двух минут выводится предупреждение.',
            'Доля завершения считается по проверенным запускам, без оценки прогресса внутри текущих запусков.',
            'Если открытый просмотр не обновляет содержимое автоматически, откройте файл заново.','']
    temporary=OUTPUT.with_suffix('.tmp')
    temporary.write_text('\n'.join(lines),encoding='utf-8');temporary.replace(OUTPUT)
    return state['status']

def main():
    global STATE
    parser=argparse.ArgumentParser();parser.add_argument('--watch',action='store_true')
    parser.add_argument('--series',choices=['delay-burst-v1','timeaware-v1'],default='delay-burst-v1')
    args=parser.parse_args();STATE=ROOT/'results'/args.series
    if not args.watch:update();return
    marker=STATE/'progress-monitor.lock'
    with marker.open('x') as stream:stream.write(str(os.getpid()))
    try:
        while True:
            try:
                status=update()
                if status in ['complete','paused','failed']:break
            except (OSError,json.JSONDecodeError) as error:
                with (STATE/'progress-monitor-errors.log').open('a',encoding='utf-8') as log:
                    log.write(stamp(time.time())+' '+repr(error)+'\n')
            time.sleep(30)
    finally:marker.unlink(missing_ok=True)

if __name__=='__main__':main()
