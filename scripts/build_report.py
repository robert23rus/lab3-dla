"""Build the Russian lab report from saved, real experiment results.

Run from any directory: python scripts/build_report.py --summary docs/results/summary.json
The script never runs simulations or inserts substitute numerical results.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / 'report' / 'Отчет_ЛР3_DLA.docx'


def number(value: object, digits: int = 3) -> str:
    """Russian numeric formatting; absent/undefined estimates stay absent."""
    if value is None:
        return '—'
    if isinstance(value, bool):
        return 'да' if value else 'нет'
    if isinstance(value, int):
        return f'{value:,}'.replace(',', ' ')
    if isinstance(value, float):
        if not math.isfinite(value):
            return '—'
        return f'{value:.{digits}f}'.replace('.', ',')
    return str(value)


def mrun(text: str):
    element = OxmlElement('m:r')
    text_element = OxmlElement('m:t')
    text_element.set(qn('xml:space'), 'preserve')
    text_element.text = text
    element.append(text_element)
    return element


def append_math(parent, item):
    if isinstance(item, (list, tuple)):
        for piece in item:
            append_math(parent, piece)
    else:
        parent.append(mrun(item) if isinstance(item, str) else item)


def sub(base, index):
    element = OxmlElement('m:sSub')
    for tag, item in [('m:e', base), ('m:sub', index)]:
        part = OxmlElement(tag)
        append_math(part, item)
        element.append(part)
    return element


def sup(base, power):
    element = OxmlElement('m:sSup')
    for tag, item in [('m:e', base), ('m:sup', power)]:
        part = OxmlElement(tag)
        append_math(part, item)
        element.append(part)
    return element


def frac(numerator, denominator):
    element = OxmlElement('m:f')
    for tag, item in [('m:num', numerator), ('m:den', denominator)]:
        part = OxmlElement(tag)
        append_math(part, item)
        element.append(part)
    return element


def radical(item):
    element = OxmlElement('m:rad')
    properties = OxmlElement('m:radPr')
    hide = OxmlElement('m:degHide')
    hide.set(qn('m:val'), '1')
    properties.append(hide)
    element.append(properties)
    element.append(OxmlElement('m:deg'))
    expression = OxmlElement('m:e')
    append_math(expression, item)
    element.append(expression)
    return element


def summation(index, upper, expression):
    element = OxmlElement('m:nary')
    properties = OxmlElement('m:naryPr')
    character = OxmlElement('m:chr')
    character.set(qn('m:val'), '∑')
    properties.append(character)
    limits = OxmlElement('m:limLoc')
    limits.set(qn('m:val'), 'undOvr')
    properties.append(limits)
    element.append(properties)
    for tag, item in [('m:sub', index), ('m:sup', upper), ('m:e', expression)]:
        part = OxmlElement(tag)
        append_math(part, item)
        element.append(part)
    return element


class Report:
    def __init__(self, summary: dict, summary_path: Path):
        self.summary = summary
        self.summary_path = summary_path
        self.doc = Document()
        self.table_count = 0
        self.figure_count = 0
        self.headings: list[str] = []
        self.contents_start = None
        self._configure()

    def _configure(self):
        section = self.doc.sections[0]
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(3)
        section.right_margin = Cm(1.5)
        section.header_distance = Cm(1)
        section.footer_distance = Cm(1)
        styles = self.doc.styles
        normal = styles['Normal']
        normal.font.name = 'Times New Roman'
        normal.font.size = Pt(14)
        normal.paragraph_format.line_spacing = 1.5
        normal.paragraph_format.first_line_indent = Cm(1.25)
        normal.paragraph_format.space_after = Pt(0)
        for name in ['Heading 1', 'Heading 2']:
            style = styles[name]
            style.font.name = 'Times New Roman'
            style.font.size = Pt(14)
            style.font.bold = True
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.paragraph_format.first_line_indent = Cm(0)
            style.paragraph_format.space_before = Pt(0)
            style.paragraph_format.space_after = Pt(10)
            style.paragraph_format.keep_with_next = True
            style.paragraph_format.line_spacing = 1.2
        caption = styles['Caption']
        caption.font.name = 'Times New Roman'
        caption.font.size = Pt(12)
        caption.font.color.rgb = RGBColor(0, 0, 0)
        caption.paragraph_format.first_line_indent = Cm(0)
        caption.paragraph_format.line_spacing = 1.0
        caption.paragraph_format.space_after = Pt(8)
        for name in ['TOC 1', 'TOC Heading']:
            if name not in styles:
                styles.add_style(name, 1)
            style = styles[name]
            style.font.name = 'Times New Roman'
            style.font.size = Pt(14)
            style.font.color.rgb = RGBColor(0, 0, 0)
            style.paragraph_format.first_line_indent = Cm(0)
            style.paragraph_format.line_spacing = 1.2
            style.paragraph_format.space_after = Pt(5)
        footer = section.footer.paragraphs[0]
        footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
        footer.paragraph_format.first_line_indent = Cm(0)
        footer.paragraph_format.line_spacing = 1
        self._field(footer, 'PAGE', '1')
        settings = self.doc.settings.element
        update = OxmlElement('w:updateFields')
        update.set(qn('w:val'), 'true')
        settings.append(update)
        self.doc.core_properties.title = (
            'Лабораторная работа № 3. Диффузионно-ограниченная агрегация'
        )
        self.doc.core_properties.subject = 'Компьютерное моделирование; DLA; Монте-Карло'
        self.doc.core_properties.author = ''
        self.doc.core_properties.keywords = 'DLA, случайное блуждание, фрактал, Монте-Карло'

    @staticmethod
    def _field(paragraph, instruction: str, cached: str):
        run = paragraph.add_run()
        begin = OxmlElement('w:fldChar')
        begin.set(qn('w:fldCharType'), 'begin')
        run._r.append(begin)
        instruction_element = OxmlElement('w:instrText')
        instruction_element.set(qn('xml:space'), 'preserve')
        instruction_element.text = instruction
        run._r.append(instruction_element)
        separate = OxmlElement('w:fldChar')
        separate.set(qn('w:fldCharType'), 'separate')
        run._r.append(separate)
        paragraph.add_run(cached)
        end_run = paragraph.add_run()
        end = OxmlElement('w:fldChar')
        end.set(qn('w:fldCharType'), 'end')
        end_run._r.append(end)

    def contents(self):
        heading = self.doc.add_paragraph('СОДЕРЖАНИЕ', style='TOC Heading')
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.contents_start = self.doc.add_paragraph(style='TOC 1')

    def finalize_contents(self):
        # The visible cache is useful before a field update; Word replaces it
        # with hyperlinks and correct page numbers when updating the TOC.
        self._field(self.contents_start, 'TOC \\o "1-1" \\h \\z \\u', '\n'.join(self.headings))

    def page(self, title: str):
        heading = self.doc.add_heading(title, level=1)
        heading.paragraph_format.page_break_before = True
        self.headings.append(title)

    def body(self, text: str):
        p = self.doc.add_paragraph(text)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        return p

    def bullet(self, text: str):
        p = self.doc.add_paragraph('• ' + text)
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.left_indent = Cm(0.6)
        p.paragraph_format.line_spacing = 1.25
        p.paragraph_format.space_after = Pt(4)
        return p

    def equation(self, *items):
        p = self.doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1
        p.paragraph_format.space_before = Pt(7)
        p.paragraph_format.space_after = Pt(7)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        block = OxmlElement('m:oMathPara')
        math_element = OxmlElement('m:oMath')
        for item in items:
            append_math(math_element, item)
        block.append(math_element)
        p._p.append(block)

    def table(self, caption: str, headers: list[str], rows: list[list[object]], *, size=11):
        self.table_count += 1
        cp = self.doc.add_paragraph(f'Таблица {self.table_count} — {caption}', style='Caption')
        cp.alignment = WD_ALIGN_PARAGRAPH.LEFT
        cp.paragraph_format.keep_with_next = True
        table = self.doc.add_table(rows=1, cols=len(headers))
        table.style = 'Table Grid'
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        header_properties = table.rows[0]._tr.get_or_add_trPr()
        repeat = OxmlElement('w:tblHeader')
        header_properties.append(repeat)
        for cell, header in zip(table.rows[0].cells, headers):
            cell.text = header
            shading = OxmlElement('w:shd')
            shading.set(qn('w:fill'), 'E9EEF3')
            cell._tc.get_or_add_tcPr().append(shading)
        for row in rows:
            cells = table.add_row().cells
            for cell, value in zip(cells, row):
                cell.text = str(value)
        for row_index, row in enumerate(table.rows):
            properties = row._tr.get_or_add_trPr()
            properties.append(OxmlElement('w:cantSplit'))
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.first_line_indent = Cm(0)
                    p.paragraph_format.line_spacing = 1.05
                    p.paragraph_format.space_after = Pt(3)
                    p.paragraph_format.space_before = Pt(3)
                    for run in p.runs:
                        run.font.name = 'Times New Roman'
                        run.font.size = Pt(size)
                        if row_index == 0:
                            run.bold = True
        return table

    def figure(self, key: str, caption: str, *, height: float = 9.0):
        raw = self.summary['figures'].get(key)
        if not raw:
            raise ValueError(f'В summary.json отсутствует figures.{key}')
        path = Path(raw)
        if not path.is_absolute():
            path = ROOT / path
        if not path.is_file():
            raise FileNotFoundError(f'Не найден рисунок {key}: {path}')
        with Image.open(path) as source:
            if getattr(source, 'n_frames', 1) > 1:
                source.seek(source.n_frames - 1)
            image = source.convert('RGB')
            width_px, height_px = image.size
            buffer = BytesIO()
            image.save(buffer, format='PNG')
        buffer.seek(0)
        width_cm = min(16.1, height * width_px / height_px)
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(buffer, width=Cm(width_cm))
        self.figure_count += 1
        cp = self.doc.add_paragraph(f'Рисунок {self.figure_count} — {caption}', style='Caption')
        cp.alignment = WD_ALIGN_PARAGRAPH.CENTER

    def code(self, text: str):
        p = self.doc.add_paragraph()
        p.paragraph_format.first_line_indent = Cm(0)
        p.paragraph_format.line_spacing = 1
        p.paragraph_format.space_before = Pt(5)
        p.paragraph_format.space_after = Pt(5)
        run = p.add_run(text)
        run.font.name = 'Consolas'
        run.font.size = Pt(9)


def ensure_summary(summary: dict):
    if summary.get('schema_version') != 1:
        raise ValueError('Поддерживается summary.json со schema_version=1')
    for key in ['environment', 'parameters', 'validation', 'experiments', 'figures']:
        if key not in summary:
            raise ValueError(f'В summary.json отсутствует поле {key}')
    if not summary['experiments'].get('sticking'):
        raise ValueError('Серия экспериментов sticking пуста')
    if not summary['experiments'].get('boundary'):
        raise ValueError('Серия экспериментов boundary пуста')
    validation = summary['validation'].get('random_walk', {})
    for key in ['steps', 'trials', 'expected_msd', 'measured_msd', 'standard_error', 'z_score', 'passed']:
        if key not in validation:
            raise ValueError(f'В summary.json отсутствует validation.random_walk.{key}')
    for row in summary['experiments']['sticking']:
        for key in ['p', 'N', 'seeds', 'rg_mean', 'rg_std', 'dimension_mean', 'dimension_std', 'steps_mean', 'seconds_mean']:
            if key not in row:
                raise ValueError(f'В строке sticking отсутствует {key}')


def build_report(summary_path: Path, out: Path) -> Path:
    summary_path = summary_path.resolve()
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    ensure_summary(summary)
    sticking = sorted(summary['experiments']['sticking'], key=lambda row: row['p'], reverse=True)
    boundary = summary['experiments']['boundary']
    validation = summary['validation']['random_walk']
    parameters = summary['parameters']
    environment = summary['environment']
    baseline = next((row for row in sticking if row['p'] == 1), sticking[0])
    n = baseline['N']
    reps = baseline.get('replicates', len(baseline['seeds']))
    report = Report(summary, summary_path)
    report.contents()

    report.page('1 Цель и задачи работы')
    report.body('Тема лабораторной работы № 3 — «Моделирование роста фрактальных структур методом диффузионно-ограниченной агрегации (DLA)».')
    report.body('Цель работы — реализовать стохастическую модель необратимой агрегации, исследовать геометрию растущих кластеров и оценить влияние вероятности прилипания и численных границ на полученные характеристики.')
    for text in [
        'Реализовать случайное блуждание на квадратной решётке и рост кластера из одного зародыша.',
        'Проверить модель по точному закону среднего квадрата смещения свободных частиц и по структурным свойствам кластера.',
        'Исследовать изменение радиуса инерции при увеличении числа частиц и получить оценку эффективной фрактальной размерности.',
        'Сравнить режимы полного и неполного прилипания в серии независимых реализаций.',
        'Проверить чувствительность статистических характеристик к радиусам запуска и перезапуска.',
        'Подготовить воспроизводимые численные данные, графики и анимацию фактически рассчитанного роста.',
    ]:
        report.bullet(text)
    report.body('Работа опирается на случайные блуждания и диффузию из лекции № 8, а также на методы статистической обработки из лекции № 9. DLA является выбранным приложением этих методов; подробная постановка алгоритма дополнена первичными работами Виттена и Сандера.')

    report.page('2 Постановка задачи и допущения')
    report.body('Рассматривается двумерная квадратная решётка с единичным расстоянием между соседними узлами. В начальном состоянии занят только узел (0, 0). Частицы имеют одинаковую условную массу. В каждый момент моделируется одна свободная частица; остальные частицы образуют неподвижный кластер.')
    report.body('Свободная частица случайно перемещается по четырём направлениям. Контактом считается нахождение в свободном узле, имеющем хотя бы одного занятого соседа по стороне клетки. На каждом контактном такте частица закрепляется с вероятностью p. После закрепления её координаты сохраняются и запускается следующая частица.')
    report.body('При p = 1 используется классическое правило закрепления при первом контакте. При p < 1 после неудачной попытки прилипания блуждание продолжается. Перемещение в занятый узел отклоняется. Повторная попытка прилипания после такого отклонения входит в принятое правило контакта.')
    report.body('Основной расчёт заканчивается после достижения заданного числа N, включая зародыш. Частицы не отделяются, не перестраиваются и не взаимодействуют на расстоянии. Внешнее поле, направленный дрейф, течение среды и кристаллографические силы отсутствуют.')
    report.body('Число присоединившихся частиц задаёт стадию роста. Оно не является физическим временем. Измеренное время работы программы представляет вычислительные затраты и также не задаёт физическую скорость агрегации.')
    report.table('Обозначения', ['Величина', 'Значение'], [
        ['N', 'Число частиц кластера, включая зародыш'], ['p', 'Вероятность прилипания за контактный такт'],
        ['a = 1', 'Шаг решётки, единица длины'], ['seed', 'Начальное состояние генератора'],
        ['R_g', 'Радиус инерции относительно центра масс'], ['R_max', 'Максимальное расстояние от зародыша'],
    ], size=12)

    report.page('3 Случайное блуждание и диффузия')
    report.body('Обозначим положение частицы после k шагов через r_k. При отсутствии препятствий приращения независимы; каждое из четырёх направлений выбирается с вероятностью 1/4:')
    report.equation(sub('r', 'k+1'), ' = ', sub('r', 'k'), ' + ', sub('ξ', 'k'), ',   ', sub('ξ', 'k'), ' ∈ {(a,0), (−a,0), (0,a), (0,−a)}.')
    report.body('Среднее приращение равно нулю. При старте в начале координат среднее положение остаётся нулевым. Средние перекрёстные произведения независимых приращений исчезают, поэтому квадрат смещения имеет точное математическое ожидание:')
    report.equation('E[', sup(sub('r', 'k'), '2'), '] = k', sup('a', '2'), ',   E[', sup(sub('x', 'k'), '2'), '] = E[', sup(sub('y', 'k'), '2'), '] = ', frac([ 'k', sup('a', '2') ], '2'), '.')
    report.body('В диффузионном пределе распределение частиц описывается уравнением диффузии. Если каждому шагу сопоставить интервал Δt, коэффициент диффузии для данной двумерной схемы равен:')
    report.equation(frac('∂c', '∂t'), ' = D', sup('∇', '2'), 'c,   D = ', frac(sup('a', '2'), '4Δt'), ',   E[', sup('r', '2'), '(t)] = 4Dt.')
    report.body('При a = 1 проверяемая зависимость принимает вид E[r²(k)] = k. Сопоставляется среднее по ансамблю независимых частиц, а не квадрат смещения одной траектории. Отдельная частица может вернуться в начало координат или удалиться значительно дальше среднеквадратичного расстояния.')
    report.body('Свободное блуждание рассчитывается как отдельный статистический эталон связи случайных шагов и диффузии. Оно не является прямым тестом внутреннего генератора и цикла DLA. Корректность ядра дополнительно проверяется структурными тестами и согласованностью вычислительных backend.')

    report.page('4 Алгоритм агрегации и численные границы')
    report.body('После каждого присоединения обновляется максимальное расстояние занятого узла от зародыша. Окружности запуска и перезапуска увеличиваются вместе с кластером:')
    report.equation(sub('R', 'launch'), ' = λ max(', sub('R', 'max'), ', 5) + 5,   ', sub('R', 'kill'), ' = μ', sub('R', 'launch'), '.')
    for text in [
        'Выбрать угол равномерно на [0, 2π), вычислить точку окружности запуска и округлить её до узла решётки.',
        'Проверить наличие занятого соседа. При контакте выполнить случайную попытку закрепления с вероятностью p.',
        'Если закрепление не произошло, выбрать одно из четырёх направлений. Занятый целевой узел не допускается; в этом случае положение не меняется.',
        'При выходе за R_kill перезапустить эту частицу на окружности запуска. Число узлов кластера не увеличивать.',
        'При закреплении записать новый узел в массив координат и повторить процедуру до достижения N.',
    ]:
        report.bullet(text)
    report.body('Конечные окружности являются численным приближением к удалённому источнику частиц. Поэтому их влияние проверяется отдельно. Равномерность угла запуска не тождественна точной равномерности по решёточным узлам окружности.')
    report.body('Двумерный массив используется для быстрого поиска занятых узлов; свободная частица может находиться вне этого массива. Рост самого кластера до края хранения и превышение максимального числа шагов завершают расчёт ошибкой. Неполный или обрезанный кластер не считается завершённым результатом.')

    report.page('5 Геометрические характеристики и размерность')
    report.body('Положение центра масс и радиус инерции вычисляются непосредственно по координатам всех занятых узлов. Центр масс не обязан совпадать с неподвижным зародышем:')
    report.equation(sub('r', 'cm'), ' = ', frac('1', 'N'), summation('i=1', 'N', sub('r', 'i')), ',   ', sup(sub('R', 'g'), '2'), ' = ', frac('1', 'N'), summation('i=1', 'N', sup(['‖', sub('r', 'i'), ' − ', sub('r', 'cm'), '‖'], '2')), '.')
    report.body('В основном исследовании эффективная размерность определяется по массе внутри окружности, центрированной на центре масс конечного кластера:')
    report.equation('M(r) = ', summation('i=1', 'N', ['1{‖', sub('r', 'i'), ' − ', sub('r', 'cm'), '‖ ≤ r}']), ',   ln M(r) ≈ ', sub('D', 'eff'), ' ln r + b.')
    report.body('Используются 32 логарифмически расположенных радиуса от max(4; 0,12R) до 0,60R, где R — максимальное расстояние от конечного центра масс до частицы. В аппроксимацию включаются точки с M(r) ≥ 10. Требуется не менее восьми радиусов и пяти различных значений массы; иначе оценка не определяется.')
    report.body('На масштабе нескольких клеток результат зависит от решётки, а на масштабе всего объекта — от конечного размера и отдельных длинных ветвей. Поэтому выбранный диапазон аппроксимации сохраняется вместе с измерениями. В отчёте используется термин «эффективная фрактальная размерность»: это показатель конечного диапазона, а не доказательство предельной размерности бесконечного DLA.')
    report.body('Значения массы на вложенных окружностях коррелированы. Большой R² не устраняет эту корреляцию. Центр масс разреженного объекта может попасть в пустую область, что также влияет на оценку. Устойчивость показателя оценивается по независимо выращенным кластерам.')
    report.body('Разные вероятности прилипания могут менять конечномасштабную морфологию. Возможное различие оценок размерности в данной серии нельзя автоматически переносить на асимптотический предел.')

    report.page('6 Программная реализация')
    report.body('Программа написана на Python. Массив занятости обеспечивает постоянное время проверки соседства для каждого решёточного шага. Координаты хранятся целыми числами, поэтому совпадение узлов и четырёхсвязность не зависят от погрешностей арифметики с плавающей точкой.')
    report.table('Основные части проекта', ['Компонент', 'Назначение'], [
        ['dla/model.py', 'Генерация кластера, контроль пределов, сохранение и загрузка NPZ'],
        ['Численный анализ', 'История роста, радиус инерции, размерность, статистика серий'],
        ['dla/rendering.py', 'Отрисовка рассчитанных координат, PNG и GIF'],
        ['main.py и CLI', 'Запуск моделирования, проверки, экспериментов и повторной отрисовки'],
        ['tests/', 'Автоматическая проверка свойств модели и обработки данных'],
        ['scripts/', 'Создание демонстрационных материалов и отчёта'],
    ], size=12)
    report.body('При доступности Numba внутренний цикл компилируется. Дополнительное ускорение не меняет правило единичного случайного шага: искусственный дрейф и приближённые радиальные прыжки не используются. Первый вызов включает компиляцию; перед измеряемой серией выполняется прогрев.')
    report.body('NPZ содержит координаты в порядке присоединения и метаданные JSON; загрузка не требует pickle. Сохранённые координаты позволяют повторять анализ и отрисовку без нового роста.')
    report.body('Цвет обозначает порядок присоединения. Свечение добавляется при отрисовке; геометрия измеряется по исходным координатам.')

    report.page('7 План и параметры экспериментов')
    p_values = '; '.join(number(row['p'], 1) for row in sticking)
    report.body(f'Основная серия включает режимы p = {p_values}. В каждом режиме выращиваются кластеры с N = {number(n)} частицами. Для базового режима выполнено {number(reps)} независимых реализаций. Полные списки seed сохранены в сводном JSON и приведены ниже.')
    report.table('Параметры основной серии', ['p', 'N', 'Реализаций', 'seed'], [
        [number(row['p'], 1), number(row['N']), number(row.get('replicates', len(row['seeds']))), ', '.join(map(str, row['seeds']))]
        for row in sticking
    ], size=11)
    report.table('Варианты численных границ', ['λ запуска', 'μ перезапуска', 'N', 'Реализаций'], [
        [number(row['launch_factor'], 2), number(row['kill_factor'], 2), number(row['N']), number(row.get('replicates', len(row['seeds'])))]
        for row in boundary
    ], size=12)
    report.body('Сопоставление режимов проводится при одинаковом конечном числе частиц. Показатели каждой реализации вычисляются отдельно, после чего усредняются. По возможности одинаковые списки seed используются как средство организации серии; это не означает совпадение траекторий при разных p.')
    report.body(f'В проверке свободного блуждания используется {number(validation["trials"])} независимых траекторий длиной {number(validation["steps"])} шагов. Сравнение с точным математическим ожиданием выполняется с учётом стандартной ошибки среднего.')
    report.body('Фактические параметры, версии библиотек и пути к исходным данным связаны файлом summary.json. Для вычисления изображений README могут использоваться отдельные демонстрационные реализации; численные выводы берутся из статистической серии.')

    report.page('8 Проверка свободного блуждания')
    report.body('Для единичного шага теоретическое среднее квадрата смещения после k шагов равно k, а дисперсия r² равна k(k − 1). Выборочная стандартная ошибка сопоставляется с точной величиной. Предварительно задан критерий для конечного шага:')
    report.equation(sub('SE', 'exact'), ' = ', radical(frac('k(k−1)', 'm')), ',   z = ', frac(['⟨', sup('r', '2'), '⟩ − k'], [ 's(', sup('r', '2'), ')/', radical('m') ]), ',   |z| ≤ 4.')
    report.table('Результат проверки', ['Показатель', 'Значение'], [
        ['Количество траекторий', number(validation['trials'])], ['Шагов на траекторию', number(validation['steps'])],
        ['Точное E[r²]', number(validation['expected_msd'], 4)], ['Измеренное ⟨r²⟩', number(validation['measured_msd'], 4)],
        ['Выборочная стандартная ошибка', number(validation['standard_error'], 4)],
        ['Теоретическая стандартная ошибка', number(validation.get('expected_standard_error'), 4)],
        ['Нормированное отклонение z', number(validation['z_score'], 3)],
        ['Критерий программы выполнен', number(validation['passed'])],
    ], size=12)
    report.figure('validation', 'Средний квадрат смещения свободных частиц и теоретический закон', height=7.5)
    if validation['passed']:
        report.body('Результат удовлетворяет заданному в программе критерию. Наблюдаемое отклонение от точного значения сопоставляется со статистической ошибкой; нулевое отклонение от стохастического расчёта не требуется.')
    else:
        report.body('Заданный статистический критерий не выполнен. Перед интерпретацией серии необходимо проверить допуск, объём выборки и реализацию блуждания; этот исход не скрывается при генерации отчёта.')

    report.page('9 Базовый кластер DLA')
    report.body('На рисунке представлен рассчитанный кластер при полном прилипании. Частицы окрашены по порядку присоединения: цвет позволяет проследить развитие отдельных ветвей. Форма получена случайным блужданием и правилом контакта, без заранее заданного контура.')
    showcase = summary.get('showcase', {})
    showcase_config = showcase.get('config', {})
    if showcase_config:
        report.body(f'Для демонстрации используется отдельная реализация: N = {number(showcase_config["particles"])}, seed = {showcase_config["seed"]}, p = {number(showcase_config["sticking_probability"], 1)}. Она не подменяет статистическую серию из кластеров с N = {number(n)}.')
    report.figure('hero', 'Кластер DLA; цвет обозначает порядок присоединения', height=10.0)
    report.body('Внешние выступы перехватывают часть приходящих частиц, поэтому внутренние области оказываются экранированными. Этим объясняется ветвистая морфология вместо равномерного заполнения круга. Это качественное объяснение механизма, а количественное сравнение далее основано на радиусе инерции и статистике реализаций.')
    report.body('Зародыш входит в общее число частиц. Положение центра масс может отличаться от начала координат. Масштаб камеры фиксирован в пределах каждой анимации; визуальное увеличение структуры соответствует добавлению реально рассчитанных узлов.')

    report.page('10 Изменение размеров при росте')
    report.body('Поскольку координаты записываются в порядке присоединения, геометрические характеристики могут быть вычислены для последовательных стадий одного расчёта. Для каждой стадии пересчитывается центр масс и радиус инерции относительно него.')
    report.figure('growth', 'Изменение геометрических размеров кластера по мере роста', height=10.2)
    report.body(f'Для основной серии при p = {number(baseline["p"], 1)} и N = {number(baseline["N"])} средний итоговый радиус инерции равен {number(baseline["rg_mean"])} шага решётки, а выборочное стандартное отклонение между реализациями — {number(baseline["rg_std"])}.')
    report.body('Неравномерное изменение размера связано с тем, что новая частица может как удлинить удалённую ветвь, так и закрепиться ближе к центральной части объекта. Радиус инерции не обязан изменяться строго монотонно на каждом отдельном присоединении, поскольку одновременно смещается центр масс.')
    report.body('График одной реализации иллюстрирует механизм роста. Оценка изменчивости требует независимых запусков, а не большого числа точек одной траектории.')

    report.page('11 Оценка эффективной фрактальной размерности')
    report.body('Зависимость массы внутри окружности от её радиуса проверяется линейной аппроксимацией в логарифмических координатах. Окружности центрированы на центре масс конечного кластера. Метод и промежуточный диапазон аппроксимации определены в коде анализа и сохраняются в результатах.')
    report.figure('dimension', 'Масштабная зависимость и оценка эффективной размерности', height=10.0)
    report.table('Размерность по независимым реализациям', ['p', 'Средняя D_eff', 'Стандартное отклонение'], [
        [number(row['p'], 1), number(row['dimension_mean']), number(row['dimension_std'])] for row in sticking
    ], size=12)
    report.body('Приведённые значения относятся к конечным кластерам и выбранному диапазону размеров. Разброс оценивается между реализациями. Массы во вложенных окружностях не являются независимой статистической выборкой. Дополнительная чувствительность связана с возможным нахождением центра масс в пустой области.')

    report.page('12 Влияние вероятности прилипания')
    report.body('Режимы сравниваются при одинаковом числе закрепившихся частиц. При уменьшении p частица может многократно достигать контактных узлов и уходить от них до окончательного закрепления. Поэтому изменяется распределение мест роста, хотя правило свободного движения сохраняется.')
    report.figure('comparison', 'Примеры кластеров при разных вероятностях прилипания', height=7.0)
    report.table('Геометрия при разных p', ['p', 'Средний R_g', 'СКО R_g', 'Средняя D_eff'], [
        [number(row['p'], 1), number(row['rg_mean']), number(row['rg_std']), number(row['dimension_mean'])]
        for row in sticking
    ], size=12)
    lowest = min(sticking, key=lambda row: row['p'])
    report.body(f'В данной серии при p = {number(lowest["p"], 1)} получено R_g = {number(lowest["rg_mean"])} ± {number(lowest["rg_std"])}; при p = {number(baseline["p"], 1)} — {number(baseline["rg_mean"])} ± {number(baseline["rg_std"])}. Здесь после знака ± приведено стандартное отклонение отдельных реализаций, а не доверительный интервал среднего.')
    change_percent = (lowest['rg_mean'] / baseline['rg_mean'] - 1) * 100
    report.body(f'Относительное изменение среднего R_g между указанными режимами составляет {number(change_percent, 2)} %. При одинаковом числе частиц меньший R_g соответствует более компактному расположению массы относительно центра масс.')
    report.body('Наблюдаемые различия характеризуют исследованные конечные размеры. Они не доказывают различие предельных фрактальных размерностей при разных p.')

    report.page('13 Статистический разброс реализаций')
    report.body('Один seed определяет одну реализацию случайного роста. Для отделения эффекта параметров от изменчивости формы используются несколько seed. Статистические характеристики рассчитываются по итоговым значениям каждой реализации:')
    report.equation('X̄ = ', frac('1', 'm'), summation('j=1', 'm', sub('X', 'j')), ',   s = ', radical(frac(summation('j=1', 'm', sup([sub('X', 'j'), ' − X̄'], '2')), 'm−1')), ',   SE = ', frac('s', radical('m')), '.')
    report.figure('sticking', 'Сравнение режимов прилипания с учётом межреализационного разброса', height=10.0)
    report.body('Стандартное отклонение описывает типичный разброс результатов отдельных расчётов. Стандартная ошибка среднего уменьшается при увеличении числа независимых реализаций. Полосы стандартного отклонения не следует интерпретировать как доверительный интервал среднего.')
    report.body(f'Базовый режим содержит {number(reps)} реализаций. Этот объём достаточен для демонстрации изменчивости модели, но ограничивает точность статистических выводов. Для проверки слабых различий требуется увеличение числа повторов и размеров кластеров.')

    report.page('14 Чувствительность к численным границам')
    report.body('Конечные радиусы запуска и перезапуска изменяют способ подачи частиц к кластеру. Для проверки чувствительности выполнены варианты параметров λ и μ. Сравнение ведётся на одинаковом числе частиц и по независимым реализациям.')
    report.table('Результаты изменения радиусов', ['λ', 'μ', 'Средний R_g', 'СКО R_g', 'Средняя D_eff'], [
        [number(row['launch_factor'], 2), number(row['kill_factor'], 2), number(row['rg_mean']), number(row.get('rg_std')), number(row.get('dimension_mean'))]
        for row in boundary
    ], size=11)
    report.figure('boundary', 'Чувствительность геометрических характеристик к численным границам', height=8.2)
    base_boundary = next((row for row in boundary if abs(row['launch_factor'] - 1.6) < 1e-9 and abs(row['kill_factor'] - 3) < 1e-9), boundary[0])
    if base_boundary['rg_mean']:
        max_shift = max(abs(row['rg_mean'] / base_boundary['rg_mean'] - 1) for row in boundary) * 100
        report.body(f'Максимальное относительное отличие среднего R_g от варианта λ = {number(base_boundary["launch_factor"], 2)}, μ = {number(base_boundary["kill_factor"], 2)} составляет {number(max_shift, 2)} %. Это описательное сравнение средних, которое нужно сопоставлять с межреализационным разбросом.')
    report.body('Даже близкие результаты небольшой серии не доказывают строгую независимость от границ. Проверка ограничивает интерпретацию данной реализации; она не заменяет предельного перехода к бесконечно удалённому источнику.')

    report.page('15 Вычислительные затраты и воспроизводимость')
    report.body('Основная работа алгоритма связана с решёточными шагами свободных частиц. Число шагов случайно и зависит от текущей формы, p и численных границ. Поэтому универсальное время выполнения только по числу частиц не задаётся.')
    report.table('Измеренные затраты основной серии', ['p', 'Среднее шагов', 'Среднее время, с'], [
        [number(row['p'], 1), number(row['steps_mean'], 0), number(row['seconds_mean'], 3)] for row in sticking
    ], size=12)
    report.body('Здесь приведено сохранённое время вычисления модели. Генерация изображений и GIF выполняется после расчёта. Времена относятся к указанной среде и машине; их нельзя без измерений переносить на другой компьютер.')
    env_rows = [[str(key), str(value)] for key, value in environment.items() if isinstance(value, (str, int, float, bool))]
    env_rows.extend([[str(key), str(value)] for key, value in environment.get('packages', {}).items()])
    if env_rows:
        report.table('Среда расчёта', ['Параметр', 'Значение'], env_rows[:10], size=10)
    report.body('Для воспроизведения необходимо сохранить исходный код, версии библиотек, backend, параметры и списки seed. Готовые данные позволяют повторять геометрические измерения и построение рисунков без нового случайного роста.')
    report.body('Команды запуска основной серии и создания отчёта:')
    report.code(f'python main.py experiments --particles {n} --replicates {reps} --out results/study\npython scripts/build_readme_media.py --study results/study\npython scripts/build_report.py --summary docs/results/summary.json')

    report.page('16 Выводы и ограничения исследования')
    report.body('Реализована решёточная модель DLA с четырьмя равновероятными направлениями блуждания, необратимым закреплением и настраиваемой вероятностью прилипания. Координаты сохраняются в порядке роста, что обеспечивает повторное вычисление характеристик и построение анимации.')
    outcome = 'выполнен' if validation['passed'] else 'не выполнен'
    report.body(f'Критерий проверки свободного блуждания {outcome}: при {number(validation["steps"])} шагах измеренное среднее r² равно {number(validation["measured_msd"], 3)} при точном значении {number(validation["expected_msd"], 3)}; стандартная ошибка составляет {number(validation["standard_error"], 3)}.')
    report.body(f'Для базового режима p = {number(baseline["p"], 1)} и N = {number(n)} получен средний радиус инерции {number(baseline["rg_mean"])} с межреализационным стандартным отклонением {number(baseline["rg_std"])}.')
    if baseline['dimension_mean'] is not None:
        report.body(f'Средняя эффективная фрактальная размерность базового режима составляет {number(baseline["dimension_mean"])}; стандартное отклонение оценок между реализациями равно {number(baseline["dimension_std"])}. Это характеристика исследованного конечного диапазона масштабов.')
    report.body(f'При переходе от p = {number(baseline["p"], 1)} к p = {number(lowest["p"], 1)} относительное изменение среднего радиуса инерции составило {number(change_percent, 2)} %. Это характеризует изменение компактности конечных кластеров при одинаковом N.')
    dimension_rows = [row for row in sticking if row['dimension_mean'] is not None and row['dimension_std'] is not None]
    if len(dimension_rows) >= 2:
        span = max(row['dimension_mean'] for row in dimension_rows) - min(row['dimension_mean'] for row in dimension_rows)
        smallest_std = min(row['dimension_std'] for row in dimension_rows)
        if span < smallest_std:
            report.body('Размах средних оценок размерности между режимами меньше стандартного отклонения оценок внутри каждого режима. Данная серия не даёт основания уверенно утверждать изменение размерности с вероятностью прилипания.')
    report.body('Проверка вариантов численных границ выявляет чувствительность на фоне межреализационного разброса; полная независимость от границ не объявляется. Все различия относятся к выбранным правилам контакта, размерам объектов и числу повторов.')
    report.body('Основные ограничения — квадратная решётка, конечные окружности запуска/перезапуска, конечное число частиц и небольшая статистическая серия. Модель не описывает отрыв, перестройку, взаимодействие свободных частиц или перенос вещества течением. Последующие исследования могут включать увеличение размеров и числа повторов, а также сравнение с безрешёточной постановкой.')

    report.page('17 Использованные источники и материалы')
    sources = [
        'Федулов В. А. Компьютерное моделирование. Лекция № 8 «Стохастические компьютерные модели». Предоставленный учебный материал. С. 13–21.',
        'Федулов В. А. Компьютерное моделирование. Лекция № 9 «Методы Монте-Карло». Предоставленный учебный материал. С. 4–10.',
        'Witten T. A., Jr., Sander L. M. Diffusion-Limited Aggregation, a Kinetic Critical Phenomenon // Physical Review Letters. 1981. Vol. 47. P. 1400–1403. DOI: 10.1103/PhysRevLett.47.1400.',
        'Witten T. A., Sander L. M. Diffusion-limited aggregation // Physical Review B. 1983. Vol. 27. P. 5686–5697. DOI: 10.1103/PhysRevB.27.5686.',
    ]
    for i, source in enumerate(sources, 1):
        report.body(f'{i}. {source}')
    report.body('Электронные материалы проекта: README.md; docs/THEORY.md; docs/USER_GUIDE.md; сохранённая статистическая серия docs/results; исходные координаты NPZ; генератор настоящего отчёта scripts/build_report.py.')
    report.body('Первичные публикации:')
    report.code('https://doi.org/10.1103/PhysRevLett.47.1400\nhttps://doi.org/10.1103/PhysRevB.27.5686')
    report.body('Контрольная сумма SHA-256 использованного summary.json:')
    report.code(sha256(summary_path.read_bytes()).hexdigest())
    hashes = summary.get('source_sha256', summary.get('source_hashes', environment.get('source_hashes', {})))
    if isinstance(hashes, dict) and hashes:
        report.body('Контрольные суммы ключевых вычислительных модулей приведены ниже. Полный набор находится в source_sha256 файла summary.json:')
        selected_hashes = {name: value for name, value in hashes.items() if name in {'dla/model.py', 'dla/analysis.py', 'dla/experiments.py'}}
        for name, digest in (selected_hashes or dict(list(hashes.items())[:3])).items():
            report.code(f'{name}\n{digest}')
    report.finalize_contents()
    out = out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    report.doc.save(out)
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Создать отчёт DOCX по реальным результатам DLA')
    parser.add_argument('--summary', type=Path, default=ROOT / 'docs/results/summary.json')
    parser.add_argument('--out', type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    summary = args.summary if args.summary.is_absolute() else Path.cwd() / args.summary
    try:
        out = build_report(summary, args.out)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f'Ошибка подготовки отчёта: {error}\n')
    print(out)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
