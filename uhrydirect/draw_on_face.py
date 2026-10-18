# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui
import Part

try:
    from PySide2 import QtCore
except ImportError:
    try:
        from PySide6 import QtCore
    except ImportError:
        from PySide import QtCore


TOL = 1.0e-7
_active_session = None


def placement_global(obj):
    """Retorna o Placement global de um objeto."""
    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception:
        try:
            return App.Placement(obj.Placement)
        except Exception:
            return App.Placement()


def encontrar_body(obj):
    """Localiza o PartDesign::Body mais próximo que contém o objeto."""
    if obj is None:
        return None

    if getattr(obj, "TypeId", "") == "PartDesign::Body":
        return obj

    visitados = set()
    fila = [obj]

    while fila:
        atual = fila.pop(0)
        chave = getattr(atual, "Name", str(id(atual)))
        if chave in visitados:
            continue
        visitados.add(chave)

        for pai in getattr(atual, "InList", []):
            if getattr(pai, "TypeId", "") == "PartDesign::Body":
                return pai
            fila.append(pai)

    return None


def encontrar_part_pai(obj):
    """Procura o App::Part mais próximo que contém o objeto."""
    if obj is None:
        return None

    if getattr(obj, "TypeId", "") == "App::Part":
        return obj

    visitados = set()
    fila = [obj]

    while fila:
        atual = fila.pop(0)
        chave = getattr(atual, "Name", str(id(atual)))
        if chave in visitados:
            continue
        visitados.add(chave)

        for pai in getattr(atual, "InList", []):
            if getattr(pai, "TypeId", "") == "App::Part":
                return pai
            fila.append(pai)

    return None


def face_global_da_selecao(sel):
    """Obtém uma cópia da face selecionada em coordenadas globais."""
    nome_face = sel.SubElementNames[0]

    try:
        if len(sel.SubObjects) == 1 and sel.SubObjects[0] is not None:
            face = sel.SubObjects[0].copy()

            pl_global_obj = placement_global(sel.Object)
            pl_local_obj = App.Placement(
                getattr(sel.Object, "Placement", App.Placement())
            )
            pl_pais = pl_global_obj * pl_local_obj.inverse()

            face.Placement = pl_pais * face.Placement
            return face
    except Exception:
        pass

    face = sel.Object.Shape.getElement(nome_face).copy()
    face.Placement = placement_global(sel.Object) * face.Placement
    return face


def normal_face(face):
    """Calcula uma normal estável no centro paramétrico da face."""
    umin, umax, vmin, vmax = face.ParameterRange
    u = (umin + umax) / 2.0
    v = (vmin + vmax) / 2.0

    normal = App.Vector(face.normalAt(u, v))

    if normal.Length < TOL:
        raise RuntimeError("Não consegui determinar a normal da face.")

    normal.normalize()
    return normal


def frame_face(face):
    """Cria um frame global para o novo Body/Sketch."""
    normal = normal_face(face)

    global_z = App.Vector(0, 0, 1)
    ydir = global_z - normal * global_z.dot(normal)

    if ydir.Length < TOL:
        global_y = App.Vector(0, 1, 0)
        ydir = global_y - normal * global_y.dot(normal)

    if ydir.Length < TOL:
        raise RuntimeError("Não consegui definir a orientação do Sketch.")

    ydir.normalize()

    xdir = ydir.cross(normal)
    if xdir.Length < TOL:
        raise RuntimeError("Não consegui definir o eixo X do Sketch.")
    xdir.normalize()

    ydir = normal.cross(xdir)
    ydir.normalize()

    vertices = [App.Vector(v.Point) for v in face.Vertexes]

    if not vertices:
        origem = App.Vector(face.CenterOfMass)
    else:
        xs = [p.dot(xdir) for p in vertices]
        ys = [p.dot(ydir) for p in vertices]

        xmin = min(xs)
        ymin = min(ys)

        origem = min(
            vertices,
            key=lambda p: (
                (p.dot(xdir) - xmin) ** 2
                + (p.dot(ydir) - ymin) ** 2
            ),
        )

    rot = App.Rotation(xdir, ydir, normal, "ZXY")
    return App.Placement(origem, rot), normal


def _label_unico(doc, base):
    existentes = {
        str(getattr(obj, "Label", ""))
        for obj in getattr(doc, "Objects", [])
    }

    if base not in existentes:
        return base

    indice = 2
    while True:
        candidato = "{}_{:02d}".format(base, indice)
        if candidato not in existentes:
            return candidato
        indice += 1


