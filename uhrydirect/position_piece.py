# -*- coding: utf-8 -*-

# Posicionar Peça Direct 1.3

# Face→Face, Ponto→Ponto, Clone/Link e Linhas Guia→Plano de Face

#

# Novo na 1.3:

# - Linhas Guia sao projetadas para o plano da face pela DIRECAO DA VISTA ATUAL;

# - o centro da guia permanece no mesmo ponto visual da tela em vista ortografica;

# - em vista Frente/Tras, por exemplo, isso equivale a alterar somente a profundidade;

# - leitura da geometria global da guia refeita para evitar dupla aplicacao de Placement.

#

# Base da 1.2:

# - Linhas Guia -> Face usa o CENTRO geometrico da guia como referencia;

# - a guia e transladada somente pela normal da face;

# - o centro conserva exatamente as coordenadas tangentes ao plano;

# - se a guia nao for paralela ao plano da face, a operacao e bloqueada

#   para evitar deslocamento/resultado inesperado.

import FreeCAD as App

import FreeCADGui as Gui

import Part

doc = None

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

        return obj.getGlobalPlacement()

    except Exception:

        return obj.Placement

def definir_placement_global(obj, novo_global):

    """Converte o Placement global para o sistema local do App::Part pai."""

    part_pai = encontrar_part_pai(obj)

    if part_pai is None:

        obj.Placement = novo_global

    else:

        obj.Placement = placement_global(part_pai).inverse() * novo_global

# ============================================================

# GEOMETRIA SELECIONADA EM COORDENADAS GLOBAIS

# ============================================================

def nome_subelemento(sel):

    if len(sel.SubElementNames) != 1:

        raise Exception("Selecione exatamente uma geometria em cada peça.")

    return sel.SubElementNames[0]

def subelemento_global(sel):

    """

    Pede ao FreeCAD o subelemento ja transformado.

    Isto e importante para Draft Clone, App::Link e objetos dentro de

    App::Part. Evita aplicar o Placement duas vezes.

    """

    nome = nome_subelemento(sel)

    # A selecao grafica entrega a geometria com o Placement do proprio objeto,

    # mas pode omitir os Placements dos pais (Body e App::Part). Aplicamos

    # somente a transformacao dos pais para nao duplicar o Placement interno

    # de um Part Design Clone.

    try:

        if len(sel.SubObjects) == 1 and sel.SubObjects[0] is not None:

            elemento = sel.SubObjects[0].copy()

            pl_global_obj = placement_global(sel.Object)

            pl_local_obj = sel.Object.Placement

            pl_pais = pl_global_obj * pl_local_obj.inverse()

            elemento.Placement = pl_pais * elemento.Placement

            return elemento

    except Exception:

        pass

    try:

        elemento = sel.Object.getSubObject(nome, 1, True)

        if elemento is not None:

            return elemento

    except Exception:

        pass

    # Compatibilidade com objetos simples/versoes que nao resolvam acima.

    elemento = sel.Object.Shape.getElement(nome).copy()

    elemento.Placement = placement_global(sel.Object) * elemento.Placement

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

    return min(pontos, key=lambda p: (p - clique).Length)

def normal_face_global(face_global):

    umin, umax, vmin, vmax = face_global.ParameterRange

    u = (umin + umax) / 2.0

    v = (vmin + vmax) / 2.0

    normal = face_global.normalAt(u, v)

    if normal.Length < 0.000001:

        raise Exception("Nao consegui determinar a normal da face.")

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

            direcoes.append((comprimento, d))

    return direcoes

def frame_face(xdir, normal):

    xdir = xdir - normal * xdir.dot(normal)

    if xdir.Length < 0.000001:

        raise Exception("Nao consegui criar os eixos da face.")

    xdir.normalize()

    ydir = normal.cross(xdir)

    ydir.normalize()

    xdir = ydir.cross(normal)

    xdir.normalize()

    return App.Rotation(xdir, ydir, normal, "ZXY")

# ============================================================

# FACE -> FACE

# ============================================================

