# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui
import Part

TOL = 1.0e-7


def normalizar_selecoes(valor):
    saida = []

    def visitar(item):
        if isinstance(item, (list, tuple)):
            for sub in item:
                visitar(sub)
        elif item is not None:
            saida.append(item)

    visitar(valor)
    return saida


def placement_global(obj):
    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception:
        try:
            return App.Placement(obj.Placement)
        except Exception:
            return App.Placement()


def encontrar_body(obj):
    """Encontra o PartDesign::Body que contém o objeto selecionado."""
    if obj is None:
        return None

    if getattr(obj, 'TypeId', '') == 'PartDesign::Body':
        return obj

    for nome_metodo in ('getParentGeoFeatureGroup', 'getParentGroup'):
        metodo = getattr(obj, nome_metodo, None)
        if callable(metodo):
            try:
                pai = metodo()
                if pai is not None and getattr(pai, 'TypeId', '') == 'PartDesign::Body':
                    return pai
            except Exception:
                pass

    visitados = set()
    fila = [obj]

    while fila:
        atual = fila.pop(0)
        chave = getattr(atual, 'Name', str(id(atual)))
        if chave in visitados:
            continue
        visitados.add(chave)

        for pai in getattr(atual, 'InList', []):
            if getattr(pai, 'TypeId', '') == 'PartDesign::Body':
                return pai
            fila.append(pai)

    return None


def encontrar_part_pai(obj):
    if obj is None:
        return None

    if getattr(obj, 'TypeId', '') == 'App::Part':
        return obj

    visitados = set()
    fila = [obj]

    while fila:
        atual = fila.pop(0)
        chave = getattr(atual, 'Name', str(id(atual)))
        if chave in visitados:
            continue
        visitados.add(chave)

        for pai in getattr(atual, 'InList', []):
            if getattr(pai, 'TypeId', '') == 'App::Part':
                return pai
            fila.append(pai)

    return None


def tem_shape_util(obj):
    shape = getattr(obj, 'Shape', None)
    if shape is None:
        return False
    try:
        return not shape.isNull() and len(shape.Faces) > 0
    except Exception:
        return False


def copiar_aparencia(origem, destino):
    for prop in (
        'ShapeColor',
        'LineColor',
        'PointColor',
        'Transparency',
        'DisplayMode',
    ):
        try:
            setattr(destino.ViewObject, prop, getattr(origem.ViewObject, prop))
        except Exception:
            pass


def face_global_da_selecao(sel):
    """Obtém a face selecionada em coordenadas globais."""
    nome_face = sel.SubElementNames[0]

    try:
        if len(sel.SubObjects) == 1 and sel.SubObjects[0] is not None:
            face = sel.SubObjects[0].copy()
            pl_global_obj = placement_global(sel.Object)
            pl_local_obj = App.Placement(
                getattr(sel.Object, 'Placement', App.Placement())
            )
            pl_pais = pl_global_obj * pl_local_obj.inverse()
            face.Placement = pl_pais * face.Placement
            return face
    except Exception:
        pass

    face = sel.Object.Shape.getElement(nome_face).copy()
    face.Placement = placement_global(sel.Object) * face.Placement
    return face


def eh_face_plana(face):
    try:
        if isinstance(face.Surface, Part.Plane):
            return True
    except Exception:
        pass

    try:
        return 'plane' in type(face.Surface).__name__.lower()
    except Exception:
        return False


def normal_face(face):
    umin, umax, vmin, vmax = face.ParameterRange
    normal = App.Vector(face.normalAt((umin + umax) * 0.5, (vmin + vmax) * 0.5))
    if normal.Length < TOL:
        raise RuntimeError('Não consegui determinar a normal da face.')
    normal.normalize()
    return normal


def _vetor_camera(rot, vetor_local):
    try:
        return rot.multVec(vetor_local)
    except Exception:
        return App.Rotation(rot).multVec(vetor_local)


