# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui


# ============================================================
# IDENTIFICACAO DE OBJETOS
# ============================================================

def eh_clone(obj):
    """Reconhece Draft Clone sem depender de um unico TypeId."""
    if obj is None:
        return False

    proxy = getattr(obj, "Proxy", None)
    tipo_proxy = str(getattr(proxy, "Type", "")).lower()

    if tipo_proxy == "clone" or tipo_proxy.endswith("clone"):
        return True

    propriedades = set(getattr(obj, "PropertiesList", []))
    return "Objects" in propriedades and "Scale" in propriedades


def eh_link(obj):
    if obj is None:
        return False
    return obj.TypeId == "App::Link" or obj.TypeId.startswith("App::Link")


def encontrar_body(obj):
    """Localiza o Body que realmente contem o objeto selecionado."""
    if obj is None:
        return None

    if obj.TypeId == "PartDesign::Body":
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
            if pai.TypeId == "PartDesign::Body":
                return pai
            fila.append(pai)

    return None


def objeto_movel(obj_selecionado):
    """
    Decide qual Placement deve ser alterado.

    - Recurso normal de Part Design: move o Body.
    - Clone dentro de Body: move o Body que o contem.
    - Clone solto: move o proprio Clone.
    - App::Link: move o proprio Link.
    """
    if obj_selecionado is None:
        return None

    if eh_link(obj_selecionado):
        return obj_selecionado

    if eh_clone(obj_selecionado):
        body = encontrar_body(obj_selecionado)
        return body if body is not None else obj_selecionado

    body = encontrar_body(obj_selecionado)
    if body is not None:
        return body

    if hasattr(obj_selecionado, "Placement"):
        return obj_selecionado

    return None


def encontrar_part_pai(obj):
    """Retorna o App::Part direto que define o sistema local do objeto."""
    for pai in getattr(obj, "InList", []):
        if pai.TypeId == "App::Part":
            return pai
    return None


# ============================================================
# PLACEMENTS
# ============================================================

def placement_global(obj):
    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception:
        return App.Placement(obj.Placement)


def definir_placement_global(obj, novo_global):
    """Converte o Placement global para o sistema local do App::Part pai."""
    part_pai = encontrar_part_pai(obj)

    if part_pai is None:
        obj.Placement = novo_global
    else:
        obj.Placement = (
            placement_global(part_pai).inverse()
            * novo_global
        )


# ============================================================
# GEOMETRIA SELECIONADA EM COORDENADAS GLOBAIS
# ============================================================

def nome_subelemento(sel):
    if len(sel.SubElementNames) != 1:
        raise Exception(
            "Selecione exatamente uma geometria em cada peça."
        )
    return sel.SubElementNames[0]


def subelemento_global(sel):
    """
    Pede ao FreeCAD o subelemento ja transformado.

    Importante para Draft Clone, App::Link e objetos dentro de App::Part.
    Evita aplicar o Placement duas vezes.
    """
    nome = nome_subelemento(sel)

    try:
        if len(sel.SubObjects) == 1 and sel.SubObjects[0] is not None:
            elemento = sel.SubObjects[0].copy()

            pl_global_obj = placement_global(sel.Object)
            pl_local_obj = App.Placement(sel.Object.Placement)
            pl_pais = pl_global_obj * pl_local_obj.inverse()

            elemento.Placement = (
                pl_pais * elemento.Placement
            )

            return elemento

    except Exception:
        pass

    try:
        elemento = sel.Object.getSubObject(
            nome,
            1,
            True,
        )

        if elemento is not None:
            return elemento

    except Exception:
        pass

    elemento = sel.Object.Shape.getElement(nome).copy()
    elemento.Placement = (
        placement_global(sel.Object)
        * elemento.Placement
    )

    return elemento


def ponto_clicado(sel):
    try:
        if len(sel.PickedPoints) > 0:
            return sel.PickedPoints[0]
    except Exception:
        pass

    return None


def canto_face(sel, face_global):
    clique = ponto_clicado(sel)
    pontos = [v.Point for v in face_global.Vertexes]

    if not pontos:
        raise Exception("A face nao possui vertices.")

    if clique is None:
        return pontos[0]

    return min(
        pontos,
        key=lambda p: (p - clique).Length,
    )