def posicionar_face_face(sel_origem, sel_destino):

    movel = objeto_movel(sel_origem.Object)

    if movel is None:

        raise Exception("Nao encontrei uma peca movel com Placement.")

    movel_destino = objeto_movel(sel_destino.Object)

    if movel_destino == movel:

        raise Exception("As duas faces pertencem a mesma peca movel.")

    face_origem = subelemento_global(sel_origem)

    face_destino = subelemento_global(sel_destino)

    canto_origem = canto_face(sel_origem, face_origem)

    canto_destino = canto_face(sel_destino, face_destino)

    normal_origem = normal_face_global(face_origem)

    normal_destino = normal_face_global(face_destino)

    normal_desejada = -normal_destino

    dirs_origem = direcoes_no_canto(face_origem, canto_origem)

    dirs_destino = direcoes_no_canto(face_destino, canto_destino)

    if not dirs_origem or not dirs_destino:

        raise Exception("Nao consegui determinar as arestas das faces.")

    dirs_origem.sort(key=lambda item: item[0], reverse=True)

    x_origem = dirs_origem[0][1]

    rot_normal = App.Rotation(normal_origem, normal_desejada)

    x_estimado = rot_normal.multVec(x_origem)

    melhor_dot = -1.0

    x_destino = None

    for comprimento, direcao in dirs_destino:

        valor = abs(x_estimado.dot(direcao))

        if valor > melhor_dot:

            melhor_dot = valor

            x_destino = direcao

    if x_destino is None:

        raise Exception("Nao consegui escolher a direcao da face de destino.")

    if x_estimado.dot(x_destino) < 0:

        x_destino = -x_destino

    frame_origem = frame_face(x_origem, normal_origem)

    frame_destino = frame_face(x_destino, normal_desejada)

    rot_delta = frame_destino.multiply(frame_origem.inverted())

    pl_atual = placement_global(movel)

    rot_nova = rot_delta.multiply(pl_atual.Rotation)

    vetor_base = pl_atual.Base - canto_origem

    nova_base = canto_destino + rot_delta.multVec(vetor_base)

    pl_global_novo = App.Placement(nova_base, rot_nova)

    App.Console.PrintMessage(

        "\n--- DIAGNOSTICO FACE COM FACE ---\n"

        f"Origem: {sel_origem.Object.Name}.{nome_subelemento(sel_origem)}\n"

        f"Destino: {sel_destino.Object.Name}.{nome_subelemento(sel_destino)}\n"

        f"Objeto movel: {movel.Name}\n"

        f"Clique origem: {ponto_clicado(sel_origem)}\n"

        f"Clique destino: {ponto_clicado(sel_destino)}\n"

        f"Canto origem: {canto_origem}\n"

        f"Canto destino: {canto_destino}\n"

        f"Normal origem: {normal_origem}\n"

        f"Normal destino: {normal_destino}\n"

        f"Rotacao delta: {rot_delta.Angle * 180.0 / 3.141592653589793:.3f} graus\n"

        "----------------------------------\n"

    )

    definir_placement_global(movel, pl_global_novo)

    doc.recompute()

    Gui.Selection.clearSelection()

    Gui.Selection.addSelection(movel)

    tipo = "App::Link" if eh_link(movel) else "Clone" if eh_clone(movel) else movel.TypeId

    App.Console.PrintMessage(

        "\n"

        "====================================\n"

        "FACE COM FACE\n"

        "====================================\n"

        f"Peca movida: {movel.Label}\n"

        f"Tipo: {tipo}\n"

        "Rotacao automatica: SIM\n"

        "Normais: opostas\n"

        "Faces: coincidentes\n"

        "====================================\n"

    )

# ============================================================

# PONTO -> PONTO

# ============================================================

def obter_ponto(sel):

    nome = nome_subelemento(sel)

    elemento = subelemento_global(sel)

    clique = ponto_clicado(sel)

    if nome.split(".")[-1].startswith("Vertex"):

        return elemento.Point

    if nome.split(".")[-1].startswith("Edge"):

        pontos = [v.Point for v in elemento.Vertexes]

        if not pontos:

            return elemento.CenterOfMass

        if clique is None:

            return pontos[0]

        return min(pontos, key=lambda p: (p - clique).Length)

    if nome.split(".")[-1].startswith("Face"):

        return canto_face(sel, elemento)

    raise Exception("Selecione face, aresta ou vertice.")

def posicionar_ponto_ponto(sel_origem, sel_destino):

    movel = objeto_movel(sel_origem.Object)

    if movel is None:

        raise Exception("Nao encontrei uma peca movel com Placement.")

    p1 = obter_ponto(sel_origem)

    p2 = obter_ponto(sel_destino)

    delta_global = p2 - p1

    pl_atual = placement_global(movel)

    pl_global_novo = App.Placement(

        pl_atual.Base + delta_global,

        pl_atual.Rotation

    )

    definir_placement_global(movel, pl_global_novo)

    doc.recompute()

    Gui.Selection.clearSelection()

    Gui.Selection.addSelection(movel)

# ============================================================

# LINHAS GUIA -> PLANO DE UMA FACE

# ============================================================

GUIDE_FLAG = "UhryGuiaReferencia"
DIRECT_GUIDE_FLAG = "DirectGuiaReferencia"