def frame_local_da_face(face):
    """Mantém direita/cima da vista como X/Y do Sketch."""
    normal = normal_face(face)
    view = Gui.activeDocument().activeView()
    cam_rot = view.getCameraOrientation()

    direita_tela = _vetor_camera(cam_rot, App.Vector(1, 0, 0))
    cima_tela = _vetor_camera(cam_rot, App.Vector(0, 1, 0))
    direcao_visao = _vetor_camera(cam_rot, App.Vector(0, 0, -1))

    for vetor in (direita_tela, cima_tela, direcao_visao):
        if vetor.Length > TOL:
            vetor.normalize()

    zdir = App.Vector(normal)
    zdir.normalize()
    if zdir.dot(direcao_visao) > 0:
        zdir = -zdir

    xdir = direita_tela - zdir * direita_tela.dot(zdir)
    if xdir.Length < TOL:
        ydir = cima_tela - zdir * cima_tela.dot(zdir)
        if ydir.Length < TOL:
            raise RuntimeError('A vista atual está degenerada para esta face.')
        ydir.normalize()
        xdir = ydir.cross(zdir)
    xdir.normalize()

    ydir = zdir.cross(xdir)
    if ydir.Length < TOL:
        raise RuntimeError('Não consegui determinar os eixos locais da face.')
    ydir.normalize()

    if ydir.dot(cima_tela) < 0:
        zdir = -zdir
        ydir = zdir.cross(xdir)
        ydir.normalize()

    vertices = [App.Vector(v.Point) for v in face.Vertexes]
    if not vertices:
        origem = App.Vector(face.CenterOfMass)
    else:
        ref = vertices[0]
        coords = []
        for p in vertices:
            rel = p - ref
            coords.append((p, rel.dot(xdir), rel.dot(ydir)))
        xmin = min(item[1] for item in coords)
        ymin = min(item[2] for item in coords)
        origem = min(
            coords,
            key=lambda item: (item[1] - xmin) ** 2 + (item[2] - ymin) ** 2,
        )[0]

    rot = App.Rotation(xdir, ydir, zdir, 'ZXY')
    return App.Placement(origem, rot), zdir


def _local_point(point, sketch_global):
    local = sketch_global.inverse().multVec(App.Vector(point))
    return App.Vector(float(local.x), float(local.y), 0.0)


def _add_segment(sketch, p1, p2):
    if (p2 - p1).Length <= 1.0e-7:
        return 0
    sketch.addGeometry(Part.LineSegment(p1, p2), False)
    return 1


def _add_edge_as_profile(sketch, edge, sketch_global):
    """Copia uma aresta da face para o Sketch como geometria normal."""
    try:
        verts = list(edge.Vertexes)
    except Exception:
        verts = []

    curve_name = ''
    try:
        curve_name = type(edge.Curve).__name__.lower()
    except Exception:
        pass

    if len(verts) >= 2 and 'line' in curve_name:
        p1 = _local_point(verts[0].Point, sketch_global)
        p2 = _local_point(verts[-1].Point, sketch_global)
        return _add_segment(sketch, p1, p2)

    # Círculo completo.
    try:
        if edge.isClosed() and 'circle' in curve_name:
            center = _local_point(edge.Curve.Center, sketch_global)
            radius = float(edge.Curve.Radius)
            sketch.addGeometry(
                Part.Circle(center, App.Vector(0, 0, 1), radius),
                False,
            )
            return 1
    except Exception:
        pass

    # Arcos circulares e curvas suaves: primeiro tenta arco exato por 3 pontos.
    try:
        first = float(edge.FirstParameter)
        last = float(edge.LastParameter)
        mid = (first + last) * 0.5
        p1 = _local_point(edge.valueAt(first), sketch_global)
        pm = _local_point(edge.valueAt(mid), sketch_global)
        p2 = _local_point(edge.valueAt(last), sketch_global)
        if (p2 - p1).Length > 1.0e-7 and 'circle' in curve_name:
            sketch.addGeometry(Part.Arc(p1, pm, p2), False)
            return 1
    except Exception:
        pass

    # Fallback para curvas não suportadas diretamente: aproximação segmentada.
    try:
        pts = edge.discretize(Number=48)
    except Exception:
        pts = []

    if len(pts) < 2 and len(verts) >= 2:
        pts = [verts[0].Point, verts[-1].Point]

    local_pts = [_local_point(p, sketch_global) for p in pts]
    total = 0
    for a, b in zip(local_pts, local_pts[1:]):
        total += _add_segment(sketch, a, b)
    return total


def copiar_perfil_face(sketch, face_global, sketch_global):
    total = 0
    wires = list(getattr(face_global, 'Wires', []))
    if not wires:
        wires = [face_global]

    for wire in wires:
        edges = list(getattr(wire, 'Edges', []))
        for edge in edges:
            total += _add_edge_as_profile(sketch, edge, sketch_global)

    return total


