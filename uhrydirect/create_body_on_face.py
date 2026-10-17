# -*- coding: utf-8 -*-

import FreeCAD as App
import FreeCADGui as Gui

try:
    from PySide import QtWidgets
except Exception:
    from PySide2 import QtWidgets


TOL = 1e-7



def normalizar_selecoes(valor):
    """
    Achata listas/tuplas devolvidas por variantes de getSelectionEx().
    """
    saida = []

    def visitar(item):
        if isinstance(item, (list, tuple)):
            for sub in item:
                visitar(sub)
        elif item is not None:
            saida.append(item)

    visitar(valor)
    return saida


def encontrar_part_pai(obj):
    """
    Procura o App::Part mais próximo que contém o objeto selecionado.
    """
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


def placement_global(obj):
    """
    Retorna o Placement global do objeto.
    """
    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception:
        return App.Placement(obj.Placement)


def face_global_da_selecao(sel):
    """
    Obtém a face selecionada em coordenadas globais, inclusive quando
    o objeto está dentro de App::Part/containers.
    """
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
    umin, umax, vmin, vmax = face.ParameterRange
    u = (umin + umax) / 2.0
    v = (vmin + vmax) / 2.0

    normal = face.normalAt(u, v)

    if normal.Length < TOL:
        raise RuntimeError(
            "Não consegui determinar a normal da face."
        )

    normal.normalize()
    return normal


def direcoes_retas_da_face(face, normal):
    """
    Extrai direções das arestas da própria face.

    Isso é o ponto principal da correção: o XY do novo Body/Sketch é
    construído a partir da geometria selecionada, e não a partir de
    X/Y/Z globais.
    """
    candidatos = []

    for edge in face.Edges:
        verts = edge.Vertexes

        if len(verts) < 2:
            continue

        p1 = verts[0].Point
        p2 = verts[-1].Point
        d = p2 - p1

        # Projeta no plano da face para evitar pequeno erro numérico.
        d = d - normal * d.dot(normal)

        if d.Length < TOL:
            continue

        comprimento = d.Length
        d.normalize()

        # Elimina direções paralelas repetidas.
        repetida = False
        for _, existente in candidatos:
            if abs(abs(d.dot(existente)) - 1.0) < 1e-5:
                repetida = True
                break

        if not repetida:
            candidatos.append((comprimento, d))

    candidatos.sort(
        key=lambda item: item[0],
        reverse=True,
    )

    return candidatos


def _vetor_camera(rot, vetor_local):
    """
    Converte um eixo local da câmera para coordenadas globais.
    """
    try:
        return rot.multVec(vetor_local)
    except Exception:
        return App.Rotation(rot).multVec(vetor_local)


def eixos_da_vista_na_face(normal):
    """
    Cria X/Y da face a partir da ORIENTAÇÃO VISUAL atual.

    Objetivo:
    - o que está à direita na tela vira +X do Sketch;
    - o que está para cima na tela vira +Y do Sketch;
    - portanto, ao entrar no Sketcher, direita continua direita
      e baixo continua baixo.

    A normal é orientada para o lado da câmera para manter a mesma leitura
    visual da face selecionada.
    """
    view = Gui.activeDocument().activeView()
    cam_rot = view.getCameraOrientation()

    direita_tela = _vetor_camera(
        cam_rot,
        App.Vector(1, 0, 0),
    )

    cima_tela = _vetor_camera(
        cam_rot,
        App.Vector(0, 1, 0),
    )

    direcao_visao = _vetor_camera(
        cam_rot,
        App.Vector(0, 0, -1),
    )

    for vetor in (direita_tela, cima_tela, direcao_visao):
        if vetor.Length > TOL:
            vetor.normalize()

    zdir = App.Vector(normal)
    zdir.normalize()

    # A câmera olha na direção "direcao_visao".
    # Para o Sketch ser visto do mesmo lado da face, +Z deve apontar
    # aproximadamente em direção à câmera, isto é, contra a direção da visão.
    if zdir.dot(direcao_visao) > 0:
        zdir = -zdir

    # Primeiro tenta manter exatamente a noção de "direita" da tela.
    xdir = (
        direita_tela
        - zdir * direita_tela.dot(zdir)
    )

    if xdir.Length >= TOL:
        xdir.normalize()
        ydir = zdir.cross(xdir)

        if ydir.Length < TOL:
            raise RuntimeError(
                "Não consegui determinar o eixo Y pela orientação da vista."
            )

        ydir.normalize()

    else:
        # Caso raro: a direita da câmera está quase paralela à normal.
        # Então preservamos "para cima" e deduzimos X.
        ydir = (
            cima_tela
            - zdir * cima_tela.dot(zdir)
        )

        if ydir.Length < TOL:
            raise RuntimeError(
                "A vista atual está degenerada para esta face."
            )

        ydir.normalize()
        xdir = ydir.cross(zdir)
        xdir.normalize()

    # Pequena correção numérica e garantia de leitura visual.
    xdir = xdir - zdir * xdir.dot(zdir)
    xdir.normalize()

    ydir = zdir.cross(xdir)
    ydir.normalize()

    # Normalmente isso já é positivo. Se alguma orientação de câmera especial
    # produzir Y invertido, invertemos Z e recalculamos Y mantendo X à direita.
    if ydir.dot(cima_tela) < 0:
        zdir = -zdir
        ydir = zdir.cross(xdir)
        ydir.normalize()

    return xdir, ydir, zdir, direita_tela, cima_tela


