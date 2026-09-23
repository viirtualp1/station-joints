"""Текстовый отчёт по схеме (cli.py, старый интерфейс app.py): стрелки, въезды,
самопроверка по методичке, светофоры, обоснование стыков, участки."""
from __future__ import annotations

from checks import audit_text
from joints import Station, _nm, _numkey
from signals import report_signals


def report(st: Station) -> str:
    g = st.g
    out = []
    out.append(f'Стрелок: {len(st.sw)}, путей станции: {len([l for l in st.lines if "name" in l])}, '
               f'съездов: {len(st.crossovers)}, стрелочных улиц: {len(st.ladders)}')
    out.append(f'Стыков: {len(st.joints)} (негабаритных: {sum(j.negab for j in st.joints)})')
    if abs(st.u - 10) < 1e-6:
        x0 = min(n.x for n in g.nodes.values())
        out.append('Миллиметровка: 1 клетка = 10 мм = междупутье; ординаты от левого края, мм:')
        sws = sorted(st.sw, key=lambda s: _numkey(_nm(st, s)))
        out.append('  ' + ', '.join(f'{_nm(st, s)}: {g.nodes[s].x - x0:.0f}' for s in sws))
        if st.geom_check is not None:
            bad, off = st.geom_check
            out.append('Проверка чертежа: диагонали 10 мм по высоте на 15 мм по горизонтали – '
                       + ('все' if not bad else f'НЕ все ({len(bad)}: {bad})')
                       + '; узлы на линиях сетки – ' + ('все' if not off else f'НЕ все ({len(off)})'))
    out.append('')
    out.append('Въезды (зона между стыками а и в):')
    for sig, ok, first in st.entry_check:
        out.append(f'  {sig}П: ' + (f'есть, до стрелки {first}' if ok else 'НЕТ – проверьте!'))
    out.append('')
    out += audit_text(st)
    out.append('')
    if st.signals:
        out.append(f'Светофоры ({len(st.signals)}):')
        out += report_signals(st)
        out.append('')
    out.append('Обоснование стыков:')
    out += st.log
    out.append('')
    out.append('Участки:')
    for s in sorted(st.sections, key=lambda s: (s['name'] in ('перегон', 'тупик', 'п/п'), s['name'])):
        if s['name'] == 'перегон':
            continue
        extra = ''
        if s['switches']:
            extra = f"  стрелок: {len(s['switches'])}"
            if len(s['switches']) > 3:
                extra += '  (!) > 3'
        out.append(f"  {s['name']}{extra}")
    return '\n'.join(out)
