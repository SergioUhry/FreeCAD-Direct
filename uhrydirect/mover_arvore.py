# -*- coding: utf-8 -*-
"""Reorganiza objetos na árvore do FreeCAD preservando o Placement global.

Com um objeto selecionado, move-o para a raiz. Com dois objetos selecionados,
o primeiro é movido para o contêiner indicado pelo segundo. Features internas
de PartDesign::Body são protegidas contra movimentação isolada.
"""

import math
import FreeCAD as App
import FreeCADGui as Gui


TOL_POS_MM = 0.001
TOL_ROT_GRAUS = 0.001


# ============================================================
# PLACEMENT
# ============================================================

def possui_placement(obj):
    return hasattr(obj, "Placement")


def placement_global(obj):
    """
    Retorna o Placement global real.

    Não usa fallback silencioso para Placement local.
    """
    if not possui_placement(obj):
        return None

    try:
        return App.Placement(obj.getGlobalPlacement())
    except Exception as e:
        raise RuntimeError(
            "Não foi possível obter o Placement global de '{}': {}".format(
                obj.Label, e
            )
        )


def placement_local(obj):
    if not possui_placement(obj):
        return None

    try:
        return App.Placement(obj.Placement)
    except Exception as e:
        raise RuntimeError(
            "Não foi possível obter o Placement local de '{}': {}".format(
                obj.Label, e
            )
        )


def restaurar_global(objeto, global_antes):
    """
    Depois que o próprio FreeCAD faz a troca de contêiner,
    descobre qual referencial geométrico realmente passou a atuar:

        referencial = global_atual * local_atual.inverse()

    Então recupera a posição global anterior:

        local_novo = referencial.inverse() * global_antes
    """
    if global_antes is None or not possui_placement(objeto):
        return

    global_atual = placement_global(objeto)
    local_atual = placement_local(objeto)

    referencial = global_atual * local_atual.inverse()
    objeto.Placement = referencial.inverse() * global_antes


def diferenca_posicao(a, b):
    return (a.Base - b.Base).Length


def diferenca_rotacao(a, b):
    q1 = [float(v) for v in a.Rotation.Q]
    q2 = [float(v) for v in b.Rotation.Q]

    n1 = math.sqrt(sum(v * v for v in q1))
    n2 = math.sqrt(sum(v * v for v in q2))

    if n1 <= 1e-15 or n2 <= 1e-15:
        return float("inf")

    q1 = [v / n1 for v in q1]
    q2 = [v / n2 for v in q2]

    dot = abs(sum(a_ * b_ for a_, b_ in zip(q1, q2)))
    dot = max(-1.0, min(1.0, dot))

    return math.degrees(2.0 * math.acos(dot))


def validar_global(objeto, global_antes):
    if global_antes is None or not possui_placement(objeto):
        return 0.0, 0.0

    global_depois = placement_global(objeto)

    dp = diferenca_posicao(global_antes, global_depois)
    dr = diferenca_rotacao(global_antes, global_depois)

    if dp > TOL_POS_MM or dr > TOL_ROT_GRAUS:
        raise RuntimeError(
            "A posição global não foi preservada. "
            "Diferença: {:.6f} mm / {:.6f}°.".format(dp, dr)
        )

    return dp, dr


# ============================================================
# ÁRVORE / CONTÊINERES
# ============================================================

def contem_objeto(container, obj):
    try:
        return obj in list(container.Group)
    except Exception:
        return False


def pais_diretos(obj):
    """
    Procura contêineres diretos reais.

    Não considera qualquer InList como pai, pois InList também pode conter
    vínculos que não representam contenção na árvore.
    """
    pais = []

    try:
        pai = obj.getParentGeoFeatureGroup()
        if pai is not None:
            pais.append(pai)
    except Exception:
        pass

    for candidato in getattr(obj, "InList", []):
        if contem_objeto(candidato, obj) and candidato not in pais:
            pais.append(candidato)

    return pais


def pai_direto(obj):
    pais = pais_diretos(obj)
    return pais[0] if pais else None


def filhos_diretos(obj):
    try:
        return list(obj.Group)
    except Exception:
        return []


def eh_descendente(destino, objeto):
    """
    Verifica se destino já está dentro da árvore de objeto,
    evitando criar hierarquia circular.
    """
    visitados = set()
    fila = list(filhos_diretos(objeto))

    while fila:
        atual = fila.pop(0)

        if atual is destino:
            return True

        chave = getattr(atual, "Name", str(id(atual)))
        if chave in visitados:
            continue

        visitados.add(chave)
        fila.extend(filhos_diretos(atual))

    return False


def pode_receber_objetos(destino):
    return callable(getattr(destino, "addObject", None))


def esta_no_destino(objeto, destino):
    if contem_objeto(destino, objeto):
        return True

    try:
        if objeto.getParentGeoFeatureGroup() is destino:
            return True
    except Exception:
        pass

    return False


def remover_do_container(container, objeto):
    if not contem_objeto(container, objeto):
        return

    remover = getattr(container, "removeObject", None)

    if not callable(remover):
        raise RuntimeError(
            "O contêiner '{}' não permite remover objetos.".format(
                container.Label
            )
        )

    remover(objeto)


# ============================================================
# CASOS ESPECIAIS PART DESIGN
# ============================================================

def body_pai_direto(objeto):
    for pai in pais_diretos(objeto):
        if getattr(pai, "TypeId", "") == "PartDesign::Body":
            return pai
    return None


