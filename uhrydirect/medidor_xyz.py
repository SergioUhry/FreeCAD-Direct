# -*- coding: utf-8 -*-
"""Medidor XYZ Pro + Cotas de Conferência (Dockable)

Mede a menor distância 3D entre dois elementos selecionados e mostra
as componentes globais ΔX, ΔY e ΔZ.

Além da medição, permite criar cotas Draft no próprio 3D, com estilo
de conferência inspirado no TechDraw: setas maiores, texto legível e
linhas de extensão com traço final. Escolha: 3D, X, Y e Z.

Compatível com Faces, Arestas, Vértices, objetos inteiros, App::Part,
PartDesign::Body e App::Link. Para arestas circulares, usa o centro do
círculo como ponto de medição.
"""

import FreeCAD as App
import FreeCADGui as Gui
import Part
import math

try:
    from PySide2 import QtWidgets, QtCore
except ImportError:
    try:
        from PySide6 import QtWidgets, QtCore
    except ImportError:
        from PySide import QtWidgets, QtCore


DOCK_NAME = "MedidorXYZDock_Uhry"
COTAS_GROUP_NAME = "Uhry_Cotas_Medidor_XYZ"


def _is_circle_edge(shape):
    if getattr(shape, "ShapeType", "") != "Edge":
        return False
    try:
        curve = shape.Curve
        type_id = getattr(curve, "TypeId", "")
        return "Circle" in type_id or "ArcOfCircle" in type_id
    except Exception:
        return False


def _circle_center_vertex(edge):
    try:
        c = edge.Curve.Center
        return Part.Vertex(App.Vector(float(c.x), float(c.y), float(c.z)))
    except Exception:
        pass

    try:
        u = (float(edge.FirstParameter) + float(edge.LastParameter)) / 2.0
        c = edge.centerOfCurvatureAt(u)
        return Part.Vertex(App.Vector(float(c.x), float(c.y), float(c.z)))
    except Exception:
        raise ValueError("Não foi possível determinar o centro da aresta circular.")


def _shape_from_selection(sel_obj, sub_name=None):
    obj = sel_obj.Object

    if sub_name:
        shape = Part.getShape(
            obj,
            sub_name,
            needSubElement=True,
            transform=True,
        )
    else:
        shape = Part.getShape(
            obj,
            "",
            needSubElement=False,
            transform=True,
        )

    if shape is None or getattr(shape, "isNull", lambda: True)():
        raise ValueError("A seleção não possui geometria válida para medir.")

    if _is_circle_edge(shape):
        return _circle_center_vertex(shape)

    return shape


def _selected_shapes_global():
    selection = Gui.Selection.getSelectionEx("", 0)
    shapes = []

    for sel_obj in selection:
        names = list(sel_obj.SubElementNames or [])
        if names:
            for name in names:
                shapes.append(_shape_from_selection(sel_obj, name))
        else:
            shapes.append(_shape_from_selection(sel_obj, None))

    return shapes


def _closest_points(shape1, shape2):
    dist, vectors, _infos = shape1.distToShape(shape2)

    if not vectors:
        raise ValueError("O FreeCAD não retornou pontos para a menor distância.")

    pair = vectors[0]
    if not isinstance(pair, (tuple, list)) or len(pair) < 2:
        raise ValueError("Formato inesperado no resultado de distToShape().")

    p1, p2 = pair[0], pair[1]
    if not all(hasattr(p, a) for p in (p1, p2) for a in ("x", "y", "z")):
        raise ValueError("O FreeCAD retornou pontos de medição inválidos.")

    return float(dist), App.Vector(p1), App.Vector(p2)


def _midpoint(a, b):
    return App.Vector(
        (a.x + b.x) / 2.0,
        (a.y + b.y) / 2.0,
        (a.z + b.z) / 2.0,
    )


def _safe_unit(v):
    try:
        u = App.Vector(v)
        if u.Length > 1e-9:
            length = float(u.Length)
            return App.Vector(u.x / length, u.y / length, u.z / length)
    except Exception:
        pass
    return App.Vector(1, 0, 0)


def _perpendicular_for(v):
    """Escolhe um vetor perpendicular estável para afastar a cota 3D."""
    vv = App.Vector(v)
    if vv.Length < 1e-9:
        return App.Vector(0, 0, 1)

    # Escolhe um eixo pouco paralelo ao vetor medido.
    candidates = [App.Vector(0, 0, 1), App.Vector(0, 1, 0), App.Vector(1, 0, 0)]
    best = None
    best_len = -1.0
    for axis in candidates:
        c = vv.cross(axis)
        if c.Length > best_len:
            best = c
            best_len = c.Length
    return _safe_unit(best)