def frame_local_da_face(face):
    """
    Cria o frame do novo Body usando a vista atual do usuário.

    Assim:
    - direita na tela -> +X do Sketch;
    - cima na tela -> +Y do Sketch;
    - canto visual inferior esquerdo -> origem do Sketch.

    A orientação NÃO depende dos eixos globais e também NÃO escolhe
    arbitrariamente a maior aresta da face.
    """
    normal = normal_face(face)

    (
        xdir,
        ydir,
        zdir,
        direita_tela,
        cima_tela,
    ) = eixos_da_vista_na_face(normal)

    vertices = [v.Point for v in face.Vertexes]

    if not vertices:
        origem = face.CenterOfMass
    else:
        ref = vertices[0]
        coords = []

        for p in vertices:
            rel = p - ref
            coords.append(
                (
                    p,
                    rel.dot(xdir),
                    rel.dot(ydir),
                )
            )

        xmin = min(item[1] for item in coords)
        ymin = min(item[2] for item in coords)

        origem = min(
            coords,
            key=lambda item: (
                (item[1] - xmin) ** 2
                + (item[2] - ymin) ** 2
            ),
        )[0]

    rot_global = App.Rotation(
        xdir,
        ydir,
        zdir,
        "ZXY",
    )

    return (
        App.Placement(origem, rot_global),
        xdir,
        ydir,
        zdir,
        direita_tela,
        cima_tela,
    )

def run():
    doc = App.ActiveDocument

    if doc is None:
        App.Console.PrintError(
            "Nenhum documento aberto.\n"
        )
        return False

    sel = normalizar_selecoes(Gui.Selection.getSelectionEx())

    if len(sel) != 1:
        App.Console.PrintError(
            "Selecione exatamente UMA face plana.\n"
        )
        return False

    if len(sel[0].SubElementNames) != 1:
        App.Console.PrintError(
            "Selecione exatamente UMA face.\n"
        )
        return False

    if not sel[0].SubElementNames[0].split(".")[-1].startswith("Face"):
        App.Console.PrintError(
            "A seleção precisa ser uma FACE.\n"
        )
        return False

    try:
        obj_ref = sel[0].Object
        nome_face = sel[0].SubElementNames[0]

        # A face já vem transformada para o mundo.
        face_global = face_global_da_selecao(sel[0])

        (
            placement_desejado,
            xdir,
            ydir,
            normal,
            direita_tela,
            cima_tela,
        ) = frame_local_da_face(
            face_global
        )

        nome, ok = QtWidgets.QInputDialog.getText(
            None,
            "Novo Body",
            "Nome da peça:",
            text="Nova_Peca",
        )

        if not ok:
            App.Console.PrintMessage(
                "Criação cancelada.\n"
            )
            return False

        nome = nome.strip() or "Nova_Peca"

        doc.openTransaction(
            "Direct - Criar Body na Face"
        )

        try:
            body = doc.addObject(
                "PartDesign::Body",
                "Body",
            )
            body.Label = nome

            part_pai = encontrar_part_pai(obj_ref)

            if part_pai is not None:
                part_pai.addObject(body)

                pl_part_global = placement_global(part_pai)
                body.Placement = (
                    pl_part_global.inverse()
                    * placement_desejado
                )
            else:
                body.Placement = placement_desejado

            sketch = body.newObject(
                "Sketcher::SketchObject",
                "Sketch",
            )
            sketch.Label = "Sketch"
            sketch.MapMode = "Deactivated"

            # Como o Body já está exatamente no frame da face,
            # o Sketch nasce na origem XY LOCAL do Body.
            sketch.Placement = App.Placement()

            # Este comando SEMPRE inicia uma nova peça/novo Body.

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
            "=================================\n"
            "NOVO BODY CRIADO\n"
            "=================================\n"
            "Nome: {}\n"
            "Origem global: {}\n"
            "Plano: face selecionada\n"
            "Zero: canto inferior esquerdo LOCAL da face\n"
            "Orientação: vista atual projetada na face\n"
            "X local: {}\n"
            "Y local: {}\n"
            "Normal local Z: {}\n"
            "Referência: independente\n"
            "=================================\n".format(
                body.Label,
                placement_desejado.Base,
                xdir,
                ydir,
                normal,
                direita_tela,
                cima_tela,
            )
        )

        return True

    except Exception as erro:
        App.Console.PrintError(
            "Erro ao criar nova peça: {}\n".format(erro)
        )
        return False