def validar_partdesign(objeto, destino=None):
    """
    Mover um Body inteiro é permitido.

    Feature individual dentro de Body é bloqueada porque Body altera Tip,
    ordem, Origin e dependências internas.
    """
    body_origem = body_pai_direto(objeto)

    if body_origem is not None and objeto.TypeId != "PartDesign::Body":
        raise RuntimeError(
            "'{}' é uma feature interna do Body '{}'. "
            "Para não quebrar Tip/dependências, esta macro move o Body inteiro, "
            "não features individuais.".format(
                objeto.Label, body_origem.Label
            )
        )

    if destino is not None and destino.TypeId == "PartDesign::Body":
        raise RuntimeError(
            "Mover genericamente um objeto para dentro de PartDesign::Body "
            "não é seguro. Use uma operação específica do Part Design."
        )


# ============================================================
# MOVER PARA OUTRO CONTÊINER
# ============================================================

def mover_para_destino(objeto, destino, doc):
    if objeto is destino:
        raise ValueError("O objeto e o destino não podem ser o mesmo.")

    if objeto.Document is not destino.Document:
        raise ValueError(
            "Objeto e destino precisam estar no mesmo documento."
        )

    if eh_descendente(destino, objeto):
        raise ValueError(
            "Não é possível mover um objeto para dentro de um descendente dele."
        )

    if not pode_receber_objetos(destino):
        raise ValueError(
            "'{}' não aceita objetos filhos na árvore do FreeCAD.".format(
                destino.Label
            )
        )

    validar_partdesign(objeto, destino)

    global_antes = placement_global(objeto)
    pais_anteriores = pais_diretos(objeto)

    destino.addObject(objeto)
    doc.recompute()

    # Alguns containers removem automaticamente o objeto do pai anterior.
    # Se ainda permanecer no grupo anterior, removemos explicitamente.
    for pai in pais_anteriores:
        if pai is destino:
            continue

        if contem_objeto(pai, objeto):
            remover_do_container(pai, objeto)

    doc.recompute()

    if not esta_no_destino(objeto, destino):
        raise RuntimeError(
            "O FreeCAD não confirmou '{}' como filho de '{}'.".format(
                objeto.Label, destino.Label
            )
        )

    # Não presume que o destino selecionado seja o referencial geométrico real.
    restaurar_global(objeto, global_antes)
    doc.recompute()

    dp, dr = validar_global(objeto, global_antes)

    return pais_anteriores, dp, dr


# ============================================================
# DEVOLVER PARA A RAIZ
# ============================================================

def devolver_para_raiz(objeto, doc):
    validar_partdesign(objeto)

    global_antes = placement_global(objeto)
    pais = pais_diretos(objeto)

    if not pais:
        raise ValueError(
            "O objeto selecionado já está solto na raiz da árvore."
        )

    for pai in list(pais):
        remover_do_container(pai, objeto)

    doc.recompute()

    # Na raiz o Placement do objeto passa a representar o global.
    if global_antes is not None and possui_placement(objeto):
        objeto.Placement = global_antes

    doc.recompute()

    restantes = pais_diretos(objeto)
    if restantes:
        raise RuntimeError(
            "O objeto ainda possui contêiner direto: {}.".format(
                ", ".join(p.Label for p in restantes)
            )
        )

    dp, dr = validar_global(objeto, global_antes)

    return pais, dp, dr


# ============================================================
# EXECUÇÃO
# ============================================================

doc = App.ActiveDocument

if doc is None:
    App.Console.PrintError(
        "Abra um documento antes de usar Mover Objeto.\n"
    )

else:
    sel = Gui.Selection.getSelection()

    if len(sel) == 1:
        objeto = sel[0]

        try:
            doc.openTransaction("Mover Objeto - para raiz")

            pais, dp, dr = devolver_para_raiz(objeto, doc)

            doc.commitTransaction()

            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(objeto)

            App.Console.PrintMessage(
                "{} devolvido para a raiz. "
                "Δpos={:.6f} mm | Δrot={:.6f}°\n".format(
                    objeto.Label, dp, dr
                )
            )

        except Exception as e:
            try:
                doc.abortTransaction()
                doc.recompute()
            except Exception:
                pass

            App.Console.PrintError(
                "Mover Objeto cancelado: {}\n".format(e)
            )

    elif len(sel) == 2:
        objeto = sel[0]
        destino = sel[1]

        try:
            doc.openTransaction("Mover Objeto")

            pais, dp, dr = mover_para_destino(
                objeto, destino, doc
            )

            doc.commitTransaction()

            Gui.Selection.clearSelection()
            Gui.Selection.addSelection(objeto)

            App.Console.PrintMessage(
                "{} movido para {}. "
                "Δpos={:.6f} mm | Δrot={:.6f}°\n".format(
                    objeto.Label, destino.Label, dp, dr
                )
            )

        except Exception as e:
            try:
                doc.abortTransaction()
                doc.recompute()
            except Exception:
                pass

            App.Console.PrintError(
                "Mover Objeto cancelado: {}\n".format(e)
            )

    else:
        App.Console.PrintError(
            "\nMover Objeto — árvore:\n"
            "• 1 seleção: devolve o objeto para a raiz.\n"
            "• 2 seleções: primeiro o objeto; depois o contêiner de destino.\n"
        )