def _get_or_create_cotas_group(doc):
    group = doc.getObject(COTAS_GROUP_NAME)
    if group is None:
        group = doc.addObject("App::DocumentObjectGroup", COTAS_GROUP_NAME)
        group.Label = "Cotas — Medidor XYZ Pro"
    return group


def _set_if_exists(obj, prop, value):
    try:
        if hasattr(obj, prop):
            setattr(obj, prop, value)
            return True
    except Exception:
        pass
    return False


def _configure_dimension(dim, label, arrow_size, font_size, decimals=2):
    """Estilo de conferência inspirado nas cotas do TechDraw.

    A ideia aqui é privilegiar leitura no 3D: texto maior, setas visíveis,
    linhas de extensão com pequeno afastamento da peça e um traço que
    ultrapassa a linha de cota, como em desenho técnico 2D.
    """
    dim.Label = label
    vo = dim.ViewObject

    # Terminação clássica de desenho técnico.
    _set_if_exists(vo, "ArrowType", "Arrow")
    _set_if_exists(vo, "ArrowSize", arrow_size)
    _set_if_exists(vo, "FlipArrows", False)

    # ExtLines negativo cria um pequeno vão junto à peça.
    # ExtOvershoot faz o traço de chamada ultrapassar a linha de cota.
    gap = max(1.5, arrow_size * 0.28)
    witness_over = max(3.5, arrow_size * 0.85)
    _set_if_exists(vo, "ExtLines", -gap)
    _set_if_exists(vo, "ExtOvershoot", witness_over)

    # A linha de cota quase não ultrapassa as setas; quem ultrapassa é a
    # linha de extensão, reproduzindo melhor a aparência da folha 2D.
    _set_if_exists(vo, "DimOvershoot", max(0.5, arrow_size * 0.12))
    _set_if_exists(vo, "ShowLine", True)
    _set_if_exists(vo, "LineWidth", 3.0)

    # Alto contraste para uso como medida de conferência no modelo 3D.
    _set_if_exists(vo, "LineColor", (1.0, 0.15, 0.15))
    _set_if_exists(vo, "TextColor", (1.0, 0.15, 0.15))
    _set_if_exists(vo, "FontName", "DejaVu Sans:Bold")
    _set_if_exists(vo, "FontSize", font_size)
    _set_if_exists(vo, "Decimals", decimals)
    _set_if_exists(vo, "ShowUnit", True)
    _set_if_exists(vo, "TextSpacing", max(2.0, font_size * 0.30))

    # Mantém o texto sempre voltado para a tela.
    _set_if_exists(vo, "DisplayMode", "Screen")

    # Na vista 3D mostra somente o valor, como numa folha de desenho.
    # O nome ΔX/ΔY/ΔZ continua aparecendo na árvore do projeto.
    _set_if_exists(vo, "Override", "$dim")


def _create_draft_dimension(doc, group, start, end, dimline, label, scale):
    try:
        import Draft
    except Exception as exc:
        raise ValueError("Não foi possível carregar a bancada Draft: {}".format(exc))

    dim = Draft.make_dimension(App.Vector(start), App.Vector(end), App.Vector(dimline))
    if dim is None:
        raise ValueError("O FreeCAD não conseguiu criar a cota Draft.")

    # Escala adequada para cotas de conferência em diferentes níveis de zoom.
    arrow = max(4.0, min(14.0, scale * 0.026))
    font = max(7.0, min(20.0, scale * 0.042))
    _configure_dimension(dim, label, arrow, font, 2)

    try:
        group.addObject(dim)
    except Exception:
        pass

    return dim


