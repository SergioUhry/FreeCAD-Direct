# -*- coding: utf-8 -*-

"""Linha Guia para FreeCAD 1.1+.

Cria referências paralelas a arestas ou guias existentes, oferece entrada
numérica, travas globais X/Y/Z, medição ao vivo e snap em arestas e
cruzamentos de guias. O preview não altera a geometria do documento.
"""



import traceback
import math

import FreeCAD as App

import FreeCADGui as Gui

import Part
from pivy import coin



try:

    from PySide import QtCore, QtGui, QtWidgets

except ImportError:

    try:

        from PySide2 import QtCore, QtGui, QtWidgets

    except ImportError:

        from PySide6 import QtCore, QtGui, QtWidgets



GROUP_NAME = "Direct_Guias_Referencia"

GROUP_LABEL = "Guias de Referência"

GUIDE_FLAG = "UhryGuiaReferencia"
DIRECT_GUIDE_FLAG = "DirectGuiaReferencia"



def get_axis(axis_name):

    if axis_name == "X": return App.Vector(1, 0, 0)

    if axis_name == "Y": return App.Vector(0, 1, 0)

    if axis_name == "Z": return App.Vector(0, 0, 1)

    return App.Vector(1, 0, 0)


def qt_key(name):
    """Compatibilidade PySide/PySide2/PySide6 para códigos de tecla."""
    try:
        return getattr(QtCore.Qt, name)
    except Exception:
        return getattr(QtCore.Qt.Key, name)


def keypress_event_type():
    try:
        return QtCore.QEvent.KeyPress
    except Exception:
        return QtCore.QEvent.Type.KeyPress



class DirectGuideMeasureEdit(QtWidgets.QLineEdit):
    """
    Campo numérico usado durante a medição.

    Mantém o foco enquanto a ferramenta está ativa para que números, sinais e
    separadores decimais não sejam enviados aos atalhos do viewport.
    """

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.setObjectName("DirectGuideMeasure")
        self.setPlaceholderText("ex.: 50")
        self.setFixedWidth(125)
        self.returnPressed.connect(self._confirm)

    def _confirm(self):
        self.controller.confirm_numeric()

    def keyPressEvent(self, event):
        key = event.key()

        if key == qt_key("Key_Escape"):
            self.controller._request_cancel()
            return

        if key == qt_key("Key_X"):
            self.controller._set_axis("X")
            self.controller.focus_measure(select_all=False)
            return

        if key == qt_key("Key_Y"):
            self.controller._set_axis("Y")
            self.controller.focus_measure(select_all=False)
            return

        if key == qt_key("Key_Z"):
            self.controller._set_axis("Z")
            self.controller.focus_measure(select_all=False)
            return

        # O campo mostra a medida ao vivo como no SketchUp. No primeiro
        # algarismo digitado, selecionamos esse valor de preview para que o
        # número do usuário o substitua imediatamente.
        txt = event.text() or ""
        if not self.controller.numeric_buffer.strip() and txt in "0123456789+-,.":
            self.selectAll()
            self.controller.numeric_direction_sign = (
                -1.0 if self.controller.current_offset < 0 else 1.0
            )

        super().keyPressEvent(event)



def add_prop(obj, typ, name, description, group="Guia"):

    if name not in obj.PropertiesList:

        obj.addProperty(typ, name, group, description)



def get_group(doc):

    group = doc.getObject(GROUP_NAME)

    if group is None:

        group = doc.addObject("App::DocumentObjectGroup", GROUP_NAME)

        group.Label = GROUP_LABEL

    return group



def all_guides(doc):

    return [

        obj for obj in doc.Objects

        if GUIDE_FLAG in getattr(obj, "PropertiesList", [])

        and bool(getattr(obj, GUIDE_FLAG, False))

    ]



def set_guide_style(obj):

    if not obj.ViewObject:

        return

    try:

        obj.ViewObject.DrawStyle = "Dashed"

    except Exception:

        pass

    try:

        obj.ViewObject.LineColor = (0.20, 0.75, 1.00)

    except Exception:

        pass

    try:

        obj.ViewObject.LineWidth = 2.0

    except Exception:

        pass



def unit(vec):

    length = vec.Length

    if length < 1e-9:

        raise ValueError("Direção com comprimento zero.")

    return App.Vector(vec.x / length, vec.y / length, vec.z / length)



def make_long_line(center, direction, length):

    safe_length = min(max(float(length), 1.0), 1000000.0)

    d = unit(direction)

    half = safe_length * 0.5

    p1 = center - (d * half)

    p2 = center + (d * half)

    return Part.makeLine(p1, p2)



def selection_ex_full_path():
    """
    Retorna a seleção SEM resolver App::Link/matrizes até o objeto-fonte.

    O segundo argumento = 0 preserva o caminho hierárquico completo do clique.
    Isso é essencial em matrizes: a 2ª/3ª instância pode usar a mesma EdgeN
    da peça-base, mas possui um caminho/transformação diferente.
    """
    try:
        return Gui.Selection.getSelectionEx("", 0)
    except Exception:
        # Compatibilidade defensiva caso a assinatura mude em outra instalação.
        return Gui.Selection.getSelectionEx()


def transformed_subelement(obj, subname):
    """Resolve um subelemento usando o caminho hierárquico completo."""
    try:
        # Uso por palavras-chave para evitar ambiguidade na assinatura de Part.getShape.
        # needSubElement=True garante que EdgeN/VertexN seja realmente extraído.
        # transform=True aplica também as transformações da instância da matriz/Link.
        return Part.getShape(
            obj,
            subname,
            needSubElement=True,
            transform=True,
        )
    except Exception:
        # Durante a criação da guia, o SubObject da seleção é a fonte mais fiel:
        # ele representa exatamente a ocorrência que o usuário clicou no 3D.
        for sel in selection_ex_full_path():
            if sel.Object == obj:
                for name, sub in zip(sel.SubElementNames, sel.SubObjects):
                    if name == subname:
                        try:
                            return sub.copy()
                        except Exception:
                            return sub
        raise ValueError(
            f"Falha ao resolver coordenadas globais de {obj.Label}.{subname}."
        )


def is_guide_object(obj):
    """Reconhece Linha Guia Direct, inclusive documentos legados."""
    if obj is None:
        return False
    props = set(getattr(obj, "PropertiesList", []))
    try:
        if DIRECT_GUIDE_FLAG in props and bool(getattr(obj, DIRECT_GUIDE_FLAG, False)):
            return True
    except Exception:
        pass
    try:
        if GUIDE_FLAG in props and bool(getattr(obj, GUIDE_FLAG, False)):
            return True
    except Exception:
        pass
    return str(getattr(obj, "Name", "")).startswith("UhryGuia")


def global_object_shape(obj):
    """Retorna a Shape visível do objeto em coordenadas globais.

    É especialmente importante para Linhas Guia que já foram reposicionadas:
    a Shape local continua na posição em que nasceu, enquanto o Placement do
    objeto passa a carregar o deslocamento atual.
    """
    try:
        shape = Part.getShape(
            obj,
            "",
            needSubElement=False,
            transform=True,
        )
        if shape is not None and not shape.isNull():
            return shape
    except Exception:
        pass

    if hasattr(obj, "Shape") and obj.Shape is not None and not obj.Shape.isNull():
        shape = obj.Shape.copy()
        try:
            pl_global = obj.getGlobalPlacement()
            pl_local = obj.Placement
            pl_parents = pl_global * pl_local.inverse()
            shape.Placement = pl_parents * shape.Placement
        except Exception:
            try:
                shape.Placement = obj.Placement * shape.Placement
            except Exception:
                pass
        return shape

    raise ValueError(f"{obj.Label}: objeto sem geometria válida.")


def selected_items():
    items = []

    # IMPORTANTE: resolve=0 mantém o objeto raiz da seleção e o caminho completo
    # até a instância clicada. Sem isso, o FreeCAD pode resolver uma matriz/App::Link
    # para Pad/Body da peça-base e todas as cópias acabam parecendo a primeira.
    for sel in selection_ex_full_path():
        obj = sel.Object

        if sel.SubElementNames:
            subobjects = list(sel.SubObjects)

            for index, subname in enumerate(sel.SubElementNames):
                shape = None

                # Linhas Guia podem ter sido movidas depois da criação. Nesse caso
                # obj.Shape/SubObjects ainda podem representar a geometria local
                # antiga. Para guia, a fonte da verdade é sempre a geometria global
                # resolvida pelo FreeCAD com transform=True.
                if is_guide_object(obj):
                    try:
                        shape = transformed_subelement(obj, subname)
                    except Exception:
                        shape = None

                # Para peças normais/matrizes preservamos o SubObject do clique,
                # pois ele identifica corretamente a instância visual selecionada.
                if shape is None and index < len(subobjects):
                    candidate = subobjects[index]
                    if getattr(candidate, "ShapeType", ""):
                        try:
                            shape = candidate.copy()
                        except Exception:
                            shape = candidate

                if shape is None:
                    shape = transformed_subelement(obj, subname)

                items.append((obj, subname, shape))

        else:
            # Seleção do objeto inteiro na Árvore do Modelo. Nunca usamos
            # obj.Shape cru aqui: uma Linha Guia reposicionada teria a forma
            # local antiga e o novo Placement seria ignorado.
            try:
                resolved = global_object_shape(obj)
            except Exception:
                resolved = None

            if resolved is not None and not resolved.isNull():
                if resolved.ShapeType == 'Edge':
                    items.append((obj, "Edge1", resolved))
                elif resolved.Edges:
                    items.append((obj, "Edge1", resolved.Edges[0]))

    return items



