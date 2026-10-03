"""Produce an evidence-bounded Russian manuscript and status from measured data."""
from pathlib import Path
import csv
import json
from datetime import datetime,timezone,timedelta
import statistics

R=Path(__file__).resolve().parents[1]
E=R/'results/article-evaluation'
def csvrows(name):
    path=E/name
    return list(csv.DictReader(path.open(encoding='utf-8'))) if path.exists() else []
def fmt(x,n=2):return '—' if x in ('',None) else f'{float(x):.{n}f}'
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','|'+'|'.join(['---']*len(headers))+'|']+
                     ['| '+' | '.join(map(str,row))+' |' for row in rows])
def main():
    a=json.loads((E/'audit.json').read_text());runs=[r for r in a['runs'] if r['eligible']]
    matrices=[]
    for path in sorted((R/'results').glob('article*/matrix.json')):
        matrices.append(json.loads(path.read_text()))
    ongoing=any(not m.get('finished') for m in matrices)
    used=max((m.get('active_seconds',0) for m in matrices),default=0)
    duration=f'{int(used//3600)} ч {int(used%3600//60)} мин {int(used%60)} с'
    total=sum(r['established'] for r in runs)
    measured=sum(r['n'] for r in runs if '-cal-' not in r['run'])
    effects=a['effects'];byrun=csvrows('detectors-by-run.csv')
    sections=['\n## Фактически полученные результаты\n',
        f'Срез данных: {datetime.now(timezone(timedelta(hours=5))).isoformat(timespec="seconds")}. '
        +('**Серия продолжается; таблицы промежуточные.**' if ongoing else '**Таблицы отражают сохранённые завершённые опыты.**'),
        f'Аудит прошли {len(runs)} запусков из {len(a["runs"])} технически завершённых. '
        f'В них подтверждено {total} успешных установлений PDU-сессий; '
        f'после исключения заполнения, разогрева и калибровки — {measured} измеряемых назначений. '
        'Три исходных B0-прогона (900 установлений) учитываются отдельно.',
        f'Консервативный учёт суммарного времени активных опытов, включая отладку и неудачные попытки: {duration} '
        'при лимите 4 часа. Для параллельных копий времена складываются. '
        'В первичную оценку вошли 16 из 18 запланированных сопоставимых пар: '
        'для SWRR при 20% одна пара пересекла изменение конфигурации, а для случайного выбора при 20% '
        'третий парный повтор не запускался из-за лимита. Переходные результаты не скрываются.',
        '### Исходный B0',
        table(['Порядок регистрации','SMF1','SMF2','SMF3'],[['1→2→3',300,0,0],['2→3→1',0,300,0],['3→1→2',0,0,300]]),
        'При перестановке порядка все назначения следовали за первым зарегистрированным SMF. '
        'Это подтверждает влияние порядка в проверенной конфигурации исходной версии и объясняет необходимость явной экспериментальной политики.',
        '### Эффект занижения нагрузки',
        table(['Политика','Нагрузка','Пар','ΔS, п.п.','95% bootstrap, п.п.','Теория, п.п.'],
              [[r['policy'],fmt(100*r['rho'],0)+'%',r['independent_pairs'],fmt(r['delta_pp']),
                fmt(r['bootstrap_low'])+' … '+fmt(r['bootstrap_high']),fmt(r['theory_delta_pp'])] for r in effects])
        if effects else 'Завершённых пригодных пар пока нет.',
        'Интервал не выводится при числе пар меньше трёх. Даже три пары дают только разведочную оценку; '
        'знак эффекта одного опыта не служит доказательством универсального преимущества атакующего. '
        f'В контрольных отсчётах SMF зафиксировано {sum(r.get("saturated_load_samples",0) for r in runs)} '
        f'случаев достижения операционной ёмкости из {sum(r.get("load_samples",0) for r in runs)} отсчётов. '
        'Они включают заполнение и разогрев; это индикатор нарушения ненасыщенного приближения, а не отдельная оценка временной доли перегрузки.',
        '### Детекторы на отложенных тестовых запусках',
        table(['Оценка','Порог','Честных окон','Окон основной атаки','FPR','Pd','Ложных окон/ч'],
              [[d['model'],fmt(d['calibrated_threshold']),d['benign_windows'],d['attack_windows'],
                fmt(d['empirical_fpr'],3),fmt(d['empirical_pd'],3),fmt(d['false_alarm_windows_per_hour'])] for d in a['detectors']]),
        'Окна в одной трассе зависимы. Значение FPR=0 означает отсутствие наблюдавшихся ложных окон в данном объёме, '
        'а не доказанный нулевой риск. Результаты при разных достигнутых FPR нельзя объявлять сравнением при одинаковом FPR=1%.',
        'Разделение по политике при общей SWRR-калибровке:',
        table(['Политика','Оценка','Честных окон','Окон атаки','FPR','Pd'],
              [[d['policy'],d['model'],d['benign_windows'],d['attack_windows'],fmt(d['empirical_fpr'],3),fmt(d['empirical_pd'],3)]
               for d in csvrows('detectors-by-policy.csv')]),
        '### Дополнительные кампании',
    ]
    controls=[r for r in runs if r['seed'] in (801,811)]
    base=next((r for r in controls if 'adaptive-counterfactual' in r['run']),None)
    rows=[]
    for r in controls:
        det=next((d for d in byrun if d['run']==r['run'] and d['model']=='residual'),None)
        quant=next((d for d in byrun if d['run']==r['run'] and d['model']=='residual_quantized'),None)
        delta=100*(r['s3']-base['s3']) if base and r['workload_hash']==base['workload_hash'] else None
        rows.append([r['run'].replace('article-20261001-',''),fmt(100*r['s3']),fmt(delta),
                     fmt(det['alarm_fraction'],3) if det else '—',fmt(quant['alarm_fraction'],3) if quant else '—'])
    sections+=[table(['Кампания','Доля SMF3, %','Δ к контролю, п.п.','Тревога residual','Тревога quantized'],rows)
               if rows else 'Завершённых дополнительных кампаний пока нет.',
               'Доля тревог в кампании с включением/выключением не равна Pd по истинным интервалам активного искажения. '
               'Бюджет b=0 задаёт нулевое искажение. Пропущенное Δ означает отсутствие подходящего парного контроля.',
               '### Распространение и свежесть отчётов']
    timing=[]
    for key,label in [('compute_to_nrf','Вычисление → NRF'),('age_at_selection','Возраст при выборе AMF')]:
        ps=[r['propagation'][key] for r in runs if r['propagation'][key]['n']]
        if ps:timing.append([label,sum(p['n'] for p in ps),fmt(statistics.median(p['median_ms'] for p in ps),3),
                            fmt(min(p['p95_ms'] for p in ps),3)+' … '+fmt(max(p['p95_ms'] for p in ps),3),
                            fmt(min(p['p99_ms'] for p in ps),3)+' … '+fmt(max(p['p99_ms'] for p in ps),3)])
    sections+=[table(['Величина','Событий','Медиана медиан, мс','Диапазон p95 прогонов, мс','Диапазон p99, мс'],timing),
               'Квантили отдельных прогонов не усредняются с выдачей за общий квантиль. Полные значения по каждому запуску сохранены в audit.json.',
               '### Проверяемый вывод',
               'Реализована и проверена цепочка динамического отчёта SMF → NRF → AMF и независимый учёт SCP. '
               'Величина и устойчивость смещения определяются только завершёнными парными опытами в таблице. '
               'Нельзя переносить вывод на штатную политику Open5GS, неизвестную ёмкость или неполное наблюдение SCP без новых опытов.',
               'На завершённых дополнительных опытах простой residual выявляет искажение нагрузки, но не проверяет относительную capacity: '
               'при её завышении до 150 нагрузка может сообщаться честно, а распределение назначений всё равно меняется. '
               'Проверка capacity относительно доверенной конфигурации закрывает именно этот вариант. '
               'Честная ёмкость 70 выявляет другую проблему: сравнение целочисленного отчёта с дробным наблюдением даёт ложные тревоги. '
               'Вариант quantized устраняет эту причину в наблюдавшемся контроле; это не доказательство отсутствия иных причин ложных тревог.',
               'Для малых бюджетов искажения эффект в отдельных коротких опытах может иметь отрицательный знак. '
               'Даже нулевое воздействие b=0 отличается от отдельного честного контрфактического прогона из-за конечного объёма и динамики выбора. '
               'Поэтому имеющиеся точки не устанавливают надёжную границу скрытности и полезности адаптивной атаки. '
               'Нужны более длинные серии с большим числом независимых повторов; ML на этих данных пока не обоснован.',
               '## Доступность материалов',
               'Полные патчи находятся в `patches/`, закреплённые версии — в `patches/manifest.json`, '
               'рецепт сборки — в `Dockerfile` и `compose.yaml`. Сырые журналы, конфигурации, PCAP, '
               'контрольные метрики, история операций UE и параметры опытов сохраняются в `runs/`. '
               'Таблицы анализа — в `results/article-evaluation/`; аналитический расчёт — отдельно в `results/theory/`. '
               'Проверка: `python scripts/test_analysis.py`; обновление таблиц: `python scripts/evaluate_article.py`; '
               'сборка этого текста: `python scripts/report_article.py`.']
    source=(R/'article/METHODS.md').read_text(encoding='utf-8')
    title,rest=source.split('\n',1)
    effect_text=('Средние парные эффекты в доступных сочетаниях политики и нагрузки составили от '
                 +fmt(min(e['delta_pp'] for e in effects))+' до '+fmt(max(e['delta_pp'] for e in effects))
                 +' процентного пункта. ') if effects else ''
    abstract=('\n\n## Аннотация\n\nПроверена причинная цепочка фальсификации нагрузки SMF в изолированном стенде Open5GS v2.8.0. '
              'Исходная конфигурация назначала все 900 проверенных сессий первому зарегистрированному SMF. '
              'После введения свежего discovery и взвешенного выбора выполнено '+str(sum(e['independent_pairs'] for e in effects))
              +' пригодных парных сравнений честного и заниженного отчёта. '+effect_text+
              'Независимое наблюдение SCP позволяет сравнивать отчёт с числом обслуживаемых контекстов без использования метрик SMF в признаках. '
              'Разделены время доставки отчёта в NRF, его возраст при выборе и ошибки детекторов на отдельных тестовых запусках. '
              'Вывод ограничен исследовательской политикой и пилотным объёмом; полное наблюдение и доверенная шкала ёмкости являются существенными предпосылками. '
              +('Серия ещё продолжается.\n' if ongoing else '\n'))
    output=title+abstract+rest+'\n\n'+'\n\n'.join(sections)+'\n'
    (R/'article/ARTICLE.md').write_text(output,encoding='utf-8')
    failed=[]
    for path in sorted((R/'runs').glob('article-*/manifest.json')):
        m=json.loads(path.read_text())
        if not m.get('complete'):failed.append([path.parent.name,m.get('error','Причина не сохранена старым runner; исключён')])
    primary_pairs=sum(r['independent_pairs'] for r in effects)
    status=['# Статус выполнения плана',
            'Серия продолжается.' if ongoing else 'Пилотная серия завершена в согласованном лимите. Расширенный протокол полностью не выполнен.',
            f'Суммарное время активных опытов: {duration}.',
            table(['Этап','Состояние'],[
                ['Закрепление стенда и исходников','Выполнено; патчи применяются к чистым исходникам'],
                ['B0 и порядок регистрации','Выполнено: 3 × 300 установлений'],
                ['Честный load и атакующее преобразование','Реализовано и проверено на реальных сессиях'],
                ['PATCH /load в NRF','Проверены изменение и шесть некорректных одиночных значений'],
                ['Fresh discovery и две политики','Реализовано; фактические повторы — в таблицах статьи'],
                ['Время распространения','Точная корреляция версий; p50/p95/p99 по запускам'],
                ['Независимый учёт SCP','Аудит каждого пригодного прогона'],
                ['Основная матрица','Завершено пар: '+str(primary_pairs)+' из 18 пилотных'],
                ['Пороговые детекторы и абляция источников','Выполнены для доступных пригодных трасс'],
                ['Адаптивные воздействия и честный контроль','Завершено кампаний: '+str(len(controls))+' из 11'],
                ['Расширенный протокол 10 seeds × 3000','Не выполнен в четырёхчасовом бюджете'],
                ['Потери наблюдения, рестарты и физическое замедление','Не выполнены; не подменяются расчётными данными'],
                ['Статья','Сформирован исследовательский текст с фактическими результатами и ограничениями']]),
            '## Остановки контроллеров',
            table(['Контроллер','Завершён','Причина','Прогонов'],[[i+1,m.get('complete'),m.get('stop_reason','работает' if not m.get('finished') else 'завершён'),len(m['runs'])] for i,m in enumerate(matrices)]),
            '## Исключённые технически незавершённые опыты',table(['Опыт','Причина'],failed) if failed else 'Нет.']
    (R/'article/STATUS.md').write_text('\n\n'.join(status)+'\n',encoding='utf-8')
    print(f'Article updated: {len(runs)} eligible runs, {primary_pairs} pairs')
if __name__=='__main__':main()
