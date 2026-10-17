# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui


def placement_global(obj):
    """
    Retorna o Placement global de um objeto.
    """
    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception:
        try:
            return App.Placement(obj.Placement)
        except Exception:
            return App.Placement()


def encontrar_body(obj):
    """
    Localiza o PartDesign::Body mais próximo que contém o objeto selecionado.
    """
    if obj is None:
        return None

    if getattr(obj, "TypeId", "") == "PartDesign::Body":
        return obj

    for nome_metodo in ("getParentGeoFeatureGroup", "getParentGroup"):
        metodo = getattr(obj, nome_metodo, None)
        if callable(metodo):
            try:
                pai = metodo()
                if pai is not None and getattr(pai, "TypeId", "") == "PartDesign::Body":
                    return pai
            except Exception:
                pass

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
    """
    Procura o App::Part mais próximo que contém o objeto selecionado.
    """
    if obj is None:
        return None

    if getattr(obj, "TypeId", "") == "App::Part":
        return obj

    for nome_metodo in ("getParentGeoFeatureGroup", "getParentGroup"):
        metodo = getattr(obj, nome_metodo, None)
        if callable(metodo):
            try:
                pai = metodo()
                if pai is not None and getattr(pai, "TypeId", "") == "App::Part":
                    return pai
            except Exception:
                pass

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
    """
    Obtém uma cópia da face selecionada já em coordenadas globais.
    """
    nome_face = sel.SubElementNames[0]

    try:
        if len(sel.SubObjects) == 1 and sel.SubObjects[0] is not None:
            face = sel.SubObjects[0].copy()

            pl_global_obj = placement_global(sel.Object)
            pl_local_obj = App.Placement(getattr(sel.Object, "Placement", App.Placement()))
            pl_pais = pl_global_obj * pl_local_obj.inverse()

            face.Placement = pl_pais * face.Placement
            return face
    except Exception:
        pass

    face = sel.Object.Shape.getElement(nome_face).copy()
    face.Placement = placement_global(sel.Object) * face.Placement
    return face


def normal_face(face):
    """
    Calcula uma normal estável no centro paramétrico da face.
    """
    umin, umax, vmin, vmax = face.ParameterRange
    u = (umin + umax) / 2.0
    v = (vmin + vmax) / 2.0

    normal = face.normalAt(u, v)

    if normal.Length < 0.000001:
        raise RuntimeError("Não consegui determinar a normal da face.")

    normal.normalize()
    return normal


def frame_face(face):
    """
    Cria um referencial global para o novo Sketch.

    Regra de orientação:
    - em faces verticais, Y do Sketch tenta acompanhar Z global;
    - em faces horizontais, Y do Sketch tenta acompanhar Y global;
    - origem = canto inferior esquerdo da face nesse frame.
    """
    normal = normal_face(face)

    global_z = App.Vector(0, 0, 1)
    ydir = global_z - normal * global_z.dot(normal)

    if ydir.Length < 0.000001:
        global_y = App.Vector(0, 1, 0)
        ydir = global_y - normal * global_y.dot(normal)

    if ydir.Length < 0.000001:
        raise RuntimeError("Não consegui definir a orientação do Sketch.")

    ydir.normalize()

    xdir = ydir.cross(normal)
    if xdir.Length < 0.000001:
        raise RuntimeError("Não consegui definir o eixo X do Sketch.")
    xdir.normalize()

    ydir = normal.cross(xdir)
    ydir.normalize()

    vertices = [v.Point for v in face.Vertexes]

    if not vertices:
        origem = face.CenterOfMass
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


def nome_label_sketch(container, base="Sketch_Face"):
    """
    Gera um Label legível e sem conflito visível.
    """
    existentes = []

    try:
        if container is not None and hasattr(container, "Group"):
            existentes = [obj.Label for obj in container.Group if hasattr(obj, "Label")]
        else:
            existentes = [obj.Label for obj in App.ActiveDocument.Objects if hasattr(obj, "Label")]
    except Exception:
        existentes = []

    if base not in existentes:
        return base

    indice = 2
    while True:
        nome = "{}_{:02d}".format(base, indice)
        if nome not in existentes:
            return nome
        indice += 1