def straight_edge_data(obj, subname, shape=None):

    # Para Linhas Guia, sempre releia a aresta em coordenadas globais atuais.
    # Isso evita reutilizar a Shape local anterior quando a própria guia foi
    # movida para outro plano pela ferramenta Posicionar Peça.
    if is_guide_object(obj):
        try:
            shape = transformed_subelement(obj, subname)
        except Exception:
            if shape is None:
                resolved = global_object_shape(obj)
                shape = resolved if resolved.ShapeType == "Edge" else resolved.Edges[0]
    else:
        shape = shape if shape is not None else transformed_subelement(obj, subname)

    if getattr(shape, "ShapeType", "") != "Edge":

        raise ValueError("O elemento não é uma aresta.")

    verts = shape.Vertexes

    if len(verts) < 2:

        raise ValueError("A aresta não possui dois extremos.")

    p1 = App.Vector(verts[0].Point)

    p2 = App.Vector(verts[-1].Point)

    direction = unit(p2 - p1)

    midpoint = (p1 + p2) * 0.5

    return p1, p2, midpoint, direction



def vertex_point(obj, subname, shape=None):

    shape = shape if shape is not None else transformed_subelement(obj, subname)

    if getattr(shape, "ShapeType", "") != "Vertex":

        raise ValueError("Selecione um vértice/ponto.")

    return App.Vector(shape.Point)



def add_common_properties(obj, mode, length):

    add_prop(obj, "App::PropertyBool", GUIDE_FLAG, "Compatibilidade com versões anteriores.")
    add_prop(obj, "App::PropertyBool", DIRECT_GUIDE_FLAG, "Identifica Linha Guia Direct.")

    add_prop(obj, "App::PropertyString", "UhryTipoGuia", "Modo usado.")

    add_prop(obj, "App::PropertyLength", "UhryComprimento", "Comprimento da linha.")

    add_prop(obj, "App::PropertyString", "UhryInfo", "Descrição.")

    obj.UhryGuiaReferencia = True
    obj.DirectGuiaReferencia = True

    obj.UhryTipoGuia = mode

    obj.UhryComprimento = min(max(float(length), 1.0), 1000000.0)

    try: obj.setEditorMode(GUIDE_FLAG, 1)

    except: pass



def new_guide(doc, label, shape, mode, length):

    obj = doc.addObject("Part::Feature", "UhryGuia")

    obj.Label = label

    obj.Shape = shape

    add_common_properties(obj, mode, length)

    set_guide_style(obj)

    get_group(doc).addObject(obj)

    return obj



def set_ref(obj, propname, source_obj, subname, description):
    """
    Guarda a referência sem depender de App::PropertyLinkSub para caminhos
    hierárquicos de matrizes/App::Link.

    Em uma seleção como Array001 -> 2.Pad010.Edge2, o objeto-raiz e o caminho
    são preservados separadamente. Isso evita que o FreeCAD reduza a referência
    à peça-base da matriz e também evita avisos de escopo em novos guias.
    """
    obj_prop = propname + "Objeto"
    sub_prop = propname + "Subelemento"
    info_prop = propname + "Info"

    add_prop(obj, "App::PropertyLink", obj_prop, description + " — objeto raiz")
    add_prop(obj, "App::PropertyString", sub_prop, description + " — caminho hierárquico")
    add_prop(obj, "App::PropertyString", info_prop, description + " — leitura")

    setattr(obj, obj_prop, source_obj)
    setattr(obj, sub_prop, str(subname))
    setattr(obj, info_prop, f"{source_obj.Label} :: {subname}")


def read_guide_ref(obj, propname):
    """Lê referências atuais e mantém compatibilidade com guias antigas."""
    obj_prop = propname + "Objeto"
    sub_prop = propname + "Subelemento"

    if obj_prop in getattr(obj, "PropertiesList", []) and sub_prop in getattr(obj, "PropertiesList", []):
        src = getattr(obj, obj_prop, None)
        sub = str(getattr(obj, sub_prop, "") or "")
        if src and sub:
            return src, sub

    # Compatibilidade com guias que usam PropertyLinkSub.
    return read_linksub(getattr(obj, propname, None))


def read_linksub(value):

    if not value: return None, None

    try:

        src = value[0]

        subs = value[1]

    except: return None, None

    subname = subs if isinstance(subs, str) else (subs[0] if subs else None)

    return src, subname



def create_parallel_guide(doc, axis, offset, length):

    items = selected_items()

    if not items: raise ValueError("Nenhuma aresta selecionada.")

    src, subname, shape = items[0]

    _, _, mid, direction = straight_edge_data(src, subname, shape)

    shift_axis = get_axis(axis)

    if abs(direction.dot(shift_axis)) > 0.999999:

        raise ValueError(f"A aresta selecionada já é paralela ao eixo {axis}.")

    center = mid + (shift_axis * float(offset))

    obj = new_guide(doc, f"Guia {axis} {float(offset):+.1f}", make_long_line(center, direction, length), "Paralela", length)

    set_ref(obj, "UhryReferencia1", src, subname, "Referência")

    add_prop(obj, "App::PropertyString", "UhryEixo", "")

    add_prop(obj, "App::PropertyDistance", "UhryDistancia", "")

    obj.UhryEixo = axis

    obj.UhryDistancia = float(offset)

    obj.UhryInfo = f"Paralela deslocada {float(offset):+.1f} em {axis}"

    return obj



def create_axis_guide(doc, axis, length):

    items = selected_items()

    src, subname, shape = items[0]

    point = vertex_point(src, subname, shape)

    obj = new_guide(doc, f"Guia {axis} por ponto", make_long_line(point, get_axis(axis), length), "EixoPorPonto", length)

    set_ref(obj, "UhryReferencia1", src, subname, "Referência")

    add_prop(obj, "App::PropertyString", "UhryEixo", "")

    obj.UhryEixo = axis

    return obj



def create_three_axis_guides(doc, length):

    items = selected_items()

    src, subname, shape = items[0]

    point = vertex_point(src, subname, shape)

    created = []

    for axis in ["X", "Y", "Z"]:

        obj = new_guide(doc, f"Guia {axis} por ponto", make_long_line(point, get_axis(axis), length), "EixoPorPonto", length)

        set_ref(obj, "UhryReferencia1", src, subname, "Referência")

        add_prop(obj, "App::PropertyString", "UhryEixo", "")

        obj.UhryEixo = axis

        created.append(obj)

    return created



def create_middle_guide(doc, length):

    items = selected_items()

    a_obj, a_sub, a_shape = items[0]

    b_obj, b_sub, b_shape = items[1]

    _, _, a_mid, a_dir = straight_edge_data(a_obj, a_sub, a_shape)

    _, _, b_mid, b_dir = straight_edge_data(b_obj, b_sub, b_shape)

    if abs(a_dir.dot(b_dir)) < 0.999:

        raise ValueError("As arestas não são paralelas.")

    if a_dir.dot(b_dir) < 0:

        b_dir = b_dir * -1.0

    center = (a_mid + b_mid) * 0.5

    direction = unit(a_dir + b_dir)

    obj = new_guide(doc, "Guia central", make_long_line(center, direction, length), "CentralEntreArestas", length)

    set_ref(obj, "UhryReferencia1", a_obj, a_sub, "Ref 1")

    set_ref(obj, "UhryReferencia2", b_obj, b_sub, "Ref 2")

    return obj