class MedidorXYZDock(QtWidgets.QDockWidget):
    def __init__(self):
        super().__init__("Medidor XYZ Pro", Gui.getMainWindow())
        self.setObjectName(DOCK_NAME)
        self.setAllowedAreas(QtCore.Qt.AllDockWidgetAreas)
        self.setMinimumWidth(185)

        self.last_measurement = None

        container = QtWidgets.QWidget()
        container.setMinimumWidth(175)
        self.setWidget(container)

        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        self.info = QtWidgets.QLabel(
            "<small><b>CTRL:</b> selecione 2 elementos → Medir</small>"
        )
        self.info.setWordWrap(True)
        layout.addWidget(self.info)

        self.btn_medir = QtWidgets.QPushButton("Medir seleção")
        self.btn_medir.setStyleSheet(
            "font-weight:bold; padding:5px; background-color:#1976D2; "
            "color:white; border-radius:4px;"
        )
        self.btn_medir.clicked.connect(self.calcular)
        layout.addWidget(self.btn_medir)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(3)

        self.chk_dist, self.lbl_dist = self._measure_widget(True)
        self.chk_x, self.lbl_x = self._measure_widget(True)
        self.chk_y, self.lbl_y = self._measure_widget(True)
        self.chk_z, self.lbl_z = self._measure_widget(True)

        form.addRow("3D:", self._wrap_measure(self.chk_dist, self.lbl_dist))
        form.addRow("X:", self._wrap_measure(self.chk_x, self.lbl_x))
        form.addRow("Y:", self._wrap_measure(self.chk_y, self.lbl_y))
        form.addRow("Z:", self._wrap_measure(self.chk_z, self.lbl_z))
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        buttons.setSpacing(4)

        self.btn_cotas = QtWidgets.QPushButton("Criar cotas")
        self.btn_cotas.setToolTip(
            "Cria no 3D somente as cotas marcadas. Atalho: Ctrl+Alt+D"
        )
        self.btn_cotas.setShortcut("Ctrl+Alt+D")
        self.btn_cotas.clicked.connect(self.criar_cotas)
        buttons.addWidget(self.btn_cotas)

        self.btn_apagar = QtWidgets.QPushButton("Apagar")
        self.btn_apagar.setToolTip("Apaga todas as cotas criadas pelo Medidor XYZ Pro")
        self.btn_apagar.clicked.connect(self.apagar_cotas)
        buttons.addWidget(self.btn_apagar)

        layout.addLayout(buttons)

        self.cota_info = QtWidgets.QLabel(
            "<small>☑ Cotas de conferência no 3D.</small>"
        )
        self.cota_info.setWordWrap(True)
        layout.addWidget(self.cota_info)
        layout.addStretch()

    def _measure_widget(self, checked=False):
        chk = QtWidgets.QCheckBox()
        chk.setChecked(bool(checked))
        chk.setToolTip("Criar esta cota no modelo 3D")

        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setAlignment(QtCore.Qt.AlignRight)
        field.setMinimumWidth(86)
        field.setStyleSheet(
            "background-color:#f5f5f5; font-weight:bold; color:#222; font-size:10px;"
        )
        return chk, field

    @staticmethod
    def _wrap_measure(chk, field):
        w = QtWidgets.QWidget()
        h = QtWidgets.QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(3)
        h.addWidget(chk)
        h.addWidget(field, 1)
        return w

    def limpar(self):
        for field in (self.lbl_dist, self.lbl_x, self.lbl_y, self.lbl_z):
            field.clear()
        self.last_measurement = None

    @staticmethod
    def fmt(value):
        return (
            f"{float(value):,.3f} mm"
            .replace(",", "X")
            .replace(".", ",")
            .replace("X", ".")
        )

    def erro(self, texto):
        self.info.setText(
            "<span style='color:#D32F2F;'><small><b>Erro:</b> "
            + str(texto)
            + "</small></span>"
        )
        self.limpar()

    def calcular(self):
        try:
            shapes = _selected_shapes_global()

            if len(shapes) != 2:
                self.erro(
                    "Selecione exatamente 2 elementos. "
                    f"Foram encontrados {len(shapes)}."
                )
                return

            s1, s2 = shapes

            try:
                dist_native, p1, p2 = _closest_points(s1, s2)
            except Exception as exc:
                self.erro(
                    "O FreeCAD não conseguiu calcular a distância entre essas "
                    f"geometrias. Detalhe: {exc}"
                )
                return

            dx = abs(float(p2.x) - float(p1.x))
            dy = abs(float(p2.y) - float(p1.y))
            dz = abs(float(p2.z) - float(p1.z))
            dist_xyz = math.sqrt(dx * dx + dy * dy + dz * dz)

            if not math.isfinite(dist_xyz):
                dist_xyz = dist_native

            self.last_measurement = {
                "p1": App.Vector(p1),
                "p2": App.Vector(p2),
                "dist": float(dist_xyz),
                "dx": float(dx),
                "dy": float(dy),
                "dz": float(dz),
            }

            self.info.setText(
                "<span style='color:#388E3C;'><small><b>Medição concluída.</b></small></span>"
            )
            self.lbl_dist.setText(self.fmt(dist_xyz))
            self.lbl_x.setText(self.fmt(dx))
            self.lbl_y.setText(self.fmt(dy))
            self.lbl_z.setText(self.fmt(dz))

            App.Console.PrintMessage(
                "Medidor XYZ Pro | kernel={:.6f} mm | dXYZ={:.6f} mm | "
                "dX={:.6f} dY={:.6f} dZ={:.6f}\n".format(
                    dist_native, dist_xyz, dx, dy, dz
                )
            )

        except Exception as exc:
            App.Console.PrintError("Medidor XYZ Pro: {}\n".format(exc))
            self.erro(exc)

    def criar_cotas(self):
        if App.ActiveDocument is None:
            self.erro("Abra um documento antes de criar cotas.")
            return

        if not self.last_measurement:
            self.erro("Faça uma medição antes de criar as cotas.")
            return

        checks = [self.chk_dist, self.chk_x, self.chk_y, self.chk_z]
        if not any(c.isChecked() for c in checks):
            self.erro("Marque pelo menos uma das opções 3D, X, Y ou Z.")
            return

        doc = App.ActiveDocument
        m = self.last_measurement
        p1 = App.Vector(m["p1"])
        p2 = App.Vector(m["p2"])

        # Caminho ortogonal p1 -> X -> Y -> p2.
        # Assim as três cotas X/Y/Z formam uma cadeia geométrica que realmente
        # liga os dois pontos medidos.
        px = App.Vector(p2.x, p1.y, p1.z)
        pxy = App.Vector(p2.x, p2.y, p1.z)

        scale = max(30.0, m["dist"], m["dx"], m["dy"], m["dz"])
        offset = max(12.0, scale * 0.08)
        group = _get_or_create_cotas_group(doc)

        doc.openTransaction("Criar cotas Medidor XYZ")
        created = []
        try:
            # Distância alinhada direta entre os dois pontos.
            if self.chk_dist.isChecked() and m["dist"] > 1e-7:
                vec = p2.sub(p1)
                perp = _perpendicular_for(vec)
                line_pt = _midpoint(p1, p2) + (perp * (offset * 1.20))
                created.append(
                    _create_draft_dimension(doc, group, p1, p2, line_pt, "3D", scale)
                )

            # Cota X: primeiro trecho da cadeia ortogonal.
            if self.chk_x.isChecked() and m["dx"] > 1e-7:
                line_pt = _midpoint(p1, px) + App.Vector(0, 0, offset)
                created.append(
                    _create_draft_dimension(doc, group, p1, px, line_pt, "ΔX", scale)
                )

            # Cota Y: segundo trecho da cadeia ortogonal.
            if self.chk_y.isChecked() and m["dy"] > 1e-7:
                line_pt = _midpoint(px, pxy) + App.Vector(0, 0, offset * 1.35)
                created.append(
                    _create_draft_dimension(doc, group, px, pxy, line_pt, "ΔY", scale)
                )

            # Cota Z: último trecho da cadeia, chegando ao ponto 2 real.
            if self.chk_z.isChecked() and m["dz"] > 1e-7:
                line_pt = _midpoint(pxy, p2) + App.Vector(offset * 1.55, 0, 0)
                created.append(
                    _create_draft_dimension(doc, group, pxy, p2, line_pt, "ΔZ", scale)
                )

            if not created:
                raise ValueError(
                    "As cotas marcadas possuem valor zero; não há segmento para dimensionar."
                )

            doc.recompute()
            doc.commitTransaction()
            self.cota_info.setText(
                "<span style='color:#388E3C;'><small><b>{} cota(s) criada(s).</b> "
                "Elas ficam salvas no projeto e podem ser reposicionadas.</small></span>".format(
                    len(created)
                )
            )

        except Exception as exc:
            doc.abortTransaction()
            doc.recompute()
            App.Console.PrintError("Medidor XYZ Pro - cotas: {}\n".format(exc))
            self.cota_info.setText(
                "<span style='color:#D32F2F;'><small><b>Erro nas cotas:</b> {}</small></span>".format(
                    exc
                )
            )

    def apagar_cotas(self):
        doc = App.ActiveDocument
        if doc is None:
            return

        group = doc.getObject(COTAS_GROUP_NAME)
        if group is None:
            self.cota_info.setText("<small>Nenhuma cota do medidor para apagar.</small>")
            return

        objs = list(getattr(group, "Group", []) or [])
        doc.openTransaction("Apagar cotas Medidor XYZ")
        try:
            for obj in objs:
                try:
                    doc.removeObject(obj.Name)
                except Exception:
                    pass
            doc.recompute()
            doc.commitTransaction()
            self.cota_info.setText(
                "<small>{} cota(s) removida(s).</small>".format(len(objs))
            )
        except Exception as exc:
            doc.abortTransaction()
            doc.recompute()
            self.cota_info.setText(
                "<span style='color:#D32F2F;'><small>Erro ao apagar: {}</small></span>".format(
                    exc
                )
            )


def run():
    main_window = Gui.getMainWindow()

    for dock in main_window.findChildren(QtWidgets.QDockWidget):
        if dock.objectName() == DOCK_NAME:
            dock.show()
            dock.raise_()
            return

    dock = MedidorXYZDock()
    main_window.addDockWidget(QtCore.Qt.LeftDockWidgetArea, dock)
    dock.show()
    dock.raise_()

    # Largura inicial compacta; o painel continua redimensionável.
    try:
        main_window.resizeDocks([dock], [245], QtCore.Qt.Horizontal)
    except Exception:
        pass


try:
    run()
except Exception as exc:
    App.Console.PrintError("Medidor XYZ Pro: {}\n".format(exc))