def criar_body_e_sketch(doc, obj_ref, placement_desejado):
    """Cria uma NOVA peça independente no mesmo App::Part, quando houver."""
    part_pai = encontrar_part_pai(obj_ref)

    body = doc.addObject("PartDesign::Body", "Body")
    body.Label = _label_unico(doc, "Nova_Peca")

    if part_pai is not None:
        try:
            part_pai.addObject(body)
            pl_part_global = placement_global(part_pai)
            body.Placement = pl_part_global.inverse() * placement_desejado
            destino = part_pai.Label
        except Exception:
            body.Placement = placement_desejado
            destino = "Documento"
    else:
        body.Placement = placement_desejado
        destino = "Documento"

    sketch = body.newObject("Sketcher::SketchObject", "Sketch")
    sketch.Label = "Sketch"
    sketch.MapMode = "Deactivated"
    sketch.Placement = App.Placement()

    return body, sketch, destino


def _camera_direction():
    """Direção da câmera para dentro da cena, em coordenadas globais."""
    view = Gui.activeDocument().activeView()
    rot = view.getCameraOrientation()

    try:
        direcao = rot.multVec(App.Vector(0, 0, -1))
    except Exception:
        direcao = App.Rotation(rot).multVec(App.Vector(0, 0, -1))

    if direcao.Length < TOL:
        return None

    direcao.normalize()
    return direcao


def _global_shape(obj):
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

    try:
        shape = obj.Shape
        if shape is not None and not shape.isNull():
            result = shape.copy()
            result.Placement = placement_global(obj) * result.Placement
            return result
    except Exception:
        pass

    return None


def _bbox_corners(bb):
    return [
        App.Vector(x, y, z)
        for x in (bb.XMin, bb.XMax)
        for y in (bb.YMin, bb.YMax)
        for z in (bb.ZMin, bb.ZMax)
    ]


def _is_guide(obj):
    props = set(getattr(obj, "PropertiesList", []))
    for name in ("DirectGuiaReferencia", "UhryGuiaReferencia"):
        if name in props:
            try:
                if bool(getattr(obj, name)):
                    return True
            except Exception:
                pass
    return False


def ocultar_objetos_na_frente(doc, face_global, obj_ref):
    """Oculta temporariamente sólidos entre a câmera e o plano selecionado."""
    direcao = _camera_direction()
    if direcao is None:
        return []

    ponto_plano = App.Vector(face_global.CenterOfMass)
    profundidade_plano = ponto_plano.dot(direcao)

    body_ref = encontrar_body(obj_ref)
    preservados = {
        getattr(obj_ref, "Name", ""),
        getattr(body_ref, "Name", ""),
    }

    ocultados = []

    for obj in getattr(doc, "Objects", []):
        nome = getattr(obj, "Name", "")
        if not nome or nome in preservados:
            continue

        view_obj = getattr(obj, "ViewObject", None)
        if view_obj is None:
            continue

        try:
            if not bool(view_obj.Visibility):
                continue
        except Exception:
            continue

        tipo = getattr(obj, "TypeId", "")
        if tipo == "Sketcher::SketchObject":
            continue
        if _is_guide(obj):
            continue

        shape = _global_shape(obj)
        if shape is None:
            continue

        try:
            if len(shape.Faces) == 0 and len(shape.Solids) == 0:
                continue
        except Exception:
            continue

        bb = shape.BoundBox
        centro_depth = App.Vector(bb.Center).dot(direcao)

        # A direção cresce da câmera para o interior da cena. Logo, centro com
        # profundidade menor que a face está visualmente na frente dela.
        if centro_depth < profundidade_plano - 0.01:
            try:
                view_obj.Visibility = False
                ocultados.append(nome)
            except Exception:
                pass

    return ocultados



def _local_point_from_global(point, sketch_global_placement):
    inv = sketch_global_placement.inverse()
    local = inv.multVec(App.Vector(point))
    return App.Vector(float(local.x), float(local.y), 0.0)


def _add_construction_segment(sketch, p1, p2):
    if (p2 - p1).Length < 1.0e-6:
        return 0
    sketch.addGeometry(Part.LineSegment(p1, p2), True)
    return 1