def update_guide(obj):

    mode = getattr(obj, "UhryTipoGuia", "")

    length = min(max(float(getattr(obj, "UhryComprimento", 20000.0)), 1.0), 1000000.0)

    src1, sub1 = read_guide_ref(obj, "UhryReferencia1")

    if not src1 or not sub1: raise ValueError("Referência 1 perdida.")



    if mode == "Paralela":

        _, _, mid, direction = straight_edge_data(src1, sub1)

        axis = str(getattr(obj, "UhryEixo", "X"))

        offset = float(getattr(obj, "UhryDistancia", 0.0))

        center = mid + (get_axis(axis) * offset)

        obj.Shape = make_long_line(center, direction, length)

    elif mode == "EixoPorPonto":

        point = vertex_point(src1, sub1)

        axis = str(getattr(obj, "UhryEixo", "X"))

        obj.Shape = make_long_line(point, get_axis(axis), length)

    elif mode == "CentralEntreArestas":

        src2, sub2 = read_guide_ref(obj, "UhryReferencia2")

        if not src2 or not sub2: raise ValueError("Referência 2 perdida.")

        _, _, a_mid, a_dir = straight_edge_data(src1, sub1)

        _, _, b_mid, b_dir = straight_edge_data(src2, sub2)

        if abs(a_dir.dot(b_dir)) < 0.999: raise ValueError("Não são mais paralelas.")

        if a_dir.dot(b_dir) < 0: b_dir = b_dir * -1.0

        center = (a_mid + b_mid) * 0.5

        direction = unit(a_dir + b_dir)

        obj.Shape = make_long_line(center, direction, length)



    set_guide_style(obj)



def update_all_guides(doc):

    guides = all_guides(doc)

    updated, errors = 0, []

    for obj in guides:

        try:

            update_guide(obj)

            updated += 1

        except Exception as e:

            errors.append(f"{obj.Label}: {e}")

    doc.recompute()

    return updated, errors



def toggle_all_guides(doc):

    guides = all_guides(doc)

    if not guides: return 0, False

    state = not any(g.ViewObject.Visibility for g in guides)

    for obj in guides: obj.ViewObject.Visibility = state

    return len(guides), state



def delete_all_guides(doc):

    guides = all_guides(doc)

    names = [g.Name for g in guides]

    doc.openTransaction("Apagar Linhas Guia")

    try:

        for name in names:

            if doc.getObject(name): doc.removeObject(name)

        group = doc.getObject(GROUP_NAME)

        if group and not group.Group: doc.removeObject(group.Name)

        doc.recompute()

        doc.commitTransaction()

    except:

        doc.abortTransaction()

        raise

    return len(names)



# ==========================================

# CRIAÇÃO OU ABERTURA DE SKETCH NA GUIA

# ==========================================

def show_guides_while_sketching(doc):
    """Mantém as guias visíveis/selecionáveis durante a edição do Sketcher."""
    try:
        group = doc.getObject(GROUP_NAME)
        if group and getattr(group, "ViewObject", None):
            group.ViewObject.Visibility = True
    except Exception:
        pass

    for guide in all_guides(doc):
        try:
            if guide.ViewObject:
                guide.ViewObject.Visibility = True
        except Exception:
            pass

    try:
        Gui.activeDocument().activeView().redraw()
    except Exception:
        pass



def _direct_container_parents(obj):
    """
    Retorna somente contêineres que realmente contêm o objeto pela propriedade Group.
    Evita confundir InList de referência com relação pai/filho.
    """
    parents = []
    for parent in list(getattr(obj, "InList", []) or []):
        try:
            group = getattr(parent, "Group", None)
            if group is not None and obj in list(group):
                parents.append(parent)
        except Exception:
            pass
    return parents


def _containing_app_part(obj, _visited=None):
    """
    Encontra o App::Part geométrico que contém o objeto, inclusive quando há
    App::DocumentObjectGroup entre o objeto e o Part.
    """
    if obj is None:
        return None
    if _visited is None:
        _visited = set()
    name = getattr(obj, "Name", None)
    key = (getattr(obj, "Document", None), name, id(obj))
    if key in _visited:
        return None
    _visited.add(key)

    for parent in _direct_container_parents(obj):
        if getattr(parent, "TypeId", "") == "App::Part":
            return parent

    for parent in _direct_container_parents(obj):
        found = _containing_app_part(parent, _visited)
        if found is not None:
            return found
    return None


def _global_placement_safe(obj):
    try:
        return obj.getGlobalPlacement()
    except Exception:
        try:
            return obj.Placement
        except Exception:
            return App.Placement()


def _remove_from_direct_geo_containers(obj):
    """
    Remove o objeto somente de contêineres geométricos diretos (Body/App::Part).
    É usado para neutralizar o comportamento do FreeCAD que pode inserir um
    Sketch recém-criado no Part/Body atualmente ativo.
    """
    for parent in list(_direct_container_parents(obj)):
        if getattr(parent, "TypeId", "") in ("App::Part", "PartDesign::Body"):
            try:
                parent.removeObject(obj)
            except Exception:
                try:
                    parent.removeObjectsFromDocument([obj.Name])
                except Exception:
                    pass


def _sync_sketch_scope_with_guide(sketch, guide, desired_global_placement=None):
    """
    Coloca o Sketch no MESMO escopo geométrico (App::Part) da Linha Guia.

    Esse detalhe é indispensável para o Sketcher aceitar External Projection.
    Criar o Sketch com doc.addObject() enquanto outro Part/Body está ativo pode
    colocá-lo silenciosamente naquele contêiner, mesmo que o código não chame
    body.addObject(). O resultado é:
        "This object belongs to another part, can't link..."

    A rotina preserva a posição global durante a correção.
    """
    if desired_global_placement is None:
        desired_global_placement = _global_placement_safe(sketch)

    target_part = _containing_app_part(guide)

    # Sai de Body/App::Part eventualmente escolhidos pelo estado ativo da GUI.
    _remove_from_direct_geo_containers(sketch)

    # Se a guia pertence a um App::Part, o Sketch entra exatamente no mesmo Part.
    if target_part is not None:
        try:
            if sketch not in list(getattr(target_part, "Group", []) or []):
                target_part.addObject(sketch)
        except Exception:
            target_part.addObject(sketch)

        # Placement do Sketch é local ao Part. Converte o Placement global desejado.
        try:
            part_global = target_part.getGlobalPlacement()
            sketch.Placement = part_global.inverse() * desired_global_placement
        except Exception:
            sketch.Placement = desired_global_placement
    else:
        # Guia na raiz -> Sketch também na raiz.
        sketch.Placement = desired_global_placement

    return target_part


def enter_sketch_edit_with_guides(doc, sketch):
    """Entra em edição e reaplica visibilidade após o Sketcher mudar o estado visual."""
    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sketch)
    Gui.activeDocument().setEdit(sketch.Name)
    show_guides_while_sketching(doc)
    try:
        QtCore.QTimer.singleShot(0, lambda: show_guides_while_sketching(doc))
        QtCore.QTimer.singleShot(80, lambda: show_guides_while_sketching(doc))
    except Exception:
        pass

def create_or_open_sketch_on_guide(doc, plane_choice, import_external=True, open_edit=True):

    items = selected_items()

    if not items:

        raise ValueError("Selecione uma Linha Guia (no 3D ou na Árvore) para abrir o Sketcher.")



    obj, subname, shape = items[0]



    # 1. Se a Guia já possuir um Sketch previamente vinculado, abre direto!

    if hasattr(obj, "UhrySketcher") and obj.UhrySketcher is not None:

        existing_sketch = obj.UhrySketcher

        # Garante que o Sketch permaneça no mesmo escopo geométrico da guia.
        try:
            gp = _global_placement_safe(existing_sketch)
            _sync_sketch_scope_with_guide(existing_sketch, obj, gp)
            doc.recompute()
        except Exception as e:
            App.Console.PrintWarning(
                f"[Linha Guia] Não foi possível reparar o escopo do Sketch existente: {e}\n"
            )

        if open_edit:

            enter_sketch_edit_with_guides(doc, existing_sketch)

        return existing_sketch



    # 2. Se for uma nova Guia, extrai Ponto e Direção

    if shape.ShapeType == 'Edge':

        _, _, center, direction = straight_edge_data(obj, subname, shape)

    elif shape.ShapeType == 'Vertex':

        center = vertex_point(obj, subname, shape)

        direction = App.Vector(1, 0, 0)

    else:

        center = shape.BoundBox.Center

        direction = App.Vector(1, 0, 0)



    doc.openTransaction("Criar Sketch na Guia")

    try:

        sketch = doc.addObject("Sketcher::SketchObject", f"Sketch_{obj.Label}")

        sketch.Label = f"Sketch_{obj.Label}"



        # Sincroniza explicitamente o escopo do Sketch com o da Linha Guia.

        # Matriz de Orientação do Plano

        if plane_choice == "Plano XY (Horizontal)":

            rot = App.Rotation(App.Vector(0,0,1), 0)

        elif plane_choice == "Plano XZ (Frontal)":

            rot = App.Rotation(App.Vector(1,0,0), 90)

        elif plane_choice == "Plano YZ (Lateral)":

            rot = App.Rotation(App.Vector(0,1,0), -90)

        elif plane_choice == "Perpendicular à Guia":

            rot = App.Rotation(App.Vector(0,0,1), direction)

        else:

            rot = App.Rotation(App.Vector(0,0,1), 0)



        desired_global_placement = App.Placement(center, rot)

        # Força Sketch e Guia a pertencerem ao MESMO App::Part (ou ambos à raiz)
        # preservando a posição global do plano.
        _sync_sketch_scope_with_guide(
            sketch,
            obj,
            desired_global_placement=desired_global_placement,
        )



        # Importa a própria Guia como Geometria Externa no Sketcher.
        # Mantém o erro disponível no Report View se o link for bloqueado.
        if import_external and shape.ShapeType == 'Edge':

            try:

                sketch.addExternal(obj.Name, subname)

            except Exception as e:
                App.Console.PrintWarning(
                    f"[Linha Guia] Falha ao projetar a guia inicial "
                    f"{obj.Label}.{subname}: {e}\n"
                )



        # Registra o vínculo no objeto da Guia para aberturas futuras

        add_prop(obj, "App::PropertyLink", "UhrySketcher", "Sketch vinculado a esta guia.")

        obj.UhrySketcher = sketch



        doc.recompute()

        doc.commitTransaction()



        if open_edit:

            enter_sketch_edit_with_guides(doc, sketch)



        return sketch

    except Exception as e:

        doc.abortTransaction()

        raise e



