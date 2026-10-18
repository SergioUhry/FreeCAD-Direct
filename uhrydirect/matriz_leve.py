# -*- coding: utf-8 -*-
"""Matriz Leve — FreeCAD 1.1+

Matriz ortogonal leve baseada em Draft Link Array e modo especial
"Face oposta" para criar uma Draft Link Array nativa com a 2ª peça invertida (esquerda/direita).

No modo Par oposto:
- há sempre 2 peças: a original + 1 espelhada;
- escolhe-se o eixo X/Y/Z em que a duplicata ficará;
- a segunda peça é um Part::Mirroring nativo e paramétrico;
- o plano de espelho fica exatamente no meio entre as duas posições;
- assim, a face extrema da origem fica frente a frente com a face extrema
  correspondente da peça oposta.

Sem proxies persistentes personalizados.
"""

import math
import traceback
import FreeCAD as App
import FreeCADGui as Gui
import Part
from draftmake.make_orthoarray import make_ortho_array

try:
    from PySide import QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets
    except ImportError:
        from PySide6 import QtCore, QtWidgets

AXES = 'XYZ'


def measure(spans, counts, values, gap_mode=False, reverse=None):
    reverse = reverse or [False] * 3
    steps = [(values[i] + spans[i] if gap_mode else values[i]) for i in range(3)]
    totals = [spans[i] + (counts[i] - 1) * steps[i] for i in range(3)]
    gaps = [steps[i] - spans[i] for i in range(3)]
    return [(-v if reverse[i] else v) for i, v in enumerate(steps)], totals, gaps


def fmt(value):
    return ('%.3f' % value).rstrip('0').rstrip('.').replace('.', ',')


def parent_part(obj):
    try:
        p = obj.getParentGeoFeatureGroup()
        return p if p and p.TypeId == 'App::Part' else None
    except Exception:
        return None


def body_for(obj):
    try:
        p = obj.getParentGeoFeatureGroup()
        if p and p.TypeId == 'PartDesign::Body':
            return p
    except Exception:
        pass
    return obj


def shape_for(obj):
    shape = Part.getShape(obj)
    if shape is None or shape.isNull():
        raise ValueError('A seleção não possui geometria utilizável.')
    return shape


def _length_value(value):
    try:
        return float(value.Value)
    except Exception:
        return float(value)


def spans_for(obj):
    """Dimensões usadas pela lógica da macro.

    Para uma Matriz Leve já existente, a fonte de verdade são os totais internos X/Y/Z.
    Isso evita usar o BoundBox visual da Link Array (que pode variar com ScaleList
    e espelhamento) e garante que matriz sobre matriz use exatamente o total
    calculado pela etapa anterior. Para peças comuns, usa o BoundBox real.
    """
    if obj is not None and getattr(obj, 'UhryMatrizLeve', False):
        vals = []
        ok = True
        for axis in AXES:
            name = 'UhryTotal' + axis
            if name not in getattr(obj, 'PropertiesList', []):
                ok = False
                break
            try:
                vals.append(abs(_length_value(getattr(obj, name))))
            except Exception:
                ok = False
                break
        if ok and all(math.isfinite(v) and v >= 0 for v in vals):
            return vals

    box = shape_for(obj).BoundBox
    spans = [box.XLength, box.YLength, box.ZLength]
    if not all(math.isfinite(v) and v >= 0 for v in spans):
        raise ValueError('Não foi possível calcular as dimensões da seleção.')
    return spans


def bbox_for(obj):
    return shape_for(obj).BoundBox


def property_value(obj, name, default):
    return getattr(obj, name, default) if obj else default


def add_prop(obj, typ, name, description, group='Matriz Direct'):
    if name not in obj.PropertiesList:
        obj.addProperty(typ, name, group, description)


def copy_view_style(source, target):
    """Copia apenas propriedades visuais simples quando disponíveis."""
    sv = getattr(source, 'ViewObject', None)
    tv = getattr(target, 'ViewObject', None)
    if sv is None or tv is None:
        return
    for prop in ('ShapeColor', 'LineColor', 'PointColor', 'Transparency', 'LineWidth', 'PointSize'):
        try:
            if hasattr(sv, prop) and hasattr(tv, prop):
                setattr(tv, prop, getattr(sv, prop))
        except Exception:
            pass