def normal_face_global(face_global):
    umin, umax, vmin, vmax = face_global.ParameterRange

    u = (umin + umax) / 2.0
    v = (vmin + vmax) / 2.0

    normal = face_global.normalAt(u, v)

    if normal.Length < 0.000001:
        raise Exception(
            "Nao consegui determinar a normal da face."
        )

    normal.normalize()

    return normal


def direcoes_no_canto(face_global, canto_global):
    direcoes = []
    tolerancia = 0.01

    for edge in face_global.Edges:
        verts = edge.Vertexes

        if len(verts) < 2:
            continue

        p1 = verts[0].Point
        p2 = verts[-1].Point

        if (p1 - canto_global).Length < tolerancia:
            d = p2 - p1

        elif (p2 - canto_global).Length < tolerancia:
            d = p1 - p2

        else:
            continue

        if d.Length > 0.000001:
            comprimento = d.Length
            d.normalize()
            direcoes.append(
                (comprimento, d)
            )

    return direcoes


def frame_face(xdir, normal):
    xdir = xdir - normal * xdir.dot(normal)

    if xdir.Length < 0.000001:
        raise Exception(
            "Nao consegui criar os eixos da face."
        )

    xdir.normalize()

    ydir = normal.cross(xdir)
    ydir.normalize()

    xdir = ydir.cross(normal)
    xdir.normalize()

    return App.Rotation(
        xdir,
        ydir,
        normal,
        "ZXY",
    )


# ============================================================
# FACE -> FACE
# ============================================================

def posicionar_face_face(
    doc,
    sel_origem,
    sel_destino,
):
    movel = objeto_movel(sel_origem.Object)

    if movel is None:
        raise Exception(
            "Nao encontrei uma peca movel com Placement."
        )

    movel_destino = objeto_movel(
        sel_destino.Object
    )

    if movel_destino == movel:
        raise Exception(
            "As duas faces pertencem a mesma peca movel."
        )

    face_origem = subelemento_global(sel_origem)
    face_destino = subelemento_global(sel_destino)

    canto_origem = canto_face(
        sel_origem,
        face_origem,
    )

    canto_destino = canto_face(
        sel_destino,
        face_destino,
    )

    normal_origem = normal_face_global(
        face_origem
    )

    normal_destino = normal_face_global(
        face_destino
    )

    normal_desejada = -normal_destino

    dirs_origem = direcoes_no_canto(
        face_origem,
        canto_origem,
    )

    dirs_destino = direcoes_no_canto(
        face_destino,
        canto_destino,
    )

    if not dirs_origem or not dirs_destino:
        raise Exception(
            "Nao consegui determinar as arestas das faces."
        )

    dirs_origem.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    x_origem = dirs_origem[0][1]

    rot_normal = App.Rotation(
        normal_origem,
        normal_desejada,
    )

    x_estimado = rot_normal.multVec(
        x_origem
    )

    melhor_dot = -1.0
    x_destino = None

    for comprimento, direcao in dirs_destino:
        valor = abs(
            x_estimado.dot(direcao)
        )

        if valor > melhor_dot:
            melhor_dot = valor
            x_destino = direcao

    if x_destino is None:
        raise Exception(
            "Nao consegui escolher a direcao da face de destino."
        )

    if x_estimado.dot(x_destino) < 0:
        x_destino = -x_destino

    frame_origem = frame_face(
        x_origem,
        normal_origem,
    )

    frame_destino = frame_face(
        x_destino,
        normal_desejada,
    )

    rot_delta = frame_destino.multiply(
        frame_origem.inverted()
    )

    pl_atual = placement_global(movel)

    rot_nova = rot_delta.multiply(
        pl_atual.Rotation
    )

    vetor_base = (
        pl_atual.Base - canto_origem
    )

    nova_base = (
        canto_destino
        + rot_delta.multVec(vetor_base)
    )

    pl_global_novo = App.Placement(
        nova_base,
        rot_nova,
    )

    App.Console.PrintMessage(
        "\n--- DIAGNOSTICO FACE COM FACE ---\n"
        "Origem: {}.{}\n"
        "Destino: {}.{}\n"
        "Objeto movel: {}\n"
        "Clique origem: {}\n"
        "Clique destino: {}\n"
        "Canto origem: {}\n"
        "Canto destino: {}\n"
        "Normal origem: {}\n"
        "Normal destino: {}\n"
        "Rotacao delta: {:.3f} graus\n"
        "----------------------------------\n".format(
            sel_origem.Object.Name,
            nome_subelemento(sel_origem),
            sel_destino.Object.Name,
            nome_subelemento(sel_destino),
            movel.Name,
            ponto_clicado(sel_origem),
            ponto_clicado(sel_destino),
            canto_origem,
            canto_destino,
            normal_origem,
            normal_destino,
            (
                rot_delta.Angle
                * 180.0
                / 3.141592653589793
            ),
        )
    )

    definir_placement_global(
        movel,
        pl_global_novo,
    )

    doc.recompute()

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(movel)

    tipo = (
        "App::Link"
        if eh_link(movel)
        else "Clone"
        if eh_clone(movel)
        else movel.TypeId
    )

    App.Console.PrintMessage(
        "\n"
        "====================================\n"
        "FACE COM FACE\n"
        "====================================\n"
        "Peca movida: {}\n"
        "Tipo: {}\n"
        "Rotacao automatica: SIM\n"
        "Normais: opostas\n"
        "Faces: coincidentes\n"
        "====================================\n".format(
            movel.Label,
            tipo,
        )
    )