# ==========================================

# MODO DIRETO 3D

# ==========================================

_ACTIVE_DIRECT_TOOL = None


def _computed_auto_length(doc):
    try:
        bb = doc.BoundBox
        diag = bb.DiagonalLength
        if diag > 0:
            return min(max(diag * 3.0, 1000.0), 1000000.0)
    except Exception:
        pass
    return 15000.0


def _camera_vector_from_coin(sbvec):
    return App.Vector(float(sbvec[0]), float(sbvec[1]), float(sbvec[2]))


class DirectGuideTool(QtCore.QObject):
    """
    Ferramenta interativa de Linha Guia.

    O arraste usa apenas preview Coin3D, sem recompute do documento. A criação
    da guia é confirmada fora do callback de mouse para preservar o scenegraph.
    """

    def __init__(self, doc, src, subname, shape):
        super().__init__()

        self.doc = doc
        self.src = src
        self.subname = subname
        self.shape = shape
        self.view = Gui.activeDocument().activeView()
        self.main_window = Gui.getMainWindow()
        self.qt_app = QtWidgets.QApplication.instance()

        _, _, self.mid, self.direction = straight_edge_data(src, subname, shape)
        self.length = _computed_auto_length(doc)

        self.valid_axes = [
            name for name in ("Z", "Y", "X")
            if abs(self.direction.dot(get_axis(name))) <= 0.999999
        ]
        if not self.valid_axes:
            raise ValueError("Não foi possível encontrar um eixo válido para deslocar esta aresta.")

        self.locked_axis = None
        self.auto_axis = self._best_visible_axis()
        self.current_axis = self.auto_axis
        self.current_offset = 0.0

        # Camada de snap apenas para o PREVIEW/medição. Ela nunca altera o
        # documento durante o movimento do mouse. O clique continua sendo a
        # única operação que cria uma Linha Guia real.
        self.snap_kind = "LIVRE"
        self.snap_point = None
        self._snap_intersections = []
        self._refresh_snap_intersections()

        # Texto digitado e sinal herdado do lado para onde o cursor estava.
        # Ex.: puxou para baixo em Z e digitou 50 -> usa -50 mm.
        self.numeric_buffer = ""
        self.numeric_direction_sign = 1.0

        self.finished = False
        self.pending_action = None

        self._scene = self.view.getSceneGraph()
        self._ghost_root = None
        self._ghost_coords = None
        self._move_cb = None
        self._mouse_cb = None

        self.measure_overlay = None
        self.measure_edit = None
        self.measure_unit = None
        self.measure_tape = None

        self._build_ghost()
        self._update_ghost(0.0, self.current_axis)
        self._create_measure_ui()

        self._move_cb = self.view.addEventCallback(
            "SoLocation2Event", self._on_mouse_move
        )
        self._mouse_cb = self.view.addEventCallback(
            "SoMouseButtonEvent", self._on_mouse_button
        )

        # Mantém o foco no campo numérico real. Esta foi a solução estável
        # Mantém o foco no campo numérico.
        self.focus_measure(select_all=False)
        self._show_status()

    # --------------------------------------------------------
    # PREVIEW / GEOMETRIA DE TELA
    # --------------------------------------------------------

    def _build_ghost(self):
        root = coin.SoSeparator()

        color = coin.SoBaseColor()
        color.rgb = (0.20, 0.75, 1.00)

        style = coin.SoDrawStyle()
        style.lineWidth = 3.0
        try:
            style.linePattern = 0x00FF
        except Exception:
            pass

        coords = coin.SoCoordinate3()
        coords.point.setNum(2)
        coords.point.set1Value(0, 0.0, 0.0, 0.0)
        coords.point.set1Value(1, 0.0, 0.0, 0.0)

        line = coin.SoLineSet()
        line.numVertices.set1Value(0, 2)

        root.addChild(color)
        root.addChild(style)
        root.addChild(coords)
        root.addChild(line)
        self._scene.addChild(root)

        self._ghost_root = root
        self._ghost_coords = coords

    def _best_visible_axis(self):
        try:
            view_dir = self.view.getCameraOrientation().multVec(App.Vector(0, 0, -1))
            view_dir = unit(view_dir)
            return min(self.valid_axes, key=lambda a: abs(get_axis(a).dot(view_dir)))
        except Exception:
            return self.valid_axes[0]

    def _screen_ray(self, pos):
        x, y = int(pos[0]), int(pos[1])
        p = App.Vector(self.view.getPoint(x, y))

        camera_type = str(self.view.getCameraType())
        if "Perspective" in camera_type:
            cam = self.view.getCameraNode()
            cp = cam.position.getValue()
            origin = _camera_vector_from_coin(cp)
            direction = unit(p - origin)
        else:
            origin = p
            direction = unit(
                self.view.getCameraOrientation().multVec(App.Vector(0, 0, -1))
            )

        return origin, direction

    def _offset_for_axis_legacy(self, axis_name, pos):
        """Algoritmo estável anterior, mantido como fallback defensivo."""
        axis = get_axis(axis_name)
        ray_origin, ray_dir = self._screen_ray(pos)

        b = axis.dot(ray_dir)
        denom = 1.0 - (b * b)
        if abs(denom) < 1e-9:
            return None, None

        w = self.mid - ray_origin
        s = (b * ray_dir.dot(w) - axis.dot(w)) / denom
        t = ray_dir.dot(w) + (b * s)

        axis_point = self.mid + (axis * s)
        ray_point = ray_origin + (ray_dir * t)
        separation = (axis_point - ray_point).Length
        return float(s), float(separation)

    def _movement_plane(self, axis_name):
        """Plano varrido pela linha ao deslocar no eixo global escolhido."""
        axis = get_axis(axis_name)
        normal = self.direction.cross(axis)
        if normal.Length < 1e-9:
            return None, None
        normal.normalize()
        return axis, normal

    def _movement_plane_name(self, axis_name):
        """Nome amigável do plano global quando ele coincide com XY/XZ/YZ."""
        try:
            _axis, normal = self._movement_plane(axis_name)
            if normal is None:
                return axis_name
            comps = {
                "X": abs(normal.dot(App.Vector(1, 0, 0))),
                "Y": abs(normal.dot(App.Vector(0, 1, 0))),
                "Z": abs(normal.dot(App.Vector(0, 0, 1))),
            }
            dominant = max(comps, key=comps.get)
            if comps[dominant] >= 0.999:
                return {"X": "YZ", "Y": "XZ", "Z": "XY"}[dominant]
        except Exception:
            pass
        return axis_name

    def _offset_from_world_point(self, axis_name, point):
        """
        Calcula o deslocamento que faz a guia passar por ``point``.

        A guia possível é: mid + direction*t + axis*s. Resolvemos t e s
        por mínimos quadrados. O residual informa se o ponto pertence ao plano
        que a guia consegue alcançar sem inventar profundidade.
        """
        axis = get_axis(axis_name)
        d = self.direction
        rel = App.Vector(point) - self.mid
        c = d.dot(axis)
        denom = 1.0 - c * c
        if abs(denom) < 1e-10:
            return None, None

        rd = rel.dot(d)
        ra = rel.dot(axis)
        along = (rd - c * ra) / denom
        offset = (ra - c * rd) / denom
        reconstructed = self.mid + d * along + axis * offset
        residual = (App.Vector(point) - reconstructed).Length
        return float(offset), float(residual)

    def _offset_for_axis(self, axis_name, pos):
        """
        Faz a linha fantasma passar pela ponta do mouse.

        Em vez de aproximar apenas o eixo de deslocamento ao raio da câmera,
        intersectamos o raio com o PLANO varrido pela linha (direção da linha +
        eixo global). Isso preserva a mesma grandeza de deslocamento, mas deixa
        o preview visual muito mais intuitivo. O algoritmo antigo continua como
        fallback para vistas degeneradas/paralelas.
        """
        try:
            axis, normal = self._movement_plane(axis_name)
            if normal is None:
                return self._offset_for_axis_legacy(axis_name, pos)

            ray_origin, ray_dir = self._screen_ray(pos)
            den = normal.dot(ray_dir)
            if abs(den) < 1e-10:
                return self._offset_for_axis_legacy(axis_name, pos)

            ray_t = normal.dot(self.mid - ray_origin) / den
            if "Perspective" in str(self.view.getCameraType()) and ray_t <= 0:
                return self._offset_for_axis_legacy(axis_name, pos)

            cursor_point = ray_origin + ray_dir * ray_t
            offset, residual = self._offset_from_world_point(axis_name, cursor_point)
            if offset is None:
                return self._offset_for_axis_legacy(axis_name, pos)
            return float(offset), float(residual or 0.0)
        except Exception:
            return self._offset_for_axis_legacy(axis_name, pos)

    def _world_per_pixel(self, point, pos):
        """Escala aproximada mm/pixel na profundidade do ponto."""
        try:
            size = self.view.getSize()
            height_px = max(1.0, float(size[1]))
            cam = self.view.getCameraNode()
            camera_type = str(self.view.getCameraType())

            if "Perspective" in camera_type:
                cp = _camera_vector_from_coin(cam.position.getValue())
                forward = unit(
                    self.view.getCameraOrientation().multVec(App.Vector(0, 0, -1))
                )
                depth = abs((App.Vector(point) - cp).dot(forward))
                angle = float(cam.heightAngle.getValue())
                visible_height = 2.0 * max(depth, 1e-6) * math.tan(angle * 0.5)
                return max(visible_height / height_px, 1e-9)

            visible_height = float(cam.height.getValue())
            return max(visible_height / height_px, 1e-9)
        except Exception:
            try:
                x, y = int(pos[0]), int(pos[1])
                a = App.Vector(self.view.getPoint(x, y))
                b = App.Vector(self.view.getPoint(x + 1, y))
                scale = (b - a).Length
                if scale > 1e-9:
                    return scale
            except Exception:
                pass
        return 1.0

    def _refresh_snap_intersections(self):
        """Reaproveita o cálculo já validado do Snap Cruzamento da Direct."""
        try:
            from .guide_intersection_snap import capture_intersections
            self._snap_intersections = capture_intersections(self.doc)
        except Exception:
            self._snap_intersections = []

    def _nearest_guide_intersection(self, pos, axis_name):
        if not self._snap_intersections:
            return None
        try:
            ray_origin, ray_dir = self._screen_ray(pos)
        except Exception:
            return None

        best = None
        best_ratio = None
        for hit in self._snap_intersections:
            p = App.Vector(hit["point"])
            t = (p - ray_origin).dot(ray_dir)
            if "Perspective" in str(self.view.getCameraType()) and t <= 0:
                continue
            closest = ray_origin + ray_dir * t
            dist_world = (p - closest).Length
            radius_world = max(self._world_per_pixel(p, pos) * 14.0, 0.05)
            ratio = dist_world / radius_world
            if ratio > 1.0:
                continue

            offset, residual = self._offset_from_world_point(axis_name, p)
            if offset is None or residual is None or residual > 0.20:
                continue

            if best_ratio is None or ratio < best_ratio:
                best_ratio = ratio
                best = {"point": p, "offset": offset, "kind": "CRUZAMENTO"}
        return best

    def _object_info(self, pos):
        try:
            x, y = int(pos[0]), int(pos[1])
            data = self.view.getObjectInfo((x, y))
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    def _edge_snap_candidate(self, pos, axis_name):
        """
        Snap exato em ARESTA sob o cursor.

        Para aresta reta, procura primeiro a interseção matemática da aresta
        com o plano ativo da guia. Se a aresta inteira já estiver nesse plano,
        usa o ponto real devolvido pelo pick do FreeCAD. Curvas só são usadas
        quando o ponto clicado realmente pertence ao plano alcançável.
        """
        data = self._object_info(pos)
        if not data:
            return None

        component = str(data.get("Component", "") or "")
        if not component.startswith("Edge"):
            return None

        # Evita que a própria aresta de origem domine o snap quando o usuário
        # apenas começa a puxar a guia. Zero continua possível em modo livre.
        object_name = str(data.get("Object", "") or "")
        if object_name == getattr(self.src, "Name", "") and component == self.subname:
            return None

        hit_point = None
        try:
            hit_point = App.Vector(
                float(data["x"]), float(data["y"]), float(data["z"])
            )
        except Exception:
            pass

        obj = self.doc.getObject(object_name) if object_name else None
        edge = None
        if obj is not None:
            try:
                edge = Part.getShape(
                    obj, component, needSubElement=True, transform=True
                )
            except Exception:
                try:
                    edge = transformed_subelement(obj, component)
                except Exception:
                    edge = None

        axis, normal = self._movement_plane(axis_name)
        if normal is None:
            return None

        target = None
        if edge is not None and getattr(edge, "ShapeType", "") == "Edge":
            verts = list(getattr(edge, "Vertexes", []) or [])
            if len(verts) >= 2:
                p1 = App.Vector(verts[0].Point)
                p2 = App.Vector(verts[-1].Point)
                d1 = normal.dot(p1 - self.mid)
                d2 = normal.dot(p2 - self.mid)
                eps = 0.20

                if abs(d1) <= eps and abs(d2) <= eps:
                    # Aresta contida no plano ativo: o ponto sob o cursor é a
                    # referência mais intuitiva e continua geometricamente exato.
                    target = hit_point if hit_point is not None else (p1 + p2) * 0.5
                else:
                    seg = p2 - p1
                    den = normal.dot(seg)
                    if abs(den) > 1e-12:
                        u = normal.dot(self.mid - p1) / den
                        if -1e-7 <= u <= 1.0 + 1e-7:
                            target = p1 + seg * u

        if target is None and hit_point is not None:
            target = hit_point

        if target is None:
            return None

        offset, residual = self._offset_from_world_point(axis_name, target)
        if offset is None or residual is None or residual > 0.20:
            return None

        return {"point": App.Vector(target), "offset": offset, "kind": "ARESTA"}

    def _snap_candidate(self, pos, axis_name):
        # Prioridade proposital: cruzamento matemático de guias > aresta.
        hit = self._nearest_guide_intersection(pos, axis_name)
        if hit is not None:
            return hit
        return self._edge_snap_candidate(pos, axis_name)

    def _choose_auto_axis(self, pos):
        candidates = []
        for axis_name in self.valid_axes:
            try:
                offset, separation = self._offset_for_axis(axis_name, pos)
                if offset is not None:
                    candidates.append((separation, axis_name, offset))
            except Exception:
                pass

        if not candidates:
            return self.auto_axis, self.current_offset

        candidates.sort(key=lambda item: item[0])
        _, axis_name, offset = candidates[0]
        return axis_name, offset

    def _update_ghost(self, offset, axis_name):
        if not axis_name or self._ghost_coords is None:
            return

        center = self.mid + (get_axis(axis_name) * float(offset))
        half = self.length * 0.5
        p1 = center - (self.direction * half)
        p2 = center + (self.direction * half)

        self._ghost_coords.point.set1Value(
            0, coin.SbVec3f(p1.x, p1.y, p1.z)
        )
        self._ghost_coords.point.set1Value(
            1, coin.SbVec3f(p2.x, p2.y, p2.z)
        )

    # --------------------------------------------------------
    # UI NUMÉRICA — APENAS VISUAL; TECLADO É CAPTURADO GLOBALMENTE
    # --------------------------------------------------------

    def _create_measure_ui(self):
        """
        Cria um pequeno visor de medida sobre a área 3D, no estilo SketchUp.

        IMPORTANTE: esta camada altera apenas a apresentação. Toda a lógica
        geométrica, sinal, trava X/Y/Z, preview Coin3D e entrada numérica
        continua exatamente a mesma que já foi validada nas versões anteriores.
        """
        overlay = QtWidgets.QFrame(self.main_window)
        overlay.setObjectName("DirectGuideMeasureOverlay")
        try:
            overlay.setFrameShape(QtWidgets.QFrame.NoFrame)
        except Exception:
            pass

        # A caixa não intercepta cliques do viewport. O campo continua recebendo
        # teclado porque o foco é atribuído programaticamente.
        try:
            attr = getattr(QtCore.Qt, "WA_TransparentForMouseEvents", None)
            if attr is None:
                attr = QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents
            overlay.setAttribute(attr, True)
        except Exception:
            pass

        overlay.setStyleSheet(
            "QFrame#DirectGuideMeasureOverlay {"
            " background: rgba(30, 30, 30, 225);"
            " border: 1px solid rgba(235, 235, 235, 190);"
            " border-radius: 5px;"
            " }"
            " QLabel { color: white; background: transparent; border: none; }"
            " QLineEdit { color: white; background: transparent; border: none;"
            " font-weight: bold; padding: 0px; selection-background-color: #2d7dd2; }"
        )

        layout = QtWidgets.QHBoxLayout(overlay)
        layout.setContentsMargins(7, 3, 7, 3)
        layout.setSpacing(4)

        tape = QtWidgets.QLabel("📏")
        tape.setToolTip("Medida da Linha Guia")

        edit = DirectGuideMeasureEdit(self)
        edit.setFixedWidth(82)
        edit.setFixedHeight(22)
        edit.setPlaceholderText("0,000")
        try:
            align_right = getattr(QtCore.Qt, "AlignRight", None)
            if align_right is None:
                align_right = QtCore.Qt.AlignmentFlag.AlignRight
            edit.setAlignment(align_right)
        except Exception:
            pass
        edit.textChanged.connect(self._on_measure_text_changed)

        unit_lbl = QtWidgets.QLabel("mm")

        layout.addWidget(tape)
        layout.addWidget(edit)
        layout.addWidget(unit_lbl)

        overlay.adjustSize()
        overlay.show()
        overlay.raise_()

        self.measure_overlay = overlay
        self.measure_edit = edit
        self.measure_unit = unit_lbl
        self.measure_tape = tape
        self._update_measure_overlay_position()

    def _remove_measure_ui(self):
        if self.measure_overlay is not None:
            try:
                self.measure_overlay.hide()
            except Exception:
                pass
            try:
                self.measure_overlay.deleteLater()
            except Exception:
                pass

        self.measure_overlay = None
        self.measure_edit = None
        self.measure_unit = None
        self.measure_tape = None

    def _update_measure_overlay_position(self):
        """Posiciona a caixinha perto do cursor, sem cobrir o ponto medido."""
        if self.measure_overlay is None:
            return
        try:
            global_pos = QtGui.QCursor.pos()
            local = self.main_window.mapFromGlobal(global_pos)
            self.measure_overlay.adjustSize()
            w = self.measure_overlay.width()
            h = self.measure_overlay.height()

            x = int(local.x()) + 22
            y = int(local.y()) + 22

            # Mantém o visor dentro da janela principal.
            max_x = max(4, self.main_window.width() - w - 8)
            max_y = max(4, self.main_window.height() - h - 8)
            x = max(4, min(x, max_x))
            y = max(4, min(y, max_y))

            self.measure_overlay.move(x, y)
            self.measure_overlay.raise_()
        except Exception:
            pass

    def focus_measure(self, select_all=False):
        if self.measure_edit is None:
            return
        try:
            reason = getattr(QtCore.Qt, "OtherFocusReason", None)
            if reason is None:
                reason = QtCore.Qt.FocusReason.OtherFocusReason
            self.measure_edit.setFocus(reason)
        except Exception:
            try:
                self.measure_edit.setFocus()
            except Exception:
                return
        if select_all:
            try:
                self.measure_edit.selectAll()
            except Exception:
                pass

    def _parse_numeric(self):
        raw = self.numeric_buffer.strip().replace(',', '.')
        if raw in ("", "+", "-", ".", "+.", "-."):
            return None

        # Aceita também mm, cm e m, igual ao Mover Direct.
        factor = 1.0
        low = raw.lower()
        if low.endswith("mm"):
            raw = raw[:-2].strip()
        elif low.endswith("cm"):
            raw = raw[:-2].strip()
            factor = 10.0
        elif low.endswith("m"):
            raw = raw[:-1].strip()
            factor = 1000.0

        try:
            value = float(raw) * factor
        except Exception:
            return None

        # Sinal digitado explicitamente ganha prioridade.
        if raw.startswith(("+", "-")):
            return value

        return abs(value) * self.numeric_direction_sign

    def _on_measure_text_changed(self, text):
        if self.finished or self.pending_action:
            return

        previous_empty = not self.numeric_buffer.strip()
        self.numeric_buffer = str(text)

        # Ao começar a digitar sem sinal explícito, mantém o lado do arraste.
        clean = self.numeric_buffer.strip()
        if previous_empty and clean and not clean.startswith(("+", "-")):
            self.numeric_direction_sign = -1.0 if self.current_offset < 0 else 1.0

        typed = self._parse_numeric()
        if typed is not None:
            self.current_offset = typed
            self._update_ghost(self.current_offset, self.current_axis)

        self._sync_measure_ui()

    def confirm_numeric(self):
        if self.finished or self.pending_action:
            return

        typed = self._parse_numeric()
        if typed is None and not self.numeric_buffer.strip():
            typed = float(self.current_offset)
        if typed is None:
            self._show_status("Digite uma medida válida, por exemplo 50 ou 50,5.")
            self.focus_measure(select_all=True)
            return

        self.current_offset = typed
        self._update_ghost(self.current_offset, self.current_axis)
        self._request_confirm()

    def _sync_measure_ui(self):
        shown = self._parse_numeric()
        if shown is None:
            shown = self.current_offset

        # Preview visual: o valor é mostrado sem entrar em numeric_buffer.
        # Assim, ao digitar o primeiro número, a entrada real substitui o
        # preview, preservando o comportamento já validado contra atalhos 0..9.
        if self.measure_edit is not None and not self.numeric_buffer.strip():
            try:
                self.measure_edit.blockSignals(True)
                self.measure_edit.setText(f"{float(shown):.3f}")
                self.measure_edit.blockSignals(False)
            except Exception:
                try:
                    self.measure_edit.blockSignals(False)
                except Exception:
                    pass

        if self.measure_unit is not None:
            try:
                plane = self._movement_plane_name(self.current_axis) if self.current_axis else ""
                kind = self.snap_kind if self.snap_kind not in ("", "LIVRE") else ""
                extra = " • ".join(x for x in (plane, kind) if x)
                self.measure_unit.setText("mm" + (" • " + extra if extra else ""))
            except Exception:
                self.measure_unit.setText("mm")

        self._update_measure_overlay_position()

    def _show_status(self, extra=""):
        self._sync_measure_ui()

        msg = (
            "Linha Guia — mova/MEÇA | X/Y/Z trava plano global | "
            "digite a medida + Enter | clique confirma | Esc cancela"
        )
        if extra:
            msg += " | " + str(extra)

        self.main_window.statusBar().showMessage(msg)

    # --------------------------------------------------------
    # MOUSE — SOMENTE GHOST
    # --------------------------------------------------------

    def _on_mouse_move(self, info):
        if self.finished or self.pending_action or self.numeric_buffer:
            return

        pos = info.get("Position")
        if not pos:
            return

        try:
            if self.locked_axis:
                axis_name = self.locked_axis
                offset, _ = self._offset_for_axis(axis_name, pos)
                if offset is None:
                    self._show_status(
                        "Eixo alinhado à câmera; digite a distância."
                    )
                    return
            else:
                axis_name, offset = self._choose_auto_axis(pos)

            # Snap de medição é apenas uma camada de entrada. O documento não
            # recebe recompute nem novos objetos enquanto o mouse se move.
            snap = self._snap_candidate(pos, axis_name)
            if snap is not None:
                offset = snap["offset"]
                self.snap_kind = snap["kind"]
                self.snap_point = App.Vector(snap["point"])
            else:
                self.snap_kind = "LIVRE"
                self.snap_point = None

            self.current_axis = axis_name
            self.current_offset = float(offset)
            self._update_ghost(self.current_offset, self.current_axis)
            extra = "SNAP " + self.snap_kind if self.snap_kind != "LIVRE" else ""
            self._show_status(extra)

        except Exception as exc:
            self._show_status(str(exc))

    def _on_mouse_button(self, info):
        if self.finished or self.pending_action:
            return

        if str(info.get("State", "")).upper() != "DOWN":
            return

        button = str(info.get("Button", "")).upper()

        if button in ("BUTTON1", "LEFT", "LEFTBUTTON"):
            self._request_confirm()
        elif button in ("BUTTON2", "BUTTON3", "RIGHT", "RIGHTBUTTON"):
            self._request_cancel()

    # --------------------------------------------------------
    # TECLADO — FILTRO GLOBAL QT, NÃO Coin3D
    # --------------------------------------------------------

    def _set_axis(self, axis_name):
        if axis_name not in self.valid_axes:
            self._show_status(
                f"{axis_name} é paralelo à aresta; use outro eixo."
            )
            return

        self.locked_axis = axis_name
        self.current_axis = axis_name
        self.snap_kind = "LIVRE"
        self.snap_point = None

        typed = self._parse_numeric()
        if typed is not None:
            self.current_offset = typed

        self._update_ghost(self.current_offset, self.current_axis)
        self._show_status()
        self.focus_measure(select_all=False)

    def _append_numeric(self, char):
        # No primeiro algarismo sem sinal explícito, preserva o lado para onde
        # o cursor já estava puxando a guia.
        if not self.numeric_buffer and char not in "+-":
            self.numeric_direction_sign = -1.0 if self.current_offset < 0 else 1.0

        if char in ".,":
            if "." in self.numeric_buffer or "," in self.numeric_buffer:
                return

        if char in "+-":
            if self.numeric_buffer:
                # +/- com número já iniciado alterna o sinal explícito.
                if self.numeric_buffer.startswith("-"):
                    self.numeric_buffer = self.numeric_buffer[1:]
                elif self.numeric_buffer.startswith("+"):
                    self.numeric_buffer = "-" + self.numeric_buffer[1:]
                else:
                    self.numeric_buffer = "-" + self.numeric_buffer
            else:
                self.numeric_buffer = char
        else:
            self.numeric_buffer += char

        typed = self._parse_numeric()
        if typed is not None:
            self.current_offset = typed
            self._update_ghost(self.current_offset, self.current_axis)

        self._show_status()

    # O teclado é tratado pelo campo de medida, que mantém foco real.
    # Isso evita que 0..9 sejam interpretados como atalhos de vista pelo FreeCAD.

    # --------------------------------------------------------
    # CONFIRMAÇÃO SEGURA — FORA DO CALLBACK Coin3D
    # --------------------------------------------------------

    def _request_confirm(self):
        if self.finished or self.pending_action:
            return

        if not self.current_axis:
            self._show_status("Escolha X, Y ou Z antes de confirmar.")
            return

        self.pending_action = "confirm"
        QtCore.QTimer.singleShot(0, self._confirm_deferred)

    def _request_cancel(self):
        if self.finished or self.pending_action:
            return

        self.pending_action = "cancel"
        QtCore.QTimer.singleShot(0, self._cancel_deferred)

    def _detach_interaction(self):
        # Chamado apenas fora do callback Coin3D.
        if self.finished:
            return

        self.finished = True

        try:
            if self._move_cb is not None:
                self.view.removeEventCallback(
                    "SoLocation2Event", self._move_cb
                )
        except Exception:
            pass

        try:
            if self._mouse_cb is not None:
                self.view.removeEventCallback(
                    "SoMouseButtonEvent", self._mouse_cb
                )
        except Exception:
            pass

        self._move_cb = None
        self._mouse_cb = None

        try:
            if self._ghost_root is not None:
                self._scene.removeChild(self._ghost_root)
        except Exception:
            pass

        self._ghost_root = None
        self._ghost_coords = None
        self._remove_measure_ui()

    def _confirm_deferred(self):
        global _ACTIVE_DIRECT_TOOL

        if self.finished:
            return

        typed = self._parse_numeric()
        if typed is not None:
            self.current_offset = typed

        axis_name = self.current_axis
        offset = float(self.current_offset)

        # Primeiro desliga callbacks/ghost/filtro. Só DEPOIS toca no documento.
        self._detach_interaction()

        self.doc.openTransaction("Criar Linha Guia")
        try:
            center = self.mid + (get_axis(axis_name) * offset)
            obj = new_guide(
                self.doc,
                f"Guia {axis_name} {offset:+.1f}",
                make_long_line(center, self.direction, self.length),
                "Paralela",
                self.length,
            )

            set_ref(
                obj, "UhryReferencia1", self.src, self.subname, "Referência"
            )
            add_prop(obj, "App::PropertyString", "UhryEixo", "")
            add_prop(obj, "App::PropertyDistance", "UhryDistancia", "")
            obj.UhryEixo = axis_name
            obj.UhryDistancia = offset
            obj.UhryInfo = (
                f"Paralela deslocada {offset:+.1f} em {axis_name}"
            )

            # ÚNICO recompute da operação direta.
            self.doc.recompute()
            self.doc.commitTransaction()

            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(obj)
            self.main_window.statusBar().showMessage(
                f"Linha guia criada: {axis_name} {offset:+.3f} mm",
                5000,
            )

        except Exception as exc:
            try:
                self.doc.abortTransaction()
            except Exception:
                pass

            App.Console.PrintError(
                "Linha Guia 2.5 — erro ao confirmar: {}\n".format(exc)
            )
            try:
                QtWidgets.QMessageBox.critical(
                    self.main_window,
                    "Linha Guia",
                    "Não foi possível criar a guia:\n{}".format(exc),
                )
            except Exception:
                pass

        finally:
            self.pending_action = None
            _ACTIVE_DIRECT_TOOL = None

    def _cancel_deferred(self):
        global _ACTIVE_DIRECT_TOOL

        if self.finished:
            return

        self._detach_interaction()
        self.pending_action = None
        _ACTIVE_DIRECT_TOOL = None
        self.main_window.statusBar().showMessage(
            "Criação da linha guia cancelada.", 3000
        )

    # Compatibilidade com run(): permite cancelar uma ferramenta anterior.
    def cancel(self):
        if self.finished:
            return
        self._request_cancel()