def ensure_opposite_properties(container):
    """Adiciona propriedades internas da Matriz Leve."""
    add_prop(container, 'App::PropertyBool', 'UhryMatrizLeve', 'Matriz criada pela ferramenta Direct')
    add_prop(container, 'App::PropertyBool', 'UhryParOposto', 'Par esquerda/direita com segunda peça espelhada')
    add_prop(container, 'App::PropertyBool', 'UhryNomeAutomatico', 'Atualizar nome ao aplicar pela macro')
    add_prop(container, 'App::PropertyBool', 'UhryModoVao', 'Entrada por vão externo')
    add_prop(container, 'App::PropertyString', 'UhryUltimoNome', 'Último nome atribuído pela macro')
    add_prop(container, 'App::PropertyString', 'UhryMedidasInfo', 'Referência das medidas')
    add_prop(container, 'App::PropertyString', 'UhryEixoOposto', 'Eixo do espelhamento X/Y/Z')
    add_prop(container, 'App::PropertyLink', 'Base', 'Peça original da matriz')
    add_prop(container, 'App::PropertyLink', 'UhryEspelho', 'Peça oposta espelhada')

    for axis in AXES:
        add_prop(container, 'App::PropertyInteger', 'Number' + axis, 'Quantidade no eixo ' + axis)
        add_prop(container, 'App::PropertyVectorDistance', 'Interval' + axis, 'Intervalo no eixo ' + axis)
        add_prop(container, 'App::PropertyLength', 'UhryTotal' + axis, 'Total externo ao aplicar pela macro')
        try:
            container.setEditorMode('UhryTotal' + axis, 1)
        except Exception:
            pass


def is_opposite_array(obj):
    return bool(obj and getattr(obj, 'UhryParOposto', False))



def _clear_expression(obj, prop):
    try:
        obj.setExpression(prop, None)
    except Exception:
        pass


def _set_expression(obj, prop, expr):
    """Define expressão e devolve True se o FreeCAD aceitou."""
    try:
        obj.setExpression(prop, expr)
        return True
    except Exception as exc:
        App.Console.PrintWarning('Matriz Leve: não foi possível vincular %s = %s (%s)\n' % (prop, expr, exc))
        return False


def ensure_dynamic_totals(array, source=None):
    """Mantém os totais internos coerentes com a regra:

        Total = tamanho da origem + intervalo lógico * (quantidade - 1)

    Em matriz normal, o intervalo lógico é o Interval nativo do Draft.
    Em Par oposto, usa UhryIntervaloX/Y/Z, pois o Interval nativo recebe
    uma compensação geométrica para o espelhamento.
    """
    if array is None:
        return

    try:
        own_spans = spans_for(source if source is not None else array)
    except Exception:
        own_spans = [0.0, 0.0, 0.0]

    is_opposite = bool(getattr(array, 'UhryParOposto', False))

    for i, axis in enumerate(AXES):
        span_name = 'UhrySpan' + axis
        total_name = 'UhryTotal' + axis
        logical_name = 'UhryIntervalo' + axis

        add_prop(array, 'App::PropertyLength', span_name,
                 'Tamanho externo da origem usado no cálculo')
        add_prop(array, 'App::PropertyLength', total_name,
                 'Total externo da matriz')

        linked = False
        if source is not None and source is not array and ('UhryTotal' + axis) in getattr(source, 'PropertiesList', []):
            linked = _set_expression(array, span_name, '%s.%s' % (source.Name, total_name))
        if not linked:
            _clear_expression(array, span_name)
            try:
                setattr(array, span_name, own_spans[i])
            except Exception:
                pass

        component = axis.lower()
        if is_opposite and logical_name in getattr(array, 'PropertiesList', []):
            expr = '%s + (Number%s - 1) * abs(%s)' % (span_name, axis, logical_name)
            try:
                logical_value = abs(_length_value(getattr(array, logical_name)))
            except Exception:
                logical_value = 0.0
        else:
            expr = '%s + (Number%s - 1) * abs(Interval%s.%s)' % (
                span_name, axis, axis, component)
            try:
                interval = getattr(array, 'Interval' + axis)
                logical_value = abs(getattr(interval, component))
            except Exception:
                logical_value = 0.0

        if not _set_expression(array, total_name, expr):
            try:
                count = int(getattr(array, 'Number' + axis))
                setattr(array, total_name, own_spans[i] + (count - 1) * logical_value)
            except Exception:
                pass

        try:
            array.setEditorMode(span_name, 1)
            array.setEditorMode(total_name, 1)
        except Exception:
            pass