def adicionar_referencias_construcao(sketch, face_global, sketch_global_placement):
    """Copia o contorno da face para o Sketch como geometria de construção.

    Não usa External Geometry entre Bodies, porque o PartDesign bloqueia links
    diretos desse tipo. As referências são cópias estáticas no sistema local do
    novo Sketch, preservando a independência entre os Bodies.
    """
    total = 0

    for edge in face_global.Edges:
        try:
            verts = list(edge.Vertexes)
        except Exception:
            verts = []

        curve_name = ""
        try:
            curve_name = type(edge.Curve).__name__.lower()
        except Exception:
            pass

        # A maioria das peças desta ferramenta é prismática: preserva linhas
        # retas exatamente. Para curvas, aproxima com pequenos segmentos apenas
        # como referência visual/de projeto.
        if len(verts) >= 2 and "line" in curve_name:
            p1 = _local_point_from_global(verts[0].Point, sketch_global_placement)
            p2 = _local_point_from_global(verts[-1].Point, sketch_global_placement)
            total += _add_construction_segment(sketch, p1, p2)
            continue

        try:
            pts = edge.discretize(Number=24)
        except Exception:
            pts = []

        if len(pts) < 2 and len(verts) >= 2:
            pts = [verts[0].Point, verts[-1].Point]

        local_pts = [
            _local_point_from_global(pt, sketch_global_placement)
            for pt in pts
        ]

        for a, b in zip(local_pts, local_pts[1:]):
            total += _add_construction_segment(sketch, a, b)

    return total


def _profile_geometry_count(sketch):
    """Conta apenas geometrias normais; referências de construção não contam."""
    try:
        total = int(sketch.GeometryCount)
    except Exception:
        try:
            total = len(sketch.Geometry)
        except Exception:
            return 0

    normal = 0
    for i in range(total):
        try:
            if not bool(sketch.getConstruction(i)):
                normal += 1
        except Exception:
            # Fallback conservador para builds sem getConstruction.
            normal += 1
    return normal


def _geometry_count(sketch):
    try:
        return int(sketch.GeometryCount)
    except Exception:
        pass

    try:
        return len(sketch.Geometry)
    except Exception:
        return 0


def _objeto_em_edicao(gui_doc):
    try:
        vp = gui_doc.getInEdit()
    except Exception:
        return None

    if vp is None:
        return None

    obj = getattr(vp, "Object", None)
    if obj is not None:
        return obj

    if isinstance(vp, (list, tuple)) and vp:
        primeiro = vp[0]
        return getattr(primeiro, "Object", primeiro)

    return None


class _SketchPadSession:
    """Restaura a cena ao sair do Sketch e abre o Pad automaticamente."""

    def __init__(self, doc_name, body_name, sketch_name, hidden_names):
        self.doc_name = doc_name
        self.body_name = body_name
        self.sketch_name = sketch_name
        self.hidden_names = list(hidden_names)
        self.finished = False

        self.timer = QtCore.QTimer(Gui.getMainWindow())
        self.timer.setInterval(180)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def stop(self):
        try:
            self.timer.stop()
        except Exception:
            pass

    def restore_visibility(self):
        try:
            doc = App.getDocument(self.doc_name)
        except Exception:
            doc = None

        if doc is None:
            return

        for nome in self.hidden_names:
            obj = doc.getObject(nome)
            if obj is None:
                continue
            try:
                obj.ViewObject.Visibility = True
            except Exception:
                pass

    def cancel(self):
        global _active_session

        if self.finished:
            return

        self.finished = True
        self.stop()
        self.restore_visibility()

        if _active_session is self:
            _active_session = None

    def _poll(self):
        if self.finished:
            return

        try:
            doc = App.getDocument(self.doc_name)
            gui_doc = Gui.getDocument(self.doc_name)
        except Exception:
            self.cancel()
            return

        if doc is None or gui_doc is None:
            self.cancel()
            return

        sketch = doc.getObject(self.sketch_name)
        body = doc.getObject(self.body_name)

        if sketch is None or body is None:
            self.cancel()
            return

        edit_obj = _objeto_em_edicao(gui_doc)

        if edit_obj is not None and getattr(edit_obj, "Name", "") == self.sketch_name:
            return

        # O Sketch foi fechado.
        self.finished = True
        self.stop()
        self.restore_visibility()

        global _active_session
        if _active_session is self:
            _active_session = None

        if _profile_geometry_count(sketch) <= 0:
            App.Console.PrintMessage(
                "[Direct - Desenhar na Face] Sketch fechado sem perfil normal; "
                "referências de construção não geram Pad.\n"
            )
            return

        def abrir_pad():
            try:
                doc2 = App.getDocument(self.doc_name)
                body2 = doc2.getObject(self.body_name)
                sketch2 = doc2.getObject(self.sketch_name)

                if body2 is None or sketch2 is None:
                    return

                Gui.getDocument(self.doc_name).ActiveView.setActiveObject(
                    "pdbody",
                    body2,
                )

                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(sketch2)
                Gui.runCommand("PartDesign_Pad", 0)

                App.Console.PrintMessage(
                    "[Direct - Desenhar na Face] Pad aberto para configuração.\n"
                )
            except Exception as erro:
                App.Console.PrintError(
                    "[Direct - Desenhar na Face] Não foi possível abrir o Pad: {}\n".format(
                        erro
                    )
                )

        QtCore.QTimer.singleShot(120, abrir_pad)