# ==========================================

# INTERFACE GRÁFICA UNIFICADA

# ==========================================

class GuideDialog(QtWidgets.QDialog):

    def __init__(self, doc):

        super().__init__(Gui.getMainWindow())

        self.doc = doc

        self.setWindowTitle("Linhas Guia")

        self.resize(750, 560)

        layout = QtWidgets.QVBoxLayout(self)



        layout.addWidget(QtWidgets.QLabel("<b>Linhas de Referência & Gerador de Sketcher</b>"))

        self.selection_info = QtWidgets.QLabel()

        self.selection_info.setWordWrap(True)

        layout.addWidget(self.selection_info)



        # --- BLOCO 1: CRIAR E GERENCIAR GUIAS ---

        gb_guias = QtWidgets.QGroupBox("1. Criar e Gerenciar Linhas Guia")

        form_g = QtWidgets.QFormLayout(gb_guias)



        self.mode = QtWidgets.QComboBox()

        self.mode.addItems(["Paralela à aresta selecionada", "Guia X/Y/Z pelo vértice", "3 guias X/Y/Z pelo vértice", "Central entre 2 arestas paralelas"])

        form_g.addRow("Modo:", self.mode)



        self.axis = QtWidgets.QComboBox()

        self.axis.addItems(["X", "Y", "Z"])

        form_g.addRow("Eixo do deslocamento:", self.axis)



        self.offset = QtWidgets.QDoubleSpinBox()

        self.offset.setRange(-1e7, 1e7); self.offset.setDecimals(3); self.offset.setValue(100.0); self.offset.setSuffix(" mm")

        form_g.addRow("Distância:", self.offset)



        self.auto_len = QtWidgets.QCheckBox("Comprimento automático"); self.auto_len.setChecked(True)

        form_g.addRow("", self.auto_len)



        self.length = QtWidgets.QDoubleSpinBox()

        self.length.setRange(10.0, 1000000.0); self.length.setDecimals(0); self.length.setValue(10000.0); self.length.setSuffix(" mm"); self.length.setEnabled(False)

        form_g.addRow("Comprimento manual:", self.length)



        self.precalc_lbl = QtWidgets.QLabel()

        self.precalc_lbl.setWordWrap(True)

        self.precalc_lbl.setStyleSheet("background-color:#eef; padding:6px; border-radius:4px; font-family:monospace; font-size:11px;")

        form_g.addRow(self.precalc_lbl)



        row_g = QtWidgets.QHBoxLayout()

        self.create_btn = QtWidgets.QPushButton("Criar guia")

        self.update_btn = QtWidgets.QPushButton("Atualizar todas")

        self.toggle_btn = QtWidgets.QPushButton("Mostrar / ocultar")

        self.delete_btn = QtWidgets.QPushButton("Apagar todas")

        row_g.addWidget(self.create_btn); row_g.addWidget(self.update_btn); row_g.addWidget(self.toggle_btn); row_g.addWidget(self.delete_btn)

        form_g.addRow(row_g)

        layout.addWidget(gb_guias)



        # --- BLOCO 2: CRIAR / ABRIR SKETCH NA GUIA ---

        gb_sketch = QtWidgets.QGroupBox("2. Abrir / Criar Sketcher na Guia Selecionada")

        gb_sketch.setStyleSheet("QGroupBox { font-weight: bold; }")

        form_s = QtWidgets.QFormLayout(gb_sketch)



        self.sketch_plane = QtWidgets.QComboBox()

        self.sketch_plane.addItems(["Plano XY (Horizontal)", "Plano XZ (Frontal)", "Plano YZ (Lateral)", "Perpendicular à Guia"])

        form_s.addRow("Orientação do Plano:", self.sketch_plane)



        self.sketch_import = QtWidgets.QCheckBox("Vincular Guia como Geometria Externa no Sketch")

        self.sketch_import.setChecked(True)

        form_s.addRow("", self.sketch_import)



        self.btn_create_sketch = QtWidgets.QPushButton("✏️ Abrir / Criar Sketcher na Guia Selecionada")

        self.btn_create_sketch.setStyleSheet("font-weight: bold; padding: 7px; background-color: #2E7D32; color: white;")

        form_s.addRow(self.btn_create_sketch)

        layout.addWidget(gb_sketch)



        close_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)

        close_box.button(QtWidgets.QDialogButtonBox.Close).setText("Fechar")

        layout.addWidget(close_box)



        # Conexões

        self.create_btn.clicked.connect(self.create_guides)

        self.update_btn.clicked.connect(self.update_all)

        self.toggle_btn.clicked.connect(self.toggle_all)

        self.delete_btn.clicked.connect(self.delete_all)

        self.btn_create_sketch.clicked.connect(self.create_or_open_sketch)

        close_box.rejected.connect(self.reject)



        self.mode.currentIndexChanged.connect(self.update_ui)

        self.axis.currentIndexChanged.connect(self.update_ui)

        self.offset.valueChanged.connect(self.update_ui)

        self.auto_len.toggled.connect(self.toggle_auto_len)

        self.length.valueChanged.connect(self.update_ui)



        self.update_ui()



    def toggle_auto_len(self, checked):

        self.length.setEnabled(not checked)

        self.update_ui()



    def _get_computed_length(self):

        if self.auto_len.isChecked():

            try:

                bb = self.doc.BoundBox

                diag = bb.DiagonalLength

                if diag > 0: return min(max(diag * 3.0, 1000.0), 1000000.0)

            except: pass

            return 15000.0

        return min(max(self.length.value(), 1.0), 1000000.0)



    def update_ui(self, *_):

        idx = self.mode.currentIndex()

        self.axis.setEnabled(idx in [0, 1])

        self.offset.setEnabled(idx == 0)



        try:

            items = selected_items()

            sel_text = " | ".join(f"{o.Label}.{s}" for o, s, _ in items) if items else "Nenhuma"



            # Detecta se a guia selecionada já possui um sketch prévio

            if items and hasattr(items[0][0], "UhrySketcher") and items[0][0].UhrySketcher:

                self.btn_create_sketch.setText(f"📂 Abrir Sketcher Existente ({items[0][0].UhrySketcher.Label})")

            else:

                self.btn_create_sketch.setText("✏️ Criar Novo Sketcher na Guia Selecionada")

        except:

            items = []

            sel_text = "Nenhuma"

            self.btn_create_sketch.setText("✏️ Abrir / Criar Sketcher na Guia Selecionada")



        self.selection_info.setText(f"<b>Seleção Atual:</b> {sel_text}")



        precalc_text = ""

        comp = self._get_computed_length()



        if items:

            if idx == 0 and len(items) == 1:

                try:

                    _, _, mid, _ = straight_edge_data(items[0][0], items[0][1], items[0][2])

                    ax = self.axis.currentText()

                    off = self.offset.value()

                    n_mid = mid + (get_axis(ax) * off)

                    precalc_text = f"Centro da aresta: ({mid.x:.1f}, {mid.y:.1f}, {mid.z:.1f})\nDeslocamento: {off:+.1f} mm em {ax}\nNovo centro: ({n_mid.x:.1f}, {n_mid.y:.1f}, {n_mid.z:.1f})"

                except Exception:

                    precalc_text = "Aresta inválida para cálculo."

            elif idx in [1, 2] and len(items) == 1:

                try:

                    p = vertex_point(items[0][0], items[0][1], items[0][2])

                    precalc_text = f"Ponto base: ({p.x:.1f}, {p.y:.1f}, {p.z:.1f})"

                except Exception:

                    precalc_text = "Vértice inválido para cálculo."



        precalc_text += f"\nComprimento final da linha: {comp:,.1f} mm".replace(',', 'X').replace('.', ',').replace('X', '.')

        self.precalc_lbl.setText(precalc_text.strip())



    def create_guides(self):

        self.update_ui()

        self.doc.openTransaction("Criar Linha Guia")

        try:

            idx = self.mode.currentIndex()

            l = self._get_computed_length()

            if idx == 0: created = [create_parallel_guide(self.doc, self.axis.currentText(), self.offset.value(), l)]

            elif idx == 1: created = [create_axis_guide(self.doc, self.axis.currentText(), l)]

            elif idx == 2: created = create_three_axis_guides(self.doc, l)

            else: created = [create_middle_guide(self.doc, l)]



            self.doc.recompute()

            self.doc.commitTransaction()

            Gui.Selection.clearSelection()

            for obj in created: Gui.Selection.addSelection(obj)

            self.accept()

        except Exception as e:

            self.doc.abortTransaction()

            self.doc.recompute()

            QtWidgets.QMessageBox.critical(self, "Erro", str(e))



    def create_or_open_sketch(self):

        try:

            plane = self.sketch_plane.currentText()

            imp = self.sketch_import.isChecked()

            create_or_open_sketch_on_guide(self.doc, plane, import_external=imp, open_edit=True)

            self.accept()

        except Exception as e:

            QtWidgets.QMessageBox.critical(self, "Erro no Sketcher", str(e))



    def update_all(self):

        try:

            upd, errs = update_all_guides(self.doc)

            msg = f"{upd} guia(s) atualizada(s)."

            if errs: msg += "\nErros:\n- " + "\n- ".join(errs)

            QtWidgets.QMessageBox.information(self, "Atualizar", msg)

        except Exception as e: QtWidgets.QMessageBox.critical(self, "Erro", str(e))



    def toggle_all(self):

        c, v = toggle_all_guides(self.doc)

        self.doc.recompute()

        QtWidgets.QMessageBox.information(self, "Guias", f"{c} guias {'visíveis' if v else 'ocultas'}." if c else "Sem guias.")



    def delete_all(self):

        guides = all_guides(self.doc)

        if not guides: return

        if QtWidgets.QMessageBox.question(self, "Apagar", f"Apagar {len(guides)} guias?", QtWidgets.QMessageBox.Yes|QtWidgets.QMessageBox.No) == QtWidgets.QMessageBox.Yes:

            try:

                count = delete_all_guides(self.doc)

                QtWidgets.QMessageBox.information(self, "Apagadas", f"{count} guias apagadas.")

            except Exception as e:

                QtWidgets.QMessageBox.critical(self, "Erro", str(e))



def run():
    global _ACTIVE_DIRECT_TOOL

    if not App.ActiveDocument:
        QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "Aviso", "Abra um documento do FreeCAD antes.")
        return

    # Se uma operação direta anterior ainda estiver viva, encerra antes de iniciar outra.
    if _ACTIVE_DIRECT_TOOL is not None:
        try:
            _ACTIVE_DIRECT_TOOL.cancel()
        except Exception:
            _ACTIVE_DIRECT_TOOL = None

    items = selected_items()

    # Qualquer aresta reta selecionada inicia o modo direto no 3D, inclusive uma Linha Guia.
    if len(items) == 1:
        obj, subname, shape = items[0]
        if getattr(shape, "ShapeType", "") == "Edge":
            _ACTIVE_DIRECT_TOOL = DirectGuideTool(
                App.ActiveDocument, obj, subname, shape
            )
            return

    # Sem uma aresta simples selecionada, mantém a janela avançada existente.
    # A função de Sketch permanece preservada no código para ser separada depois
    # em uma ferramenta própria.
    dlg = GuideDialog(App.ActiveDocument)
    (dlg.exec if hasattr(dlg, "exec") else dlg.exec_)()