def configure_follow_source(array, source, gaps, steps, counts):
    """Em matriz sobre matriz, preserva o VÃO entre conjuntos.

    O Interval nativo da matriz externa passa a ser uma expressão:
        total atual da matriz interna + vão desejado
    Portanto, se a matriz interna ficar maior/menor, a matriz externa se reposiciona.
    """
    if array is None or source is None or not getattr(source, 'UhryMatrizLeve', False):
        return

    add_prop(array, 'App::PropertyBool', 'UhrySegueBase',
             'Intervalos acompanham automaticamente o tamanho da matriz de origem')
    array.UhrySegueBase = True

    for i, axis in enumerate(AXES):
        gap_name = 'UhryVao' + axis
        add_prop(array, 'App::PropertyLength', gap_name,
                 'Vão preservado entre os limites externos dos conjuntos no eixo ' + axis)
        _clear_expression(array, gap_name)
        try:
            setattr(array, gap_name, gaps[i])
        except Exception:
            pass

        if counts[i] <= 1:
            continue

        total_name = 'UhryTotal' + axis
        if total_name not in getattr(source, 'PropertiesList', []):
            continue

        component = axis.lower()
        sign = '-' if steps[i] < 0 else ''
        expr = '%s(%s.%s + %s)' % (sign, source.Name, total_name, gap_name)
        _set_expression(array, 'Interval%s.%s' % (axis, component), expr)

    add_prop(array, 'App::PropertyString', 'UhryEncadeamentoInfo',
             'Como a matriz externa acompanha a matriz interna')
    array.UhryEncadeamentoInfo = (
        'Matriz encadeada: IntervalX/Y/Z repetidos usam o total atual da base + UhryVaoX/Y/Z. '
        'Ao alterar a matriz interna, esta matriz se reposiciona automaticamente.'
    )