# ============================================================
# PONTO -> PONTO
# ============================================================

def obter_ponto(sel):
    nome = nome_subelemento(sel)
    elemento = subelemento_global(sel)
    clique = ponto_clicado(sel)

    ultimo = nome.split(".")[-1]

    if ultimo.startswith("Vertex"):
        return elemento.Point

    if ultimo.startswith("Edge"):
        pontos = [
            v.Point
            for v in elemento.Vertexes
        ]

        if not pontos:
            return elemento.CenterOfMass

        if clique is None:
            return pontos[0]

        return min(
            pontos,
            key=lambda p: (p - clique).Length,
        )

    if ultimo.startswith("Face"):
        return canto_face(
            sel,
            elemento,
        )

    raise Exception(
        "Selecione face, aresta ou vertice."
    )


def posicionar_ponto_ponto(
    doc,
    sel_origem,
    sel_destino,
):
    movel = objeto_movel(
        sel_origem.Object
    )

    if movel is None:
        raise Exception(
            "Nao encontrei uma peca movel com Placement."
        )

    p1 = obter_ponto(sel_origem)
    p2 = obter_ponto(sel_destino)

    delta_global = p2 - p1

    pl_atual = placement_global(movel)

    pl_global_novo = App.Placement(
        pl_atual.Base + delta_global,
        pl_atual.Rotation,
    )

    definir_placement_global(
        movel,
        pl_global_novo,
    )

    doc.recompute()

    Gui.Selection.clearSelection()
    Gui.Selection.addSelection(movel)


# ============================================================
# COMANDO
# ============================================================

def run():
    doc = App.ActiveDocument

    if doc is None:
        App.Console.PrintError(
            "Nenhum documento aberto.\n"
        )
        return False

    selecoes = Gui.Selection.getSelectionEx()

    if len(selecoes) != 2:
        App.Console.PrintError(
            "\nSelecione duas referencias.\n"
            "1a = peca movel\n"
            "2a = destino\n"
        )
        return False

    if (
        len(selecoes[0].SubElementNames) != 1
        or len(selecoes[1].SubElementNames) != 1
    ):
        App.Console.PrintError(
            "Selecione uma geometria em cada peca.\n"
        )
        return False

    try:
        nome1 = (
            selecoes[0]
            .SubElementNames[0]
            .split(".")[-1]
        )

        nome2 = (
            selecoes[1]
            .SubElementNames[0]
            .split(".")[-1]
        )

        doc.openTransaction(
            "Posicionar peca"
        )

        try:
            if (
                nome1.startswith("Face")
                and nome2.startswith("Face")
            ):
                posicionar_face_face(
                    doc,
                    selecoes[0],
                    selecoes[1],
                )
            else:
                posicionar_ponto_ponto(
                    doc,
                    selecoes[0],
                    selecoes[1],
                )

            doc.commitTransaction()

        except Exception:
            try:
                doc.abortTransaction()
                doc.recompute()
            except Exception:
                pass
            raise

        return True

    except Exception as erro:
        App.Console.PrintError(
            "\nErro ao posicionar peca:\n"
            "{}\n\n".format(erro)
        )
        return False