def converter_para_body(doc, origem):
    """Converte um objeto solto para Body, preservando posição e aparência."""
    origem_label = getattr(origem, 'Label', origem.Name)
    origem_name = origem.Name
    origem_global = placement_global(origem)
    part_pai = encontrar_part_pai(origem)

    try:
        shape_local = origem.Shape.copy()
    except Exception as exc:
        raise RuntimeError('Não consegui copiar a Shape do objeto: {}'.format(exc))

    body = doc.addObject('PartDesign::Body', 'Body')
    body.Label = origem_label

    if part_pai is not None:
        part_pai.addObject(body)
        body.Placement = placement_global(part_pai).inverse() * origem_global
    else:
        body.Placement = origem_global

    base = body.newObject('PartDesign::Feature', 'Base_Direct')
    base.Label = 'Base_Direct'
    base.Shape = shape_local
    base.Placement = App.Placement()
    copiar_aparencia(origem, base)

    doc.recompute()
    doc.removeObject(origem_name)
    doc.recompute()

    return body, base


def criar_sketch_no_body(body, face_global, frame_global):
    doc = body.Document
    sketch = body.newObject('Sketcher::SketchObject', 'Sketch_ExtrudeFace')
    sketch.Label = 'Sketch_ExtrudeFace'
    sketch.MapMode = 'Deactivated'

    body_global = placement_global(body)
    sketch.Placement = body_global.inverse() * frame_global

    total = copiar_perfil_face(sketch, face_global, frame_global)
    if total <= 0:
        raise RuntimeError('Não foi possível copiar o contorno da face para o Sketch.')

    doc.recompute()
    return sketch, total


def abrir_pad(body, sketch):
    try:
        Gui.ActiveDocument.ActiveView.setActiveObject('pdbody', body)
    except Exception:
        pass

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(sketch)
    Gui.runCommand('PartDesign_Pad', 0)


def run():
    doc = App.ActiveDocument
    if doc is None:
        App.Console.PrintError('Direct — nenhum documento aberto.\n')
        return False

    selecoes = normalizar_selecoes(Gui.Selection.getSelectionEx())
    if len(selecoes) != 1:
        App.Console.PrintError('Direct — selecione exatamente UMA face plana.\n')
        return False

    sel = selecoes[0]
    if len(sel.SubElementNames) != 1:
        App.Console.PrintError('Direct — selecione exatamente UMA face.\n')
        return False

    nome_face = sel.SubElementNames[0]
    if not nome_face.split('.')[-1].startswith('Face'):
        App.Console.PrintError('Direct — a seleção precisa ser uma FACE.\n')
        return False

    origem = sel.Object
    if not tem_shape_util(origem):
        App.Console.PrintError('Direct — o objeto selecionado não possui sólido utilizável.\n')
        return False

    try:
        face_global = face_global_da_selecao(sel)
        if not eh_face_plana(face_global):
            App.Console.PrintError('Direct — a face selecionada precisa ser plana.\n')
            return False

        frame_global, normal = frame_local_da_face(face_global)
        body_existente = encontrar_body(origem)
        convertido = body_existente is None

        doc.openTransaction('Direct - Extrudar Face')
        try:
            if convertido:
                body, base = converter_para_body(doc, origem)
                modo = 'Objeto convertido para Body'
                base_info = base.Label
                removido = 'SIM'
            else:
                body = body_existente
                modo = 'Body existente'
                base_info = getattr(getattr(body, 'Tip', None), 'Label', '-')
                removido = 'NÃO'

            sketch, total = criar_sketch_no_body(
                body,
                face_global,
                frame_global,
            )

            doc.recompute()
            doc.commitTransaction()

        except Exception:
            try:
                doc.abortTransaction()
                doc.recompute()
            except Exception:
                pass
            raise

        abrir_pad(body, sketch)

        App.Console.PrintMessage(
            '\n'
            '====================================\n'
            'DIRECT — EXTRUDAR FACE\n'
            '====================================\n'
            'Modo: {}\n'
            'Face origem: {}.{}\n'
            'Body: {}\n'
            'Base/Tip anterior: {}\n'
            'Perfil copiado: {} elemento(s)\n'
            'MapMode: Deactivated\n'
            'Normal global: {}\n'
            'Objeto original removido: {}\n'
            'Pad aberto para configuração.\n'
            '====================================\n'.format(
                modo,
                getattr(origem, 'Label', origem.Name),
                nome_face,
                body.Label,
                base_info,
                total,
                normal,
                removido,
            )
        )
        return True

    except Exception as erro:
        App.Console.PrintError(
            'Direct — erro ao extrudar face:\n{}\n'.format(erro)
        )
        return False