class MatrixDialog(QtWidgets.QDialog):
    def __init__(self, source, array=None):
        super().__init__(Gui.getMainWindow())
        self.source, self.array = source, array
        self.doc = source.Document
        self.spans = spans_for(source)
        self.box = bbox_for(source)
        self._array_is_opposite = is_opposite_array(array)

        self.setWindowTitle('Matriz Leve — ' + ('Editar' if array else 'Criar'))
        self.resize(860, 500)
        layout = QtWidgets.QVBoxLayout(self)

        layout.addWidget(QtWidgets.QLabel('Peça original: ' + source.Label))
        p = parent_part(source)
        layout.addWidget(QtWidgets.QLabel(
            'Direções X/Y/Z: ' + ('eixos do conjunto ' + p.Label if p else 'eixos globais')
        ))

        # Mostra as dimensões máximas reais da seleção antes de preencher a matriz.
        # Para uma peça: limites externos da peça. Para uma matriz: limites externos
        # atuais do conjunto selecionado. Isso facilita calcular passo/vão desejado.
        size_box = QtWidgets.QGroupBox('Dimensões máximas da seleção')
        size_layout = QtWidgets.QHBoxLayout(size_box)
        self.max_size_labels = []
        for i, axis in enumerate(AXES):
            lab = QtWidgets.QLabel('<b>%s:</b> %s mm' % (axis, fmt(self.spans[i])))
            lab.setToolTip('Extensão máxima projetada da seleção no eixo %s.' % axis)
            self.max_size_labels.append(lab)
            size_layout.addWidget(lab)
        size_layout.addStretch(1)
        layout.addWidget(size_box)

        # Modo especial: par oposto / esquerda-direita.
        special_box = QtWidgets.QGroupBox('Duplicação especial')
        special_layout = QtWidgets.QHBoxLayout(special_box)
        self.opposite = QtWidgets.QCheckBox('2ª peça com face oposta (matriz nativa)')
        self.opposite.setToolTip(
            'Cria a peça original + uma segunda peça espelhada.\n'
            'Ideal para pares esquerda/direita, como catracas, suportes e ferragens.'
        )
        self.opposite_axis = QtWidgets.QComboBox()
        self.opposite_axis.addItems(['X', 'Y', 'Z'])
        self.opposite_axis.setToolTip('Eixo em que a segunda peça ficará em relação à original.')
        special_layout.addWidget(self.opposite, 1)
        special_layout.addWidget(QtWidgets.QLabel('Eixo da duplicata:'))
        special_layout.addWidget(self.opposite_axis)
        layout.addWidget(special_box)

        self.mode = QtWidgets.QComboBox()
        self.mode.addItems(['Informar intervalo entre posições', 'Informar vão entre limites externos', 'Informar total desejado'])
        self.mode.setCurrentIndex(int(property_value(array, 'UhryModoVao', False)))
        layout.addWidget(self.mode)

        grid = QtWidgets.QGridLayout()
        layout.addLayout(grid)
        headers = ['Eixo', 'Máx. seleção', 'Quantidade', 'Distância (mm)', 'Inverter', 'Intervalo', 'Vão', 'Total']
        self.input_header = QtWidgets.QLabel(headers[3])
        for col, label in enumerate(headers):
            widget = self.input_header if col == 3 else QtWidgets.QLabel(label)
            grid.addWidget(widget, 0, col)

        self.n, self.value, self.rev, self.results = [], [], [], []
        self._old_mode = self.mode.currentIndex()

        saved_axis = str(property_value(array, 'UhryEixoOposto', 'X') or 'X').upper()
        if saved_axis not in AXES:
            saved_axis = 'X'
        self.opposite_axis.setCurrentIndex(AXES.index(saved_axis))

        for i, axis in enumerate(AXES):
            grid.addWidget(QtWidgets.QLabel(axis), i + 1, 0)

            size_label = QtWidgets.QLabel(fmt(self.spans[i]) + ' mm')
            size_label.setToolTip('Dimensão máxima da seleção no eixo %s.' % axis)
            grid.addWidget(size_label, i + 1, 1)

            n = QtWidgets.QSpinBox()
            n.setRange(1, 10000)
            n.setValue(int(property_value(array, 'Number' + axis, 2 if i == 0 else 1)))

            value = QtWidgets.QDoubleSpinBox()
            value.setRange(0, 10000000)
            value.setDecimals(3)
            interval = property_value(array, 'Interval' + axis, None)
            step = getattr(interval, axis.lower()) if interval is not None else self.spans[i] + 25
            step_abs = abs(step)
            count0 = n.value()
            if self._old_mode == 1:
                initial_value = max(0.0, step_abs - self.spans[i])
            elif self._old_mode == 2:
                initial_value = self.spans[i] + max(0, count0 - 1) * step_abs
            else:
                initial_value = step_abs
            value.setValue(initial_value)

            rev = QtWidgets.QCheckBox()
            rev.setChecked(step < 0)

            self.n.append(n)
            self.value.append(value)
            self.rev.append(rev)

            for col, widget in enumerate([n, value, rev], 2):
                grid.addWidget(widget, i + 1, col)

            labels = [QtWidgets.QLabel() for _ in range(3)]
            self.results.append(labels)
            for col, widget in enumerate(labels, 5):
                grid.addWidget(widget, i + 1, col)

            n.valueChanged.connect(self.refresh)
            value.valueChanged.connect(self.refresh)
            rev.toggled.connect(self.refresh)

        self.auto = QtWidgets.QCheckBox('Nome automático: quantidade × nome da peça')
        automatic = property_value(array, 'UhryNomeAutomatico', True)
        if array and property_value(array, 'UhryUltimoNome', '') != array.Label:
            automatic = False
        self.auto.setChecked(automatic)
        layout.addWidget(self.auto)

        self.name = QtWidgets.QLineEdit(array.Label if array else source.Label + ' — Matriz')
        layout.addWidget(self.name)

        self.summary = QtWidgets.QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        self.opposite_info = QtWidgets.QLabel()
        self.opposite_info.setWordWrap(True)
        self.opposite_info.setStyleSheet('color:#555;')
        layout.addWidget(self.opposite_info)

        note = QtWidgets.QLabel(
            'Máx. seleção usa o total calculado quando a seleção já é uma Matriz Leve; para peça comum usa o tamanho real em X/Y/Z.\n'
            'REGRA: Total = tamanho da seleção + intervalo × (quantidade - 1).\n'
            'Exemplo: peça 92 mm, intervalo 1318 mm, quantidade 2 -> total 1410 mm.\n'
            'Modo total desejado: informe o total final; o intervalo é calculado por (total - tamanho) / (quantidade - 1).\n'
            'Face oposta altera somente a orientação visual da 2ª posição; não altera a fórmula de intervalo/total.\n'
            'Em matriz sobre matriz, o tamanho da seleção é o total da matriz interna. '
            'Se Face oposta estiver ativa, o conjunto inteiro é espelhado e o vão entre os conjuntos é preservado.'
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText('Atualizar matriz' if array else 'Criar matriz')
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.mode.currentIndexChanged.connect(self.change_mode)
        self.auto.toggled.connect(self.refresh)
        self.opposite.toggled.connect(self.special_changed)
        self.opposite_axis.currentIndexChanged.connect(self.special_changed)

        # Ao editar, não converte automaticamente um tipo de matriz no outro.
        if array:
            self.opposite.setChecked(self._array_is_opposite)
            self.opposite.setEnabled(False)
            if not self._array_is_opposite:
                self.opposite_axis.setEnabled(False)
        else:
            self.opposite.setChecked(False)

        self.special_changed()
        self.refresh()

    def _opposite_axis_index(self):
        return self.opposite_axis.currentIndex()

    def special_changed(self, *_):
        special = self.opposite.isChecked()
        axis_i = self._opposite_axis_index()
        self.opposite_axis.setEnabled(special and (self.array is None or self._array_is_opposite))

        if special:
            for i in range(3):
                self.n[i].blockSignals(True)
                self.n[i].setValue(2 if i == axis_i else 1)
                self.n[i].setEnabled(False)
                self.value[i].setEnabled(i == axis_i)
                self.rev[i].setEnabled(i == axis_i)
                self.n[i].blockSignals(False)
        else:
            for i in range(3):
                self.n[i].setEnabled(True)
                self.value[i].setEnabled(True)
                self.rev[i].setEnabled(True)

        self.refresh()

    def _step_from_input(self, span, count, value, mode_index):
        if count <= 1:
            return 0.0
        if mode_index == 0:  # intervalo nativo
            return max(0.0, value)
        if mode_index == 1:  # vão externo
            return max(0.0, value + span)
        # Total desejado -> calcula o intervalo.
        # Total = span + (count-1)*intervalo
        return max(0.0, (value - span) / float(count - 1))

    def _input_from_step(self, span, count, step_abs, mode_index):
        if mode_index == 0:
            return step_abs
        if mode_index == 1:
            return max(0.0, step_abs - span)
        return span + max(0, count - 1) * step_abs

    def data(self):
        counts = [n.value() for n in self.n]
        values = [v.value() for v in self.value]
        reverse = [v.isChecked() for v in self.rev]
        mode_index = self.mode.currentIndex()

        if self.opposite.isChecked():
            axis_i = self._opposite_axis_index()
            counts = [2 if i == axis_i else 1 for i in range(3)]

        steps, totals, gaps = [], [], []
        for i in range(3):
            count = counts[i]
            span = self.spans[i]
            step_abs = self._step_from_input(span, count, values[i], mode_index)
            step = -step_abs if reverse[i] else step_abs
            total = span + max(0, count - 1) * step_abs
            gap = step_abs - span if count > 1 else 0.0
            steps.append(step)
            totals.append(total)
            gaps.append(gap)

        return counts, steps, totals, gaps

    def change_mode(self, index):
        # Converte o valor exibido sem alterar a geometria pretendida.
        old_mode = self._old_mode
        for i, widget in enumerate(self.value):
            count = self.n[i].value()
            old_value = widget.value()
            step_abs = self._step_from_input(self.spans[i], count, old_value, old_mode)
            new_value = self._input_from_step(self.spans[i], count, step_abs, index)
            widget.blockSignals(True)
            widget.setValue(new_value)
            widget.blockSignals(False)
        self._old_mode = index
        self.refresh()

    def refresh(self, *_):
        mode_index = self.mode.currentIndex()
        if hasattr(self, 'input_header'):
            self.input_header.setText(['Intervalo (mm)', 'Vão (mm)', 'Total desejado (mm)'][mode_index])
        counts, steps, totals, gaps = self.data()
        for i in range(3):
            for label, val in zip(self.results[i], [abs(steps[i]), gaps[i], totals[i]]):
                label.setText(fmt(val) + ' mm')
            self.results[i][1].setText(fmt(gaps[i]) + ' mm' if counts[i] > 1 else '—')

        total = math.prod(counts)
        overlap = any(counts[i] > 1 and gaps[i] < 0 for i in range(3))
        self.summary.setText('%d peças (incluindo a primeira).%s' % (
            total,
            ' Há sobreposição dos limites externos.' if overlap else '',
        ))

        if self.opposite.isChecked():
            axis = AXES[self._opposite_axis_index()]
            direction = '-' + axis if steps[self._opposite_axis_index()] < 0 else '+' + axis
            self.opposite_info.setText(
                '<b>Par oposto:</b> a segunda peça será espelhada no eixo %s e posicionada no sentido %s. '
                'As duas faces extremas internas ficam frente a frente.' % (axis, direction)
            )
        else:
            self.opposite_info.setText('')

        self.name.setReadOnly(self.auto.isChecked())
        if self.auto.isChecked():
            if self.opposite.isChecked():
                self.name.setText('2 × %s — Par oposto' % self.source.Label)
            else:
                self.name.setText('%d × %s' % (total, self.source.Label))

    def _create_or_update_opposite(self, counts, steps, totals, gaps):
        """Cria Link Array nativa com a 2ª peça espelhada e total físico coerente.

        O valor digitado na janela continua sendo o intervalo lógico.
        No eixo espelhado, o Interval nativo do Draft recebe automaticamente
        a largura da peça somada ao intervalo lógico. Exemplo:

            peça 92 mm + intervalo 1318 mm = Interval nativo 1410 mm
            Total = 92 + 1318 = 1410 mm

        Assim a geometria real e o total calculado ficam iguais, sem depender de
        calibração posterior.
        """
        axis_i = self._opposite_axis_index()
        axis = AXES[axis_i]

        # Intervalos lógicos informados pelo usuário.
        logical_steps = list(steps)

        # Para a peça espelhada, o Draft precisa deslocar a 2ª instância também
        # pela dimensão da peça naquele eixo, senão ela cresce para trás e o
        # comprimento físico fica igual apenas ao intervalo.
        draft_steps = list(steps)
        sign = -1.0 if steps[axis_i] < 0 else 1.0
        draft_steps[axis_i] = sign * (abs(steps[axis_i]) + self.spans[axis_i])

        vectors = [
            App.Vector(draft_steps[0], 0, 0),
            App.Vector(0, draft_steps[1], 0),
            App.Vector(0, 0, draft_steps[2]),
        ]

        array = self.array if self._array_is_opposite else None
        if array is None:
            array = make_ortho_array(
                self.source,
                v_x=vectors[0], v_y=vectors[1], v_z=vectors[2],
                n_x=counts[0], n_y=counts[1], n_z=counts[2],
                use_link=True,
            )
            if array is None:
                raise RuntimeError('O Draft não conseguiu criar a matriz de vínculos.')
            p = parent_part(self.source)
            if p is not None:
                p.addObject(array)

        for a, count, vector in zip(AXES, counts, vectors):
            setattr(array, 'Number' + a, count)
            setattr(array, 'Interval' + a, vector)

        if 'Fuse' in array.PropertiesList:
            array.Fuse = False
        if 'ExpandArray' in array.PropertiesList:
            array.ExpandArray = False
        if 'ShowElement' in array.PropertiesList:
            array.ShowElement = False

        for typ, name, description in [
            ('App::PropertyBool', 'UhryMatrizLeve', 'Matriz criada pela ferramenta Direct'),
            ('App::PropertyBool', 'UhryParOposto', 'A segunda instância da Link Array está invertida'),
            ('App::PropertyBool', 'UhryNomeAutomatico', 'Atualizar nome ao aplicar pela macro'),
            ('App::PropertyBool', 'UhryModoVao', 'Entrada por vão externo'),
            ('App::PropertyString', 'UhryUltimoNome', 'Último nome atribuído pela macro'),
            ('App::PropertyString', 'UhryMedidasInfo', 'Referência das medidas'),
            ('App::PropertyString', 'UhryEixoOposto', 'Eixo da inversão X/Y/Z'),
        ]:
            add_prop(array, typ, name, description)

        array.UhryMatrizLeve = True
        array.UhryParOposto = True
        array.UhryNomeAutomatico = self.auto.isChecked()
        array.UhryModoVao = bool(self.mode.currentIndex())
        array.UhryEixoOposto = axis

        # Guarda os intervalos lógicos separados dos intervalos técnicos do Draft.
        for i, a in enumerate(AXES):
            pname = 'UhryIntervalo' + a
            add_prop(array, 'App::PropertyLength', pname,
                     'Intervalo lógico informado pelo usuário no eixo ' + a)
            _clear_expression(array, pname)
            setattr(array, pname, abs(float(logical_steps[i])))

        self.doc.recompute()
        if 'ScaleList' not in array.PropertiesList:
            raise RuntimeError('Esta Link Array não expõe ScaleList neste módulo do FreeCAD.')

        normal = App.Vector(1.0, 1.0, 1.0)
        mirrored = App.Vector(1.0, 1.0, 1.0)
        if axis_i == 0:
            mirrored.x = -1.0
        elif axis_i == 1:
            mirrored.y = -1.0
        else:
            mirrored.z = -1.0
        array.ScaleList = [normal, mirrored]

        array.Label = self.name.text().strip()
        array.UhryUltimoNome = array.Label
        array.UhryMedidasInfo = (
            'Par oposto: o intervalo interno guarda o valor lógico; Interval do Draft recebe a compensação da dimensão da peça. '
            'Regra: Total = tamanho da origem + intervalo lógico × (quantidade - 1).'
        )

        ensure_dynamic_totals(array, self.source)

        # Permite Face Oposta quando a origem já é outra Matriz Leve.
        # Nesse caso, além de espelhar o conjunto inteiro, preservamos o vão físico
        # entre os dois conjuntos quando a matriz interna mudar de tamanho.
        if getattr(self.source, 'UhryMatrizLeve', False):
            add_prop(
                array, 'App::PropertyBool', 'UhrySegueBase',
                'Intervalos acompanham automaticamente o tamanho da matriz de origem'
            )
            array.UhrySegueBase = True

            for i, a in enumerate(AXES):
                if counts[i] <= 1:
                    continue

                gap_name = 'UhryVao' + a
                logical_name = 'UhryIntervalo' + a
                source_total = 'UhryTotal' + a
                component = a.lower()

                add_prop(
                    array, 'App::PropertyLength', gap_name,
                    'Vão preservado entre os limites externos dos conjuntos no eixo ' + a
                )
                _clear_expression(array, gap_name)
                setattr(array, gap_name, gaps[i])

                # Intervalo lógico do par externo = tamanho atual da matriz interna + vão.
                # Assim UhryTotal = tamanho da base + intervalo lógico = 2*base + vão.
                if source_total in getattr(self.source, 'PropertiesList', []):
                    _set_expression(
                        array, logical_name,
                        '%s.%s + %s' % (self.source.Name, source_total, gap_name)
                    )

                    # O Draft precisa de uma compensação adicional do tamanho da origem
                    # porque a segunda instância está espelhada por ScaleList.
                    sign = '-' if steps[i] < 0 else ''
                    _set_expression(
                        array, 'Interval%s.%s' % (a, component),
                        '%s(%s.%s + %s)' % (
                            sign, self.source.Name, source_total, logical_name
                        )
                    )

            add_prop(
                array, 'App::PropertyString', 'UhryEncadeamentoInfo',
                'Como o par oposto externo acompanha a matriz interna'
            )
            array.UhryEncadeamentoInfo = (
                'Par oposto sobre Matriz Leve: o conjunto inteiro é espelhado. '
                'O vão externo é preservado automaticamente quando a matriz interna muda de tamanho.'
            )

            # Reaplica os totais depois de criar os vínculos dinâmicos.
            ensure_dynamic_totals(array, self.source)

        self.source.ViewObject.Visibility = False
        array.ViewObject.Visibility = True
        return array

    def apply(self):
        counts, steps, totals, gaps = self.data()

        if math.prod(counts) > 10000:
            QtWidgets.QMessageBox.warning(self, 'Quantidade', 'O limite é de 10.000 instâncias no total.')
            return

        if any(counts[i] > 1 and abs(steps[i]) < 1e-9 for i in range(3)):
            QtWidgets.QMessageBox.warning(self, 'Passo zero', 'Informe um passo maior que zero no eixo repetido.')
            return

        if not self.name.text().strip():
            QtWidgets.QMessageBox.warning(self, 'Nome', 'Informe um nome para a matriz.')
            return

        if self.opposite.isChecked():
            axis_i = self._opposite_axis_index()
            expected = [2 if i == axis_i else 1 for i in range(3)]
            if counts != expected:
                QtWidgets.QMessageBox.warning(
                    self,
                    'Par oposto',
                    'No modo Par oposto deve existir somente a peça original + 1 duplicata em um único eixo.'
                )
                return

        self.doc.openTransaction('Matriz Leve')
        try:
            if self.opposite.isChecked():
                array = self._create_or_update_opposite(counts, steps, totals, gaps)
            else:
                vectors = [
                    App.Vector(steps[0], 0, 0),
                    App.Vector(0, steps[1], 0),
                    App.Vector(0, 0, steps[2]),
                ]
                array = self.array

                if array is None:
                    array = make_ortho_array(
                        self.source,
                        v_x=vectors[0],
                        v_y=vectors[1],
                        v_z=vectors[2],
                        n_x=counts[0],
                        n_y=counts[1],
                        n_z=counts[2],
                        use_link=True,
                    )
                    if array is None:
                        raise RuntimeError('O Draft não conseguiu criar a matriz de vínculos.')
                    p = parent_part(self.source)
                    if p is not None:
                        p.addObject(array)

                for axis, count, vector in zip(AXES, counts, vectors):
                    setattr(array, 'Number' + axis, count)
                    setattr(array, 'Interval' + axis, vector)

                if 'Fuse' in array.PropertiesList:
                    array.Fuse = False
                if 'ExpandArray' in array.PropertiesList:
                    array.ExpandArray = False

                for typ, name, description in [
                    ('App::PropertyBool', 'UhryMatrizLeve', 'Matriz criada pela ferramenta Direct'),
                    ('App::PropertyBool', 'UhryNomeAutomatico', 'Atualizar nome ao aplicar pela macro'),
                    ('App::PropertyBool', 'UhryModoVao', 'Entrada por vão externo'),
                    ('App::PropertyString', 'UhryUltimoNome', 'Último nome atribuído pela macro'),
                    ('App::PropertyString', 'UhryMedidasInfo', 'Referência das medidas'),
                ]:
                    add_prop(array, typ, name, description)

                array.UhryMatrizLeve = True
                array.UhryNomeAutomatico = self.auto.isChecked()
                array.UhryModoVao = bool(self.mode.currentIndex())
                array.Label = self.name.text().strip()
                array.UhryUltimoNome = array.Label
                array.UhryMedidasInfo = (
                    'Regra: Total = tamanho da origem + intervalo × (quantidade - 1). '
                    'Reabrir após mudar a origem.'
                )

                # Totais dinâmicos acompanham Number/Interval.
                ensure_dynamic_totals(array, self.source)

                # Em matriz sobre matriz, preserva o vão entre conjuntos.
                # e faz a matriz externa acompanhar automaticamente o tamanho da base.
                configure_follow_source(array, self.source, gaps, steps, counts)

                self.source.ViewObject.Visibility = False
                array.ViewObject.Visibility = True

            self.doc.recompute()
            if 'Invalid' in array.State:
                raise RuntimeError('O FreeCAD marcou a matriz como inválida.')

            self.doc.commitTransaction()
            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(array)
            App.Console.PrintMessage('\nMatriz Leve: %s\n' % array.Label)
            self.accept()

        except Exception as exc:
            self.doc.abortTransaction()
            self.doc.recompute()
            App.Console.PrintError(traceback.format_exc())
            QtWidgets.QMessageBox.critical(self, 'Não foi possível aplicar', str(exc))


def run():
    if App.ActiveDocument is None:
        raise ValueError('Abra um documento e selecione uma peça, Body, Part ou uma Matriz Leve.')

    selected = Gui.Selection.getSelection()
    if len(selected) != 1:
        raise ValueError('Selecione uma peça, Body, Part ou uma Matriz Leve.')

    obj = selected[0]

    # Uma matriz selecionada pode ser usada como origem de uma nova matriz.
    if getattr(obj, 'UhryMatrizLeve', False):
        source = obj
        array = None
        App.Console.PrintMessage('\nMatriz Leve: criando matriz encadeada sobre: %s\n' % obj.Label)
    else:
        source = body_for(obj)
        array = None

    if source is None:
        raise ValueError('A origem da matriz não está disponível.')

    # Ao usar uma matriz como origem, atualiza primeiro os totais dela para
    # que qualquer alteração manual em Interval/Number propague à matriz seguinte.
    if getattr(source, 'UhryMatrizLeve', False):
        ensure_dynamic_totals(source, getattr(source, 'Base', None))
        App.ActiveDocument.recompute()

    dialog = MatrixDialog(source, array)

    # Uma Matriz Leve também pode ser usada como origem de outro conjunto.
    # par com face oposta. Nesse caso a segunda posição espelha o CONJUNTO
    # inteiro, e não apenas a peça original da matriz interna.
    if getattr(source, 'UhryMatrizLeve', False):
        try:
            dialog.opposite.setChecked(False)
            dialog.opposite.setEnabled(True)
            dialog.opposite_axis.setEnabled(False)
            dialog.opposite.setToolTip(
                'A origem já é uma Matriz Leve. Ative para criar uma segunda '
                'cópia do conjunto inteiro com face oposta.'
            )
            dialog.setWindowTitle(
                'Matriz Leve — Criar matriz sobre matriz'
            )
        except Exception:
            pass

    (dialog.exec if hasattr(dialog, 'exec') else dialog.exec_)()


try:
    run()
except Exception as exc:
    App.Console.PrintError(traceback.format_exc())
    QtWidgets.QMessageBox.critical(Gui.getMainWindow(), 'Matriz Leve', str(exc))