def eh_linha_guia(obj):
    """Reconhece Linhas Guia atuais e documentos antigos."""
    if obj is None:
        return False

    try:
        props = getattr(obj, "PropertiesList", [])
        if DIRECT_GUIDE_FLAG in props and bool(getattr(obj, DIRECT_GUIDE_FLAG, False)):
            return True
        if GUIDE_FLAG in props and bool(getattr(obj, GUIDE_FLAG, False)):
            return True
    except Exception:
        pass

    return str(getattr(obj, "Name", "")).startswith(("UhryGuia", "DirectGuia"))

def selecao_e_face(sel):

    """True quando a selecao contem exatamente uma Face."""

    try:

        if len(sel.SubElementNames) != 1:

            return False

        return sel.SubElementNames[0].split(".")[-1].startswith("Face")

    except Exception:

        return False

def shape_global_objeto(obj):

    """

    Retorna a Shape do objeto em coordenadas globais.

    IMPORTANTE:

    tenta primeiro Part.getShape(..., transform=True), que ja resolve Placement

    do objeto e de conteineres. Isso evita aplicar Placement duas vezes.

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

    if not hasattr(obj, "Shape") or obj.Shape is None or obj.Shape.isNull():

        raise Exception(f"{obj.Label}: a linha guia nao possui geometria valida.")

    return obj.Shape.copy()

def dados_centro_guia(sel):

    """

    Retorna centro geometrico e direcao GLOBAL da Linha Guia selecionada.

    Quando a guia foi clicada no 3D, usa o subelemento da propria selecao,

    que representa a geometria visual realmente clicada.

    """

    obj = sel.Object

    edge = None

    try:

        if (

            len(sel.SubElementNames) == 1

            and sel.SubElementNames[0].split(".")[-1].startswith("Edge")

        ):

            elemento = subelemento_global(sel)

            if getattr(elemento, "ShapeType", "") == "Edge":

                edge = elemento

    except Exception:

        edge = None

    if edge is None:

        shape = shape_global_objeto(obj)

        if getattr(shape, "ShapeType", "") == "Edge":

            edge = shape

        elif getattr(shape, "Edges", None):

            edge = shape.Edges[0]

    if edge is None:

        raise Exception(f"{obj.Label}: a Linha Guia nao possui uma aresta valida.")

    verts = edge.Vertexes

    if len(verts) >= 2:

        p1 = App.Vector(verts[0].Point)

        p2 = App.Vector(verts[-1].Point)

    else:

        try:

            fp = edge.FirstParameter

            lp = edge.LastParameter

            p1 = App.Vector(edge.valueAt(fp))

            p2 = App.Vector(edge.valueAt(lp))

        except Exception:

            raise Exception(

                f"{obj.Label}: nao consegui determinar centro/direcao da Linha Guia."

            )

    direcao = p2 - p1

    if direcao.Length < 0.000001:

        raise Exception(f"{obj.Label}: a Linha Guia possui comprimento nulo.")

    centro = (p1 + p2) * 0.5

    direcao.normalize()

    return centro, direcao

def direcao_da_vista():

    """Retorna a direcao em que a camera olha para o modelo."""

    try:

        rot = Gui.activeDocument().activeView().getCameraOrientation()

        direcao = rot.multVec(App.Vector(0, 0, -1))

    except Exception as exc:

        raise Exception(f"Nao consegui obter a direcao da vista atual: {exc}")

    if direcao.Length < 0.000001:

        raise Exception("A direcao da vista atual e invalida.")

    direcao.normalize()

    return direcao

def plano_da_face(sel_face):

    """Retorna ponto e normal global de uma face plana."""

    face = subelemento_global(sel_face)

    if getattr(face, "ShapeType", "") != "Face":

        raise Exception("O destino precisa ser uma face.")

    # A operacao foi projetada para faces planas.

    try:

        if not isinstance(face.Surface, Part.Plane):

            raise Exception("A face de destino precisa ser plana.")

    except TypeError:

        # Algumas builds Python do OCC nao expõem isinstance de forma confiavel.

        pass

    umin, umax, vmin, vmax = face.ParameterRange

    u = (umin + umax) * 0.5

    v = (vmin + vmax) * 0.5

    ponto = App.Vector(face.valueAt(u, v))

    normal = App.Vector(face.normalAt(u, v))

    if normal.Length < 0.000001:

        raise Exception("Nao consegui determinar a normal da face de destino.")

    normal.normalize()

    return ponto, normal

def mover_guias_para_plano(selecoes_guias, sel_face):

    """

    Move uma ou varias Linhas Guia para o plano da face pela DIRECAO DA VISTA.

    Resultado pratico:

    - o centro da guia permanece no mesmo ponto visual da tela;

    - em Frente/Tras, por exemplo, muda apenas a profundidade;

    - nao ha salto lateral causado pela projecao isometrica.

    A linha precisa ser paralela ao plano da face para que uma translacao pura

    consiga colocar a linha inteira no plano sem girar.

    """

    ponto_plano, normal = plano_da_face(sel_face)

    view_dir = direcao_da_vista()

    denom = view_dir.dot(normal)

    if abs(denom) < 0.000001:

        raise Exception(

            "A vista atual esta praticamente paralela ao plano da face.\n"

            "Gire para enxergar a face e execute novamente."

        )

    movidas = []

    for sel in selecoes_guias:

        guia = sel.Object

        if not eh_linha_guia(guia):

            raise Exception(f"{guia.Label}: o objeto nao e uma Linha Guia.")

        centro_guia, direcao_guia = dados_centro_guia(sel)

        componente_normal = abs(direcao_guia.dot(normal))

        if componente_normal > 0.00001:

            raise Exception(

                f"{guia.Label}: a Linha Guia nao e paralela ao plano da face.\n"

                "Para colocar a linha inteira no plano sem girar,\n"

                "use uma guia paralela a essa face."

            )

        # Intersecao da reta (centro + t * direcao_da_vista) com o plano.

        t = (ponto_plano - centro_guia).dot(normal) / denom

        centro_destino = centro_guia + (view_dir * t)

        delta = centro_destino - centro_guia

        pl_atual = placement_global(guia)

        pl_novo = App.Placement(pl_atual.Base + delta, pl_atual.Rotation)

        definir_placement_global(guia, pl_novo)

        movidas.append((guia, centro_guia, centro_destino, delta))

    doc.recompute()

    Gui.Selection.clearSelection()

    for guia, _, _, _ in movidas:

        Gui.Selection.addSelection(guia)

    App.Console.PrintMessage(

        "\n====================================\n"

        "LINHAS GUIA -> PLANO DA FACE\n"

        "====================================\n"

        f"Guias movidas: {len(movidas)}\n"

        "Referencia: centro geometrico projetado pela vista atual.\n"

    )

    for guia, centro_antes, centro_depois, delta in movidas:

        App.Console.PrintMessage(

            f"- {guia.Label}\n"

            f"  centro antes:  ({centro_antes.x:.3f}, {centro_antes.y:.3f}, {centro_antes.z:.3f})\n"

            f"  centro depois: ({centro_depois.x:.3f}, {centro_depois.y:.3f}, {centro_depois.z:.3f})\n"

            f"  delta global:  ({delta.x:+.3f}, {delta.y:+.3f}, {delta.z:+.3f}) mm\n"

        )

    App.Console.PrintMessage(

        "O centro permanece na mesma posicao VISUAL em vista ortografica.\n"

        "====================================\n"

    )

def run():
    global doc
    doc = App.ActiveDocument

    if doc is None:
        App.Console.PrintError("Nenhum documento aberto.\n")
        return False

    selecoes = Gui.Selection.getSelectionEx()

    try:
        modo_guias = (
            len(selecoes) >= 2
            and selecao_e_face(selecoes[-1])
            and all(eh_linha_guia(sel.Object) for sel in selecoes[:-1])
        )

        if modo_guias:
            doc.openTransaction("Posicionar linhas guia no plano da face")
            try:
                mover_guias_para_plano(selecoes[:-1], selecoes[-1])
                doc.commitTransaction()
            except Exception:
                doc.abortTransaction()
                doc.recompute()
                raise
        else:
            if len(selecoes) != 2:
                raise Exception(
                    "Selecione:\n"
                    "- uma ou varias Linhas Guia e, por ultimo, uma face; OU\n"
                    "- duas referencias para o posicionamento tradicional."
                )

            if (
                len(selecoes[0].SubElementNames) != 1
                or len(selecoes[1].SubElementNames) != 1
            ):
                raise Exception("Selecione uma geometria em cada peca.")

            nome1 = selecoes[0].SubElementNames[0].split(".")[-1]
            nome2 = selecoes[1].SubElementNames[0].split(".")[-1]

            doc.openTransaction("Posicionar peca")
            try:
                if nome1.startswith("Face") and nome2.startswith("Face"):
                    posicionar_face_face(selecoes[0], selecoes[1])
                else:
                    posicionar_ponto_ponto(selecoes[0], selecoes[1])
                doc.commitTransaction()
            except Exception:
                doc.abortTransaction()
                doc.recompute()
                raise

        return True

    except Exception as erro:
        App.Console.PrintError(
            "\nErro ao posicionar peca:\n"
            f"{erro}\n\n"
        )
        return False