def criar_sketch_no_body(doc, body, placement_desejado):
    """
    Cria o Sketch dentro de um PartDesign::Body.
    """
    pl_body_global = placement_global(body)
    placement_local = pl_body_global.inverse() * placement_desejado

    sketch = body.newObject("Sketcher::SketchObject", "Sketch")
    sketch.Label = nome_label_sketch(body, "Sketch_Face")
    sketch.MapMode = "Deactivated"
    sketch.Placement = placement_local

    # Mantém a continuação do histórico dentro do MESMO Body.

    return sketch, "Body existente", body.Label


def criar_sketch_em_objeto_geral(doc, obj_ref, placement_desejado):
    """
    Cria um Sketch independente para peças que NÃO são PartDesign Body.

    Se houver um App::Part pai, o Sketch entra nele.
    Senão, fica solto na raiz do documento.
    """
    part_pai = encontrar_part_pai(obj_ref)

    sketch = doc.addObject("Sketcher::SketchObject", "Sketch_Face")

    if part_pai is not None:
        try:
            part_pai.addObject(sketch)
        except Exception:
            # Se não aceitar por qualquer motivo, o Sketch fica na raiz.
            part_pai = None

    sketch.Label = nome_label_sketch(part_pai, "Sketch_Face")
    sketch.MapMode = "Deactivated"

    if part_pai is not None:
        pl_part_global = placement_global(part_pai)
        sketch.Placement = pl_part_global.inverse() * placement_desejado
        return sketch, "Sketch independente (sem criar Body)", part_pai.Label

    sketch.Placement = placement_desejado
    return sketch, "Sketch independente (sem criar Body)", "Documento"


def run():
    doc = App.ActiveDocument

    if doc is None:
        App.Console.PrintError(
            "Direct — nenhum documento aberto.\n"
        )
        return False

    selecoes = Gui.Selection.getSelectionEx()

    if len(selecoes) != 1:
        App.Console.PrintError(
            "Direct — selecione exatamente UMA face.\n"
        )
        return False

    sel = selecoes[0]

    if len(sel.SubElementNames) != 1:
        App.Console.PrintError(
            "Direct — selecione exatamente UMA face.\n"
        )
        return False

    nome = sel.SubElementNames[0]

    if not nome.split(".")[-1].startswith("Face"):
        App.Console.PrintError(
            "Direct — a seleção precisa ser uma FACE.\n"
        )
        return False

    try:
        face_global = face_global_da_selecao(sel)
        placement_desejado, normal = frame_face(face_global)

        body = encontrar_body(sel.Object)

        doc.openTransaction("Direct - Desenhar na Face")

        try:
            if body is not None:
                sketch, modo, destino = criar_sketch_no_body(
                    doc, body, placement_desejado
                )
            else:
                sketch, modo, destino = criar_sketch_em_objeto_geral(
                    doc, sel.Object, placement_desejado
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

        Gui.Selection.clearSelection()
        Gui.Selection.addSelection(sketch)
        Gui.activeDocument().setEdit(sketch.Name)

        App.Console.PrintMessage(
            "\n"
            "====================================\n"
            "DIRECT — DESENHAR NA FACE\n"
            "====================================\n"
            "Modo: {}\n"
            "Destino: {}\n"
            "Sketch: {}\n"
            "Face origem: {}.{}\n"
            "MapMode: Deactivated\n"
            "Dependência topológica: NÃO\n"
            "Origem: canto inferior esquerdo da face\n"
            "Normal global: {}\n"
            "====================================\n".format(
                modo,
                destino,
                sketch.Label,
                sel.Object.Name,
                nome,
                normal,
            )
        )

        return True

    except Exception as erro:
        App.Console.PrintError(
            "Direct — erro ao criar Sketch na face:\n"
            "{}\n".format(erro)
        )
        return False