def run():
    global _active_session

    doc = App.ActiveDocument

    if doc is None:
        App.Console.PrintError("Direct — nenhum documento aberto.\n")
        return False

    selecoes = Gui.Selection.getSelectionEx()

    if len(selecoes) != 1:
        App.Console.PrintError("Direct — selecione exatamente UMA face.\n")
        return False

    sel = selecoes[0]

    if len(sel.SubElementNames) != 1:
        App.Console.PrintError("Direct — selecione exatamente UMA face.\n")
        return False

    nome = sel.SubElementNames[0]

    if not nome.split(".")[-1].startswith("Face"):
        App.Console.PrintError("Direct — a seleção precisa ser uma FACE.\n")
        return False

    if _active_session is not None:
        try:
            _active_session.cancel()
        except Exception:
            pass
        _active_session = None

    ocultados = []

    try:
        face_global = face_global_da_selecao(sel)
        placement_desejado, normal = frame_face(face_global)

        ocultados = ocultar_objetos_na_frente(
            doc,
            face_global,
            sel.Object,
        )

        doc.openTransaction("Direct - Desenhar na Face")

        try:
            body, sketch, destino = criar_body_e_sketch(
                doc,
                sel.Object,
                placement_desejado,
            )

            referencias_construcao = adicionar_referencias_construcao(
                sketch,
                face_global,
                placement_desejado,
            )

            doc.recompute()
            doc.commitTransaction()

        except Exception:
            try:
                doc.abortTransaction()
                doc.recompute()
            except Exception:
                pass

            for nome_obj in ocultados:
                obj = doc.getObject(nome_obj)
                if obj is not None:
                    try:
                        obj.ViewObject.Visibility = True
                    except Exception:
                        pass
            raise

        try:
            Gui.ActiveDocument.ActiveView.setActiveObject("pdbody", body)
        except Exception:
            pass

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(sketch)

        resultado_edit = Gui.getDocument(doc.Name).setEdit(sketch.Name)
        if resultado_edit is False:
            raise RuntimeError("Não foi possível abrir o Sketch para edição.")

        _active_session = _SketchPadSession(
            doc.Name,
            body.Name,
            sketch.Name,
            ocultados,
        )

        App.Console.PrintMessage(
            "\n"
            "====================================\n"
            "DIRECT — DESENHAR NA FACE\n"
            "====================================\n"
            "Modo: NOVO Body independente\n"
            "Body: {}\n"
            "Destino: {}\n"
            "Sketch: {}\n"
            "Face origem: {}.{}\n"
            "MapMode: Deactivated\n"
            "Dependência topológica: NÃO\n"
            "Origem: canto inferior esquerdo da face\n"
            "Normal global: {}\n"
            "Referências da face: {} geometria(s) de construção\n"
            "Vínculo externo entre Bodies: NÃO (cópia estática)\n"
            "Objetos temporariamente ocultos: {}\n"
            "Ao fechar o Sketch: restaura a cena e abre Pad.\n"
            "====================================\n".format(
                body.Label,
                destino,
                sketch.Label,
                sel.Object.Name,
                nome,
                normal,
                referencias_construcao,
                len(ocultados),
            )
        )

        return True

    except Exception as erro:
        # Se a falha ocorrer depois de esconder a cena, restaura os objetos.
        for nome_obj in ocultados:
            obj = doc.getObject(nome_obj)
            if obj is not None:
                try:
                    obj.ViewObject.Visibility = True
                except Exception:
                    pass

        App.Console.PrintError(
            "Direct — erro ao criar Sketch na face:\n{}\n".format(erro)
        )
        return False
